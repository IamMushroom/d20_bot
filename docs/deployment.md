# Установка и эксплуатация

## Переменные окружения

| Переменная | Обязательна | По умолчанию | Описание |
|---|---:|---:|---|
| `D20_BOT_TG_TOKEN` | для бота | — | Токен от BotFather; Core его не получает. |
| `D20_BOT_MODE` | нет | `standalone` | `standalone` или `connected`. |
| `D20_BOT_CORE_URL` | для `connected` | `http://core:8190` в Compose | Внутренний адрес Core API. |
| `D20_BOT_CORE_TOKEN` | для `connected` и Core | — | Общий секрет бота и Core. |
| `D20_BOT_LOG_FORMAT` | нет | `json` | Формат логов. |
| `D20_BOT_DOCKER_TAG` | нет | `latest` | Тег Docker-образа для Compose. |
| `D20_BOT_DATABASE_URL` | нет | `sqlite:////data/d20.sqlite3` | URL файла SQLite. |
| `D20_BOT_GAME_TIMEZONE` | нет | `Europe/Moscow` | Часовой пояс расписания. |
| `D20_BOT_FOUNDRY_URL` | нет | — | Адрес Foundry по умолчанию. |
| `D20_BOT_WEB_BASE_URL` | нет | — | Публичный адрес панели по умолчанию. |
| `D20_BOT_WEB_PORT` | нет | `8190` | Опубликованный порт панели. |
| `D20_BOT_WEB_SECURE_COOKIE` | нет | `auto` | Secure-флаг cookie: `auto`, `true` или `false`. |
| `D20_BOT_WEB_TRUSTED_PROXIES` | нет | — | Доверенные IP/CIDR reverse proxy через запятую. |
| `D20_BOT_SQLITE_WEB_PORT` | нет | `8080` | Порт `sqlite-web` в debug-профиле. |

## Локальный запуск

