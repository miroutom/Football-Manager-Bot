#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Пересобрать ``season_N/common.db`` из league + cl (с ``person_id`` из исходников)."""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from utils import season_paths
from utils.common_db import rebuild_common_database_for_disk_paths
from utils.migrate_player_person_id import migrate_person_id_for_sqlite


def rebuild_season(sn: int) -> None:
    d = season_paths.season_archive_directory(sn)
    lp = f"{d}/{season_paths.SEASON_LEAGUE_NAME}"
    cp = f"{d}/{season_paths.SEASON_CL_NAME}"
    op = f"{d}/{season_paths.SEASON_COMMON_NAME}"
    for path, label in ((lp, "league"), (cp, "cl"), (op, "common")):
        migrate_person_id_for_sqlite(path, label=f"s{sn}/{label}")
    rebuild_common_database_for_disk_paths(lp, cp, op)
    print(f"OK season_{sn}/common.db ← league + cl")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument(
        "--season",
        type=int,
        action="append",
        dest="seasons",
        help="Номер сезона (можно несколько раз: --season 1 --season 2)",
    )
    ap.add_argument(
        "--all-archives",
        action="store_true",
        help="Все db/season_N с league.db",
    )
    args = ap.parse_args()
    if args.all_archives:
        from utils.cumulative_db import list_season_archives_with_db

        seasons = list_season_archives_with_db()
    elif args.seasons:
        seasons = sorted(set(args.seasons))
    else:
        seasons = [season_paths.get_active_season()]
    for sn in seasons:
        rebuild_season(sn)


if __name__ == "__main__":
    main()
