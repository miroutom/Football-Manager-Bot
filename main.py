"""
Football Manager - Сезон 2024/25
Режим матч-день: в один день матчи из разных лиг (РПЛ, АПЛ, Ла Лига, Серия А, Бундеслига, ЛЧ)
"""
import os
import json
from typing import Dict, Optional
from teams import (
    get_sorted_teams, save_teams, get_pickle_dir,
    teams_rpl, teams_eng, teams_spain, teams_italy, teams_germany, teams_champ_league,
    england, spain, italy, germany, rpl
)
from skipped_matches import (
    add_skipped_match,
    load_skipped_matches,
    play_skipped_match,
    remove_skipped_match,
    show_skipped_matches,
)
from match_results import (
    _normalize_cl_phase,
    add_match_result,
    cl_knockout_two_leg_totals,
    cl_phase_from_mixed_schedule_line,
    count_recorded_matches,
    find_cl_knockout_first_leg_record,
    format_played_matches_report,
    get_match_results_path,
    is_match_played as is_match_in_results,
    migrate_from_teams as migrate_match_results,
)
from schedule_view import browse_schedule_interactive
from table.schedule import (
    schedule_rpl, schedule_england, schedule_bundesliga, schedule_laliga, schedule_seria,
    schedule_cl, get_round_matches
)
from champions_league.bracket_html import open_cl_bracket_in_browser
from champions_league.knockout_bracket import format_cl_knockout_bracket_text
from player_stats import (
    input_match_stats,
    show_top_scorers,
    show_top_assistants,
    show_top_ga,
    add_stats_to_match_interactive,
    show_team_goalscorers_interactive,
    show_all_leagues_combined_full_list,
)

# Текущая активная лига
CURRENT_LEAGUE = 'rpl'  # По умолчанию РПЛ

# Маппинг лиг
LEAGUES = {
    '1': {'code': 'rpl', 'name': 'РПЛ', 'teams': teams_rpl, 'schedule': schedule_rpl},
    '2': {'code': 'eng', 'name': 'АПЛ', 'teams': teams_eng, 'schedule': schedule_england},
    '3': {'code': 'esp', 'name': 'Ла Лига', 'teams': teams_spain, 'schedule': schedule_laliga},
    '4': {'code': 'ita', 'name': 'Серия А', 'teams': teams_italy, 'schedule': schedule_seria},
    '5': {'code': 'ger', 'name': 'Бундеслига', 'teams': teams_germany, 'schedule': schedule_bundesliga},
    '6': {'code': 'cl', 'name': 'Лига Чемпионов', 'teams': teams_champ_league, 'schedule': schedule_cl},
}

# Текущие туры для каждой лиги
current_rounds = {
    'rpl': 1,
    'eng': 1,
    'esp': 1,
    'ger': 1,
    'ita': 1,
    'cl': 1,
}

# Флаг: вводить ли статистику игроков после матча
INPUT_PLAYER_STATS = True

# Абсолютный путь к смешанному расписанию
from utils.utils import PROJECT_ROOT
MIXED_SCHEDULE_FILE = os.path.join(PROJECT_ROOT, 'mixed_schedule.json')


def _skipped_matches_slot(skip, home, away, league_code, cl_phase_expected):
    """Пропуск относится к этому слоту (для ЛЧ — с учётом фазы)."""
    if skip['home'] != home or skip['away'] != away:
        return False
    if skip['tournament'] != league_code:
        return False
    if league_code != 'cl':
        return True
    sp = skip.get('cl_phase') or 'knockout'
    ep = cl_phase_expected or 'knockout'
    return sp == ep


def load_or_generate_mixed_schedule():
    """
    Загрузить mixed_schedule.json с диска.

    Формат v3 (10 «месяцев»): если файла нет — один раз генерируется v3 (нац. + ЛЧ),
    плей-офф в календарь не входит. Старый плоский список матч-дней — по-прежнему
    читается как есть, если лежит в проекте.
    """
    from utils.schedule_by_months import load_parsed_mixed

    data, _ = load_parsed_mixed(MIXED_SCHEDULE_FILE)
    return data


