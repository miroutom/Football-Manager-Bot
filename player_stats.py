"""
Модуль для записи статистики игроков после матчей
"""
import contextlib
import io
from typing import Optional, Tuple

from utils.utils import (
    Base,
    defenders,
    forwards,
    get_engine,
    get_session,
    goalkeepers,
    midfielders,
)
from data.forward import Forward
from data.midfielder import Midfielder
from data.defender import Defender
from data.goalkeeper import Goalkeeper

# Команды по лигам для фильтрации (10 в каждой)
LEAGUE_TEAMS = {
    'rpl': [
        # В SQLite и журнале — «Цска», не «ЦСКА» (см. import_screen_extractions._TEAM_DB_CANON)
        "Цска", "Зенит", "Краснодар", "Локомотив", "Спартак", "Ростов",
        "Динамо", "Рубин", "Крылья Советов", "Урал"
    ],
    'eng': [
        "Сити", "Мю", "Ливерпуль", "Арсенал", "Астон Вилла", "Челси",
        "Тоттенхэм", "Ньюкасл", "Фулхэм", "Брайтон"
    ],
    'esp': [
        "Реал", "Барселона", "Атлетико", "Атлетик", "Реал Сосьедад", "Севилья",
        "Вильярреал", "Райо Вальекано", "Жирона", "Бетис"
    ],
    'ger': [
        "Бавария", "Дортмунд", "Байер", "Лейпциг", "Франкфурт", "Фрайбург",
        "Боруссия М", "Вольфсбург", "Штутгарт", "Хоффенхайм"
    ],
    'ita': [
        "Интер", "Милан", "Ювентус", "Наполи", "Аталанта", "Фиорентина",
        "Лацио", "Рома", "Торино", "Сассуоло"
    ],
}

# Названия лиг для заголовков
LEAGUE_NAMES = {
    'rpl': 'РПЛ',
    'eng': 'АПЛ',
    'esp': 'Ла Лига',
    'ger': 'Бундеслига',
    'ita': 'Серия А',
    'cl': 'Лига Чемпионов'
}


def get_position_type(position: str):
    """Определить тип позиции"""
    position = position.upper()
    if position in forwards:
        return 'forward'
    elif position in midfielders:
        return 'midfielder'
    elif position in defenders:
        return 'defender'
    else:
        return 'goalkeeper'


def get_player_class(position: str):
    """Получить класс игрока по позиции"""
    pos_type = get_position_type(position)
    if pos_type == 'forward':
        return Forward
    elif pos_type == 'midfielder':
        return Midfielder
    elif pos_type == 'defender':
        return Defender
    else:
        return Goalkeeper


def _norm_cmp(s: str) -> str:
    """Нормализация для сравнения имён и команд (регистр не важен)."""
    return (s or "").strip().lower()


def _team_score_in_match(team: str, match_for_cs: tuple) -> Optional[int]:
    """
    Голы указанной команды в матче (home, away, home_score, away_score).
    None — если кортеж битый или команда не хозяева и не гости.
    """
    if not match_for_cs or len(match_for_cs) < 4:
        return None
    ht, at, hs, away_s = match_for_cs[:4]
    t = _norm_cmp(team)
    if _norm_cmp(ht) == t:
        return int(hs)
    if _norm_cmp(at) == t:
        return int(away_s)
    return None


def _validate_goals_vs_team_score(
    team: str, goals: int, assists: int, match_for_cs: tuple
) -> Tuple[bool, Optional[str]]:
    """
    Один игрок за матч не может набрать больше голов, чем забила его команда,
    и больше «гол+пас» суммарно, чем голов у команды (нельзя обойти лимит двумя цифрами).
    """
    if goals < 0 or assists < 0:
        return False, "голы и передачи не могут быть отрицательными"
    if goals == 0 and assists == 0:
        return True, None
    ts = _team_score_in_match(team, match_for_cs)
    if ts is None:
        return (
            False,
            f"команда «{team}» не совпадает с хозяевами/гостями в match_for_cs "
            f"({match_for_cs[0]} — {match_for_cs[1]})",
        )
    if goals > ts:
        return False, f"голов {goals} при счёте команды {ts} в матче (макс. {ts})"
    if assists > ts:
        return False, f"передач {assists} при {ts} голах команды (макс. {ts})"
    if goals + assists > ts:
        return (
            False,
            f"Г+П {goals}+{assists}={goals + assists} при {ts} голах команды "
            f"(сумма не может превышать число голов команды в матче)",
        )
    return True, None


def find_player_by_name(session, name: str, team: str = None):
    """
    Найти игрока по имени во всех таблицах (без учёта регистра и отличий вроде «Ван Де Вен» vs «Ван де Вен»).
    Возвращает (player, position_type) или (None, None)
    """
    classes = [
        (Forward, 'forward'),
        (Midfielder, 'midfielder'),
        (Defender, 'defender'),
        (Goalkeeper, 'goalkeeper')
    ]
    want_name = _norm_cmp(name)
    want_team = _norm_cmp(team) if team else None

    for PlayerClass, pos_type in classes:
        try:
            for player in session.query(PlayerClass).all():
                if want_team is not None and _norm_cmp(player.team) != want_team:
                    continue
                if _norm_cmp(player.name) == want_name:
                    return player, pos_type
        except Exception:
            pass

    return None, None


