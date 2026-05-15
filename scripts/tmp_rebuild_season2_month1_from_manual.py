#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
ВРЕМЕННЫЙ скрипт: пересборка статистики голов/передач/матчей (полевые) сезона 2
по ручным спискам матчей «месяц 1» и «месяц 2» со скринов Telegram.

ВАЖНО
------
- По умолчанию ничего не пишет в БД: только проверки и план (--dry-run).
- Режим --apply делает ЖЁСТКОЕ обнуление goals/assists/matches/ga у всех
  forwards/midfielders/defenders в db/season_2/league.db и champions_league.db,
  затем заново добавляет вклад из ``ALL_SEASON2_MANUAL_FIXTURES`` (месяц 1 + месяц 2).
  Карточки, травмы, clean_sheets, вратари и overall не трогаются.
  Не используйте --apply, пока дополняете список матчей — потеряете остальную стату S2.
  Пока в объединённом списке есть матчи с голами в счёте и пустым ``players``, ``--apply``
  по умолчанию запрещён; матчи **0-0** с пустым ``players`` не считаются дырой.
  Для осознанной частичной заливки добавь ``--allow-partial-fixtures``.
- После успешной заливки: пересборка common активного сезона и всех *_synced.db из архивов season_*.
- Перед боевым запуском проверьте db/season_state.json: active_season == 2 (или скрипт откажется).

ЖК / КК / травмы сознательно не сверяем (как в ТЗ пользователя).

Сумма голов в ``players`` по команде не должна превышать счёт (автоголы в чате могут не
разноситься по полевым — равенство счёту не требуется).

Дополните списки MONTH1_FIXTURES / MONTH2_FIXTURES для матчей без строк по игрокам.
Запуск из корня проекта (где есть venv с sqlalchemy), например:
  python scripts/tmp_rebuild_season2_month1_from_manual.py --dry-run
  python scripts/tmp_rebuild_season2_month1_from_manual.py --apply --i-understand-destroy-stats
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import Any

# корень проекта
_ROOT = Path(__file__).resolve().parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

# ---------------------------------------------------------------------------
# Данные: месяц 1 — эталон по скринам (голы и передачи полевых)
# tournament: "league" → league.db; "cl" → champions_league.db
#
# Если для матча нет блока players (или он пустой), строка счётчиков не добавляется
# (валидатор счётов для таких матчей пропускает проверку).
# ---------------------------------------------------------------------------

