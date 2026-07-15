# Changelog

Все заметные изменения проекта будут документироваться в этом файле. Формат основан на [Keep a Changelog](https://keepachangelog.com/ru/1.1.0/), версии следуют [Semantic Versioning](https://semver.org/lang/ru/).

## [Unreleased]

### Added

- SQLite-модуль с миграциями, репозиториями и постоянным Docker volume.
- Расписание следующей игры с Foundry-ссылкой и автоматическим закреплением в Telegram.
- Ссылка Foundry по умолчанию через `FOUNDRY_URL` с возможностью переопределения в `/game`.

## [0.11.1] - 2026-07-11

### Added

- Telegram-команды бросков, Daggerheart и таймеров.
- JSON-логи, Docker deployment и GitHub Actions.
- Расширенные броски `kh` и `kl`.
- Structured observability с request/update/user IDs и latency.
- Управление зависимостями через uv lockfile.
- SBOM, provenance и ARM64 CI/CD.
