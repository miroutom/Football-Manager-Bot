# -*- coding: utf-8 -*-
"""
Пути к БД и pickle: режим **legacy** (как раньше: db/*_synced.db и pickle/) или
**per_season** (db/season_n/league.db, … и db/season_n/pickle/).

``db/season_state.json``:
  { "data_mode": "legacy" | "per_season", "active_season": <int> }

В режиме per_season рабочие файлы: ``db/season_{active_season}/league.db``,
``champions_league.db``, ``common.db``; pickle — в ``.../pickle/``.

Накопительная статистика за **все** сезоны лежит прямо в ``db/``:
``db/league.db``, ``db/champions_league.db``, ``db/common.db`` (пополняются при завершении сезона).
"""
from __future__ import annotations

import json
import os
import shutil
from typing import Any

# Не тянем utils (циклический импорт); корень = родитель пакета utils
PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_DB = os.path.join(PROJECT_ROOT, "db")
_STATE_FILE = os.path.join(_DB, "season_state.json")

# Имена файлов в папке сезона (как в ТЗ)
SEASON_LEAGUE_NAME = "league.db"
SEASON_CL_NAME = "champions_league.db"
SEASON_COMMON_NAME = "common.db"

# Legacy-имена (текущий репо)
LEGACY_LEAGUE = "league_synced.db"
LEGACY_CL = "champions_league_synced.db"
LEGACY_COMMON = "common_synced.db"


def _read_state() -> dict[str, Any]:
    if not os.path.isfile(_STATE_FILE):
        return {"data_mode": "legacy", "active_season": 1}
    with open(_STATE_FILE, encoding="utf-8") as f:
        out = json.load(f)
    out.setdefault("data_mode", "legacy")
    out.setdefault("active_season", 1)
    return out


def get_state() -> dict[str, Any]:
    return _read_state().copy()


def is_legacy_mode() -> bool:
    return _read_state()["data_mode"] == "legacy"


def get_active_season() -> int:
    return int(_read_state()["active_season"] or 1)


def _season_subdir() -> str:
    return f"season_{get_active_season()}"


def get_season_directory_abs() -> str:
    """
    Каталог активного сезона (per_season) или пустой для legacy
    (pickle/лежат отдельно в get_pickle_directory()).
    """
    if is_legacy_mode():
        return _DB
    return os.path.join(_DB, _season_subdir())


def get_pickle_directory() -> str:
    st = _read_state()
    if st["data_mode"] == "legacy":
        return os.path.join(PROJECT_ROOT, "pickle")
    return os.path.join(_DB, _season_subdir(), "pickle")


def get_league_db_path() -> str:
    if is_legacy_mode():
        return os.path.join(_DB, LEGACY_LEAGUE)
    return os.path.join(_DB, _season_subdir(), SEASON_LEAGUE_NAME)


def get_cl_db_path() -> str:
    if is_legacy_mode():
        return os.path.join(_DB, LEGACY_CL)
    return os.path.join(_DB, _season_subdir(), SEASON_CL_NAME)


def get_common_db_path() -> str:
    if is_legacy_mode():
        return os.path.join(_DB, LEGACY_COMMON)
    return os.path.join(_DB, _season_subdir(), SEASON_COMMON_NAME)


def write_state(data: dict[str, Any]) -> None:
    os.makedirs(_DB, exist_ok=True)
    with open(_STATE_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


def ensure_pickle_subdir() -> str:
    d = get_pickle_directory()
    os.makedirs(d, exist_ok=True)
    return d


def get_cumulative_league_db_path() -> str:
    """Общая накопительная БД национальных лиг (все сезоны)."""
    return os.path.join(_DB, SEASON_LEAGUE_NAME)


def get_cumulative_cl_db_path() -> str:
    """Общая накопительная БД ЛЧ (все сезоны)."""
    return os.path.join(_DB, SEASON_CL_NAME)


def get_cumulative_common_db_path() -> str:
    """Общая объединённая БД (лига + ЛЧ), пересобирается из двух файлов выше."""
    return os.path.join(_DB, SEASON_COMMON_NAME)


def season_archive_directory(season_num: int) -> str:
    return os.path.join(_DB, f"season_{int(season_num)}")


def repair_per_season_database_files() -> list[str]:
    """
    Если в season_state режим per_season, а файлов league.db в папке сезона нет,
    копируем из legacy *_synced.db в активную папку (восстановление после сбоя).
    Возвращает список выполненных действий (для логов).
    """
    if is_legacy_mode():
        return []
    actions: list[str] = []
    league = get_league_db_path()
    season_dir = os.path.dirname(league)
    if os.path.isfile(league) and os.path.isfile(get_cl_db_path()) and os.path.isfile(get_common_db_path()):
        return actions
    os.makedirs(season_dir, exist_ok=True)
    leg_l = os.path.join(_DB, LEGACY_LEAGUE)
    leg_c = os.path.join(_DB, LEGACY_CL)
    leg_o = os.path.join(_DB, LEGACY_COMMON)
    if not os.path.isfile(league) and os.path.isfile(leg_l):
        shutil.copy2(leg_l, league)
        actions.append(f"restored {league} from legacy")
    if not os.path.isfile(get_cl_db_path()) and os.path.isfile(leg_c):
        shutil.copy2(leg_c, get_cl_db_path())
        actions.append("restored cl db from legacy")
    if not os.path.isfile(get_common_db_path()) and os.path.isfile(leg_o):
        shutil.copy2(leg_o, get_common_db_path())
        actions.append("restored common from legacy")
    return actions
