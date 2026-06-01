#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Восстановить поля статистики из снимка БД, сохранив текущие имя/фамилию и состав.

Копируются только счётчики и status; name, surname, overall, team, position, nation,
left_team не трогаются. Сопоставление строк — по id внутри таблицы.

  python3 scripts/restore_stats_from_backup.py
  python3 scripts/restore_stats_from_backup.py --apply
  python3 scripts/restore_stats_from_backup.py --apply --src db/backup_pre_names_apply_20260601_162149
"""
from __future__ import annotations

import argparse
import os
import shutil
import sqlite3
import sys
from datetime import datetime

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

DEFAULT_SRC = os.path.join(ROOT, "db", "backup_pre_names_apply_20260601_162149")

TABLES = ("forwards", "midfielders", "defenders", "goalkeepers")

# Не перезаписываем из бэкапа
ROSTER_COLS = frozenset(
    {
        "id",
        "name",
        "surname",
        "overall",
        "team",
        "position",
        "nation",
        "left_team",
    }
)

# Явный список не нужен: берём все колонки таблицы, кроме состава (ROSTER_COLS).

DB_PAIRS: list[tuple[str, str]] = [
    ("season_1/league.db", "season_1/league.db"),
    ("season_1/champions_league.db", "season_1/champions_league.db"),
    ("season_1/common.db", "season_1/common.db"),
    ("season_2/league.db", "season_2/league.db"),
    ("season_2/champions_league.db", "season_2/champions_league.db"),
    ("season_2/common.db", "season_2/common.db"),
    ("league_synced.db", "league_synced.db"),
    ("champions_league_synced.db", "champions_league_synced.db"),
    ("common_synced.db", "common_synced.db"),
]


def _stat_cols_for_table(
    src: sqlite3.Connection, dst: sqlite3.Connection, table: str
) -> list[str]:
    src_cols = [r[1] for r in src.execute(f"PRAGMA table_info({table})").fetchall()]
    dst_cols = {r[1] for r in dst.execute(f"PRAGMA table_info({table})").fetchall()}
    return [c for c in src_cols if c in dst_cols and c not in ROSTER_COLS]


def _restore_db(src_path: str, dst_path: str, *, apply: bool) -> tuple[int, int]:
    """Вернуть (число обновлённых ячеек-полей, число строк с хотя бы одним изменением)."""
    src = sqlite3.connect(src_path)
    dst = sqlite3.connect(dst_path)
    rows_touched = 0
    fields_written = 0
    try:
        for table in TABLES:
            if table not in [
                r[0]
                for r in src.execute(
                    "SELECT name FROM sqlite_master WHERE type='table'"
                ).fetchall()
            ]:
                continue
            stat_cols = _stat_cols_for_table(src, dst, table)
            if not stat_cols:
                continue
            col_list = ",".join(stat_cols)
            backup_rows = {
                r[0]: r[1:]
                for r in src.execute(f"SELECT id,{col_list} FROM {table}")
            }
            for row in dst.execute(f"SELECT id,{col_list} FROM {table}"):
                pid = row[0]
                if pid not in backup_rows:
                    continue
                cur_vals = row[1:]
                bak_vals = backup_rows[pid]
                if cur_vals == bak_vals:
                    continue
                rows_touched += 1
                if apply:
                    sets = ", ".join(f"{c}=?" for c in stat_cols)
                    dst.execute(
                        f"UPDATE {table} SET {sets} WHERE id=?",
                        (*bak_vals, pid),
                    )
                fields_written += sum(1 for a, b in zip(cur_vals, bak_vals) if a != b)
        if apply:
            dst.commit()
    finally:
        src.close()
        dst.close()
    return fields_written, rows_touched


def _safety_backup(dst_path: str, tag: str) -> str:
    base = os.path.dirname(dst_path)
    name = os.path.basename(dst_path)
    out_dir = os.path.join(base, f"backup_pre_stat_restore_{tag}")
    os.makedirs(out_dir, exist_ok=True)
    out = os.path.join(out_dir, name)
    shutil.copy2(dst_path, out)
    return out


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--src", default=DEFAULT_SRC, help="Папка снимка (корень backup)")
    ap.add_argument("--apply", action="store_true", help="Записать в БД (иначе dry-run)")
    args = ap.parse_args()
    src_root = os.path.abspath(args.src)
    if not os.path.isdir(src_root):
        print(f"Нет папки бэкапа: {src_root}", file=sys.stderr)
        return 1

    tag = datetime.now().strftime("%Y%m%d_%H%M%S")
    total_rows = 0
    total_fields = 0

    for rel_src, rel_dst in DB_PAIRS:
        sp = os.path.join(src_root, rel_src)
        dp = os.path.join(ROOT, "db", rel_dst)
        if not os.path.isfile(sp):
            print(f"SKIP (нет в бэкапе): {rel_src}")
            continue
        if not os.path.isfile(dp):
            print(f"SKIP (нет цели): {rel_dst}")
            continue
        if args.apply:
            snap = _safety_backup(dp, tag)
            print(f"снимок: {snap}")
        fields, rows = _restore_db(sp, dp, apply=args.apply)
        mode = "APPLY" if args.apply else "dry-run"
        print(f"[{mode}] {rel_dst}: строк={rows}, полей={fields}")
        total_rows += rows
        total_fields += fields

    print(f"Итого: строк={total_rows}, полей={total_fields}")
    if not args.apply:
        print("Повторите с --apply для записи.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