def get_teams_by_league(league_code):
    """Получить словарь команд по коду лиги"""
    m = {
        'rpl': teams_rpl, 'eng': teams_eng, 'esp': teams_spain,
        'ger': teams_germany, 'ita': teams_italy, 'cl': teams_champ_league,
    }
    return m.get(league_code)


def find_next_match_in_schedule(mixed_schedule):
    """
    Найти следующий матч в смешанном расписании (не сыгран, не пропущен).
    Возвращает (day_num, match_str, home, away, league_code) или (None,)*5
    """
    skipped = load_skipped_matches()
    for day_data in mixed_schedule:
        day_num = day_data['day']
        for match_str in day_data['matches']:
            parts = match_str.split(';')
            if len(parts) < 3:
                continue
            home, away, league_code = parts[0], parts[1], parts[2]
            cl_ph = (
                cl_phase_from_mixed_schedule_line(match_str)
                if league_code == 'cl'
                else None
            )
            teams = get_teams_by_league(league_code)
            if not teams:
                continue
            if is_match_played(home, away, league_code, teams, cl_phase=cl_ph):
                continue
            is_skipped = any(
                _skipped_matches_slot(s, home, away, league_code, cl_ph)
                for s in skipped
            )
            if is_skipped:
                continue
            return day_num, match_str, home, away, league_code
    return None, None, None, None, None


def count_remaining_in_schedule(mixed_schedule):
    """Сколько матчей осталось в расписании"""
    count = 0
    skipped = load_skipped_matches()
    for day_data in mixed_schedule:
        day_num = day_data['day']
        for match_str in day_data['matches']:
            parts = match_str.split(';')
            if len(parts) < 3:
                continue
            home, away, league_code = parts[0], parts[1], parts[2]
            cl_ph = (
                cl_phase_from_mixed_schedule_line(match_str)
                if league_code == 'cl'
                else None
            )
            teams = get_teams_by_league(league_code)
            if not teams:
                continue
            if is_match_played(home, away, league_code, teams, cl_phase=cl_ph):
                continue
            if any(
                _skipped_matches_slot(s, home, away, league_code, cl_ph)
                for s in skipped
            ):
                continue
            count += 1
    return count


def list_remaining_schedule_matches(mixed_schedule):
    """
    Все слоты смешанного расписания, которые ещё не сыграны и не в skipped_matches
    (тот же порядок обхода, что у ``find_next_match_in_schedule``).

    Каждый элемент — dict с ключами: ``day``, ``match_str``, ``home``, ``away``,
    ``league_code``, ``cl_ph``.
    """
    skipped = load_skipped_matches()
    out = []
    for day_data in mixed_schedule:
        day_num = day_data["day"]
        for match_str in day_data["matches"]:
            parts = match_str.split(";")
            if len(parts) < 3:
                continue
            home, away, league_code = parts[0], parts[1], parts[2]
            cl_ph = (
                cl_phase_from_mixed_schedule_line(match_str)
                if league_code == "cl"
                else None
            )
            teams = get_teams_by_league(league_code)
            if not teams:
                continue
            if is_match_played(home, away, league_code, teams, cl_phase=cl_ph):
                continue
            if any(
                _skipped_matches_slot(s, home, away, league_code, cl_ph)
                for s in skipped
            ):
                continue
            out.append(
                {
                    "day": day_num,
                    "match_str": match_str,
                    "home": home,
                    "away": away,
                    "league_code": league_code,
                    "cl_ph": cl_ph,
                }
            )
    return out


def get_current_league():
    """Получить данные текущей лиги"""
    for key, league in LEAGUES.items():
        if league['code'] == CURRENT_LEAGUE:
            return league
    return LEAGUES['1']


def add_stat(first_team, second_team, first_score, second_score, teams):
    """Добавить результат матча"""
    teams[first_team].update_stats(first_score, second_score, second_team)
    teams[second_team].update_stats(second_score, first_score, first_team)


