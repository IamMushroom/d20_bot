# ADR-001: Identity кампании и Telegram binding

- Статус: Accepted
- Дата: 2026-08-16
- Принято после архитектурного ревью: 2026-08-27
- Задача: `ARCH-013`
- Решение относится только к будущей миграции; production schema и API этим ADR не меняются.

## Контекст

Сейчас внутренняя identity кампании фактически смешана с Telegram identity:

- `campaigns.chat_id` имеет `NOT NULL UNIQUE`, а `Campaign` содержит `chat_id`;
- `CampaignRepository` создаёт и находит кампанию по `chat_id`;
- `CampaignService`, `SessionService` и `GameWorkflowService` принимают `chat_id`;
- `game_configs` адресуется по `chat_id`, хотя настройки принадлежат кампании;
- internal API использует `/internal/campaigns/{chat_id}/*`, и `CoreClient` передаёт туда ID чата;
- web identity и web-сессии сохраняют `initial_chat_id` и выбирают кампанию по `chat_id`;
- outbox-события используют `chat_id` как адрес Telegram side effect.

Из-за этого Core application нельзя использовать для кампании без Telegram-чата, а новый adapter
должен был бы притворяться Telegram integration. Standalone-команды этой проблемой не затронуты и
не должны участвовать в campaign resolution.

## Решение

Identity кампании — внутренний `Campaign.id`. Telegram chat ID является external identifier
отдельного adapter binding.

`telegram_campaign_bindings` — infrastructure representation Telegram integration mapping, а не
часть Campaign domain model. После миграции `Campaign` содержит только внутреннюю identity,
название и domain state; binding не добавляется в entity или value object кампании.

Для Telegram выбирается явная таблица:

```sql
CREATE TABLE telegram_campaign_bindings (
    campaign_id  INTEGER NOT NULL UNIQUE,
    chat_id      INTEGER NOT NULL UNIQUE,
    created_at   TEXT NOT NULL,
    FOREIGN KEY (campaign_id) REFERENCES campaigns(id) ON DELETE CASCADE
);
```

На первом этапе cardinality — `Campaign 0..1 ↔ 1 Telegram chat`:

- кампания может существовать без Telegram;
- одна кампания пока привязывается не более чем к одному чату;
- один чат привязывается не более чем к одной кампании.

Поддержки нескольких чатов у кампании сейчас не требуется. Если появится реальный сценарий
нескольких delivery destinations, ограничение `UNIQUE(campaign_id)` можно будет осознанно снять,
не меняя identity кампании.

## Почему не generic binding

Рассматривалась таблица `campaign_bindings(provider, kind, external_id)`. Она упрощает добавление
похожего provider только внешне, но переносит provider-specific ограничения в код и со временем
рискует стать EAV-подобным хранилищем.

Явная `telegram_campaign_bindings` предпочтительнее, потому что:

- тип и уникальность Telegram `chat_id` выражаются схемой;
- lookup и жизненный цикл остаются очевидными;
- не вводится plugin/provider abstraction до второго однородного use case;
- будущая Foundry связь сможет иметь собственные world ID, URL, credential reference и правила.

Foundry world не считается binding той же природы автоматически. Его модель определяется отдельно
в `ARCH-014`; общим у связей остаётся только `campaign_id`.

## Целевая граница

Connected Telegram adapter разрешает внешний ID до вызова application use case:

```text
Telegram update
    → connected command
    → CoreClient.resolve/ensure Telegram binding(chat_id, chat_title)
    → campaign_id
    → /internal/campaigns/{campaign_id}/...
    → application use case(campaign_id, ...)
```

Lookup хранится в Core persistence adapter: отдельный repository отвечает за Telegram binding.
Bot не получает доступ к SQLite. Создание кампании и binding должно быть одной идемпотентной
Core-транзакцией, чтобы параллельные команды не создавали дубликаты.

Предлагаемый integration API:

```text
GET /internal/telegram/chats/{chat_id}/campaign
PUT /internal/telegram/chats/{chat_id}/campaign
```

`GET` реализует side-effect-free resolve: возвращает `campaign_id` существующей связи либо
`campaign_not_bound`. `PUT` реализует ensure: атомарно возвращает существующую связь либо создаёт
Campaign вместе с binding и возвращает `campaign_id`.

