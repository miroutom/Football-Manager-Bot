#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Слить дубли: один игрок + один клуб не должен иметь двух строк (разные позиции).

  python3 scripts/consolidate_team_player_duplicates.py
  python3 scripts/consolidate_team_player_duplicates.py --apply
  python3 scripts/consolidate_team_player_duplicates.py --apply --db league
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

from utils import season_paths
from utils.squad_roster_sync import consolidate_player_team_duplicates


def _run(path: str, *, apply: bool) -> dict[str, int]:
    eng = create_engine(f"sqlite:///{path}")
    Session = sessionmaker(bind=eng)
    session = Session()
    try:
        log = consolidate_player_team_duplicates(session)
        if apply:
            session.commit()
        else:
            session.rollback()
        return log
    finally:
        session.close()
        eng.dispose()


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--apply", action="store_true", help="Записать изменения")
    ap.add_argument(
        "--db",
        choices=("league", "cl", "common", "league_synced", "cl_synced", "common_synced", "all"),
        default="all",
    )
    args = ap.parse_args()

    paths: list[tuple[str, str]] = []
    if args.db in ("league", "all"):
        paths.append(("league", season_paths.get_league_db_path()))
    if args.db in ("cl", "all"):
        paths.append(("cl", season_paths.get_cl_db_path()))
    if args.db in ("common", "all"):
        paths.append(("common", season_paths.get_common_db_path()))
    if args.db in ("league_synced", "all"):
        paths.append(("league_synced", season_paths.get_cumulative_league_db_path()))
    if args.db in ("cl_synced", "all"):
        paths.append(("cl_synced", season_paths.get_cumulative_cl_db_path()))
    if args.db in ("common_synced", "all"):
        paths.append(("common_synced", season_paths.get_cumulative_common_db_path()))

    mode = "APPLY" if args.apply else "DRY-RUN"
    print(f"{mode}: слияние дублей игрок+клуб")
    for label, path in paths:
        if not os.path.isfile(path):
            print(f"  skip {label}: нет файла {path}")
            continue
        log = _run(path, apply=args.apply)
        print(f"  {label}: merged={log['groups_merged']} deleted={log['rows_deleted']}")

    if not args.apply:
        print("\nDry-run. Применить: … --apply")


if __name__ == "__main__":
    main()
