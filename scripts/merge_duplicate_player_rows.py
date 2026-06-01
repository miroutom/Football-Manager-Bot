#!/usr/bin/env python3
"""
Слить дубли одного игрока в клубе (разные позиции в БД, одно имя).

Пример: Уиллок ЦП + Уиллок ЦОП в Ньюкасле → одна строка ЦОП.

  python3 scripts/merge_duplicate_player_rows.py --dry-run \\
      --name Уиллок --team Ньюкасл --keep-position ЦОП
  python3 scripts/merge_duplicate_player_rows.py --apply --no-sum \\
      --name Ольмо --team Лейпциг --keep-position ЦАП
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
from player_stats import _norm_cmp
from utils import season_paths

_ALL = (Forward, Midfielder, Defender, Goalkeeper)


def _rows(session, name: str, team: str) -> list[tuple[type, object]]:
    want_n = _norm_cmp(name)
    want_t = _norm_cmp(team)
    out: list[tuple[type, object]] = []
    for Cls in _ALL:
        for r in session.query(Cls).all():
            if _norm_cmp(r.name) == want_n and _norm_cmp(r.team) == want_t:
                out.append((Cls, r))
    return out


def _row_stats_line(r: object) -> str:
    return (
        f"m={int(getattr(r, 'matches', 0) or 0)} "
        f"g={int(getattr(r, 'goals', 0) or 0)} "
        f"a={int(getattr(r, 'assists', 0) or 0)}"
    )


def _merge_into(keeper, donor) -> None:
    for fld in (
        "matches",
        "goals",
        "assists",
        "ga",
        "clean_sheets",
        "missed_goals",
        "trophies",
        "golden_balls",
        "golden_boots",
        "golden_gloves",
        "golden_boys",
        "yellow_cards",
        "red_cards",
    ):
        if not hasattr(keeper, fld) or not hasattr(donor, fld):
            continue
        kv = int(getattr(keeper, fld, 0) or 0)
        dv = int(getattr(donor, fld, 0) or 0)
        setattr(keeper, fld, kv + dv)
    ko = int(getattr(keeper, "overall", 0) or 0)
    do = int(getattr(donor, "overall", 0) or 0)
    if do > ko:
        keeper.overall = do
    if not (getattr(keeper, "status", None) or "").strip():
        keeper.status = getattr(donor, "status", None)


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--name", required=True)
    ap.add_argument("--team", required=True)
    ap.add_argument("--keep-position", required=True, help="Позиция строки, которую оставить")
    ap.add_argument(
        "--also-name",
        default="",
        help="Второе имя того же игрока (напр. Силва при --name Рафа)",
    )
    ap.add_argument(
        "--no-sum",
        action="store_true",
        help="Не суммировать статы donor → keeper (удалить дубль как ошибочную строку)",
    )
    ap.add_argument("--dry-run", action="store_true", default=True)
    ap.add_argument("--apply", action="store_true")
    args = ap.parse_args()
    if not args.apply:
        args.dry_run = True

    from utils.migrate_player_left_team import migrate_all_player_left_team_columns

    migrate_all_player_left_team_columns()

    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker

    from utils.utils import Base

    paths = [
        season_paths.get_league_db_path(),
        season_paths.get_cl_db_path(),
        season_paths.get_common_db_path(),
    ]
    keep_pos = (args.keep_position or "").strip().upper()
    also_name = (args.also_name or "").strip().title()

    for path in paths:
        if not os.path.isfile(path):
            continue
        e = create_engine(f"sqlite:///{path}")
        Base.metadata.create_all(e)
        S = sessionmaker(bind=e)()
        try:
            rows = _rows(S, args.name, args.team)
            if len(rows) < 2:
                print(f"{path}: дублей нет ({len(rows)} строк)")
                continue
            print(f"\n{os.path.basename(path)}:")
            keeper = None
            donors: list[tuple[type, object]] = []
            for Cls, r in rows:
                tag = "KEEP" if (r.position or "").strip().upper() == keep_pos else "DROP"
                print(
                    f"  [{tag}] {Cls.__tablename__} id={r.id} {r.name} {r.position} "
                    f"{_row_stats_line(r)}"
                )
            for Cls, r in rows:
                if (r.position or "").strip().upper() == keep_pos:
                    if keeper is None:
                        keeper = (Cls, r)
                    else:
                        donors.append((Cls, r))
                else:
                    donors.append((Cls, r))
            if keeper is None:
                print(f"  Нет строки с позицией {keep_pos}")
                continue
            if also_name:
                from utils.squad_roster_sync import find_player_row as fbn

                extra, _ = fbn(S, args.name.strip().title(), also_name)
                if extra is not None and int(extra.id) != int(keeper[1].id):
                    donors.append((type(extra), extra))
                    print(
                        f"  [DROP] {type(extra).__tablename__} id={extra.id} "
                        f"{extra.name} {extra.position} {_row_stats_line(extra)} (also-name)"
                    )
            if not donors:
                print("  Нечего сливать")
                continue
            mode = "без суммы статов" if args.no_sum else "с суммой статов"
            if args.dry_run:
                print(
                    f"  (dry-run) Оставить id={keeper[1].id} {keeper[1].position} "
                    f"({_row_stats_line(keeper[1])}), удалить {len(donors)} строк, {mode}"
                )
                continue
            for _Cls, d in donors:
                if not args.no_sum:
                    _merge_into(keeper[1], d)
                S.delete(d)
            S.commit()
            print(
                f"  ✓ Оставлен id={keeper[1].id} {keeper[1].position}, "
                f"удалено {len(donors)} ({mode})"
            )
        finally:
            S.close()
            e.dispose()

    if args.apply and also_name:
        from utils.player_identity import register_name_change

        register_name_change(args.team, also_name, args.name.strip().title())

    if args.apply:
        from utils.cumulative_db import rebuild_active_season_common_db

        rebuild_active_season_common_db()
        print("common.db пересобран.")


if __name__ == "__main__":
    main()
