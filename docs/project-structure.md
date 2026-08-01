# Структура проекта

Корень репозитория — рабочая директория и для бота, и для скриптов.

```
PythonProject/
├── bot/                 # Telegram-бот (aiogram 3)
├── utils/               # Бизнес-логика, БД, экспорт, ЧМ, трансферы
├── data/                # JSON-конфиги, дисциплина, nicknames, WC
├── db/                  # SQLite, season_state, free_agents.db
├── scripts/             # Одноразовые и maintenance-скрипты
├── tools/               # Отдельные приложения (transfer window app)
├── tests/               # pytest
├── docs/                # Документация (этот каталог)
├── champions_league/    # ЛЧ: сетка, инфографика
├── pickle/              # Pickle-данные (legacy / per_season)
└── requirements.txt
```

## Бот (`bot/`)

| Файл / модуль | Назначение |
|---------------|------------|
| `run_bot.py`, `__main__.py` | Точка входа: `python -m bot` |
| `handlers.py` | Основное меню, клубы, матчи |
| `transfer_handlers.py` | Загрузка трансферного окна |
| `wc_handlers.py` | ЧМ: жеребьёвка, вызовы, заявка 26 |
| `squad_pitch.py` (re-export в bot) | PNG-схемы составов |
| `report_gfx.py`, `standings_infographic.py` | PNG-таблицы и отчёты |
| `.env` | Токен Telegram (не в git) |

## Базы данных (`db/`)

Активный сезон задаётся в `db/season_state.json`:

```json
{
  "data_mode": "legacy" | "per_season",
  "active_season": 4
}
```

- **legacy** — `db/league_synced.db`, `champions_league_synced.db`, …
- **per_season** — `db/season_4/league.db`, …

Накопительная статистика (все сезоны): `*_synced.db` в корне `db/`.

Отдельно: `db/free_agents.db` — пул свободных агентов.

Пути централизованы в `utils/season_paths.py`.

## Данные (`data/`)

| Файл | Содержимое |
|------|------------|
| `player_discipline.json` | ЖК, травмы, дисквалификации |
| `player_nicknames.json` | Прозвища по `person_id` |
| `world_cup_squads.json` | Заявки сборных ЧМ |
| `world_cup.json` | Конфиг наций, формат |

## Utils (`utils/`)

Крупные модули:

- `wc_callups.py`, `wc_squad_quota.py` — заявки ЧМ
- `transfer_window_apply.py` — применение upload из transfer app
- `player_nicknames.py` — короткие имена в UI
- `free_agents_db.py` — FA-пул

## Tools (`tools/`)

- `transfer_window_app/` — локальный сервер + SPA для трансферов

## Тесты

```bash
python3 -m pytest tests/ -q
```

---

См. [scripts.md](scripts.md) для обзора папки `scripts/`.
