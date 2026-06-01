#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Игроки с одинаковым полем ``name`` в одном сезоне (разные люди / строки).

По умолчанию — только ``db/season_2/league.db``.

  python3 scripts/list_duplicate_names.py
  python3 scripts/list_duplicate_names.py --season 1
  python3 scripts/list_duplicate_names.py --json -o data/duplicate_names_s2.json
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


def _load_season_league(season: int) -> list[dict]:
    path = os.path.join(ROOT, "db", f"season_{season}", "league.db")
    if not os.path.isfile(path):
        raise FileNotFoundError(path)
    rows: list[dict] = []
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
            for rec in conn.execute(f"SELECT {sel} FROM {table}"):
                rid, name, team, pos = rec[0], rec[1], rec[2], rec[3]
                overall = int(rec[4] or 0) if has_ov and len(rec) > 4 else 0
                team = (team or "").strip()
                nm = (name or "").strip()
                if not nm:
                    continue
                rows.append(
                    {
                        "table": table,
                        "id": rid,
                        "name": nm,
                        "name_norm": _norm_cmp(nm),
                        "team": team,
                        "position": (pos or "").strip().upper(),
                        "overall": overall,
                    }
                )
    finally:
        conn.close()
    return rows


def _find_duplicates(rows: list[dict]) -> list[dict]:
    by_name: dict[str, list[dict]] = defaultdict(list)
    display: dict[str, str] = {}
    for r in rows:
        by_name[r["name_norm"]].append(r)
        display.setdefault(r["name_norm"], r["name"])

    out: list[dict] = []
    for key in sorted(by_name, key=lambda k: display[k].casefold()):
        group = by_name[key]
        if len(group) < 2:
            continue
        out.append(
            {
                "name": display[key],
                "count": len(group),
                "players": sorted(
                    group,
                    key=lambda r: (r["position"], r["team"], r["table"], r["id"]),
                ),
            }
        )
    return out


def _print_report(groups: list[dict], season: int) -> None:
    total_rows = sum(g["count"] for g in groups)
    print(f"season_{season}/league.db — одинаковое name у разных строк: {len(groups)} имён, {total_rows} игроков\n")
    for g in groups:
        positions = sorted({p["position"] for p in g["players"]})
        print(f"=== {g['name']!r} ===  ({g['count']} строк, позиции: {', '.join(positions)})")
        for p in g["players"]:
            fa = " [FA]" if p["team"].casefold() == "free agent" else ""
            print(
                f"  {p['table']:<14} id={p['id']:<5} {p['position']:<4} {p['team']:<22} ovr={p['overall']}{fa}"
            )
        print()


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--season", type=int, default=2, choices=(1, 2))
    ap.add_argument("--json", action="store_true")
    ap.add_argument("-o", "--output")
    args = ap.parse_args()

    rows = _load_season_league(args.season)
    groups = _find_duplicates(rows)

    if args.json or args.output:
        payload = {
            "season": args.season,
            "db": f"season_{args.season}/league.db",
            "duplicate_names": groups,
            "name_count": len(groups),
            "player_rows": sum(g["count"] for g in groups),
        }
        text = json.dumps(payload, ensure_ascii=False, indent=2)
        if args.output:
            with open(args.output, "w", encoding="utf-8") as f:
                f.write(text)
            print(f"Записано: {args.output}")
        else:
            print(text)
    else:
        _print_report(groups, args.season)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
