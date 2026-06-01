#!/usr/bin/env python3
"""
Игроки с одинаковым именем в БД сезона (омонимы: разные люди, одна фамилия/кличка).

Для каждого имени с 2+ строками — компактный список, чтобы развести по полным именам.

  python3 scripts/list_homonym_players.py
  python3 scripts/list_homonym_players.py --season 2
  python3 scripts/list_homonym_players.py --min-rows 3
  python3 scripts/list_homonym_players.py --json > homonyms.json
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from collections import defaultdict

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from data.defender import Defender
from data.forward import Forward
from data.goalkeeper import Goalkeeper
from data.midfielder import Midfielder
from player_stats import _norm_cmp

_ALL = (Forward, Midfielder, Defender, Goalkeeper)


def _season_league_path(season: int) -> str:
    return os.path.join(ROOT, "db", f"season_{season}", "league.db")


def _load_rows(db_path: str) -> list[dict]:
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker

    from utils.utils import Base

    engine = create_engine(f"sqlite:///{db_path}")
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine)
    session = Session()
    out: list[dict] = []
    try:
        for Cls in _ALL:
            tbl = Cls.__tablename__
            for r in session.query(Cls).all():
                name = (getattr(r, "name", None) or "").strip()
                if not name:
                    continue
                out.append(
                    {
                        "table": tbl,
                        "id": int(r.id),
                        "name": name,
                        "team": (getattr(r, "team", None) or "").strip(),
                        "position": (getattr(r, "position", None) or "").strip().upper(),
                        "overall": int(getattr(r, "overall", 0) or 0),
                        "nation": (getattr(r, "nation", None) or "").strip() or "—",
                        "matches": int(getattr(r, "matches", 0) or 0),
                        "goals": int(getattr(r, "goals", 0) or 0),
                        "assists": int(getattr(r, "assists", 0) or 0),
                        "left_team": bool(getattr(r, "left_team", False)),
                    }
                )
    finally:
        session.close()
        engine.dispose()
    return out


def _group_by_name(rows: list[dict]) -> dict[str, list[dict]]:
    by: dict[str, list[dict]] = defaultdict(list)
    for r in rows:
        by[_norm_cmp(r["name"])].append(r)
    return {k: v for k, v in by.items() if len(v) >= 2}


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--season", type=int, default=2)
    ap.add_argument(
        "--min-rows",
        type=int,
        default=2,
        help="Минимум строк с одним именем (по умолчанию 2)",
    )
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args()

    path = _season_league_path(args.season)
    if not os.path.isfile(path):
        print(f"Нет файла: {path}")
        sys.exit(1)

    rows = _load_rows(path)
    by_name = _group_by_name(rows)
    groups = [
        (rows[0]["name"], sorted(rows, key=lambda x: (x["team"].lower(), x["position"])))
        for _, rows in sorted(by_name.items(), key=lambda x: (-len(x[1]), x[1][0]["name"].lower()))
        if len(rows) >= args.min_rows
    ]

    if args.json:
        print(
            json.dumps(
                [
                    {
                        "display_name": disp,
                        "row_count": len(grp),
                        "rows": grp,
                    }
                    for disp, grp in groups
                ],
                ensure_ascii=False,
                indent=2,
            )
        )
        return

    print(f"Сезон {args.season} · {path}")
    print(f"Имён с {args.min_rows}+ строками: {len(groups)} (всего строк: {sum(len(g) for _, g in groups)})\n")

    for disp, grp in groups:
        print(f"{'=' * 72}")
        print(f"{disp}  —  {len(grp)} строк(и)")
        print(f"{'=' * 72}")
        for r in grp:
            st = "ушёл" if r["left_team"] else "в заявке"
            print(
                f"  id={r['id']:<5} {r['table']:<12} {r['team']:<16} {r['position']:<5} "
                f"ovr={r['overall']:<2} {st:<10} "
                f"м={r['matches']} г={r['goals']} п={r['assists']}  [{r['nation']}]"
            )
        print()


if __name__ == "__main__":
    main()
