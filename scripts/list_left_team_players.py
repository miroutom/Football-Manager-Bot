#!/usr/bin/env python3
"""
Игроки с ``left_team=True`` в БД сезона + где они сейчас в заявке (активная строка).

  python3 scripts/list_left_team_players.py
  python3 scripts/list_left_team_players.py --season 2
  python3 scripts/list_left_team_players.py --season 2 --db both --json
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


def _season_db_paths(season: int) -> list[tuple[str, str]]:
    base = os.path.join(ROOT, "db", f"season_{season}")
    out: list[tuple[str, str]] = []
    for label, name in (("league", "league.db"), ("cl", "champions_league.db")):
        p = os.path.join(base, name)
        if os.path.isfile(p):
            out.append((label, p))
    return out


def _load_all_rows(db_label: str, db_path: str) -> list[dict]:
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
                if not name:
                    continue
                rows.append(
                    {
                        "db": db_label,
                        "table": tbl,
                        "id": int(r.id),
                        "name": name,
                        "position": (getattr(r, "position", None) or "").strip().upper(),
                        "team": (getattr(r, "team", None) or "").strip(),
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
    return rows


def _active_clubs_by_name(all_rows: list[dict]) -> dict[str, list[str]]:
    """Активные строки (left_team=False): имя → список «клуб · поз»."""
    out: dict[str, list[str]] = defaultdict(list)
    for r in all_rows:
        if r["left_team"]:
            continue
        team = r["team"]
        if not team:
            continue
        key = _norm_cmp(r["name"])
        tag = f"{team} · {r['position']}"
        if tag not in out[key]:
            out[key].append(tag)
    return out


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--season", type=int, default=2, help="Номер сезона (папка db/season_N)")
    ap.add_argument(
        "--db",
        choices=("league", "cl", "both"),
        default="league",
        help="Какую БД сканировать (по умолчанию league.db)",
    )
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args()

    paths = _season_db_paths(args.season)
    if args.db == "league":
        paths = [p for p in paths if p[0] == "league"]
    elif args.db == "cl":
        paths = [p for p in paths if p[0] == "cl"]
    if not paths:
        print(f"Нет БД для season_{args.season} (db/season_{args.season}/)")
        sys.exit(1)

    all_rows: list[dict] = []
    for label, path in paths:
        all_rows.extend(_load_all_rows(label, path))

    active = _active_clubs_by_name(all_rows)
    left_rows = [r for r in all_rows if r["left_team"]]
    left_rows.sort(key=lambda x: (x["team"].lower(), x["name"].lower(), x["position"]))

    if args.json:
        payload = []
        for r in left_rows:
            cur = active.get(_norm_cmp(r["name"]), [])
            payload.append({**r, "current_clubs": cur})
        print(json.dumps(payload, ensure_ascii=False, indent=2))
        return

    scanned = ", ".join(p for _, p in paths)
    print(f"Сезон {args.season} · {scanned}")
    print(f"Строк с left_team=True: {len(left_rows)}\n")
    if not left_rows:
        print("(нет)")
        return

    w_team = max(len(r["team"]) for r in left_rows)
    w_name = max(len(r["name"]) for r in left_rows)
    w_pos = 6
    print(
        f"{'Клуб (стата)':<{w_team}}  {'Игрок':<{w_name}}  {'Поз':<{w_pos}}  "
        f"{'OVR':>3}  {'М':>3}  {'Г':>3}  {'П':>3}  Сейчас в заявке"
    )
    print("-" * (w_team + w_name + w_pos + 50))

    for r in left_rows:
        cur = active.get(_norm_cmp(r["name"]), [])
        cur_s = "— (нет активной строки)" if not cur else "; ".join(cur)
        print(
            f"{r['team']:<{w_team}}  {r['name']:<{w_name}}  {r['position']:<{w_pos}}  "
            f"{r['overall']:>3}  {r['matches']:>3}  {r['goals']:>3}  {r['assists']:>3}  "
            f"{cur_s}"
        )
        if len(paths) > 1 or args.db == "both":
            print(f"  └ [{r['db']}] id={r['id']} ({r['table']})")


if __name__ == "__main__":
    main()