def cl_knockout_aggregate_tie_needs_penalties(
    home: str,
    away: str,
    home_score: int,
    away_score: int,
    cl_phase: Optional[str],
) -> bool:
    """Ответный матч нокаута ЛЧ и сумма двух матчей — ничья (нужна серия пенальти)."""
    if _normalize_cl_phase(cl_phase) != "knockout":
        return False
    first = find_cl_knockout_first_leg_record(home, away)
    if not first:
        return False
    totals = cl_knockout_two_leg_totals(first, home, away, home_score, away_score)
    if totals is None:
        return False
    th, ta = totals
    return th == ta


def _prompt_cl_penalties_after_aggregate_tie(
    home: str,
    away: str,
    home_score: int,
    away_score: int,
    cl_phase: Optional[str],
) -> Optional[Dict[str, int]]:
    """
    Пенальти только если это ответный матч нокаута ЛЧ и сумма двух матчей — ничья.
    Не по ничьей в одном матче, а по общему счёту стыка.
    """
    if _normalize_cl_phase(cl_phase) != "knockout":
        return None
    first = find_cl_knockout_first_leg_record(home, away)
    if not first:
        return None
    totals = cl_knockout_two_leg_totals(first, home, away, home_score, away_score)
    if totals is None:
        return None
    th, ta = totals
    if th != ta:
        return None
    fh_n, fa_n = first["home"], first["away"]
    print(
        f"\n  Сумма двух матчей: {fh_n} {th} — {ta} {fa_n} (ничья). "
        f"Нужна серия пенальти после ответного матча."
    )
    while True:
        raw = input(
            f"  Пенальти (забитые в серии): {home} (хозяева ответного), "
            f"{away} (гости) — два числа, напр. 5 4: "
        ).strip()
        try:
            ph, pa = map(int, raw.split())
        except ValueError:
            print("  Введите два целых числа через пробел.")
            continue
        if ph == pa:
            print("  В серии должен быть победитель (разные счёта).")
            continue
        return {home: ph, away: pa}


def show_cl_knockout_bracket():
    """Сетка плей-офф ЛЧ: HTML в браузере (колонки, счета из журнала) + краткий текст в консоль."""
    path = open_cl_bracket_in_browser()
    print("\n" + "=" * 70)
    print("  СЕТКА ПЛЕЙ-ОФФ ЛЧ")
    print("=" * 70)
    print("Открыта страница в браузере (если нет — открой файл вручную):")
    print(f"  {path}")
    print()
    print(format_cl_knockout_bracket_text())


def show_table(
    teams,
    title="",
    league_code=None,
    *,
    cl_journal_path: Optional[str] = None,
):
    """
    Показать таблицу. Для ЛЧ — группа из журнала (без нокаута).

    ``cl_journal_path``: путь к ``match_results.json`` архива сезона; если задан и файла
    нет — для ЛЧ берётся таблица из ``teams`` (pickle). ``None`` — живой журнал проекта.
    """
    display_teams = teams
    if league_code == "cl":
        from match_results import compute_cl_group_standings_from_journal

        if cl_journal_path is not None:
            if os.path.isfile(cl_journal_path):
                display_teams = compute_cl_group_standings_from_journal(
                    teams.keys(), journal_path=cl_journal_path
                )
            else:
                display_teams = teams
        else:
            display_teams = compute_cl_group_standings_from_journal(teams.keys())
    if title:
        print(f"\n{'='*70}")
        cl_note = (
            "\n  (групповой этап, нокаут не входит в эту таблицу)"
            if league_code == "cl"
            else ""
        )
        print(f"  {title}{cl_note}")
        print(f"{'='*70}")

    sorted_teams = get_sorted_teams(display_teams)

    headers = ["#", "Команда", "И", "В", "Н", "П", "ЗМ", "ПМ", "РМ", "О"]
    print("{:<4} {:<20} {:<4} {:<4} {:<4} {:<4} {:<5} {:<5} {:<6} {:<4}".format(*headers))
    print("-" * 65)

    for i, (name, team) in enumerate(sorted_teams, 1):
        diff = f"+{team.difference}" if team.difference > 0 else str(team.difference)
        print("{:<4} {:<20} {:<4} {:<4} {:<4} {:<4} {:<5} {:<5} {:<6} {:<4}".format(
            i, name, team.matches, team.wins, team.draws, team.losses,
            team.scored, team.missed, diff, team.points
        ))


