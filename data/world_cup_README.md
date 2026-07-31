# Чемпионат мира (ЧМ)

С сезона **4**, каждые **4** сезона (4, 8, 12…).

| | |
|---|---|
| Месяц | **11** (после финала ЛЧ в месяце 10) |
| БД | `db/season_N/world_cup.db` |
| Конфиг | `data/world_cup_config.json` |
| Заявки | `data/world_cup_squads.json` |

## Статус

Сборные ещё не заданы. Каркас: пути, БД, история, превью.

## Превью

```bash
python3 scripts/preview_world_cup.py
```

Пишет PNG в `assets/history/_preview_world_cup.png` и создаёт пустую `world_cup.db` для сезона 4.

## Заявка

Игроки из клубов (вызов) + ручные добавления сверху (`utils.world_cup.add_manual_callup`), чтобы раскрывшихся на ЧМ можно было забрать в клуб.

## Награды в сезонах ЧМ

ЗМ / бутса / перчатка / Golden Boy — **после** ЧМ.  
Отдельно: **лучший игрок ЧМ** (`world_cup_best` в `season_history.json`).
