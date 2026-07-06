"""
Модуль для записи статистики игроков после матчей
"""
from __future__ import annotations

import contextlib
import io
from typing import Any, Optional, Tuple

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


def national_league_code_for_team(team: str) -> str | None:
    """Код нац. лиги (rpl, eng, …): реестр команд, иначе LEAGUE_TEAMS."""
    try:
        from utils.team_registry import league_code_for_team

        code = league_code_for_team(team)
        if code:
            return code
    except Exception:
        pass
    t = _norm_cmp(team)
    if not t:
        return None
    for code, tlist in LEAGUE_TEAMS.items():
        for tname in tlist:
            if _norm_cmp(tname) == t:
                return code
    return None


def infer_league_code_for_stats(
    home_team: str, away_team: str, tournament: str
) -> str:
    """По сторонам матча и виду турнира — код лиги (для дисциплины: rpl, eng, … или cl)."""
    if (tournament or "") == "cl" or (tournament or "") == "champ_league":
        return "cl"
    for code, tlist in LEAGUE_TEAMS.items():
        h = _norm_cmp(home_team)
        a = _norm_cmp(away_team)
        for tname in tlist:
            tn = _norm_cmp(tname)
            if tn == h or tn == a:
                return code
    return "rpl"


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


def team_match_contrib_from_session_acc(
    session_acc: dict | None, team: str
) -> tuple[int, int]:
    """Сумма голов и передач по команде за матч из накопленной сессии бота."""
    if not session_acc:
        return 0, 0
    tg = ta = 0
    want = _norm_cmp(team)
    for acc in session_acc.values():
        if _norm_cmp(acc.get("team") or "") != want:
            continue
        tg += int(acc.get("goals") or 0)
        ta += int(acc.get("assists") or 0)
    return tg, ta


class MatchTeamStatBudget:
    """Накопленные голы и передачи команд за один матч (ввод по строкам / батч)."""

    __slots__ = ("_goals", "_assists")

    def __init__(self) -> None:
        self._goals: dict[str, int] = {}
        self._assists: dict[str, int] = {}

    @staticmethod
    def _k(team: str) -> str:
        return _norm_cmp(team)

    def goals_used(self, team: str) -> int:
        return int(self._goals.get(self._k(team), 0))

    def assists_used(self, team: str) -> int:
        return int(self._assists.get(self._k(team), 0))

    def add(self, team: str, goals: int, assists: int) -> None:
        k = self._k(team)
        if goals:
            self._goals[k] = self.goals_used(team) + int(goals)
        if assists:
            self._assists[k] = self.assists_used(team) + int(assists)

    @classmethod
    def from_session_acc(cls, session_acc: dict) -> MatchTeamStatBudget:
        b = cls()
        for acc in session_acc.values():
            b.add(acc.get("team") or "", int(acc.get("goals") or 0), int(acc.get("assists") or 0))
        return b


def _validate_goals_vs_team_score(
    team: str,
    goals: int,
    assists: int,
    match_for_cs: tuple,
    *,
    team_goals_already: int = 0,
    team_assists_already: int = 0,
) -> Tuple[bool, Optional[str]]:
    """
    Проверка голов/передач за матч относительно счёта команды.

    - Один игрок: не больше голов команды; не больше передач; г+п игрока ≤ голам команды.
    - Команда целиком: сумма голов всех игроков и сумма передач не превышают голы команды
      (``team_goals_already`` / ``team_assists_already`` — уже учтённые в этом матче).
    """
    if goals == 0 and assists == 0:
        return True, None
    ts = _team_score_in_match(team, match_for_cs)
    if ts is None:
        return (
            False,
            f"команда «{team}» не совпадает с хозяевами/гостями в match_for_cs "
            f"({match_for_cs[0]} — {match_for_cs[1]})",
        )
    tg0 = max(0, int(team_goals_already))
    ta0 = max(0, int(team_assists_already))
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
    team_g_after = tg0 + goals
    team_a_after = ta0 + assists
    if team_g_after > ts:
        left = max(0, ts - tg0)
        return (
            False,
            f"по команде уже {tg0} гол(ов) в матче, +{goals} при счёте {ts} "
            f"(осталось не больше {left})",
        )
    if team_a_after > ts:
        left = max(0, ts - ta0)
        return (
            False,
            f"по команде уже {ta0} передач в матче, +{assists} при {ts} голах команды "
            f"(осталось не больше {left})",
        )
    return True, None


def find_player_by_name(
    session, name: str, team: str = None, nation: str | None = None
):
    """
    Найти игрока по имени во всех таблицах (без учёта регистра).

    При нескольких однофамильцах в одном клубе (Санчес Мю / Санчес Рома) передай ``team``.
    Если в клубе всё ещё неоднозначно — ``nation`` (как в БД: Мексика, Чили, …).
    Возвращает (player, position_type) или (None, None).
    """
    classes = [
        (Forward, 'forward'),
        (Midfielder, 'midfielder'),
        (Defender, 'defender'),
        (Goalkeeper, 'goalkeeper')
    ]
    want_team = _norm_cmp(team) if team else None
    want_nat = _norm_cmp(nation) if nation else None

    if want_team is not None and want_nat is None:
        from utils.player_names import resolve_player_query_in_team

        row, _err = resolve_player_query_in_team(session, team, name)
        if row is None:
            return None, None
        for PlayerClass, pos_type in classes:
            if isinstance(row, PlayerClass):
                return row, pos_type
        return row, get_position_type(getattr(row, "position", "") or "")

    cands: list[tuple] = []
    for PlayerClass, pos_type in classes:
        try:
            for player in session.query(PlayerClass).all():
                if want_team is not None and _norm_cmp(player.team) != want_team:
                    continue
                from utils.player_names import player_row_matches_query

                if not player_row_matches_query(player, name):
                    continue
                if want_nat is not None:
                    pn = _norm_cmp(getattr(player, "nation", None) or "")
                    if pn != want_nat:
                        continue
                cands.append((player, pos_type))
        except Exception:
            pass

    if not cands:
        return None, None
    if len(cands) == 1:
        return cands[0]
    if want_team is not None and want_nat is None:
        return max(
            cands,
            key=lambda c: (
                int(getattr(c[0], "matches", 0) or 0),
                int(getattr(c[0], "overall", 0) or 0),
                int(getattr(c[0], "id", 0) or 0),
            ),
        )
    return cands[0]


