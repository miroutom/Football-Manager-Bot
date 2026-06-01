#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Если ``season2_trim_removed_teams.py`` уже запускали с полным сбросом «Рубин»,
эти два игрока не появятся при повторном trim — нужно вставить вручную из канона.

Добавляет в ``db/season_2/{league,champions_league}.db`` Палмера и Ранделовича
для «Рубин» по данным ``data.russia_rpl_squads``, затем пересобирает ``common.db``.

  python scripts/season2_reinsert_rubin_keepers.py
"""
from __future__ import annotations

import os
import sys

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from data.russia_rpl_squads import RUSSIA_RPL_SQUADS
from utils import season_paths
from utils.common_db import rebuild_common_database_for_disk_paths
from utils.player_transfer import add_player_to_club_sessions

_SEASON = 2
_TEAM = "Рубин"
_NAMES = frozenset({"Палмер", "Ранделович"})


def run() -> None:
    base = os.path.join(season_paths.PROJECT_ROOT, "db", f"season_{_SEASON}")
    p_l = os.path.join(base, season_paths.SEASON_LEAGUE_NAME)
    p_c = os.path.join(base, season_paths.SEASON_CL_NAME)
    p_o = os.path.join(base, season_paths.SEASON_COMMON_NAME)

    rows = [t for t in RUSSIA_RPL_SQUADS[_TEAM] if t[0] in _NAMES]
    if len(rows) != len(_NAMES):
        missing = _NAMES - {t[0] for t in rows}
        raise SystemExit(f"В RUSSIA_RPL_SQUADS нет строк для: {sorted(missing)}")

    el = create_engine(f"sqlite:///{p_l}")
    ec = create_engine(f"sqlite:///{p_c}")
    Sl = sessionmaker(bind=el)
    Scl = sessionmaker(bind=ec)
    sl, scl = Sl(), Scl()
    try:
        for name, pos, ovr, nation, status in rows:
            c = add_player_to_club_sessions(
                sl,
                scl,
                name,
                pos,
                _TEAM,
                status,
                int(ovr),
                nation=nation,
                on_league_duplicate="skip",
            )
            print(f"{name}: inserted league={c['league']}, cl={c['cl']}")
        sl.commit()
        scl.commit()
    except Exception:
        sl.rollback()
        scl.rollback()
        raise
    finally:
        sl.close()
        scl.close()
        el.dispose()
        ec.dispose()

    rebuild_common_database_for_disk_paths(p_l, p_c, p_o)
    print("Пересобран:", p_o)


if __name__ == "__main__":
    run()
