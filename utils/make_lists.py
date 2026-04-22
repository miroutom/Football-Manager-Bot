import os
import csv

BASE_PATH = os.path.expanduser("~/PycharmProjects/PythonProject/")

CSV_FILES = {
    'league': 'csv/league.csv',
    'cl': 'csv/champ_league.csv',
}


def get_csv_path(tournament: str) -> str:
    """
    Получить путь к CSV файлу
    tournament: 'league' или 'cl'
    """
    file_name = CSV_FILES.get(tournament, CSV_FILES['league'])
    return os.path.join(BASE_PATH, file_name)


def make_lists(tournament: str = 'league'):
    """
    Получить список игроков
    tournament: 'league' - все национальные лиги
                'cl' - Лига Чемпионов
    """
    file_path = get_csv_path(tournament)

    if not os.path.exists(file_path):
        print(f"Файл {file_path} не найден")
        return []

    with open(file_path, 'r', encoding='utf-8') as file:
        reader = csv.reader(file, delimiter=';')
        next(reader)  # Пропускаем заголовок
        players = [tuple(row[:4]) for row in reader]

    return players
