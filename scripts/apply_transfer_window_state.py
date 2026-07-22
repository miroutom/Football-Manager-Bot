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
import re
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
    """Убрать хвост ``=== transfers ===`` из экспорта составов."""
    m = re.search(r"(?im)^===\s*transfers\s*===", text)
    if m:
        return text[: m.start()].rstrip() + "\n"
    return text


def _apply_transfers(transfers: list[dict], *, dry_run: bool) -> int:
    from utils.player_transfer import apply_transfer_with_status, normalize_player_name_for_db
    from utils.transfer_input import normalize_position, resolve_team_name
    from utils.utils import session_league

    n_ok = 0
    for i, t in enumerate(transfers, 1):
        name = normalize_player_name_for_db(str(t.get("name") or ""))
        pos = normalize_position(str(t.get("position") or ""))
        frm = resolve_team_name(str(t.get("from_team") or ""), session_league) or str(
            t.get("from_team") or ""
        )
        to = resolve_team_name(str(t.get("to_team") or ""), session_league) or str(
            t.get("to_team") or ""
        )
        st = (t.get("status") or "bench")
        st = str(st).strip().lower() if st else None
        if st not in ("start", "bench", "reserve"):
            st = "bench"
        ovr = t.get("overall")
        ovr_i = int(ovr) if ovr is not None else None
        print(f"  [{i}/{len(transfers)}] {name} ({pos}) {frm} → {to} [{st}]")
        if dry_run:
            n_ok += 1
            continue
        apply_transfer_with_status(
            name,
            frm,
            pos,
            to,
            st,
            rebuild_common=False,
            new_overall=ovr_i,
        )
        n_ok += 1
    return n_ok


def _apply_squads_file(path: Path, *, dry_run: bool) -> int:
    from scripts.apply_bulk_squad_declarations import resolve_team_label, split_bulk_blocks
    from utils.roster_manual import apply_team_squad_declaration, parse_squad_declaration_text

    text = _strip_transfers_appendix(path.read_text(encoding="utf-8"))
    blocks = split_bulk_blocks(text)
    n = 0
    for team_raw, body in blocks:
        team = resolve_team_label(team_raw)
        entries, errors = parse_squad_declaration_text(body)
        if errors:
            print(f"!!! разбор {team}: {errors}", file=sys.stderr)
            raise SystemExit(2)
        if dry_run:
            print(f"  squad OK {team}: {len(entries)}")
            n += 1
            continue
        r = apply_team_squad_declaration(team, entries)
        print(f"  {team}: заявлено {r['declared']}, снято {r['released']}")
        n += 1
    return n


def _apply_formations(teams: list[dict], *, dry_run: bool) -> int:
    from coach_squad_state import get_coach_id_for_team, set_active_formation_id

    n = 0
    for t in teams:
        name = str(t.get("name") or "").strip()
        fid = t.get("formation_id")
        if not name or fid is None:
            continue
        fid_i = int(fid)
        cid = get_coach_id_for_team(name)
        if not cid:
            print(f"  !! нет тренера для {name}, схема {fid_i} пропущена")
            continue
        print(f"  {name}: схема {fid_i} (coach {cid})")
        if not dry_run:
            set_active_formation_id(cid, fid_i)
        n += 1
    return n


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
