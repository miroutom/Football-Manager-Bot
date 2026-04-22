# -*- coding: utf-8 -*-
"""
Формат Лиги Чемпионов (адаптация по образцу УЕФА 2025/26):
- 30 команд (15 Roman + 15 Lika) — фиксированный список
- 1-й этап: 30 команд → 6 вылетают, остаётся 24
- 2-й этап: 24 команды → 8 напрямую в плей-офф, 16 в стыки (play-offs)
- Стыки: 8 пар, 8 победителей → плей-офф
- Плей-офф: 8 + 8 = 16 команд, 1/8, 1/4, 1/2, финал
"""
from config.leagues_config import CL_PARTICIPANTS


def get_cl_participants() -> list:
    """Получить 30 команд для ЛЧ (15 Roman + 15 Lika) — фиксированный список."""
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
