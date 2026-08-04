# -*- coding: utf-8 -*-
"""Колонка ``lineup_slot`` — слот на поле для стартового состава."""
from __future__ import annotations

import logging
import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

logger = logging.getLogger(__name__)

_TABLES = ("forwards", "midfielders", "defenders", "goalkeepers")


def _add_column_via_engines() -> list[str]:
    from utils.migrate_sqlite_schema import safe_add_column, sqlite_has_player_roster
    from utils.utils import engine_cl, engine_common, engine_league

    out: list[str] = []
    for engine, label in (
        (engine_league, "league"),
        (engine_cl, "cl"),
        (engine_common, "common"),
    ):
        with engine.begin() as conn:
            if not sqlite_has_player_roster(conn):
                continue
            for table in _TABLES:
                if safe_add_column(conn, table, "lineup_slot VARCHAR"):
                    out.append(f"{label}:{table}")
    return out


def migrate_lineup_slot_for_sqlite(db_path: str, *, label: str = "") -> list[str]:
    from sqlalchemy import create_engine

    from utils.migrate_sqlite_schema import safe_add_column, sqlite_has_player_roster

    if not Path(db_path).is_file():
        return []
    tag = label or Path(db_path).name
    out: list[str] = []
    engine = create_engine(f"sqlite:///{db_path}")
    with engine.begin() as conn:
        if not sqlite_has_player_roster(conn):
            engine.dispose()
            return []
        for table in _TABLES:
            if safe_add_column(conn, table, "lineup_slot VARCHAR"):
                out.append(f"{tag}:{table}")
    engine.dispose()
    return out


def ensure_lineup_slot_schema(db_path: str) -> None:
    """Идемпотентно: колонка ``lineup_slot`` в четырёх таблицах игроков."""
    migrate_lineup_slot_for_sqlite(db_path)


def migrate_all_lineup_slot_columns() -> list[str]:
    from utils import season_paths

    out = _add_column_via_engines()
    seen = set(out)
    for label, path in season_paths.iter_player_roster_db_paths(
        include_synced=True, include_archives=True
    ):
        for item in migrate_lineup_slot_for_sqlite(path, label=label):
            if item not in seen:
                seen.add(item)
                out.append(item)
    return out


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    added = migrate_all_lineup_slot_columns()
    if added:
        print("Добавлено:", ", ".join(added))
    else:
        print("Колонка lineup_slot уже есть.")
