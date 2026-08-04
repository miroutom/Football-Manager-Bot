# -*- coding: utf-8 -*-
"""Общие помощники миграций SQLite с таблицами игроков."""
from __future__ import annotations

from sqlalchemy import text
from sqlalchemy.exc import OperationalError

PLAYER_TABLES = ("forwards", "midfielders", "defenders", "goalkeepers")


def sqlite_has_player_roster(conn) -> bool:
    """Есть ли в файле хотя бы одна таблица состава (forwards/…)."""
    n = conn.execute(
        text(
            "SELECT COUNT(*) FROM sqlite_master "
            "WHERE type='table' AND name IN "
            "('forwards','midfielders','defenders','goalkeepers')"
        )
    ).scalar()
    return int(n or 0) > 0


def safe_add_column(conn, table: str, ddl: str) -> bool:
    """
    ``ALTER TABLE … ADD COLUMN …``; игнорировать дубликат колонки и отсутствие таблицы.
    Возвращает True, если колонка добавлена.
    """
    try:
        conn.execute(text(f"ALTER TABLE {table} ADD COLUMN {ddl}"))
        return True
    except OperationalError as e:
        msg = str(e).lower()
        if "duplicate column" in msg or "no such table" in msg:
            return False
        raise
