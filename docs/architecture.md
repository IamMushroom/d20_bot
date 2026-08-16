# Архитектура и режимы запуска

Проект разделяется на два процесса: лёгкий Telegram-бот и Core. Бот отвечает за броски
кубов и служит пультом управления, а Core владеет постоянными данными, игровыми сценариями
и веб-панелью мастера.

## Компоненты

```text
Telegram
   │
   ▼
┌─────────────────────┐       HTTP + Bearer token        ┌──────────────────────┐
│ d20 bot             │ ───────────────────────────────► │ Core                 │
│                     │                                  │                      │
│ • команды бросков   │                                  │ • сервисы кампаний   │
│ • таймер            │                                  │ • расписание/сессии  │
│ • пульт управления  │ ◄──── persistent outbox ──────── │ • SQLite и миграции  │
└─────────────────────┘                                  │ • панель мастера     │
                                                         └──────────┬───────────┘
                                                                    │
                                                                    ▼
                                                             d20.sqlite3
```

Оба процесса пока собираются из одного Docker-образа, но имеют разные точки входа:

- `src/run.py` запускает Telegram-бота;
- `src/run_core.py` запускает Core;
- `src/core/client.py` содержит клиент внутреннего API;
- `src/core/runtime.py` собирает базу, сервисы и HTTP-сервер Core.

Это позволяет разделить процессы и их ресурсы без дублирования пакетов и образов.

## Режимы Telegram-бота

Режим задаётся переменной `D20_BOT_MODE`.

### `standalone`

Режим по умолчанию. Для запуска нужен только `D20_BOT_TG_TOKEN`.

Доступны `/roll`, `/roll20`, `/duality`, `/timer`, `/help` и `/version`. Бот не открывает
SQLite, не применяет миграции, не запускает HTTP-сервер и не зависит от Core.

Этот режим подходит для отдельной бросалки или для продолжения бросков при отключённой
игровой платформе.

### `connected`

Бот сохраняет локальные команды standalone-режима и подключается к Core по `D20_BOT_CORE_URL`.
В connected-режиме доступны все текущие управляющие команды. Они обращаются к Core за
данными и выполнением сценариев, но Telegram-сообщения, member tags и закрепы создаёт бот.

Для запуска требуются:

```dotenv
D20_BOT_TG_TOKEN=<telegram-token>
D20_BOT_MODE=connected
D20_BOT_CORE_URL=http://core:8190
D20_BOT_CORE_TOKEN=<shared-secret>
```

Если Core временно недоступен, броски продолжают работать, а удалённая команда возвращает
понятное сообщение об ошибке.

## Core

При старте Core выполняет следующие действия:

1. проверяет `D20_BOT_CORE_TOKEN`;
2. открывает SQLite по `D20_BOT_DATABASE_URL`;
3. применяет миграции из `migrations/`;
4. создаёт сервисы кампаний, сессий, outbox, аутентификации и rate limiting;
5. запускает HTTP-сервер и панель мастера;
6. при остановке закрывает HTTP-сервер и базу.

Core не получает `D20_BOT_TG_TOKEN` и не вызывает Telegram API. Изменения из веб-панели записываются
в таблицу `outbox_events`. Connected-бот периодически получает неподтверждённые события через
`GET /internal/events`, выполняет Telegram-действие и подтверждает доставку отдельным запросом.
До подтверждения
событие сохраняется в SQLite и переживает перезапуск обоих процессов. Доставка имеет
семантику at-least-once: при сбое между Telegram-вызовом и подтверждением событие может быть
выполнено повторно, но не будет молча потеряно.

Сервисы предметной области, включая `SessionService`, только изменяют и читают состояние и
никогда не создают outbox-события. Их использует internal API для команд бота: Telegram-ответ
в этом сценарии выполняет сам бот, поэтому дополнительное событие не требуется.

Операции web-панели, после которых Telegram-действие должен выполнить бот, используют явные
методы `GameWorkflowService`: `schedule_and_notify`, `start_and_notify` и `stop_and_notify`.
Каждый такой application workflow владеет общей SQLite-транзакцией, включающей изменение
состояния и ровно одно связанное outbox-событие. Ошибка записи события откатывает изменение
сессии. Добавлять универсальный флаг наподобие `notify=True` в mutation-only сервисы не следует:
выбор сценария и его побочных эффектов должен быть виден в имени вызываемого use case.
Текущая deployment-модель предполагает ровно один экземпляр Core и один экземпляр Bot;
outbox leasing и координация нескольких consumers пока не реализованы.

`CoreRuntime` является явным composition root Core. Он создаёт concrete repositories, передаёт
их сервисам через конструкторы, собирает application workflows и только затем создаёт web-сервер.
Сервисы не создают repositories самостоятельно, а `AdminWebServer` получает уже собранный
`GameWorkflowService`. Для этой сборки используются обычные Python-конструкторы без service
locator, глобального registry или DI-фреймворка.

Канонический источник мастера кампании — `campaign_memberships.role = 'master'`. Таблица
`campaigns` не дублирует Telegram ID мастера, а partial unique index гарантирует не более одной
master-membership на кампанию. `CampaignService` оркестрирует назначение и передачу роли внутри
application-транзакции; repositories изменяют только принадлежащие им persistence concerns.

## Внутренний API

Legacy action-based API физически изолирован в `web/api/legacy.py`, помечен deprecated и пока
предоставляет методы для совместимости:

