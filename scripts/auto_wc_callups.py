#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Автовызов лучших игроков в сборные ЧМ (4-3-3 ат) + экспорт для Transfer Window App.

  python3 scripts/auto_wc_callups.py
  python3 scripts/auto_wc_callups.py --apply
  python3 scripts/auto_wc_callups.py --bundle
  python3 scripts/auto_wc_callups.py --wc-out path/wc_squads_auto.txt
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

_DEFAULT_DIR = _ROOT / "data" / "transfer_window"

_RECENT_TRANSFERS = [
    ("Палазон", "Барселона", "Лацио"),
    ("Байер", "Лацио", "Локомотив"),
    ("Дембеле", "Локомотив", "Барселона"),
]


def _write_transfers_simple(path: Path, rows: list[tuple[str, str, str]]) -> None:
    lines = ["Игрок\tКлуб (из)\tКлуб (в)"]
    for name, from_team, to_team in rows:
        lines.append(f"{name}\t{from_team}\t{to_team}")
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def _export_club_squads(path: Path) -> int:
    from utils.transfer_export import export_squads_txt_for_bot

    text = export_squads_txt_for_bot()
    path.write_text(text, encoding="utf-8")
    return text.count("\n@")


def main() -> int:
    ap = argparse.ArgumentParser(description="Auto WC callups + transfer app exports")
    ap.add_argument(
        "--wc-out",
        type=Path,
        default=_DEFAULT_DIR / "wc_squads_auto_callups.txt",
        help="wc_squads_export.txt для режима сборных в transfer app",
    )
    ap.add_argument(
        "--squads-out",
        type=Path,
        default=None,
        help="squads_export клубов (текущая league.db)",
    )
    ap.add_argument(
        "--transfers-out",
        type=Path,
        default=None,
        help="transfers_simple.txt (недавние переносы)",
    )
    ap.add_argument(
        "--bundle",
        action="store_true",
        help="Также squads_export_current.txt и transfers_simple_recent.txt",
    )
    ap.add_argument(
        "--apply",
        action="store_true",
        help="Записать заявки в data/world_cup_squads.json",
    )
    ap.add_argument(
        "--formation-id",
        type=int,
        default=1,
        help="Схема сборной (1 = 4-3-3 ат)",
    )
    args = ap.parse_args()

    if args.bundle:
        args.squads_out = args.squads_out or (_DEFAULT_DIR / "squads_export_current.txt")
        args.transfers_out = args.transfers_out or (_DEFAULT_DIR / "transfers_simple_recent.txt")

    from utils.wc_auto_callups import auto_callup_summary, build_all_auto_callup_teams
    from utils.wc_squad_app import apply_nation_teams_to_wc_squads, format_wc_squads_export_txt

    teams = build_all_auto_callup_teams(formation_id=args.formation_id)
    wc_text = format_wc_squads_export_txt(teams)
    args.wc_out.parent.mkdir(parents=True, exist_ok=True)
    args.wc_out.write_text(wc_text, encoding="utf-8")
    print(f"WC squads: {len(teams)} наций → {args.wc_out}")

    summary = auto_callup_summary(teams)
    print(
        f"  полных заявок: {summary['complete']}/{summary['nations']}, "
        f"нужно добрать: {len(summary['incomplete'])}"
    )
    for row in summary["incomplete"][:12]:
        miss = ", ".join(row.get("missing") or [])
        print(f"    {row['nation']}: {row['total']}/26 — {miss}")
    if len(summary["incomplete"]) > 12:
        print(f"    … ещё {len(summary['incomplete']) - 12}")

    if args.apply:
        stats = apply_nation_teams_to_wc_squads(teams, save=True)
        print(f"  записано в world_cup_squads.json: {stats['nations']} наций, {stats['players']} игроков")

    if args.squads_out:
        n = _export_club_squads(args.squads_out)
        print(f"Club squads → {args.squads_out} (~{n} clubs)")

    if args.transfers_out:
        _write_transfers_simple(args.transfers_out, _RECENT_TRANSFERS)
        print(f"Transfers → {args.transfers_out} ({len(_RECENT_TRANSFERS)} moves)")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