Отсутствие binding для resolve — нормальное состояние ещё не настроенного connected-чата, а не
ошибка инфраструктуры. Resolve гарантированно не создаёт и не изменяет записи и может применяться
как проверка настройки. Обычная connected-команда при `campaign_not_bound` возвращает управляемое
сообщение о необходимости сначала выполнить setup.

Выбрана семантика explicit setup. Ensure разрешён только очевидным setup/registration use cases,
которые и сейчас создают Campaign: назначению первого мастера и регистрации первого игрока.
Обычные Core-dependent команды — просмотр и изменение расписания, start/stop сессии, настройки и
получение admin link — используют resolve и не создают Campaign как побочный эффект. Расширение
списка ensure-операций является отдельным продуктовым решением.

Ensure строго идемпотентен. Создание Campaign и binding выполняется в одной SQLite-транзакции;
`UNIQUE(chat_id)` и `UNIQUE(campaign_id)` являются последней защитой от дублей. При конкурентном
ensure проигравшая операция откатывает созданную ею Campaign, повторно читает binding и возвращает
тот же `campaign_id`. Ошибка создания binding откатывает всю операцию. Ensure первой версии не
привязывает существующую Campaign; отдельной команды регистрации Campaign не добавляется.

Business API после миграции использует `/internal/campaigns/{campaign_id}/*`.

Не следует добавлять campaign resolution в общий command pipeline. `/roll`, `/timer` и остальные
Core-independent handlers исполняются локально; resolver используется только connected handlers.
`CoreClient` остаётся optional dependency bootstrap.

## Application и web

Application-сервисы должны принимать `campaign_id`. Telegram-specific операции создания и lookup
binding находятся перед ними в integration adapter. Название Telegram-чата может использоваться
только как initial seed новой `Campaign.title`, но не является её identity. После создания
переименование Telegram-чата не меняет название кампании автоматически. Возможная синхронизация
названий потребует отдельного explicit use case.

Web-панель уже знает доступные кампании пользователя через membership. Её identity и query
parameters должны перейти с `chat_id` на `campaign_id`; web-запросам Telegram binding для обычных
campaign use cases не нужен. `game_configs` также должен принадлежать `campaign_id`.

Campaign без Telegram является валидной и для Web. Первая migration не добавляет создание кампании
или управление binding через панель: все перенесённые кампании уже имеют binding, а новый binding
создаёт только Telegram-side setup. Если Web получает доступ к непривязанной Campaign, он показывает
`Telegram: не подключён` и отключает Telegram-specific действия, сохраняя доступ к независимым
данным. Web attach/create остаются отдельными будущими product use cases.

В URL используется numeric `campaign_id`; slug без реального требования не вводится. Новый query
parameter называется `campaign_id`. Старый `campaign`, фактически содержавший `chat_id`, после
migration отклоняется без redirect, поэтому bookmark нельзя ошибочно интерпретировать как новый ID.

`initial_chat_id` в login tokens и web sessions заменяется на `initial_campaign_id`. Эти записи
эфемерны, поэтому migration удаляет активные login tokens/sessions и требует новый вход вместо
dual-read compatibility. Persistent local accounts и memberships сохраняются.

`game_configs.campaign_id` становится одновременно primary key и FK на `campaigns.id` с
`ON DELETE CASCADE`: config существует максимум в одном экземпляре на Campaign и не может
существовать без неё. Backfill связывает строки через прежний `chat_id` и перед переключением
проверяет равенство количества исходных и перенесённых configs и отсутствие orphan rows.

Local account по-прежнему связан с `telegram_user_id`: этот ADR отвязывает именно Campaign от
Telegram chat, а не меняет user identity/authentication.

## Outbox и доставка

Application events после migration должны содержать `campaign_id`, а не выбирать Telegram
destination внутри workflow. Connected Bot разрешает Telegram destination через Core binding API
`GET /internal/campaigns/{campaign_id}/telegram-binding` до side effect. Пока consumer единственный,
отдельный generic destination envelope не вводится.