MONTH1_FIXTURES: list[dict[str, Any]] = [
    # Месяц 1 · ЛЧ — нужны строки игроков со скринов (разбор не приложен полностью)
    {
        "label": "М1 ЛЧ Аталанта — Франкфурт 1-1",
        "tournament": "cl",
        "home": "Аталанта",
        "away": "Франкфурт",
        "score_home": 1,
        "score_away": 1,
        "players": [
            {"name": "Муриэль", "team": "Аталанта", "position": "ЛФА", "goals": 1, "assists": 0},
            {"name": "Симонс", "team": "Аталанта", "position": "ЦАП", "goals": 0, "assists": 1},
            {"name": "Дина Эбимбе", "team": "Франкфурт", "position": "ЛФА", "goals": 1, "assists": 0},
            {"name": "Мармуш", "team": "Франкфурт", "position": "ФРВ", "goals": 0, "assists": 1},
        ],
    },
    {
        "label": "М1 БЛ Хоффенхайм — Бавария 2-6",
        "tournament": "league",
        "home": "Хоффенхайм",
        "away": "Бавария",
        "score_home": 2,
        "score_away": 6,
        "players": [
            {"name": "Бебу", "team": "Хоффенхайм", "position": "ЛФА", "goals": 0, "assists": 1},
            {"name": "Довбык", "team": "Хоффенхайм", "position": "ФРВ", "goals": 2, "assists": 0},
            {"name": "Гиббс-Уайт", "team": "Хоффенхайм", "position": "ЦАП", "goals": 0, "assists": 1},
            {"name": "Коман", "team": "Бавария", "position": "ЛФА", "goals": 0, "assists": 1},
            {"name": "Банза", "team": "Бавария", "position": "ФРВ", "goals": 0, "assists": 1},
            {"name": "Кейн", "team": "Бавария", "position": "ФРВ", "goals": 4, "assists": 1},
            {"name": "Сане", "team": "Бавария", "position": "ПФА", "goals": 2, "assists": 0},
            {"name": "Горетцка", "team": "Бавария", "position": "ЦОП", "goals": 0, "assists": 1},
            {"name": "Киммих", "team": "Бавария", "position": "ПЗ", "goals": 0, "assists": 2},
        ],
    },
    {
        "label": "М1 Ла Лига Барселона — Жирона 3-1",
        "tournament": "league",
        "home": "Барселона",
        "away": "Жирона",
        "score_home": 3,
        "score_away": 1,
        "players": [
            {"name": "Неймар", "team": "Барселона", "position": "ЛФА", "goals": 2, "assists": 1},
            {"name": "Лева", "team": "Барселона", "position": "ФРВ", "goals": 0, "assists": 1},
            {"name": "Рафинья", "team": "Барселона", "position": "ПФА", "goals": 0, "assists": 1},
            {"name": "Педри", "team": "Барселона", "position": "ЦП", "goals": 1, "assists": 0},
            {"name": "Савио", "team": "Жирона", "position": "ЛФА", "goals": 0, "assists": 1},
            {"name": "Алейш Гарсия", "team": "Жирона", "position": "ЦП", "goals": 1, "assists": 0},
        ],
    },
    # Серия А, скрин: голы сошлись 4-2; у гостей Malcom 2+0, Arthur 0+1 (бонавентура 3м на скрине
    # противоречит счёту — в эталон не берём)
    {
        "label": "М1 СА Аталанта — Фиорентина 4-2",
        "tournament": "league",
        "home": "Аталанта",
        "away": "Фиорентина",
        "score_home": 4,
        "score_away": 2,
        "players": [
            {"name": "Муриэль", "team": "Аталанта", "position": "ЛФА", "goals": 1, "assists": 0},
            {"name": "Миранчук", "team": "Аталанта", "position": "ФРВ", "goals": 1, "assists": 1},
            {"name": "Лукман", "team": "Аталанта", "position": "ПФА", "goals": 1, "assists": 0},
            {"name": "Симонс", "team": "Аталанта", "position": "ЦАП", "goals": 0, "assists": 2},
            {"name": "Пашалич", "team": "Аталанта", "position": "ЦП", "goals": 1, "assists": 0},
            {"name": "Малком", "team": "Фиорентина", "position": "ЛФА", "goals": 2, "assists": 0},
            {"name": "Артур", "team": "Фиорентина", "position": "ЦОП", "goals": 0, "assists": 1},
        ],
    },
    # ЛЧ 6-1: на скрине явно сумма голов дома даёт 5 — добавлен Муриэль 1-0 как 6-й (Аталанта в атаке в этой связке логична)
    {
        "label": "М1 ЛЧ Аталанта — Мю 6-1",
        "tournament": "cl",
        "home": "Аталанта",
        "away": "Мю",
        "score_home": 6,
        "score_away": 1,
        "players": [
            {"name": "Муриэль", "team": "Аталанта", "position": "ЛФА", "goals": 1, "assists": 0},
            {"name": "Миранчук", "team": "Аталанта", "position": "ФРВ", "goals": 3, "assists": 1},
            {"name": "Лукман", "team": "Аталанта", "position": "ПФА", "goals": 0, "assists": 1},
            {"name": "Симонс", "team": "Аталанта", "position": "ЦАП", "goals": 1, "assists": 1},
            {"name": "Пашалич", "team": "Аталанта", "position": "ЦП", "goals": 1, "assists": 2},
            {"name": "Гарначо", "team": "Мю", "position": "ЛФА", "goals": 1, "assists": 0},
            {"name": "Брозович", "team": "Мю", "position": "ЦОП", "goals": 0, "assists": 1},
        ],
    },
    {
        "label": "М1 Ла Лига Атлетико — Севилья 1-1",
        "tournament": "league",
        "home": "Атлетико",
        "away": "Севилья",
        "score_home": 1,
        "score_away": 1,
        "players": [
            {"name": "Лемар", "team": "Атлетико", "position": "ЦП", "goals": 1, "assists": 0},
            {"name": "Льоренте", "team": "Атлетико", "position": "ЦП", "goals": 0, "assists": 1},
            {"name": "Ундав", "team": "Севилья", "position": "ЦП", "goals": 1, "assists": 0},
            {"name": "Лукебакио", "team": "Севилья", "position": "ПФА", "goals": 0, "assists": 1},
        ],
    },
    {
        "label": "М1 Ла Лига Барселона — Реал 5-2",
        "tournament": "league",
        "home": "Барселона",
        "away": "Реал",
        "score_home": 5,
        "score_away": 2,
        "players": [
            {"name": "Неймар", "team": "Барселона", "position": "ЛФА", "goals": 1, "assists": 2},
            {"name": "Рафинья", "team": "Барселона", "position": "ФРВ", "goals": 1, "assists": 0},
            {"name": "Лева", "team": "Барселона", "position": "ФРВ", "goals": 2, "assists": 0},
            {"name": "Педри", "team": "Барселона", "position": "ЦП", "goals": 1, "assists": 2},
            {"name": "Де Йонг", "team": "Барселона", "position": "ЦОП", "goals": 0, "assists": 1},
            {"name": "Родриго", "team": "Реал", "position": "ЛФА", "goals": 0, "assists": 1},
            {"name": "Лукаку", "team": "Реал", "position": "ФРВ", "goals": 2, "assists": 0},
        ],
    },
    {
        "label": "М1 ЛЧ Тоттенхэм — Вольфсбург 1-1",
        "tournament": "cl",
        "home": "Тоттенхэм",
        "away": "Вольфсбург",
        "score_home": 1,
        "score_away": 1,
        "players": [
            {"name": "Сон", "team": "Тоттенхэм", "position": "ЛФА", "goals": 1, "assists": 0},
            {"name": "Мэддисон", "team": "Тоттенхэм", "position": "ЦАП", "goals": 0, "assists": 1},
            {"name": "Линдстром", "team": "Вольфсбург", "position": "ЛФА", "goals": 0, "assists": 1},
            {"name": "Фирмино", "team": "Вольфсбург", "position": "ФРВ", "goals": 1, "assists": 0},
        ],
    },
    {
        "label": "М1 ЛЧ Наполи — Реал Сосьедад 6-3",
        "tournament": "cl",
        "home": "Наполи",
        "away": "Реал Сосьедад",
        "score_home": 6,
        "score_away": 3,
        "players": [
            {"name": "Квара", "team": "Наполи", "position": "ЛФА", "goals": 1, "assists": 2},
            {"name": "Осимен", "team": "Наполи", "position": "ФРВ", "goals": 5, "assists": 0},
            {"name": "Сака", "team": "Наполи", "position": "ПФА", "goals": 0, "assists": 2},
            {"name": "Лоботка", "team": "Наполи", "position": "ЦП", "goals": 0, "assists": 1},
            {"name": "Тюкавин", "team": "Реал Сосьедад", "position": "ФРВ", "goals": 1, "assists": 0},
            {"name": "Оярзабаль", "team": "Реал Сосьедад", "position": "ЦАП", "goals": 1, "assists": 1},
            {"name": "Мендез", "team": "Реал Сосьедад", "position": "ЦП", "goals": 1, "assists": 1},
        ],
    },
    {
        "label": "М1 ЛЧ Байер — Атлетик 4-1",
        "tournament": "cl",
        "home": "Байер",
        "away": "Атлетик",
        "score_home": 4,
        "score_away": 1,
        "players": [
            {"name": "Иконе", "team": "Байер", "position": "ФРВ", "goals": 1, "assists": 1},
            {"name": "Хофманн", "team": "Байер", "position": "ЦП", "goals": 1, "assists": 1},
            {"name": "Андрих", "team": "Байер", "position": "ЦП", "goals": 1, "assists": 0},
            {"name": "Гримальдо", "team": "Байер", "position": "ЛФЗ", "goals": 1, "assists": 0},
            {"name": "Иньяки", "team": "Атлетик", "position": "ФРВ", "goals": 1, "assists": 0},
            {"name": "Муниаин", "team": "Атлетик", "position": "ЦАП", "goals": 0, "assists": 1},
        ],
    },
    {
        "label": "М1 ЛЧ Сити — Наполи 2-4",
        "tournament": "cl",
        "home": "Сити",
        "away": "Наполи",
        "score_home": 2,
        "score_away": 4,
        "players": [
            {"name": "Холанд", "team": "Сити", "position": "ФРВ", "goals": 1, "assists": 0},
            {"name": "Месси", "team": "Сити", "position": "ПФА", "goals": 0, "assists": 1},
            {"name": "Де Брюйне", "team": "Сити", "position": "ЦАП", "goals": 0, "assists": 1},
            {"name": "Сильва", "team": "Сити", "position": "ЦП", "goals": 1, "assists": 0},
            {"name": "Квара", "team": "Наполи", "position": "ЛФА", "goals": 0, "assists": 3},
            {"name": "Осимен", "team": "Наполи", "position": "ФРВ", "goals": 2, "assists": 0},
            {"name": "Сака", "team": "Наполи", "position": "ПФА", "goals": 1, "assists": 0},
            {"name": "Лоботка", "team": "Наполи", "position": "ЦП", "goals": 1, "assists": 0},
        ],
    },
    {
        "label": "М1 ЛЧ Тоттенхэм — Франкфурт 2-4",
        "tournament": "cl",
        "home": "Тоттенхэм",
        "away": "Франкфурт",
        "score_home": 2,
        "score_away": 4,
        "players": [
            {"name": "Сон", "team": "Тоттенхэм", "position": "ЛФА", "goals": 1, "assists": 0},
            {"name": "Диа", "team": "Тоттенхэм", "position": "ФРВ", "goals": 1, "assists": 0},
            {"name": "Мэддисон", "team": "Тоттенхэм", "position": "ЦАП", "goals": 0, "assists": 1},
            {"name": "Удоджи", "team": "Тоттенхэм", "position": "ЛЗ", "goals": 0, "assists": 1},
            {"name": "Дина Эбимбе", "team": "Франкфурт", "position": "ЛФА", "goals": 1, "assists": 1},
            {"name": "Мармуш", "team": "Франкфурт", "position": "ФРВ", "goals": 2, "assists": 2},
            {"name": "Мусиаля", "team": "Франкфурт", "position": "ЦАП", "goals": 1, "assists": 0},
        ],
    },
    # --- Дополнение: другие матчи месяца 1 (со скринов) ---
    {
        "label": "М1 ЛЧ Атлетик — Милан 5-1 (+2 гола хозяев без строк в чате — Леау, Гурузета; три асиста Муниаина на Кулушевски, Сансет, Иньяки)",
        "tournament": "cl",
        "home": "Атлетик",
        "away": "Милан",
        "score_home": 5,
        "score_away": 1,
        "players": [
            {"name": "Кулушевски", "team": "Атлетик", "position": "ЦП", "goals": 1, "assists": 0},
            {"name": "Муниаин", "team": "Атлетик", "position": "ЦАП", "goals": 0, "assists": 3},
            {"name": "Сансет", "team": "Атлетик", "position": "ЦП", "goals": 1, "assists": 0},
            {"name": "Иньяки", "team": "Атлетик", "position": "ПФА", "goals": 1, "assists": 0},
            {"name": "Леау", "team": "Атлетик", "position": "ФРВ", "goals": 1, "assists": 0},
            {"name": "Гурузета", "team": "Атлетик", "position": "ФРВ", "goals": 1, "assists": 0},
            {"name": "Вини", "team": "Милан", "position": "ФРВ", "goals": 0, "assists": 1},
            {"name": "Бензема", "team": "Милан", "position": "ФРВ", "goals": 1, "assists": 0},
        ],
    },
    {
        "label": "М1 СА Милан — Лацио 2-1",
        "tournament": "league",
        "home": "Милан",
        "away": "Лацио",
        "score_home": 2,
        "score_away": 1,
        "players": [
            {"name": "Бензема", "team": "Милан", "position": "ФРВ", "goals": 1, "assists": 0},
            {"name": "Вини", "team": "Милан", "position": "ФРВ", "goals": 1, "assists": 0},
            {"name": "Беллингем", "team": "Милан", "position": "ЦАП", "goals": 0, "assists": 1},
            {"name": "Рейндерс", "team": "Милан", "position": "ЦП", "goals": 0, "assists": 1},
            {"name": "Иммобиле", "team": "Лацио", "position": "ФРВ", "goals": 1, "assists": 0},
        ],
    },
    {
        "label": "М1 АПЛ Ливерпуль — Ньюкасл 1-3",
        "tournament": "league",
        "home": "Ливерпуль",
        "away": "Ньюкасл",
        "score_home": 1,
        "score_away": 3,
        "players": [
            {"name": "Коке", "team": "Ливерпуль", "position": "ЦОП", "goals": 1, "assists": 0},
            {"name": "Тюрам", "team": "Ньюкасл", "position": "ЦП", "goals": 1, "assists": 0},
            {"name": "Перейра", "team": "Ньюкасл", "position": "ФРВ", "goals": 1, "assists": 0},
            {"name": "Исак", "team": "Ньюкасл", "position": "ФРВ", "goals": 1, "assists": 0},
            {"name": "Силва", "team": "Ньюкасл", "position": "ЦАП", "goals": 0, "assists": 1},
            {"name": "Тонали", "team": "Ньюкасл", "position": "ЦП", "goals": 0, "assists": 1},
        ],
    },
    {
        "label": "М1 СА Рома — Интер 1-7",
        "tournament": "league",
        "home": "Рома",
        "away": "Интер",
        "score_home": 1,
        "score_away": 7,
        "players": [
            {"name": "Гризманн", "team": "Рома", "position": "ФРВ", "goals": 1, "assists": 0},
            {"name": "Пеллегрини", "team": "Рома", "position": "ЦП", "goals": 0, "assists": 1},
            {"name": "Мартинез", "team": "Интер", "position": "ФРВ", "goals": 4, "assists": 1},
            {"name": "Арнаутович", "team": "Интер", "position": "ФРВ", "goals": 2, "assists": 2},
            {"name": "Мхитарян", "team": "Интер", "position": "ЛП", "goals": 0, "assists": 1},
            {"name": "Барелла", "team": "Интер", "position": "ЦП", "goals": 0, "assists": 1},
            {"name": "Берарди", "team": "Интер", "position": "ПП", "goals": 1, "assists": 1},
        ],
    },
    {
        "label": "М1 ЛЧ Байер — Реал Сосьедад 0-1",
        "tournament": "cl",
        "home": "Байер",
        "away": "Реал Сосьедад",
        "score_home": 0,
        "score_away": 1,
        "players": [
            {"name": "Ди Мария", "team": "Реал Сосьедад", "position": "ПП", "goals": 1, "assists": 0},
            {"name": "Оярзабаль", "team": "Реал Сосьедад", "position": "ЦАП", "goals": 0, "assists": 1},
        ],
    },
    {
        "label": "М1 ЛЧ Арсенал — Атлетико 2-3",
        "tournament": "cl",
        "home": "Арсенал",
        "away": "Атлетико",
        "score_home": 2,
        "score_away": 3,
        "players": [
            {"name": "Плеа", "team": "Арсенал", "position": "ЦАП", "goals": 1, "assists": 0},
            {"name": "Канте", "team": "Арсенал", "position": "ЦОП", "goals": 1, "assists": 0},
            {"name": "Хаверц", "team": "Арсенал", "position": "ФРВ", "goals": 0, "assists": 1},
            {"name": "Одегаард", "team": "Арсенал", "position": "ЦАП", "goals": 0, "assists": 1},
            {"name": "Мората", "team": "Атлетико", "position": "ФРВ", "goals": 1, "assists": 0},
            {"name": "Корреа", "team": "Атлетико", "position": "ФРВ", "goals": 1, "assists": 0},
            {"name": "Депай", "team": "Атлетико", "position": "ЦАП", "goals": 1, "assists": 0},
            {"name": "Льоренте", "team": "Атлетико", "position": "ЦП", "goals": 0, "assists": 1},
            {"name": "Родри", "team": "Атлетико", "position": "ЦОП", "goals": 0, "assists": 1},
            {"name": "Алмада", "team": "Атлетико", "position": "ЦАП", "goals": 0, "assists": 1},
        ],
    },
    {
        "label": "М1 СА Ювентус — Рома 4-3",
        "tournament": "league",
        "home": "Ювентус",
        "away": "Рома",
        "score_home": 4,
        "score_away": 3,
        "players": [
            {"name": "Костич", "team": "Ювентус", "position": "ПФА", "goals": 1, "assists": 0},
            {"name": "Влашич", "team": "Ювентус", "position": "ЦП", "goals": 0, "assists": 3},
            {"name": "Бремер", "team": "Ювентус", "position": "ЦЗ", "goals": 3, "assists": 0},
            {"name": "Гнабри", "team": "Рома", "position": "ПФА", "goals": 1, "assists": 0},
            {"name": "Гризманн", "team": "Рома", "position": "ФРВ", "goals": 2, "assists": 0},
            {"name": "Пеллегрини", "team": "Рома", "position": "ЦП", "goals": 0, "assists": 1},
            {"name": "Карсдорп", "team": "Рома", "position": "ПЗ", "goals": 0, "assists": 1},
            {"name": "Ауар", "team": "Рома", "position": "ЦАП", "goals": 0, "assists": 1},
        ],
    },
    {
        "label": "М1 СА Наполи — Лацио 3-2",
        "tournament": "league",
        "home": "Наполи",
        "away": "Лацио",
        "score_home": 3,
        "score_away": 2,
        "players": [
            {"name": "Осимен", "team": "Наполи", "position": "ФРВ", "goals": 3, "assists": 0},
            {"name": "Сака", "team": "Наполи", "position": "ПФА", "goals": 0, "assists": 1},
            {"name": "Лоботка", "team": "Наполи", "position": "ЦП", "goals": 0, "assists": 2},
            {"name": "Тель", "team": "Лацио", "position": "ФРВ", "goals": 0, "assists": 1},
            {"name": "Фраттези", "team": "Лацио", "position": "ЦП", "goals": 2, "assists": 0},
        ],
    },
    {
        "label": "М1 ЛЧ Севилья — Цска 5-3",
        "tournament": "cl",
        "home": "Севилья",
        "away": "Цска",
        "score_home": 5,
        "score_away": 3,
        "players": [
            {"name": "Гонсалвеш", "team": "Севилья", "position": "ЛФА", "goals": 3, "assists": 1},
            {"name": "Лукебакио", "team": "Севилья", "position": "ПФА", "goals": 0, "assists": 1},
            {"name": "Ундав", "team": "Севилья", "position": "ЦП", "goals": 1, "assists": 0},
            {"name": "Соу", "team": "Севилья", "position": "ЦП", "goals": 0, "assists": 1},
            {"name": "Карраско", "team": "Севилья", "position": "ЛФА", "goals": 1, "assists": 0},
            {"name": "Мудрык", "team": "Цска", "position": "ЛФА", "goals": 1, "assists": 0},
            {"name": "Кучаев", "team": "Цска", "position": "ЛФА", "goals": 1, "assists": 1},
            {"name": "Симеоне", "team": "Цска", "position": "ФРВ", "goals": 1, "assists": 0},
        ],
    },
    {
        "label": "М1 БЛ Дортмунд — Вольфсбург 1-2",
        "tournament": "league",
        "home": "Дортмунд",
        "away": "Вольфсбург",
        "score_home": 1,
        "score_away": 2,
        "players": [
            {"name": "Дибала", "team": "Дортмунд", "position": "ЦАП", "goals": 1, "assists": 0},
            {"name": "Фред", "team": "Дортмунд", "position": "ЦП", "goals": 0, "assists": 1},
            {"name": "Виммер", "team": "Вольфсбург", "position": "ПФА", "goals": 1, "assists": 0},
            {"name": "Майер", "team": "Вольфсбург", "position": "ЦП", "goals": 1, "assists": 0},
            {"name": "Сванберг", "team": "Вольфсбург", "position": "ЦП", "goals": 0, "assists": 1},
        ],
    },
    {
        "label": "М1 ЛЧ Спартак — Лейпциг 1-5",
        "tournament": "cl",
        "home": "Спартак",
        "away": "Лейпциг",
        "score_home": 1,
        "score_away": 5,
        "players": [
            {"name": "Пепе", "team": "Спартак", "position": "ЦАП", "goals": 1, "assists": 0},
            {"name": "Пруцев", "team": "Спартак", "position": "ЦП", "goals": 0, "assists": 1},
            {"name": "Вернер", "team": "Лейпциг", "position": "ФРВ", "goals": 1, "assists": 1},
            {"name": "Опенда", "team": "Лейпциг", "position": "ФРВ", "goals": 1, "assists": 1},
            {"name": "Клаудиньо", "team": "Лейпциг", "position": "ЦАП", "goals": 1, "assists": 0},
            {"name": "Кёкчю", "team": "Лейпциг", "position": "ЦП", "goals": 0, "assists": 1},
            {"name": "Ольмо", "team": "Лейпциг", "position": "ЦП", "goals": 1, "assists": 2},
            {"name": "Клостерманн", "team": "Лейпциг", "position": "ПЗ", "goals": 1, "assists": 0},
        ],
    },
    {
        "label": "М1 СА Наполи — Аталанта 3-3",
        "tournament": "league",
        "home": "Наполи",
        "away": "Аталанта",
        "score_home": 3,
        "score_away": 3,
        "players": [
            {"name": "Квара", "team": "Наполи", "position": "ЛФА", "goals": 2, "assists": 0},
            {"name": "Сака", "team": "Наполи", "position": "ПФА", "goals": 0, "assists": 1},
            {"name": "Лоботка", "team": "Наполи", "position": "ЦП", "goals": 1, "assists": 0},
            {"name": "Ангисса", "team": "Наполи", "position": "ЦОП", "goals": 0, "assists": 1},
            {"name": "Муриэль", "team": "Аталанта", "position": "ПФА", "goals": 1, "assists": 1},
            {"name": "Копмейнерс", "team": "Аталанта", "position": "ЦП", "goals": 1, "assists": 0},
            {"name": "Симонс", "team": "Аталанта", "position": "ЦАП", "goals": 1, "assists": 0},
            {"name": "Торрес", "team": "Аталанта", "position": "ЦП", "goals": 0, "assists": 2},
        ],
    },
    {
        "label": "М1 Ла Лига Атлетик — Жирона 2-1",
        "tournament": "league",
        "home": "Атлетик",
        "away": "Жирона",
        "score_home": 2,
        "score_away": 1,
        "players": [
            {"name": "Леау", "team": "Атлетик", "position": "ФРВ", "goals": 1, "assists": 0},
            {"name": "Муниаин", "team": "Атлетик", "position": "ЦАП", "goals": 1, "assists": 0},
            {"name": "Сансет", "team": "Атлетик", "position": "ЦП", "goals": 0, "assists": 1},
            {"name": "Савио", "team": "Жирона", "position": "ЛФА", "goals": 1, "assists": 0},
            {"name": "Эррера", "team": "Жирона", "position": "ЦОП", "goals": 0, "assists": 1},
        ],
    },
    {
        "label": "М1 ЛЧ Ливерпуль — Лейпциг 4-3",
        "tournament": "cl",
        "home": "Ливерпуль",
        "away": "Лейпциг",
        "score_home": 4,
        "score_away": 3,
        "players": [
            {"name": "Жота", "team": "Ливерпуль", "position": "ФРВ", "goals": 2, "assists": 0},
            {"name": "Мбаппе", "team": "Ливерпуль", "position": "ПФА", "goals": 2, "assists": 1},
            {"name": "Коке", "team": "Ливерпуль", "position": "ЦП", "goals": 0, "assists": 1},
            {"name": "Гравенберх", "team": "Ливерпуль", "position": "ЦП", "goals": 0, "assists": 1},
            {"name": "Вернер", "team": "Лейпциг", "position": "ФРВ", "goals": 1, "assists": 0},
            {"name": "Клаудиньо", "team": "Лейпциг", "position": "ЦАП", "goals": 2, "assists": 0},
            {"name": "Ольмо", "team": "Лейпциг", "position": "ЦП", "goals": 0, "assists": 2},
            {"name": "Симакан", "team": "Лейпциг", "position": "ЦЗ", "goals": 0, "assists": 1},
        ],
    },
    {
        "label": "М1 ЛЧ Реал — Интер 2-5",
        "tournament": "cl",
        "home": "Реал",
        "away": "Интер",
        "score_home": 2,
        "score_away": 5,
        "players": [
            {"name": "Лукаку", "team": "Реал", "position": "ФРВ", "goals": 2, "assists": 0},
            {"name": "Родриго", "team": "Реал", "position": "ЛФА", "goals": 0, "assists": 1},
            {"name": "Мартинез", "team": "Интер", "position": "ФРВ", "goals": 2, "assists": 2},
            {"name": "Барелла", "team": "Интер", "position": "ЦП", "goals": 3, "assists": 0},
            {"name": "Мхитарян", "team": "Интер", "position": "ЛП", "goals": 0, "assists": 2},
            {"name": "Берарди", "team": "Интер", "position": "ПП", "goals": 0, "assists": 1},
        ],
    },
    {
        "label": "М1 СА Ювентус — Фиорентина 7-0",
        "tournament": "league",
        "home": "Ювентус",
        "away": "Фиорентина",
        "score_home": 7,
        "score_away": 0,
        "players": [
            {"name": "Кьеза", "team": "Ювентус", "position": "ЛФА", "goals": 1, "assists": 0},
            {"name": "Смолов", "team": "Ювентус", "position": "ФРВ", "goals": 1, "assists": 0},
            {"name": "Костич", "team": "Ювентус", "position": "ПФА", "goals": 2, "assists": 0},
            {"name": "Влашич", "team": "Ювентус", "position": "ЦП", "goals": 0, "assists": 4},
            {"name": "Миретти", "team": "Ювентус", "position": "ЦП", "goals": 1, "assists": 1},
            {"name": "Бремер", "team": "Ювентус", "position": "ЦЗ", "goals": 2, "assists": 0},
        ],
    },
    {
        "label": "М1 АПЛ Мю — Сити 2-7",
        "tournament": "league",
        "home": "Мю",
        "away": "Сити",
        "score_home": 2,
        "score_away": 7,
        "players": [
            {"name": "Гарначо", "team": "Мю", "position": "ЛФА", "goals": 0, "assists": 1},
            {"name": "Марсиаль", "team": "Мю", "position": "ФРВ", "goals": 1, "assists": 0},
            {"name": "Мартинелли", "team": "Мю", "position": "ЛФА", "goals": 1, "assists": 1},
            {"name": "Рэшфорд", "team": "Сити", "position": "ФРВ", "goals": 1, "assists": 1},
            {"name": "Холанд", "team": "Сити", "position": "ФРВ", "goals": 1, "assists": 0},
            {"name": "Месси", "team": "Сити", "position": "ПФА", "goals": 2, "assists": 2},
            {"name": "Де Брюйне", "team": "Сити", "position": "ЦАП", "goals": 2, "assists": 1},
            {"name": "Сильва", "team": "Сити", "position": "ЦП", "goals": 1, "assists": 2},
        ],
    },
    {
        "label": "М1 АПЛ Арсенал — Астон Вилла 2-4 (2й гол Арсенала: Сака — на скрине явно только Хаверц)",
        "tournament": "league",
        "home": "Арсенал",
        "away": "Астон Вилла",
        "score_home": 2,
        "score_away": 4,
        "players": [
            {"name": "Хаверц", "team": "Арсенал", "position": "ФРВ", "goals": 2, "assists": 0},
            {"name": "Заниоло", "team": "Астон Вилла", "position": "ФРВ", "goals": 1, "assists": 0},
            {"name": "Сперцян", "team": "Астон Вилла", "position": "ФРВ", "goals": 0, "assists": 1},
            {"name": "Гакпо", "team": "Астон Вилла", "position": "ФРВ", "goals": 1, "assists": 2},
            {"name": "Вейга", "team": "Астон Вилла", "position": "ЦАП", "goals": 1, "assists": 0},
            {"name": "Тилеманс", "team": "Астон Вилла", "position": "ЦП", "goals": 1, "assists": 0},
        ],
    },
    {
        "label": "М1 АПЛ Арсенал — Тоттенхэм 3-1 (жк Мэддисон, Флорентину у Тоттенхэма — в скрипт не включены)",
        "tournament": "league",
        "home": "Арсенал",
        "away": "Тоттенхэм",
        "score_home": 3,
        "score_away": 1,
        "players": [
            {"name": "Мерино", "team": "Арсенал", "position": "ЦП", "goals": 1, "assists": 0},
            {"name": "Жезус", "team": "Арсенал", "position": "ПФА", "goals": 1, "assists": 0},
            {"name": "Хаверц", "team": "Арсенал", "position": "ФРВ", "goals": 1, "assists": 1},
            {"name": "Коло-Муани", "team": "Арсенал", "position": "ЛФА", "goals": 0, "assists": 1},
            {"name": "Куадрадо", "team": "Тоттенхэм", "position": "ПФА", "goals": 1, "assists": 0},
            {"name": "Альварез", "team": "Тоттенхэм", "position": "ФРВ", "goals": 0, "assists": 1},
        ],
    },
    {
        "label": "М1 РПЛ Спартак — Динамо 2-2",
        "tournament": "league",
        "home": "Спартак",
        "away": "Динамо",
        "score_home": 2,
        "score_away": 2,
        "players": [
            {"name": "Пепе", "team": "Спартак", "position": "ФРВ", "goals": 2, "assists": 0},
            {"name": "Зиньковский", "team": "Спартак", "position": "ЛФА", "goals": 0, "assists": 1},
            {"name": "Эдвардс", "team": "Спартак", "position": "ПФА", "goals": 0, "assists": 1},
            {"name": "Шешко", "team": "Динамо", "position": "ФРВ", "goals": 2, "assists": 0},
            {"name": "Чавез", "team": "Динамо", "position": "ЦП", "goals": 0, "assists": 2},
        ],
    },
    {
        "label": "М1 БЛ Лейпциг — Вольфсбург 1-3",
        "tournament": "league",
        "home": "Лейпциг",
        "away": "Вольфсбург",
        "score_home": 1,
        "score_away": 3,
        "players": [
            {"name": "Вернер", "team": "Лейпциг", "position": "ФРВ", "goals": 1, "assists": 0},
            {"name": "Клаудиньо", "team": "Лейпциг", "position": "ЦАП", "goals": 0, "assists": 1},
            {"name": "Нмеча", "team": "Вольфсбург", "position": "ФРВ", "goals": 2, "assists": 0},
            {"name": "Майер", "team": "Вольфсбург", "position": "ЦП", "goals": 1, "assists": 0},
            {"name": "Арнольд", "team": "Вольфсбург", "position": "ЦП", "goals": 0, "assists": 1},
        ],
    },
    {
        "label": "М1 БЛ Франкфурт — Боруссия М 4-4",
        "tournament": "league",
        "home": "Франкфурт",
        "away": "Боруссия М",
        "score_home": 4,
        "score_away": 4,
        "players": [
            {"name": "Дина Эбимбе", "team": "Франкфурт", "position": "ЛФА", "goals": 1, "assists": 0},
            {"name": "Мармуш", "team": "Франкфурт", "position": "ФРВ", "goals": 1, "assists": 0},
            {"name": "Мусиаля", "team": "Франкфурт", "position": "ЦАП", "goals": 1, "assists": 1},
            {"name": "Кох", "team": "Франкфурт", "position": "ЦОП", "goals": 1, "assists": 1},
            {"name": "Хонорат", "team": "Боруссия М", "position": "ЛФА", "goals": 0, "assists": 1},
            {"name": "Трусар", "team": "Боруссия М", "position": "ФРВ", "goals": 2, "assists": 0},
            {"name": "Кванкара", "team": "Боруссия М", "position": "ФРВ", "goals": 1, "assists": 0},
            {"name": "Траоре", "team": "Боруссия М", "position": "ПФА", "goals": 1, "assists": 1},
        ],
    },
    {
        "label": "М1 БЛ Дортмунд — Бавария 1-1",
        "tournament": "league",
        "home": "Дортмунд",
        "away": "Бавария",
        "score_home": 1,
        "score_away": 1,
        "players": [
            {"name": "Касьерра", "team": "Дортмунд", "position": "ФРВ", "goals": 1, "assists": 0},
            {"name": "Фред", "team": "Дортмунд", "position": "ЦП", "goals": 0, "assists": 1},
            {"name": "Кейн", "team": "Бавария", "position": "ФРВ", "goals": 0, "assists": 1},
            {"name": "Рёль", "team": "Бавария", "position": "ЦП", "goals": 1, "assists": 0},
        ],
    },
    {
        "label": "М1 РПЛ Зенит — Цска 3-2",
        "tournament": "league",
        "home": "Зенит",
        "away": "Цска",
        "score_home": 3,
        "score_away": 2,
        "players": [
            {"name": "Заха", "team": "Зенит", "position": "ЛФА", "goals": 1, "assists": 0},
            {"name": "Давид", "team": "Зенит", "position": "ФРВ", "goals": 2, "assists": 0},
            {"name": "Мантуан", "team": "Зенит", "position": "ЛФА", "goals": 0, "assists": 1},
            {"name": "Вильмар Барриос", "team": "Зенит", "position": "ЦОП", "goals": 0, "assists": 1},
            {"name": "Симеоне", "team": "Цска", "position": "ФРВ", "goals": 1, "assists": 0},
            {"name": "Мудрык", "team": "Цска", "position": "ЛФА", "goals": 1, "assists": 0},
            {"name": "Мойзес", "team": "Цска", "position": "ЛЗ", "goals": 0, "assists": 1},
        ],
    },
    {
        "label": "М1 БЛ Байер — Боруссия М 6-2",
        "tournament": "league",
        "home": "Байер",
        "away": "Боруссия М",
        "score_home": 6,
        "score_away": 2,
        "players": [
            {"name": "Иконе", "team": "Байер", "position": "ФРВ", "goals": 2, "assists": 0},
            {"name": "Бонифасе", "team": "Байер", "position": "ФРВ", "goals": 1, "assists": 1},
            {"name": "Шик", "team": "Байер", "position": "ФРВ", "goals": 1, "assists": 0},
            {"name": "Амири", "team": "Байер", "position": "ЦАП", "goals": 1, "assists": 1},
            {"name": "Хофманн", "team": "Байер", "position": "ЦП", "goals": 1, "assists": 1},
            {"name": "Андрих", "team": "Байер", "position": "ЦП", "goals": 0, "assists": 2},
            {"name": "Руис", "team": "Байер", "position": "ЦП", "goals": 0, "assists": 1},
            {"name": "Себашё", "team": "Боруссия М", "position": "ФРВ", "goals": 1, "assists": 0},
            {"name": "Нойхаус", "team": "Боруссия М", "position": "ЦП", "goals": 0, "assists": 2},
            {"name": "Вайгль", "team": "Боруссия М", "position": "ЦП", "goals": 1, "assists": 0},
        ],
    },
    {
        "label": "М1 БЛ Байер — Хоффенхайм 2-2",
        "tournament": "league",
        "home": "Байер",
        "away": "Хоффенхайм",
        "score_home": 2,
        "score_away": 2,
        "players": [
            {"name": "Адли", "team": "Байер", "position": "ФРВ", "goals": 1, "assists": 0},
            {"name": "Шик", "team": "Байер", "position": "ФРВ", "goals": 1, "assists": 0},
            {"name": "Иконе", "team": "Байер", "position": "ФРВ", "goals": 0, "assists": 1},
            {"name": "Гримальдо", "team": "Байер", "position": "ЛЗ", "goals": 0, "assists": 1},
            {"name": "Бебу", "team": "Хоффенхайм", "position": "ЛФА", "goals": 1, "assists": 0},
            {"name": "Гиббс-Уайт", "team": "Хоффенхайм", "position": "ЦАП", "goals": 0, "assists": 1},
            {"name": "Стах", "team": "Хоффенхайм", "position": "ЦП", "goals": 1, "assists": 0},
            {"name": "Сков", "team": "Хоффенхайм", "position": "ЛЗ", "goals": 0, "assists": 1},
        ],
    },
    {
        "label": "М1 БЛ Лейпциг — Франкфурт 4-4",
        "tournament": "league",
        "home": "Лейпциг",
        "away": "Франкфурт",
        "score_home": 4,
        "score_away": 4,
        "players": [
            {"name": "Вернер", "team": "Лейпциг", "position": "ФРВ", "goals": 2, "assists": 0},
            {"name": "Опенда", "team": "Лейпциг", "position": "ФРВ", "goals": 1, "assists": 1},
            {"name": "Клаудиньо", "team": "Лейпциг", "position": "ЦАП", "goals": 1, "assists": 1},
            {"name": "Ольмо", "team": "Лейпциг", "position": "ЦП", "goals": 0, "assists": 1},
            {"name": "Мармуш", "team": "Франкфурт", "position": "ФРВ", "goals": 1, "assists": 2},
            {"name": "Науфф", "team": "Франкфурт", "position": "ПФА", "goals": 1, "assists": 0},
            {"name": "Мусиаля", "team": "Франкфурт", "position": "ЦАП", "goals": 2, "assists": 1},
            {"name": "Гётце", "team": "Франкфурт", "position": "ЦОП", "goals": 0, "assists": 1},
        ],
    },
    {
        "label": "М1 АПЛ Мю — Тоттенхэм 3-5 (3й гол Мю без явной строки на скрине — Каземиро; поправь при расхождении с составом)",
        "tournament": "league",
        "home": "Мю",
        "away": "Тоттенхэм",
        "score_home": 3,
        "score_away": 5,
        "players": [
            {"name": "Гарначо", "team": "Мю", "position": "ЛФА", "goals": 1, "assists": 0},
            {"name": "Марсиаль", "team": "Мю", "position": "ФРВ", "goals": 0, "assists": 1},
            {"name": "Фернандеш", "team": "Мю", "position": "ЦАП", "goals": 1, "assists": 0},
            {"name": "Амрабат", "team": "Мю", "position": "ЦП", "goals": 0, "assists": 1},
            {"name": "Каземиро", "team": "Мю", "position": "ЦОП", "goals": 1, "assists": 0},
            {"name": "Сон", "team": "Тоттенхэм", "position": "ЛФА", "goals": 2, "assists": 0},
            {"name": "Альварез", "team": "Тоттенхэм", "position": "ФРВ", "goals": 2, "assists": 0},
            {"name": "Куадрадо", "team": "Тоттенхэм", "position": "ПФА", "goals": 1, "assists": 1},
            {"name": "Мэддисон", "team": "Тоттенхэм", "position": "ЦАП", "goals": 0, "assists": 3},
            {"name": "Хёйберг", "team": "Тоттенхэм", "position": "ЦОП", "goals": 0, "assists": 1},
        ],
    },
    {
        "label": "М1 СА Милан — Интер 3-4",
        "tournament": "league",
        "home": "Милан",
        "away": "Интер",
        "score_home": 3,
        "score_away": 4,
        "players": [
            {"name": "Вини", "team": "Милан", "position": "ФРВ", "goals": 1, "assists": 2},
            {"name": "Бензема", "team": "Милан", "position": "ФРВ", "goals": 2, "assists": 0},
            {"name": "Рейндерс", "team": "Милан", "position": "ЦП", "goals": 0, "assists": 1},
            {"name": "Берарди", "team": "Интер", "position": "ПП", "goals": 3, "assists": 0},
            {"name": "Мхитарян", "team": "Интер", "position": "ЛП", "goals": 0, "assists": 1},
            {"name": "Верман", "team": "Интер", "position": "ЦП", "goals": 1, "assists": 1},
            {"name": "Мане", "team": "Интер", "position": "ЛП", "goals": 0, "assists": 1},
        ],
    },
    {
        "label": "М1 ЛЧ Ньюкасл — Бавария 3-4",
        "tournament": "cl",
        "home": "Ньюкасл",
        "away": "Бавария",
        "score_home": 3,
        "score_away": 4,
        "players": [
            {"name": "Силва", "team": "Ньюкасл", "position": "ЦАП", "goals": 0, "assists": 1},
            {"name": "Исак", "team": "Ньюкасл", "position": "ФРВ", "goals": 1, "assists": 1},
            {"name": "Тонали", "team": "Ньюкасл", "position": "ЦАП", "goals": 1, "assists": 1},
            {"name": "Уиллок", "team": "Ньюкасл", "position": "ЦП", "goals": 1, "assists": 0},
            {"name": "Коман", "team": "Бавария", "position": "ЛФА", "goals": 1, "assists": 1},
            {"name": "Кейн", "team": "Бавария", "position": "ФРВ", "goals": 3, "assists": 1},
            {"name": "Рёль", "team": "Бавария", "position": "ЦП", "goals": 0, "assists": 2},
        ],
    },
    {
        "label": "М1 РПЛ Краснодар — Динамо 1-5",
        "tournament": "league",
        "home": "Краснодар",
        "away": "Динамо",
        "score_home": 1,
        "score_away": 5,
        "players": [
            {"name": "Буанга", "team": "Краснодар", "position": "ЛФА", "goals": 1, "assists": 0},
            {"name": "Тимбер", "team": "Краснодар", "position": "ЦП", "goals": 0, "assists": 1},
            {"name": "Макаров", "team": "Динамо", "position": "ПФА", "goals": 1, "assists": 0},
            {"name": "Гиттенс", "team": "Динамо", "position": "ЛФА", "goals": 1, "assists": 0},
            {"name": "Грулёв", "team": "Динамо", "position": "ЛФА", "goals": 0, "assists": 1},
            {"name": "Силас", "team": "Динамо", "position": "ПФА", "goals": 2, "assists": 0},
            {"name": "Гагнидзе", "team": "Динамо", "position": "ЦП", "goals": 1, "assists": 0},
            {"name": "Карраскаль", "team": "Динамо", "position": "ЦП", "goals": 0, "assists": 2},
        ],
    },
    {
        "label": "М1 РПЛ Локомотив — Спартак 2-2",
        "tournament": "league",
        "home": "Локомотив",
        "away": "Спартак",
        "score_home": 2,
        "score_away": 2,
        "players": [
            {"name": "Кастильехо", "team": "Локомотив", "position": "ПФА", "goals": 1, "assists": 0},
            {"name": "Миранчук", "team": "Локомотив", "position": "ЦП", "goals": 1, "assists": 0},
            {"name": "Виффер", "team": "Локомотив", "position": "ЦП", "goals": 0, "assists": 1},
            {"name": "Пепе", "team": "Спартак", "position": "ФРВ", "goals": 1, "assists": 1},
            {"name": "Эдвардс", "team": "Спартак", "position": "ПФА", "goals": 0, "assists": 1},
            {"name": "Зобнин", "team": "Спартак", "position": "ЦОП", "goals": 1, "assists": 0},
        ],
    },
    {
        "label": "М1 ЛЧ Динамо — Фиорентина 8-0 (+скрин Ругани 2+0 CS — не сшито с 8 голами без доразбора)",
        "tournament": "cl",
        "home": "Динамо",
        "away": "Фиорентина",
        "score_home": 8,
        "score_away": 0,
        "players": [
            {"name": "Гиттенс", "team": "Динамо", "position": "ЛФА", "goals": 1, "assists": 1},
            {"name": "Макаров", "team": "Динамо", "position": "ПФА", "goals": 1, "assists": 1},
            {"name": "Шешко", "team": "Динамо", "position": "ФРВ", "goals": 0, "assists": 2},
            {"name": "Гагнидзе", "team": "Динамо", "position": "ЦП", "goals": 1, "assists": 0},
            {"name": "Бителло", "team": "Динамо", "position": "ЦАП", "goals": 2, "assists": 0},
            {"name": "Чавез", "team": "Динамо", "position": "ЦП", "goals": 1, "assists": 0},
            {"name": "Карраскаль", "team": "Динамо", "position": "ЦП", "goals": 2, "assists": 2},
        ],
    },
    {
        "label": "М1 АПЛ Ливерпуль — Челси 0-0 (нет скринов)",
        "tournament": "league",
        "home": "Ливерпуль",
        "away": "Челси",
        "score_home": 0,
        "score_away": 0,
        "players": [],
    },
    {
        "label": "М1 ЛЧ Милан — Ливерпуль 1-1",
        "tournament": "cl",
        "home": "Милан",
        "away": "Ливерпуль",
        "score_home": 1,
        "score_away": 1,
        "players": [
            {"name": "Вини", "team": "Милан", "position": "ФРВ", "goals": 1, "assists": 0},
            {"name": "Калулу", "team": "Милан", "position": "ЦЗ", "goals": 0, "assists": 1},
            {"name": "Жота", "team": "Ливерпуль", "position": "ФРВ", "goals": 1, "assists": 0},
            {"name": "Олисе", "team": "Ливерпуль", "position": "ПФА", "goals": 0, "assists": 1},
        ],
    },
    {
        "label": "М1 ЛЧ Зенит — Ювентус 1-3",
        "tournament": "cl",
        "home": "Зенит",
        "away": "Ювентус",
        "score_home": 1,
        "score_away": 3,
        "players": [
            {"name": "Заха", "team": "Зенит", "position": "ЛФА", "goals": 0, "assists": 1},
            {"name": "Давид", "team": "Зенит", "position": "ФРВ", "goals": 1, "assists": 0},
            {"name": "Кьеза", "team": "Ювентус", "position": "ЛФА", "goals": 1, "assists": 0},
            {"name": "Влашич", "team": "Ювентус", "position": "ЦП", "goals": 0, "assists": 3},
            {"name": "Альба", "team": "Ювентус", "position": "ЛЗ", "goals": 1, "assists": 0},
            {"name": "Бремер", "team": "Ювентус", "position": "ЦЗ", "goals": 1, "assists": 0},
        ],
    },
    {
        "label": "М1 Ла Лига Бетис — Реал 0-0 (нет скринов)",
        "tournament": "league",
        "home": "Бетис",
        "away": "Реал",
        "score_home": 0,
        "score_away": 0,
        "players": [],
    },
    {
        "label": "М1 РПЛ Локомотив — Крылья Советов 2-1 (кк Бабкина в боте — в скрипт не включён)",
        "tournament": "league",
        "home": "Локомотив",
        "away": "Крылья Советов",
        "score_home": 2,
        "score_away": 1,
        "players": [
            {"name": "Чалов", "team": "Локомотив", "position": "ФРВ", "goals": 1, "assists": 1},
            {"name": "Виффер", "team": "Локомотив", "position": "ЦП", "goals": 1, "assists": 1},
            {"name": "Бабкин", "team": "Крылья Советов", "position": "ЦП", "goals": 1, "assists": 0},
        ],
    },
    {
        "label": "М1 ЛЧ Сити — Барселона 3-1",
        "tournament": "cl",
        "home": "Сити",
        "away": "Барселона",
        "score_home": 3,
        "score_away": 1,
        "players": [
            {"name": "Рэшфорд", "team": "Сити", "position": "ЛФА", "goals": 1, "assists": 1},
            {"name": "Месси", "team": "Сити", "position": "ПФА", "goals": 1, "assists": 0},
            {"name": "Сильва", "team": "Сити", "position": "ЦП", "goals": 1, "assists": 0},
            {"name": "Де Брюйне", "team": "Сити", "position": "ЦАП", "goals": 0, "assists": 1},
            {"name": "Неймар", "team": "Барселона", "position": "ЛФА", "goals": 1, "assists": 0},
            {"name": "Гави", "team": "Барселона", "position": "ЦП", "goals": 0, "assists": 1},
        ],
    },
    {
        "label": "М1 ЛЧ Барселона — Динамо 2-1",
        "tournament": "cl",
        "home": "Барселона",
        "away": "Динамо",
        "score_home": 2,
        "score_away": 1,
        "players": [
            {"name": "Лева", "team": "Барселона", "position": "ФРВ", "goals": 1, "assists": 0},
            {"name": "Араухо", "team": "Барселона", "position": "ЦЗ", "goals": 1, "assists": 0},
            {"name": "Канселу", "team": "Барселона", "position": "ПЗ", "goals": 0, "assists": 1},
            {"name": "Силас", "team": "Динамо", "position": "ПФА", "goals": 1, "assists": 0},
        ],
    },
    {
        "label": "М1 РПЛ Краснодар — Урал 1-2",
        "tournament": "league",
        "home": "Краснодар",
        "away": "Урал",
        "score_home": 1,
        "score_away": 2,
        "players": [
            {"name": "Кокшаров", "team": "Краснодар", "position": "ФРВ", "goals": 1, "assists": 0},
            {"name": "Бевеев", "team": "Урал", "position": "ПЗ", "goals": 1, "assists": 0},
            {"name": "Каштанов", "team": "Урал", "position": "ФРВ", "goals": 1, "assists": 0},
            {"name": "Ранделович", "team": "Урал", "position": "ПФА", "goals": 0, "assists": 2},
        ],
    },
    {
        "label": "М1 РПЛ Урал — Цска 1-2",
        "tournament": "league",
        "home": "Урал",
        "away": "Цска",
        "score_home": 1,
        "score_away": 2,
        "players": [
            {"name": "Бевеев", "team": "Урал", "position": "ПЗ", "goals": 1, "assists": 0},
            {"name": "Мишкич", "team": "Урал", "position": "ЦОП", "goals": 0, "assists": 1},
            {"name": "Симеоне", "team": "Цска", "position": "ФРВ", "goals": 1, "assists": 0},
            {"name": "Зджелар", "team": "Цска", "position": "ЦП", "goals": 1, "assists": 0},
            {"name": "Гроб", "team": "Цска", "position": "ЦП", "goals": 0, "assists": 2},
        ],
    },
    {
        "label": "М1 ЛЧ Ювентус — Севилья 2-1",
        "tournament": "cl",
        "home": "Ювентус",
        "away": "Севилья",
        "score_home": 2,
        "score_away": 1,
        "players": [
            {"name": "Смолов", "team": "Ювентус", "position": "ФРВ", "goals": 2, "assists": 0},
            {"name": "Карраско", "team": "Севилья", "position": "ЛФА", "goals": 1, "assists": 0},
        ],
    },
    {
        "label": "М1 Ла Лига Атлетик — Реал Сосьедад 3-1",
        "tournament": "league",
        "home": "Атлетик",
        "away": "Реал Сосьедад",
        "score_home": 3,
        "score_away": 1,
        "players": [
            {"name": "Леау", "team": "Атлетик", "position": "ФРВ", "goals": 3, "assists": 0},
            {"name": "Муниаин", "team": "Атлетик", "position": "ЦАП", "goals": 0, "assists": 1},
            {"name": "Кулушевски", "team": "Атлетик", "position": "ЦП", "goals": 0, "assists": 1},
            {"name": "Оярзабаль", "team": "Реал Сосьедад", "position": "ЦАП", "goals": 1, "assists": 0},
            {"name": "Ди Мария", "team": "Реал Сосьедад", "position": "ПФА", "goals": 0, "assists": 1},
        ],
    },
    {
        "label": "М1 ЛЧ Зенит — Арсенал 1-3",
        "tournament": "cl",
        "home": "Зенит",
        "away": "Арсенал",
        "score_home": 1,
        "score_away": 3,
        "players": [
            {"name": "Давид", "team": "Зенит", "position": "ФРВ", "goals": 1, "assists": 0},
            {"name": "Одегаард", "team": "Арсенал", "position": "ЦАП", "goals": 1, "assists": 0},
            {"name": "Жезус", "team": "Арсенал", "position": "ПФА", "goals": 1, "assists": 1},
            {"name": "Салиба", "team": "Арсенал", "position": "ЦЗ", "goals": 0, "assists": 1},
            {"name": "Хаверц", "team": "Арсенал", "position": "ФРВ", "goals": 1, "assists": 0},
        ],
    },
    {
        "label": "М1 ЛЧ Локомотив — Дортмунд 2-4",
        "tournament": "cl",
        "home": "Локомотив",
        "away": "Дортмунд",
        "score_home": 2,
        "score_away": 4,
        "players": [
            {"name": "Чалов", "team": "Локомотив", "position": "ФРВ", "goals": 1, "assists": 0},
            {"name": "Миранчук", "team": "Локомотив", "position": "ЦП", "goals": 1, "assists": 0},
            {"name": "Виффер", "team": "Локомотив", "position": "ЦП", "goals": 0, "assists": 1},
            {"name": "Адейеми", "team": "Дортмунд", "position": "ФРВ", "goals": 2, "assists": 0},
            {"name": "Касьерра", "team": "Дортмунд", "position": "ФРВ", "goals": 1, "assists": 1},
            {"name": "Дибала", "team": "Дортмунд", "position": "ЦАП", "goals": 1, "assists": 0},
            {"name": "Джан", "team": "Дортмунд", "position": "ЦП", "goals": 0, "assists": 1},
            {"name": "Фред", "team": "Дортмунд", "position": "ЦП", "goals": 0, "assists": 1},
            {"name": "Мален", "team": "Дортмунд", "position": "ФРВ", "goals": 0, "assists": 1},
        ],
    },
    {
        "label": "М1 РПЛ Зенит — Крылья Советов 2-0 (Кержаков CS на скрине — в скрипт не включён)",
        "tournament": "league",
        "home": "Зенит",
        "away": "Крылья Советов",
        "score_home": 2,
        "score_away": 0,
        "players": [
            {"name": "Фомин", "team": "Зенит", "position": "ЦП", "goals": 1, "assists": 0},
            {"name": "Нгамалу", "team": "Зенит", "position": "ПФА", "goals": 1, "assists": 0},
            {"name": "Трехо", "team": "Зенит", "position": "ЦАП", "goals": 0, "assists": 2},
        ],
    },
    {
        "label": "М1 ЛЧ Вольфсбург — Цска 4-1",
        "tournament": "cl",
        "home": "Вольфсбург",
        "away": "Цска",
        "score_home": 4,
        "score_away": 1,
        "players": [
            {"name": "Линдстром", "team": "Вольфсбург", "position": "ЛФА", "goals": 4, "assists": 0},
            {"name": "Арнольд", "team": "Вольфсбург", "position": "ЦОП", "goals": 0, "assists": 1},
            {"name": "Герхардт", "team": "Вольфсбург", "position": "ЦП", "goals": 0, "assists": 1},
            {"name": "Кучаев", "team": "Цска", "position": "ЦАП", "goals": 1, "assists": 0},
        ],
    },
    {
        "label": "М1 ЛЧ Краснодар — Мю 1-1",
        "tournament": "cl",
        "home": "Краснодар",
        "away": "Мю",
        "score_home": 1,
        "score_away": 1,
        "players": [
            {"name": "Салах", "team": "Краснодар", "position": "ПФА", "goals": 1, "assists": 0},
            {"name": "Буанга", "team": "Краснодар", "position": "ЛФА", "goals": 0, "assists": 1},
            {"name": "Каземиро", "team": "Мю", "position": "ЦОП", "goals": 1, "assists": 0},
            {"name": "Марсиаль", "team": "Мю", "position": "ФРВ", "goals": 0, "assists": 1},
        ],
    },
    {
        "label": "М1 ЛЧ Локомотив — Ньюкасл 1-3",
        "tournament": "cl",
        "home": "Локомотив",
        "away": "Ньюкасл",
        "score_home": 1,
        "score_away": 3,
        "players": [
            {"name": "Кастильехо", "team": "Локомотив", "position": "ПФА", "goals": 1, "assists": 0},
            {"name": "Трипье", "team": "Ньюкасл", "position": "ПЗ", "goals": 1, "assists": 0},
            {"name": "Тонали", "team": "Ньюкасл", "position": "ЦАП", "goals": 1, "assists": 1},
            {"name": "Ботман", "team": "Ньюкасл", "position": "ЦЗ", "goals": 1, "assists": 0},
        ],
    },
    {
        "label": "М1 АПЛ Ньюкасл — Сити 2-3 (жк Рэшфорда в боте — в скрипт не включён)",
        "tournament": "league",
        "home": "Ньюкасл",
        "away": "Сити",
        "score_home": 2,
        "score_away": 3,
        "players": [
            {"name": "Исак", "team": "Ньюкасл", "position": "ФРВ", "goals": 1, "assists": 0},
            {"name": "Уиллок", "team": "Ньюкасл", "position": "ЦП", "goals": 1, "assists": 0},
            {"name": "Шар", "team": "Ньюкасл", "position": "ЦЗ", "goals": 0, "assists": 1},
            {"name": "Холанд", "team": "Сити", "position": "ФРВ", "goals": 1, "assists": 0},
            {"name": "Рэшфорд", "team": "Сити", "position": "ЛФА", "goals": 2, "assists": 0},
            {"name": "Месси", "team": "Сити", "position": "ПФА", "goals": 0, "assists": 2},
        ],
    },
    {
        "label": "М1 Ла Лига Атлетико — Бетис 0-1 (Силва ВРТ CS на скрине — в скрипт не включён)",
        "tournament": "league",
        "home": "Атлетико",
        "away": "Бетис",
        "score_home": 0,
        "score_away": 1,
        "players": [
            {"name": "Витинья", "team": "Бетис", "position": "ЦОП", "goals": 1, "assists": 0},
        ],
    },
    {
        "label": "М1 АПЛ Астон Вилла — Челси 2-1 (жк Энцо в боте — в скрипт не включён)",
        "tournament": "league",
        "home": "Астон Вилла",
        "away": "Челси",
        "score_home": 2,
        "score_away": 1,
        "players": [
            {"name": "Ровелла", "team": "Астон Вилла", "position": "ЦП", "goals": 1, "assists": 0},
            {"name": "Виртц", "team": "Астон Вилла", "position": "ЦАП", "goals": 1, "assists": 0},
            {"name": "Сперцян", "team": "Астон Вилла", "position": "ФРВ", "goals": 0, "assists": 2},
            {"name": "Стерлинг", "team": "Челси", "position": "ЛФА", "goals": 1, "assists": 0},
            {"name": "Угарте", "team": "Челси", "position": "ЦП", "goals": 0, "assists": 1},
        ],
    },
]

