import csv
from data.defender import update_defender_stats, Defender
from data.forward import update_forward_stats, Forward
from data.goalkeeper import update_goalkeeper_stats, Goalkeeper
from data.midfielder import update_midfielder_stats, Midfielder
from utils.utils import (
    Base, engine_league, engine_cl,
    get_session, get_engine,
    forwards, midfielders, defenders
)
from utils.make_lists import get_csv_path, make_lists


def initialize_database(tournament: str = None):
    """
    Инициализировать БД
    tournament: 'league', 'cl' или None (обе)
    """
    if tournament is None:
        tournaments = ['league', 'cl']
    else:
        tournaments = [tournament]

    for t in tournaments:
        engine = get_engine(t)
        print(f"Создаем таблицы для {t}...")
        Base.metadata.create_all(engine)
        print(f"Таблицы для {t} успешно созданы.")


def update_all_players(tournament: str = 'league'):
    """
    Обновить статистику игроков
    tournament: 'league' - национальные лиги
                'cl' - Лига Чемпионов
    """
    file_path = get_csv_path(tournament)
    session = get_session(tournament)

    try:
        with open(file_path, newline='', encoding='utf-8') as csvfile:
            reader = csv.reader(csvfile, delimiter=';')
            next(reader)

            for row in reader:
                process_player_row(row, session)

        session.commit()
        print(f"Статистика для {tournament} обновлена")
    except FileNotFoundError:
        print(f"Файл {file_path} не найден")


def process_player_row(row, session):
    """Обработка строки с данными игрока"""
    try:
        name, overall, team, position, matches, goals, assists, _rating_csv, clean_sheets, trophies, golden_ball, golden_boot, missed_goals = row
    except ValueError:
        return

    name = name.title()
    team = team.title()
    overall = int(overall) if overall else 0
    position = position.upper()
    matches = int(matches) if matches else 0
    goals = int(goals) if goals else 0
    assists = int(assists) if assists else 0
    clean_sheets = int(clean_sheets) if clean_sheets else 0
    missed_goals = int(missed_goals) if missed_goals else 0
    trophies = int(trophies) if trophies else 0
    golden_ball = bool(golden_ball)
    golden_boot = bool(golden_boot)

    try:
        if position in forwards:
            update_forward_stats(
                session=session, name=name, overall=overall, position=position,
                team=team, matches=matches, goals=goals, assists=assists,
                trophies=trophies, golden_ball=golden_ball,
                golden_boot=golden_boot
            )
        elif position in midfielders:
            update_midfielder_stats(
                session=session, name=name, overall=overall, position=position,
                team=team, matches=matches, goals=goals, assists=assists,
                trophies=trophies, golden_ball=golden_ball,
                golden_boot=golden_boot
            )
        elif position in defenders:
            update_defender_stats(
                session=session, name=name, overall=overall, position=position,
                team=team, matches=matches, goals=goals, assists=assists,
                trophies=trophies,
                golden_ball=golden_ball
            )
        else:
            update_goalkeeper_stats(
                session=session, name=name, overall=overall, position=position,
                team=team, matches=matches, missed_goals_per_match=missed_goals,
                trophies=trophies, clean_sheet=clean_sheets,
                golden_ball=golden_ball
            )
    except AttributeError as e:
        print(f"Ошибка при обработке игрока {name}: {e}")


def add_all_players(tournament: str = 'league'):
    """Добавить всех игроков из CSV в БД"""
    from main_db import add_players

    players = make_lists(tournament)
    session = get_session(tournament)

    for player in players:
        add_players(*player, session=session)


if __name__ == "__main__":
    # Инициализируем обе БД
    initialize_database()

    # Обновляем обе
    for tournament in ['league', 'cl']:
        print(f"\n{'=' * 40}")
        print(f"Обработка {tournament.upper()}")
        print(f"{'=' * 40}")
        add_all_players(tournament)
        update_all_players(tournament)
