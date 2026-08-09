#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Развести person_id: Антониу Сильва (657) ≠ Сильва/Челси (773) во всех SQLite сезона."""
from __future__ import annotations

import os
import sqlite3
import sys

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

ANTONIO_PID = 657


def _iter_db_paths():
    from utils import season_paths

    seen: set[str] = set()
    for getter in (
        season_paths.get_cumulative_league_db_path,
        season_paths.get_cumulative_cl_db_path,
        season_paths.get_cumulative_common_db_path,
    ):
        p = getter()
        if p and os.path.isfile(p):
            ap = os.path.abspath(p)
            if ap not in seen:
                seen.add(ap)
                yield ap
    db_dir = os.path.join(season_paths.PROJECT_ROOT, "db")
    if os.path.isdir(db_dir):
        for entry in os.listdir(db_dir):
            if not entry.startswith("season_"):
                continue
            base = os.path.join(db_dir, entry)
            for fname in (
                season_paths.SEASON_LEAGUE_NAME,
                season_paths.SEASON_CL_NAME,
                season_paths.SEASON_COMMON_NAME,
            ):
                path = os.path.join(base, fname)
                if os.path.isfile(path):
                    ap = os.path.abspath(path)
                    if ap not in seen:
                        seen.add(ap)
                        yield ap
    for p in (
        season_paths.get_league_db_path(),
        season_paths.get_cl_db_path(),
        season_paths.get_common_db_path(),
    ):
        if p and os.path.isfile(p):
            ap = os.path.abspath(p)
            if ap not in seen:
                seen.add(ap)
                yield ap


def main() -> int:
    fixed = 0
    for path in _iter_db_paths():
        conn = sqlite3.connect(path)
        try:
            for tbl in ("defenders", "midfielders", "forwards", "goalkeepers"):
                try:
                    cur = conn.execute(
                        f"UPDATE {tbl} SET person_id=? "
                        f"WHERE name='Антониу Сильва' AND team='Аталанта' AND person_id!=?",
                        (ANTONIO_PID, ANTONIO_PID),
                    )
                    fixed += int(cur.rowcount or 0)
                except sqlite3.OperationalError:
                    pass
            conn.commit()
        finally:
            conn.close()
    print(f"OK: обновлено строк person_id={ANTONIO_PID}: {fixed}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
