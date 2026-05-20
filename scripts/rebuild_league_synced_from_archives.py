#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Пересобрать league_synced / champions_league_synced из архивов сезонов.

Исправляет строки, где голы разных клубов были слиты по (имя, позиция).
После пересборки вызывается rebuild common_synced.

  python scripts/rebuild_league_synced_from_archives.py
  python scripts/rebuild_league_synced_from_archives.py --dry-run
"""
from __future__ import annotations

import argparse
import os
import shutil
import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from utils import season_paths
from utils.cumulative_db import append_season_snapshot_to_all_time, list_season_archives_with_db


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true", help="Только показать план")
    args = ap.parse_args()
    seasons = list_season_archives_with_db()
    if not seasons:
        print("Нет db/season_N/league.db")
        return 1
    cum_l = season_paths.get_cumulative_league_db_path()
    cum_c = season_paths.get_cumulative_cl_db_path()
    cum_o = season_paths.get_cumulative_common_db_path()
    print("Сезоны:", seasons)
    print("Цели:", cum_l, cum_c, cum_o)
    if args.dry_run:
        return 0
    for p in (cum_l, cum_c, cum_o):
        if os.path.isfile(p):
            bak = p + ".bak"
            shutil.copy2(p, bak)
            os.remove(p)
            print("backup:", bak)
    log_total = []
    for sn in seasons:
        base = season_paths.season_archive_directory(sn)
        lp = os.path.join(base, season_paths.SEASON_LEAGUE_NAME)
        cp = os.path.join(base, season_paths.SEASON_CL_NAME)
        if not os.path.isfile(cp):
            print(f"skip season {sn}: no cl db")
            continue
        log = append_season_snapshot_to_all_time(lp, cp)
        log_total.append((sn, log))
        print(f"merged season {sn}:", log.get("cumulative"))
    print("done")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