def find_or_create_player(session, name: str, position: str, team: str):
    """Найти игрока или создать нового"""
    PlayerClass = get_player_class(position)
    pos_type = get_position_type(position)

    # Ищем игрока (без учёта регистра имени/команды)
    player = None
    for p in session.query(PlayerClass).all():
        if _norm_cmp(p.team) == _norm_cmp(team) and _norm_cmp(p.name) == _norm_cmp(name):
            player = p
            break

    if not player:
        # Создаём нового (не ищем в других командах — статистика только для указанного клуба)
        print(f"  + Создаю: {name} ({position}) - {team}")

        if pos_type == 'goalkeeper':
            player = PlayerClass(
                name=name, overall=0, team=team, position=position,
                matches=0, rating=0, clean_sheets=0, missed_goals=0,
                trophies=0, golden_balls=0, golden_boots=0, golden_gloves=0,
                golden_boys=0, nation=None, status=None,
            )
        elif pos_type == 'defender':
            player = PlayerClass(
                name=name, overall=0, team=team, position=position,
                matches=0, goals=0, assists=0, ga=0, rating=0,
                clean_sheets=0, trophies=0, golden_balls=0, golden_boots=0,
                golden_boys=0, nation=None, status=None,
            )
        else:
            player = PlayerClass(
                name=name, overall=0, team=team, position=position,
                matches=0, goals=0, assists=0, ga=0, rating=0,
                trophies=0, golden_balls=0, golden_boots=0, golden_boys=0,
                nation=None, status=None,
            )

        session.add(player)
        session.commit()

    return player


ALL_POSITION_CODES = tuple(
    dict.fromkeys(forwards + midfielders + defenders + goalkeepers)
)


def _strip_cs_and_goals(parts: list) -> tuple:
    """С конца: cs/сс/сухой, затем голы+ассисты (N+M или два числа или одно число)."""
    parts = list(parts)
    clean_sheet = False
    while parts and parts[-1].lower() in ('cs', 'сс', 'сухой'):
        clean_sheet = True
        parts.pop()
    if not parts:
        return 0, 0, clean_sheet, parts
    last = parts[-1]
    if '+' in last:
        try:
            g, a = last.split('+', 1)
            goals, assists = int(g), int(a)
            return goals, assists, clean_sheet, parts[:-1]
        except ValueError:
            pass
    if len(parts) >= 2 and parts[-1].isdigit() and parts[-2].isdigit():
        return int(parts[-2]), int(parts[-1]), clean_sheet, parts[:-2]
    if len(parts) >= 1 and parts[-1].isdigit():
        return int(parts[-1]), 0, clean_sheet, parts[:-1]
    return 0, 0, clean_sheet, parts


def print_roster_cheat_sheet(home_team: str, away_team: str, tournament: str = 'league') -> None:
    """Вывести составы обеих команд из БД (шпаргалка перед вводом статистики)."""
    session = get_session(tournament)

    def dump_team(title: str, team: str) -> None:
        print(f"\n── {title}: {team} ──")
        rows = []
        for cls in (Forward, Midfielder, Defender, Goalkeeper):
            try:
                for p in session.query(cls).filter_by(team=team).all():
                    rows.append((p.position, p.name))
            except Exception:
                pass
        if not rows:
            print("  (нет игроков в БД для этой команды)")
            return
        rows.sort(key=lambda x: (x[0], x[1]))
        for pos, name in rows:
            print(f"  {pos:<5}  {name}")

    dump_team("ХОЗЯЕВА", home_team)
    dump_team("ГОСТИ", away_team)
    print()


def add_player_stats(name: str, position: str, team: str, goals: int = 0, assists: int = 0,
                     clean_sheet: bool = False, tournament: str = 'league', auto_find: bool = False,
                     match_for_cs: tuple = None, create_if_missing: bool = False):
    """
    Добавить статистику игрока после матча.

    У каждого успешного вызова у игрока увеличивается ``matches`` на 1. При разборе состава
    со скринов нужен отдельный вызов на каждого сыгравшего, в том числе с 0+0.

    Ручной ввод через ``temporary`` / интерактив: команда «1» — только игроки из БД;
    «2» — новый игрок (в цикле передаётся ``create_if_missing=True``). Для программного вызова
    без БД-записи передай ``create_if_missing=True`` явно.

    match_for_cs: (home_team, away_team, home_score, away_score) — автосухой для защитников/вратарей
        и проверка: у полевых при ненулевых голах/передачах они не превышают голы команды в этом матче.
    """
    session = get_session(tournament)
    name = name.title()
    team = team.title()

    engine = get_engine(tournament)
    Base.metadata.create_all(engine)

    player = None

    if not create_if_missing:
        if position is None or auto_find:
            player, _ = find_player_by_name(session, name, team)
        else:
            cls = get_player_class(position.upper())
            player = session.query(cls).filter_by(name=name, team=team).first()
            if not player:
                player, _ = find_player_by_name(session, name, team)
        if not player:
            print(f"  ✗ Нет в БД: «{name}» ({team}) — проверь написание по шпаргалке выше.")
            return False
    else:
        if position is None or auto_find:
            player, _ = find_player_by_name(session, name, team)
            if player:
                position = player.position
            else:
                print(
                    f"  ✗ {name} не найден в БД. Укажи позицию, например: "
                    f"{name.split()[0] if name else 'игрок'} фрв {goals} {assists}  "
                    f"(или режим «2» — новый игрок)"
                )
                return False
        else:
            position = position.upper()

        if player is None:
            player = find_or_create_player(session, name, position, team)

    if not player:
        print(f"  ✗ Не удалось найти/создать игрока {name}")
        return False

    position = player.position
    pos_type = get_position_type(position)

    if match_for_cs and not clean_sheet:
        ht, at, hs, away_s = match_for_cs
        home_cs = away_s == 0
        away_cs = hs == 0
        tn = team.lower()
        if get_position_type(position) in ['defender', 'goalkeeper']:
            if (tn == ht.lower() and home_cs) or (tn == at.lower() and away_cs):
                clean_sheet = True

    if match_for_cs and (goals > 0 or assists > 0):
        ok_g, err_g = _validate_goals_vs_team_score(team, goals, assists, match_for_cs)
        if not ok_g:
            print(f"  ✗ {name} ({team}): {err_g}")
            return False

    player.matches += 1

    if pos_type in ['forward', 'midfielder', 'defender']:
        player.goals += goals
        player.assists += assists
        player.ga = player.goals + player.assists

    if pos_type in ['defender', 'goalkeeper'] and clean_sheet:
        player.clean_sheets += 1

    session.commit()

    ga_str = f" {goals} {assists}" if goals or assists else ""
    cs_str = " (CS)" if clean_sheet else ""
    disp = player.name
    print(f"  ✓ {disp} {position} {team}{ga_str}{cs_str}")

    return True