Выбрана late-binding semantics: pending notification доставляется в Telegram binding, актуальный
на момент обработки event. Перенос binding до доставки тем самым перенаправляет ещё не обработанные
уведомления в новый chat. Если binding отсутствует, consumer классифицирует event как terminal
non-deliverable, пишет structured warning с `event_id` и `campaign_id` и подтверждает его как
пропущенный, чтобы технический poller не повторял доставку бесконечно. Exactly-once по-прежнему не
обещается. Binding, созданный позднее, не возобновляет уже терминально пропущенные notifications.

Существующие pending outbox payloads с `chat_id` не переписываются. Во время rollout consumer
временно принимает обе схемы, а новые events публикуются с `campaign_id` только после deploy
совместимого Bot. После опустошения старого outbox compatibility path удаляется.

Для одного перехода schema version не добавляется. Transitional parser требует ровно один routing
identifier: payload только с `chat_id` считается legacy, только с `campaign_id` — новым. Payload с
обоими или без обоих identifier является terminal malformed event: Telegram side effect не
выполняется, consumer пишет structured error и подтверждает пропуск, чтобы poison event не блокировал
очередь. Временный parser удаляется после нулевого количества pending legacy payloads и отсутствия
их появления в observation window.

## Изменение internal API

Текущее имя `{chat_id}` вводит в заблуждение: endpoint сообщает `invalid_campaign_id`, хотя ключом
является Telegram ID. Целевой контракт действительно адресует campaign resource:

```text
/internal/campaigns/{campaign_id}/game
/internal/campaigns/{campaign_id}/sessions/start
/internal/campaigns/{campaign_id}/players
...
```

Старые chat-based routes допускаются только как временный rollout contract. Это не возвращение
удалённого `/api/*`: оба поколения остаются в `/internal/*`, имеют явный срок жизни и удаляются
после обновления Bot.

После начала migration application services имеют только canonical методы с `campaign_id`.
Временные chat-based routes выполняют resolve через `TelegramCampaignBindingRepository` и вызывают
те же canonical use cases; пары application-методов наподобие `start(chat_id)` и
`start_by_campaign_id(campaign_id)` не создаются. Compatibility существует исключительно в
integration/API adapters.

## Lifecycle Telegram binding

Первая migration поддерживает только создание binding вместе с setup, resolve существующей связи
и cascade-удаление binding при удалении Campaign. Публичные detach, reattach и attach существующей
кампании в другой chat в неё не входят.

Следовательно, ensure для непривязанного chat либо возвращает уже существующий binding, либо
создаёт новую Campaign; он не пытается угадать ранее отвязанную кампанию. Memberships принадлежат
Campaign и не зависят от binding. Будущие detach/reattach должны отдельным решением определить
авторизацию, выбор существующей Campaign и судьбу pending notifications; до этого прямое изменение
binding вне миграций не поддерживается.

## Удаление Campaign

Удаление Campaign не добавляется первой migration. Если отдельный авторизованный use case появится,
удаление должно каскадно удалить Telegram binding, memberships, characters, sessions вместе с их
recaps и `game_configs`. Эти данные принадлежат Campaign и не сохраняются как самостоятельные
агрегаты.

Outbox payload не получает FK и не удаляется каскадно: delivered events остаются техническим
аудитом, а pending event удалённой Campaign при late resolution становится terminal non-deliverable
и подтверждается как пропущенный. Перед реализацией destructive delete всё равно требуется явное
подтверждение пользователя согласно общим правилам проекта.

## Bot resolution и кеширование

Baseline не использует cache `chat_id → campaign_id`: для текущей нагрузки дополнительный HTTP
resolve дешевле протокола invalidation и риска stale binding. Оптимизация допускается только после
измеримой проблемы; до этого каждый connected request получает актуальную связь, а standalone path
resolver не создаёт и не вызывает.

## План миграции

1. Добавить новой миграцией `telegram_campaign_bindings` и backfill пары `campaigns.id/chat_id`.
2. Добавить binding repository и транзакционный explicit-setup ensure, сохранив старые пути.
3. Перенести `game_configs` с `chat_id` на PK/FK `campaign_id` с проверяемым backfill.
4. Перевести application services на единственный `campaign_id`-контракт; старые API adapters
   разрешают `chat_id` и вызывают те же canonical methods.
