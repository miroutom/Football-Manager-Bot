# -*- coding: utf-8 -*-
"""
Пути к БД и pickle: режим **legacy** (как раньше: db/*_synced.db и pickle/) или
**per_season** (db/season_n/league.db, … и db/season_n/pickle/).

``db/season_state.json``:
  { "data_mode": "legacy" | "per_season", "active_season": <int> }

В режиме per_season рабочие файлы: ``db/season_{active_season}/league.db``,
``champions_league.db``, ``common.db``; pickle — в ``.../pickle/``.

Накопительная статистика за **все** сезоны — те же файлы, что и в legacy-режиме:
``db/league_synced.db``, ``db/champions_league_synced.db``, ``db/common_synced.db``
(пополняются при завершении сезона; в ``per_season`` трансферы и правки overall из бота
дополнительно зеркалятся туда через ``utils/cumulative_mirror.py``).
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

# Справочник свободных агентов (один файл на весь проект, не привязан к сезону)
FREE_AGENTS_DB = "free_agents.db"


def get_free_agents_db_path() -> str:
    return os.path.join(_DB, FREE_AGENTS_DB)


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
    """Общая накопительная БД национальных лиг (все сезоны) — ``league_synced.db``."""
    return os.path.join(_DB, LEGACY_LEAGUE)


def get_cumulative_cl_db_path() -> str:
    """Общая накопительная БД ЛЧ (все сезоны) — ``champions_league_synced.db``."""
    return os.path.join(_DB, LEGACY_CL)


def get_cumulative_common_db_path() -> str:
    """Общая объединённая БД — ``common_synced.db`` (пересборка из двух synced выше)."""
    return os.path.join(_DB, LEGACY_COMMON)


def season_archive_directory(season_num: int) -> str:
    return os.path.join(_DB, f"season_{int(season_num)}")


def repair_per_season_database_files() -> list[str]:
    """
    Если в папке активного сезона нет league.db / cl / common:
    сначала пробуем ``db/season_{N-1}/`` + обнуление матчевой статистики (как при новом сезоне).
    Иначе — из ``*_synced.db`` через то же обнуление (не копировать synced как слепой снимок:
    там накопительная стата за все сезоны).
    """
    if is_legacy_mode():
        return []
    actions: list[str] = []
    league = get_league_db_path()
    season_dir = os.path.dirname(league)
    if os.path.isfile(league) and os.path.isfile(get_cl_db_path()) and os.path.isfile(get_common_db_path()):
        return actions
    os.makedirs(season_dir, exist_ok=True)

    from utils.season_end import _clone_db_zero_stats

    active = get_active_season()
    prev = active - 1
    if prev >= 1:
        pdir = season_archive_directory(prev)
        pl = os.path.join(pdir, SEASON_LEAGUE_NAME)
        pc = os.path.join(pdir, SEASON_CL_NAME)
        po = os.path.join(pdir, SEASON_COMMON_NAME)
        if os.path.isfile(pl) and os.path.isfile(pc) and os.path.isfile(po):
            if not os.path.isfile(league):
                _clone_db_zero_stats(pl, league)
                actions.append(f"restored {league} from season_{prev} (match stats zeroed)")
            if not os.path.isfile(get_cl_db_path()):
                _clone_db_zero_stats(pc, get_cl_db_path())
                actions.append("restored cl from previous season")
            if not os.path.isfile(get_common_db_path()):
                _clone_db_zero_stats(po, get_common_db_path())
                actions.append("restored common from previous season")
            return actions

    leg_l = os.path.join(_DB, LEGACY_LEAGUE)
    leg_c = os.path.join(_DB, LEGACY_CL)
    leg_o = os.path.join(_DB, LEGACY_COMMON)
    if not os.path.isfile(league) and os.path.isfile(leg_l):
        _clone_db_zero_stats(leg_l, league)
        actions.append(f"restored {league} from {LEGACY_LEAGUE} (match stats zeroed)")
    if not os.path.isfile(get_cl_db_path()) and os.path.isfile(leg_c):
        _clone_db_zero_stats(leg_c, get_cl_db_path())
        actions.append(f"restored cl from {LEGACY_CL} (match stats zeroed)")
    if not os.path.isfile(get_common_db_path()) and os.path.isfile(leg_o):
        _clone_db_zero_stats(leg_o, get_common_db_path())
        actions.append(f"restored common from {LEGACY_COMMON} (match stats zeroed)")
    return actions
