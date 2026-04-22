"""
Модуль для работы с пропущенными матчами
"""
import json
import os

from utils.utils import PROJECT_ROOT
SKIPPED_FILE = os.path.join(PROJECT_ROOT, 'skipped_matches.json')


def load_skipped_matches():
    """Загрузить список пропущенных матчей"""
    if os.path.exists(SKIPPED_FILE):
        try:
            with open(SKIPPED_FILE, 'r', encoding='utf-8') as f:
                return json.load(f)
        except:
            return []
    return []


def save_skipped_matches(matches):
    """Сохранить список пропущенных матчей"""
    with open(SKIPPED_FILE, 'w', encoding='utf-8') as f:
        json.dump(matches, f, ensure_ascii=False, indent=2)


def add_skipped_match(home, away, tournament, round_num, cl_phase=None):
    """Добавить матч в пропущенные. Для ЛЧ: ``cl_phase`` ``league`` / ``knockout``."""
    matches = load_skipped_matches()

    def _same_slot(m):
        if m['home'] != home or m['away'] != away or m['tournament'] != tournament:
            return False
        if tournament != 'cl':
            return True
        mp = m.get('cl_phase') or 'knockout'
        ep = cl_phase or 'knockout'
        return mp == ep

    # Проверяем, нет ли уже такого матча
    for m in matches:
        if _same_slot(m):
            print(f"Матч {home} - {away} уже в списке пропущенных")
            return False

    row = {
        'home': home,
        'away': away,
        'tournament': tournament,
        'round': round_num,
    }
    if tournament == 'cl':
        row['cl_phase'] = cl_phase or 'knockout'
    matches.append(row)

    save_skipped_matches(matches)
    print(f"✓ Матч {home} - {away} (тур {round_num}) добавлен в пропущенные")
    return True


def remove_skipped_match(home, away, round_num=None, tournament=None, cl_phase=None):
    """Удалить матч из пропущенных по (home, away, tournament); для ЛЧ — с фазой."""
    matches = load_skipped_matches()

    def to_remove(m):
        if m['home'] != home or m['away'] != away:
            return False
        if tournament is not None and m.get('tournament') != tournament:
            return False
        if tournament == 'cl':
            mp = m.get('cl_phase') or 'knockout'
            ep = cl_phase or 'knockout'
            if mp != ep:
                return False
        return True

    new_matches = [m for m in matches if not to_remove(m)]

    if len(new_matches) < len(matches):
        save_skipped_matches(new_matches)
        return True
    return False


def cleanup_old_skipped_matches(mixed_schedule):
    """
    Удалить из пропущенных матчи, которых нет в текущем расписании
    (остатки от старых розыгрышей с другими командами/лигами)
    """
    valid = set()
    for day_data in mixed_schedule:
        for match_str in day_data.get('matches', []):
            parts = match_str.split(';')
            if len(parts) >= 3:
                home, away, league = parts[0], parts[1], parts[2]
                valid.add((home, away, league))

    skipped = load_skipped_matches()
    before = len(skipped)
    filtered = [m for m in skipped if (m['home'], m['away'], m['tournament']) in valid]
    removed = before - len(filtered)

    if removed > 0:
        save_skipped_matches(filtered)
        return removed
    return 0


def show_skipped_matches():
    """Показать все пропущенные матчи"""
    matches = load_skipped_matches()

    if not matches:
        print("\n✓ Нет пропущенных матчей")
        return

    print(f"\n{'='*50}")
    print("  ПРОПУЩЕННЫЕ МАТЧИ")
    print(f"{'='*50}")

    # Группируем по лигам
    leagues = {
        'rpl': 'РПЛ',
        'eng': 'АПЛ',
        'esp': 'Ла Лига',
        'ger': 'Бундеслига',
        'ita': 'Серия А',
        'cl': 'Лига Чемпионов'
    }

    by_league = {}
    for m in matches:
        league = m['tournament']
        if league not in by_league:
            by_league[league] = []
        by_league[league].append(m)

    idx = 1
    for league_code, league_matches in by_league.items():
        league_name = leagues.get(league_code, league_code)
        print(f"\n{league_name}:")
        print("-" * 40)

        # Сортируем по туру
        league_matches.sort(key=lambda x: x['round'])

        for m in league_matches:
            print(f"  {idx}. Тур {m['round']}: {m['home']} - {m['away']}")
            idx += 1


