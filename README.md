# D20 Telegram Bot

[![Tests & Ruff](https://github.com/IamMushroom/d20_bot/actions/workflows/tests.yaml/badge.svg)](https://github.com/IamMushroom/d20_bot/actions/workflows/tests.yaml)
[![Python 3.14](https://img.shields.io/badge/python-3.14-3776AB?logo=python&logoColor=white)](https://www.python.org/)
[![Ruff](https://img.shields.io/endpoint?url=https://raw.githubusercontent.com/astral-sh/ruff/main/assets/badge/v2.json)](https://github.com/astral-sh/ruff)

Небольшой Telegram-бот для брсков кубов в настольных ролевых играх. Поддерживает математические выражения, броски Daggerheart и таймеры для чата.

## Команды

- `/roll` — обычный бросок d20.
- `/roll 2d6` — бросок указанных кубов.
- `/roll 1d20 + 4` — бросок с числовым модификатором.
- `/roll 1d12 + 1d6 - 2` — выражение из нескольких кубов и модификаторов.
- `/roll 4d6kh3` — бросить 4d6 и оставить три лучших значения.
- `/roll 2d20kl1` — бросок d20 с помехой; `2d20kh1` — с преимуществом.
- `/roll20 d20` — бросок с повышенной вероятностью минимального и максимального значения.
- `/duality` — бросок двух d12 надежды и страха для Daggerheart.
- `/duality 5` — брсок Daggerheart с модификатором.
- `/timer 60` — таймер на 60 секунд.
- `/game` — показать дату следующей игры и ссылку на Foundry.
- `/game 20.07 19:00` — назначить игру со ссылкой из `FOUNDRY_URL` и закрепить объявление (для администратора чата).
- `/game 20.07 19:00 https://foundry.example` — назначить игру, переопределив ссылку для неё.
- `/start` и `/help` — справка по командам.
- `/version` — текущая версия бота.

Алиасы: `/rolld20` для `/roll20`, `/dgh` и `/daggerheart` для `/duality`.

### Синтаксис кубов

Поддерживаются латинские `d`/`D` и кириллические `к`/`К`:

```text
d20
2d6
8к10
1d12 + 1d6
2d20 - 1d4 + 3
4d6kh3
2d20kl1
```

В выражении разрешены только `+` и `-`. Умножение, деление и скобки не поддерживаются.
Суффикс `khN` оставляет `N` наибольших значений, `klN` — `N` наименьших.

Ограничения:

- до 100 кубов на всё выражение;
- до 1000 граней у куба;
- до 20 слагаемых;
- абсолютное значение модификатора — до 1 000 000;
- таймер — от 1 секунды до 24 часов.

### Как работает `/roll20`

Для куба с `N` гранями минимум и максимум имеют вес 2, а остальные значения — вес 1. Вероятность каждого крайнего значения равна `2 / (N + 2)`.

## Переменные окружения

| Переменная | Обязательна | По умолчанию | Описание |
|---|---:|---:|---|
| `TG_TOKEN` | да | — | Токен бота от [@BotFather](https://t.me/BotFather). |
| `LOG_FORMAT` | нет | `json` | Формат логов. Сейчас поддерживается `json`. |
| `DOCKER_TAG` | нет | `latest` | Тег Docker-образа для Compose. |
| `DATABASE_URL` | нет | `sqlite:////data/d20.sqlite3` | URL файла SQLite. |
| `GAME_TIMEZONE` | нет | `Europe/Moscow` | Часовой пояс расписания игр. |
| `FOUNDRY_URL` | нет | — | Ссылка на Foundry по умолчанию для команды `/game`. |

## Локальный запуск

Требуется Python 3.14.

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
uv sync --frozen --no-dev
$env:TG_TOKEN = '<telegram-token>'
python src\run.py
```

Для Linux/macOS активация окружения выполняется командой `source .venv/bin/activate`.

## Docker Compose

Скопируйте `.env.example` в `.env` и замените токен:

```dotenv
TG_TOKEN=<telegram-token>
LOG_FORMAT=json
DOCKER_TAG=latest
DATABASE_URL=sqlite:////data/d20.sqlite3
```

Запуск:

```shell
docker compose up --build -d
```

Просмотр JSON-логов:

```shell
docker compose logs -f d20
```

## Тесты

```shell
uv sync --frozen
uv run ruff check .
uv run ruff format --check .
uv run pytest
```

Обычный запуск `pytest` сразу строит отчёт о branch coverage. Минимальный допустимый уровень — 90%.

## CI/CD

GitHub Actions запускает на self-hosted Raspberry Pi Ruff, тесты в `python:3.14-alpine` и smoke-build runtime-образа. После deploy workflow проверяет, что контейнер не завершился при инициализации. Публикуемые образы содержат SBOM и provenance attestations. Workflow запуска бота и workflow публикации образа выполняются только после успешных проверок. Из соображений безопасности fork pull request не запускает код на self-hosted runner.

Dependabot раз в неделю проверяет Python-пакеты, GitHub Actions и Docker base image. Все экосистемы объединяются в один multi-ecosystem pull request. Push в `dev` запускает dev-deploy; push в `prd` сам по себе ничего не разворачивает.

Тег `vX.Y.Z` должен совпадать с версией в `pyproject.toml`. Такой тег публикует ARM64-образы в Docker Hub и GHCR, подписывает их через Cosign, создаёт GitHub Release и затем разворачивает в production образ с этим релизным тегом.

Требования к runner:

- лейблы `self-hosted` и `raspberry`;
- Docker Engine, Buildx и Docker Compose v2;
- доступ runner-пользователя к Docker daemon;
- `TG_TOKEN` в GitHub Environment с именем ветки;
- `DOCKER_HUB_TOKEN`, `DOCKER_HUB_NAME` и environment `prd` для публикации образа.

## Структура проекта

```text
src/
├── commands/       # Telegram-обработчики и реестр команд
├── dice/           # Парсер выражений и логика бросков
├── log_format/     # JSON-форматтер логов
└── run.py          # Точка входа
tests/              # Unit-тесты
```

Активные таймеры хранятся в памяти и пропадают при перезапуске бота.
