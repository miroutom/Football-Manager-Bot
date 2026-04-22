"""Telegram-бот для Football Manager (таблицы, бомбардиры, сетка ЛЧ)."""

from __future__ import annotations

import os
import sys
from pathlib import Path


def ensure_project_paths() -> None:
    """Рабочая директория и sys.path — корень проекта (main.py, db/, mixed_schedule.json)."""
    root = Path(__file__).resolve().parent.parent
    sroot = str(root)
    if sroot not in sys.path:
        sys.path.insert(0, sroot)
    os.chdir(root)


ensure_project_paths()