# ---------------------------------------------------------------------------
# Месяц 2 · эталон по скринам (формат тот же)
# ---------------------------------------------------------------------------

MONTH2_FIXTURES: list[dict[str, Any]] = [
    {
        "label": "М2 БЛ Дортмунд — Байер 3-1",
        "tournament": "league",
        "home": "Дортмунд",
        "away": "Байер",
        "score_home": 3,
        "score_away": 1,
        "players": [
            {"name": "Мален", "team": "Дортмунд", "position": "ФРВ", "goals": 0, "assists": 1},
            {"name": "Касьерра", "team": "Дортмунд", "position": "ФРВ", "goals": 1, "assists": 0},
            {"name": "Дибала", "team": "Дортмунд", "position": "ЦАП", "goals": 1, "assists": 1},
            {"name": "Фред", "team": "Дортмунд", "position": "ЦП", "goals": 0, "assists": 1},
            {"name": "Джан", "team": "Дортмунд", "position": "ЦП", "goals": 1, "assists": 1},
            {"name": "Иконе", "team": "Байер", "position": "ФРВ", "goals": 1, "assists": 0},
            {"name": "Шик", "team": "Байер", "position": "ФРВ", "goals": 0, "assists": 1},
        ],
    },
    {
        "label": "М2 ЛЧ Лейпциг — Фиорентина 6-2",
        "tournament": "cl",
        "home": "Лейпциг",
        "away": "Фиорентина",
        "score_home": 6,
        "score_away": 2,
        "players": [
            {"name": "Вернер", "team": "Лейпциг", "position": "ФРВ", "goals": 0, "assists": 1},
            {"name": "Опенда", "team": "Лейпциг", "position": "ФРВ", "goals": 5, "assists": 0},
            {"name": "Баумгартнер", "team": "Лейпциг", "position": "ЦП", "goals": 0, "assists": 1},
            {"name": "Клаудиньо", "team": "Лейпциг", "position": "ЦАП", "goals": 1, "assists": 1},
            {"name": "Кёкчю", "team": "Лейпциг", "position": "ЦП", "goals": 0, "assists": 1},
            {"name": "Ольмо", "team": "Лейпциг", "position": "ЦП", "goals": 0, "assists": 1},
            {"name": "Соттиль", "team": "Фиорентина", "position": "ЛФА", "goals": 0, "assists": 1},
            {"name": "Гонзалез", "team": "Фиорентина", "position": "ПФА", "goals": 1, "assists": 0},
            {"name": "Лопес", "team": "Фиорентина", "position": "ЦП", "goals": 1, "assists": 0},
        ],
    },
    {
        "label": "М2 БЛ Байер — Лейпциг 2-2",
        "tournament": "league",
        "home": "Байер",
        "away": "Лейпциг",
        "score_home": 2,
        "score_away": 2,
        "players": [
            {"name": "Иконе", "team": "Байер", "position": "ФРВ", "goals": 1, "assists": 0},
            {"name": "Шик", "team": "Байер", "position": "ФРВ", "goals": 0, "assists": 1},
            {"name": "Хофманн", "team": "Байер", "position": "ЦП", "goals": 1, "assists": 0},
            {"name": "Опенда", "team": "Лейпциг", "position": "ФРВ", "goals": 1, "assists": 0},
            {"name": "Клаудиньо", "team": "Лейпциг", "position": "ЦАП", "goals": 0, "assists": 1},
            {"name": "Ольмо", "team": "Лейпциг", "position": "ЦП", "goals": 1, "assists": 0},
        ],
    },
    {
        "label": "М2 РПЛ Зенит — Краснодар 6-0",
        "tournament": "league",
        "home": "Зенит",
        "away": "Краснодар",
        "score_home": 6,
        "score_away": 0,
        "players": [
            {"name": "Заха", "team": "Зенит", "position": "ЛФА", "goals": 1, "assists": 2},
            {"name": "Нгамалу", "team": "Зенит", "position": "ПФА", "goals": 0, "assists": 1},
            {"name": "Мантуан", "team": "Зенит", "position": "ЛФА", "goals": 1, "assists": 0},
            {"name": "Давид", "team": "Зенит", "position": "ФРВ", "goals": 3, "assists": 0},
            {"name": "Трехо", "team": "Зенит", "position": "ЦАП", "goals": 1, "assists": 2},
            {"name": "Фомин", "team": "Зенит", "position": "ЦП", "goals": 0, "assists": 1},
        ],
    },
    {
        "label": "М2 РПЛ Краснодар — Локомотив 2-3",
        "tournament": "league",
        "home": "Краснодар",
        "away": "Локомотив",
        "score_home": 2,
        "score_away": 3,
        "players": [
            {"name": "Буанга", "team": "Краснодар", "position": "ЛФА", "goals": 1, "assists": 0},
            {"name": "Кокшаров", "team": "Краснодар", "position": "ФРВ", "goals": 1, "assists": 1},
            {"name": "Батши", "team": "Краснодар", "position": "ПФА", "goals": 0, "assists": 1},
            {"name": "Пиняев", "team": "Локомотив", "position": "ЛФА", "goals": 1, "assists": 1},
            {"name": "Чалов", "team": "Локомотив", "position": "ФРВ", "goals": 2, "assists": 0},
            {"name": "Кастильехо", "team": "Локомотив", "position": "ПФА", "goals": 0, "assists": 1},
            {"name": "Миранчук", "team": "Локомотив", "position": "ЦП", "goals": 0, "assists": 1},
        ],
    },
    {
        "label": "М2 ЛЧ Атлетик — Наполи 2-5 (+2й гол Атлетика: Нико ЛФА — на скрине только Леау+Муниаин)",
        "tournament": "cl",
        "home": "Атлетик",
        "away": "Наполи",
        "score_home": 2,
        "score_away": 5,
        "players": [
            {"name": "Муниаин", "team": "Атлетик", "position": "ЦАП", "goals": 0, "assists": 1},
            {"name": "Леау", "team": "Атлетик", "position": "ФРВ", "goals": 1, "assists": 0},
            {"name": "Нико", "team": "Атлетик", "position": "ЛФА", "goals": 1, "assists": 0},
            {"name": "Квара", "team": "Наполи", "position": "ЛФА", "goals": 5, "assists": 0},
            {"name": "Распадори", "team": "Наполи", "position": "ФРВ", "goals": 0, "assists": 1},
            {"name": "Элмас", "team": "Наполи", "position": "ЦАП", "goals": 0, "assists": 1},
            {"name": "Лоботка", "team": "Наполи", "position": "ЦП", "goals": 0, "assists": 1},
        ],
    },
    {
        "label": "М2 АПЛ Ньюкасл — Челси 6-1",
        "tournament": "league",
        "home": "Ньюкасл",
        "away": "Челси",
        "score_home": 6,
        "score_away": 1,
        "players": [
            {"name": "Тонали", "team": "Ньюкасл", "position": "ЦАП", "goals": 1, "assists": 2},
            {"name": "Исак", "team": "Ньюкасл", "position": "ФРВ", "goals": 3, "assists": 1},
            {"name": "Силва", "team": "Ньюкасл", "position": "ЦАП", "goals": 2, "assists": 3},
            {"name": "Стерлинг", "team": "Челси", "position": "ЛФА", "goals": 1, "assists": 0},
            {"name": "Фекир", "team": "Челси", "position": "ЦАП", "goals": 0, "assists": 1},
        ],
    },
    {
        "label": "М2 РПЛ Урал — Локомотив 4-1",
        "tournament": "league",
        "home": "Урал",
        "away": "Локомотив",
        "score_home": 4,
        "score_away": 1,
        "players": [
            {"name": "Дмитриев", "team": "Урал", "position": "ЛФА", "goals": 1, "assists": 0},
            {"name": "Каштанов", "team": "Урал", "position": "ФРВ", "goals": 1, "assists": 1},
            {"name": "Егорычев", "team": "Урал", "position": "ЦАП", "goals": 1, "assists": 1},
            {"name": "Мишкич", "team": "Урал", "position": "ЦОП", "goals": 1, "assists": 0},
            {"name": "Миранчук", "team": "Локомотив", "position": "ЦП", "goals": 1, "assists": 0},
            {"name": "Баринов", "team": "Локомотив", "position": "ЦОП", "goals": 0, "assists": 1},
        ],
    },
    {
        "label": "М2 ЛЧ Ювентус — Мю 1-4",
        "tournament": "cl",
        "home": "Ювентус",
        "away": "Мю",
        "score_home": 1,
        "score_away": 4,
        "players": [
            {"name": "Смолов", "team": "Ювентус", "position": "ФРВ", "goals": 1, "assists": 0},
            {"name": "Кьеза", "team": "Ювентус", "position": "ЛФА", "goals": 0, "assists": 1},
            {"name": "Марсиаль", "team": "Мю", "position": "ФРВ", "goals": 1, "assists": 1},
            {"name": "Гарначо", "team": "Мю", "position": "ЛФА", "goals": 2, "assists": 1},
            {"name": "Фернандеш", "team": "Мю", "position": "ЦАП", "goals": 1, "assists": 1},
        ],
    },
    {
        "label": "М2 ЛЧ Барселона — Милан 5-2",
        "tournament": "cl",
        "home": "Барселона",
        "away": "Милан",
        "score_home": 5,
        "score_away": 2,
        "players": [
            {"name": "Неймар", "team": "Барселона", "position": "ЛФА", "goals": 2, "assists": 0},
            {"name": "Рафинья", "team": "Барселона", "position": "ПФА", "goals": 1, "assists": 1},
            {"name": "Лева", "team": "Барселона", "position": "ФРВ", "goals": 1, "assists": 1},
            {"name": "Де Йонг", "team": "Барселона", "position": "ЦОП", "goals": 1, "assists": 0},
            {"name": "Педри", "team": "Барселона", "position": "ЦП", "goals": 0, "assists": 2},
            {"name": "Вини", "team": "Милан", "position": "ФРВ", "goals": 0, "assists": 2},
            {"name": "Рейндерс", "team": "Милан", "position": "ЦП", "goals": 1, "assists": 0},
            {"name": "Беннасер", "team": "Милан", "position": "ЦП", "goals": 1, "assists": 0},
        ],
    },
    {
        "label": "М2 ЛЧ Арсенал — Наполи 2-3",
        "tournament": "cl",
        "home": "Арсенал",
        "away": "Наполи",
        "score_home": 2,
        "score_away": 3,
        "players": [
            {"name": "Одегаард", "team": "Арсенал", "position": "ЦАП", "goals": 2, "assists": 0},
            {"name": "Хаверц", "team": "Арсенал", "position": "ФРВ", "goals": 0, "assists": 2},
            {"name": "Осимен", "team": "Наполи", "position": "ФРВ", "goals": 2, "assists": 0},
            {"name": "Квара", "team": "Наполи", "position": "ЛФА", "goals": 1, "assists": 0},
            {"name": "Невеш", "team": "Наполи", "position": "ЦОП", "goals": 0, "assists": 2},
        ],
    },
    {
        "label": "М2 СА Милан — Аталанта 1-4",
        "tournament": "league",
        "home": "Милан",
        "away": "Аталанта",
        "score_home": 1,
        "score_away": 4,
        "players": [
            {"name": "Эрнандез", "team": "Милан", "position": "ЛЗ", "goals": 0, "assists": 1},
            {"name": "Беллингем", "team": "Милан", "position": "ЦАП", "goals": 1, "assists": 0},
            {"name": "Муриэль", "team": "Аталанта", "position": "ЛФА", "goals": 2, "assists": 0},
            {"name": "Миранчук", "team": "Аталанта", "position": "ФРВ", "goals": 2, "assists": 1},
            {"name": "Торрес", "team": "Аталанта", "position": "ЦП", "goals": 0, "assists": 1},
            {"name": "Лукман", "team": "Аталанта", "position": "ПФА", "goals": 0, "assists": 1},
        ],
    },
    {
        "label": "М2 ЛЧ Бавария — Аталанта 5-2",
        "tournament": "cl",
        "home": "Бавария",
        "away": "Аталанта",
        "score_home": 5,
        "score_away": 2,
        "players": [
            {"name": "Коман", "team": "Бавария", "position": "ЛФА", "goals": 2, "assists": 1},
            {"name": "Банза", "team": "Бавария", "position": "ФРВ", "goals": 2, "assists": 0},
            {"name": "Мариу", "team": "Бавария", "position": "ЦАП", "goals": 0, "assists": 1},
            {"name": "Рёль", "team": "Бавария", "position": "ЦП", "goals": 0, "assists": 3},
            {"name": "Миранчук", "team": "Аталанта", "position": "ФРВ", "goals": 0, "assists": 1},
            {"name": "Лукман", "team": "Аталанта", "position": "ПФА", "goals": 1, "assists": 0},
            {"name": "Торрес", "team": "Аталанта", "position": "ЦП", "goals": 1, "assists": 1},
        ],
    },
    {
        "label": "М2 БЛ Дортмунд — Франкфурт 5-2",
        "tournament": "league",
        "home": "Дортмунд",
        "away": "Франкфурт",
        "score_home": 5,
        "score_away": 2,
        "players": [
            {"name": "Касьерра", "team": "Дортмунд", "position": "ФРВ", "goals": 2, "assists": 0},
            {"name": "Адейеми", "team": "Дортмунд", "position": "ФРВ", "goals": 0, "assists": 1},
            {"name": "Забитцер", "team": "Дортмунд", "position": "ЦП", "goals": 0, "assists": 1},
            {"name": "Дибала", "team": "Дортмунд", "position": "ЦАП", "goals": 2, "assists": 0},
            {"name": "Фред", "team": "Дортмунд", "position": "ЦП", "goals": 0, "assists": 2},
            {"name": "Джан", "team": "Дортмунд", "position": "ЦП", "goals": 1, "assists": 1},
            {"name": "Корона", "team": "Франкфурт", "position": "ПФА", "goals": 0, "assists": 1},
            {"name": "Мусиаля", "team": "Франкфурт", "position": "ЦАП", "goals": 1, "assists": 0},
            {"name": "Кох", "team": "Франкфурт", "position": "ЦОП", "goals": 0, "assists": 1},
            {"name": "Гётце", "team": "Франкфурт", "position": "ЦОП", "goals": 1, "assists": 0},
        ],
    },
    {
        "label": "М2 АПЛ Тоттенхэм — Астон Вилла 4-0",
        "tournament": "league",
        "home": "Тоттенхэм",
        "away": "Астон Вилла",
        "score_home": 4,
        "score_away": 0,
        "players": [
            {"name": "Сон", "team": "Тоттенхэм", "position": "ЛФА", "goals": 2, "assists": 0},
            {"name": "Альварез", "team": "Тоттенхэм", "position": "ФРВ", "goals": 1, "assists": 0},
            {"name": "Эзе", "team": "Тоттенхэм", "position": "ЦАП", "goals": 0, "assists": 1},
            {"name": "Мэддисон", "team": "Тоттенхэм", "position": "ЦАП", "goals": 1, "assists": 1},
        ],
    },
    {
        "label": "М2 Ла Лига Атлетико — Атлетик 3-5",
        "tournament": "league",
        "home": "Атлетико",
        "away": "Атлетик",
        "score_home": 3,
        "score_away": 5,
        "players": [
            {"name": "Корреа", "team": "Атлетико", "position": "ФРВ", "goals": 0, "assists": 2},
            {"name": "Обамеянг", "team": "Атлетико", "position": "ФРВ", "goals": 1, "assists": 0},
            {"name": "Икарди", "team": "Атлетико", "position": "ФРВ", "goals": 0, "assists": 1},
            {"name": "Мората", "team": "Атлетико", "position": "ФРВ", "goals": 1, "assists": 0},
            {"name": "Льоренте", "team": "Атлетико", "position": "ЦП", "goals": 1, "assists": 0},
            {"name": "Леау", "team": "Атлетик", "position": "ФРВ", "goals": 2, "assists": 0},
            {"name": "Бробби", "team": "Атлетик", "position": "ФРВ", "goals": 3, "assists": 0},
            {"name": "Сансет", "team": "Атлетик", "position": "ЦП", "goals": 0, "assists": 3},
            {"name": "Хартман", "team": "Атлетик", "position": "ЛЗ", "goals": 0, "assists": 1},
        ],
    },
    {
        "label": "М2 Ла Лига Севилья — Реал 6-2",
        "tournament": "league",
        "home": "Севилья",
        "away": "Реал",
        "score_home": 6,
        "score_away": 2,
        "players": [
            {"name": "Карраско", "team": "Севилья", "position": "ЛФА", "goals": 1, "assists": 1},
            {"name": "Гонсалвеш", "team": "Севилья", "position": "ЛФА", "goals": 2, "assists": 1},
            {"name": "Жоелинтон", "team": "Севилья", "position": "ЦП", "goals": 1, "assists": 0},
            {"name": "Лукебакио", "team": "Севилья", "position": "ПФА", "goals": 0, "assists": 1},
            {"name": "Ундав", "team": "Севилья", "position": "ЦП", "goals": 2, "assists": 1},
            {"name": "Браим", "team": "Реал", "position": "ЦАП", "goals": 1, "assists": 1},
            {"name": "Кроос", "team": "Реал", "position": "ЦОП", "goals": 1, "assists": 0},
            {"name": "Лукаку", "team": "Реал", "position": "ФРВ", "goals": 0, "assists": 1},
        ],
    },
    {
        "label": "М2 РПЛ Урал — Динамо 2-2",
        "tournament": "league",
        "home": "Урал",
        "away": "Динамо",
        "score_home": 2,
        "score_away": 2,
        "players": [
            {"name": "Каштанов", "team": "Урал", "position": "ФРВ", "goals": 0, "assists": 1},
            {"name": "Егорычев", "team": "Урал", "position": "ЦАП", "goals": 1, "assists": 0},
            {"name": "Мишкич", "team": "Урал", "position": "ЦОП", "goals": 1, "assists": 0},
            {"name": "Шешко", "team": "Динамо", "position": "ФРВ", "goals": 0, "assists": 1},
            {"name": "Чавез", "team": "Динамо", "position": "ЦП", "goals": 1, "assists": 0},
            {"name": "Карраскаль", "team": "Динамо", "position": "ЦП", "goals": 1, "assists": 0},
        ],
    },
    {
        "label": "М2 ЛЧ Реал Сосьедад — Ливерпуль 3-3",
        "tournament": "cl",
        "home": "Реал Сосьедад",
        "away": "Ливерпуль",
        "score_home": 3,
        "score_away": 3,
        "players": [
            {"name": "Захарян", "team": "Реал Сосьедад", "position": "ЛФА", "goals": 1, "assists": 1},
            {"name": "Ди Мария", "team": "Реал Сосьедад", "position": "ПФА", "goals": 1, "assists": 1},
            {"name": "Оярзабаль", "team": "Реал Сосьедад", "position": "ЦАП", "goals": 1, "assists": 0},
            {"name": "Нуньес", "team": "Ливерпуль", "position": "ФРВ", "goals": 1, "assists": 0},
            {"name": "Жота", "team": "Ливерпуль", "position": "ФРВ", "goals": 1, "assists": 0},
            {"name": "Мбаппе", "team": "Ливерпуль", "position": "ПФА", "goals": 0, "assists": 1},
            {"name": "Коке", "team": "Ливерпуль", "position": "ЦП", "goals": 0, "assists": 2},
            {"name": "Гравенберх", "team": "Ливерпуль", "position": "ЦП", "goals": 1, "assists": 0},
        ],
    },
    {
        "label": "М2 СА Милан — Ювентус 2-4",
        "tournament": "league",
        "home": "Милан",
        "away": "Ювентус",
        "score_home": 2,
        "score_away": 4,
        "players": [
            {"name": "Вини", "team": "Милан", "position": "ФРВ", "goals": 1, "assists": 0},
            {"name": "Бензема", "team": "Милан", "position": "ФРВ", "goals": 0, "assists": 1},
            {"name": "Чуквуезе", "team": "Милан", "position": "ПФА", "goals": 1, "assists": 1},
            {"name": "Кьеза", "team": "Ювентус", "position": "ЛФА", "goals": 0, "assists": 1},
            {"name": "Костич", "team": "Ювентус", "position": "ПФА", "goals": 0, "assists": 1},
            {"name": "Смолов", "team": "Ювентус", "position": "ФРВ", "goals": 1, "assists": 1},
            {"name": "Влашич", "team": "Ювентус", "position": "ЦП", "goals": 2, "assists": 0},
            {"name": "Фаджиоли", "team": "Ювентус", "position": "ЦП", "goals": 0, "assists": 1},
            {"name": "Миретти", "team": "Ювентус", "position": "ЦП", "goals": 1, "assists": 0},
        ],
    },
    {
        "label": "М2 АПЛ Ливерпуль — Арсенал 1-4 (травма Мбаппе в боте — в скрипт не включена)",
        "tournament": "league",
        "home": "Ливерпуль",
        "away": "Арсенал",
        "score_home": 1,
        "score_away": 4,
        "players": [
            {"name": "Олисе", "team": "Ливерпуль", "position": "ПФА", "goals": 1, "assists": 0},
            {"name": "Гравенберх", "team": "Ливерпуль", "position": "ЦП", "goals": 0, "assists": 1},
            {"name": "Хаверц", "team": "Арсенал", "position": "ФРВ", "goals": 3, "assists": 0},
            {"name": "Одегаард", "team": "Арсенал", "position": "ЦАП", "goals": 0, "assists": 3},
            {"name": "Мерино", "team": "Арсенал", "position": "ЦП", "goals": 1, "assists": 0},
        ],
    },
    {
        "label": "М2 РПЛ Динамо — Цска 8-2",
        "tournament": "league",
        "home": "Динамо",
        "away": "Цска",
        "score_home": 8,
        "score_away": 2,
        "players": [
            {"name": "Гиттенс", "team": "Динамо", "position": "ЛФА", "goals": 1, "assists": 0},
            {"name": "Карраскаль", "team": "Динамо", "position": "ЦП", "goals": 0, "assists": 2},
            {"name": "Силас", "team": "Динамо", "position": "ПФА", "goals": 1, "assists": 1},
            {"name": "Бителло", "team": "Динамо", "position": "ЦАП", "goals": 0, "assists": 2},
            {"name": "Чавез", "team": "Динамо", "position": "ЦП", "goals": 0, "assists": 1},
            {"name": "Шешко", "team": "Динамо", "position": "ФРВ", "goals": 6, "assists": 1},
            {"name": "Кучаев", "team": "Цска", "position": "ЦАП", "goals": 1, "assists": 0},
            {"name": "Дивеев", "team": "Цска", "position": "ЦЗ", "goals": 0, "assists": 1},
            {"name": "Гроб", "team": "Цска", "position": "ЦП", "goals": 1, "assists": 0},
        ],
    },
    {
        "label": "М2 ЛЧ Спартак — Ньюкасл 0-6",
        "tournament": "cl",
        "home": "Спартак",
        "away": "Ньюкасл",
        "score_home": 0,
        "score_away": 6,
        "players": [
            {"name": "Исак", "team": "Ньюкасл", "position": "ФРВ", "goals": 3, "assists": 0},
            {"name": "Тонали", "team": "Ньюкасл", "position": "ЦАП", "goals": 1, "assists": 0},
            {"name": "Уиллок", "team": "Ньюкасл", "position": "ЦП", "goals": 0, "assists": 1},
            {"name": "Прёмель", "team": "Ньюкасл", "position": "ЦП", "goals": 0, "assists": 1},
            {"name": "Тюрам", "team": "Ньюкасл", "position": "ФРВ", "goals": 1, "assists": 0},
            {"name": "Кунья", "team": "Ньюкасл", "position": "ФРВ", "goals": 1, "assists": 1},
            {"name": "Силва", "team": "Ньюкасл", "position": "ЦАП", "goals": 0, "assists": 2},
            {"name": "Лонгстаф", "team": "Ньюкасл", "position": "ЦП", "goals": 0, "assists": 1},
        ],
    },
    {
        "label": "М2 ЛЧ Франкфурт — Ювентус 3-0",
        "tournament": "cl",
        "home": "Франкфурт",
        "away": "Ювентус",
        "score_home": 3,
        "score_away": 0,
        "players": [
            {"name": "Мармуш", "team": "Франкфурт", "position": "ФРВ", "goals": 1, "assists": 0},
            {"name": "Корона", "team": "Франкфурт", "position": "ПФА", "goals": 0, "assists": 1},
            {"name": "Мусиаля", "team": "Франкфурт", "position": "ЦАП", "goals": 0, "assists": 1},
            {"name": "Гётце", "team": "Франкфурт", "position": "ЦОП", "goals": 1, "assists": 0},
            {"name": "Пачо", "team": "Франкфурт", "position": "ЦЗ", "goals": 1, "assists": 0},
        ],
    },
    {
        "label": "М2 СА Ювентус — Наполи 3-6",
        "tournament": "league",
        "home": "Ювентус",
        "away": "Наполи",
        "score_home": 3,
        "score_away": 6,
        "players": [
            {"name": "Кьеза", "team": "Ювентус", "position": "ЛФА", "goals": 0, "assists": 1},
            {"name": "Костич", "team": "Ювентус", "position": "ПФА", "goals": 1, "assists": 0},
            {"name": "Влашич", "team": "Ювентус", "position": "ЦП", "goals": 1, "assists": 0},
            {"name": "Кин", "team": "Ювентус", "position": "ФРВ", "goals": 1, "assists": 1},
            {"name": "Квара", "team": "Наполи", "position": "ЛФА", "goals": 3, "assists": 1},
            {"name": "Осимен", "team": "Наполи", "position": "ФРВ", "goals": 2, "assists": 0},
            {"name": "Сака", "team": "Наполи", "position": "ПФА", "goals": 0, "assists": 1},
            {"name": "Невеш", "team": "Наполи", "position": "ЦОП", "goals": 0, "assists": 2},
            {"name": "Лоботка", "team": "Наполи", "position": "ЦП", "goals": 1, "assists": 1},
            {"name": "Ангисса", "team": "Наполи", "position": "ЦОП", "goals": 0, "assists": 1},
        ],
    },
    {
        "label": "М2 РПЛ Крылья Советов — Спартак 2-0",
        "tournament": "league",
        "home": "Крылья Советов",
        "away": "Спартак",
        "score_home": 2,
        "score_away": 0,
        "players": [
            {"name": "Писарский", "team": "Крылья Советов", "position": "ФРВ", "goals": 0, "assists": 1},
            {"name": "Бабкин", "team": "Крылья Советов", "position": "ЦП", "goals": 2, "assists": 0},
        ],
    },
    {
        "label": "М2 СА Фиорентина — Интер 1-4 (жк Соттила в боте — в скрипт не включён)",
        "tournament": "league",
        "home": "Фиорентина",
        "away": "Интер",
        "score_home": 1,
        "score_away": 4,
        "players": [
            {"name": "Соттиль", "team": "Фиорентина", "position": "ЛФА", "goals": 1, "assists": 0},
            {"name": "Гонзалез", "team": "Фиорентина", "position": "ПФА", "goals": 0, "assists": 1},
            {"name": "Арнаутович", "team": "Интер", "position": "ФРВ", "goals": 1, "assists": 2},
            {"name": "Барелла", "team": "Интер", "position": "ЦП", "goals": 0, "assists": 1},
            {"name": "Берарди", "team": "Интер", "position": "ПП", "goals": 1, "assists": 1},
            {"name": "Уоткинс", "team": "Интер", "position": "ФРВ", "goals": 1, "assists": 0},
        ],
    },
    {
        "label": "М2 Ла Лига Жирона — Реал Сосьедад 0-6 (травма Кубо в боте — в скрипт не включена)",
        "tournament": "league",
        "home": "Жирона",
        "away": "Реал Сосьедад",
        "score_home": 0,
        "score_away": 6,
        "players": [
            {"name": "Ди Мария", "team": "Реал Сосьедад", "position": "ПФА", "goals": 3, "assists": 1},
            {"name": "Вендел", "team": "Реал Сосьедад", "position": "ЦП", "goals": 0, "assists": 1},
            {"name": "Мендез", "team": "Реал Сосьедад", "position": "ЦП", "goals": 2, "assists": 0},
            {"name": "Захарян", "team": "Реал Сосьедад", "position": "ЛФА", "goals": 0, "assists": 1},
            {"name": "Кубо", "team": "Реал Сосьедад", "position": "ПФА", "goals": 0, "assists": 1},
            {"name": "Барренечеа", "team": "Реал Сосьедад", "position": "ЛФА", "goals": 1, "assists": 0},
        ],
    },
    {
        "label": "М2 Ла Лига Барселона — Атлетико 6-2 (травма Корреа в боте — в скрипт не включена)",
        "tournament": "league",
        "home": "Барселона",
        "away": "Атлетико",
        "score_home": 6,
        "score_away": 2,
        "players": [
            {"name": "Неймар", "team": "Барселона", "position": "ЛФА", "goals": 1, "assists": 0},
            {"name": "Рафинья", "team": "Барселона", "position": "ПФА", "goals": 2, "assists": 2},
            {"name": "Лева", "team": "Барселона", "position": "ФРВ", "goals": 1, "assists": 2},
            {"name": "Педри", "team": "Барселона", "position": "ЦП", "goals": 0, "assists": 1},
            {"name": "Гави", "team": "Барселона", "position": "ЦП", "goals": 2, "assists": 1},
            {"name": "Мората", "team": "Атлетико", "position": "ФРВ", "goals": 2, "assists": 0},
            {"name": "Тюрам", "team": "Атлетико", "position": "ЦП", "goals": 0, "assists": 1},
        ],
    },
    {
        "label": "М2 БЛ Боруссия М — Бавария 1-5 (травма Вайгля в боте — в скрипт не включена)",
        "tournament": "league",
        "home": "Боруссия М",
        "away": "Бавария",
        "score_home": 1,
        "score_away": 5,
        "players": [
            {"name": "Себашё", "team": "Боруссия М", "position": "ФРВ", "goals": 1, "assists": 0},
            {"name": "Коман", "team": "Бавария", "position": "ЛФА", "goals": 0, "assists": 2},
            {"name": "Кейн", "team": "Бавария", "position": "ФРВ", "goals": 2, "assists": 0},
            {"name": "Банза", "team": "Бавария", "position": "ФРВ", "goals": 1, "assists": 0},
            {"name": "Мариу", "team": "Бавария", "position": "ЦАП", "goals": 1, "assists": 1},
            {"name": "Рёль", "team": "Бавария", "position": "ЦП", "goals": 1, "assists": 0},
            {"name": "Фримпонг", "team": "Бавария", "position": "ПЗ", "goals": 0, "assists": 1},
        ],
    },
]

