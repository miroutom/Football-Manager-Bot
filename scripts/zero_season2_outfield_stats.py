#!/usr/bin/env python3
"""
Обнулить matches / goals / assists / ga у полевых игроков в season_2 (league + ЛЧ).

Вратари: только matches (голов/передач нет).

  python3 scripts/zero_season2_outfield_stats.py           # dry-run (счётчики)
  python3 scripts/zero_season2_outfield_stats.py --apply
"""
from __future__ import annotations

import argparse
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

def _zero_table(sess, cls, label: str) -> tuple[int, int]:
    rows = sess.query(cls).all()
    changed = 0
    for r in rows:
        before = (int(r.matches or 0), int(r.goals or 0), int(r.assists or 0), int(getattr(r, "ga", 0) or 0))
        if before != (0, 0, 0, 0):
            changed += 1
        if hasattr(r, "goals"):
            r.matches = 0
            r.goals = 0
            r.assists = 0
            r.ga = 0
        else:
            r.matches = 0
    return len(rows), changed


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args()

    from data.defender import Defender
    from data.forward import Forward
    from data.midfielder import Midfielder
    from player_stats import get_session
    from utils.common_db import rebuild_common_database

    tables = [
        ("league", Forward, "forwards"),
        ("league", Midfielder, "midfielders"),
        ("league", Defender, "defenders"),
        ("cl", Forward, "forwards"),
        ("cl", Midfielder, "midfielders"),
        ("cl", Defender, "defenders"),
    ]
    gk_tables = [("league", "goalkeepers"), ("cl", "goalkeepers")]

    total_changed = 0
    for tourn, cls, label in tables:
        sess = get_session(tourn)
        n, ch = _zero_table(sess, cls, label)
        print(f"  {tourn}.db {label}: {n} строк, изменить {ch}")
        total_changed += ch

    from player_stats import get_player_class

    for tourn, label in gk_tables:
        sess = get_session(tourn)
        Cls = get_player_class("ВРТ")
        n, ch = 0, 0
        for r in sess.query(Cls).all():
            n += 1
            if int(r.matches or 0) != 0:
                ch += 1
                if args.apply:
                    r.matches = 0
        print(f"  {tourn}.db {label}: {n} строк, matches→0 у {ch}")
        total_changed += ch

    if not args.apply:
        print(f"\n(dry-run) Будет обнулено полей у {total_changed} строк. Добавь --apply.")
        return 0

    for tourn in ("league", "cl"):
        get_session(tourn).commit()
    print("\n--- Пересборка common.db ---")
    rebuild_common_database()
    print("  common.db пересобран (*_synced.db не трогаем)")
    print("\nГотово.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
