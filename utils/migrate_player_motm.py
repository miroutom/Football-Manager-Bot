# -*- coding: utf-8 -*-
"""Колонка ``motm`` (Man of the Match) во всех таблицах игроков."""
from __future__ import annotations

import logging
import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

logger = logging.getLogger(__name__)

_TABLES = ("forwards", "midfielders", "defenders", "goalkeepers")
_COL = ("motm", "INTEGER DEFAULT 0")


def _legacy_add_via_sql() -> list[str]:
    from sqlalchemy import text
    from sqlalchemy.exc import OperationalError

    from utils.utils import engine_cl, engine_common, engine_league

    out: list[str] = []
    col, typ = _COL
    for engine, label in (
        (engine_league, "league"),
        (engine_cl, "cl"),
        (engine_common, "common"),
    ):
        with engine.begin() as conn:
            for table in _TABLES:
                try:
                    conn.execute(text(f"ALTER TABLE {table} ADD COLUMN {col} {typ}"))
                    out.append(f"{label}:{table}.{col}")
                except OperationalError as e:
                    if "duplicate column name" not in str(e).lower():
                        raise
    return out


def migrate_motm_for_sqlite(db_path: str, *, label: str | None = None) -> list[str]:
    from sqlalchemy import create_engine, text
    from sqlalchemy.exc import OperationalError

    col, typ = _COL
    tag = label or db_path
    out: list[str] = []
    eng = create_engine(f"sqlite:///{db_path}")
    try:
        with eng.begin() as conn:
            for table in _TABLES:
                try:
                    conn.execute(text(f"ALTER TABLE {table} ADD COLUMN {col} {typ}"))
                    out.append(f"{tag}:{table}.{col}")
                except OperationalError as e:
                    if "duplicate column name" not in str(e).lower():
                        raise
    finally:
        eng.dispose()
    return out


def migrate_all_player_motm_columns() -> list[str]:
    import os

    from utils import season_paths

    out = _legacy_add_via_sql()
    for path_fn in (
        season_paths.get_cumulative_league_db_path,
        season_paths.get_cumulative_cl_db_path,
        season_paths.get_cumulative_common_db_path,
    ):
        path = path_fn()
        if os.path.isfile(path):
            out.extend(migrate_motm_for_sqlite(path, label=path))
    return out


if __name__ == "__main__":
    r = migrate_all_player_motm_columns()
    print("OK" if not r else "Added: " + ", ".join(r))
