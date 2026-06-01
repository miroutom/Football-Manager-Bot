#!/usr/bin/env python3
"""
Проставить ``left_team=True`` по журналу ``data/transfers.json``.

Для каждой записи (кроме из «свободный агент») помечает все строки игрока
в ``from_team`` — стата и ``team`` не меняются, из заявки скрываются.

  python3 scripts/apply_left_team_from_transfers.py --dry-run
  python3 scripts/apply_left_team_from_transfers.py --apply
"""
from __future__ import annotations

import argparse
import json
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
from utils.migrate_player_left_team import migrate_all_player_left_team_columns
from utils.player_transfer import _filter_team, mark_player_left_team
from utils.transfer_input import normalize_position, resolve_team_name

_ALL = (Forward, Midfielder, Defender, Goalkeeper)
_TRANSFERS_PATH = os.path.join(ROOT, "data", "transfers.json")
_FA_MARKERS = ("(свободный агент)", "свободный агент", "free agent")


def _is_free_agent_team(team: str) -> bool:
    t = (team or "").strip().lower()
    return any(m in t for m in _FA_MARKERS) or t in ("fa", "free agent")


def _load_transfers() -> list[dict]:
    with open(_TRANSFERS_PATH, encoding="utf-8") as f:
        data = json.load(f)
    return list(data.get("transfers") or [])


def _mark_left_in_session(sess, from_team: str, player: str, *, dry_run: bool) -> list[str]:
    resolved = resolve_team_name(from_team, sess) or from_team.strip()
    want_n = _norm_cmp(player)
    touched: list[str] = []
    for Cls in _ALL:
        for r in sess.query(Cls).filter(_filter_team(Cls, resolved, include_left=True)).all():
            if _norm_cmp(getattr(r, "name", "") or "") != want_n:
                continue
            if bool(getattr(r, "left_team", False)):
                continue
            pos = (getattr(r, "position", "") or "").strip().upper()
            line = (
                f"  {Cls.__tablename__} id={r.id} {r.name} {pos} @ {getattr(r, 'team', '')} "
                f"m={int(getattr(r, 'matches', 0) or 0)}"
            )
            touched.append(line)
            if not dry_run:
                mark_player_left_team(r)
    return touched


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--apply", action="store_true")
    args = ap.parse_args()
    if args.apply:
        args.dry_run = False
    else:
        args.dry_run = True

    migrate_all_player_left_team_columns()

    transfers = _load_transfers()
    skipped_fa = 0
    seen: set[tuple[str, str, str]] = set()
    total_lines = 0

    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker

    from utils.utils import Base

    paths = [
        ("league", season_paths.get_league_db_path()),
        ("cl", season_paths.get_cl_db_path()),
    ]

    print(f"Журнал: {_TRANSFERS_PATH} ({len(transfers)} записей)")
    print(f"Режим: {'dry-run' if args.dry_run else 'APPLY'}\n")

    for tr in transfers:
        player = (tr.get("player") or "").strip()
        from_team = (tr.get("from_team") or "").strip()
        to_team = (tr.get("to_team") or "").strip()
        pos = normalize_position(tr.get("position") or "")
        if not player or not from_team:
            continue
        if _is_free_agent_team(from_team):
            skipped_fa += 1
            continue
        key = (_norm_cmp(player), _norm_cmp(from_team), _norm_cmp(to_team))
        if key in seen:
            continue
        seen.add(key)

        any_row = False
        print(f"— {player}: {from_team} ({pos}) → {to_team}")
        for label, path in paths:
            if not os.path.isfile(path):
                continue
            e = create_engine(f"sqlite:///{path}")
            Base.metadata.create_all(e)
            S = sessionmaker(bind=e)()
            try:
                lines = _mark_left_in_session(S, from_team, player, dry_run=args.dry_run)
                if lines:
                    print(f"  [{label}]")
                    for ln in lines:
                        print(ln)
                    any_row = True
                    total_lines += len(lines)
                if not args.dry_run and lines:
                    S.commit()
            finally:
                S.close()
                e.dispose()
        if not any_row:
            print("  (строк в from_team не найдено)")

    print(f"\nИтого: пометок {total_lines}, пропущено из СА: {skipped_fa}")
    if args.dry_run:
        print("Применить: python3 scripts/apply_left_team_from_transfers.py --apply")
    else:
        from utils.common_db import rebuild_common_database

        rebuild_common_database()
        print("common.db пересобран.")


if __name__ == "__main__":
    main()
