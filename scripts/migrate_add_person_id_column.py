#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Фаза 0: колонка person_id + инициализация players_registry.db."""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from utils import season_paths
from utils.migrate_player_person_id import count_null_person_ids, migrate_all_player_person_id_columns
from utils.person_registry import init_registry_db, registry_db_path


def main() -> None:
    import argparse

    ap = argparse.ArgumentParser()
    ap.add_argument("--archives", action="store_true", help="db/season_N/*.db")
    args = ap.parse_args()

    init_registry_db()
    print(f"Реестр: {registry_db_path()}")
    added = migrate_all_player_person_id_columns(include_archives=args.archives)
    if added:
        print("ALTER:", ", ".join(added))
    else:
        print("Схема person_id уже актуальна.")

    grand = 0
    for label, path in season_paths.iter_player_roster_db_paths(
        include_synced=True,
        include_archives=args.archives,
    ):
        stats = count_null_person_ids(path)
        if not stats:
            continue
        t = sum(stats.values())
        grand += t
        print(f"  {label}: {t} строк без person_id")
    print(f"Итого строк с person_id IS NULL: {grand}")


if __name__ == "__main__":
    main()
