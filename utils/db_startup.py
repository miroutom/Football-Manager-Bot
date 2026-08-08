# -*- coding: utf-8 -*-
"""Подготовка SQLite перед стартовыми миграциями бота (закрыть пул, переоткрыть после)."""
from __future__ import annotations

import logging
import os
import time

logger = logging.getLogger(__name__)


def close_global_db_connections() -> None:
    """Закрыть глобальные Session/engine из utils.utils (иначе Alembic может ждать lock)."""
    from utils import utils

    for name in ("session_league", "session_cl", "session_common"):
        session = getattr(utils, name, None)
        if session is not None:
            try:
                session.close()
            except Exception:
                pass
    for name in ("engine_league", "engine_cl", "engine_common"):
        engine = getattr(utils, name, None)
        if engine is not None:
            try:
                engine.dispose()
            except Exception:
                pass


def reopen_global_db_connections() -> None:
    from utils.utils import reinit_db_connections

    reinit_db_connections()


def _step(label: str, fn) -> None:
    t0 = time.monotonic()
    logger.info("Startup migrate: %s…", label)
    fn()
    logger.info("Startup migrate: %s OK (%.2fs)", label, time.monotonic() - t0)


def run_startup_schema_migrations() -> None:
    """
    Быстрые идемпотентные ALTER TABLE без Alembic (Alembic на проде может зависать на lock).

    Перед прогоном закрываем глобальные соединения, после — reinit_db_connections().
    """
    if os.environ.get("BOT_SKIP_STARTUP_MIGRATIONS", "").strip().lower() in (
        "1",
        "true",
        "yes",
    ):
        logger.warning("Startup migrate: skipped (BOT_SKIP_STARTUP_MIGRATIONS)")
        return

    from utils.migrate_player_awards import migrate_player_awards_columns
    from utils.migrate_player_discipline import migrate_all_player_discipline_columns
    from utils.migrate_player_left_team import migrate_all_player_left_team_columns
    from utils.migrate_player_motm import migrate_all_player_motm_columns
    from utils.migrate_player_potm import migrate_all_player_potm_columns
    from utils.migrate_player_status import migrate_all_player_status_columns
    from utils.migrate_lineup_slot import migrate_all_lineup_slot_columns

    close_global_db_connections()
    try:
        _step("status", lambda: migrate_all_player_status_columns(use_alembic=False))
        _step("left_team", migrate_all_player_left_team_columns)
        _step("lineup_slot", migrate_all_lineup_slot_columns)
        _step("discipline", migrate_all_player_discipline_columns)
        _step("awards", migrate_player_awards_columns)
        _step("potm", migrate_all_player_potm_columns)
        _step("motm", migrate_all_player_motm_columns)
    finally:
        reopen_global_db_connections()
