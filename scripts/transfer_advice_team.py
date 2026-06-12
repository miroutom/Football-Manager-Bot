#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Рекомендации по трансферу для клуба (или всех клубов лиг).

  python3 scripts/transfer_advice_team.py Цска
  python3 scripts/transfer_advice_team.py --all
  python3 scripts/transfer_advice_team.py Цска --only СУ НУ
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))


def main() -> int:
    p = argparse.ArgumentParser(description="Рекомендации НО/СО/СУ/НУ по составу клуба.")
    p.add_argument("team", nargs="?", help="Название клуба (как в БД)")
    p.add_argument("--all", action="store_true", help="Все клубы из LEAGUE_TEAMS")
    p.add_argument(
        "--only",
        nargs="+",
        metavar="CODE",
        help="Только вердикты, напр. СУ НУ",
    )
    args = p.parse_args()

    from utils.transfer_advice import (
        VERDICT_NU,
        VERDICT_SO,
        VERDICT_SU,
        VERDICT_NO,
        all_league_teams,
        collect_transfer_advice,
    )

    valid = {VERDICT_NO, VERDICT_SO, VERDICT_SU, VERDICT_NU}
    filt: frozenset[str] | None = None
    if args.only:
        filt = frozenset(x.upper() for x in args.only)
        bad = filt - valid
        if bad:
            print("Неизвестные коды:", ", ".join(sorted(bad)), file=sys.stderr)
            return 1

    teams: list[str]
    if args.all:
        teams = all_league_teams()
    elif args.team:
        teams = [args.team.strip()]
    else:
        p.print_help()
        return 1

    exit_code = 0
    for t in teams:
        canon, rows, err = collect_transfer_advice(t)
        if err:
            print(f"--- {t}: {err}", file=sys.stderr)
            exit_code = 1
            continue
        print(f"=== {canon} ===")
        print("НО СО СУ НУ · Т− П↓ З+ С×")
        show = rows
        if filt:
            show = [r for r in rows if r.verdict in filt]
        for r in show:
            print(r.line_text())
        if not show:
            print("(нет строк по фильтру)")
        c = {VERDICT_NO: 0, VERDICT_SO: 0, VERDICT_SU: 0, VERDICT_NU: 0}
        for r in rows:
            c[r.verdict] = c.get(r.verdict, 0) + 1
        print(
            f"Итого: НО {c[VERDICT_NO]} СО {c[VERDICT_SO]} "
            f"СУ {c[VERDICT_SU]} НУ {c[VERDICT_NU]}\n"
        )
    return exit_code


if __name__ == "__main__":
    raise SystemExit(main())