def save_result(league_code):
    """Сохранить результаты"""
    save_mapping = {
        'rpl': ('rpl_teams.pkl', teams_rpl),
        'eng': ('england_teams.pkl', teams_eng),
        'esp': ('spain_teams.pkl', teams_spain),
        'ger': ('germany_teams.pkl', teams_germany),
        'ita': ('italy_teams.pkl', teams_italy),
        'cl': ('champ_league_teams.pkl', teams_champ_league),
    }

    if league_code in save_mapping:
        filename, teams = save_mapping[league_code]
        save_teams(f'{get_pickle_dir()}/{filename}', teams)


def process_match(home, away, home_score, away_score, league_code, round_num=None,
                  with_stats=True, cl_phase=None, *, interactive=True,
                  penalties_override=None):
    """
    Обработать результат матча.

    interactive=False — без input() (бот): без опроса статистики и без промпта пенальти;
    при ничьей в стыке ЛЧ без penalties_override запись не выполняется (вернётся False).

    penalties_override — {хозяева ответного: голы в серии, гости: ...} если уже известна серия.
    """
    teams_mapping = {
        'rpl': teams_rpl,
        'eng': teams_eng,
        'esp': teams_spain,
        'ger': teams_germany,
        'ita': teams_italy,
        'cl': teams_champ_league,
    }

    teams = teams_mapping.get(league_code)
    if teams is None:
        print(f"Лига {league_code} не найдена!")
        return False

    # Нормализуем названия
    home = home.strip().title()
    away = away.strip().title()

    cl_ph = None
    if league_code == 'cl':
        cl_ph = cl_phase if cl_phase is not None else 'knockout'
    if is_match_in_results(home, away, league_code, cl_phase=cl_ph):
        print(f"Матч {home} - {away} уже был сыгран!")
        return False

    if home not in teams:
        print(f"Команда '{home}' не найдена в лиге!")
        for team_name in teams.keys():
            if home.lower() in team_name.lower() or team_name.lower() in home.lower():
                print(f"  Возможно вы имели в виду: '{team_name}'?")
        return False

    if away not in teams:
        print(f"Команда '{away}' не найдена в лиге!")
        for team_name in teams.keys():
            if away.lower() in team_name.lower() or team_name.lower() in away.lower():
                print(f"  Возможно вы имели в виду: '{team_name}'?")
        return False

    penalties_by_team = None
    if league_code == "cl":
        if penalties_override is not None:
            penalties_by_team = penalties_override
        elif cl_knockout_aggregate_tie_needs_penalties(
            home, away, home_score, away_score, cl_ph
        ):
            if interactive:
                penalties_by_team = _prompt_cl_penalties_after_aggregate_tie(
                    home, away, home_score, away_score, cl_ph
                )
            else:
                print(
                    "✗ По сумме двух матчей ничья — нужна серия пенальти. "
                    "Запишите результат в консольном main.py или добавьте ввод пенальти в боте."
                )
                return False
        else:
            penalties_by_team = None

    # Таблица ЛЧ в меню — только группа (см. show_table + match_results); нокаут в pickle не копим
    cl_ph_norm = _normalize_cl_phase(cl_ph) if league_code == "cl" else None
    if league_code != "cl" or cl_ph_norm == "league":
        add_stat(home, away, home_score, away_score, teams)
    add_match_result(
        home,
        away,
        league_code,
        home_score=home_score,
        away_score=away_score,
        day=round_num,
        cl_phase=cl_ph if league_code == "cl" else None,
        penalties_by_team=penalties_by_team,
    )
    save_result(league_code)

    if round_num:
        remove_skipped_match(
            home, away, round_num, league_code, cl_phase=cl_ph if league_code == 'cl' else None
        )

    print(f"✓ {home} {home_score}:{away_score} {away}")
    if penalties_by_team:
        print(f"  Пенальти (серия): {penalties_by_team}")

    # Ввод статистики игроков
    if with_stats and INPUT_PLAYER_STATS and interactive:
        stats_input = input("\nВвести статистику игроков? (y/n): ").lower().strip()
        if stats_input == 'y':
            db_tournament = 'cl' if league_code == 'cl' else 'league'
            input_match_stats(home, away, home_score, away_score, db_tournament)

    return True


