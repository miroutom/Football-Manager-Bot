# -*- coding: utf-8 -*-
"""
Колонка ``potm`` (Player Of The Match) во всех таблицах игроков.

При первом добавлении ``potm`` переносит накопленные значения из ``motm`` в ``potm``
и обнуляет ``motm`` — далее ``motm`` = Man Of The Month (награда за месяц).
"""
from __future__ import annotations

import logging
import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

logger = logging.getLogger(__name__)

_TABLES = ("forwards", "midfielders", "defenders", "goalkeepers")
_COL = ("potm", "INTEGER DEFAULT 0")


def _split_motm_into_potm(conn, table: str) -> None:
    from sqlalchemy import text

    conn.execute(
        text(
            f"UPDATE {table} SET potm = COALESCE(motm, 0) "
            f"WHERE COALESCE(potm, 0) = 0 AND COALESCE(motm, 0) > 0"
        )
    )
    conn.execute(text(f"UPDATE {table} SET motm = 0 WHERE COALESCE(motm, 0) > 0"))


def migrate_potm_for_sqlite(db_path: str, *, label: str | None = None) -> list[str]:
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
                    _split_motm_into_potm(conn, table)
    finally:
        eng.dispose()
    return out


def migrate_all_player_potm_columns() -> list[str]:
    """Идемпотентно добавить ``potm`` и перенести старые match-MOTM в неё."""
    from utils import season_paths

    out: list[str] = []
    seen: set[str] = set()
    for label, path in season_paths.iter_player_roster_db_paths(
        include_synced=True, include_archives=True
    ):
        for item in migrate_potm_for_sqlite(path, label=label):
            if item not in seen:
                seen.add(item)
                out.append(item)
    return out


if __name__ == "__main__":
    r = migrate_all_player_potm_columns()
    print("OK" if not r else "Added: " + ", ".join(r))
