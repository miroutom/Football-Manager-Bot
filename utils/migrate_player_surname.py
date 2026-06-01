# -*- coding: utf-8 -*-
"""
Колонка ``surname`` у игроков. Пока пустая — копируем из ``name`` для отображения.

CLI::

    python -m utils.migrate_player_surname
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


def _legacy_add_surname_via_sql() -> list[str]:
    from sqlalchemy import text
    from sqlalchemy.exc import OperationalError

    from utils.utils import engine_cl, engine_common, engine_league

    out: list[str] = []
    for engine, label in (
        (engine_league, "league"),
        (engine_cl, "cl"),
        (engine_common, "common"),
    ):
        with engine.begin() as conn:
            for table in _TABLES:
                try:
                    conn.execute(
                        text(f"ALTER TABLE {table} ADD COLUMN surname VARCHAR")
                    )
                    out.append(f"{label}:{table}:add")
                except OperationalError as e:
                    if "duplicate column name" not in str(e).lower():
                        raise
            for table in _TABLES:
                conn.execute(
                    text(
                        f"UPDATE {table} SET surname = name "
                        f"WHERE surname IS NULL OR trim(surname) = ''"
                    )
                )
                out.append(f"{label}:{table}:backfill")
    return out


def migrate_all_player_surname_columns() -> list[str]:
    return _legacy_add_surname_via_sql()


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    added = migrate_all_player_surname_columns()
    print("OK:", ", ".join(added) if added else "уже применено")