def apply_match_lineup(
    rows: list,
    tournament: str,
    match_for_cs: tuple = None,
    create_if_missing: bool = False,
) -> tuple:
    """
    Пройти весь состав матча одним списком: у каждого игрока будет ``matches += 1``.

    ``rows`` — список кортежей ``(имя, позиция, команда, голы, передачи)``.
    Для игрока без гола и передачи указывайте ``0, 0`` — матч всё равно засчитывается.

    По умолчанию игроки только из БД; чтобы создавать отсутствующих при батче со скринов,
    передай ``create_if_missing=True`` явно.

    Возвращает ``(успешно, ошибок)``.
    """
    ok = 0
    fail = 0
    for row in rows:
        if len(row) != 5:
            raise ValueError(f"Ожидается (имя, позиция, команда, голы, передачи), получено: {row!r}")
        name, position, team, goals, assists = row
        if add_player_stats(
            name, position, team, goals, assists,
            tournament=tournament,
            match_for_cs=match_for_cs,
            create_if_missing=create_if_missing,
        ):
            ok += 1
        else:
            fail += 1
    return ok, fail


def revert_player_stats(
    name: str,
    position: str,
    team: str,
    goals: int = 0,
    assists: int = 0,
    clean_sheet: bool = False,
    tournament: str = "league",
    match_for_cs: tuple = None,
) -> bool:
    """
    Обратная операция к add_player_stats: вычесть один матч и те же голы/передачи/сухой.
    Используется для отката ошибочного импорта по журналу без скринов.
    """
    session = get_session(tournament)
    name = name.title()
    team = team.title()

    engine = get_engine(tournament)
    Base.metadata.create_all(engine)

    cls = get_player_class(position.upper())
    player = session.query(cls).filter_by(name=name, team=team).first()
    if not player:
        player, _ = find_player_by_name(session, name, team)
    if not player:
        print(f"  ✗ Откат: нет в БД «{name}» ({team})")
        return False

    position = player.position
    pos_type = get_position_type(position)

    if match_for_cs and not clean_sheet:
        ht, at, hs, away_s = match_for_cs
        home_cs = away_s == 0
        away_cs = hs == 0
        tn = team.lower()
        if get_position_type(position) in ["defender", "goalkeeper"]:
            if (tn == ht.lower() and home_cs) or (tn == at.lower() and away_cs):
                clean_sheet = True

    player.matches -= 1
    if player.matches < 0:
        print(f"  ⚠ Откат: matches < 0 у {player.name}, зажато в 0")
        player.matches = 0

    if pos_type in ["forward", "midfielder", "defender"]:
        player.goals -= goals
        player.assists -= assists
        if player.goals < 0:
            player.goals = 0
        if player.assists < 0:
            player.assists = 0
        player.ga = player.goals + player.assists

    if pos_type in ["defender", "goalkeeper"] and clean_sheet:
        player.clean_sheets -= 1
        if player.clean_sheets < 0:
            player.clean_sheets = 0

    session.commit()
    cs_str = " (CS−)" if clean_sheet else ""
    ga_str = f" −{goals} −{assists}" if goals or assists else ""
    print(f"  ↩ {player.name} {position} {team}{ga_str}{cs_str}")
    return True


def revert_match_lineup(
    rows: list,
    tournament: str,
    match_for_cs: tuple = None,
) -> tuple:
    """Симметрично apply_match_lineup: вычитает те же записи."""
    ok = 0
    fail = 0
    for row in rows:
        if len(row) != 5:
            raise ValueError(f"Ожидается (имя, позиция, команда, голы, передачи), получено: {row!r}")
        name, position, team, goals, assists = row
        if revert_player_stats(
            name,
            position,
            team,
            goals,
            assists,
            tournament=tournament,
            match_for_cs=match_for_cs,
        ):
            ok += 1
        else:
            fail += 1
    return ok, fail