def pick_starting_goalkeeper_row(session, team: str) -> tuple[str | None, str | None]:
    """Имя и позицию основного вратаря (предпочтительно ``status=start``), иначе (None, None)."""
    team_t = (team or "").strip().title()
    rows = session.query(Goalkeeper).filter(Goalkeeper.team == team_t).all()
    if not rows:
        return None, None

    def sort_key(r: Goalkeeper) -> tuple[int, int, str]:
        st = (getattr(r, "status", None) or "").strip().lower()
        pr = 0 if st == "start" else 1
        return (pr, -int(r.overall or 0), (r.name or "").lower())

    rows.sort(key=sort_key)
    g = rows[0]
    return g.name, g.position


def credit_goalkeepers_for_manual_fixture(
    *,
    home: str,
    away: str,
    score_home: int,
    score_away: int,
    tournament: str,
    listed_players: list[dict[str, Any]],
) -> None:
    """
    Если соперник не забил — основному вратарю +1 матч и сухой (через ``match_for_cs``).

    Команды с ручной строкой ВРТ в ``listed_players`` пропускаем.
    """
    home_t = (home or "").strip().title()
    away_t = (away or "").strip().title()
    match_for_cs = (home_t, away_t, int(score_home), int(score_away))
    teams_with_manual_gk: set[str] = set()
    for pl in listed_players or []:
        if (pl.get("position") or "").strip().upper() == "ВРТ":
            teams_with_manual_gk.add((pl.get("team") or "").strip().title())

    session = get_session(tournament)
    touched = False
    if score_away == 0 and home_t not in teams_with_manual_gk:
        nm, pos = pick_starting_goalkeeper_row(session, home_t)
        if nm and pos:
            if add_player_stats(
                nm,
                pos,
                home_t,
                0,
                0,
                clean_sheet=False,
                tournament=tournament,
                match_for_cs=match_for_cs,
                create_if_missing=False,
                skip_discipline_check=True,
                increment_matches=True,
                sync_derived=False,
            ):
                touched = True
    if score_home == 0 and away_t not in teams_with_manual_gk:
        nm, pos = pick_starting_goalkeeper_row(session, away_t)
        if nm and pos:
            if add_player_stats(
                nm,
                pos,
                away_t,
                0,
                0,
                clean_sheet=False,
                tournament=tournament,
                match_for_cs=match_for_cs,
                create_if_missing=False,
                skip_discipline_check=True,
                increment_matches=True,
                sync_derived=False,
            ):
                touched = True
    if touched:
        from utils.common_db import sync_stats_derived_databases

        sync_stats_derived_databases()


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
                matches=0, clean_sheets=0, missed_goals=0,
                trophies=0, golden_balls=0, golden_boots=0, golden_gloves=0,
                golden_boys=0, nation=None, status=None, yellow_cards=0, red_cards=0,
                potm=0, motm=0,
            )
        elif pos_type == 'defender':
            player = PlayerClass(
                name=name, overall=0, team=team, position=position,
                matches=0, goals=0, assists=0, ga=0,
                trophies=0, golden_balls=0, golden_boots=0,
                golden_boys=0, nation=None, status=None, yellow_cards=0, red_cards=0,
                potm=0, motm=0,
            )
        else:
            player = PlayerClass(
                name=name, overall=0, team=team, position=position,
                matches=0, goals=0, assists=0, ga=0,
                trophies=0, golden_balls=0, golden_boots=0, golden_boys=0,
                nation=None, status=None, yellow_cards=0, red_cards=0,
                potm=0, motm=0,
            )

        session.add(player)
        session.commit()

    return player


ALL_POSITION_CODES = tuple(
    dict.fromkeys(forwards + midfielders + defenders + goalkeepers)
)


def _is_ga_int_token(tok: str) -> bool:
    """Число в конце строки статы: в т.ч. отрицательное «-1» и «+1»."""
    t = tok.strip()
    if not t:
        return False
    if t[0] in "+-":
        return len(t) > 1 and t[1:].isdigit()
    return t.isdigit()


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
            goals, assists = int(g.strip()), int(a.strip())
            return goals, assists, clean_sheet, parts[:-1]
        except ValueError:
            pass
    if len(parts) >= 2 and _is_ga_int_token(parts[-1]) and _is_ga_int_token(parts[-2]):
        return int(parts[-2]), int(parts[-1]), clean_sheet, parts[:-2]
    if len(parts) >= 1 and _is_ga_int_token(parts[-1]):
        return int(parts[-1]), 0, clean_sheet, parts[:-1]
    return 0, 0, clean_sheet, parts


def print_roster_cheat_sheet(home_team: str, away_team: str, tournament: str = 'league') -> None:
    """Вывести составы обеих команд из БД (шпаргалка перед вводом статистики).

    Секции как в заявке (``reserve`` / ``bench`` / ``start``) — тот же принцип, что
    в ``utils.match_ratings.build_roster_template``, чтобы резерв был явно в списке
    при вводе статы, даже если кого-то подняли из резерва в старт к матчу.
    """
    from utils.match_ratings import build_roster_template

    def dump_team(title: str, team: str) -> None:
        print(f"\n── {title}: {team} ──")
        try:
            kw = (
                {"roster_from": "league"}
                if (tournament or "").strip() in ("cl", "champ_league")
                else {}
            )
            tpl, key_map, canon = build_roster_template(team, tournament, **kw)
        except Exception:
            print("  (не удалось загрузить состав из БД)")
            return
        if not key_map:
            print("  (нет игроков в БД для этой команды)")
            return
        if (canon or "").strip().casefold() != (team or "").strip().casefold():
            print(f"  (канон в БД: {canon})")
        for line in (tpl or "").splitlines():
            s = line.strip()
            if not s:
                continue
            print(f"  {line}")

    dump_team("ХОЗЯЕВА", home_team)
    dump_team("ГОСТИ", away_team)
    print()