def list_skipped_matches_ordered():
    """
    Плоский список отложенных матчей в том же порядке, что в play_skipped_match()
    (группировка по лигам в порядке первого появления в файле, внутри — по туру).
    """
    matches = load_skipped_matches()
    if not matches:
        return []
    by_league = {}
    for m in matches:
        league = m['tournament']
        if league not in by_league:
            by_league[league] = []
        by_league[league].append(m)
    numbered = []
    for _league_code, league_matches in by_league.items():
        league_matches.sort(key=lambda x: x['round'])
        numbered.extend(league_matches)
    return numbered


def play_skipped_match():
    """
    Выбрать и сыграть пропущенный матч
    Возвращает данные матча или None
    """
    matches = load_skipped_matches()

    if not matches:
        print("\n✓ Нет пропущенных матчей")
        return None

    print(f"\n{'='*50}")
    print("  ВЫБЕРИТЕ МАТЧ ДЛЯ ИГРЫ")
    print(f"{'='*50}")

    # Группируем по лигам для красивого вывода
    leagues = {
        'rpl': 'РПЛ',
        'eng': 'АПЛ',
        'esp': 'Ла Лига',
        'ger': 'Бундеслига',
        'ita': 'Серия А',
        'cl': 'Лига Чемпионов'
    }

    # Создаём нумерованный список
    numbered_matches = []
    idx = 1

    by_league = {}
    for m in matches:
        league = m['tournament']
        if league not in by_league:
            by_league[league] = []
        by_league[league].append(m)

    for league_code, league_matches in by_league.items():
        league_name = leagues.get(league_code, league_code)
        print(f"\n{league_name}:")
        print("-" * 40)

        league_matches.sort(key=lambda x: x['round'])

        for m in league_matches:
            print(f"  {idx}. Тур {m['round']}: {m['home']} - {m['away']}")
            numbered_matches.append(m)
            idx += 1

    print(f"\n  0. Отмена")
    print("-" * 50)

    choice = input("Номер матча (или 0 для отмены): ").strip()

    if choice == '0' or choice == '':
        print("Отменено")
        return None

    try:
        match_idx = int(choice) - 1
        if match_idx < 0 or match_idx >= len(numbered_matches):
            print("Неверный номер матча!")
            return None
    except ValueError:
        print("Введите число!")
        return None

    selected = numbered_matches[match_idx]

    print(f"\n{'='*40}")
    print(f"  {selected['home']} - {selected['away']}")
    print(f"  Тур {selected['round']}")
    print(f"{'='*40}")

    score_input = input("Счёт (например '2 1') или 's' для пропуска: ").strip()

    # Если хотят пропустить - просто выходим
    if score_input.lower() == 's':
        print("Матч остаётся в пропущенных")
        return None

    try:
        home_score, away_score = map(int, score_input.split())
    except ValueError:
        print("Неверный формат счёта!")
        return None

    # Удаляем из пропущенных
    remove_skipped_match(
        selected['home'],
        selected['away'],
        selected['round'],
        selected.get('tournament'),
        cl_phase=selected.get('cl_phase') if selected.get('tournament') == 'cl' else None,
    )

    out = {
        'home': selected['home'],
        'away': selected['away'],
        'home_score': home_score,
        'away_score': away_score,
        'tournament': selected['tournament'],
        'round': selected['round'],
    }
    if selected.get('tournament') == 'cl':
        out['cl_phase'] = selected.get('cl_phase') or 'knockout'
    return out


def clear_skipped_matches():
    """Очистить все пропущенные матчи"""
    save_skipped_matches([])
    print("✓ Все пропущенные матчи удалены")
