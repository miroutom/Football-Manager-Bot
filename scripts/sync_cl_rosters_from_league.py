#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Полная синхронизация заявок ЛЧ из league.db → champions_league.db для клубов пула ЛЧ.

Нужно после apply трансферного окна, если трансферы уже записали league, а CL остался
со старым составом (apply пропускал upsert при совпадении строки в лиге).

  python3 scripts/sync_cl_rosters_from_league.py
  python3 scripts/sync_cl_rosters_from_league.py --team Реал
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))


def _league_entries(team: str) -> list[tuple[str, str, str, int | None, str | None, str | None]]:
    from utils.player_transfer import normalize_player_name_for_db
    from utils.roster_manual import _iter_team_players
    from utils.transfer_input import normalize_position
    from utils.utils import session_league

    out: list[tuple[str, str, str, int | None, str | None, str | None]] = []
    for _Cls, r in _iter_team_players(session_league, team):
        if bool(getattr(r, "left_team", False)):
            continue
        nm = normalize_player_name_for_db(r.name or "")
        pp = normalize_position(r.position or "")
        st = (getattr(r, "status", None) or "bench").strip().lower()
        if st not in ("start", "bench", "reserve"):
            st = "bench"
        slot = (
            str(getattr(r, "lineup_slot", None) or "").strip().upper() or None
            if st == "start"
            else None
        )
        ovr = int(getattr(r, "overall", 0) or 0) or None
        nat = (getattr(r, "nation", None) or "").strip() or None
        out.append((nm, pp, st, ovr, nat, slot))
    return out


def main() -> int:
    p = argparse.ArgumentParser(description="Sync CL squads from league.db")
    p.add_argument("--team", help="только один клуб (как в league.db)")
    p.add_argument("--dry-run", action="store_true")
    args = p.parse_args()

    from champions_league.cl_format import get_cl_participants
    from utils.common_db import resolve_team_name_for_cl_pool
    from utils.roster_manual import apply_team_squad_declaration
    from utils.transfer_input import resolve_team_name
    from utils.utils import session_league

    teams = [args.team.strip()] if args.team else list(get_cl_participants())
    done = 0
    for raw in teams:
        team = resolve_team_name(raw, session_league) or raw.strip()
        if not resolve_team_name_for_cl_pool(team):
            print(f"skip (не в пуле ЛЧ): {team}")
            continue
        entries = _league_entries(team)
        if not entries:
            print(f"skip (пустая заявка в лиге): {team}")
            continue
        print(f"{team}: {len(entries)} игроков → CL")
        if args.dry_run:
            done += 1
            continue
        apply_team_squad_declaration(
            team,
            entries,
            rebuild_common=False,
            mirror_synced=False,
        )
        done += 1

    if not args.dry_run and done:
        from utils.common_db import rebuild_common_database

        rebuild_common_database()
        print("common.db пересобран")

    print(f"{'Would sync' if args.dry_run else 'Synced'}: {done} club(s)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
