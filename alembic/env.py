# -*- coding: utf-8 -*-
"""
Alembic: одна метадата ``Base``, три файла БД (лига, ЛЧ, common).
Каждый прогон ``upgrade`` применяет те же ревизии ко всем трём движкам подряд.
"""
from __future__ import annotations

import sys
from logging.config import fileConfig
from pathlib import Path

from alembic import context

# Корень проекта в PYTHONPATH
_ROOT = Path(__file__).resolve().parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from data.defender import Defender  # noqa: F401
from data.forward import Forward  # noqa: F401
from data.goalkeeper import Goalkeeper  # noqa: F401
from data.midfielder import Midfielder  # noqa: F401
from utils.utils import Base, engine_cl, engine_common, engine_league

config = context.config

if config.config_file_name is not None:
    fileConfig(config.config_file_name)

target_metadata = Base.metadata

_PLAYER_TABLES = ("forwards", "midfielders", "defenders", "goalkeepers")


def run_migrations_offline() -> None:
    url = config.get_main_option("sqlalchemy.url")
    context.configure(
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
    )
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    """Последовательно: league_new.db → champions_league_new.db → common.db."""
    connectables = (
        ("league", engine_league),
        ("cl", engine_cl),
        ("common", engine_common),
    )
    for _label, connectable in connectables:
        with connectable.connect() as connection:
            context.configure(
                connection=connection,
                target_metadata=target_metadata,
                compare_type=True,
            )
            with context.begin_transaction():
                context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
