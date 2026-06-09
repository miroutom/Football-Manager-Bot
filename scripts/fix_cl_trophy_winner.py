#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Перенести +1 trophies ЛЧ с одной команды на другую (ошибочный чемпион группы vs финал).

Только stdlib + sqlite3 (без sqlalchemy) — можно запускать на сервере бота.

Пример для сезона 2 после finalize:
  python3 scripts/fix_cl_trophy_winner.py --season 2 --from Дортмунд --to Ливерпуль
"""
from __future__ import annotations

import argparse
import json
import os
import sqlite3
import sys

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

from utils import season_paths

_PLAYER_TABLES = ("forwards", "midfielders", "defenders", "goalkeepers")


def _shift_trophies(conn: sqlite3.Connection, team: str, delta: int) -> int:
    raw = (team or "").strip().title()
    n = 0
    for tbl in _PLAYER_TABLES:
        cur = conn.execute(
            f"""
            UPDATE {tbl}
            SET trophies = MAX(0, COALESCE(trophies, 0) + ?)
            WHERE team = ?
            """,
            (delta, raw),
        )
        n += cur.rowcount
    return n


def _patch_history(season: int, winner: str) -> None:
    path = os.path.join(_ROOT, "data", "season_history.json")
    with open(path, encoding="utf-8") as f:
        data = json.load(f)
    rows = data.setdefault("champions_league", [])
    if not isinstance(rows, list):
        rows = []
        data["champions_league"] = rows
    found = False
    for row in rows:
        if isinstance(row, list) and len(row) >= 2 and int(row[0]) == season:
            row[1] = winner
            found = True
            break
    if not found:
        rows.append([season, winner])
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


def _rebuild_common_synced(sync_cl: str) -> None:
    try:
        from utils.common_db import rebuild_common_database_for_disk_paths
    except ImportError as e:
        print(f"common_synced: пропуск ({e}) — подтяни common_synced.db из git")
        return
    rebuild_common_database_for_disk_paths(
        season_paths.get_cumulative_league_db_path(),
        sync_cl,
        season_paths.get_cumulative_common_db_path(),
    )
    print("common_synced.db пересобран")


def main() -> None:
    ap = argparse.ArgumentParser(description="Исправить чемпиона ЛЧ (trophies + season_history)")
    ap.add_argument("--season", type=int, required=True)
    ap.add_argument("--from", dest="wrong", required=True, help="Ошибочный чемпион")
    ap.add_argument("--to", dest="right", required=True, help="Правильный чемпион")
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    arch_cl = os.path.join(
        season_paths.season_archive_directory(args.season),
        season_paths.SEASON_CL_NAME,
    )
    sync_cl = season_paths.get_cumulative_cl_db_path()
    paths = [p for p in (arch_cl, sync_cl) if os.path.isfile(p)]
    if not paths:
        raise SystemExit("Нет файлов champions_league.db для правки")

    for path in paths:
        conn = sqlite3.connect(path)
        try:
            n_from = _shift_trophies(conn, args.wrong, -1)
            n_to = _shift_trophies(conn, args.right, +1)
            print(f"{path}: {args.wrong} −1 ({n_from} игр.), {args.right} +1 ({n_to} игр.)")
            if args.dry_run:
                conn.rollback()
            else:
                conn.commit()
        finally:
            conn.close()

    if not args.dry_run:
        _patch_history(args.season, args.right.strip().title())
        _rebuild_common_synced(sync_cl)
        print(f"season_history.json: сезон {args.season} → {args.right}")
    else:
        print("(dry-run, без commit)")


if __name__ == "__main__":
    main()
