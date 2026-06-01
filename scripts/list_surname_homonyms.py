#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Омонимы: одна фамилия (токен), разные люди — другая позиция и/или клуб.

Сводка по всем season_* и *_synced.db. Для ручного заполнения полных имён.

Критерий: ≥2 разных позиций **или** ≥2 пар (позиция + клуб) с одной фамилией
(в т.ч. трансфер в другой клуб на той же позиции — проверьте глазами).

  python3 scripts/list_surname_homonyms.py
  python3 scripts/list_surname_homonyms.py --season 2
  python3 scripts/list_surname_homonyms.py --season 2 --positions-only
  python3 scripts/list_surname_homonyms.py --json -o data/surname_homonyms_report.json
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

_ALL_DB_TARGETS = [
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


def _db_targets(season: int | None, *, include_cl_common: bool) -> list[tuple[str, str]]:
    if season is None:
        return list(_ALL_DB_TARGETS)
    prefix = f"season_{season}/"
    out = [(rel, label) for rel, label in _ALL_DB_TARGETS if rel.startswith(prefix)]
    if not include_cl_common:
        out = [(rel, label) for rel, label in out if label.endswith(":league")]
    return out


def _surname_token(name: str, surname: str | None) -> str:
    sn = (surname or "").strip()
    nm = (name or "").strip()
    if sn and nm and sn.casefold() != nm.casefold():
        return sn
    raw = nm or sn
    parts = raw.split()
    if len(parts) >= 2:
        return parts[-1]
    return raw


def _iter_players(path: str, db_label: str):
    if not os.path.isfile(path):
        return
    conn = sqlite3.connect(path)
    try:
        for table in _TABLES:
            cols = {r[1] for r in conn.execute(f"PRAGMA table_info({table})")}
            if "name" not in cols:
                continue
            has_surname = "surname" in cols
            has_ov = "overall" in cols
            sel = ["id", "name", "team", "position"]
            if has_surname:
                sel.insert(2, "surname")
            if has_ov:
                sel.append("overall")
            q = f"SELECT {', '.join(sel)} FROM {table}"
            for row in conn.execute(q):
                i = 0
                rid = row[i]
                i += 1
                name = row[i]
                i += 1
                surname = None
                if has_surname:
                    surname = row[i]
                    i += 1
                team = row[i]
                i += 1
                pos = row[i]
                i += 1
                overall = int(row[i] or 0) if has_ov and i < len(row) else 0
                team = (team or "").strip()
                if not team or team.casefold() == "free agent":
                    continue
                nm = (name or "").strip()
                if not nm:
                    continue
                sur = _surname_token(nm, surname)
                yield {
                    "db": db_label,
                    "table": table,
                    "id": rid,
                    "name": nm,
                    "surname": (surname or "").strip() if surname else "",
                    "surname_token": sur,
                    "surname_norm": _norm_cmp(sur),
                    "team": team,
                    "position": (pos or "").strip().upper(),
                    "overall": overall,
                }
    finally:
        conn.close()


def _find_homonyms(
    db_targets: list[tuple[str, str]],
    *,
    positions_only: bool = False,
    min_variants: int = 2,
) -> list[dict]:
    by_sur: dict[str, list[dict]] = defaultdict(list)
    display: dict[str, str] = {}

    for rel, label in db_targets:
        path = os.path.join(ROOT, "db", rel)
        for row in _iter_players(path, label):
            sn = row["surname_norm"]
            by_sur[sn].append(row)
            display.setdefault(sn, row["surname_token"])

    out: list[dict] = []
    for sn, rows in sorted(by_sur.items(), key=lambda x: display[x[0]].casefold()):
        variants: set[tuple[str, str]] = set()
        positions: set[str] = set()
        for r in rows:
            variants.add((r["position"], _norm_cmp(r["team"])))
            positions.add(r["position"])
        if positions_only:
            if len(positions) < 2:
                continue
        elif len(positions) < 2 and len(variants) < min_variants:
            continue

        # уникальные «профили» для отчёта
        profiles: dict[tuple[str, str], dict] = {}
        for r in rows:
            k = (r["position"], _norm_cmp(r["team"]))
            if k not in profiles:
                profiles[k] = {
                    "position": r["position"],
                    "team": r["team"],
                    "example_name": r["name"],
                    "example_overall": r["overall"],
                    "occurrences": [],
                }
            profiles[k]["occurrences"].append(
                {
                    "db": r["db"],
                    "table": r["table"],
                    "id": r["id"],
                    "name": r["name"],
                    "overall": r["overall"],
                }
            )

        out.append(
            {
                "surname": display[sn],
                "surname_norm": sn,
                "positions": sorted(positions),
                "variant_count": len(variants),
                "profiles": sorted(
                    profiles.values(),
                    key=lambda p: (p["position"], p["team"]),
                ),
            }
        )
    return out


def _print_report(groups: list[dict], *, scope: str) -> None:
    print(f"[{scope}] Омонимов: {len(groups)}\n")
    for g in groups:
        print(f"=== {g['surname']} ===  позиции: {', '.join(g['positions'])}")
        for p in g["profiles"]:
            ex = p["example_name"]
            ov = p["example_overall"]
            print(f"  • {p['position']:<4} {p['team']:<22}  пример: {ex!r}  OVR {ov}")
            for occ in p["occurrences"][:1]:
                print(
                    f"      {occ['table']} id={occ['id']} "
                    f"name={occ['name']!r} ovr={occ['overall']}"
                )
        print()


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--season", type=int, choices=(1, 2), help="Только архив сезона N")
    ap.add_argument(
        "--with-cl-common",
        action="store_true",
        help="С --season: ещё champions_league.db и common.db",
    )
    ap.add_argument(
        "--positions-only",
        action="store_true",
        help="Только фамилии с ≥2 позициями (без «тот же амплуа, другой клуб»)",
    )
    ap.add_argument("--json", action="store_true")
    ap.add_argument("-o", "--output", help="Файл для JSON")
    args = ap.parse_args()

    targets = _db_targets(args.season, include_cl_common=args.with_cl_common)
    if args.season:
        scope = f"season_{args.season}" + ("" if args.with_cl_common else ", league.db")
    else:
        scope = "все БД"
    groups = _find_homonyms(targets, positions_only=args.positions_only)
    if args.json or args.output:
        payload = {"scope": scope, "homonyms": groups, "count": len(groups)}
        text = json.dumps(payload, ensure_ascii=False, indent=2)
        if args.output:
            os.makedirs(os.path.dirname(args.output) or ".", exist_ok=True)
            with open(args.output, "w", encoding="utf-8") as f:
                f.write(text)
            print(f"Записано: {args.output} ({len(groups)} фамилий)")
        else:
            print(text)
    else:
        _print_report(groups, scope=scope)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
