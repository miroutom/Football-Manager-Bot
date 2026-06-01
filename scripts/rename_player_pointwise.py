#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Точечное переименование одного игрока во всех БД (season_1/2, *_synced).

Только поле ``name``; статистика и id не меняются.

  python3 scripts/rename_player_pointwise.py \\
    --new-name "Хулиан Альварез" \\
    --was-name "Альварез" \\
    --position ФРВ \\
    --table forwards \\
    --dry-run

  python3 scripts/rename_player_pointwise.py ... --apply
"""
from __future__ import annotations

import argparse
import os
import sqlite3
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from player_stats import _norm_cmp

_TABLES = ("forwards", "midfielders", "defenders", "goalkeepers")

_ALL_DBS = [
    "season_1/league.db",
    "season_1/champions_league.db",
    "season_1/common.db",
    "season_2/league.db",
    "season_2/champions_league.db",
    "season_2/common.db",
    "league_synced.db",
    "champions_league_synced.db",
    "common_synced.db",
]


def _matches(
    row: dict,
    *,
    was_name: str,
    was_norm: str,
    position: str | None,
    positions: list[str],
    table: str | None,
    teams: list[str],
    team_norms: set[str],
    min_overall: int | None,
    max_overall: int | None,
) -> bool:
    nm = (row["name"] or "").strip()
    if _norm_cmp(nm) != was_norm and nm != was_name:
        return False
    if table and row["table"] != table:
        return False
    pos = (row["position"] or "").strip().upper()
    if position and pos != position.strip().upper():
        return False
    if positions and pos not in {p.strip().upper() for p in positions}:
        return False
    if teams:
        if _norm_cmp(row["team"] or "") not in team_norms:
            return False
    ov = int(row["overall"] or 0)
    if min_overall is not None and ov < min_overall:
        return False
    if max_overall is not None and ov > max_overall:
        return False
    return True


def _scan_db(path: str, rel: str, **match_kw) -> list[dict]:
    hits: list[dict] = []
    conn = sqlite3.connect(path)
    try:
        for tbl in _TABLES:
            cols = {r[1] for r in conn.execute(f"PRAGMA table_info({tbl})")}
            if "name" not in cols:
                continue
            has_ov = "overall" in cols
            sel = "id, name, team, position"
            if has_ov:
                sel += ", overall"
            for rec in conn.execute(f"SELECT {sel} FROM {tbl}"):
                rid, name, team, pos = rec[0], rec[1], rec[2], rec[3]
                overall = int(rec[4] or 0) if has_ov and len(rec) > 4 else 0
                row = {
                    "db": rel,
                    "path": path,
                    "table": tbl,
                    "id": rid,
                    "name": (name or "").strip(),
                    "team": (team or "").strip(),
                    "position": (pos or "").strip().upper(),
                    "overall": overall,
                }
                if _matches(row, **match_kw):
                    hits.append(row)
    finally:
        conn.close()
    return hits


def _apply(path: str, table: str, row_id: int, new_name: str) -> None:
    conn = sqlite3.connect(path)
    try:
        conn.execute(
            f"UPDATE {table} SET name = ? WHERE id = ?",
            (new_name, row_id),
        )
        conn.commit()
    finally:
        conn.close()


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--new-name", required=True)
    ap.add_argument("--was-name", required=True, help="Текущее значение name")
    ap.add_argument("--position", help="Одна позиция, напр. ФРВ")
    ap.add_argument(
        "--positions",
        help="Несколько позиций через запятую",
    )
    ap.add_argument("--table", choices=_TABLES, help="Только эта таблица")
    ap.add_argument(
        "--teams",
        help="Клубы через запятую (если не указано — любой клуб)",
    )
    ap.add_argument("--min-overall", type=int)
    ap.add_argument("--max-overall", type=int)
    ap.add_argument("--apply", action="store_true")
    ap.add_argument("--dry-run", action="store_true", help="По умолчанию, если нет --apply")
    args = ap.parse_args()

    if args.apply and args.dry_run:
        print("Укажите только --apply или --dry-run")
        return 1

    positions = [p.strip() for p in (args.positions or "").split(",") if p.strip()]
    teams = [t.strip() for t in (args.teams or "").split(",") if t.strip()]
    team_norms = {_norm_cmp(t) for t in teams}
    was_norm = _norm_cmp(args.was_name)

    match_kw = dict(
        was_name=args.was_name,
        was_norm=was_norm,
        position=args.position,
        positions=positions,
        table=args.table,
        teams=teams,
        team_norms=team_norms,
        min_overall=args.min_overall,
        max_overall=args.max_overall,
    )

    all_hits: list[dict] = []
    for rel in _ALL_DBS:
        path = os.path.join(ROOT, "db", rel)
        if not os.path.isfile(path):
            continue
        all_hits.extend(_scan_db(path, rel, **match_kw))

    if not all_hits:
        print("Ничего не найдено.")
        return 1

    print(f"Найдено строк: {len(all_hits)} → {args.new_name!r}\n")
    for h in all_hits:
        print(
            f"  {'APPLY' if args.apply else 'rename'} {h['db']} {h['table']} id={h['id']} "
            f"{h['name']!r} → {args.new_name!r}  ({h['position']} {h['team']} ovr={h['overall']})"
        )

    if not args.apply:
        print("\nДобавьте --apply для записи.")
        return 0

    for h in all_hits:
        if h["name"] == args.new_name:
            continue
        _apply(h["path"], h["table"], h["id"], args.new_name)
    print("\nГотово.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