Требуется Python 3.14.

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
uv sync --frozen --no-dev
$env:D20_BOT_TG_TOKEN = '<telegram-token>'
python src\run.py
```

Для Linux/macOS окружение активируется командой `source .venv/bin/activate`. Без
`D20_BOT_MODE` запускается standalone-бот без SQLite, миграций и HTTP-сервера.

## Docker Compose

Скопируйте `.env.example` в `.env`, укажите `D20_BOT_TG_TOKEN` и запустите бросалку:

```shell
docker compose up --build -d
```

Для полной платформы задайте общий секрет и публичный адрес:

```dotenv
D20_BOT_MODE=connected
D20_BOT_CORE_TOKEN=<long-random-secret>
D20_BOT_WEB_BASE_URL=http://rpi001.local:8190
```

```shell
docker compose --profile platform up --build -d
```

В этом варианте `d20` остаётся stateless, а контейнер `core` владеет SQLite, миграциями и
панелью. Бот больше не поддерживает монолитный запуск с базой в собственном процессе.

Перед Core одноразовый Compose-сервис `data-init` выставляет для `/data` владельца `10001:10001`.
Core запускается только после успешного завершения `data-init`. Привилегия `CHOWN` выдаётся
только этому короткоживущему инфраструктурному шагу; bot и Core всегда работают как UID `10001`.

Логи процессов:

```shell
docker compose logs -f d20
docker compose logs -f core
```

## Панель мастера

Панель работает в Core на порту `8190`. `D20_BOT_WEB_BASE_URL` должен содержать адрес, доступный
браузеру пользователя, а не внутреннее имя контейнера. Администратор также может сохранить
адрес конкретного чата командой `/web_url`; настройка чата имеет приоритет.

Мастер вызывает `/admin` в группе и получает одноразовую ссылку в личном диалоге. Ссылка
действует 15 минут, HttpOnly-сессия — 8 часов. Сессии входа сбрасываются при перезапуске Core.

`D20_BOT_WEB_SECURE_COOKIE=auto` включает Secure cookie по `X-Forwarded-Proto: https` только
когда запрос пришёл от адреса из `D20_BOT_WEB_TRUSTED_PROXIES`. Укажите там адрес или сеть
reverse proxy, например `172.18.0.0/16`; не используйте публичные сети без необходимости.
Значение `true` всегда включает Secure независимо от proxy-заголовков. Публично выставлять
панель без HTTPS не следует.

## Отладка SQLite

Профиль `debug` запускает `sqlite-web`, подключённый к рабочему volume:

```shell
docker compose --profile platform --profile debug up -d
```

Интерфейс доступен на порту `${D20_BOT_SQLITE_WEB_PORT:-8080}` Raspberry Pi. Он позволяет напрямую
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

Постоянные данные находятся в Docker volume `d20-data`, резервные копии — в отдельном
`d20-backups`. Production workflow перед заменой контейнеров запускает maintenance-сервис
`database-backup`. Он использует SQLite Online Backup API, поэтому получает согласованную копию
работающей WAL-базы без остановки Core. `D20_BOT_BACKUP_KEEP` задаёт число хранимых копий и по
умолчанию равен `10`.

Создать копию вручную:

```shell
docker compose -p d20_bot_prd --profile maintenance run --rm --no-deps database-backup
```

Посмотреть доступные копии:

```shell
docker run --rm -v d20_bot_prd_d20-backups:/backups alpine:3.23 ls -lh /backups
```

Восстановление является отдельной ручной операцией: сначала остановите Core, сохраните текущую
базу, затем скопируйте выбранный backup в `d20_bot_prd_d20-data` как `d20.sqlite3`, выставьте
владельца `10001:10001` и запустите Core с совместимым Docker-образом. Не восстанавливайте файл
поверх работающего Core и не смешивайте backup новой схемы со старым образом.

Одновременно изменять базу через Core и `sqlite-web` нежелательно.

## Kubernetes и Helm

Готовый chart находится в [`charts/d20-bot`](../charts/d20-bot/README.md). По умолчанию он
разворачивает bot, Core, ClusterIP Service и PVC. Ingress опционален; standalone-установка
включается через `core.enabled=false`.

Дополнительная диагностика связи Bot/Core приведена в
[architecture.md](architecture.md#диагностика).

## GitHub Actions

Workflow `run_bot.yaml` собирает и разворачивает ветку `dev` на self-hosted runner с label
`raspberry`. `push_image.yaml` публикует semver-теги в Docker Hub и GHCR, создаёт GitHub Release и
выполняет production-деплой.

GitHub variable `D20_MODE` управляет составом Compose:

- `standalone` или пустое значение запускает только Telegram-бота;
- `connected` добавляет Compose-профиль `platform` с Core;
- dev-окружение дополнительно включает `debug` с `sqlite-web`.

GitHub Environment Variable `D20_BOT_WEB_PORT` задаёт внешний порт Core отдельно для каждого
окружения. Workflow использует безопасные разные значения по умолчанию: `8191` для `dev` и `8190`
для `prd`, чтобы два Compose-проекта могли одновременно работать на одном Raspberry Pi.

Core публикует `GET /health`. Bot обновляет heartbeat-файл из asyncio event loop.
Liveness-проверка считает процесс живым, если heartbeat не старше 20 секунд. Readiness дополнительно
вызывает Telegram `getMe`. Ошибка Telegram записывается как структурированный warning без токена,
но не меняет exit code: внешний сбой не должен валить deploy или вызывать рестарт. В Compose и
Kubernetes статус готовности определяется свежестью heartbeat. Сетевая диагностика ограничена
одной секундой, а runtime даёт healthcheck пять секунд на запуск Python и завершение проверки.

Deployment workflow ждёт готовности всех активных сервисов до одной минуты. При ошибке в job
выводятся статусы и последние 100 строк логов.

Автоматический rollback не выполняется: после запуска миграций старый образ может быть
несовместим с новой схемой SQLite. Production backup создаётся автоматически до запуска нового
Core; откатывать образ и базу следует вместе.