def is_match_played(home, away, league_code, teams, cl_phase=None):
    """
    Проверить, был ли матч уже сыгран (журнал ``match_results``).

    Для ЛЧ несовпадение фазы слота календаря и записи в журнале учитывается в
    ``match_results.is_match_played``. Параметр ``teams`` оставлен для совместимости вызовов.
    """
    home = home.title()
    away = away.title()
    if league_code == "cl":
        cl_ph = cl_phase if cl_phase is not None else "knockout"
        return is_match_in_results(home, away, league_code, cl_phase=cl_ph)
    return is_match_in_results(home, away, league_code)


def is_match_skipped(home, away, league_code, round_num):
    """Проверить, пропущен ли матч"""
    skipped = load_skipped_matches()
    for skip in skipped:
        if (skip['home'] == home and skip['away'] == away and
                skip['tournament'] == league_code and skip['round'] == round_num):
            return True
    return False


def get_next_available_match(matches, league_code, round_num, teams):
    """
    Найти следующий матч, который:
    1. Не пропущен
    2. Не сыгран
    Возвращает (home, away, index) или (None, None, -1)
    """
    skipped = load_skipped_matches()

    for i, match_str in enumerate(matches):
        parts = match_str.split(';')
        home, away = parts[0], parts[1]
        cl_ph = (
            cl_phase_from_mixed_schedule_line(match_str)
            if league_code == 'cl'
            else None
        )

        # Проверяем, пропущен ли матч
        is_skipped_match = False
        for skip in skipped:
            if skip['round'] != round_num:
                continue
            if _skipped_matches_slot(skip, home, away, league_code, cl_ph):
                is_skipped_match = True
                break

        if is_skipped_match:
            continue

        # Проверяем, сыгран ли матч
        if is_match_played(home, away, league_code, teams, cl_phase=cl_ph):
            continue

        return home, away, i

    return None, None, -1


def count_remaining_matches(matches, league_code, round_num, teams):
    """Подсчитать количество не пропущенных и не сыгранных матчей"""
    skipped = load_skipped_matches()
    count = 0

    for match_str in matches:
        parts = match_str.split(';')
        home, away = parts[0], parts[1]
        cl_ph = (
            cl_phase_from_mixed_schedule_line(match_str)
            if league_code == 'cl'
            else None
        )

        # Проверяем пропущенные
        is_skipped_match = False
        for skip in skipped:
            if skip['round'] != round_num:
                continue
            if _skipped_matches_slot(skip, home, away, league_code, cl_ph):
                is_skipped_match = True
                break

        if is_skipped_match:
            continue

        # Проверяем сыгранные
        if is_match_played(home, away, league_code, teams, cl_phase=cl_ph):
            continue

        count += 1

    return count


def play_next_match():
    """Сыграть следующий матч по смешанному расписанию (матч-день)"""
    mixed_schedule = load_or_generate_mixed_schedule()
    day_num, match_str, home, away, league_code = find_next_match_in_schedule(mixed_schedule)

    if home is None:
        remaining = count_remaining_in_schedule(mixed_schedule)
        if remaining == 0:
            print("\n✓ Все матчи сезона сыграны!")
            show_option = input("Показать таблицы? (y/n): ").lower()
            if show_option == 'y':
                for key, league in LEAGUES.items():
                    show_table(league['teams'], league['name'], league_code=league['code'])
        else:
            print("\n⚠ Остались только пропущенные матчи. Используйте 'p' чтобы сыграть их.")
        return

    league = next((v for v in LEAGUES.values() if v['code'] == league_code), None)
    league_name = league['name'] if league else league_code
    remaining = count_remaining_in_schedule(mixed_schedule)

    print(f"\n{'=' * 40}")
    print(f"  Матч-день {day_num} | {league_name}")
    print(f"{'=' * 40}")
    print(f"  Матч: {home} - {away}")
    print(f"  Осталось матчей в сезоне: {remaining}")
    print("-" * 40)

    score_input = input("Счёт (например '2 1') или 's' для пропуска: ").strip()

    if score_input.lower() == 's':
        skip_ph = (
            cl_phase_from_mixed_schedule_line(match_str)
            if league_code == 'cl'
            else None
        )
        add_skipped_match(home, away, league_code, day_num, cl_phase=skip_ph)
        return

    try:
        home_score, away_score = map(int, score_input.split())
    except ValueError:
        print("Неверный формат счёта!")
        return

    slot_ph = (
        cl_phase_from_mixed_schedule_line(match_str)
        if league_code == 'cl'
        else None
    )
    process_match(
        home,
        away,
        home_score,
        away_score,
        league_code,
        round_num=day_num,
        cl_phase=slot_ph,
    )


