#!/usr/bin/env python3
"""
Восстановить строку игрока в прошлом клубе (если трансфер старым кодом «увёз» стата).

Пример Батши: остался только в Вольфсбурге — вернуть строку в Краснодар для батча/отчётов.

  python3 scripts/restore_former_club_stats_row.py \\
      --player Батши --position ПФА --team Краснодар \\
      --league 4 0 1 --cl 3 0 0 --overall 72 --nation Россия

  python3 scripts/restore_former_club_stats_row.py ... --apply
"""
from __future__ import annotations

import argparse
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--player", required=True)
    parser.add_argument("--position", required=True)
    parser.add_argument("--team", required=True)
    parser.add_argument("--league", nargs=3, type=int, metavar=("M", "G", "A"))
    parser.add_argument("--cl", nargs=3, type=int, metavar=("M", "G", "A"))
    parser.add_argument("--overall", type=int, default=72)
    parser.add_argument("--nation", default="")
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args()

    from player_stats import get_player_class
    from utils.player_transfer import (
        _filter_team,
        _new_player_kwargs,
        _norm_cmp,
        normalize_player_name_for_db,
    )
    from utils.utils import session_cl, session_league

    name = normalize_player_name_for_db(args.player)
    team = args.team.strip()
    pos = args.position.strip().upper()
    lm, lg, la = args.league or (0, 0, 0)
    cm, cg, ca = args.cl or (0, 0, 0)
    Cls = get_player_class(pos)

    def _has(sess):
        for r in sess.query(Cls).filter(_filter_team(Cls, team)).all():
            if _norm_cmp(r.name) == _norm_cmp(name) and _norm_cmp(r.position) == _norm_cmp(pos):
                return True
        return False

    def _insert(sess):
        kw = _new_player_kwargs(
            Cls,
            name=name,
            team=team,
            position=pos,
            overall=args.overall,
            nation=(args.nation or "").strip() or None,
        )
        row = Cls(**kw)
        row.matches = lm
        if hasattr(row, "goals"):
            row.goals = lg
            row.assists = la
            row.ga = lg + la
        sess.add(row)
        return row

    if _has(session_league):
        print(f"Уже есть: {name} ({pos}) в {team} (league.db)")
        return 0

    print(f"План: {name} ({pos}) → {team}")
    print(f"  league: {lm} м, {lg}+{la} ГП")
    if args.cl:
        print(f"  ЛЧ (если клуб в пуле): {cm} м, {cg}+{ca} ГП")

    if not args.apply:
        print("(dry-run) Добавь --apply для записи.")
        return 0

    _insert(session_league)
    session_league.commit()
    from utils.common_db import _team_in_cl_pool

    if _team_in_cl_pool(team) and not _has(session_cl):
        row = _insert(session_cl)
        row.matches = cm
        if hasattr(row, "goals"):
            row.goals = cg
            row.assists = ca
            row.ga = cg + ca
        session_cl.commit()
    elif _team_in_cl_pool(team):
        session_cl.commit()

    from utils.common_db import rebuild_common_database

    rebuild_common_database()
    print("✓ Записано, common пересобран.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