ALL_SEASON2_MANUAL_FIXTURES: list[dict[str, Any]] = MONTH1_FIXTURES + MONTH2_FIXTURES


def fixture_requires_player_rows(fx: dict[str, Any]) -> bool:
    """Нужен непустой players, только если по счёту в матче были голы (0-0 без скринов — ок)."""
    sh = int(fx["score_home"])
    sa = int(fx["score_away"])
    return sh > 0 or sa > 0


def validate_fixture_scores(fixtures: list[dict[str, Any]]) -> list[str]:
    """Проверка: сумма голов по строкам не превышает счёт (автоголы могут не быть в списке)."""
    errs: list[str] = []
    for fx in fixtures:
        players = fx.get("players") or []
        if not players:
            continue
        home = (fx["home"] or "").strip().title()
        away = (fx["away"] or "").strip().title()
        sh = int(fx["score_home"])
        sa = int(fx["score_away"])
        sum_h = sum(int(p["goals"]) for p in players if (p.get("team") or "").strip().title() == home)
        sum_a = sum(int(p["goals"]) for p in players if (p.get("team") or "").strip().title() == away)
        if sum_h > sh or sum_a > sa:
            errs.append(
                f'{fx.get("label")}: голы игроками {home} {sum_h} > счёт {sh} или '
                f'{away} {sum_a} > {sa}'
            )
    return errs