def switch_league():
    """Переключить лигу"""
    global CURRENT_LEAGUE

    print("\n" + "="*40)
    print("  ВЫБОР ЛИГИ")
    print("="*40)
    for key, league in LEAGUES.items():
        marker = " <-- текущая" if league['code'] == CURRENT_LEAGUE else ""
        print(f"  {key} - {league['name']}{marker}")

    choice = input("\nВыберите лигу (1-6): ").strip()

    if choice in LEAGUES:
        CURRENT_LEAGUE = LEAGUES[choice]['code']
        print(f"\n✓ Переключено на: {LEAGUES[choice]['name']}")
        return True
    else:
        print("Неверный выбор")
        return False


def show_player_stats_menu():
    """Меню статистики игроков"""
    print("\n" + "=" * 40)
    print("  СТАТИСТИКА ИГРОКОВ")
    print("=" * 40)
    print("  1 - Топ бомбардиров")
    print("  2 - Топ ассистентов")
    print("  3 - Топ по Г+А")
    print("  4 - Голеадоры по командам (лига → все команды)")
    print("  5 - Топ-100 игроков (лига + ЛЧ, все лиги; без 0+0)")
    print("  0 - Назад")
    print("  К пунктам 1–3 добавьте + для суммы лига+ЛЧ (common.db), напр. 3+")

    choice = input("\nВыбор: ").strip()

    if choice == "4":
        show_team_goalscorers_interactive()
        return

    use_common_for_top = choice.endswith("+")
    if use_common_for_top:
        choice = choice[:-1].strip()

    if choice == "5":
        show_all_leagues_combined_full_list()
        return

    # Определяем турнир (БД) и код лиги (фильтр)
    league = get_current_league()
    league_code = league['code']

    if use_common_for_top:
        tournament = "common"
    else:
        tournament = "cl" if league_code == "cl" else "league"

    if choice == "1":
        show_top_scorers(tournament, league_code)
    elif choice == "2":
        show_top_assistants(tournament, league_code)
    elif choice == "3":
        show_top_ga(tournament, league_code)


def toggle_player_stats():
    """Переключить ввод статистики игроков"""
    global INPUT_PLAYER_STATS
    INPUT_PLAYER_STATS = not INPUT_PLAYER_STATS
    status = "включен" if INPUT_PLAYER_STATS else "выключен"
    print(f"✓ Ввод статистики игроков: {status}")


def show_status():
    """Показать статус (матч-день)"""
    mixed_schedule = load_or_generate_mixed_schedule()
    remaining_total = count_remaining_in_schedule(mixed_schedule)
    total = sum(len(d['matches']) for d in mixed_schedule)

    print("\n" + "="*50)
    print("  СТАТУС (МАТЧ-ДЕНЬ)")
    print("="*50)
    print(f"  Всего матчей: {total}, осталось: {remaining_total}")
    n_journal = count_recorded_matches()
    print(f"  Журнал сыгранных (файл): {n_journal} записей")
    print(f"    → {get_match_results_path()}")

    print("\n  Матчей сыграно по лигам:")
    for key, league in LEAGUES.items():
        teams = league['teams']
        played = sum(t.matches for t in teams.values()) // 2  # каждый матч = 2 команды
        marker = " <-- для таблицы" if league['code'] == CURRENT_LEAGUE else ""
        print(f"  {key}. {league['name']:<20} сыграно: {played}{marker}")

    skipped = load_skipped_matches()
    if skipped:
        print(f"\n  ⚠ Пропущенных матчей: {len(skipped)}")

    stats_status = "✓" if INPUT_PLAYER_STATS else "✗"
    print(f"\n  Ввод статистики игроков: {stats_status}")


