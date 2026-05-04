# -*- coding: utf-8 -*-
"""
Формат Лиги Чемпионов (адаптация по образцу УЕФА 2025/26):
- 30 команд: из ``data/cl_participants_dynamic.txt`` (обычно топ-6 из каждой нац. лиги по ``data/draft_config.json``,
  см. ``utils/cl_standing_participants.build_cl_top30_from_draft_json`` и скрипт ``scripts/rebuild_cl_pool_and_schedule.py``),
  иначе фиксированный список ``CL_PARTICIPANTS``.
- 1-й этап: 30 команд → 6 вылетают, остаётся 24
...
"""
from pathlib import Path

from config.leagues_config import CL_PARTICIPANTS

_MODULE_DIR = Path(__file__).resolve().parent
_ROOT = _MODULE_DIR.parent
_CL_DYNAMIC = _ROOT / "data" / "cl_participants_dynamic.txt"


def get_cl_participants() -> list:
    """
    30 команд ЛЧ: если после завершения сезона создан ``data/cl_participants_dynamic.txt``,
    читаем оттуда; иначе — фиксированный список Roman+Lika (как в конфиге).
    """
    if _CL_DYNAMIC.is_file():
        lines = [
            ln.strip()
            for ln in _CL_DYNAMIC.read_text(encoding="utf-8").splitlines()
            if ln.strip()
        ]
        if len(lines) >= 2:
            return [t.title() for t in lines]
    return [t.title() for t in CL_PARTICIPANTS['roman']] + [t.title() for t in CL_PARTICIPANTS['lika']]


def get_league_phase_elimination(standings: list, n_eliminate: int = 6) -> tuple:
    """
    standings: список (team_name, points, ...) отсортированный по убыванию очков
    Возвращает (eliminated: list, remaining: list)
    """
    if len(standings) < n_eliminate:
        n_eliminate = len(standings)
    eliminated = [s[0] if isinstance(s, (list, tuple)) else s for s in standings[-n_eliminate:]]
    remaining = [s[0] if isinstance(s, (list, tuple)) else s for s in standings[:-n_eliminate]]
    return eliminated, remaining


def get_playoff_seeding(remaining_24: list, n_direct: int = 8) -> tuple:
    """
    remaining_24: 24 команды после отсева, отсортированные по месту (1-24)
    Возвращает (direct_to_playoffs: list[8], play_off_pairs: list[tuple]) 
    play_off_pairs: 8 пар (9-24, 10-23, ...) для стыков
    """
    direct = remaining_24[:n_direct]  # места 1-8
    play_off_teams = remaining_24[n_direct:]  # места 9-24
    # Пары: 9 vs 24, 10 vs 23, 11 vs 22, ...
    pairs = []
    n = len(play_off_teams)
    for i in range(n // 2):
        pairs.append((play_off_teams[i], play_off_teams[n - 1 - i]))
    return direct, pairs
