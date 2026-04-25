# -*- coding: utf-8 -*-
"""Добавить колонку status в таблицы игроков (идемпотентно по наличию колонки).

Revision ID: 001_player_status
Revises:
Create Date: 2026-04-09

"""
from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy import inspect

revision: str = "001_player_status"
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_TABLES = ("forwards", "midfielders", "defenders", "goalkeepers")


def _has_column(bind, table: str, column: str) -> bool:
    try:
        cols = inspect(bind).get_columns(table)
    except Exception:
        return False
    return any(c.get("name") == column for c in cols)


def upgrade() -> None:
    bind = op.get_bind()
    for table in _TABLES:
        if not _has_column(bind, table, "status"):
            op.add_column(table, sa.Column("status", sa.String(16), nullable=True))


def downgrade() -> None:
    bind = op.get_bind()
    for table in _TABLES:
        if _has_column(bind, table, "status"):
            op.drop_column(table, "status")