def parse_player_input(input_str: str, default_team: str = "", require_position: bool = False):
    """
    Парсинг строки игрока.

    Голы и ассисты (с конца строки): ``2+1`` или ``2 1`` или одно число ``2`` (= 2 гола, 0 передач).
    Затем опционально ``cs`` / ``сс`` / ``сухой``.

    Без позиции в строке — поиск в БД по текущей команде (auto_find).
    С позицией: ``Иванов ФРВ 1 0``, ``Ван Дейк ЦЗ 0 0 cs``.

    require_position: True для режима «новый игрок» — в строке должна быть позиция.
    """
    parts = input_str.strip().split()
    if not parts:
        return None

    goals, assists, clean_sheet, parts = _strip_cs_and_goals(parts)
    if not parts:
        print("  ✗ Имя игрока не указано")
        return None

    if len(parts) == 1:
        if require_position:
            print("  ✗ Укажи позицию, например: Иванов ФРВ 0 0")
            return None
        return {
            'name': parts[0].title(),
            'position': None,
            'team': default_team.title(),
            'goals': goals,
            'assists': assists,
            'clean_sheet': clean_sheet,
            'auto_find': True,
        }

    position = None
    position_index = -1
    for i, part in enumerate(parts):
        if part.upper() in ALL_POSITION_CODES:
            position = part.upper()
            position_index = i
            break

    if position is None:
        name = ' '.join(parts).title()
        if require_position:
            print("  ✗ Укажи позицию в строке, например: Новичок ЦП 1 0")
            return None
        return {
            'name': name,
            'position': None,
            'team': default_team.title(),
            'goals': goals,
            'assists': assists,
            'clean_sheet': clean_sheet,
            'auto_find': True,
        }

    name_parts = parts[:position_index]
    if not name_parts:
        print("  ✗ Имя игрока не указано")
        return None
    name = ' '.join(name_parts).title()
    extra = parts[position_index + 1 :]
    team = ' '.join(extra).title() if extra else default_team.title()
    if not team:
        print("  ✗ Укажи команду")
        return None

    return {
        'name': name,
        'position': position,
        'team': team,
        'goals': goals,
        'assists': assists,
        'clean_sheet': clean_sheet,
        'auto_find': False,
    }


def input_match_stats(home_team: str, away_team: str, home_score: int, away_score: int,
                      tournament: str = 'league'):
    """
    Интерактивный ввод статистики матча
    """
    print(f"\n{'='*50}")
    print(f"  СТАТИСТИКА: {home_team} {home_score}:{away_score} {away_team}")
    print(f"{'='*50}")
    print_roster_cheat_sheet(home_team, away_team, tournament)

    print("Формат: имя [позиция] голы ассисты   или   имя голы ассисты  (без «+», можно 2+1 по старому)")
    print("Примеры:")
    print("  Салах 2 1          Салах 2 0          холанд 2+1")
    print("  мартинез           ван дейк цз 0 0 cs")
    print("  новичок фрв 1 0    (режим «2» — новый игрок, позиция обязательна)")
    print("  Одно число в конце = только голы, 0 передач (напр. «игрок 1» → 1+0). Нужны 1+1: «игрок 1 1» или «игрок 1+1».")
    print("Режимы: 1 — только из БД (по умолчанию)  |  2 — новый игрок (создать при отсутствии)")
    print("Сторона: h/х — хозяева, a/г — гости")
    print("-" * 50)

    home_cs = away_score == 0
    away_cs = home_score == 0

    if home_cs:
        print(f"  💪 {home_team} - сухой матч!")
    if away_cs:
        print(f"  💪 {away_team} - сухой матч!")

    current_team = home_team
    mode_new = False

    while True:
        try:
            prompt = f"[{current_team}] {'[НОВЫЙ]' if mode_new else '[из БД]'} > "
            player_input = input(prompt).strip()
        except EOFError:
            break

        if not player_input:
            break

        low = player_input.lower()
        if low in ('1',):
            mode_new = False
            print("  → режим: только существующие в БД")
            continue
        if low in ('2',):
            mode_new = True
            print("  → режим: новый игрок (нужна позиция в строке)")
            continue

        if low in ('h', 'home', 'х', 'хозяева'):
            current_team = home_team
            print(f"  → {home_team}")
            continue
        if low in ('a', 'away', 'г', 'гости'):
            current_team = away_team
            print(f"  → {away_team}")
            continue

        line = player_input
        while True:
            pdata = parse_player_input(line, current_team, require_position=mode_new)
            if pdata is None:
                break

            # Одно имя без гол/пас, но команда забила — часто забывают цифры
            if (
                pdata.get("auto_find")
                and pdata.get("goals", 0) == 0
                and pdata.get("assists", 0) == 0
                and not pdata.get("clean_sheet")
            ):
                ts = _team_score_in_match(
                    pdata["team"],
                    (home_team, away_team, home_score, away_score),
                )
                if ts is not None and ts > 0:
                    hint = pdata["name"].split()[0]
                    print(
                        f"  ⚠ У «{pdata['team']}» в этом матче {ts} гол(а). "
                        f"Если у {hint} гол или передача — введи строку с цифрами "
                        f"(например: {hint} 1 0). Пустой Enter — оставить 0+0."
                    )
                    try:
                        fix = input("  > ").strip()
                    except EOFError:
                        fix = ""
                    if fix:
                        line = fix
                        continue

            pos = pdata.get('position')
            if pos and get_position_type(pos) in ['defender', 'goalkeeper']:
                if pdata['team'].lower() == home_team.lower() and home_cs:
                    pdata['clean_sheet'] = True
                elif pdata['team'].lower() == away_team.lower() and away_cs:
                    pdata['clean_sheet'] = True

            ok = add_player_stats(
                name=pdata['name'],
                position=pdata['position'],
                team=pdata['team'],
                goals=pdata['goals'],
                assists=pdata['assists'],
                clean_sheet=pdata['clean_sheet'],
                tournament=tournament,
                auto_find=pdata.get('auto_find', False),
                match_for_cs=(home_team, away_team, home_score, away_score),
                create_if_missing=mode_new,
            )

            if ok:
                break
            if mode_new:
                break

            print("  Повтори строку (как в шпаргалке) или Enter — отмена.")
            try:
                retry = input("  > ").strip()
            except EOFError:
                retry = ""
            if not retry:
                break
            line = retry

    print("✓ Статистика сохранена")


