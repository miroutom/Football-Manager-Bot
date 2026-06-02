# -*- coding: utf-8 -*-
"""
Колонка ``person_id`` в таблицах forwards/midfielders/defenders/goalkeepers.

CLI::

    python -m utils.migrate_player_person_id
    python -m utils.migrate_player_person_id --archives
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from sqlalchemy import create_engine, text
from sqlalchemy.exc import OperationalError

_TABLES = ("forwards", "midfielders", "defenders", "goalkeepers")


def migrate_person_id_for_sqlite(db_path: str, *, label: str = "") -> list[str]:
    if not Path(db_path).is_file():
        return []
    tag = label or Path(db_path).name
    out: list[str] = []
    engine = create_engine(f"sqlite:///{db_path}")
    with engine.begin() as conn:
        for table in _TABLES:
            try:
                conn.execute(
                    text(f"ALTER TABLE {table} ADD COLUMN person_id INTEGER")
                )
                out.append(f"{tag}:{table}")
            except OperationalError as e:
                if "duplicate column name" not in str(e).lower():
                    raise
    engine.dispose()
    return out


def migrate_all_player_person_id_columns(*, include_archives: bool = False) -> list[str]:
    from utils import season_paths

    from utils.utils import engine_cl, engine_common, engine_league

    out: list[str] = []
    seen: set[str] = set()
    for engine, label in (
        (engine_league, "league"),
        (engine_cl, "cl"),
        (engine_common, "common"),
    ):
        with engine.begin() as conn:
            for table in _TABLES:
                try:
                    conn.execute(
                        text(f"ALTER TABLE {table} ADD COLUMN person_id INTEGER")
                    )
                    item = f"{label}:{table}"
                    if item not in seen:
                        seen.add(item)
                        out.append(item)
                except OperationalError as e:
                    if "duplicate column name" not in str(e).lower():
                        raise
    for label, path in season_paths.iter_player_roster_db_paths(
        include_synced=True,
        include_archives=include_archives,
    ):
        for item in migrate_person_id_for_sqlite(path, label=label):
            if item not in seen:
                seen.add(item)
                out.append(item)
    return out


def count_null_person_ids(db_path: str) -> dict[str, int]:
    if not Path(db_path).is_file():
        return {}
    engine = create_engine(f"sqlite:///{db_path}")
    totals: dict[str, int] = {}
    with engine.connect() as conn:
        for table in _TABLES:
            try:
                n = conn.execute(
                    text(f"SELECT COUNT(*) FROM {table} WHERE person_id IS NULL")
                ).scalar()
                totals[table] = int(n or 0)
            except OperationalError:
                pass
    engine.dispose()
    return totals


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description="Добавить person_id во все player SQLite")
    ap.add_argument(
        "--archives",
        action="store_true",
        help="Включить db/season_N/*.db",
    )
    ap.add_argument(
        "--report",
        action="store_true",
        help="После миграции — число строк с person_id IS NULL",
    )
    args = ap.parse_args()
    from utils import season_paths
    from utils.person_registry import init_registry_db

    init_registry_db()
    added = migrate_all_player_person_id_columns(include_archives=args.archives)
    if added:
        print("Добавлено:", ", ".join(added))
    else:
        print("Колонка person_id уже есть (или нечего менять).")
    if args.report:
        for label, path in season_paths.iter_player_roster_db_paths(
            include_synced=True,
            include_archives=args.archives,
        ):
            stats = count_null_person_ids(path)
            if stats:
                total = sum(stats.values())
                print(f"{label}: NULL person_id rows = {total} ({stats})")
