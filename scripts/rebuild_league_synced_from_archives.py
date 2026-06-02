#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Фаза 5: пересобрать ``*_synced.db`` из ``db/season_N/`` (слияние по ``person_id``).

Удаляет старые synced, заново сливает season_1 + season_2 + …, пересобирает common_synced.

  python scripts/rebuild_league_synced_from_archives.py
  python scripts/rebuild_league_synced_from_archives.py --dry-run
  python scripts/rebuild_league_synced_from_archives.py --verify
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
from utils.cumulative_db import (
    list_season_archives_with_db,
    rebuild_all_time_databases_from_season_archives,
)
from utils.migrate_player_person_id import migrate_person_id_for_sqlite


def _verify_top() -> None:
    from utils.stats_history_agg import aggregate_life_outfield, aggregate_outfield

    print("\n--- Проверка топов ---")
    life = aggregate_life_outfield("allcl")
    for r in sorted(life, key=lambda x: -(x.get("ga") or 0))[:5]:
        print(
            f"  life #{life.index(r)+1}: {r['name']} {r['team']} {r['position']} "
            f"G+A={r.get('ga')} (G={r.get('goals')} A={r.get('assists')})"
        )
    for r in life:
        if (r.get("name") or "").strip() == "Мартинез" and r.get("team") == "Интер":
            print(f"  life Мартинез Интер: G+A={r.get('ga')}")
    s1 = aggregate_outfield("allcl", season_num=1, merge_by_player=True)
    top1 = sorted(s1, key=lambda x: -(x.get("goals", 0) + x.get("assists", 0)))[:1]
    if top1:
        t = top1[0]
        print(
            f"  S1 top G+A: {t['name']} {t['team']} {t['position']} "
            f"{t.get('goals')}+{t.get('assists')}"
        )


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true", help="Только показать план")
    ap.add_argument(
        "--verify",
        action="store_true",
        help="После пересборки — топ life и S1 Мартинез",
    )
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
    for sn in seasons:
        base = season_paths.season_archive_directory(sn)
        for fname in (
            season_paths.SEASON_LEAGUE_NAME,
            season_paths.SEASON_CL_NAME,
        ):
            migrate_person_id_for_sqlite(
                os.path.join(base, fname), label=f"s{sn}/{fname}"
            )
    if args.dry_run:
        return 0
    for p in (cum_l, cum_c, cum_o):
        if os.path.isfile(p):
            bak = p + ".bak_person_id_rebuild"
            shutil.copy2(p, bak)
            os.remove(p)
            print("backup:", bak)
    log = rebuild_all_time_databases_from_season_archives()
    print("log:", log)
    if args.verify:
        _verify_top()
    print("done")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
