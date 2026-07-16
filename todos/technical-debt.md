# Технический долг и эксплуатация

- [x] `TECH-001` Устранить `ResourceWarning` о незакрытых SQLite connections: соединения
  backup-инструмента и его теста явно закрываются.
- [x] `TECH-002` Проверить release-процесс на версии `0.13.0` строго по схеме
  `dev → prd → tag на HEAD prd`.
- [ ] `TECH-003` Проверить восстановление production backup на отдельном тестовом volume, а не
  только создание и чтение копии.
- [ ] `TECH-004` Решить, нужен ли автоматизированный restore-инструмент; восстановление должно
  оставаться явной опасной операцией.
- [ ] `TECH-005` Добавить статическую проверку GitHub Actions workflow, например `actionlint`.
- [ ] `TECH-006` Не перемещать опубликованный тег `0.12.0`; инфраструктурные исправления после него
  выпускать следующей patch-версией.
- [x] `TECH-007` Healthcheck для standalone контейнера: heartbeat asyncio event loop,
  warning-диагностика Telegram API, Docker healthcheck и Kubernetes readiness/liveness probes.