5. Обновить web identity и URL выбора кампании на `campaign_id`; инвалидировать эфемерные login
   tokens/web sessions и потребовать новый вход.
6. Deploy Core с обоими контрактами; затем обновить `CoreClient` и только connected handlers:
   сначала resolve `chat_id → campaign_id`, затем вызвать campaign endpoint.
7. Перевести новые outbox events на `campaign_id`; временно поддерживать pending старого формата.
8. Убедиться по логам/тестам, что старые routes и payload больше не используются.
9. Новой rebuild-миграцией удалить `campaigns.chat_id` и временные chat-based routes/methods.

Каждая миграция добавляется новым номером; опубликованные SQL-файлы не изменяются. Перед rollout
обязательны production backup и проверка backfill: число bindings должно совпасть с числом текущих
campaigns, а дубликаты должны отсутствовать.

Порядок deploy — Core с backward compatibility, затем Bot, затем cleanup — позволяет независимо
обновлять два контейнера без окна несовместимости.

Текущая production topology содержит по одному Core и Bot instance. На compatibility-период Core
пишет structured log при использовании chat-based route, а Bot — при обработке legacy payload.
Cleanup разрешён только когда одновременно выполнены критерии:

- production Bot работает на migrated версии;
- pending legacy outbox payloads отсутствуют;
- минимум 24 часа после production verify не было обращений к chat-based routes и появления новых
  legacy events;
- выполнен хотя бы один успешный connected smoke-сценарий через новый resolve и campaign API;
- перед cleanup migration создана и проверена резервная копия SQLite.

## Последствия и trade-offs

Положительные:

- Core application получает стабильную provider-neutral campaign identity;
- web и Foundry смогут работать с кампанией без Telegram chat semantics;
- Telegram constraints и lookup изолируются в adapter;
- схема остаётся явной и небольшой.

Отрицательные:

- connected-команде потребуется дополнительный resolve либо локально кешируемый результат;
- rollout временно поддерживает два internal контракта и две outbox payload schema;
- существующие configs и web sessions требуют отдельного backfill;
- late binding намеренно направляет pending notifications в текущий, а не первоначальный chat;
- кампания без Telegram binding не сможет получать Telegram notifications, что должно быть
  terminal non-deliverable состоянием, а не бесконечной технической ошибкой.

## Ответы на обязательные вопросы

1. Identity Campaign — `campaigns.id`.
2. Campaign может существовать без Telegram.
3. Сейчас Campaign имеет максимум один Telegram chat; расширение отложено до реального use case.
4. Telegram chat принадлежит максимум одной Campaign.
5. Foundry world не считается generic binding той же природы; решение принимает `ARCH-014`.
6. Connected Bot выполняет side-effect-free resolve перед обычным business request; ensure
   разрешён только setup/registration operations.
7. Lookup хранится в `telegram_campaign_bindings`, доступном через отдельный repository Core.
8. Internal API переходит на `{campaign_id}`, плюс появляются Telegram resolve/ensure endpoints.
9. Backfill создаёт binding для каждой существующей пары `campaigns.id/chat_id`; удаление столбца
   выполняется только последующей rebuild-миграцией.
10. Совместимость обеспечивает порядок dual-contract Core → migrated Bot → cleanup Core и
    существует только на adapter boundary.

## Standalone invariant

`CoreClient` остаётся optional dependency. Resolver создаётся и вызывается только connected path;
standalone handlers не импортируют binding repository или Core persistence. Отсутствие либо outage
Core не меняет общий command dispatch, не останавливает Bot и не мешает `/roll` и `/timer`.
Migration acceptance tests обязаны сохранять standalone startup, обе команды без Core, controlled
ошибку connected-команды и отсутствие event poller при standalone configuration.

## Не входит в это решение

- изменение production кода или базы в рамках `ARCH-013`;
- отвязка пользователей от `telegram_user_id`;
- реализация Foundry integration;
- generic integration registry;
- campaign resolution для standalone-команд;
- поддержка multiple Bot/Core replicas.
