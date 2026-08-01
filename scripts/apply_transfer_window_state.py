#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Применить сейв трансферного окна (лето/зима) к рабочим БД сезона:

1. трансферы из ``transfers``;
2. полные заявки из txt-экспорта (или из ``teams`` в JSON);
3. схемы тренеров ``formation_id``.

По умолчанию — зимний сейв из Application Support (macOS).

  python3 scripts/apply_transfer_window_state.py --dry-run
  python3 scripts/apply_transfer_window_state.py
  python3 scripts/apply_transfer_window_state.py --state path/to/state.json --squads path/to/squads.txt
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

_DEFAULT_STATE = (
    Path.home()
    / "Library/Application Support/FootballManagerBot/transfer_window"
    / "transfer_window_state_winter.json"
)
_DEFAULT_SQUADS = (
    Path.home()
    / "Library/Application Support/FootballManagerBot/transfer_window"
    / "squads_export_winter.txt"
)


def _strip_transfers_appendix(text: str) -> str:
    from utils.transfer_window_apply import strip_transfers_appendix as _strip

    return _strip(text)


def _apply_transfers(transfers: list[dict], *, dry_run: bool) -> int:
    from utils.transfer_window_apply import apply_transfers

    return apply_transfers(transfers, dry_run=dry_run)


def _apply_squads_file(path: Path, *, dry_run: bool) -> int:
    from utils.transfer_window_apply import apply_squads_text

    return apply_squads_text(path.read_text(encoding="utf-8"), dry_run=dry_run)


def _apply_formations(teams: list[dict], *, dry_run: bool) -> int:
    from utils.transfer_window_apply import apply_formations

    return apply_formations(teams, dry_run=dry_run)


def main() -> int:
    ap = argparse.ArgumentParser(description="Apply transfer window state to season DBs")
    ap.add_argument("--state", type=Path, default=_DEFAULT_STATE)
    ap.add_argument("--squads", type=Path, default=_DEFAULT_SQUADS)
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--skip-transfers", action="store_true")
    ap.add_argument("--skip-squads", action="store_true")
    ap.add_argument("--skip-formations", action="store_true")
    args = ap.parse_args()

    if not args.state.is_file():
        print("нет state:", args.state, file=sys.stderr)
        return 1
    data = json.loads(args.state.read_text(encoding="utf-8"))
    window = data.get("window") or "?"
    transfers = list(data.get("transfers") or [])
    if not transfers:
        from utils.transfer_window_apply import _transfers_from_state_dict

        transfers = _transfers_from_state_dict(data)
    teams = list(data.get("teams") or [])
    print(f"window={window} transfers={len(transfers)} teams={len(teams)}")
    print(f"state={args.state}")
    if args.dry_run:
        print("DRY-RUN — БД не пишем")

    if not args.skip_transfers:
        print("=== transfers ===")
        n = _apply_transfers(transfers, dry_run=args.dry_run)
        print(f"transfers done: {n}")
        if not args.dry_run and n:
            from utils.common_db import rebuild_common_database

            rebuild_common_database()
            print("common.db rebuilt after transfers")

    if not args.skip_squads:
        print("=== squads ===")
        if not args.squads.is_file():
            print("нет squads:", args.squads, file=sys.stderr)
            return 1
        n = _apply_squads_file(args.squads, dry_run=args.dry_run)
        print(f"squads done: {n}")

    if not args.skip_formations:
        print("=== formations ===")
        n = _apply_formations(teams, dry_run=args.dry_run)
        print(f"formations done: {n}")

    print("OK" + (" (dry-run)" if args.dry_run else ""))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
