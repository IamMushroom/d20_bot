# D20 Telegram Bot

[![Tests & Ruff](https://github.com/IamMushroom/d20_bot/actions/workflows/tests.yaml/badge.svg)](https://github.com/IamMushroom/d20_bot/actions/workflows/tests.yaml)
[![Python 3.14](https://img.shields.io/badge/python-3.14-3776AB?logo=python&logoColor=white)](https://www.python.org/)
[![Ruff](https://img.shields.io/endpoint?url=https://raw.githubusercontent.com/astral-sh/ruff/main/assets/badge/v2.json)](https://github.com/astral-sh/ruff)

Компактный Telegram-бот для бросков кубов в настольных ролевых играх. Поддерживает
выражения из нескольких кубов, advantage/disadvantage, броски Daggerheart и таймеры.
Опциональный Core добавляет расписание игр, сессии, SQLite и веб-панель мастера.

## Быстрый старт

Для запуска standalone-бросалки достаточно токена от [@BotFather](https://t.me/BotFather):

```shell
cp .env.example .env
# Укажите D20_BOT_TG_TOKEN в .env
docker compose up --build -d
```

По умолчанию бот не открывает базу и не запускает HTTP-сервер. Быстрое Telegram-меню
содержит только `/roll`, `/roll20` и `/duality`; полная справка доступна через `/help`.

Примеры:

```text
/roll
/roll 1d20 + 4
/roll 4d6kh3
/roll 2d20kl1
/duality 5
/timer 60
```

Для запуска Core и панели мастера задайте в `.env`:

```dotenv
D20_BOT_MODE=connected
D20_BOT_CORE_TOKEN=<long-random-secret>
D20_BOT_WEB_BASE_URL=http://rpi001.local:8190
```

```shell
docker compose --profile platform up --build -d
```

## Документация

- [Команды и синтаксис кубов](docs/commands.md)
- [Установка, конфигурация и эксплуатация](docs/deployment.md)
- [Архитектура Bot/Core](docs/architecture.md)
- [База данных и репозитории](docs/database.md)
- [Web-аутентификация и Telegram Login](docs/authentication.md)
- [Разработка, тесты и CI/CD](docs/development.md)
- [Helm chart](charts/d20-bot/README.md)
- [Хотелки и технический backlog](todos/README.md)
- [История изменений](CHANGELOG.md)

## Режимы

| Режим | Назначение |
|---|---|
| `standalone` | Броски и таймер без базы и Core; режим по умолчанию. |
| `connected` | Лёгкий бот, подключённый к отдельному Core. |

Подробные границы компонентов и текущее состояние миграции описаны в
[архитектурной документации](docs/architecture.md).

## Разработка

```shell
uv sync --frozen
uv run ruff check .
uv run ruff format --check .
uv run pytest
```

Требуется Python 3.14. Активные таймеры хранятся в памяти и сбрасываются при перезапуске.
