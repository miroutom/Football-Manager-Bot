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


def migrate_surname_columns_for_sqlite(db_path: str, *, label: str = "") -> list[str]:
    """Колонка ``surname`` + backfill в одном файле архива (``db/season_N/league.db`` и т.д.)."""
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
                conn.execute(text(f"ALTER TABLE {table} ADD COLUMN surname VARCHAR"))
                out.append(f"{tag}:{table}:add")
            except OperationalError as e:
                if "duplicate column name" not in str(e).lower():
                    raise
            conn.execute(
                text(
                    f"UPDATE {table} SET surname = name "
                    f"WHERE surname IS NULL OR trim(surname) = ''"
                )
            )
            out.append(f"{tag}:{table}:backfill")
    engine.dispose()
    return out


def migrate_season_archive_surnames(season_num: int) -> list[str]:
    """``league.db`` и ``champions_league.db`` в ``db/season_N/``."""
    from utils import season_paths

    base = season_paths.season_archive_directory(season_num)
    log: list[str] = []
    for fname in (season_paths.SEASON_LEAGUE_NAME, season_paths.SEASON_CL_NAME):
        path = Path(base) / fname
        if path.is_file():
            log.extend(
                migrate_surname_columns_for_sqlite(str(path), label=f"s{season_num}/{fname}")
            )
    return log


def prepare_season_archive_schema(season_num: int) -> list[str]:
    """Колонки ``surname`` и ``left_team`` в архиве сезона (для ORM-скриптов)."""
    from utils import season_paths
    from utils.migrate_player_left_team import migrate_left_team_for_sqlite

    base = season_paths.season_archive_directory(season_num)
    log = migrate_season_archive_surnames(season_num)
    for fname in (season_paths.SEASON_LEAGUE_NAME, season_paths.SEASON_CL_NAME):
        path = Path(base) / fname
        if path.is_file():
            log.extend(
                migrate_left_team_for_sqlite(str(path), label=f"s{season_num}/{fname}")
            )
    return log


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    added = migrate_all_player_surname_columns()
    print("OK:", ", ".join(added) if added else "уже применено")