def main():
    """Главный цикл программы"""
    global CURRENT_LEAGUE

    mixed_schedule = load_or_generate_mixed_schedule()
    migrated = migrate_match_results(mixed_schedule, get_teams_by_league)
    if migrated > 0:
        print(f"\n✓ Миграция: {migrated} сыгранных матчей перенесены из pickle")
    total_matches = sum(len(d['matches']) for d in mixed_schedule)
    remaining = count_remaining_in_schedule(mixed_schedule)

    print("\n" + "="*50)
    print("  ⚽ FOOTBALL MANAGER - Сезон 2024/25 ⚽")
    print("  Режим: матч-день (микс лиг)")
    print("="*50)

    while True:
        league = get_current_league()
        remaining = count_remaining_in_schedule(mixed_schedule)

        print(f"\n--- Матч-день | Осталось: {remaining} матчей ---")
        print("Команды:")
        print("  n - следующий матч")
        print("  m - ручной ввод матча")
        print("  t - таблица (текущей лиги)")
        print("  k - сетка плей-офф ЛЧ (HTML в браузере + текст в консоль)")
        print("  1-6 - выбрать лигу (для таблицы)")
        print("  s - пропущенные матчи")
        print("  p - сыграть пропущенный")
        print("  b - статистика игроков (бомбардиры и т.д.)")
        print("  a - статистика игроков по матчу (уже в журнале; только БД, не таблица лиги)")
        print("  x - вкл/выкл ввод статистики")
        print("  i - статус всех лиг")
        print("  j - журнал сыгранных матчей (match_results.json)")
        print("  v - просмотр расписания (лига / ЛЧ / туры; команда; все / оставшиеся / сыгранные)")
        print("  q - выход")

        option = input("\nВаш выбор: ").lower().strip()
        # Русская раскладка (физическая клавиша -> латиница): е->t, т->n, и->b, п->g, л->k (сетка)
        ru_to_en = {
            'е': 't', 'т': 'n', 'и': 'b', 'п': 'g', 'с': 's', 'м': 'v', 'й': 'q',
            'р': 'h', 'о': 'j', 'ф': 'a', 'л': 'k',
        }
        if len(option) == 1 and option in ru_to_en:
            option = ru_to_en[option]

        if option == 'q':
            print("\nДо свидания! ⚽")
            break

        elif option == 'n':
            play_next_match()

        elif option == 'm':
            print(f"\n  Ручной ввод матча ({league['name']})")
            home = input("Хозяева: ").strip()
            away = input("Гости: ").strip()
            score_input = input("Счёт (например '2 1'): ").strip()

            try:
                home_score, away_score = map(int, score_input.split())
                m_cl_ph = "knockout" if league["code"] == "cl" else None
                process_match(
                    home,
                    away,
                    home_score,
                    away_score,
                    league["code"],
                    cl_phase=m_cl_ph,
                )
            except ValueError:
                print("Неверный формат счёта!")

        elif option == 't':
            show_table(league['teams'], league['name'], league_code=league['code'])

        elif option == 'k':
            show_cl_knockout_bracket()

        elif option in ['1', '2', '3', '4', '5', '6']:
            CURRENT_LEAGUE = LEAGUES[option]['code']
            print(f"\n✓ Переключено на: {LEAGUES[option]['name']}")

        elif option == 's':
            show_skipped_matches()

        elif option == 'p':
            result = play_skipped_match()
            if result:
                process_match(
                    result['home'],
                    result['away'],
                    result['home_score'],
                    result['away_score'],
                    result['tournament'],
                    result['round'],
                    cl_phase=result.get('cl_phase'),
                )

        elif option == 'b':
            show_player_stats_menu()

        elif option == 'a':
            add_stats_to_match_interactive()

        elif option == 'x':
            toggle_player_stats()

        elif option == 'i':
            show_status()

        elif option == 'j':
            print("\n" + format_played_matches_report(limit=120))

        elif option == 'v':
            browse_schedule_interactive(load_or_generate_mixed_schedule)

        else:
            print("Неверная команда!")


if __name__ == '__main__':
    main()
