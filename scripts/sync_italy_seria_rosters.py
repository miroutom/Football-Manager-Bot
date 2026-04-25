#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Миграция ``status`` + синк заявок Серии А в ``league_new.db`` / ``champions_league_new.db`` (участники ЛЧ) + ``common.db``."""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from data.italy_seria_a_squads import ITALY_SERIE_A_SQUADS
from utils.squad_roster_sync import run_italy_seria_sync


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument(
        "--no-common-rebuild",
        action="store_true",
        help="не вызывать rebuild_common_database() после синка",
    )
    ap.add_argument(
        "--tournament",
        choices=("league", "cl", "both"),
        default="both",
        help="куда писать: лига, только ЛЧ, или обе БД (по умолчанию both)",
    )
    args = ap.parse_args()
    tournaments: tuple[str, ...] = (
        ("league", "cl") if args.tournament == "both" else (args.tournament,)
    )
    stats = run_italy_seria_sync(
        tournaments=tournaments,
        rebuild_common=not args.no_common_rebuild,
    )
    for tour, teams in stats.items():
        print(f"=== {tour} ===")
        for team, s in teams.items():
            print(team, s)
    if "cl" in stats:
        skipped = [t for t in ITALY_SERIE_A_SQUADS if t not in stats["cl"]]
        if skipped:
            print(
                "В champions_league_new.db не писали (не в пуле участников ЛЧ):",
                ", ".join(skipped),
            )


if __name__ == "__main__":
    main()