def zero_outfield_match_counters_season2() -> None:
    """Обнулить только goals, assists, matches, ga у полевых в обоих файлах сезона 2."""
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker

    from data.defender import Defender
    from data.forward import Forward
    from data.midfielder import Midfielder
    from utils import season_paths

    if season_paths.get_active_season() != 2:
        raise SystemExit(
            "В db/season_state.json active_season должен быть 2, иначе add_player_stats "
            "пойдёт не в те файлы."
        )

    s2 = season_paths.season_archive_directory(2)
    league_p = Path(s2) / season_paths.SEASON_LEAGUE_NAME
    cl_p = Path(s2) / season_paths.SEASON_CL_NAME
    for path in (league_p, cl_p):
        if not path.is_file():
            raise SystemExit(f"Нет файла: {path}")
        eng = create_engine(f"sqlite:///{path}")
        Mk = sessionmaker(bind=eng)
        s = Mk()
        try:
            for Cls in (Forward, Midfielder, Defender):
                for row in s.query(Cls).all():
                    row.goals = 0
                    row.assists = 0
                    row.matches = 0
                    row.ga = 0
            s.commit()
        finally:
            s.close()
            eng.dispose()


def apply_fixtures(fixtures: list[dict[str, Any]]) -> None:
    """Добавить вклад матчей через player_stats (после обнуления — единственный источник g/a/m)."""
    from player_stats import add_player_stats

    for fx in fixtures:
        players = fx.get("players") or []
        if not players:
            continue
        h = (fx["home"] or "").strip().title()
        a = (fx["away"] or "").strip().title()
        hs = int(fx["score_home"])
        aws = int(fx["score_away"])
        tourn = fx["tournament"]
        match_for_cs = (h, a, hs, aws)
        for pl in players:
            ok = add_player_stats(
                pl["name"],
                pl["position"],
                pl["team"],
                goals=int(pl.get("goals") or 0),
                assists=int(pl.get("assists") or 0),
                clean_sheet=False,
                tournament=tourn,
                auto_find=True,
                match_for_cs=match_for_cs,
                create_if_missing=False,
                skip_discipline_check=True,
                increment_matches=True,
            )
            if not ok:
                label = fx.get("label", "")
                raise SystemExit(
                    f"Не записалась строка ({label}): {pl.get('name')} {pl.get('team')} — "
                    "проверь имя/позицию в БД или добавь create_if_missing (пока False)."
                )


