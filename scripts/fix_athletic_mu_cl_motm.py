#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Атлетик — Мю (ЛЧ): POTM ошибочно записан на Марсиаля → перенести на Мартинелли.

  python3 scripts/fix_athletic_mu_cl_motm.py
  python3 scripts/fix_athletic_mu_cl_motm.py --dry-run
"""
from __future__ import annotations

import argparse
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

HOME, AWAY = "Атлетик", "Мю"
WRONG_NAME, WRONG_TEAM = "Марсиаль", "Мю"
CORRECT_NAME, CORRECT_TEAM = "Мартинелли", "Мю"
POSITION = "ФРВ"
TOURNAMENT = "cl"


def _read_potm() -> tuple[int, int]:
    from data.forward import Forward
    from player_stats import get_session

    s = get_session(TOURNAMENT)
    w = s.query(Forward).filter_by(name=WRONG_NAME, team=WRONG_TEAM).first()
    c = s.query(Forward).filter_by(name=CORRECT_NAME, team=CORRECT_TEAM).first()
    return (
        int(getattr(w, "potm", 0) or 0) if w else -1,
        int(getattr(c, "potm", 0) or 0) if c else -1,
    )


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true", help="только показать текущие potm")
    args = ap.parse_args()

    wm, cm = _read_potm()
    print(f"Матч: {HOME} — {AWAY} (ЛЧ)")
    print(f"До:  {WRONG_NAME} potm={wm}, {CORRECT_NAME} potm={cm}")

    if args.dry_run:
        return 0

    from player_stats import correct_match_potm

    ok, msg = correct_match_potm(
        WRONG_NAME,
        WRONG_TEAM,
        CORRECT_NAME,
        CORRECT_TEAM,
        wrong_position=POSITION,
        correct_position=POSITION,
        tournament=TOURNAMENT,
        sync_derived=True,
    )
    if not ok:
        print(f"Ошибка: {msg}")
        return 1

    wm2, cm2 = _read_potm()
    print(f"После: {WRONG_NAME} potm={wm2}, {CORRECT_NAME} potm={cm2}")
    print(msg)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
