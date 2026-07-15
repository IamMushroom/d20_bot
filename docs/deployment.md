# Установка и эксплуатация

## Переменные окружения

| Переменная | Обязательна | По умолчанию | Описание |
|---|---:|---:|---|
| `TG_TOKEN` | для бота | — | Токен от BotFather; Core его не получает. |
| `D20_MODE` | нет | `standalone` | `standalone` или `connected`. |
| `CORE_URL` | для `connected` | `http://core:8190` в Compose | Внутренний адрес Core API. |
| `CORE_TOKEN` | для `connected` и Core | — | Общий секрет бота и Core. |
| `LOG_FORMAT` | нет | `json` | Формат логов. |
| `DOCKER_TAG` | нет | `latest` | Тег Docker-образа для Compose. |
| `DATABASE_URL` | нет | `sqlite:////data/d20.sqlite3` | URL файла SQLite. |
| `GAME_TIMEZONE` | нет | `Europe/Moscow` | Часовой пояс расписания. |
| `FOUNDRY_URL` | нет | — | Адрес Foundry по умолчанию. |
| `WEB_BASE_URL` | нет | — | Публичный адрес панели по умолчанию. |
| `WEB_PORT` | нет | `8190` | Опубликованный порт панели. |
| `WEB_SECURE_COOKIE` | нет | `auto` | Secure-флаг cookie: `auto`, `true` или `false`. |
| `SQLITE_WEB_PORT` | нет | `8080` | Порт `sqlite-web` в debug-профиле. |

## Локальный запуск

Требуется Python 3.14.

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
uv sync --frozen --no-dev
$env:TG_TOKEN = '<telegram-token>'
python src\run.py
```

Для Linux/macOS окружение активируется командой `source .venv/bin/activate`. Без
`D20_MODE` запускается standalone-бот без SQLite, миграций и HTTP-сервера.

## Docker Compose

Скопируйте `.env.example` в `.env`, укажите `TG_TOKEN` и запустите бросалку:

```shell
docker compose up --build -d
```

Для полной платформы задайте общий секрет и публичный адрес:

```dotenv
D20_MODE=connected
CORE_TOKEN=<long-random-secret>
WEB_BASE_URL=http://rpi001.local:8190
```

```shell
docker compose --profile platform up --build -d
```

В этом варианте `d20` остаётся stateless, а контейнер `core` владеет SQLite, миграциями и
панелью. Бот больше не поддерживает монолитный запуск с базой в собственном процессе.

Логи процессов:

```shell
docker compose logs -f d20
docker compose logs -f core
```

## Панель мастера

Панель работает в Core на порту `8190`. `WEB_BASE_URL` должен содержать адрес, доступный
браузеру пользователя, а не внутреннее имя контейнера. Администратор также может сохранить
адрес конкретного чата командой `/web_url`; настройка чата имеет приоритет.

Мастер вызывает `/admin` в группе и получает одноразовую ссылку в личном диалоге. Ссылка
действует 15 минут, HttpOnly-сессия — 8 часов. Сессии входа сбрасываются при перезапуске Core.

`WEB_SECURE_COOKIE=auto` включает Secure cookie при HTTPS или заголовке
`X-Forwarded-Proto: https`. Публично выставлять панель без HTTPS не следует.

## Отладка SQLite

Профиль `debug` запускает `sqlite-web`, подключённый к рабочему volume:

```shell
docker compose --profile platform --profile debug up -d
```

Интерфейс доступен на порту `${SQLITE_WEB_PORT:-8080}` Raspberry Pi. Он позволяет напрямую
менять данные, поэтому его нельзя публиковать в интернет. Для ограниченного доступа можно
использовать firewall или SSH-туннель:

```shell
ssh -L 8080:127.0.0.1:8080 user@raspberry-pi
```

Остановка только отладочного интерфейса:

```shell
docker compose stop sqlite-web
```

## Резервное копирование

Постоянные данные находятся в Docker volume `d20-data`. Перед обновлением миграций следует
остановить Core и сохранить копию файла `/data/d20.sqlite3` или всего volume. Одновременно
изменять базу через Core и `sqlite-web` нежелательно.

Дополнительная диагностика связи Bot/Core приведена в
[architecture.md](architecture.md#диагностика).