def add_player_stats(name: str, position: str, team: str, goals: int = 0, assists: int = 0,
                     clean_sheet: bool = False, tournament: str = 'league', auto_find: bool = False,
                     match_for_cs: tuple = None, create_if_missing: bool = False,
                     discipline_league_code: str | None = None,
                     schedule_day: int | None = None,
                     skip_discipline_check: bool = False,
                     increment_matches: bool = True,
                     team_goals_already: int = 0,
                     team_assists_already: int = 0,
                     sync_derived: bool = True):
    """
    Добавить статистику игрока после матча.

    По умолчанию у каждого успешного вызова ``matches`` увеличивается на 1. Чтобы засчитать
    только голы/передачи без игры в статистике матчей (бот — строки после матча), передайте
    ``increment_matches=False``. Засчёт матчей по оценкам — через ``utils.match_ratings``.

    Ручной ввод через ``temporary`` / интерактив: команда «1» — только игроки из БД;
    «2» — новый игрок (в цикле передаётся ``create_if_missing=True``). Для программного вызова
    без БД-записи передай ``create_if_missing=True`` явно.

    match_for_cs: (home_team, away_team, home_score, away_score) — автосухой для защитников/вратарей
        и проверка: у полевых при ненулевых голах/передачах они не превышают голы команды в этом матче
        (в т.ч. суммарно по всем уже внесённым игрокам команды — см. team_goals_already).

    team_goals_already / team_assists_already: уже учтённые в этом матче голы и передачи команды
        (сессия бота или MatchTeamStatBudget при батче).
    """
    session = get_session(tournament)
    name = name.title()
    team = team.title()

    engine = get_engine(tournament)
    Base.metadata.create_all(engine)

    player = None

    if not create_if_missing:
        from utils.player_names import resolve_player_query_in_team

        if position is None or auto_find:
            player, err = resolve_player_query_in_team(
                session, team, name, position=None
            )
            if err:
                print(f"  ✗ {err}")
                return False
        else:
            player, err = resolve_player_query_in_team(
                session, team, name, position=position.upper()
            )
            if err:
                print(f"  ✗ {err}")
                return False
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

    if not create_if_missing and not skip_discipline_check:
        from utils.player_discipline import check_player_eligible, get_calendar_month

        lc = discipline_league_code
        if lc is None and match_for_cs and len(match_for_cs) >= 2:
            lc = infer_league_code_for_stats(match_for_cs[0], match_for_cs[1], tournament)
        msched = get_calendar_month(schedule_day)
        fixture_round = None
        if match_for_cs and len(match_for_cs) >= 2 and lc:
            from utils.player_discipline import find_fixture_round

            fixture_round = find_fixture_round(
                match_for_cs[0], match_for_cs[1], lc
            )
        if lc:
            el, msg = check_player_eligible(
                player.name,
                team,
                league_code=lc,
                tournament=tournament,
                schedule_month=msched,
                fixture_round=fixture_round,
            )
            if not el:
                print(f"  {msg}")
                return False

    position = player.position
    pos_type = get_position_type(position)

    if match_for_cs and not clean_sheet:
        ht, at, hs, away_s = match_for_cs
        home_cs = away_s == 0
        away_cs = hs == 0
        tn = team.lower()
        if get_position_type(position) == 'goalkeeper':
            if (tn == ht.lower() and home_cs) or (tn == at.lower() and away_cs):
                clean_sheet = True

    if match_for_cs and (goals != 0 or assists != 0):
        ok_g, err_g = _validate_goals_vs_team_score(
            team,
            goals,
            assists,
            match_for_cs,
            team_goals_already=team_goals_already,
            team_assists_already=team_assists_already,
        )
        if not ok_g:
            print(f"  ✗ {name} ({team}): {err_g}")
            return False

    if increment_matches:
        player.matches += 1

    if pos_type in ['forward', 'midfielder', 'defender']:
        if goals < 0 and player.goals + goals < 0:
            print(f"  ✗ {name}: голов в БД {player.goals}, нельзя убавить на {abs(goals)}.")
            return False
        if assists < 0 and player.assists + assists < 0:
            print(f"  ✗ {name}: передач в БД {player.assists}, нельзя убавить на {abs(assists)}.")
            return False
        player.goals += goals
        player.assists += assists
        player.ga = player.goals + player.assists

    if pos_type == 'goalkeeper' and clean_sheet:
        player.clean_sheets += 1

    session.commit()

    from utils.stats_derived_sync import record_stat_write

    d_cs = 1 if (pos_type == "goalkeeper" and clean_sheet) else 0
    if pos_type in ("forward", "midfielder", "defender"):
        record_stat_write(
            player,
            tournament,
            d_matches=1 if increment_matches else 0,
            d_goals=goals,
            d_assists=assists,
            flush=sync_derived,
        )
    else:
        record_stat_write(
            player,
            tournament,
            d_matches=1 if increment_matches else 0,
            d_clean_sheets=d_cs,
            flush=sync_derived,
        )

    ga_str = f" {goals} {assists}" if goals or assists else ""
    cs_str = " (CS)" if clean_sheet else ""
    disp = player.name
    print(f"  ✓ {disp} {position} {team}{ga_str}{cs_str}")

    return True


def apply_match_potm(
    name: str,
    position: str,
    team: str,
    *,
    tournament: str = "league",
    sync_derived: bool = True,
) -> bool:
    """Засчитать игрока матча (POTM — Player Of The Match)."""
    session = get_session(tournament)
    name = (name or "").strip()
    team = (team or "").strip()
    player, err = None, None
    from utils.player_names import resolve_player_query_in_team

    if position:
        player, err = resolve_player_query_in_team(
            session, team, name, position=position.upper()
        )
    else:
        player, err = resolve_player_query_in_team(session, team, name, position=None)
    if err or not player:
        print(f"  ✗ POTM: {err or f'не найден «{name}» ({team})'}")
        return False
    player.potm = int(getattr(player, "potm", 0) or 0) + 1
    session.commit()
    from utils.stats_derived_sync import record_stat_write

    record_stat_write(player, tournament, d_potm=1, flush=sync_derived)
    print(f"  ✓ POTM: {player.name} ({player.team})")
    return True


