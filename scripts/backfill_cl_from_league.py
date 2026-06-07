#!/usr/bin/env python3
"""Добавить в champions_league.db строки из league для клубов пула ЛЧ (пропуски после трансфера)."""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from utils.player_transfer import backfill_cl_rows_from_league


def main() -> None:
    log = backfill_cl_rows_from_league()
    if not log:
        print("Пропусков нет — league и CL совпадают для клубов ЛЧ.")
        return
    print(f"Добавлено {len(log)} строк в champions_league.db:")
    for line in log:
        print(f"  + {line}")


if __name__ == "__main__":
    main()
