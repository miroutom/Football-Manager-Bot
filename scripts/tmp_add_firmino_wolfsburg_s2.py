#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Временно: добавить Фирмино (ФРВ, 82, Вольфсбург) одной строкой в forwards — без синка заявок и без prune.

Цели (если файл есть и не пустой, есть таблица forwards):
  - db/season_2/league.db
  - db/season_2/champions_league.db
  - db/season_2/common.db
  - db/league_synced.db
  - db/champions_league_synced.db
  - db/common_synced.db

Повторный запуск: если уже есть игрок с тем же именем и клубом (без учёта регистра) — пропуск.

Запуск из корня проекта:
  python scripts/tmp_add_firmino_wolfsburg_s2.py
  python scripts/tmp_add_firmino_wolfsburg_s2.py --dry-run
"""
from __future__ import annotations

import argparse
import sqlite3
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

NAME = "Фирмино"
TEAM = "Вольфсбург"
POSITION = "ФРВ"
OVERALL = 82
NATION = "Бразилия"
STATUS = "reserve"


def _db_paths() -> list[Path]:
    return [
        ROOT / "db" / "season_2" / "league.db",
        ROOT / "db" / "season_2" / "champions_league.db",
        ROOT / "db" / "season_2" / "common.db",
        ROOT / "db" / "league_synced.db",
        ROOT / "db" / "champions_league_synced.db",
        ROOT / "db" / "common_synced.db",
    ]


def _table_exists(conn: sqlite3.Connection, name: str) -> bool:
    row = conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?",
        (name,),
    ).fetchone()
    return row is not None


def _already_has(conn: sqlite3.Connection) -> bool:
    row = conn.execute(
        """
        SELECT 1 FROM forwards
        WHERE team = ? AND lower(trim(name)) = lower(trim(?))
        LIMIT 1
        """,
        (TEAM, NAME),
    ).fetchone()
    return row is not None


def _insert_forward(conn: sqlite3.Connection, dry_run: bool) -> str:
    if _already_has(conn):
        return "skip_exists"
    sql = """
        INSERT INTO forwards (
            name, overall, team, position,
            matches, goals, assists, ga,
            trophies, golden_balls, golden_boots, golden_boys,
            nation, status, yellow_cards, red_cards
        ) VALUES (?, ?, ?, ?, 0, 0, 0, 0, 0, 0, 0, 0, ?, ?, 0, 0)
    """
    if dry_run:
        return "would_insert"
    conn.execute(
        sql,
        (NAME, OVERALL, TEAM, POSITION, NATION, STATUS),
    )
    conn.commit()
    return "inserted"


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument(
        "--dry-run",
        action="store_true",
        help="только показать, куда бы вставили, без записи",
    )
    args = ap.parse_args()

    for path in _db_paths():
        rel = path.relative_to(ROOT)
        if not path.is_file() or path.stat().st_size == 0:
            print(f"{rel}: пропуск (нет файла или пустой)")
            continue
        try:
            conn = sqlite3.connect(str(path))
        except sqlite3.Error as e:
            print(f"{rel}: ошибка открытия: {e}")
            continue
        try:
            if not _table_exists(conn, "forwards"):
                print(f"{rel}: нет таблицы forwards")
                continue
            action = _insert_forward(conn, args.dry_run)
            if action == "skip_exists":
                print(f"{rel}: уже есть {NAME} ({TEAM})")
            elif action == "would_insert":
                print(f"{rel}: dry-run — добавил бы {NAME} {POSITION} {OVERALL}")
            else:
                print(f"{rel}: добавлен {NAME} {POSITION} {OVERALL} ({TEAM})")
        finally:
            conn.close()

    if args.dry_run:
        print("Dry-run: БД не менялись.")


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        sys.exit(130)