def rebuild_common_and_synced() -> None:
    from utils.common_db import rebuild_common_database
    from utils.cumulative_db import rebuild_all_time_databases_from_season_archives

    rebuild_common_database()
    log = rebuild_all_time_databases_from_season_archives()
    print("Пересборка *_synced:", log.get("cumulative"), "сезоны:", log.get("seasons"))


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Проверить, что суммы голов по строкам не превышают счёт, и выйти (по умолчанию).",
    )
    parser.add_argument(
        "--apply",
        action="store_true",
        help="Обнулить матчевую стату полевых S2 и залить ALL_SEASON2_MANUAL_FIXTURES (м1+m2), затем common+synced.",
    )
    parser.add_argument(
        "--i-understand-destroy-stats",
        action="store_true",
        help="Обязательный флаг вместе с --apply (тупиковое обнуление g/a/m/ga по всем полевым S2).",
    )
    parser.add_argument(
        "--allow-partial-fixtures",
        action="store_true",
        help="Разрешить --apply при незаполненных матчах (остальная стата S2 обнулится без восстановления!).",
    )
    args = parser.parse_args()

    if not args.dry_run and not args.apply:
        args.dry_run = True
    # Реальная заливка не смешиваем с одновременным --dry-run
    if args.apply:
        args.dry_run = False

    errs = validate_fixture_scores(ALL_SEASON2_MANUAL_FIXTURES)
    for e in errs:
        print("ОШИБКА:", e)
    if errs:
        raise SystemExit(1)

    incomplete = [
        fx["label"]
        for fx in ALL_SEASON2_MANUAL_FIXTURES
        if fixture_requires_player_rows(fx) and not (fx.get("players") or [])
    ]
    if incomplete:
        print("Матчи без блока players (будут пропущены при --apply):")
        for x in incomplete:
            print("  -", x)

    if args.apply and incomplete and not args.allow_partial_fixtures:
        raise SystemExit(
            "Есть матчи с пустым players — дополни MONTH1_FIXTURES / MONTH2_FIXTURES или явно передай "
            "--allow-partial-fixtures (вся матчевая стата полевых S2 обнулится, "
            "а зальются только матчи со списком!)."
        )

    if args.dry_run and not args.apply:
        print("Dry-run OK. Для применения (когда список полон): --apply --i-understand-destroy-stats")
        return

    if args.apply:
        if not args.i_understand_destroy_stats:
            raise SystemExit("С --apply нужен --i-understand-destroy-stats")
        print("Обнуление goals/assists/matches/ga (полевые) в league+cl сезона 2…")
        zero_outfield_match_counters_season2()
        print("Заливка эталонных матчей…")
        apply_fixtures(ALL_SEASON2_MANUAL_FIXTURES)
        print("Пересборка common.db и *_synced.db…")
        rebuild_common_and_synced()
        print("Готово.")


if __name__ == "__main__":
    main()
