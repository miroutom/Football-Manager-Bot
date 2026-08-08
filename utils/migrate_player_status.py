# -*- coding: utf-8 -*-
"""
Миграции схемы игроков (колонка ``status`` и далее).

1. Если установлен **Alembic** и есть ``alembic.ini`` — ``upgrade head`` по трём SQLite
   (см. ``alembic/env.py``).
2. Иначе — идемпотентный ``ALTER TABLE … ADD COLUMN status`` (как раньше).

CLI::

    alembic upgrade head
    python -m utils.migrate_player_status
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


def _legacy_add_status_via_sql() -> list[str]:
    """Добавить ``status`` без Alembic (старые окружения)."""
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
                    conn.execute(text(f"ALTER TABLE {table} ADD COLUMN status VARCHAR(16)"))
                    out.append(f"{label}:{table}")
                except OperationalError as e:
                    if "duplicate column name" not in str(e).lower():
                        raise
    return out


def migrate_all_player_status_columns(*, use_alembic: bool = False) -> list[str]:
    """
    Привести схему всех трёх рабочих SQLite в соответствие с моделями.

    По умолчанию — быстрый idempotent ``ALTER TABLE`` (старт бота).
    ``use_alembic=True`` — ``alembic upgrade head`` (CLI / ручной прогон).
    """
    if not use_alembic:
        return _legacy_add_status_via_sql()

    ini = _ROOT / "alembic.ini"
    try:
        from alembic import command
        from alembic.config import Config
    except ImportError:
        logger.info("Alembic не установлен — добавляю status через ALTER TABLE")
        return _legacy_add_status_via_sql()

    if not ini.is_file():
        logger.info("Нет alembic.ini — добавляю status через ALTER TABLE")
        return _legacy_add_status_via_sql()

    cfg = Config(str(ini))
    command.upgrade(cfg, "head")
    return []


if __name__ == "__main__":
    import argparse

    p = argparse.ArgumentParser()
    p.add_argument(
        "--alembic",
        action="store_true",
        help="через alembic upgrade head (по умолчанию — быстрый ALTER TABLE)",
    )
    args = p.parse_args()
    r = migrate_all_player_status_columns(use_alembic=args.alembic)
    print("OK" if not r else "Added (legacy): " + ", ".join(r))
