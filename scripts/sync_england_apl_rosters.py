#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Миграция колонки ``status`` + синхрон заявок АПЛ в ``league_new.db`` и ``champions_league_new.db``,
затем пересборка ``common.db`` (если не отключено).

Бот рисует состав из SQLite, а не из скриншотов: правки в ``data/england_apl_squads.py`` попадут в картинку
**только после** ``python scripts/sync_england_apl_rosters.py`` на той машине, где лежит ``db/league_new.db``
(тот же каталог, откуда запускается бот). ``*.db`` в git не коммитятся.
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from data.england_apl_squads import ENGLAND_APL_SQUADS
from utils.squad_roster_sync import run_full_england_sync


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
    if args.tournament == "both":
        tournaments: tuple[str, ...] = ("league", "cl")
    else:
        tournaments = (args.tournament,)
    stats = run_full_england_sync(
        tournaments=tournaments,
        rebuild_common=not args.no_common_rebuild,
    )
    for tour, teams in stats.items():
        print(f"=== {tour} ===")
        for team, s in teams.items():
            print(team, s)
    if "cl" in stats:
        skipped = [t for t in ENGLAND_APL_SQUADS if t not in stats["cl"]]
        if skipped:
            print(
                "В champions_league_new.db не писали (клуб не в пуле участников ЛЧ):",
                ", ".join(skipped),
            )


if __name__ == "__main__":
    main()
