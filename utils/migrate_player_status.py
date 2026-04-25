# -*- coding: utf-8 -*-
"""Добавить колонку ``status`` во все таблицы игроков (SQLite). Идемпотентно."""
from __future__ import annotations

import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from sqlalchemy import text
from sqlalchemy.exc import OperationalError

from utils.utils import engine_cl, engine_common, engine_league

_TABLES = ("forwards", "midfielders", "defenders", "goalkeepers")


def add_status_column_if_missing(engine, label: str) -> list[str]:
    done: list[str] = []
    with engine.begin() as conn:
        for table in _TABLES:
            sql = f"ALTER TABLE {table} ADD COLUMN status VARCHAR(16)"
            try:
                conn.execute(text(sql))
                done.append(f"{label}:{table}")
            except OperationalError as e:
                if "duplicate column name" not in str(e).lower():
                    raise
    return done


def migrate_all_player_status_columns() -> list[str]:
    out: list[str] = []
    out.extend(add_status_column_if_missing(engine_league, "league"))
    out.extend(add_status_column_if_missing(engine_cl, "cl"))
    out.extend(add_status_column_if_missing(engine_common, "common"))
    return out


if __name__ == "__main__":
    r = migrate_all_player_status_columns()
    print("OK" if not r else "Added: " + ", ".join(r))
