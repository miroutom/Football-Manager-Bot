# Скрипты (`scripts/`)

Большинство скриптов запускаются **из корня проекта**:

```bash
python3 scripts/имя_скрипта.py [--apply] [опции]
```

Многие поддерживают dry-run без `--apply` — сначала смотри вывод, потом применяй.

## Часто используемые

| Скрипт | Назначение |
|--------|------------|
| `assign_player_nicknames.py` | Интерактивно задать прозвища игрокам |
| `import_removed_players_to_fa.py` | Импорт архивных игроков в `free_agents.db` |
| `apply_transfer_window_state.py` | Применить JSON состояния transfer app к БД |
| `export_transfer_window_squads_xlsx.py` | Excel составов для окна |
| `assign_person_ids_active_season.py` | Проставить `person_id` в активном сезоне |
| `local_bootstrap_active_season.py` | Локальная инициализация сезона |

## Трансферы и составы

- `apply_bulk_squad_declarations.py`
- `apply_left_team_from_transfers.py`
- `build_transfer_draft_v3.py`
- `transfer_market_draft.py`
- `sync_*_rosters.py` — синхронизация составов лиг (APL, RPL, …)

## Статистика и починка данных

- `apply_stats_from_screens.py` / `dry_run_stats_from_screens.py`
- `fix_player_stats_batch.py`
- `restore_stats_from_backup.py`
- `merge_duplicate_player_rows.py`

## ЧМ

- `preview_world_cup.py` — превью данных турнира

## Правило

Новый скрипт: короткий docstring в начале файла (что делает, пример запуска). Если скрипт часть рабочего процесса — добавь строку в эту таблицу или отдельный `docs/*.md`.

Полный список: `ls scripts/*.py` (~100 файлов; многие — разовые фиксы сезона).
