#!/usr/bin/env python3
"""
Пакетный --dry-run слияний «один клуб, две позиции» (без суммы статов при --apply).

  python3 scripts/merge_position_duplicates_dry_run.py
"""
from __future__ import annotations

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
    print("=" * 72)
    print("DRY-RUN: слияние дублей позиций (--no-sum при будущем --apply)")
    print("=" * 72)
    for name, team, keep_pos in MERGES:
        print(f"\n>>> {name} · {team} · оставить {keep_pos}")
        print("-" * 72)
        rc = subprocess.call(
            [
                sys.executable,
                str(MERGE),
                "--dry-run",
                "--no-sum",
                "--name",
                name,
                "--team",
                team,
                "--keep-position",
                keep_pos,
            ],
            cwd=str(ROOT),
        )
        if rc != 0:
            sys.exit(rc)
    print("\n" + "=" * 72)
    print("Готово. Для применения по одному:")
    print(
        "  python3 scripts/merge_duplicate_player_rows.py --apply --no-sum "
        "--name … --team … --keep-position …"
    )


if __name__ == "__main__":
    main()
