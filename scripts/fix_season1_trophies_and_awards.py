#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Восстановить трофеи и индивидуальные награды за 1-й сезон; обнулить их в активном 2-м.

Сезон 1 (один раз на игрока/клуб):
  нац. чемпионы — +1 trophies в league.db;
  ЛЧ — +1 trophies в champions_league.db для состава победителя;
  ЗМ / бутса — Лаутаро Мартинез (Интер);
  перчатка — Ян Зоммер (Интер);
  Golden Boy — Мерлин Рёль (Фрайбург, как в season_history.json).

Сезон 2: trophies и golden_* = 0 (идёт чемпионат, наград ещё нет).

Затем пересборка *_synced.db из архивов season_*.

  python3 scripts/fix_season1_trophies_and_awards.py           # dry-run
  python3 scripts/fix_season1_trophies_and_awards.py --apply
"""
from __future__ import annotations

import argparse
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from data.defender import Defender
from data.forward import Forward
from data.goalkeeper import Goalkeeper
from data.midfielder import Midfielder
from utils import season_paths
from utils.common_db import rebuild_common_database, rebuild_common_database_for_disk_paths
from utils.season_end import _inc_trophies_all_players_of_team

_ALL = (Forward, Midfielder, Defender, Goalkeeper)

SEASON1_NATIONAL = (
    "Зенит",
    "Сити",
    "Атлетико",
    "Интер",
    "Бавария",
)
SEASON1_CL = "Интер"

AWARDS: tuple[tuple[str, str, str], ...] = (
    ("ball", "Мартинез", "Интер"),
    ("boot", "Мартинез", "Интер"),
    ("glove", "Зоммер", "Интер"),
    ("boy", "Рёль", "Фрайбург"),
)

_ATTR = {
    "ball": "golden_balls",
    "boot": "golden_boots",
    "glove": "golden_gloves",
    "boy": "golden_boys",
}


def _zero_trophies_and_awards(session) -> int:
    n = 0
    for Cls in _ALL:
        for row in session.query(Cls).all():
            row.trophies = 0
            row.golden_balls = 0
            row.golden_boots = 0
            row.golden_boys = 0
            if hasattr(row, "golden_gloves"):
                row.golden_gloves = 0
            n += 1
    return n


def _set_award(session, kind: str, name: str, team: str) -> bool:
    from player_stats import find_player_by_name, get_position_type

    attr = _ATTR[kind]
    pl, pos_type = find_player_by_name(session, name.strip().title(), team.strip().title())
    if not pl:
        return False
    if kind == "glove" and pos_type != "goalkeeper":
        return False
    if kind != "glove" and pos_type == "goalkeeper":
        return False
    setattr(pl, attr, 1)
    return True


def _session_pair(league_path: str, cl_path: str):
    el = create_engine(f"sqlite:///{league_path}")
    ec = create_engine(f"sqlite:///{cl_path}")
    return sessionmaker(bind=el)(), sessionmaker(bind=ec)(), el, ec


def _fix_pair(league_path: str, cl_path: str, *, apply: bool, label: str) -> dict:
    sl, sc, el, ec = _session_pair(league_path, cl_path)
    log: dict = {"label": label}
    try:
        log["zeroed_rows"] = _zero_trophies_and_awards(sl) + _zero_trophies_and_awards(sc)
        if apply:
            for team in SEASON1_NATIONAL:
                log[f"league:{team}"] = _inc_trophies_all_players_of_team(sl, team, 1)
            log["cl"] = _inc_trophies_all_players_of_team(sc, SEASON1_CL, 1)
            for kind, name, team in AWARDS:
                ok = _set_award(sl, kind, name, team)
                log[f"award:{kind}:{name}"] = ok
            sl.commit()
            sc.commit()
        else:
            log["would_bump_league"] = list(SEASON1_NATIONAL)
            log["would_bump_cl"] = SEASON1_CL
            log["would_awards"] = list(AWARDS)
    finally:
        sl.close()
        sc.close()
        el.dispose()
        ec.dispose()
    return log


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true")
    args = ap.parse_args()
    apply = args.apply

    season_paths.repair_per_season_database_files()
    s1 = os.path.join(ROOT, "db", "season_1")
    s2 = os.path.join(ROOT, "db", "season_2")
    p1l = os.path.join(s1, season_paths.SEASON_LEAGUE_NAME)
    p1c = os.path.join(s1, season_paths.SEASON_CL_NAME)
    p2l = os.path.join(s2, season_paths.SEASON_LEAGUE_NAME)
    p2c = os.path.join(s2, season_paths.SEASON_CL_NAME)

    print("=== season_1 (чемпионы + награды) ===")
    print(_fix_pair(p1l, p1c, apply=apply, label="season_1"))

    print("\n=== season_2 (только обнуление наград) ===")
    sl, sc, el, ec = _session_pair(p2l, p2c)
    try:
        n = _zero_trophies_and_awards(sl) + _zero_trophies_and_awards(sc)
        print({"zeroed_rows": n})
        if apply:
            sl.commit()
            sc.commit()
    finally:
        sl.close()
        sc.close()
        el.dispose()
        ec.dispose()

    if not apply:
        print("\n(dry-run) Запусти с --apply для записи и пересборки synced.")
        return 0

    from utils.cumulative_db import rebuild_all_time_databases_from_season_archives

    print("\n=== Пересборка *_synced из архивов ===")
    print(rebuild_all_time_databases_from_season_archives())

    from utils.utils import reinit_db_connections

    reinit_db_connections()
    rebuild_common_database()
    print("season_2 common.db пересобран:", season_paths.get_common_db_path())

    # Проверка
    cum_o = season_paths.get_cumulative_common_db_path()
    import sqlite3

    con = sqlite3.connect(cum_o)
    cur = con.cursor()
    cur.execute(
        "SELECT name, team, trophies, golden_balls, golden_boots FROM forwards "
        "WHERE name LIKE '%Мартинез%' AND team='Интер'"
    )
    print("\nПроверка Мартинез (common_synced):", cur.fetchone())
    cur.execute(
        "SELECT name, team, trophies FROM forwards WHERE team='Зенит' ORDER BY trophies DESC LIMIT 1"
    )
    print("Проверка Зенит max trophies:", cur.fetchone())
    cur.execute(
        "SELECT name, team, golden_gloves FROM goalkeepers WHERE name LIKE '%Зоммер%'"
    )
    print("Проверка Зоммер:", cur.fetchone())
    con.close()
    print("\nГотово.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
