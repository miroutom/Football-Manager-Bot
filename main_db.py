# -*- coding: utf-8 -*-

from data.defender import Defender
from data.forward import Forward
from data.goalkeeper import Goalkeeper
from data.midfielder import Midfielder
from utils.utils import get_session, forwards, midfielders, defenders


def class_by_position(position: str):
    if position in forwards:
        return Forward
    elif position in midfielders:
        return Midfielder
    elif position in defenders:
        return Defender
    else:
        return Goalkeeper


def add_players(name: str, overall: int, team: str, position: str, session=None, tournament: str = 'league'):
    """Добавить игрока в БД"""
    if session is None:
        session = get_session(tournament)

    name = name.title()
    overall = int(overall)
    team = team.title()
    position = position.upper()

    class_to_search = class_by_position(position)
    exists = session.query(class_to_search).filter_by(name=name, team=team, position=position).first()

    if exists:
        print(f"Игрок {name} из команды {team} уже существует.")
        return

    player = class_to_search(name=name, overall=overall, team=team, position=position)
    session.add(player)
    session.commit()
    print(f"Игрок {name} добавлен в команду {team}.")


def delete_player(name: str, team: str, position: str, tournament: str = 'league'):
    session = get_session(tournament)
    name = name.title()
    team = team.title()
    position = position.upper()

    player = session.query(class_by_position(position)).filter_by(name=name, team=team, position=position).first()
    if player:
        session.delete(player)
        session.commit()
        print(f"Игрок {player.name} удален.")
    else:
        print(f"Игрок {name} не найден.")


def get_top_scorers(tournament: str = 'league', limit: int = 20):
    """Топ бомбардиров"""
    session = get_session(tournament)

    forwards_list = session.query(Forward).order_by(Forward.goals.desc()).limit(limit).all()
    midfielders_list = session.query(Midfielder).order_by(Midfielder.goals.desc()).limit(limit).all()

    all_players = forwards_list + midfielders_list
    all_players.sort(key=lambda x: x.goals, reverse=True)

    return all_players[:limit]


def get_top_assistants(tournament: str = 'league', limit: int = 20):
    """Топ ассистентов"""
    session = get_session(tournament)

    forwards_list = session.query(Forward).order_by(Forward.assists.desc()).limit(limit).all()
    midfielders_list = session.query(Midfielder).order_by(Midfielder.assists.desc()).limit(limit).all()

    all_players = forwards_list + midfielders_list
    all_players.sort(key=lambda x: x.assists, reverse=True)

    return all_players[:limit]


def get_top_ga(tournament: str = 'league', limit: int = 20):
    """Топ по Г+А"""
    session = get_session(tournament)

    forwards_list = session.query(Forward).all()
    midfielders_list = session.query(Midfielder).all()

    all_players = forwards_list + midfielders_list
    all_players.sort(key=lambda x: x.ga, reverse=True)

    return all_players[:limit]
