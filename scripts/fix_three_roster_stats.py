#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Разовая правка статы: Дауд, Фуллкруг (нули), Садик (лига 1+0, ЛЧ 3+1)."""
from __future__ import annotations

import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)


def _set_outfield(row, *, matches: int, goals: int, assists: int) -> None:
    row.matches = int(matches)
    row.goals = int(goals)
    row.assists = int(assists)
    row.ga = int(goals) + int(assists)
    for k in (
        "trophies",
        "golden_balls",
        "golden_boots",
        "golden_boys",
        "golden_gloves",
        "yellow_cards",
        "red_cards",
    ):
        if hasattr(row, k):
            setattr(row, k, 0)


def main() -> None:
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker

    from data.forward import Forward
    from data.midfielder import Midfielder
    from utils.migrate_player_surname import prepare_season_archive_schema
    from utils.utils import Base

    prepare_season_archive_schema(2)
    league_path = os.path.join(ROOT, "db", "season_2", "league.db")
    cl_path = os.path.join(ROOT, "db", "season_2", "champions_league.db")

    for path in (league_path, cl_path):
        eng = create_engine(f"sqlite:///{path}")
        Base.metadata.create_all(eng)
        S = sessionmaker(bind=eng)
        s = S()
        try:
            tag = "league" if "league" in path else "cl"
            # Дауд — только лига
            if tag == "league":
                for r in s.query(Midfielder).filter_by(id=1086, name="Дауд").all():
                    _set_outfield(r, matches=0, goals=0, assists=0)
                    print(f"league Дауд id={r.id}: → нули")

            # Фуллкруг
            for r in s.query(Forward).filter_by(name="Фуллкруг", team="Спартак").all():
                _set_outfield(r, matches=0, goals=0, assists=0)
                print(f"{tag} Фуллкруг id={r.id}: → нули")

            # Садик
            if tag == "league":
                for r in s.query(Forward).filter_by(id=913, name="Садик").all():
                    _set_outfield(r, matches=1, goals=1, assists=0)
                    print(f"league Садик id={r.id}: → 1 матч, 1+0")
            else:
                for r in s.query(Forward).filter_by(id=669).all():
                    _set_outfield(r, matches=1, goals=3, assists=1)
                    print(f"cl Садик id={r.id}: → 1 матч, 3+1")
            s.commit()
        finally:
            s.close()
            eng.dispose()

    from utils.common_db import rebuild_common_database

    rebuild_common_database()
    print("season_2/common.db пересобран.")


if __name__ == "__main__":
    main()