def format_roster_cheat_sheet_text(
    home_team: str, away_team: str, tournament: str = "league"
) -> str:
    """Текст шпаргалки составов (для Telegram), без print в консоль."""
    import contextlib
    import io

    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        print_roster_cheat_sheet(home_team, away_team, tournament)
    return buf.getvalue().strip()


def apply_stats_bot_line(
    line: str,
    *,
    home_team: str,
    away_team: str,
    home_score: int,
    away_score: int,
    tournament: str,
    current_team: str,
    mode_new: bool,
) -> tuple[str, str, bool]:
    """
    Одна строка ввода статистики для бота (без input()).
    Возвращает (текст ответа, текущая сторона для следующей строки, режим «новый игрок»).
    """
    import contextlib
    import io

    raw = (line or "").strip()
    if not raw:
        return (
            "Пустую строку пропускаем. Закончить — /done или кнопка «Готово».",
            current_team,
            mode_new,
        )

    low = raw.lower()
    if low in ("1",):
        return ("Режим: только игроки из БД.", current_team, False)
    if low in ("2",):
        return ("Режим: новый игрок (позиция в строке обязательна).", current_team, True)
    if low in ("h", "home", "х", "хозяева"):
        return (f"Сторона ввода: {home_team}", home_team, mode_new)
    if low in ("a", "away", "г", "гости"):
        return (f"Сторона ввода: {away_team}", away_team, mode_new)

    match_for_cs = (home_team, away_team, home_score, away_score)

    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        pdata = parse_player_input(raw, current_team, require_position=mode_new)
    head = buf.getvalue().strip()

    if pdata is None:
        return (head or "Не удалось разобрать строку.", current_team, mode_new)

    if (
        pdata.get("auto_find")
        and pdata.get("goals", 0) == 0
        and pdata.get("assists", 0) == 0
        and not pdata.get("clean_sheet")
    ):
        ts = _team_score_in_match(pdata["team"], match_for_cs)
        if ts is not None and ts > 0:
            hint = pdata["name"].split()[0]
            return (
                f"⚠ У «{pdata['team']}» в этом матче {ts} гол(а). "
                f"Если у игрока есть гол или передача — укажи цифры "
                f"(например: {hint} 1 0).",
                current_team,
                mode_new,
            )

    pos = pdata.get("position")
    home_cs = away_score == 0
    away_cs = home_score == 0
    if pos and get_position_type(pos) in ("defender", "goalkeeper"):
        if pdata["team"].lower() == home_team.lower() and home_cs:
            pdata["clean_sheet"] = True
        elif pdata["team"].lower() == away_team.lower() and away_cs:
            pdata["clean_sheet"] = True

    buf2 = io.StringIO()
    with contextlib.redirect_stdout(buf2):
        ok_add = add_player_stats(
            name=pdata["name"],
            position=pdata["position"],
            team=pdata["team"],
            goals=pdata["goals"],
            assists=pdata["assists"],
            clean_sheet=pdata["clean_sheet"],
            tournament=tournament,
            auto_find=pdata.get("auto_find", False),
            match_for_cs=match_for_cs,
            create_if_missing=mode_new,
        )
    out = buf2.getvalue().strip()
    if not ok_add:
        return (
            out or "Запись не выполнена. Проверь строку по шпаргалке.",
            current_team,
            mode_new,
        )
    return (out or "✓", current_team, mode_new)


def add_stats_to_match_interactive():
    """
    Ввод только статистики игроков (голы, передачи, сухие) в БД league_new / champions_league_new.

    Сценарий: матч уже учтён (журнал match_results, таблица лиги в pickle) — стата не вводилась.
    Турнирную таблицу команд и повторно счёт матча здесь не меняем; в pickle ничего не пишется.

    Если матча ещё не было в журнале — после ввода он будет добавлен в match_results.json.
    """
    print("\n" + "=" * 50)
    print("  СТАТИСТИКА ИГРОКОВ ПО УЖЕ СЫГРАННОМУ МАТЧУ")
    print("=" * 50)
    print("  Только голы/передачи в базу. Таблица лиги (pickle) не пересчитывается.")
    print("=" * 50)
    home = input("Хозяева: ").strip().title()
    away = input("Гости: ").strip().title()
    score_str = input("Счёт (например 1 1): ").strip()
    try:
        home_score, away_score = map(int, score_str.split())
    except ValueError:
        print("Неверный формат счёта!")
        return
    print("\nЛига: 1-РПЛ 2-АПЛ 3-ЛаЛига 4-СерияА 5-Бундеслига 6-ЛЧ")
    league_choice = input("Лига (1-6): ").strip()
    league_map = {'1': 'rpl', '2': 'eng', '3': 'esp', '4': 'ita', '5': 'ger', '6': 'cl'}
    league_code = league_map.get(league_choice, 'ita')
    tournament = 'cl' if league_code == 'cl' else 'league'
    input_match_stats(home, away, home_score, away_score, tournament)
    from match_results import (
        add_match_result,
        get_match_results_path,
        is_match_played as _is_in_journal,
    )
    if not _is_in_journal(home, away, league_code):
        add_match_result(
            home,
            away,
            league_code,
            home_score=home_score,
            away_score=away_score,
            cl_phase="knockout" if league_code == "cl" else None,
        )
        print(f"  (матч добавлен в журнал {get_match_results_path()})")


