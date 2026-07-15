# Разработка и CI/CD

## Локальные проверки

```shell
uv sync --frozen
uv run ruff check .
uv run ruff format --check .
uv run pytest
```

Pytest строит отчёт о branch coverage. Порог задаётся в `pytest.ini`; новые ветки поведения
должны сопровождаться тестами.

## Структура проекта

```text
src/
├── commands/       # Telegram-обработчики и реестр команд
├── core/           # Runtime Core и клиент внутреннего API
├── database/       # SQLite, миграции, модели и репозитории
├── dice/           # Парсер выражений и броски
├── log_format/     # JSON-форматирование логов
├── services/       # Сценарии кампаний, расписания и сессий
├── web/            # HTTP API и панель мастера
├── run.py          # Telegram-бот
└── run_core.py     # Core
tests/              # Автоматические тесты
migrations/         # Последовательные SQL-миграции
```

Архитектурные зависимости описаны в [architecture.md](architecture.md), устройство слоя
хранения — в [database.md](database.md).

## CI/CD

GitHub Actions запускает Ruff, тесты в `python:3.14-alpine` и smoke-build runtime-образа на
self-hosted Raspberry Pi. После deploy workflow проверяет, что контейнер не завершился при
инициализации. Публикуемые образы содержат SBOM и provenance attestations. Код из fork pull
request не запускается на self-hosted runner.

Dependabot еженедельно проверяет Python-пакеты, GitHub Actions и Docker base image, объединяя
экосистемы в один multi-ecosystem pull request. Push в `dev` запускает dev-deploy; push в
`prd` сам по себе ничего не разворачивает.

Релизный тег `vX.Y.Z` должен совпадать с версией в `pyproject.toml`. Тег публикует ARM64-образы
в Docker Hub и GHCR, подписывает их через Cosign, создаёт GitHub Release и разворачивает
production-образ с этим тегом.

Runner должен иметь:

- лейблы `self-hosted` и `raspberry`;
- Docker Engine, Buildx и Docker Compose v2;
- доступ runner-пользователя к Docker daemon;
- `TG_TOKEN` в GitHub Environment с именем ветки;
- `DOCKER_HUB_TOKEN`, `DOCKER_HUB_NAME` и environment `prd` для публикации.

## Почему docs, а не GitHub Wiki

Документация в `docs/` версионируется тем же коммитом, что и код, проходит review в pull
request и корректно отображается GitHub. Wiki хранится в отдельном Git-репозитории и легче
расходится с фактической версией приложения. При необходимости `docs/` позднее можно без
переноса содержания опубликовать через MkDocs и GitHub Pages.