- `POST /api/admin-link` — одноразовая ссылка мастера;
- `POST /api/game` — чтение и изменение расписания, сохранение ID объявления;
- `POST /api/game-url` — чтение и изменение адреса Foundry по умолчанию.
- `POST /api/session` — запуск и завершение игровой сессии.
- `POST /api/role` — назначение мастера и регистрация персонажа;
- `POST /api/web-url` — адрес панели для конкретного чата.
- `POST /api/events` — получение и подтверждение событий outbox.

Основной operation-oriented API предоставляет endpoints:

- `GET /internal/events` — список ожидающих событий;
- `POST /internal/events/{event_id}/ack` — подтверждение отдельного события.
- `GET /internal/campaigns/{chat_id}/game` — текущее расписание кампании;
- `PUT /internal/campaigns/{chat_id}/game` — назначение или перенос игры;
- `POST /internal/sessions/{session_id}/announcement` — сохранение Telegram message ID;
- `POST /internal/campaigns/{chat_id}/sessions/start` — старт игровой сессии;
- `POST /internal/campaigns/{chat_id}/sessions/stop` — завершение игровой сессии.
- `POST /internal/auth/registration-codes` — выпуск одноразового кода регистрации;
- `POST /internal/campaigns/{chat_id}/admin-links` — выпуск ссылки web-панели;
- `PUT /internal/campaigns/{chat_id}/master` — назначение мастера;
- `POST /internal/campaigns/{chat_id}/players` — регистрация персонажа игрока;
- `GET|PUT /internal/campaigns/{chat_id}/foundry-url` — чтение и изменение Foundry URL;
- `GET|PUT /internal/campaigns/{chat_id}/web-url` — чтение и изменение адреса панели.

Ошибки новых `/internal/*` endpoints имеют единый контракт:

```json
{
  "error": {
    "code": "invalid_event_id",
    "message": "Event ID must be a positive integer."
  }
}
```

Клиенты принимают решения по стабильному `code`, а `message` предназначен для диагностики.
Все методы `CoreClient` используют `/internal/*`. Старые `/api/*` endpoints пока сохраняются для
совместимости уже запущенных экземпляров Bot и должны удаляться только отдельным изменением после
явно выбранного compatibility window.

Пример запроса ссылки:

```http
POST /internal/campaigns/-100123/admin-links
Authorization: Bearer <D20_BOT_CORE_TOKEN>
Content-Type: application/x-www-form-urlencoded

user_id=12345&chat_title=Campaign
```

Core проверяет, что пользователь является мастером указанной кампании, создаёт одноразовый
токен входа и возвращает JSON:

```json
{"url": "https://d20.example/login?token=..."}
```

`D20_BOT_CORE_TOKEN` — внутренний общий секрет, а не пользовательская сессия. Используйте длинное
случайное значение, одинаковое для контейнеров `d20` и `core`. Не публикуйте внутренний API
в интернет без reverse proxy и дополнительных сетевых ограничений.

## Docker Compose

Обычный запуск поднимает только standalone-бота:

```shell
docker compose up --build -d
```

Полная платформа запускается профилем `platform`:

```dotenv
D20_BOT_TG_TOKEN=<telegram-token>
D20_BOT_MODE=connected
D20_BOT_CORE_TOKEN=<long-random-secret>
D20_BOT_WEB_BASE_URL=http://rpi001.local:8190
```

```shell
docker compose --profile platform up --build -d
```

В этом варианте только `core` подключает volume `d20-data` и публикует порт панели `8190`.
Контейнер бота остаётся stateless. Явного `depends_on` нет: бот может стартовать раньше Core,
а временная недоступность Core не должна мешать броскам.

Профиль `debug` отдельно добавляет `sqlite-web`:

```shell
docker compose --profile platform --profile debug up -d
```

`sqlite-web` имеет прямой доступ к рабочему volume. Его нельзя публиковать в интернет.

## Владение данными и зависимости

SQLite имеет одного владельца — Core. Telegram-бот в `standalone` и `connected` не должен
импортировать репозитории для обработки команд и не должен получать путь к базе.

Внутри Core зависимости направлены следующим образом:

```text
HTTP handler → service → repository → Database → SQLite
```

SQL остаётся в репозиториях, бизнес-сценарии — в сервисах, транспортная проверка и разбор
запросов — в HTTP-слое. Подробнее устройство хранения описано в [database.md](database.md).

## Текущее состояние миграции

Уже отделены:

- жизненный цикл базы, миграций и панели в `CoreRuntime`;
- отдельная точка входа Core;
- standalone-запуск без платформенных зависимостей;
- получение ссылки `/admin` через защищённый Core API;
- расписание `/game` и настройка `/game_url` через Core API;
- lifecycle `/session_start` и `/session_stop` через Core API;
- роли `/master`, `/player` и настройка `/web_url` через Core API;
- отправка и закрепление объявлений на стороне Telegram-бота;
- Docker-профиль `platform`.

Все управляющие команды имеют Core API, монолитный режим удалён, исходящие Telegram-события
передаются через постоянный outbox. HTTP transport, Router, middleware, internal API и HTML
handlers уже разделены по модулям; `AdminWebServer` остаётся composition root. Возможное
дальнейшее улучшение — добавить lease для нескольких экземпляров бота.

## Диагностика

Логи процессов разделены:

```shell
docker compose logs -f d20
docker compose logs -f core
```

Если `/admin` сообщает о недоступности Core, следует проверить:

- запущен ли профиль `platform`;
- совпадает ли `D20_BOT_CORE_TOKEN` у обоих сервисов;
- использует ли бот `D20_BOT_MODE=connected`;
- доступен ли из контейнера бота адрес `D20_BOT_CORE_URL`;
- задан ли публичный `D20_BOT_WEB_BASE_URL` или адрес панели для кампании.