def show_top_scorers(tournament: str = 'league', league_code: str = None, limit: int = 20):
    """
    Показать топ бомбардиров

    Args:
        tournament: 'league', 'cl' или 'common' (сумма league_new + champions_league_new)
        league_code: 'eng', 'esp', 'ger', 'ita', 'cl' - для фильтрации по командам
        limit: количество игроков
    """
    if tournament in ('common', 'merged', 'all'):
        from utils.common_db import rebuild_common_database
        rebuild_common_database()
    session = get_session(tournament)

    all_players = []

    # Получаем список команд для фильтрации
    filter_teams = None
    if league_code and league_code != 'cl' and league_code in LEAGUE_TEAMS:
        filter_teams = [t.lower() for t in LEAGUE_TEAMS[league_code]]

    for PlayerClass in [Forward, Midfielder, Defender]:
        try:
            players = session.query(PlayerClass).filter(PlayerClass.goals > 0).all()
            for p in players:
                # Фильтруем по командам лиги
                if filter_teams and p.team.lower() not in filter_teams:
                    continue

                all_players.append({
                    'name': p.name,
                    'team': p.team,
                    'position': p.position,
                    'goals': p.goals,
                    'assists': p.assists,
                    'ga': p.ga,
                    'matches': p.matches
                })
        except:
            pass

    all_players.sort(key=lambda x: (-x['goals'], -x['assists']))

    # Заголовок с названием лиги
    base_name = LEAGUE_NAMES.get(league_code, 'Все лиги')
    league_name = (
        f"{base_name} (лига + ЛЧ)" if tournament in ('common', 'merged', 'all') else base_name
    )

    print(f"\n{'='*65}")
    print(f"  ТОП-{limit} БОМБАРДИРОВ - {league_name}")
    print(f"{'='*65}")
    print(f"{'#':<4} {'Игрок':<18} {'Команда':<15} {'Поз':<5} {'Г':<4} {'А':<4} {'Г+А':<5}")
    print("-"*65)

    if not all_players:
        print("  Нет данных")
    else:
        for i, p in enumerate(all_players[:limit], 1):
            print(f"{i:<4} {p['name']:<18} {p['team']:<15} {p['position']:<5} {p['goals']:<4} {p['assists']:<4} {p['ga']:<5}")


def show_top_assistants(tournament: str = 'league', league_code: str = None, limit: int = 20):
    """
    Показать топ ассистентов

    Args:
        tournament: 'league', 'cl' или 'common'
        league_code: 'eng', 'esp', 'ger', 'ita', 'cl' - для фильтрации по командам
        limit: количество игроков
    """
    if tournament in ('common', 'merged', 'all'):
        from utils.common_db import rebuild_common_database
        rebuild_common_database()
    session = get_session(tournament)

    all_players = []

    filter_teams = None
    if league_code and league_code != 'cl' and league_code in LEAGUE_TEAMS:
        filter_teams = [t.lower() for t in LEAGUE_TEAMS[league_code]]

    for PlayerClass in [Forward, Midfielder, Defender]:
        try:
            players = session.query(PlayerClass).filter(PlayerClass.assists > 0).all()
            for p in players:
                if filter_teams and p.team.lower() not in filter_teams:
                    continue

                all_players.append({
                    'name': p.name,
                    'team': p.team,
                    'position': p.position,
                    'goals': p.goals,
                    'assists': p.assists,
                    'ga': p.ga,
                    'matches': p.matches
                })
        except:
            pass

    all_players.sort(key=lambda x: (-x['assists'], -x['goals']))

    base_name = LEAGUE_NAMES.get(league_code, 'Все лиги')
    league_name = (
        f"{base_name} (лига + ЛЧ)" if tournament in ('common', 'merged', 'all') else base_name
    )

    print(f"\n{'='*65}")
    print(f"  ТОП-{limit} АССИСТЕНТОВ - {league_name}")
    print(f"{'='*65}")
    print(f"{'#':<4} {'Игрок':<18} {'Команда':<15} {'Поз':<5} {'А':<4} {'Г':<4} {'Г+А':<5}")
    print("-"*65)

    if not all_players:
        print("  Нет данных")
    else:
        for i, p in enumerate(all_players[:limit], 1):
            print(f"{i:<4} {p['name']:<18} {p['team']:<15} {p['position']:<5} {p['assists']:<4} {p['goals']:<4} {p['ga']:<5}")


def show_top_ga(tournament: str = 'league', league_code: str = None, limit: int = 20):
    """
    Показать топ по Г+А

    Args:
        tournament: 'league', 'cl' или 'common'
        league_code: 'eng', 'esp', 'ger', 'ita', 'cl' - для фильтрации по командам
        limit: количество игроков
    """
    if tournament in ('common', 'merged', 'all'):
        from utils.common_db import rebuild_common_database
        rebuild_common_database()
    session = get_session(tournament)

    all_players = []

    filter_teams = None
    if league_code and league_code != 'cl' and league_code in LEAGUE_TEAMS:
        filter_teams = [t.lower() for t in LEAGUE_TEAMS[league_code]]

    for PlayerClass in [Forward, Midfielder, Defender]:
        try:
            players = session.query(PlayerClass).filter(PlayerClass.ga > 0).all()
            for p in players:
                if filter_teams and p.team.lower() not in filter_teams:
                    continue

                all_players.append({
                    'name': p.name,
                    'team': p.team,
                    'position': p.position,
                    'goals': p.goals,
                    'assists': p.assists,
                    'ga': p.ga,
                    'matches': p.matches
                })
        except:
            pass

    all_players.sort(key=lambda x: (-x['ga'], -x['goals']))

    base_name = LEAGUE_NAMES.get(league_code, 'Все лиги')
    league_name = (
        f"{base_name} (лига + ЛЧ)" if tournament in ('common', 'merged', 'all') else base_name
    )

    print(f"\n{'='*65}")
    print(f"  ТОП-{limit} ПО Г+А - {league_name}")
    print(f"{'='*65}")
    print(f"{'#':<4} {'Игрок':<18} {'Команда':<15} {'Поз':<5} {'Г+А':<5} {'Г':<4} {'А':<4}")
    print("-"*65)

    if not all_players:
        print("  Нет данных")
    else:
        for i, p in enumerate(all_players[:limit], 1):
            print(f"{i:<4} {p['name']:<18} {p['team']:<15} {p['position']:<5} {p['ga']:<5} {p['goals']:<4} {p['assists']:<4}")


