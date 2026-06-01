#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Игроки, у которых имя == фамилия (заглушка до раздельного имени).

  python3 scripts/list_players_name_equals_surname.py
  python3 scripts/list_players_name_equals_surname.py --season 2
  python3 scripts/list_players_name_equals_surname.py --all-seasons
  python3 scripts/list_players_name_equals_surname.py --season 1 --db league
  python3 scripts/list_players_name_equals_surname.py --json -o /tmp/name_eq_surname.txt
"""
from __future__ import annotations

import argparse
import json
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from data.defender import Defender
from data.forward import Forward
from data.goalkeeper import Goalkeeper
from data.midfielder import Midfielder

_ALL = (Forward, Midfielder, Defender, Goalkeeper)

_DB_CHOICES = ("league", "cl", "common", "all")


def _name_eq_surname(name: str, surname: str | None) -> bool:
    n = (name or "").strip()
    s = (surname or "").strip()
    return bool(n and s and n.casefold() == s.casefold())


def _seasons_to_scan(season: int | None, all_seasons: bool) -> list[int]:
    from utils.cumulative_db import list_season_archives_with_db

    if season is not None:
        return [int(season)]
    if all_seasons:
        return list_season_archives_with_db()
    return list_season_archives_with_db()


def _db_paths_for_season(season: int, db_kind: str) -> list[tuple[str, str]]:
    base = os.path.join(ROOT, "db", f"season_{season}")
    mapping = {
        "league": ("league", "league.db"),
        "cl": ("cl", "champions_league.db"),
        "common": ("common", "common.db"),
    }
    kinds = list(mapping) if db_kind == "all" else [db_kind]
    out: list[tuple[str, str]] = []
    for k in kinds:
        label, fname = mapping[k]
        p = os.path.join(base, fname)
        if os.path.isfile(p):
            out.append((f"s{season}:{label}", p))
    return out


def _load_placeholder_rows(db_label: str, db_path: str) -> list[dict]:
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker

    from utils.utils import Base

    engine = create_engine(f"sqlite:///{db_path}")
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine)
    session = Session()
    rows: list[dict] = []
    try:
        for Cls in _ALL:
            tbl = Cls.__tablename__
            for r in session.query(Cls).all():
                name = (getattr(r, "name", None) or "").strip()
                surname = (getattr(r, "surname", None) or "").strip()
                if not _name_eq_surname(name, surname):
                    continue
                row: dict = {
                    "db": db_label,
                    "path": db_path,
                    "table": tbl,
                    "id": int(r.id),
                    "name": name,
                    "surname": surname,
                    "team": (getattr(r, "team", None) or "").strip(),
                    "position": (getattr(r, "position", None) or "").strip().upper(),
                    "overall": int(getattr(r, "overall", 0) or 0),
                    "nation": (getattr(r, "nation", None) or "").strip() or "—",
                    "matches": int(getattr(r, "matches", 0) or 0),
                }
                if hasattr(r, "goals"):
                    row["goals"] = int(getattr(r, "goals", 0) or 0)
                    row["assists"] = int(getattr(r, "assists", 0) or 0)
                rows.append(row)
    finally:
        session.close()
        engine.dispose()
    return rows


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument(
        "--season",
        type=int,
        default=None,
        help="Один сезон (db/season_N). Без флага — все архивы с league.db",
    )
    ap.add_argument(
        "--all-seasons",
        action="store_true",
        help="Явно все сезоны (то же, что без --season)",
    )
    ap.add_argument(
        "--db",
        choices=_DB_CHOICES,
        default="all",
        help="Какие БД сезона сканировать (по умолчанию league+cl+common)",
    )
    ap.add_argument("--json", action="store_true", help="JSON в stdout")
    ap.add_argument("-o", "--output", default="", help="Записать вывод в файл (текст или JSON)")
    args = ap.parse_args()

    seasons = _seasons_to_scan(args.season, args.all_seasons)
    if not seasons:
        print("Нет папок db/season_N с league.db", file=sys.stderr)
        return 1

    all_rows: list[dict] = []
    for sn in seasons:
        for label, path in _db_paths_for_season(sn, args.db):
            for row in _load_placeholder_rows(label, path):
                row["season"] = sn
                all_rows.append(row)

    if args.json:
        text = json.dumps(all_rows, ensure_ascii=False, indent=2)
    else:
        parts = [f"Имя == фамилия · сезоны: {', '.join(map(str, seasons))} · db={args.db}"]
        if all_rows:
            w_team = max(len(r["team"]) for r in all_rows)
            w_name = max(len(r["name"]) for r in all_rows)
            w_db = max(len(r["db"]) for r in all_rows)
            has_ga = "goals" in all_rows[0]
            parts.append(
                f"{'Сезон':>5}  {'БД':<{w_db}}  {'Клуб':<{w_team}}  {'Имя':<{w_name}}  "
                f"{'Поз':<4}  {'OVR':>3}  {'М':>3}"
                + ("  Г    П " if has_ga else "")
                + "  id"
            )
            parts.append("-" * 72)
            for r in sorted(
                all_rows,
                key=lambda x: (x["season"], x["team"].lower(), x["name"].lower(), x["position"]),
            ):
                line = (
                    f"{r['season']:>5}  {r['db']:<{w_db}}  {r['team']:<{w_team}}  "
                    f"{r['name']:<{w_name}}  {r['position']:<4}  {r['overall']:>3}  {r['matches']:>3}"
                )
                if has_ga:
                    line += f"  {r.get('goals', 0):>3}  {r.get('assists', 0):>3}"
                line += f"  {r['id']}"
                parts.append(line)
        parts.append(f"\nИтого: {len(all_rows)}")
        text = "\n".join(parts)

    if args.output:
        with open(args.output, "w", encoding="utf-8") as f:
            f.write(text)
            if not text.endswith("\n"):
                f.write("\n")
        print(f"Записано {len(all_rows)} строк → {args.output}")
    else:
        print(text)

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
