# -*- coding: utf-8 -*-
from table.team import Team
import pickle
import os
from config.leagues_config import england, spain, italy, germany, rpl
from utils.utils import PROJECT_ROOT

def get_pickle_dir() -> str:
    """Папка с *.pkl (legacy: project/pickle; сезон: db/season_n/pickle)."""
    from utils.season_paths import get_pickle_directory, ensure_pickle_subdir
    return ensure_pickle_subdir()

# Лига Чемпионов — 30 команд (15 Roman + 15 Lika), фиксированный список
def _get_cl_teams():
    from champions_league.cl_format import get_cl_participants
    return get_cl_participants()

champ_league = _get_cl_teams()


def ensure_pickle_dir():
    """Создать папку pickle если её нет"""
    if not os.path.exists(get_pickle_dir()):
        os.makedirs(get_pickle_dir())
        print(f"Создана папка {get_pickle_dir()}")


def save_teams(filename, teams):
    ensure_pickle_dir()
    with open(filename, 'wb') as file:
        pickle.dump(teams, file)


def load_teams(filename):
    try:
        with open(filename, 'rb') as file:
            return pickle.load(file)
    except FileNotFoundError:
        return None


def create_teams_dict(team_list):
    """Создать словарь команд из списка"""
    return {team.title(): Team(team.title()) for team in team_list}


def load_or_create_teams(filename, team_list):
    """Загрузить команды из файла или создать новые и сохранить"""
    teams = load_teams(filename)
    if teams is None:
        print(f"Файл {filename} не найден. Создаю новый...")
        teams = create_teams_dict(team_list)
        save_teams(filename, teams)
        print(f"Файл {filename} создан.")
    return teams


# Загружаем или создаём команды
ensure_pickle_dir()

teams_rpl = load_or_create_teams(f'{get_pickle_dir()}/rpl_teams.pkl', rpl)
teams_eng = load_or_create_teams(f'{get_pickle_dir()}/england_teams.pkl', england)
teams_spain = load_or_create_teams(f'{get_pickle_dir()}/spain_teams.pkl', spain)
teams_italy = load_or_create_teams(f'{get_pickle_dir()}/italy_teams.pkl', italy)
teams_germany = load_or_create_teams(f'{get_pickle_dir()}/germany_teams.pkl', germany)
teams_champ_league = load_or_create_teams(f'{get_pickle_dir()}/champ_league_teams.pkl', champ_league)


def compare_head_to_head(team1, team2, teams_dict):
    """Сравнить две команды по личным встречам"""
    t1 = teams_dict[team1]
    t2 = teams_dict[team2]

    t1_h2h = t1.get_h2h_stats(team2)
    t2_h2h = t2.get_h2h_stats(team1)

    if t1_h2h[0] != t2_h2h[0]:
        return -1 if t1_h2h[0] > t2_h2h[0] else 1

    if t1_h2h[1] != t2_h2h[1]:
        return -1 if t1_h2h[1] > t2_h2h[1] else 1

    if t1_h2h[2] != t2_h2h[2]:
        return -1 if t1_h2h[2] > t2_h2h[2] else 1

    return 0


def get_sorted_teams(teams):
    """Сортировка: очки -> разница -> личные встречи -> победы -> забитые"""
    from functools import cmp_to_key

    def compare_teams(item1, item2):
        name1, team1 = item1
        name2, team2 = item2

        if team1.points != team2.points:
            return team2.points - team1.points

        if team1.difference != team2.difference:
            return team2.difference - team1.difference

        h2h = compare_head_to_head(name1, name2, teams)
        if h2h != 0:
            return h2h

        if team1.wins != team2.wins:
            return team2.wins - team1.wins

        if team1.scored != team2.scored:
            return team2.scored - team1.scored

        return 0

    return sorted(teams.items(), key=cmp_to_key(compare_teams))


def reset_league(league_name):
    """Сбросить одну лигу"""
    global teams_rpl, teams_eng, teams_spain, teams_italy, teams_germany, teams_champ_league

    leagues = {
        'rpl': (rpl, 'rpl_teams.pkl'),
        'england': (england, 'england_teams.pkl'),
        'spain': (spain, 'spain_teams.pkl'),
        'italy': (italy, 'italy_teams.pkl'),
        'germany': (germany, 'germany_teams.pkl'),
        'cl': (champ_league, 'champ_league_teams.pkl'),
    }

    if league_name in leagues:
        team_list, filename = leagues[league_name]
        if league_name == 'cl':
            team_list = _get_cl_teams()  # пересчёт при сбросе
        teams = create_teams_dict(team_list)
        save_teams(f'{get_pickle_dir()}/{filename}', teams)

        if league_name == 'rpl':
            teams_rpl = teams
        elif league_name == 'england':
            teams_eng = teams
        elif league_name == 'spain':
            teams_spain = teams
        elif league_name == 'italy':
            teams_italy = teams
        elif league_name == 'germany':
            teams_germany = teams
        elif league_name == 'cl':
            teams_champ_league = teams

        print(f"Лига {league_name} сброшена!")
        return teams
    return None


def reset_all_teams():
    """Сбросить все команды (начать сезон заново)"""
    for league in ['rpl', 'england', 'spain', 'italy', 'germany', 'cl']:
        reset_league(league)
    print("Все лиги сброшены. Новый сезон!")


def reload_teams_from_disk() -> None:
    """Перезагрузить глобальные словари pickle (после смены каталога сезона)."""
    global teams_rpl, teams_eng, teams_spain, teams_italy, teams_germany, teams_champ_league
    pd = get_pickle_dir()
    teams_rpl = load_or_create_teams(f"{pd}/rpl_teams.pkl", rpl)
    teams_eng = load_or_create_teams(f"{pd}/england_teams.pkl", england)
    teams_spain = load_or_create_teams(f"{pd}/spain_teams.pkl", spain)
    teams_italy = load_or_create_teams(f"{pd}/italy_teams.pkl", italy)
    teams_germany = load_or_create_teams(f"{pd}/germany_teams.pkl", germany)
    teams_champ_league = load_or_create_teams(f"{pd}/champ_league_teams.pkl", champ_league)
    # main.LEAGUES держит ссылки на старые dict — обновим
    import sys
    _main = sys.modules.get("main")
    if _main is not None and hasattr(_main, "LEAGUES"):
        L = _main.LEAGUES
        L["1"]["teams"] = teams_rpl
        L["2"]["teams"] = teams_eng
        L["3"]["teams"] = teams_spain
        L["4"]["teams"] = teams_italy
        L["5"]["teams"] = teams_germany
        L["6"]["teams"] = teams_champ_league


if __name__ == "__main__":
    print("Инициализация pickle файлов...")
    reset_all_teams()
    print("Готово!")
