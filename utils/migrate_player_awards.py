# -*- coding: utf-8 -*-
"""
Идемпотентно добавляет колонки наград (золотой мяч, бутса, перчатка, golden boy) к таблицам
игроков в league / cl / common SQLite, если их ещё нет.
Вызывется при старте бота после migrate_all_player_status_columns.
"""
from __future__ import annotations

import logging
import sys
from pathlib import Path

from sqlalchemy import text
from sqlalchemy.exc import OperationalError

_ROOT = Path(__file__).resolve().parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from utils.utils import engine_cl, engine_common, engine_league

logger = logging.getLogger(__name__)

# (table, column, sqlite_type) — в порядке, без дубликатов
_ALTER: list[tuple[str, str, str]] = [
    ("forwards", "golden_boots", "INTEGER NOT NULL DEFAULT 0"),
    ("midfielders", "golden_boots", "INTEGER NOT NULL DEFAULT 0"),
    ("forwards", "golden_boys", "INTEGER NOT NULL DEFAULT 0"),
    ("midfielders", "golden_boys", "INTEGER NOT NULL DEFAULT 0"),
    ("defenders", "golden_boots", "INTEGER NOT NULL DEFAULT 0"),
    ("defenders", "golden_boys", "INTEGER NOT NULL DEFAULT 0"),
    ("goalkeepers", "golden_boots", "INTEGER NOT NULL DEFAULT 0"),
    ("goalkeepers", "golden_gloves", "INTEGER NOT NULL DEFAULT 0"),
    ("goalkeepers", "golden_boys", "INTEGER NOT NULL DEFAULT 0"),
]


def migrate_player_awards_columns() -> list[str]:
    out: list[str] = []
    for engine, label in (
        (engine_league, "league"),
        (engine_cl, "cl"),
        (engine_common, "common"),
    ):
        with engine.begin() as conn:
            for table, col, sqlt in _ALTER:
                try:
                    conn.execute(text(f"ALTER TABLE {table} ADD COLUMN {col} {sqlt}"))
                    out.append(f"{label}:{table}.{col}")
                except OperationalError as e:
                    if "duplicate column" not in str(e).lower():
                        raise
    if out:
        logger.info("Awards columns added: %s", ", ".join(out))
    return out


if __name__ == "__main__":
    r = migrate_player_awards_columns()
    print("OK" if not r else "Added: " + ", ".join(r))
