# -*- coding: utf-8 -*-
"""Колонка ``motm`` (Man Of The Month) во всех таблицах игроков."""
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
    from utils.migrate_sqlite_schema import safe_add_column, sqlite_has_player_roster
    from utils.utils import engine_cl, engine_common, engine_league

    out: list[str] = []
    col, typ = _COL
    for engine, label in (
        (engine_league, "league"),
        (engine_cl, "cl"),
        (engine_common, "common"),
    ):
        with engine.begin() as conn:
            if not sqlite_has_player_roster(conn):
                continue
            for table in _TABLES:
                if safe_add_column(conn, table, f"{col} {typ}"):
                    out.append(f"{label}:{table}.{col}")
    return out


def migrate_motm_for_sqlite(db_path: str, *, label: str | None = None) -> list[str]:
    from sqlalchemy import create_engine

    from utils.migrate_sqlite_schema import safe_add_column, sqlite_has_player_roster

    col, typ = _COL
    tag = label or db_path
    out: list[str] = []
    eng = create_engine(f"sqlite:///{db_path}")
    try:
        with eng.begin() as conn:
            if not sqlite_has_player_roster(conn):
                return []
            for table in _TABLES:
                if safe_add_column(conn, table, f"{col} {typ}"):
                    out.append(f"{tag}:{table}.{col}")
    finally:
        eng.dispose()
    return out


def migrate_all_player_motm_columns() -> list[str]:
    """Идемпотентно добавить ``motm`` во все SQLite с игроками (сезон, synced, архивы)."""
    from utils import season_paths

    out: list[str] = []
    seen: set[str] = set()
    for label, path in season_paths.iter_player_roster_db_paths(
        include_synced=True, include_archives=True
    ):
        for item in migrate_motm_for_sqlite(path, label=label):
            if item not in seen:
                seen.add(item)
                out.append(item)
    return out


if __name__ == "__main__":
    r = migrate_all_player_motm_columns()
    print("OK" if not r else "Added: " + ", ".join(r))
