#!/usr/bin/env python3
"""
Выгрузить всех игроков сезона для заполнения имени и фамилии.

CSV с колонками: team, table, id, first_name, surname, position, overall, nation, left_team

  python3 scripts/export_player_name_roster.py --season 2
  python3 scripts/export_player_name_roster.py --season 2 -o data/season2_player_names.csv
"""
from __future__ import annotations

import argparse
import csv
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from data.defender import Defender
from data.forward import Forward
from data.goalkeeper import Goalkeeper
from data.midfielder import Midfielder
from utils.migrate_player_surname import migrate_all_player_surname_columns
from utils.player_names import player_first_name, player_surname

_ALL = (Forward, Midfielder, Defender, Goalkeeper)


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--season", type=int, default=2)
    ap.add_argument(
        "-o",
        "--output",
        default="",
        help="Путь к CSV (по умолчанию data/season_N_player_names.csv)",
    )
    args = ap.parse_args()

    migrate_all_player_surname_columns()

    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker

    from utils.utils import Base

    path = os.path.join(ROOT, "db", f"season_{args.season}", "league.db")
    if not os.path.isfile(path):
        print(f"Нет {path}")
        sys.exit(1)

    out_path = args.output or os.path.join(
        ROOT, "data", f"season_{args.season}_player_names.csv"
    )

    engine = create_engine(f"sqlite:///{path}")
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine)
    session = Session()
    rows_out: list[dict] = []
    try:
        for Cls in _ALL:
            tbl = Cls.__tablename__
            for r in session.query(Cls).order_by(Cls.team, Cls.id).all():
                team = (getattr(r, "team", None) or "").strip()
                if not team:
                    continue
                rows_out.append(
                    {
                        "team": team,
                        "table": tbl,
                        "id": int(r.id),
                        "first_name": player_first_name(r),
                        "surname": player_surname(r),
                        "position": (getattr(r, "position", None) or "").strip(),
                        "overall": int(getattr(r, "overall", 0) or 0),
                        "nation": (getattr(r, "nation", None) or "").strip(),
                        "left_team": int(bool(getattr(r, "left_team", False))),
                    }
                )
    finally:
        session.close()
        engine.dispose()

    fieldnames = [
        "team",
        "table",
        "id",
        "first_name",
        "surname",
        "position",
        "overall",
        "nation",
        "left_team",
    ]
    os.makedirs(os.path.dirname(out_path) or ".", exist_ok=True)
    with open(out_path, "w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=fieldnames)
        w.writeheader()
        w.writerows(rows_out)

    print(f"Записано {len(rows_out)} строк → {out_path}")
    print("Заполни first_name и surname; surname — то, что видно в боте.")


if __name__ == "__main__":
    main()
