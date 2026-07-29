#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Исправить Реал Сосьедад 3:1 Барселона → 1:3 + стата/POTM/жк."""
from __future__ import annotations

import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from player_stats import apply_match_lineup, apply_match_potm
from utils.correct_match_score import correct_match_score
from utils.match_player_stats_log import record_match_player_stats
from utils.player_discipline import get_calendar_month, try_apply_discipline_line
from matches_stats_tracking import mark_stats_completed

HOME = "Реал Сосьедад"
AWAY = "Барселона"
LEAGUE = "esp"
DAY = 7
OLD = (3, 1)
NEW = (1, 3)


def main() -> int:
    ok, msg = correct_match_score(
        HOME,
        AWAY,
        LEAGUE,
        NEW[0],
        NEW[1],
        day=DAY,
        expected_old=OLD,
    )
    print(msg)
    if not ok:
        return 1

    mcs = (HOME, AWAY, NEW[0], NEW[1])
    rows = [
        ("Палазон", "ЛФА", AWAY, 2, 1),
        ("Лева", "ФРВ", AWAY, 1, 0),
        ("Де Йонг", "ЦП", AWAY, 0, 1),
        ("Педри", "ЦАП", AWAY, 0, 1),
        ("Бальде", "ЛЗ", AWAY, 0, 1),
        ("Хулиан Альварез", "ФРВ", HOME, 1, 0),
        ("Сангаре", "ЦОП", HOME, 0, 1),
    ]
    print("=== Стата игроков ===")
    apply_match_lineup(rows, "league", match_for_cs=mcs)

    record_match_player_stats(
        players=[
            {"player": n, "team": t, "position": p, "goals": g, "assists": a}
            for n, p, t, g, a in rows
        ],
        home=HOME,
        away=AWAY,
        tournament="league",
        day=DAY,
        home_score=NEW[0],
        away_score=NEW[1],
        league_code=LEAGUE,
    )

    print("=== POTM ===")
    apply_match_potm(
        "Палазон",
        "ЛФА",
        AWAY,
        tournament="league",
        home=HOME,
        away=AWAY,
        day=DAY,
        home_score=NEW[0],
        away_score=NEW[1],
        league_code=LEAGUE,
    )

    month = get_calendar_month(DAY)
    print(f"=== ЖК (месяц {month}) ===")
    for name, team in (("Лева", AWAY), ("Лориент", HOME)):
        disc_msg, _ = try_apply_discipline_line(
            f"{name} жк",
            current_team=team,
            tournament="league",
            league_code=LEAGUE,
            schedule_month=month,
            fixture_home=HOME,
            fixture_away=AWAY,
        )
        print(disc_msg or name)

    mark_stats_completed(HOME, AWAY, "league", day=DAY)
    print("✓ matches_stats_completed")

    try:
        from utils.common_db import rebuild_common_database

        rebuild_common_database()
        print("common.db пересобран")
    except Exception as e:
        print(f"common: {e}")

    try:
        from utils.cumulative_db import rebuild_all_time_databases_from_season_archives

        log = rebuild_all_time_databases_from_season_archives()
        print("synced:", log.get("cumulative"), "сезоны:", log.get("seasons"))
    except Exception as e:
        print(f"synced: {e}")

    from teams import teams_spain

    for n in (HOME, AWAY):
        t = teams_spain[n]
        print(
            f"{n}: m={t.matches} w={t.wins} d={t.draws} l={t.losses} "
            f"gf={t.scored} ga={t.missed} pts={t.points}"
        )
    print(f"Готово: {HOME} {NEW[0]}:{NEW[1]} {AWAY}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
