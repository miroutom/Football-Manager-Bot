# -*- coding: utf-8 -*-
"""
Расчёт силы команды для отбора в ЛЧ.
Сила = средний overall игроков команды в БД (или дефолт 70 если нет данных).
"""
from utils.utils import get_session
from data.forward import Forward
from data.midfielder import Midfielder
from data.defender import Defender
from data.goalkeeper import Goalkeeper

# Нормализация названий команд (БД может хранить в другом формате)
def _normalize_team(team: str) -> str:
    return team.strip().title()

def get_team_strength(team_name: str, tournament: str = 'league') -> float:
    """
    Получить силу команды по среднему overall игроков.
    team_name: название команды (например "Реал", "Барселона")
    tournament: 'league' или 'cl'
    """
    try:
        session = get_session(tournament)
        team_norm = _normalize_team(team_name)

        all_overalls = []
        for Model in [Forward, Midfielder, Defender, Goalkeeper]:
            players = session.query(Model).filter(Model.team == team_norm).all()
            for p in players:
                if hasattr(p, 'overall') and p.overall:
                    all_overalls.append(p.overall)

        if not all_overalls:
            return 70.0  # дефолт для команд без игроков в БД
        return sum(all_overalls) / len(all_overalls)
    except Exception:
        return 70.0  # дефолт при ошибке (нет таблиц, нет БД и т.д.)


def get_teams_sorted_by_strength(team_names: list, tournament: str = 'league') -> list:
    """
    Отсортировать команды по силе (убывание).
    Возвращает список кортежей (team_name, strength).
    """
    scored = [(t, get_team_strength(t, tournament)) for t in team_names]
    return sorted(scored, key=lambda x: x[1], reverse=True)


def select_cl_teams(n_per_manager: int = 15, tournament: str = 'league') -> dict:
    """
    Выбрать команды для ЛЧ: по n_per_manager от Roman и от Lika (по силе).
    Возвращает {'roman': [...], 'lika': [...]} — списки названий команд.
    """
    from config.leagues_config import MANAGER_TEAMS

    result = {'roman': [], 'lika': []}
    for manager in ['roman', 'lika']:
        teams = MANAGER_TEAMS[manager]
        sorted_teams = get_teams_sorted_by_strength(teams, tournament)
        result[manager] = [t[0].title() for t in sorted_teams[:n_per_manager]]
    return result
