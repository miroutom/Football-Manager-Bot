# -*- coding: utf-8 -*-
"""
Колонки ``yellow_cards``, ``red_cards`` (ЖК, КК в смысле учёта за сезон) во всех таблицах игроков.
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
_COLS: tuple[tuple[str, str], ...] = (
    ("yellow_cards", "INTEGER DEFAULT 0"),
    ("red_cards", "INTEGER DEFAULT 0"),
)


def _legacy_add_via_sql() -> list[str]:
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
                for col, typ in _COLS:
                    try:
                        conn.execute(
                            text(f"ALTER TABLE {table} ADD COLUMN {col} {typ}")
                        )
                        out.append(f"{label}:{table}.{col}")
                    except OperationalError as e:
                        if "duplicate column name" not in str(e).lower():
                            raise
    return out


def migrate_all_player_discipline_columns() -> list[str]:
    ini = _ROOT / "alembic.ini"
    try:
        from alembic import command
        from alembic.config import Config
    except ImportError:
        logger.info("Alembic не установлен — добавляю жк/кк через ALTER TABLE")
        return _legacy_add_via_sql()

    if not ini.is_file():
        logger.info("Нет alembic.ini — добавляю жк/кк через ALTER TABLE")
        return _legacy_add_via_sql()
    try:
        cfg = Config(str(ini))
        command.upgrade(cfg, "head")
    except Exception as e:
        logger.warning("alembic upgrade: %s — fallback ALTER", e)
        return _legacy_add_via_sql()
    # Alembic может не знать про жк/кк — idempotent ADD COLUMN
    return _legacy_add_via_sql()


if __name__ == "__main__":
    r = migrate_all_player_discipline_columns()
    print("OK" if not r else "Added: " + ", ".join(r))