def apply_match_motm(
    name: str,
    position: str,
    team: str,
    *,
    tournament: str = "league",
    sync_derived: bool = True,
) -> bool:
    """Алиас для обратной совместимости — см. ``apply_match_potm``."""
    return apply_match_potm(
        name, position, team, tournament=tournament, sync_derived=sync_derived
    )


def correct_match_potm(
    wrong_name: str,
    wrong_team: str,
    correct_name: str,
    correct_team: str,
    *,
    wrong_position: str = "",
    correct_position: str = "",
    tournament: str = "league",
    sync_derived: bool = True,
) -> tuple[bool, str]:
    """
    Перенести POTM с ошибочно выбранного игрока на правильного.

    Если у «wrong» potm=0 (ошибка не записана в этой БД), начисляет potm только «correct».
    Повторный запуск при wrong=0 и correct.potm>=1 — no-op.
    """
    from utils.player_names import resolve_player_query_in_team
    from utils.stats_derived_sync import record_stat_write

    session = get_session(tournament)
    wrong_name = (wrong_name or "").strip()
    wrong_team = (wrong_team or "").strip()
    correct_name = (correct_name or "").strip()
    correct_team = (correct_team or "").strip()

    def _resolve(name: str, team: str, position: str):
        if position:
            return resolve_player_query_in_team(
                session, team, name, position=position.upper()
            )
        return resolve_player_query_in_team(session, team, name, position=None)

    wrong, wrong_err = _resolve(wrong_name, wrong_team, wrong_position)
    correct, correct_err = _resolve(correct_name, correct_team, correct_position)
    if wrong_err or not wrong:
        return False, wrong_err or f"не найден «{wrong_name}» ({wrong_team})"
    if correct_err or not correct:
        return False, correct_err or f"не найден «{correct_name}» ({correct_team})"

    wrong_potm = int(getattr(wrong, "potm", 0) or 0)
    correct_potm = int(getattr(correct, "potm", 0) or 0)

    if wrong_potm <= 0 and correct_potm >= 1:
        msg = (
            f"POTM уже у {correct.name} ({correct_potm}); "
            f"у {wrong.name} potm={wrong_potm} — правка не нужна."
        )
        print(f"  ○ {msg}")
        return True, msg

    d_wrong = 0
    d_correct = 0
    if wrong_potm > 0:
        wrong.potm = wrong_potm - 1
        d_wrong = -1
        correct.potm = correct_potm + 1
        d_correct = 1
    else:
        correct.potm = correct_potm + 1
        d_correct = 1

    session.commit()
    if d_wrong:
        record_stat_write(wrong, tournament, d_potm=d_wrong, flush=False)
    if d_correct:
        record_stat_write(correct, tournament, d_potm=d_correct, flush=sync_derived)
    elif sync_derived:
        from utils.stats_derived_sync import flush_stat_deltas

        flush_stat_deltas()

    msg = (
        f"POTM: {wrong.name} {wrong.potm} → {correct.name} {correct.potm} "
        f"({tournament})"
    )
    print(f"  ✓ {msg}")
    return True, msg


def correct_match_motm(
    wrong_name: str,
    wrong_team: str,
    correct_name: str,
    correct_team: str,
    **kwargs,
) -> tuple[bool, str]:
    """Алиас — см. ``correct_match_potm``."""
    return correct_match_potm(
        wrong_name, wrong_team, correct_name, correct_team, **kwargs
    )


def apply_month_motm(
    name: str,
    position: str,
    team: str,
    *,
    tournament: str = "league",
    sync_derived: bool = True,
) -> bool:
    """Награда MOTM — Man Of The Month (+1 к полю motm)."""
    session = get_session(tournament)
    name = (name or "").strip()
    team = (team or "").strip()
    from utils.player_names import resolve_player_query_in_team

    if position:
        player, err = resolve_player_query_in_team(
            session, team, name, position=position.upper()
        )
    else:
        player, err = resolve_player_query_in_team(session, team, name, position=None)
    if err or not player:
        print(f"  ✗ MOTM месяца: {err or f'не найден «{name}» ({team})'}")
        return False
    player.motm = int(getattr(player, "motm", 0) or 0) + 1
    session.commit()
    from utils.stats_derived_sync import record_stat_write

    record_stat_write(player, tournament, d_motm=1, flush=sync_derived)
    print(f"  ✓ MOTM месяца: {player.name} ({player.team})")
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
    budget = MatchTeamStatBudget()
    for row in rows:
        if len(row) != 5:
            raise ValueError(f"Ожидается (имя, позиция, команда, голы, передачи), получено: {row!r}")
        name, position, team, goals, assists = row
        if add_player_stats(
            name, position, team, goals, assists,
            tournament=tournament,
            match_for_cs=match_for_cs,
            create_if_missing=create_if_missing,
            team_goals_already=budget.goals_used(team),
            team_assists_already=budget.assists_used(team),
            sync_derived=False,
        ):
            budget.add(team, goals, assists)
            ok += 1
        else:
            fail += 1
    if ok:
        from utils.common_db import sync_stats_derived_databases

        sync_stats_derived_databases()
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
    sync_derived: bool = True,
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

    if pos_type == "goalkeeper" and clean_sheet:
        player.clean_sheets -= 1
        if player.clean_sheets < 0:
            player.clean_sheets = 0

    session.commit()

    from utils.stats_derived_sync import record_stat_write

    d_cs = -1 if (pos_type == "goalkeeper" and clean_sheet) else 0
    if pos_type in ("forward", "midfielder", "defender"):
        record_stat_write(
            player,
            tournament,
            d_matches=-1,
            d_goals=-goals,
            d_assists=-assists,
            flush=sync_derived,
        )
    else:
        record_stat_write(
            player,
            tournament,
            d_matches=-1,
            d_clean_sheets=d_cs,
            flush=sync_derived,
        )

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
            sync_derived=False,
        ):
            ok += 1
        else:
            fail += 1
    if ok:
        from utils.common_db import sync_stats_derived_databases

        sync_stats_derived_databases()
    return ok, fail


