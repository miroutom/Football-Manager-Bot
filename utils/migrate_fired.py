# -*- coding: utf-8 -*-
"""Колонка ``fired`` только в ``free_agents.db`` — исключён из клуба vs новый FA."""
from __future__ import annotations

import logging
import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

logger = logging.getLogger(__name__)

_TABLES = ("forwards", "midfielders", "defenders", "goalkeepers")


def migrate_fired_for_sqlite(db_path: str, *, label: str = "") -> list[str]:
    from sqlalchemy import create_engine, text
    from sqlalchemy.exc import OperationalError

    if not Path(db_path).is_file():
        return []
    tag = label or Path(db_path).name
    out: list[str] = []
    engine = create_engine(f"sqlite:///{db_path}")
    with engine.begin() as conn:
        for table in _TABLES:
            try:
                conn.execute(
                    text(
                        f"ALTER TABLE {table} ADD COLUMN fired BOOLEAN "
                        "DEFAULT 0 NOT NULL"
                    )
                )
                out.append(f"{tag}:{table}")
            except OperationalError as e:
                if "duplicate column name" not in str(e).lower():
                    raise
    engine.dispose()
    return out


def ensure_fired_schema(db_path: str | None = None) -> None:
    """Идемпотентно: ``fired`` только в ``db/free_agents.db``."""
    if db_path is None:
        from utils.free_agents_db import get_free_agents_db_path

        db_path = get_free_agents_db_path()
    migrate_fired_for_sqlite(db_path, label="free_agents")


def migrate_all_fired_columns() -> list[str]:
    from utils.free_agents_db import get_free_agents_db_path

    return migrate_fired_for_sqlite(get_free_agents_db_path(), label="free_agents")


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    added = migrate_all_fired_columns()
    if added:
        print("Добавлено:", ", ".join(added))
    else:
        print("Колонка fired уже есть в free_agents.db.")
