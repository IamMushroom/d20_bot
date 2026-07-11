# D20 Telegram Bot

Небольшой Telegram-бот для брсков кубов в настольных ролевых играх. Поддерживает математические выражения, броски Daggerheart и таймеры для чата.

## Команды

- `/roll 2d6` — обычный бросок.
- `/roll 1d20 + 4` — бросок с числовым модификатором.
- `/roll 1d12 + 1d6 - 2` — выражение из нескольких кубов и модификаторов.
- `/roll20 d20` — бросок с повышенной вероятностью минимального и максимального значения.
- `/duality` — бросок двух d12 надежды и страха для Daggerheart.
- `/duality 5` — брсок Daggerheart с модификатором.
- `/timer 60` — таймер на 60 секунд.
- `/start` и `/help` — справка по командам.

Алиасы: `/rolld20` для `/roll20`, `/dgh` и `/daggerheart` для `/duality`.

### Синтаксис кубов

Поддерживаются латинские `d`/`D` и кириллические `к`/`К`:

```text
d20
2d6
8к10
1d12 + 1d6
2d20 - 1d4 + 3
```

В выражении разрешены только `+` и `-`. Умножение, деление и скобки не поддерживаются.

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

## Локальный запуск

Требуется Python 3.14.

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
$env:TG_TOKEN = '<telegram-token>'
python src\run.py
```

Для Linux/macOS активация окружения выполняется командой `source .venv/bin/activate`.

## Docker Compose

Создайте `.env`:

```dotenv
TG_TOKEN=<telegram-token>
LOG_FORMAT=json
DOCKER_TAG=latest
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
python -m pip install -r requirements-dev.txt
python -m ruff check .
python -m ruff format --check .
python -m pytest
```

Отчёт о покрытии ветвей:

```shell
python -m pytest --cov=src --cov-branch --cov-report=term-missing
```

## CI/CD

GitHub Actions запускает тесты на Python 3.14. Workflow запуска бота и workflow публикации Docker-образа выполняются только после успешного тестового job.

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
