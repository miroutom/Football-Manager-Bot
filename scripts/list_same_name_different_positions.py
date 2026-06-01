#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Игроки с одинаковым полем ``name``, но разными позициями (в разных БД или строках).

  python3 scripts/list_same_name_different_positions.py
  python3 scripts/list_same_name_different_positions.py --json -o data/same_name_multi_pos.json
"""
from __future__ import annotations

import argparse
import json
import os
import sqlite3
import sys
from collections import defaultdict

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from player_stats import _norm_cmp

_TABLES = ("forwards", "midfielders", "defenders", "goalkeepers")

_DB_TARGETS = [
    ("season_1/league.db", "s1:league"),
    ("season_1/champions_league.db", "s1:cl"),
    ("season_1/common.db", "s1:common"),
    ("season_2/league.db", "s2:league"),
    ("season_2/champions_league.db", "s2:cl"),
    ("season_2/common.db", "s2:common"),
    ("league_synced.db", "sync:league"),
    ("champions_league_synced.db", "sync:cl"),
    ("common_synced.db", "sync:common"),
]


def _iter_players(path: str, db_label: str):
    if not os.path.isfile(path):
        return
    conn = sqlite3.connect(path)
    try:
        for table in _TABLES:
            cols = {r[1] for r in conn.execute(f"PRAGMA table_info({table})")}
            if "name" not in cols:
                continue
            has_ov = "overall" in cols
            sel = "id, name, team, position"
            if has_ov:
                sel += ", overall"
            for row in conn.execute(f"SELECT {sel} FROM {table}"):
                rid, name, team, pos = row[0], row[1], row[2], row[3]
                overall = int(row[4] or 0) if has_ov and len(row) > 4 else 0
                team = (team or "").strip()
                nm = (name or "").strip()
                if not nm:
                    continue
                if team.casefold() == "free agent":
                    continue
                yield {
                    "db": db_label,
                    "table": table,
                    "id": rid,
                    "name": nm,
                    "name_norm": _norm_cmp(nm),
                    "team": team,
                    "position": (pos or "").strip().upper(),
                    "overall": overall,
                }
    finally:
        conn.close()


def _find_multi_position_names() -> list[dict]:
    by_name: dict[str, list[dict]] = defaultdict(list)
    display: dict[str, str] = {}

    for rel, label in _DB_TARGETS:
        path = os.path.join(ROOT, "db", rel)
        for row in _iter_players(path, label):
            k = row["name_norm"]
            by_name[k].append(row)
            display.setdefault(k, row["name"])

    out: list[dict] = []
    for k, rows in sorted(by_name.items(), key=lambda x: display[x[0]].casefold()):
        positions = {r["position"] for r in rows if r["position"]}
        if len(positions) < 2:
            continue

        by_pos: dict[str, list[dict]] = defaultdict(list)
        for r in rows:
            by_pos[r["position"]].append(r)

        out.append(
            {
                "name": display[k],
                "name_norm": k,
                "positions": sorted(positions),
                "by_position": {
                    pos: sorted(
                        by_pos[pos],
                        key=lambda r: (r["db"], r["team"], r["id"]),
                    )
                    for pos in sorted(by_pos)
                },
            }
        )
    return out


def _print_report(groups: list[dict]) -> None:
    print(f"Имя с разными позициями: {len(groups)}\n")
    for g in groups:
        print(f"=== {g['name']!r} ===  позиции: {', '.join(g['positions'])}")
        for pos in g["positions"]:
            rows = g["by_position"][pos]
            teams = sorted({r["team"] for r in rows})
            print(f"  [{pos}] клубы: {', '.join(teams[:8])}" + (" …" if len(teams) > 8 else ""))
            shown = 0
            for r in rows:
                if shown >= 5:
                    break
                print(
                    f"      {r['db']} {r['table']} id={r['id']} "
                    f"{r['team']} ovr={r['overall']}"
                )
                shown += 1
            if len(rows) > 5:
                print(f"      … всего {len(rows)} строк для позиции {pos}")
        print()


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--json", action="store_true")
    ap.add_argument("-o", "--output", help="Файл для JSON")
    args = ap.parse_args()

    groups = _find_multi_position_names()
    if args.json or args.output:
        payload = {"same_name_multi_position": groups, "count": len(groups)}
        text = json.dumps(payload, ensure_ascii=False, indent=2)
        if args.output:
            os.makedirs(os.path.dirname(args.output) or ".", exist_ok=True)
            with open(args.output, "w", encoding="utf-8") as f:
                f.write(text)
            print(f"Записано: {args.output} ({len(groups)} имён)")
        else:
            print(text)
    else:
        _print_report(groups)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
