#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Восстановить yellow_cards / red_cards в архиве season_1 из снимка БД (конец 1-го сезона).

При первом переходе сезона карточки в SQLite обнулялись — в ``db/season_1/`` остались нули,
хотя в ``player_discipline.json`` сбрасывается только цикл жк (0–3), а не история в БД.

По умолчанию источник: ``db/backup_view_b4bd9f2_20260526/`` (если есть).

  python3 scripts/restore_season1_cards_from_backup.py
  python3 scripts/restore_season1_cards_from_backup.py --apply
  python3 scripts/restore_season1_cards_from_backup.py --apply --src /path/to/backup_dir
"""
from __future__ import annotations

import argparse
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from data.defender import Defender
from data.forward import Forward
from data.goalkeeper import Goalkeeper
from data.midfielder import Midfielder
from utils import season_paths

_ALL = (Forward, Midfielder, Defender, Goalkeeper)
DEFAULT_SRC = os.path.join(ROOT, "db", "backup_view_b4bd9f2_20260526")


def _key(name: str, team: str, position: str) -> tuple[str, str, str]:
    return (
        (name or "").strip().casefold(),
        (team or "").strip().casefold(),
        (position or "").strip().upper(),
    )


def _load_cards(path: str) -> dict[tuple[str, str, str], tuple[int, int]]:
    eng = create_engine(f"sqlite:///{path}")
    Sess = sessionmaker(bind=eng)
    s = Sess()
    out: dict[tuple[str, str, str], tuple[int, int]] = {}
    try:
        for Cls in _ALL:
            for r in s.query(Cls).all():
                y = int(getattr(r, "yellow_cards", 0) or 0)
                rd = int(getattr(r, "red_cards", 0) or 0)
                if y or rd:
                    out[_key(r.name, r.team, r.position)] = (y, rd)
    finally:
        s.close()
        eng.dispose()
    return out


def _apply_cards(dst_path: str, cards: dict[tuple[str, str, str], tuple[int, int]]) -> tuple[int, int]:
    eng = create_engine(f"sqlite:///{dst_path}")
    Sess = sessionmaker(bind=eng)
    s = Sess()
    updated = 0
    try:
        for Cls in _ALL:
            for r in s.query(Cls).all():
                k = _key(r.name, r.team, r.position)
                if k not in cards:
                    continue
                y, rd = cards[k]
                if int(r.yellow_cards or 0) != y or int(r.red_cards or 0) != rd:
                    r.yellow_cards = y
                    r.red_cards = rd
                    updated += 1
        s.commit()
    finally:
        s.close()
        eng.dispose()
    return updated, len(cards)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true")
    ap.add_argument("--src", default=DEFAULT_SRC, help="Папка с league.db и champions_league.db")
    args = ap.parse_args()

    src = os.path.abspath(args.src)
    s1 = os.path.join(ROOT, "db", "season_1")
    src_l = os.path.join(src, season_paths.SEASON_LEAGUE_NAME)
    src_c = os.path.join(src, season_paths.SEASON_CL_NAME)
    dst_l = os.path.join(s1, season_paths.SEASON_LEAGUE_NAME)
    dst_c = os.path.join(s1, season_paths.SEASON_CL_NAME)

    for p in (src_l, src_c, dst_l, dst_c):
        if not os.path.isfile(p):
            print(f"Нет файла: {p}")
            return 1

    cards_l = _load_cards(src_l)
    cards_c = _load_cards(src_c)
    print(f"Источник: {src}")
    print(f"  league: {len(cards_l)} игроков с жк/кк, сумма жк={sum(x[0] for x in cards_l.values())}")
    print(f"  ЛЧ:     {len(cards_c)} игроков с жк/кк, сумма жк={sum(x[0] for x in cards_c.values())}")

    if not args.apply:
        print("\n(dry-run) С --apply запишем в db/season_1/ и пересоберём synced.")
        return 0

    u_l, _ = _apply_cards(dst_l, cards_l)
    u_c, _ = _apply_cards(dst_c, cards_c)
    print(f"\nseason_1 обновлено строк: league={u_l}, ЛЧ={u_c}")

    from utils.common_db import rebuild_common_database_for_disk_paths

    rebuild_common_database_for_disk_paths(
        dst_l, dst_c, os.path.join(s1, season_paths.SEASON_COMMON_NAME)
    )
    from utils.cumulative_db import rebuild_all_time_databases_from_season_archives

    print(rebuild_all_time_databases_from_season_archives())

    from utils.utils import reinit_db_connections

    reinit_db_connections()
    from utils.common_db import rebuild_common_database

    rebuild_common_database()
    print("Активный season_2 common.db пересобран.")
    print("Готово.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
