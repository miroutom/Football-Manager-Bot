#!/usr/bin/env python3
"""
Пакетное слияние «один клуб, две позиции» (--no-sum).

  python3 scripts/merge_position_duplicates_dry_run.py
  python3 scripts/merge_position_duplicates_dry_run.py --apply
"""
from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
MERGE = ROOT / "scripts" / "merge_duplicate_player_rows.py"

# (имя, клуб, позиция которую оставить)
MERGES: list[tuple[str, str, str]] = [
    ("Ольмо", "Лейпциг", "ЦАП"),
    ("Буанга", "Краснодар", "ФРВ"),
    ("Кох", "Франкфурт", "ЦП"),
    ("Зобнин", "Спартак", "ЦП"),
    ("Мишкич", "Урал", "ЦП"),
    ("Каземиро", "Мю", "ЦП"),
    ("Газинский", "Урал", "ЦП"),
    ("Миранчук", "Локомотив", "ЦАП"),
    ("Залевски", "Рома", "ПФА"),
    ("Коне", "Боруссия М", "ЦАП"),
]


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--apply", action="store_true", help="Применить слияния в БД")
    args = ap.parse_args()
    mode = "APPLY" if args.apply else "DRY-RUN"
    print("=" * 72)
    print(f"{mode}: слияние дублей позиций (--no-sum)")
    print("=" * 72)
    for name, team, keep_pos in MERGES:
        print(f"\n>>> {name} · {team} · оставить {keep_pos}")
        print("-" * 72)
        cmd = [
            sys.executable,
            str(MERGE),
            "--no-sum",
            "--name",
            name,
            "--team",
            team,
            "--keep-position",
            keep_pos,
        ]
        if args.apply:
            cmd.append("--apply")
        else:
            cmd.append("--dry-run")
        rc = subprocess.call(cmd, cwd=str(ROOT))
        if rc != 0:
            sys.exit(rc)
    print("\n" + "=" * 72)
    if args.apply:
        print("Слияния применены. Далее: python3 scripts/apply_left_team_from_transfers.py")
    else:
        print("Dry-run готов. Применить: … merge_position_duplicates_dry_run.py --apply")


if __name__ == "__main__":
    main()
