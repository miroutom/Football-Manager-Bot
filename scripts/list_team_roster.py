#!/usr/bin/env python3
"""
Состав клуба(ов) из ``db/season_N/league.db`` — только текущая заявка (без ``left_team``).

  python3 scripts/list_team_roster.py --season 2
  python3 scripts/list_team_roster.py --season 2 --team Арсенал
  python3 scripts/list_team_roster.py --season 2 --team Арсенал --with-ids
"""
from __future__ import annotations

import argparse
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from data.defender import Defender
from data.forward import Forward
from data.goalkeeper import Goalkeeper
from data.midfielder import Midfielder
from utils.migrate_player_surname import prepare_season_archive_schema
from utils.player_names import player_first_name, player_surname
from utils.player_transfer import _filter_team

_ALL = (
    (Forward, "forwards"),
    (Midfielder, "midfielders"),
    (Defender, "defenders"),
    (Goalkeeper, "goalkeepers"),
)

_POS_ORDER = {"ФРВ": 0, "ЛФА": 1, "ПФА": 2, "ЦАП": 3, "ЦП": 4, "ЦЗ": 5, "ЛЗ": 6, "ПЗ": 7, "ВРТ": 8}


def _line_label(row) -> str:
    fn = player_first_name(row)
    sn = player_surname(row)
    if fn and _norm(fn) != _norm(sn):
        who = f"{fn} {sn}"
    else:
        who = sn or fn
    pos = (getattr(row, "position", None) or "").strip()
    ovr = int(getattr(row, "overall", 0) or 0)
    nat = (getattr(row, "nation", None) or "").strip().title()
    return f"{who} {pos} {ovr} {nat}".strip()


def _norm(s: str) -> str:
    return (s or "").strip().casefold()


def _collect(session, *, team_filter: str, include_left: bool, include_free: bool):
    by_team: dict[str, list[tuple]] = {}
    for Cls, tbl in _ALL:
        q = session.query(Cls)
        if team_filter:
            q = q.filter(_filter_team(Cls, team_filter, include_left=include_left))
        elif not include_left:
            if hasattr(Cls, "left_team"):
                q = q.filter((Cls.left_team.is_(False)) | (Cls.left_team.is_(None)))
        for r in q.all():
            team = (getattr(r, "team", None) or "").strip()
            if not team:
                continue
            if not include_free and team.casefold() == "free agent":
                continue
            if team_filter and _norm(team) != _norm(team_filter):
                continue
            if not include_left and bool(getattr(r, "left_team", False)):
                continue
            pos = (getattr(r, "position", None) or "").strip()
            ovr = int(getattr(r, "overall", 0) or 0)
            by_team.setdefault(team, []).append((pos, -ovr, who_sort_key(r), r, tbl))

    for team in by_team:
        rows = by_team[team]
        rows.sort(
            key=lambda x: (
                _POS_ORDER.get(x[0], 50),
                x[1],
                x[2],
            )
        )
        by_team[team] = rows
    return by_team


def who_sort_key(row) -> str:
    return _line_label(row).casefold()


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--season", type=int, default=2)
    ap.add_argument("--team", default="", help="Одна команда (как в БД)")
    ap.add_argument(
        "--with-ids",
        action="store_true",
        help="Добавить table:id для import_player_names.py",
    )
    ap.add_argument(
        "--include-left",
        action="store_true",
        help="Показать ушедших (left_team)",
    )
    ap.add_argument(
        "--include-free",
        action="store_true",
        help="Показать Free Agent",
    )
    args = ap.parse_args()

    path = os.path.join(ROOT, "db", f"season_{args.season}", "league.db")
    if not os.path.isfile(path):
        print(f"Нет {path}")
        sys.exit(1)

    prepare_season_archive_schema(args.season)

    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker

    from utils.utils import Base

    engine = create_engine(f"sqlite:///{path}")
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine)
    session = Session()
    try:
        by_team = _collect(
            session,
            team_filter=args.team.strip(),
            include_left=args.include_left,
            include_free=args.include_free,
        )
    finally:
        session.close()
        engine.dispose()

    if not by_team:
        print("Никого не найдено. Проверь --team и фильтры.")
        sys.exit(0)

    total = 0
    for team in sorted(by_team.keys()):
        print(team)
        for _pos, _novr, _sort, r, tbl in by_team[team]:
            label = _line_label(r)
            if args.with_ids:
                rid = int(getattr(r, "id", 0) or 0)
                print(f"  {label}  [{tbl}:{rid}]")
            else:
                print(f"  {label}")
            total += 1
        print()

    print(f"Всего: {total} игроков, {len(by_team)} команд.")


if __name__ == "__main__":
    main()
