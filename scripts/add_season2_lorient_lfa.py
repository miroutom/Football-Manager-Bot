#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Добавить «Лориент» (ЛФА, Реал Сосьедад) в БД **сезона 2**, как в ``data/spain_la_liga_squads.py``,
и пересобрать ``season_2/common.db``.

  python scripts/add_season2_lorient_lfa.py
  python scripts/add_season2_lorient_lfa.py --also-cumulative   # плюс league_synced / cl_synced / common_synced
"""
from __future__ import annotations

import argparse
import os
import sys

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from data.forward import Forward
from utils import season_paths
from utils.common_db import rebuild_common_database_for_disk_paths
from utils.player_transfer import add_player_to_club_sessions

SEASON_NUM = 2
PLAYER = "Лориент"
TEAM = "Реал Сосьедад"
POSITION = "ЛФА"
OVERALL = 80
NATION = "Франция"
STATUS = "start"


def _open_pair(league_path: str, cl_path: str):
    el = create_engine(f"sqlite:///{league_path}")
    ec = create_engine(f"sqlite:///{cl_path}")
    Sl = sessionmaker(bind=el)
    Scl = sessionmaker(bind=ec)
    return Sl(), Scl(), el, ec


def _dispose_pair(sl, scl, el, ec) -> None:
    sl.close()
    scl.close()
    el.dispose()
    ec.dispose()


def _ensure_lorient_nation_and_overall(sl, scl) -> None:
    """После вставки: нация и рейтинг как в канонической заявке."""
    nl = PLAYER.lower()
    pl = POSITION.lower()
    tt = TEAM.strip()
    ttl = tt.lower()

    def _pick(sess):
        for r in sess.query(Forward).all():
            if (r.name or "").strip().lower() != nl:
                continue
            if (r.position or "").strip().lower() != pl:
                continue
            rt = (r.team or "").strip()
            if rt == tt or rt.lower() == ttl:
                return r
        return None

    for sess in (sl, scl):
        row = _pick(sess)
        if row is not None:
            row.nation = NATION
            row.overall = max(1, min(99, int(OVERALL)))
        sess.commit()


def _run_for_paths(league_path: str, cl_path: str, common_path: str, label: str) -> dict[str, int]:
    if not os.path.isfile(league_path) or not os.path.isfile(cl_path):
        print(f"[{label}] нет league/cl: пропуск", file=sys.stderr)
        return {"league": 0, "cl": 0}
    sl, scl, el, ec = _open_pair(league_path, cl_path)
    try:
        counts = add_player_to_club_sessions(
            sl,
            scl,
            PLAYER,
            POSITION,
            TEAM,
            STATUS,
            OVERALL,
            nation=NATION,
            on_league_duplicate="skip",
        )
        _ensure_lorient_nation_and_overall(sl, scl)
        rebuild_common_database_for_disk_paths(league_path, cl_path, common_path)
        print(
            f"[{label}] league+={counts['league']}, cl+={counts['cl']}; "
            f"пересобран common: {common_path}",
        )
        return counts
    finally:
        _dispose_pair(sl, scl, el, ec)


def main() -> None:
    ap = argparse.ArgumentParser(description="Лориент ЛФА → БД сезона 2 + common")
    ap.add_argument(
        "--also-cumulative",
        action="store_true",
        help="То же в db/league_synced.db, champions_league_synced.db, common_synced.db",
    )
    args = ap.parse_args()

    base = os.path.join(season_paths.PROJECT_ROOT, "db", f"season_{SEASON_NUM}")
    p_l = os.path.join(base, season_paths.SEASON_LEAGUE_NAME)
    p_c = os.path.join(base, season_paths.SEASON_CL_NAME)
    p_o = os.path.join(base, season_paths.SEASON_COMMON_NAME)

    _run_for_paths(p_l, p_c, p_o, f"season_{SEASON_NUM}")

    if args.also_cumulative:
        if season_paths.is_legacy_mode():
            print("--also-cumulative: режим legacy, накопительные БД = рабочие; пропуск дубля.")
        else:
            lp = season_paths.get_cumulative_league_db_path()
            cp = season_paths.get_cumulative_cl_db_path()
            cop = season_paths.get_cumulative_common_db_path()
            if os.path.isfile(lp) and os.path.isfile(cp):
                _run_for_paths(lp, cp, cop, "cumulative_synced")
            else:
                print("--also-cumulative: нет league_synced/cl_synced файлов.", file=sys.stderr)

    print("Готово.")


if __name__ == "__main__":
    main()
