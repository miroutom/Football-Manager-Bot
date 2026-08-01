# Документация проекта

Football Manager Bot — Telegram-бот для лиг, ЛЧ, трансферов, статистики и ЧМ, плюс локальные утилиты (transfer app, скрипты).

## Быстрый старт

| Задача | Документ |
|--------|----------|
| Запустить бота | [getting-started.md](getting-started.md) |
| Запустить transfer app | [transfer-window-app.md](transfer-window-app.md) |
| Понять структуру репозитория | [project-structure.md](project-structure.md) |

## Функциональность

| Тема | Документ |
|------|----------|
| ЧМ: вызовы, заявка 26, квоты | [world-cup.md](world-cup.md) |
| Правила отображения статистики | [stats_display_rules.md](stats_display_rules.md) |
| Полные правила меню статистики | [stats_menu_rules_full.md](stats_menu_rules_full.md) |
| Миграция `person_id` | [person_id_migration_plan.md](person_id_migration_plan.md) |

## Скрипты и утилиты

| Тема | Документ |
|------|----------|
| Обзор `scripts/` | [scripts.md](scripts.md) |

## Исходники рядом с кодом

- Transfer app (детали сборки): [../tools/transfer_window_app/README.md](../tools/transfer_window_app/README.md)
- Пример env для бота: [../bot/.env.example](../bot/.env.example)

## Куда добавлять новое

- **Общие how-to и процессы** → новый `.md` в `docs/` + ссылка в этом README.
- **Правила домена** (статы, дисциплина, квоты) → `docs/` с говорящим именем.
- **README у инструмента** → только если документ привязан к одной папке (`tools/...`); дублировать краткую выжимку в `docs/`.