def show_all_leagues_combined_full_list(limit: int = 100) -> None:
    """
    Топ игроков из объединённой БД (лига + ЛЧ, все лиги), без строк 0+0.
    Столбцы статистики всегда в порядке: Г, А, Г+А.
    """
    from utils.common_db import rebuild_common_database

    rebuild_common_database()
    session = get_session("common")
    rows = []
    for PlayerClass in (Forward, Midfielder, Defender):
        for p in session.query(PlayerClass).all():
            g = int(p.goals or 0)
            a = int(p.assists or 0)
            ga = int(getattr(p, "ga", None) or (g + a))
            if g == 0 and a == 0:
                continue
            rows.append(
                {
                    "name": p.name,
                    "team": p.team,
                    "position": p.position,
                    "matches": int(p.matches or 0),
                    "goals": g,
                    "assists": a,
                    "ga": ga,
                }
            )

    print("\n" + "=" * 76)
    print(
        f"  ТОП-{limit} — лига + ЛЧ, все лиги "
        f"(с голом или передачей; кандидатов: {len(rows)})"
    )
    print("=" * 76)
    print("  Сортировка: 1 — по голам  |  2 — по голевым передачам  |  3 — по Г+А")
    ch = input("  Выбор (1/2/3, Enter = 1): ").strip()
    if ch == "2":
        rows.sort(key=lambda x: (-x["assists"], -x["goals"], x["name"].lower()))
    elif ch == "3":
        rows.sort(key=lambda x: (-x["ga"], -x["goals"], x["name"].lower()))
    else:
        rows.sort(key=lambda x: (-x["goals"], -x["assists"], x["name"].lower()))

    rows = rows[:limit]

    print()
    hdr = (
        f"{'#':<4} {'Игрок':<20} {'Команда':<18} {'Поз':<5} "
        f"{'И':>4} {'Г':>4} {'А':>4} {'Г+А':>5}"
    )
    print(hdr)
    print("-" * 76)
    for i, p in enumerate(rows, 1):
        print(
            f"{i:<4} {p['name']:<20} {p['team']:<18} {p['position']:<5} "
            f"{p['matches']:>4} {p['goals']:>4} {p['assists']:>4} {p['ga']:>5}"
        )
    print("-" * 76)


def _team_name_as_in_db(team: str) -> str:
    """Имя команды как в SQLite (расхождения LEAGUE_TEAMS ↔ БД)."""
    if (team or "").strip() == "ЦСКА":
        return "Цска"
    return team


def _find_team_in_standings(teams_dict: Optional[dict], team_name: str):
    """Словарь команд из pickle (teams.py): ключ — имя команды."""
    if not teams_dict or not team_name:
        return None
    if team_name in teams_dict:
        return teams_dict[team_name]
    key = (team_name or "").strip()
    for k, t in teams_dict.items():
        if k.lower() == key.lower():
            return t
    return None


def show_team_goalscorers_table(
    team: str,
    tournament: str = "league",
    standings_dict: Optional[dict] = None,
) -> None:
    """
    Игроки команды с голом или передачей: И (матчи в БД), Г, А, Г+А по убыванию Г+А.
    Учитываются нападающие, полузащитники и защитники (голы > 0 или передачи > 0).
    Внизу: сумма голов игроков в списке, ЗМ по таблице и число матчей команды (pickle).
    """
    team = _team_name_as_in_db(team)
    session = get_session(tournament)
    rows = []
    for PlayerClass in (Forward, Midfielder, Defender):
        for p in session.query(PlayerClass).filter_by(team=team).all():
            g = int(p.goals or 0)
            a = int(p.assists or 0)
            if g <= 0 and a <= 0:
                continue
            ga = int(getattr(p, "ga", None) or (g + a))
            rows.append(
                {
                    "name": p.name,
                    "pos": p.position,
                    "matches": int(p.matches or 0),
                    "g": g,
                    "a": a,
                    "ga": ga,
                }
            )
    rows.sort(key=lambda x: (-x["ga"], -x["g"], x["name"].lower()))

    width = 68
    sep = "=" * width
    tname = "Лига Чемпионов" if tournament in ("cl", "champ_league") else "национальные лиги"
    print(f"\n{sep}")
    print(f"  Голы и передачи: {team} ({tname})")
    print(sep)
    if not rows:
        print("  Нет игроков с голами или передачами в этой базе.")
    else:
        print(f"{'#':<4} {'Игрок':<18} {'Поз':<6} {'И':>4} {'Г':>4} {'А':>4} {'Г+А':>5}")
        print("-" * width)
        for i, r in enumerate(rows, 1):
            print(
                f"{i:<4} {r['name']:<18} {r['pos']:<6} {r['matches']:>4} "
                f"{r['g']:>4} {r['a']:>4} {r['ga']:>5}"
            )

    sum_goals = sum(r["g"] for r in rows)
    st = _find_team_in_standings(standings_dict, team)
    if st is not None:
        table_gf = int(getattr(st, "scored", 0) or 0)
        table_str = str(table_gf)
        table_matches = int(getattr(st, "matches", 0) or 0)
        matches_str = str(table_matches)
    else:
        table_str = "—"
        matches_str = "—"
    print(
        f"  Итог: {sum_goals}    Итог по таблице: {table_str}    "
        f"Матчи по таблице: {matches_str}"
    )
    print(f"{sep}\n")


