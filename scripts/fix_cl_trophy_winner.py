#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Перенести +1 trophies ЛЧ с одной команды на другую (ошибочный чемпион группы vs финал).

Пример для сезона 2 после finalize:
  python3 scripts/fix_cl_trophy_winner.py --season 2 --from Дортмунд --to Ливерпуль
"""
from __future__ import annotations

import argparse
import json
import os
import sys

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

from sqlalchemy import create_engine, func, or_
from sqlalchemy.orm import sessionmaker

from data.defender import Defender
from data.forward import Forward
from data.goalkeeper import Goalkeeper
from data.midfielder import Midfielder
from utils import season_paths

_ALL = (Forward, Midfielder, Defender, Goalkeeper)


def _shift_trophies(session, team: str, delta: int) -> int:
    raw = (team or "").strip()
    tl = raw.lower()
    n = 0
    for Cls in _ALL:
        rows = (
            session.query(Cls)
            .filter(or_(Cls.team == raw, func.lower(Cls.team) == tl))
            .all()
        )
        for row in rows:
            cur = int(getattr(row, "trophies", 0) or 0)
            row.trophies = max(0, cur + delta)
            n += 1
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
        eng = create_engine(f"sqlite:///{path}")
        S = sessionmaker(bind=eng)
        s = S()
        try:
            n_from = _shift_trophies(s, args.wrong, -1)
            n_to = _shift_trophies(s, args.right, +1)
            print(f"{path}: {args.wrong} −1 ({n_from} игр.), {args.right} +1 ({n_to} игр.)")
            if not args.dry_run:
                s.commit()
            else:
                s.rollback()
        finally:
            s.close()
            eng.dispose()

    if not args.dry_run:
        _patch_history(args.season, args.right.strip().title())
        try:
            from utils.common_db import rebuild_common_database_for_disk_paths

            rebuild_common_database_for_disk_paths(
                season_paths.get_cumulative_league_db_path(),
                sync_cl,
                season_paths.get_cumulative_common_db_path(),
            )
            print("common_synced.db пересобран")
        except Exception as e:
            print(f"common_synced: {e!s}")
        print(f"season_history.json: сезон {args.season} → {args.right}")
    else:
        print("(dry-run, без commit)")


if __name__ == "__main__":
    main()
