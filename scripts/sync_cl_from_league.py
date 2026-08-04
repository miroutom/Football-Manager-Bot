#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Синхронизировать overall и nation в champions_league.db из league.db (по person_id).

Нужно после apply_ratings, если ЛЧ-строки клубов вне топ-30 не обновились.

  python3 scripts/sync_cl_from_league.py
  python3 scripts/sync_cl_from_league.py --dry-run
"""
from __future__ import annotations

import argparse
import os
import sys

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

from data.defender import Defender
from data.forward import Forward
from data.goalkeeper import Goalkeeper
from data.midfielder import Midfielder

_ALL = (Forward, Midfielder, Defender, Goalkeeper)


def main() -> int:
    parser = argparse.ArgumentParser(description="Sync CL overall/nation from league by person_id")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    from utils.utils import session_cl, session_league

    league_by_pid: dict[int, object] = {}
    for Cls in _ALL:
        for r in session_league.query(Cls).all():
            if bool(getattr(r, "left_team", False)):
                continue
            pid = getattr(r, "person_id", None)
            if pid is not None:
                league_by_pid[int(pid)] = r

    changed = 0
    notes: list[str] = []
    for Cls in _ALL:
        for row_c in session_cl.query(Cls).all():
            if bool(getattr(row_c, "left_team", False)):
                continue
            pid = getattr(row_c, "person_id", None)
            if pid is None or int(pid) not in league_by_pid:
                continue
            row_l = league_by_pid[int(pid)]
            lo = int(getattr(row_l, "overall", 0) or 0)
            co = int(getattr(row_c, "overall", 0) or 0)
            ln = (getattr(row_l, "nation", None) or "").strip() or None
            cn = (getattr(row_c, "nation", None) or "").strip() or None
            if lo == co and (ln == cn or not ln):
                continue
            name = (getattr(row_c, "name", None) or "").strip()
            team = (getattr(row_c, "team", None) or "").strip()
            bits: list[str] = []
            if lo != co:
                bits.append(f"ovr {co}→{lo}")
                if not args.dry_run:
                    row_c.overall = lo
            if ln and ln != cn:
                bits.append(f"nation {cn!r}→{ln!r}")
                if not args.dry_run:
                    row_c.nation = ln
            if bits:
                notes.append(f"  {team} · {name}: " + ", ".join(bits))
                changed += 1

    if not args.dry_run and changed:
        session_cl.commit()
        from utils.common_db import rebuild_common_database

        rebuild_common_database()
        print("common.db пересобран")

    for line in notes[:40]:
        print(line)
    if len(notes) > 40:
        print(f"  … ещё {len(notes) - 40}")

    print(f"\n{'Would update' if args.dry_run else 'Updated'}: {changed} CL rows")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
