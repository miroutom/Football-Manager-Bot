# -*- coding: utf-8 -*-
"""
Генератор рандомного расписания.
- Каждая лига: два круга (каждый с каждым)
- Матч-день: микс матчей из разных лиг (пример: 1 РПЛ, 1 АПЛ, 1 Испания, 2 Италия, 2 ЛЧ, 2 Германия)
- К середине и концу сезона у всех команд в лиге одинаковое кол-во матчей (автоматически при round-robin)
"""
import random
from itertools import combinations
from config.leagues_config import ALL_LEAGUES, rpl, england, spain, italy, germany


def round_robin_matches(teams: list) -> list:
    """
    Генерация матчей одного круга (каждый с каждым).
    Возвращает список туров, каждый тур — список пар (home, away).
    """
    n = len(teams)
    if n % 2:
        teams = teams + [None]  # виртуальный "выходной"
        n += 1
    # Круговая система
    fixed = teams[0]
    rest = teams[1:]
    rounds = []
    for _ in range(n - 1):
        round_matches = []
        round_matches.append((rest[0], fixed))  # fixed всегда играет с первым из rest
        for i in range(1, n // 2):
            round_matches.append((rest[i], rest[n - 1 - i]))
        rounds.append(round_matches)
        # Ротация
        rest = [rest[-1]] + rest[:-1]
    # Убираем None
    result = []
    for r in rounds:
        clean = []
        for h, a in r:
            if h is not None and a is not None:
                clean.append((h, a))
        result.append(clean)
    return result


def double_round_robin(teams: list) -> list:
    """Два круга: сначала все дома, потом реванши."""
    first = round_robin_matches(teams)
    second = []
    for r in first:
        rev = [(a, h) for h, a in r]
        second.append(rev)
    return first + second


def generate_league_schedule(teams: list, league_code: str) -> dict:
    """
    Генерация расписания лиги (формат как в table/schedule.py).
    teams: список названий (lowercase), будут преобразованы в Title
    Возвращает {1: ['Home;Away;code', ...], 2: [...], ...}
    """
    teams_title = [t.title() for t in teams]
    rounds = double_round_robin(teams_title)
    schedule = {}
    for i, r in enumerate(rounds, 1):
        schedule[i] = [f"{h};{a};{league_code}" for h, a in r]
    return schedule


def generate_mixed_match_days(
    league_schedules: dict,
    slots_per_day: dict = None,
    shuffle=True
) -> list:
    """
    Генерация матч-дней с миксом лиг.
    В одном матч-дне каждая команда играет не более одного матча.
    """
    if slots_per_day is None:
        slots_per_day = {'rpl': 1, 'eng': 1, 'esp': 1, 'ita': 2, 'cl': 2, 'ger': 2}

    max_rounds = max(
        len(sched) for sched in league_schedules.values() if sched
    )
    match_days = []

    # Сначала domestic лиги (не пересекаются), потом ЛЧ (команды из всех лиг)
    league_order = [c for c in slots_per_day.keys() if c != 'cl'] + ['cl']

    for round_num in range(1, max_rounds + 1):
        day_matches = []
        teams_used_today = set()

        for league_code in league_order:
            slots = slots_per_day.get(league_code, 0)
            if slots <= 0:
                continue
            sched = league_schedules.get(league_code, {})
            matches = sched.get(round_num, [])
            if shuffle:
                matches = list(matches)
                random.shuffle(matches)

            added = 0
            for m in matches:
                if added >= slots:
                    break
                parts = m.split(';')
                if len(parts) < 3:
                    continue
                home, away = parts[0], parts[1]
                if home in teams_used_today or away in teams_used_today:
                    continue
                day_matches.append(m)
                teams_used_today.add(home)
                teams_used_today.add(away)
                added += 1

        if shuffle:
            random.shuffle(day_matches)
        if day_matches:
            match_days.append(day_matches)
    return match_days


def generate_cl_league_phase(cl_teams: list, n_matches_per_team: int = 8) -> dict:
    """
    Генерация лиговой фазы ЛЧ (30 команд, 8 матчей на команду).
    Используем первые 8 туров круглой системы — каждый с каждым не играет,
    но каждая команда играет ровно 8 матчей с разными соперниками.
    """
    teams = [t.title() if isinstance(t, str) else t for t in cl_teams]
    # Полный круг — 29 туров для 30 команд. Берём первые 8.
    full_rounds = round_robin_matches(teams)
    schedule = {}
    for i, r in enumerate(full_rounds[:n_matches_per_team], 1):
        schedule[i] = [f"{h};{a};cl" for h, a in r]
    return schedule


def build_full_schedule(cl_teams: list = None) -> dict:
    """
    Построить полное расписание всех лиг + ЛЧ.
    cl_teams: список из 30 команд для ЛЧ (если None — заглушка)
    Возвращает {'rpl': {...}, 'eng': {...}, ..., 'cl': {...}}
    """
    from config.leagues_config import rpl, england, spain, italy, germany

    result = {}
    result['rpl'] = generate_league_schedule(rpl, 'rpl')
    result['eng'] = generate_league_schedule(england, 'eng')
    result['esp'] = generate_league_schedule(spain, 'esp')
    result['ita'] = generate_league_schedule(italy, 'ita')
    result['ger'] = generate_league_schedule(germany, 'ger')

    if cl_teams is None:
        from champions_league.cl_format import get_cl_participants
        cl_teams = get_cl_participants()
    result['cl'] = generate_cl_league_phase(cl_teams)

    return result
