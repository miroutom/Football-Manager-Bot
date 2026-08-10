#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Пересчитать ``trophies`` во всех сезонных архивах по ``season_history.json``
и пересобрать ``*_synced.db``.

  python scripts/rebuild_player_trophies_from_history.py
  python scripts/rebuild_player_trophies_from_history.py --dry-run
  python scripts/rebuild_player_trophies_from_history.py --no-synced
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from utils.player_trophies import (
    rebuild_archives_trophies_from_history,
    rebuild_synced_trophies_from_archives,
    season_tournament_db_path,
)


def _sample_liverpool_cl() -> None:
    import sqlite3

    path = season_tournament_db_path(2, cl=True)
    if not path:
        return
    conn = sqlite3.connect(path)
    cur = conn.execute(
        "SELECT MAX(trophies) FROM forwards WHERE team LIKE '%ивер%'"
    )
    mx = cur.fetchone()[0]
    conn.close()
    print(f"  season 2 CL Liverpool max trophies (expect 1): {mx}")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument(
        "--no-synced",
        action="store_true",
        help="Не пересобирать league_synced / cl_synced / common_synced",
    )
    args = ap.parse_args()
    if args.dry_run:
        print("Будет: reset trophies в архивах → начисление по history → synced")
        return 0

    log = rebuild_archives_trophies_from_history(include_active=True)
    print("Сезоны:", log.get("seasons"))
    print("Строк обнулено:", log.get("reset"))
    for part in log.get("apply") or []:
        sn = part.get("season")
        cl = part.get("cl")
        lg = part.get("league") or []
        if lg or cl:
            print(f"  season {sn}: league={len(lg)} winners, cl={cl}")

    _sample_liverpool_cl()

    if not args.no_synced:
        print("Пересборка *_synced.db …")
        synced = rebuild_synced_trophies_from_archives()
        print("Synced:", synced.get("cumulative"))

    from bot.team_history import clear_titled_players_cache

    clear_titled_players_cache()
    print("Готово.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
