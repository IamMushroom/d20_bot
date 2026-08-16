# ADR-001: Identity кампании и Telegram binding

- Статус: Proposed
- Дата: 2026-08-16
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

`GET` только разрешает существующую связь. `PUT` идемпотентно создаёт кампанию и binding при
первом Core-dependent setup и возвращает `campaign_id`. Business API после миграции использует
`/internal/campaigns/{campaign_id}/*`.

Не следует добавлять campaign resolution в общий command pipeline. `/roll`, `/timer` и остальные
Core-independent handlers исполняются локально; resolver используется только connected handlers.
`CoreClient` остаётся optional dependency bootstrap.

## Application и web

Application-сервисы должны принимать `campaign_id`. Telegram-specific операции создания и lookup
binding находятся перед ними в integration adapter. Название Telegram-чата может использоваться
как начальное название новой кампании, но не является её identity.

Web-панель уже знает доступные кампании пользователя через membership. Её identity и query
parameters должны перейти с `chat_id` на `campaign_id`; web-запросам Telegram binding для обычных
campaign use cases не нужен. `game_configs` также должен принадлежать `campaign_id`.

Local account по-прежнему связан с `telegram_user_id`: этот ADR отвязывает именно Campaign от
Telegram chat, а не меняет user identity/authentication.

## Outbox и доставка

Application events после migration должны содержать `campaign_id`, а не выбирать Telegram
destination внутри workflow. Connected Bot разрешает Telegram destination через Core binding API
`GET /internal/campaigns/{campaign_id}/telegram-binding` до side effect. Пока consumer единственный,
отдельный generic destination envelope не вводится.

Существующие pending outbox payloads с `chat_id` не переписываются. Во время rollout consumer
временно принимает обе схемы, а новые events публикуются с `campaign_id` только после deploy
совместимого Bot. После опустошения старого outbox compatibility path удаляется.

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

## План миграции

1. Добавить новой миграцией `telegram_campaign_bindings` и backfill пары `campaigns.id/chat_id`.
2. Добавить binding repository и транзакционный resolve/ensure use case, сохранив старые пути.
3. Добавить `campaign_id`-ориентированные методы application services и internal API.
4. Перенести `game_configs` с `chat_id` на FK `campaign_id` с backfill.
5. Обновить web identity, login/session storage и URL выбора кампании на `campaign_id`.
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
- кампания без Telegram binding не сможет получать Telegram notifications, что должно быть
  контролируемым состоянием, а не application error.

## Ответы на обязательные вопросы

1. Identity Campaign — `campaigns.id`.
2. Campaign может существовать без Telegram.
3. Сейчас Campaign имеет максимум один Telegram chat; расширение отложено до реального use case.
4. Telegram chat принадлежит максимум одной Campaign.
5. Foundry world не считается generic binding той же природы; решение принимает `ARCH-014`.
6. Connected Bot разрешает `chat_id` через Core integration endpoint до business request.
7. Lookup хранится в `telegram_campaign_bindings`, доступном через отдельный repository Core.
8. Internal API переходит на `{campaign_id}`, плюс появляются Telegram resolve/ensure endpoints.
9. Backfill создаёт binding для каждой существующей пары `campaigns.id/chat_id`; удаление столбца
   выполняется только последующей rebuild-миграцией.
10. Совместимость обеспечивает порядок dual-contract Core → migrated Bot → cleanup Core.

## Не входит в это решение

- изменение production кода или базы в рамках `ARCH-013`;
- отвязка пользователей от `telegram_user_id`;
- реализация Foundry integration;
- generic integration registry;
- campaign resolution для standalone-команд;
- поддержка multiple Bot/Core replicas.
