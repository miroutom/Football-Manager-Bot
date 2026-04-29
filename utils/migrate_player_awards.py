# -*- coding: utf-8 -*-
"""
Колонки наград: golden_boys (все позиции), golden_gloves (вратари),
golden_boots (у защитников — при отсутствии в старых БД).

Идемпотентно: ADD COLUMN, игнор «duplicate column».
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


def _add_column(conn, table: str, coldef: str) -> bool:
    try:
        conn.execute(text(f"ALTER TABLE {table} ADD COLUMN {coldef}"))
        return True
    except OperationalError as e:
        if "duplicate column name" not in str(e).lower():
            raise
        return False


def migrate_player_awards_columns() -> list[str]:
    """
    Все три рабочих SQLite: league, cl, common.
    Возвращает список ``label:table:column`` для добавленных колонок.
    """
    out: list[str] = []
    for engine, label in (
        (engine_league, "league"),
        (engine_cl, "cl"),
        (engine_common, "common"),
    ):
        with engine.begin() as conn:
            for table, coldef in (
                ("forwards", "golden_boys INTEGER DEFAULT 0"),
                ("midfielders", "golden_boys INTEGER DEFAULT 0"),
                ("defenders", "golden_boots INTEGER DEFAULT 0"),
                ("defenders", "golden_boys INTEGER DEFAULT 0"),
                ("goalkeepers", "golden_boots INTEGER DEFAULT 0"),
                ("goalkeepers", "golden_gloves INTEGER DEFAULT 0"),
                ("goalkeepers", "golden_boys INTEGER DEFAULT 0"),
            ):
                if _add_column(conn, table, coldef):
                    col = coldef.split()[0]
                    out.append(f"{label}:{table}:{col}")
    return out


if __name__ == "__main__":
    r = migrate_player_awards_columns()
    print("OK" if not r else "Added: " + ", ".join(r))