def show_team_goalscorers_interactive() -> None:
    """Интерактив: лига (1–6) → голеадоры по всем командам этой лиги подряд."""
    print("\n" + "=" * 50)
    print("  ГОЛЫ И ПЕРЕДАЧИ ПО КОМАНДАМ (гол или передача)")
    print("=" * 50)
    print("Лига: 1-РПЛ  2-АПЛ  3-Ла Лига  4-Серия А  5-Бундеслига  6-ЛЧ")
    league_choice = input("Лига (1-6): ").strip()
    league_map = {"1": "rpl", "2": "eng", "3": "esp", "4": "ita", "5": "ger", "6": "cl"}
    league_code = league_map.get(league_choice)
    if not league_code:
        print("Неверный выбор лиги.")
        return
    tournament = "cl" if league_code == "cl" else "league"
    import teams as teams_mod

    # ЛЧ — 30 участников из pickle, не входят в LEAGUE_TEAMS (только нац. лиги по 10).
    if league_code == "cl":
        teams = sorted(teams_mod.teams_champ_league.keys())
    else:
        teams = sorted(LEAGUE_TEAMS[league_code])
    league_name = LEAGUE_NAMES.get(league_code, league_code)

    standings_by_code = {
        "rpl": teams_mod.teams_rpl,
        "eng": teams_mod.teams_eng,
        "esp": teams_mod.teams_spain,
        "ita": teams_mod.teams_italy,
        "ger": teams_mod.teams_germany,
        "cl": teams_mod.teams_champ_league,
    }
    standings = standings_by_code.get(league_code)

    print(f"\n{'=' * 60}")
    print(f"  {league_name} — голеадоры всех команд")
    print(f"{'=' * 60}\n")
    for team in teams:
        show_team_goalscorers_table(team, tournament, standings)


def format_team_goalscorers_table_str(
    team: str,
    tournament: str = "league",
    standings_dict: Optional[dict] = None,
) -> str:
    """Текст блока «голеадоры команды» — как show_team_goalscorers_table, для бота."""
    import contextlib
    import io

    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        show_team_goalscorers_table(team, tournament, standings_dict)
    return buf.getvalue()


def format_team_goalscorers_league_report(league_code: str) -> str:
    """Все команды лиги подряд — как пункт «b»→4 в консоли."""
    tournament = "cl" if league_code == "cl" else "league"
    import teams as teams_mod

    if league_code == "cl":
        teams = sorted(teams_mod.teams_champ_league.keys())
    else:
        teams = sorted(LEAGUE_TEAMS[league_code])
    league_name = LEAGUE_NAMES.get(league_code, league_code)

    standings_by_code = {
        "rpl": teams_mod.teams_rpl,
        "eng": teams_mod.teams_eng,
        "esp": teams_mod.teams_spain,
        "ita": teams_mod.teams_italy,
        "ger": teams_mod.teams_germany,
        "cl": teams_mod.teams_champ_league,
    }
    standings = standings_by_code.get(league_code)

    parts = [
        "\n" + "=" * 60,
        f"  {league_name} — голеадоры всех команд",
        "=" * 60 + "\n",
    ]
    for team in teams:
        parts.append(format_team_goalscorers_table_str(team, tournament, standings))
    return "".join(parts)


def format_all_leagues_combined_list_str(limit: int = 100, sort_key: int = 1) -> str:
    """
    Топ игроков common.db — как пункт «b»→5.
    sort_key: 1 — голы, 2 — передачи, 3 — Г+А.
    """
    from utils.common_db import rebuild_common_database

    rebuild_common_database()
    session = get_session("common")
    rows = []
    for PlayerClass in (Forward, Midfielder, Defender):
        for p in session.query(PlayerClass).all():
            g = int(p.goals or 0)
            a = int(p.assists or 0)
            ga = int(getattr(p, "ga", None) or (g + a))
            if g == 0 and a == 0:
                continue
            rows.append(
                {
                    "name": p.name,
                    "team": p.team,
                    "position": p.position,
                    "matches": int(p.matches or 0),
                    "goals": g,
                    "assists": a,
                    "ga": ga,
                }
            )

    n_cand = len(rows)

    if sort_key == 2:
        rows.sort(key=lambda x: (-x["assists"], -x["goals"], x["name"].lower()))
    elif sort_key == 3:
        rows.sort(key=lambda x: (-x["ga"], -x["goals"], x["name"].lower()))
    else:
        rows.sort(key=lambda x: (-x["goals"], -x["assists"], x["name"].lower()))

    rows = rows[:limit]

    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        print("\n" + "=" * 76)
        print(
            f"  ТОП-{limit} — лига + ЛЧ, все лиги "
            f"(с голом или передачей; кандидатов: {n_cand})"
        )
        print("=" * 76)
        hdr = (
            f"{'#':<4} {'Игрок':<20} {'Команда':<18} {'Поз':<5} "
            f"{'И':>4} {'Г':>4} {'А':>4} {'Г+А':>5}"
        )
        print()
        print(hdr)
        print("-" * 76)
        for i, p in enumerate(rows, 1):
            print(
                f"{i:<4} {p['name']:<20} {p['team']:<18} {p['position']:<5} "
                f"{p['matches']:>4} {p['goals']:>4} {p['assists']:>4} {p['ga']:>5}"
            )
        print("-" * 76)
    return buf.getvalue().strip()
