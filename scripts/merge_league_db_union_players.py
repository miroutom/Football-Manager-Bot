#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
После git merge с конфликтом в *.db: объединить строки игроков из двух копий SQLite.

Не трогает squads.py — только переносит отсутствующих игроков в целевую БД.

  python3 scripts/merge_league_db_union_players.py \\
    --base db/season_2/backup_pre_pull_XXX/league.db \\
    --incoming /path/to/theirs_league.db \\
    --out db/season_2/league.db
"""
from __future__ import annotations

import argparse
import sqlite3
from pathlib import Path

TABLES = ("forwards", "midfielders", "defenders", "goalkeepers")
KEY_COLS = ("name", "team")


def _rows(conn: sqlite3.Connection, table: str) -> list[dict]:
    cur = conn.execute(f"PRAGMA table_info({table})")
    cols = [r[1] for r in cur.fetchall()]
    out = []
    for row in conn.execute(f"SELECT * FROM {table}"):
        out.append(dict(zip(cols, row)))
    return out


def _insert_if_missing(dst: sqlite3.Connection, table: str, row: dict) -> bool:
    name, team = row.get("name"), row.get("team")
    if not name or not team:
        return False
    exists = dst.execute(
        f"SELECT 1 FROM {table} WHERE name=? AND team=? LIMIT 1",
        (name, team),
    ).fetchone()
    if exists:
        return False
    cols = list(row.keys())
    placeholders = ",".join("?" * len(cols))
    dst.execute(
        f"INSERT INTO {table} ({','.join(cols)}) VALUES ({placeholders})",
        [row[c] for c in cols],
    )
    return True


def merge(base: Path, incoming: Path, out: Path) -> int:
    out.parent.mkdir(parents=True, exist_ok=True)
    if out.exists():
        out.unlink()
    import shutil

    shutil.copy2(base, out)
    added = 0
    b = sqlite3.connect(base)
    i = sqlite3.connect(incoming)
    d = sqlite3.connect(out)
    try:
        for table in TABLES:
            try:
                incoming_rows = _rows(i, table)
            except sqlite3.OperationalError:
                continue
            for row in incoming_rows:
                if _insert_if_missing(d, table, row):
                    added += 1
        d.commit()
    finally:
        b.close()
        i.close()
        d.close()
    return added


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--base", type=Path, required=True, help="наша копия (backup)")
    p.add_argument("--incoming", type=Path, required=True, help="версия с origin/бота")
    p.add_argument("--out", type=Path, required=True)
    args = p.parse_args()
    n = merge(args.base, args.incoming, args.out)
    print(f"Добавлено строк игроков: {n} → {args.out}")


if __name__ == "__main__":
    main()
