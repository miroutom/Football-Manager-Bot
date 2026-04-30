#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Локальные разовые правки БД (награды, удаление rating, удаление дубля «Лауриент»).

  python3 scripts/apply_local_db_fixes.py              # всё
  python3 scripts/apply_local_db_fixes.py --awards-only
  python3 scripts/apply_local_db_fixes.py --drop-rating-only
  python3 scripts/apply_local_db_fixes.py --delete-lauriente-only

Требуется SQLite 3.35+ для ``ALTER TABLE … DROP COLUMN`` (колонка rating).
"""
from __future__ import annotations

import argparse
import os
import sqlite3
import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

PLAYER_TABLES = ("forwards", "midfielders", "defenders", "goalkeepers")

LAURIENT_TEAM = "Реал Сосьедад"
LAURIENT_NAME = "Лауриент"


def _iter_sqlite_files() -> list[Path]:
    db = _ROOT / "db"
    if not db.is_dir():
        return []
    out: list[Path] = []
    for p in db.rglob("*.db"):
        if p.is_file():
            out.append(p)
    return sorted(out)


def _sqlite_supports_drop_column() -> bool:
    v = sqlite3.sqlite_version_info
    return v >= (3, 35, 0)


def apply_awards(conn: sqlite3.Connection) -> list[str]:
    log: list[str] = []
    cur = conn.cursor()
    for sql, label in (
        (
            "UPDATE forwards SET golden_balls = 1, golden_boots = 1 "
            "WHERE team = 'Интер' AND position = 'ФРВ' AND name = 'Мартинез'",
            "Мартинез · ЗМ + бутса",
        ),
        (
            "UPDATE goalkeepers SET golden_gloves = 1 "
            "WHERE team = 'Интер' AND position = 'ВРТ' AND name = 'Зоммер'",
            "Зоммер · перчатка",
        ),
        (
            "UPDATE midfielders SET golden_boys = 1 "
            "WHERE team = 'Фрайбург' AND position = 'ЦП' AND name = 'Рёль'",
            "Рёль · Golden Boy",
        ),
    ):
        cur.execute(sql)
        n = cur.rowcount or 0
        if n:
            log.append(f"{label}: {n}")
    return log


def drop_rating_columns(conn: sqlite3.Connection, path: str) -> list[str]:
    if not _sqlite_supports_drop_column():
        raise SystemExit(
            f"SQLite {sqlite3.sqlite_version} < 3.35 — нет DROP COLUMN. Обновите SQLite."
        )
    log: list[str] = []
    cur = conn.cursor()
    for table in PLAYER_TABLES:
        cols = {r[1] for r in cur.execute(f"PRAGMA table_info({table})")}
        if "rating" not in cols:
            continue
        try:
            cur.execute(f"ALTER TABLE {table} DROP COLUMN rating")
            log.append(f"{path}:{table}.rating")
        except sqlite3.OperationalError as e:
            log.append(f"{path}:{table} SKIP ({e})")
    return log


def delete_lauriente(conn: sqlite3.Connection) -> int:
    n = 0
    cur = conn.cursor()
    for table in PLAYER_TABLES:
        cur.execute(
            f"DELETE FROM {table} WHERE name = ? AND team = ?",
            (LAURIENT_NAME, LAURIENT_TEAM),
        )
        n += cur.rowcount or 0
    return n


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--awards-only", action="store_true")
    ap.add_argument("--drop-rating-only", action="store_true")
    ap.add_argument("--delete-lauriente-only", action="store_true")
    args = ap.parse_args()

    flags = (args.awards_only, args.drop_rating_only, args.delete_lauriente_only)
    if sum(bool(x) for x in flags) > 1:
        ap.error("укажите не больше одного из --awards-only / --drop-rating-only / --delete-lauriente-only")
    if args.awards_only:
        do_awards, do_rating, do_lau = True, False, False
    elif args.drop_rating_only:
        do_awards, do_rating, do_lau = False, True, False
    elif args.delete_lauriente_only:
        do_awards, do_rating, do_lau = False, False, True
    else:
        do_awards = do_rating = do_lau = True

    files = _iter_sqlite_files()
    if not files:
        print("Нет *.db в db/")
        return

    total_rating: list[str] = []
    for path in files:
        p = str(path)
        conn = sqlite3.connect(p)
        try:
            if do_awards:
                aw = apply_awards(conn)
                if aw:
                    print(f"{p} awards:", "; ".join(aw))
            if do_lau:
                k = delete_lauriente(conn)
                if k:
                    print(f"{p} deleted Lauriente rows: {k}")
            if do_rating:
                total_rating.extend(drop_rating_columns(conn, p))
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()

    if do_rating and total_rating:
        print("Dropped rating:", len(total_rating), "ops")
        for line in total_rating[:40]:
            print(" ", line)
        if len(total_rating) > 40:
            print(f"  … и ещё {len(total_rating) - 40}")
    print("OK")


if __name__ == "__main__":
    main()