def parse_player_input(input_str: str, default_team: str = "", require_position: bool = False):
    """
    Парсинг строки игрока.

    Голы и ассисты (с конца строки): ``2+1`` или ``2 1`` или одно число ``2`` (= 2 гола, 0 передач);
    можно отрицательные поправки: ``игрок -1 0``, ``игрок -1 +1``.
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
    print(
        "Дисциплина/травмы: бастони жк  |  бастони 2жк  |  бастони кк  |  симонс 4м  |  брозович с3 1м "
        "(травма — отдельной строкой, лат. m OK; месяц без слота берётся из max(day) сыгранных в match_results.json)"
    )
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

        from utils.player_discipline import (
            get_calendar_month,
            line_looks_discipline,
            try_apply_discipline_line,
        )

        st_tourn = "cl" if tournament == "cl" else "league"
        lc_inf = infer_league_code_for_stats(home_team, away_team, st_tourn)
        msched = get_calendar_month(None)
        if line_looks_discipline(player_input):
            dm, h = try_apply_discipline_line(
                player_input,
                current_team=current_team,
                tournament=st_tourn,
                league_code=lc_inf,
                schedule_month=msched,
                fixture_home=home_team,
                fixture_away=away_team,
            )
            if h:
                if dm:
                    print(f"  {dm}")
            else:
                print(
                    "  Не разобрать дисциплину. Формат: «… жк» / «… 2жк» / «… кк» / «… 4м»/«… 4m»"
                )
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
                discipline_league_code=lc_inf,
                schedule_day=None,
                sync_derived=False,
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

    from utils.common_db import sync_stats_derived_databases

    sync_stats_derived_databases()
    print("✓ Статистика сохранена")


def format_single_team_roster_text(team: str, tournament: str = "league") -> str:
    """Состав одного клуба для подсказки при вводе «кто сыграл»."""
    from utils.match_ratings import build_roster_template

    team = (team or "").strip().title()
    try:
        kw = (
            {"roster_from": "league"}
            if (tournament or "").strip() in ("cl", "champ_league")
            else {}
        )
        tpl, _, _canon = build_roster_template(team, tournament, **kw)
    except Exception:
        return ""
    lines: list[str] = []
    for line in (tpl or "").splitlines():
        s = line.strip()
        if s:
            lines.append(s)
    return "\n".join(lines)


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


def _stats_session_key(name: str, team: str) -> str:
    from utils.player_transfer import _norm_cmp

    return f"{_norm_cmp((name or '').strip())}|{_norm_cmp((team or '').strip())}"


def _default_session_acc_entry() -> dict:
    return {
        "display_name": "",
        "position": "",
        "team": "",
        "goals": 0,
        "assists": 0,
        "yellow_count": 0,
        "second_yellow": False,
        "red_direct": False,
        "injury_months": None,
        "clean_sheet": False,
    }


def _merge_session_acc_discipline(acc: dict, raw: str) -> None:
    from utils.player_discipline import _RE_2Y, _RE_2Y_GLUE, _RE_INJ, _RE_R, _RE_Y

    s = (raw or "").strip()
    if _RE_2Y.match(s) or _RE_2Y_GLUE.match(s):
        acc["second_yellow"] = True
        return
    m_inj = _RE_INJ.match(s)
    if m_inj:
        acc["injury_months"] = int(m_inj.group(2))
        return
    if _RE_Y.match(s):
        acc["yellow_count"] = int(acc.get("yellow_count") or 0) + 1
        return
    if _RE_R.match(s):
        acc["red_direct"] = True


def format_stats_session_summary_line(acc: dict) -> str:
    """Одна строка «имя позиция G+A жк …» для саммари после ввода."""
    nm = (acc.get("display_name") or "").strip()
    pos = (acc.get("position") or "").strip()
    g, a = int(acc.get("goals") or 0), int(acc.get("assists") or 0)
    parts = [nm, pos, f"{g} {a}"]
    if acc.get("red_direct"):
        parts.append("кк")
    elif acc.get("second_yellow") or int(acc.get("yellow_count") or 0) >= 2:
        parts.append("2жк")
    elif int(acc.get("yellow_count") or 0) >= 1:
        parts.append("жк")
    ij = acc.get("injury_months")
    if ij is not None:
        parts.append(f"{int(ij)}м")
    if acc.get("clean_sheet"):
        parts.append("cs")
    return " ".join(x for x in parts if x)


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
    league_code: str | None = None,
    schedule_day: int | None = None,
    increment_matches: bool = True,
    session_match_players: set[str] | None = None,
    session_acc: dict[str, dict] | None = None,
    stats_played_keys: set[str] | None = None,
    confirm_unlisted_apply: bool = False,
) -> tuple[str, str, bool, dict | None]:
    """
    Одна строка ввода статистики для бота (без input()).
    Возвращает (ответ, сторона, режим «новый игрок», confirm|None).

    ``stats_played_keys``: после фазы «кто сыграл» — матчи уже +1; при строке для игрока
    вне списка — ``confirm`` с полями name, team, position, line (без записи).

    Если переданы оба ``session_match_players`` и ``session_acc``, у каждого игрока поле matches
    в БД растёт только при первой строке этого игрока в сессии (кроме режима ``stats_played_keys``).

    Иначе ``increment_matches`` задаёт поведение по строке как раньше (консоль / без сессии).
    """
    _confirm_none: dict | None = None

    def _ret(msg: str, team: str = current_team, mode: bool = mode_new, confirm=None):
        return (msg, team, mode, confirm if confirm is not None else _confirm_none)
    import contextlib
    import io

    from utils.player_discipline import (
        extract_discipline_player_name,
        get_calendar_month,
        line_looks_discipline,
        try_apply_discipline_line,
    )

    raw = (line or "").strip()
    played_phase = stats_played_keys is not None

    if not raw:
        return _ret(
            "Пустую строку пропускаем. Закончить — /done или кнопка «Готово»."
        )

    low = raw.lower()
    if low in ("1",):
        return _ret("Режим: только игроки из БД.", mode=False)
    if low in ("2",):
        return _ret("Режим: новый игрок (позиция в строке обязательна).", mode=True)
    if low in ("h", "home", "х", "хозяева"):
        return _ret(f"Сторона ввода: {home_team}", home_team)
    if low in ("a", "away", "г", "гости"):
        return _ret(f"Сторона ввода: {away_team}", away_team)

    st_tourn = "cl" if (tournament or "") == "cl" else "league"
    lc = league_code or infer_league_code_for_stats(home_team, away_team, st_tourn)
    msched = get_calendar_month(schedule_day)
    use_session = session_match_players is not None and session_acc is not None

    if line_looks_discipline(raw):
        if played_phase and not confirm_unlisted_apply:
            pname_chk = extract_discipline_player_name(raw)
            if pname_chk:
                from utils.player_names import resolve_player_query_in_team

                sess_chk = get_session(st_tourn)
                pl_chk, _ = resolve_player_query_in_team(
                    sess_chk,
                    current_team.strip().title(),
                    pname_chk.strip(),
                )
                if pl_chk:
                    key_chk = _stats_session_key(pl_chk.name, pl_chk.team)
                    if key_chk not in stats_played_keys:
                        return _ret(
                            "",
                            confirm={
                                "name": pl_chk.name.strip().title(),
                                "team": (pl_chk.team or current_team).strip().title(),
                                "position": (pl_chk.position or "").strip(),
                                "line": raw,
                            },
                        )
        dmsg, handled = try_apply_discipline_line(
            raw,
            current_team=current_team,
            tournament=st_tourn,
            league_code=lc,
            schedule_month=msched,
            fixture_home=home_team,
            fixture_away=away_team,
        )
        if handled:
            tail = ""
            if use_session:
                pname_raw = extract_discipline_player_name(raw)
                if pname_raw:
                    from utils.player_names import resolve_player_query_in_team

                    sess = get_session(st_tourn)
                    pl, _ = resolve_player_query_in_team(
                        sess,
                        current_team.strip().title(),
                        pname_raw.strip(),
                    )
                    if pl:
                        key_d = _stats_session_key(pl.name, pl.team)
                        if key_d not in session_acc:
                            session_acc[key_d] = _default_session_acc_entry()
                            session_acc[key_d]["display_name"] = pl.name.strip()
                            session_acc[key_d]["position"] = (pl.position or "").strip()
                            session_acc[key_d]["team"] = (pl.team or "").strip().title()
                        _merge_session_acc_discipline(session_acc[key_d], raw)
                        incr_d = (
                            increment_matches
                            and not played_phase
                            and key_d not in session_match_players
                        )
                        if confirm_unlisted_apply and played_phase:
                            stats_played_keys.add(key_d)
                            incr_d = key_d not in session_match_players
                        if incr_d:
                            match_for_cs_d = (home_team, away_team, home_score, away_score)
                            bufm = io.StringIO()
                            with contextlib.redirect_stdout(bufm):
                                ok_m = add_player_stats(
                                    pl.name,
                                    pl.position,
                                    pl.team,
                                    0,
                                    0,
                                    clean_sheet=False,
                                    tournament=tournament,
                                    auto_find=True,
                                    match_for_cs=match_for_cs_d,
                                    create_if_missing=False,
                                    discipline_league_code=lc,
                                    schedule_day=schedule_day,
                                    increment_matches=True,
                                    skip_discipline_check=True,
                                    sync_derived=False,
                                )
                            if ok_m:
                                session_match_players.add(key_d)
                        tail = "\n📋 " + format_stats_session_summary_line(
                            session_acc[key_d]
                        )
            return _ret((dmsg or "—") + tail)
        return _ret(
            "Не удалось разобрать дисциплину. Формат: «фамилия жк» / «… 2жк» / «… кк» / «… 4м» или «… 4m»"
        )

    match_for_cs = (home_team, away_team, home_score, away_score)

    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        pdata = parse_player_input(raw, current_team, require_position=mode_new)
    head = buf.getvalue().strip()

    if pdata is None:
        return _ret(head or "Не удалось разобрать строку.")

    if (
        pdata.get("auto_find")
        and pdata.get("goals", 0) == 0
        and pdata.get("assists", 0) == 0
        and not pdata.get("clean_sheet")
    ):
        ts = _team_score_in_match(pdata["team"], match_for_cs)
        if ts is not None and ts > 0:
            hint = pdata["name"].split()[0]
            return _ret(
                f"⚠ У «{pdata['team']}» в этом матче {ts} гол(а). "
                f"Если у игрока есть гол или передача — укажи цифры "
                f"(например: {hint} 1 0)."
            )

    key_g = _stats_session_key(pdata["name"], pdata["team"]) if use_session else None
    if played_phase and key_g and key_g not in stats_played_keys and not confirm_unlisted_apply:
        return _ret(
            "",
            confirm={
                "name": pdata["name"].strip().title(),
                "team": (pdata.get("team") or current_team).strip().title(),
                "position": (pdata.get("position") or "").strip(),
                "line": raw,
            },
        )

    pos = pdata.get("position")
    home_cs = away_score == 0
    away_cs = home_score == 0
    if pos and get_position_type(pos) in ("defender", "goalkeeper"):
        if pdata["team"].lower() == home_team.lower() and home_cs:
            pdata["clean_sheet"] = True
        elif pdata["team"].lower() == away_team.lower() and away_cs:
            pdata["clean_sheet"] = True

    do_incr = increment_matches
    if played_phase:
        do_incr = False
    elif use_session and key_g is not None:
        do_incr = increment_matches and (key_g not in session_match_players)
    if confirm_unlisted_apply and played_phase and key_g:
        stats_played_keys.add(key_g)
        do_incr = key_g not in session_match_players if use_session else True

    team_g0, team_a0 = (0, 0)
    if use_session and session_acc is not None:
        team_g0, team_a0 = team_match_contrib_from_session_acc(
            session_acc, pdata["team"]
        )

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
            discipline_league_code=lc,
            schedule_day=schedule_day,
            increment_matches=do_incr,
            skip_discipline_check=True,
            team_goals_already=team_g0,
            team_assists_already=team_a0,
            sync_derived=False,
        )
    out = buf2.getvalue().strip()
    if not ok_add:
        return _ret(out or "Запись не выполнена. Проверь строку по шпаргалке.")
    if use_session and key_g is not None:
        session_match_players.add(key_g)
        if key_g not in session_acc:
            session_acc[key_g] = _default_session_acc_entry()
            session_acc[key_g]["display_name"] = pdata["name"].strip().title()
            session_acc[key_g]["position"] = (pdata.get("position") or "").strip()
            session_acc[key_g]["team"] = (pdata.get("team") or "").strip().title()
        session_acc[key_g]["goals"] = int(session_acc[key_g].get("goals") or 0) + int(
            pdata.get("goals") or 0
        )
        session_acc[key_g]["assists"] = int(session_acc[key_g].get("assists") or 0) + int(
            pdata.get("assists") or 0
        )
        if pdata.get("clean_sheet"):
            session_acc[key_g]["clean_sheet"] = True
        tail = "\n📋 " + format_stats_session_summary_line(session_acc[key_g])
        return _ret((out or "✓") + tail)
    return _ret(out or "✓")


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


def format_top_scorers_from_session(
    session,
    league_code: Optional[str] = None,
    limit: int = 20,
    title_suffix: str = "",
) -> str:
    """Печать топа бомбардиров из произвольной SQLAlchemy-сессии (готовый common или тест)."""
    all_players: list[dict] = []
    filter_teams = None
    if league_code == "cl":
        import teams as teams_mod

        filter_teams = [t.lower() for t in teams_mod.teams_champ_league.keys()]
    elif league_code and league_code in LEAGUE_TEAMS:
        filter_teams = [t.lower() for t in LEAGUE_TEAMS[league_code]]

    for PlayerClass in (Forward, Midfielder, Defender):
        try:
            for p in session.query(PlayerClass).filter(PlayerClass.goals > 0).all():
                if filter_teams and p.team.lower() not in filter_teams:
                    continue
                all_players.append(
                    {
                        "name": p.name,
                        "team": p.team,
                        "position": p.position,
                        "goals": p.goals,
                        "assists": p.assists,
                        "ga": p.ga,
                        "matches": p.matches,
                    }
                )
        except Exception:
            pass

    all_players.sort(key=lambda x: (-x["goals"], -x["assists"]))
    base_name = LEAGUE_NAMES.get(league_code, "Все лиги")
    league_name = f"{base_name}{title_suffix}"

    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        print(f"\n{'='*65}")
        print(f"  ТОП-{limit} БОМБАРДИРОВ - {league_name}")
        print(f"{'='*65}")
        print(
            f"{'#':<4} {'Игрок':<18} {'Команда':<15} {'Поз':<5} {'Г':<4} {'А':<4} {'Г+А':<5}"
        )
        print("-" * 65)
        if not all_players:
            print("  Нет данных")
        else:
            for i, p in enumerate(all_players[:limit], 1):
                print(
                    f"{i:<4} {p['name']:<18} {p['team']:<15} {p['position']:<5} "
                    f"{p['goals']:<4} {p['assists']:<4} {p['ga']:<5}"
                )
    return buf.getvalue()


def format_top_assists_from_session(
    session,
    league_code: Optional[str] = None,
    limit: int = 20,
    title_suffix: str = "",
) -> str:
    all_players: list[dict] = []
    filter_teams = None
    if league_code == "cl":
        import teams as teams_mod

        filter_teams = [t.lower() for t in teams_mod.teams_champ_league.keys()]
    elif league_code and league_code in LEAGUE_TEAMS:
        filter_teams = [t.lower() for t in LEAGUE_TEAMS[league_code]]

    for PlayerClass in (Forward, Midfielder, Defender):
        try:
            for p in session.query(PlayerClass).filter(PlayerClass.assists > 0).all():
                if filter_teams and p.team.lower() not in filter_teams:
                    continue
                all_players.append(
                    {
                        "name": p.name,
                        "team": p.team,
                        "position": p.position,
                        "goals": p.goals,
                        "assists": p.assists,
                        "ga": p.ga,
                        "matches": p.matches,
                    }
                )
        except Exception:
            pass

    all_players.sort(key=lambda x: (-x["assists"], -x["goals"]))
    base_name = LEAGUE_NAMES.get(league_code, "Все лиги")
    league_name = f"{base_name}{title_suffix}"

    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        print(f"\n{'='*65}")
        print(f"  ТОП-{limit} АССИСТЕНТОВ - {league_name}")
        print(f"{'='*65}")
        print(
            f"{'#':<4} {'Игрок':<18} {'Команда':<15} {'Поз':<5} {'А':<4} {'Г':<4} {'Г+А':<5}"
        )
        print("-" * 65)
        if not all_players:
            print("  Нет данных")
        else:
            for i, p in enumerate(all_players[:limit], 1):
                print(
                    f"{i:<4} {p['name']:<18} {p['team']:<15} {p['position']:<5} "
                    f"{p['assists']:<4} {p['goals']:<4} {p['ga']:<5}"
                )
    return buf.getvalue()


def format_top_ga_from_session(
    session,
    league_code: Optional[str] = None,
    limit: int = 20,
    title_suffix: str = "",
) -> str:
    all_players: list[dict] = []
    filter_teams = None
    if league_code == "cl":
        import teams as teams_mod

        filter_teams = [t.lower() for t in teams_mod.teams_champ_league.keys()]
    elif league_code and league_code in LEAGUE_TEAMS:
        filter_teams = [t.lower() for t in LEAGUE_TEAMS[league_code]]

    for PlayerClass in (Forward, Midfielder, Defender):
        try:
            for p in session.query(PlayerClass).filter(PlayerClass.ga > 0).all():
                if filter_teams and p.team.lower() not in filter_teams:
                    continue
                all_players.append(
                    {
                        "name": p.name,
                        "team": p.team,
                        "position": p.position,
                        "goals": p.goals,
                        "assists": p.assists,
                        "ga": p.ga,
                        "matches": p.matches,
                    }
                )
        except Exception:
            pass

    all_players.sort(key=lambda x: (-x["ga"], -x["goals"]))
    base_name = LEAGUE_NAMES.get(league_code, "Все лиги")
    league_name = f"{base_name}{title_suffix}"

    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        print(f"\n{'='*65}")
        print(f"  ТОП-{limit} ПО Г+А - {league_name}")
        print(f"{'='*65}")
        print(
            f"{'#':<4} {'Игрок':<18} {'Команда':<15} {'Поз':<5} {'Г+А':<5} {'Г':<4} {'А':<4}"
        )
        print("-" * 65)
        if not all_players:
            print("  Нет данных")
        else:
            for i, p in enumerate(all_players[:limit], 1):
                print(
                    f"{i:<4} {p['name']:<18} {p['team']:<15} {p['position']:<5} "
                    f"{p['ga']:<5} {p['goals']:<4} {p['assists']:<4}"
                )
    return buf.getvalue()


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
                    "potm": int(getattr(p, "potm", 0) or 0),
                    "motm": int(getattr(p, "motm", 0) or 0),
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
        f"{'И':>4} {'Г':>4} {'А':>4} {'Г+А':>5} {'POTM':>4} {'MOTM':>4}"
    )
    print(hdr)
    print("-" * 80)
    for i, p in enumerate(rows, 1):
        print(
            f"{i:<4} {p['name']:<20} {p['team']:<18} {p['position']:<5} "
            f"{p['matches']:>4} {p['goals']:>4} {p['assists']:>4} "
            f"{p['ga']:>5} {int(p.get('potm', 0)):>4} {int(p.get('motm', 0)):>4}"
        )
    print("-" * 80)


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
    *,
    session=None,
    title_suffix: str = "",
) -> None:
    """
    Игроки команды с голом или передачей: И (матчи в БД), Г, А, Г+А по убыванию Г+А.
    Учитываются нападающие, полузащитники и защитники (голы > 0 или передачи > 0).
    Внизу: сумма голов игроков в списке, ЗМ по таблице и число матчей команды (pickle).

    Если передан ``session`` (архивный sqlite), он используется вместо ``get_session``;
    вызывающий код закрывает сессию и движок.
    """
    team = _team_name_as_in_db(team)
    if session is None:
        session = get_session(tournament)
    rows = []
    for PlayerClass in (Forward, Midfielder, Defender):
        for p in session.query(PlayerClass).filter_by(team=team).all():
            g = int(p.goals or 0)
            a = int(p.assists or 0)
            if g <= 0 and a <= 0:
                continue
            ga = int(getattr(p, "ga", None) or (g + a))
            from utils.player_names import player_display_name

            rows.append(
                {
                    "name": player_display_name(p),
                    "pos": p.position,
                    "matches": int(p.matches or 0),
                    "g": g,
                    "a": a,
                    "ga": ga,
                    "potm": int(getattr(p, "potm", 0) or 0),
                    "motm": int(getattr(p, "motm", 0) or 0),
                }
            )
    rows.sort(key=lambda x: (-x["ga"], -x["g"], x["name"].lower()))

    width = 74
    sep = "=" * width
    if tournament in ("cl", "champ_league"):
        tname = "Лига Чемпионов"
    elif tournament in ("common", "merged", "all"):
        tname = "лига + ЛЧ (общая БД)"
    else:
        tname = "национальные лиги"
    suf = f" · {title_suffix}" if title_suffix else ""
    print(f"\n{sep}")
    print(f"  Статистика: {team} ({tname}){suf}")
    print(sep)
    if not rows:
        print("  Нет игроков с голами или передачами в этой базе.")
    else:
        print(f"{'#':<4} {'Игрок':<18} {'Поз':<6} {'И':>4} {'Г':>4} {'А':>4} {'Г+А':>5} {'POTM':>4} {'MOTM':>4}")
        print("-" * width)
        for i, r in enumerate(rows, 1):
            print(
                f"{i:<4} {r['name']:<18} {r['pos']:<6} {r['matches']:>4} "
                f"{r['g']:>4} {r['a']:>4} {r['ga']:>5} {int(r.get('potm', 0)):>4} {int(r.get('motm', 0)):>4}"
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
    *,
    session=None,
    title_suffix: str = "",
) -> str:
    """Текст блока «голеадоры команды» — как show_team_goalscorers_table, для бота."""
    import contextlib
    import io

    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        show_team_goalscorers_table(
            team,
            tournament,
            standings_dict,
            session=session,
            title_suffix=title_suffix,
        )
    return buf.getvalue()


def format_team_goalscorers_league_report(
    league_code: str,
    *,
    session=None,
    title_suffix: str = "",
    teams_order: Optional[list[str]] = None,
) -> str:
    """Все команды лиги подряд — как пункт «b»→4 в консоли."""
    tournament = "cl" if league_code == "cl" else "league"
    import teams as teams_mod

    if teams_order is not None:
        teams = list(teams_order)
    elif league_code == "cl":
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
    if league_code == "cl" and session is not None:
        standings = None

    head_extra = f" · {title_suffix}" if title_suffix else ""
    parts = [
        "\n" + "=" * 60,
        f"  {league_name} — стата всех клубов{head_extra}",
        "=" * 60 + "\n",
    ]
    for team in teams:
        parts.append(
            format_team_goalscorers_table_str(
                team,
                tournament,
                standings,
                session=session,
                title_suffix=title_suffix,
            )
        )
    return "".join(parts)


def format_all_leagues_combined_list_str(limit: int = 100, sort_key: int = 1) -> str:
    """
    Топ-100: лига + ЛЧ по снимкам сезонов, одна строка на игрока.
    sort_key: 1 — голы, 2 — передачи, 3 — Г+А.
    """
    from utils.stats_history_agg import format_top100_str

    return format_top100_str("allcl", limit=limit, sort_key=sort_key)
