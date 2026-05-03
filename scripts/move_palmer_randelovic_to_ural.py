#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Палмер и Ранделович → «Урал», заявка bench (данные как в squads РПЛ / сезон 1).
Обновляет накопительные *_synced.db и db/season_2/*.db + common для каждой пары.

  python scripts/move_palmer_randelovic_to_ural.py
"""
from __future__ import annotations

import os
import sys

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from utils import season_paths
from utils.common_db import rebuild_common_database_for_disk_paths
from utils.player_transfer import (
    _add_free_agent_to_sessions,
    _apply_transfer_with_status_to_sessions,
)

# Как в data/russia_rpl_squads.py («Рубин»): рейтинги и нации канона РПЛ.
PLAYERS: tuple[tuple[str, str, int, str], ...] = (
    ("Ранделович", "ПФА", 70, "Сербия"),
    ("Палмер", "ПФА", 67, "Англия"),
)
FROM_TEAM = "Рубин"
TO_TEAM = "Урал"
STATUS = "bench"


def _process_paths(p_l: str, p_c: str, p_o: str) -> None:
    if not os.path.isfile(p_l) or not os.path.isfile(p_c):
        print(f"пропуск (нет файлов): {p_l}")
        return
    el = create_engine(f"sqlite:///{p_l}")
    ec = create_engine(f"sqlite:///{p_c}")
    Sl, Scl = sessionmaker(bind=el), sessionmaker(bind=ec)
    sl, scl = Sl(), Scl()
    try:
        for name, pos, ovr, nat in PLAYERS:
            counts = _apply_transfer_with_status_to_sessions(
                sl,
                scl,
                name,
                FROM_TEAM,
                pos,
                TO_TEAM,
                STATUS,
                new_overall=ovr,
                nation_update=True,
                new_nation=nat,
            )
            if counts["league"] == 0:
                _add_free_agent_to_sessions(
                    sl,
                    scl,
                    name,
                    pos,
                    TO_TEAM,
                    STATUS,
                    ovr,
                    nation=nat,
                    on_league_duplicate="skip",
                )
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
    print("OK:", p_o)


def main() -> None:
    root = season_paths.PROJECT_ROOT
    triples = [
        (
            season_paths.get_cumulative_league_db_path(),
            season_paths.get_cumulative_cl_db_path(),
            season_paths.get_cumulative_common_db_path(),
        ),
        (
            os.path.join(root, "db", "season_2", season_paths.SEASON_LEAGUE_NAME),
            os.path.join(root, "db", "season_2", season_paths.SEASON_CL_NAME),
            os.path.join(root, "db", "season_2", season_paths.SEASON_COMMON_NAME),
        ),
    ]
    for p_l, p_c, p_o in triples:
        _process_paths(p_l, p_c, p_o)


if __name__ == "__main__":
    main()
