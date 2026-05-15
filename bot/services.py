"""
Текстовые отчёты для Telegram: переиспользуют функции main/player_stats без дублирования логики.
"""
from __future__ import annotations

import contextlib
import logging
import io
from html import escape as html_escape

# Код лиги → подпись кнопки
LEAGUE_LABELS: tuple[tuple[str, str], ...] = (
    ("rpl", "РПЛ"),
    ("eng", "АПЛ"),
    ("esp", "Ла Лига"),
    ("ita", "Серия А"),
    ("ger", "Бундеслига"),
    ("cl", "ЛЧ"),
)


def tournament_db_for_league(league_code: str) -> str:
    return "cl" if league_code == "cl" else "league"


# Имя файла pickle в db/season_n/pickle/ (как в teams.save_result)
ARCHIVE_PICKLE_BY_LEAGUE: dict[str, str] = {
    "rpl": "rpl_teams.pkl",
    "eng": "england_teams.pkl",
    "esp": "spain_teams.pkl",
    "ita": "italy_teams.pkl",
    "ger": "germany_teams.pkl",
    "cl": "champ_league_teams.pkl",
}


def render_standings(league_code: str, season_num: int | None = None) -> str:
    """
    Таблица лиги. ``season_num`` — архив ``db/season_n``; ``None`` — текущий сезон (pickle + журнал).
    """
    import os
    import pickle

    from main import LEAGUES, show_table
    from utils import season_paths

    league = next((x for x in LEAGUES.values() if x["code"] == league_code), None)
    if not league:
        return f"Неизвестная лига: {league_code}"

    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        if season_num is None:
            show_table(league["teams"], league["name"], league_code=league_code)
        else:
            pkl_name = ARCHIVE_PICKLE_BY_LEAGUE.get(league_code)
            if not pkl_name:
                print(f"Неизвестная лига: {league_code}")
            else:
                base = season_paths.season_archive_directory(season_num)
                pkl_path = os.path.join(base, "pickle", pkl_name)
                if not os.path.isfile(pkl_path):
                    print(
                        f"Нет архива pickle для сезона {season_num}: {pkl_path}\n"
                        f"(нужна папка db/season_{season_num}/pickle/)."
                    )
                else:
                    with open(pkl_path, "rb") as f:
                        arch_teams = pickle.load(f)
                    title = f"{league['name']} · архив сезона {season_num}"
                    jpath = os.path.join(base, "match_results.json")
                    cl_j = jpath if league_code == "cl" else None
                    show_table(
                        arch_teams,
                        title,
                        league_code=league_code,
                        cl_journal_path=cl_j,
                    )
    return buf.getvalue()


def render_top_scorers(league_code: str, limit: int = 25) -> str:
    from player_stats import show_top_scorers

    t = tournament_db_for_league(league_code)
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        show_top_scorers(t, league_code, limit=limit)
    return buf.getvalue()


def render_top_assists(league_code: str, limit: int = 25) -> str:
    from player_stats import show_top_assistants

    t = tournament_db_for_league(league_code)
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        show_top_assistants(t, league_code, limit=limit)
    return buf.getvalue()


def render_top_ga(league_code: str, limit: int = 25) -> str:
    from player_stats import show_top_ga

    t = tournament_db_for_league(league_code)
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        show_top_ga(t, league_code, limit=limit)
    return buf.getvalue()


def write_cl_bracket_html_path() -> str:
    from champions_league.bracket_html import write_cl_bracket_html

    return write_cl_bracket_html()


def render_cl_bracket_text() -> str:
    from champions_league.knockout_bracket import format_cl_knockout_bracket_text

    return format_cl_knockout_bracket_text()


def render_status_short() -> str:
    from match_results import count_recorded_matches, get_match_results_path
    from main import count_remaining_in_schedule, load_or_generate_mixed_schedule

    sch = load_or_generate_mixed_schedule()
    total = sum(len(d["matches"]) for d in sch)
    rem = count_remaining_in_schedule(sch)
    n = count_recorded_matches()
    path = get_match_results_path()
    return (
        f"Матчей в смешанном расписании: {total}\n"
        f"Осталось сыграть (по календарю): {rem}\n"
        f"Записей в журнале: {n}\n"
        f"Файл журнала: {path}"
    )


def render_full_status_text() -> str:
    """Как пункт «i» в консольном main: расписание, журнал, сыграно по лигам, skipped."""
    from main import LEAGUES, count_remaining_in_schedule, load_or_generate_mixed_schedule
    from match_results import count_recorded_matches, get_match_results_path
    from skipped_matches import load_skipped_matches

    mixed = load_or_generate_mixed_schedule()
    remaining = count_remaining_in_schedule(mixed)
    total = sum(len(d["matches"]) for d in mixed)
    lines: list[str] = []
    lines.append("СТАТУС (МАТЧ-ДЕНЬ)")
    lines.append(f"Всего матчей в расписании: {total}")
    lines.append(f"Осталось сыграть (по календарю): {remaining}")
    n_journal = count_recorded_matches()
    lines.append(f"Журнал сыгранных: {n_journal} записей → {get_match_results_path()}")
    lines.append("")
    lines.append("Матчей сыграно по лигам (таблицы / pickle):")
    for key, league in LEAGUES.items():
        teams = league["teams"]
        played = sum(t.matches for t in teams.values()) // 2
        lines.append(f"  {key}. {league['name']:<18} сыграно: {played}")
    skipped = load_skipped_matches()
    if skipped:
        lines.append("")
        lines.append(f"⚠ В отложенных (skipped_matches.json): {len(skipped)}")
    from main import INPUT_PLAYER_STATS

    lines.append("")
    lines.append(
        f"Ввод статистики после матча: {'вкл' if INPUT_PLAYER_STATS else 'выкл'} "
        f"(INPUT_PLAYER_STATS в main.py; переключение «x» — только в консоли)."
    )
    return "\n".join(lines)


def render_top_scorers_common(league_code: str, limit: int = 25) -> str:
    """Топ бомбардиров: лига + ЛЧ из common_synced.db (все сезоны)."""
    return render_cumulative_top_scorers(league_code, limit)


def render_top_assists_common(league_code: str, limit: int = 25) -> str:
    """Топ ассистов: common_synced.db (все сезоны)."""
    return render_cumulative_top_assists(league_code, limit)


def render_top_ga_common(league_code: str, limit: int = 25) -> str:
    """Топ Г+А: common_synced.db (все сезоны)."""
    return render_cumulative_top_ga(league_code, limit)


def render_team_goalscorers_league(league_code: str) -> str:
    """Голеадоры по всем командам лиги — как «b»→4."""
    from player_stats import format_team_goalscorers_league_report

    return format_team_goalscorers_league_report(league_code)


def teams_ordered_for_goalscorers(league_code: str) -> list[str]:
    """Клубы лиги в том же порядке, что и в полном отчёте «голеадоры по клубам»."""
    import teams as teams_mod
    from config.leagues_config import ALL_LEAGUES

    if league_code == "cl":
        return sorted(teams_mod.teams_champ_league.keys())
    if league_code not in ALL_LEAGUES:
        raise ValueError(f"Неизвестная лига: {league_code}")
    # Кнопки должны показывать только актуальный пул текущего сезона (8 клубов в нац. лигах).
    current_pool = {
        str(x).strip().title()
        for x in (ALL_LEAGUES[league_code].get("teams") or [])
        if str(x).strip()
    }
    if not current_pool:
        return []
    teams_map = {
        "rpl": teams_mod.teams_rpl,
        "eng": teams_mod.teams_eng,
        "esp": teams_mod.teams_spain,
        "ger": teams_mod.teams_germany,
        "ita": teams_mod.teams_italy,
    }
    teams_dict = teams_map.get(league_code) or {}
    return sorted([t for t in teams_dict.keys() if t in current_pool], key=lambda s: s.casefold())


def cl_team_names_from_champions_db(db_path: str) -> list[str]:
    """Участники ЛЧ по строкам в архивной champions_league.db (DISTINCT team по всем позициям)."""
    import sqlite3

    names: set[str] = set()
    conn = sqlite3.connect(db_path)
    try:
        for tbl in ("forwards", "midfielders", "defenders", "goalkeepers"):
            try:
                cur = conn.execute(
                    f"SELECT DISTINCT team FROM {tbl} "
                    "WHERE team IS NOT NULL AND trim(team) != ''"
                )
                for (t,) in cur:
                    s = str(t).strip()
                    if s:
                        names.add(s)
            except sqlite3.OperationalError:
                pass
    finally:
        conn.close()
    return sorted(names, key=lambda x: x.casefold())


def _cl_teams_from_season_pickle(season_num: int) -> list[str] | None:
    import os
    import pickle

    from utils import season_paths

    p = os.path.join(
        season_paths.season_archive_directory(int(season_num)),
        "pickle",
        ARCHIVE_PICKLE_BY_LEAGUE["cl"],
    )
    if not os.path.isfile(p):
        return None
    with open(p, "rb") as f:
        arch = pickle.load(f)
    if isinstance(arch, dict):
        keys = [str(k).strip() for k in arch.keys() if str(k).strip()]
        return sorted(keys, key=lambda x: x.casefold()) if keys else None
    return None


def teams_ordered_for_goalscorers_season_archive(
    season_num: int, league_code: str
) -> list[str]:
    """
    Клубы для клавиатуры голеадоров в архиве сезона.
    Для ЛЧ — состав участников того сезона (БД / pickle), не текущий teams_champ_league.
    """
    if league_code != "cl":
        return teams_ordered_for_goalscorers(league_code)
    p = _archived_season_db_path_for_goalscorers(int(season_num), "cl")
    if p:
        names = cl_team_names_from_champions_db(p)
        if names:
            return names
    from_pkl = _cl_teams_from_season_pickle(int(season_num))
    if from_pkl:
        return from_pkl
    return teams_ordered_for_goalscorers("cl")


def render_team_squad_pitch_png_bytes(league_code: str, team_index: int) -> bytes:
    """PNG: состав на поле (схема тренера, футболки + запас/резерв текстом)."""
    from bot.squad_pitch import render_squad_pitch_png_bytes

    teams = teams_ordered_for_goalscorers(league_code)
    if not (0 <= team_index < len(teams)):
        raise IndexError("Некорректный выбор команды")
    team = teams[team_index]
    tournament = tournament_db_for_league(league_code)
    return render_squad_pitch_png_bytes(team, tournament)


def render_team_goalscorers_single(league_code: str, team_index: int) -> str:
    """Голеадоры одного клуба."""
    teams = teams_ordered_for_goalscorers(league_code)
    if not (0 <= team_index < len(teams)):
        raise IndexError("Некорректный выбор команды")
    team = teams[team_index]
    tournament = "cl" if league_code == "cl" else "league"
    import teams as teams_mod
    from player_stats import format_team_goalscorers_table_str

    standings_by_code = {
        "rpl": teams_mod.teams_rpl,
        "eng": teams_mod.teams_eng,
        "esp": teams_mod.teams_spain,
        "ita": teams_mod.teams_italy,
        "ger": teams_mod.teams_germany,
        "cl": teams_mod.teams_champ_league,
    }
    standings = standings_by_code.get(league_code)
    return format_team_goalscorers_table_str(team, tournament, standings)


def _archived_season_db_path_for_goalscorers(season_num: int, league_code: str) -> str | None:
    """Путь к league.db или champions_league.db в архиве сезона."""
    import os

    from utils import season_paths

    base = season_paths.season_archive_directory(int(season_num))
    if league_code == "cl":
        p = os.path.join(base, season_paths.SEASON_CL_NAME)
    else:
        p = os.path.join(base, season_paths.SEASON_LEAGUE_NAME)
    return p if os.path.isfile(p) else None


def render_archived_season_team_goalscorers_league(
    season_num: int, league_code: str
) -> str:
    """Голеадоры по всем клубам лиги из архива ``db/season_n``."""
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker

    from player_stats import format_team_goalscorers_league_report

    p = _archived_season_db_path_for_goalscorers(season_num, league_code)
    if not p:
        return (
            f"Нет файла БД для сезона {int(season_num)} "
            f"({'ЛЧ' if league_code == 'cl' else 'лига'}): проверьте db/season_{int(season_num)}/."
        )
    e = create_engine(f"sqlite:///{p}")
    S = sessionmaker(bind=e)()
    try:
        suf = f"сезон {int(season_num)} (архив)"
        teams_order: list[str] | None = None
        if league_code == "cl":
            teams_order = cl_team_names_from_champions_db(p)
            if not teams_order:
                teams_order = _cl_teams_from_season_pickle(int(season_num))
        return format_team_goalscorers_league_report(
            league_code,
            session=S,
            title_suffix=suf,
            teams_order=teams_order,
        )
    finally:
        S.close()
        e.dispose()


def render_archived_season_team_goalscorers_single(
    season_num: int, league_code: str, team_index: int
) -> str:
    """Голеадоры одного клуба из архива ``db/season_n``."""
    import teams as teams_mod
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker

    from player_stats import format_team_goalscorers_table_str

    p = _archived_season_db_path_for_goalscorers(season_num, league_code)
    if not p:
        return (
            f"Нет файла БД для сезона {int(season_num)}: "
            f"проверьте db/season_{int(season_num)}/."
        )
    teams = teams_ordered_for_goalscorers_season_archive(season_num, league_code)
    if not (0 <= team_index < len(teams)):
        raise IndexError("Некорректный выбор команды")
    team = teams[team_index]
    tournament = tournament_db_for_league(league_code)
    standings_by_code = {
        "rpl": teams_mod.teams_rpl,
        "eng": teams_mod.teams_eng,
        "esp": teams_mod.teams_spain,
        "ita": teams_mod.teams_italy,
        "ger": teams_mod.teams_germany,
        "cl": teams_mod.teams_champ_league,
    }
    standings = standings_by_code.get(league_code)
    if league_code == "cl":
        standings = None
    e = create_engine(f"sqlite:///{p}")
    S = sessionmaker(bind=e)()
    try:
        suf = f"сезон {int(season_num)} (архив)"
        return format_team_goalscorers_table_str(
            team, tournament, standings, session=S, title_suffix=suf
        )
    finally:
        S.close()
        e.dispose()


def render_top100_all_leagues(sort_key: int = 1, limit: int = 100) -> str:
    """Топ-100 объединённая БД — как «b»→5; sort_key 1/2/3."""
    from player_stats import format_all_leagues_combined_list_str

    return format_all_leagues_combined_list_str(limit=limit, sort_key=sort_key)


def render_schedule_mixed(
    league_filter: str | None,
    match_filter_code: str,
    session_kind: str | None = None,
) -> str:
    """
    Смешанное расписание матч-дней.
    league_filter: None — все лиги, иначе код лиги (например cl).
    match_filter_code: all | remaining | played
    session_kind: None | ``sim`` | ``game`` — фильтр по парам менеджеров / типу записи в журнале.
    """
    from main import load_or_generate_mixed_schedule

    from schedule_view import (
        MATCH_FILTER_ALL,
        MATCH_FILTER_PLAYED,
        MATCH_FILTER_REMAINING,
        print_journal_played_matches,
        print_mixed_schedule,
    )

    mf_map = {
        "all": MATCH_FILTER_ALL,
        "remaining": MATCH_FILTER_REMAINING,
        "played": MATCH_FILTER_PLAYED,
    }
    sk = session_kind if session_kind in ("sim", "game") else None
    mf = mf_map.get(match_filter_code, MATCH_FILTER_ALL)
    mixed = load_or_generate_mixed_schedule()

    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        if match_filter_code == "played":
            if league_filter is None:
                print_journal_played_matches(
                    league_code=None,
                    team_query="",
                    title="Сыгранные матчи — все лиги (журнал)",
                    session_kind=sk,
                )
            else:
                from player_stats import LEAGUE_NAMES

                nm = LEAGUE_NAMES.get(league_filter, league_filter)
                print_journal_played_matches(
                    league_code=league_filter,
                    team_query="",
                    title=f"Сыгранные матчи — {nm} ({league_filter}), журнал",
                    session_kind=sk,
                )
        else:
            from player_stats import LEAGUE_NAMES

            lc = league_filter
            if lc is None:
                title = "Смешанное расписание — все лиги"
            elif lc == "cl":
                title = "Смешанное расписание — только Лига чемпионов"
            else:
                title = (
                    f"Смешанное расписание — только "
                    f"{LEAGUE_NAMES.get(lc, lc)} ({lc})"
                )
            print_mixed_schedule(
                mixed,
                title=title,
                league_code=lc,
                team_query="",
                match_filter=mf,
                session_kind=sk,
            )
    return buf.getvalue()


def render_schedule_intrinsic_rounds(
    league_code: str,
    match_filter_code: str,
    session_kind: str | None = None,
) -> str:
    """Официальный календарь лиги по турам — режим «v»→4."""
    from schedule_view import (
        MATCH_FILTER_ALL,
        MATCH_FILTER_PLAYED,
        MATCH_FILTER_REMAINING,
        print_intrinsic_schedule,
        print_journal_played_matches,
    )

    mf_map = {
        "all": MATCH_FILTER_ALL,
        "remaining": MATCH_FILTER_REMAINING,
        "played": MATCH_FILTER_PLAYED,
    }
    mf = mf_map.get(match_filter_code, MATCH_FILTER_ALL)
    sk = session_kind if session_kind in ("sim", "game") else None

    titles = {
        "rpl": "РПЛ — туры",
        "eng": "АПЛ — туры",
        "esp": "Ла Лига — туры",
        "ita": "Серия А — туры",
        "ger": "Бундеслига — туры",
        "cl": "ЛЧ (групповый календарь) — туры",
    }
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        if match_filter_code == "played":
            print_journal_played_matches(
                league_code=league_code,
                team_query="",
                title=f"Сыгранные — {titles.get(league_code, league_code)} (журнал)",
                session_kind=sk,
            )
        else:
            print_intrinsic_schedule(
                league_code,
                title=titles.get(league_code, league_code),
                team_query="",
                match_filter=mf,
                session_kind=sk,
            )
    return buf.getvalue()


def render_next_match_text() -> str:
    """Как «n» — следующий несыгранный слот по mixed_schedule."""
    from config.leagues_config import manager_session_label
    from main import find_next_match_in_schedule, load_or_generate_mixed_schedule
    from player_stats import LEAGUE_NAMES
    from utils.schedule_by_months import read_mixed_slot_label
    from main import MIXED_SCHEDULE_FILE

    slot_label = read_mixed_slot_label(MIXED_SCHEDULE_FILE)
    sch = load_or_generate_mixed_schedule()
    day, mstr, home, away, lg = find_next_match_in_schedule(sch)
    if day is None:
        return (
            "Следующего матча нет: всё сыграно по журналу или оставшиеся слоты в списке отложенных."
        )
    lg_title = LEAGUE_NAMES.get(lg, lg)
    mode = manager_session_label(home, away)
    head = f"{mode}\n" if mode else ""
    return (
        f"{head}"
        f"Следующий по календарю — {slot_label.lower()} {day}\n"
        f"{home} — {away}\n"
        f"Лига: {lg_title}\n"
        f"Слот: {mstr}"
    )


def render_schedule_queue_text(limit: int = 18) -> str:
    """Первые N оставшихся матчей в порядке календаря (как обзор «v», без фильтров)."""
    from main import (
        _skipped_matches_slot,
        get_teams_by_league,
        is_match_played,
        load_or_generate_mixed_schedule,
        MIXED_SCHEDULE_FILE,
    )
    from match_results import cl_phase_from_mixed_schedule_line
    from skipped_matches import load_skipped_matches
    from player_stats import LEAGUE_NAMES
    from utils.schedule_by_months import read_mixed_slot_label

    slot_label = read_mixed_slot_label(MIXED_SCHEDULE_FILE)
    mixed = load_or_generate_mixed_schedule()
    skipped = load_skipped_matches()
    lines: list[str] = []
    n = 0
    for day_data in mixed:
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
            nm = LEAGUE_NAMES.get(league_code, league_code)
            lines.append(
                f"{slot_label.lower()} {day_num} · [{nm}] {home} — {away}"
            )
            n += 1
            if n >= limit:
                return (
                    f"Очередь календаря (первые {limit} матчей)\n\n" + "\n".join(lines)
                )
    if not lines:
        return "Очередь пуста — нет несыгранных слотов вне отложенных."
    return f"Очередь календаря (все {len(lines)} оставшихся)\n\n" + "\n".join(lines)


def render_skipped_matches_text() -> str:
    """Как «s» — содержимое skipped_matches.json."""
    leagues = {
        "rpl": "РПЛ",
        "eng": "АПЛ",
        "esp": "Ла Лига",
        "ger": "Бундеслига",
        "ita": "Серия А",
        "cl": "Лига Чемпионов",
    }
    from skipped_matches import load_skipped_matches

    matches = load_skipped_matches()
    if not matches:
        return "Нет пропущенных матчей (skipped_matches.json пуст)."

    lines: list[str] = ["ПРОПУЩЕННЫЕ МАТЧИ", ""]
    by_league: dict[str, list] = {}
    for m in matches:
        by_league.setdefault(m["tournament"], []).append(m)

    order = ("rpl", "eng", "esp", "ita", "ger", "cl")

    def _key(c: str) -> tuple:
        return (order.index(c) if c in order else 99, c)

    idx = 1
    for league_code in sorted(by_league.keys(), key=_key):
        league_matches = by_league[league_code]
        league_name = leagues.get(league_code, league_code)
        lines.append(f"{league_name}:")
        lines.append("-" * 40)
        league_matches.sort(key=lambda x: x["round"])
        for m in league_matches:
            extra = ""
            if league_code == "cl" and m.get("cl_phase"):
                extra = f" | фаза {m['cl_phase']}"
            lines.append(f"  {idx}. Тур {m['round']}: {m['home']} — {m['away']}{extra}")
            idx += 1
        lines.append("")
    return "\n".join(lines).rstrip()


def render_journal_report(limit: int = 120) -> str:
    """Как «j» — хвост журнала match_results."""
    from match_results import format_played_matches_report

    return format_played_matches_report(limit=limit)


def render_cumulative_top_scorers(league_code: str | None, limit: int = 30) -> str:
    """Топ бомбардиров из db/common_synced.db (накопление по всем сезонам)."""
    import os

    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker

    import player_stats
    from utils import season_paths

    p = season_paths.get_cumulative_common_db_path()
    if not os.path.isfile(p):
        return (
            "Накопительная база ещё пуста. После первого «Завершить сезон» "
            "заполняются db/league_synced.db, db/champions_league_synced.db и db/common_synced.db."
        )
    e = create_engine(f"sqlite:///{p}")
    S = sessionmaker(bind=e)()
    try:
        lc = None if not league_code or league_code in ("a", "all") else league_code
        return player_stats.format_top_scorers_from_session(
            S,
            league_code=lc,
            limit=limit,
            title_suffix=" — все сезоны (common_synced.db)",
        )
    finally:
        S.close()
        e.dispose()


def render_cumulative_top_assists(league_code: str | None, limit: int = 30) -> str:
    """Топ ассистов из db/common_synced.db (все сезоны)."""
    import os

    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker

    import player_stats
    from utils import season_paths

    p = season_paths.get_cumulative_common_db_path()
    if not os.path.isfile(p):
        return (
            "Накопительная база ещё пуста. После первого «Завершить сезон» "
            "заполняются db/league_synced.db, db/champions_league_synced.db и db/common_synced.db."
        )
    e = create_engine(f"sqlite:///{p}")
    S = sessionmaker(bind=e)()
    try:
        lc = None if not league_code or league_code in ("a", "all") else league_code
        return player_stats.format_top_assists_from_session(
            S,
            league_code=lc,
            limit=limit,
            title_suffix=" — все сезоны (common_synced.db)",
        )
    finally:
        S.close()
        e.dispose()


def render_cumulative_top_ga(league_code: str | None, limit: int = 30) -> str:
    """Топ Г+А из db/common_synced.db (все сезоны)."""
    import os

    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker

    import player_stats
    from utils import season_paths

    p = season_paths.get_cumulative_common_db_path()
    if not os.path.isfile(p):
        return (
            "Накопительная база ещё пуста. После первого «Завершить сезон» "
            "заполняются db/league_synced.db, db/champions_league_synced.db и db/common_synced.db."
        )
    e = create_engine(f"sqlite:///{p}")
    S = sessionmaker(bind=e)()
    try:
        lc = None if not league_code or league_code in ("a", "all") else league_code
        return player_stats.format_top_ga_from_session(
            S,
            league_code=lc,
            limit=limit,
            title_suffix=" — все сезоны (common_synced.db)",
        )
    finally:
        S.close()
        e.dispose()


def _league_team_set_for_filter(league_code: str | None) -> set[str] | None:
    if not league_code or league_code in ("a", "all"):
        return None
    if league_code == "cl":
        import teams as teams_mod

        return {str(t).strip().casefold() for t in teams_mod.teams_champ_league.keys()}
    from player_stats import LEAGUE_TEAMS

    teams = LEAGUE_TEAMS.get(league_code)
    if not teams:
        return None
    return {str(t).strip().casefold() for t in teams if str(t).strip()}


def _render_cards_from_session(session, *, league_code: str | None, metric: str, limit: int, title_suffix: str) -> str:
    from data.defender import Defender
    from data.forward import Forward
    from data.goalkeeper import Goalkeeper
    from data.midfielder import Midfielder

    m = metric.lower()
    field = "yellow_cards" if m == "yc" else "red_cards"
    title = "жёлтые карточки" if m == "yc" else "красные карточки"
    team_set = _league_team_set_for_filter(league_code)
    rows: list[tuple[str, str, int, int]] = []
    for Cls in (Forward, Midfielder, Defender, Goalkeeper):
        for r in session.query(Cls).all():
            if team_set is not None and str(getattr(r, "team", "")).strip().casefold() not in team_set:
                continue
            val = int(getattr(r, field, 0) or 0)
            if val <= 0:
                continue
            rows.append(
                (
                    str(getattr(r, "name", "")).strip(),
                    str(getattr(r, "team", "")).strip(),
                    val,
                    int(getattr(r, "matches", 0) or 0),
                )
            )
    rows.sort(key=lambda x: (-x[2], -x[3], x[0].casefold()))
    out = [f"Топ {title}{title_suffix}"]
    if league_code and league_code not in ("a", "all"):
        out.append(f"Лига: {dict(LEAGUE_LABELS).get(league_code, league_code)}")
    out.append("")
    if not rows:
        out.append("Нет данных.")
        return "\n".join(out)
    out.append(f"{'№':>2} {'Игрок':<24} {'Клуб':<18} {'Матч':>5} {'Знач':>5}")
    for i, (nm, tm, val, mcnt) in enumerate(rows[:limit], start=1):
        out.append(f"{i:>2} {nm[:24]:<24} {tm[:18]:<18} {mcnt:>5} {val:>5}")
    return "\n".join(out)


def _render_clean_sheets_from_session(session, *, league_code: str | None, limit: int, title_suffix: str) -> tuple[str, str]:
    from data.defender import Defender
    from data.goalkeeper import Goalkeeper

    team_set = _league_team_set_for_filter(league_code)

    def _collect(Cls) -> list[tuple[str, str, int, int]]:
        out: list[tuple[str, str, int, int]] = []
        for r in session.query(Cls).all():
            if team_set is not None and str(getattr(r, "team", "")).strip().casefold() not in team_set:
                continue
            cs = int(getattr(r, "clean_sheets", 0) or 0)
            if cs <= 0:
                continue
            out.append(
                (
                    str(getattr(r, "name", "")).strip(),
                    str(getattr(r, "team", "")).strip(),
                    cs,
                    int(getattr(r, "matches", 0) or 0),
                )
            )
        out.sort(key=lambda x: (-x[2], -x[3], x[0].casefold()))
        return out

    def _fmt(rows: list[tuple[str, str, int, int]], role: str) -> str:
        title = f"Сухие матчи · {role}{title_suffix}"
        out = [title]
        if league_code and league_code not in ("a", "all"):
            out.append(f"Лига: {dict(LEAGUE_LABELS).get(league_code, league_code)}")
        out.append("")
        if not rows:
            out.append("Нет данных.")
            return "\n".join(out)
        out.append(f"{'№':>2} {'Игрок':<24} {'Клуб':<18} {'Матч':>5} {'Сух':>5}")
        for i, (nm, tm, cs, mcnt) in enumerate(rows[:limit], start=1):
            out.append(f"{i:>2} {nm[:24]:<24} {tm[:18]:<18} {mcnt:>5} {cs:>5}")
        return "\n".join(out)

    return _fmt(_collect(Goalkeeper), "вратари"), _fmt(_collect(Defender), "защитники")


def render_cumulative_top_cards(league_code: str | None, metric: str, limit: int = 30) -> str:
    import os

    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker
    from utils import season_paths

    p = season_paths.get_cumulative_common_db_path()
    if not os.path.isfile(p):
        return (
            "Накопительная база ещё пуста. После первого «Завершить сезон» "
            "заполняются db/league_synced.db, db/champions_league_synced.db и db/common_synced.db."
        )
    e = create_engine(f"sqlite:///{p}")
    S = sessionmaker(bind=e)()
    try:
        lc = None if not league_code or league_code in ("a", "all") else league_code
        return _render_cards_from_session(
            S, league_code=lc, metric=metric, limit=limit, title_suffix=" — все сезоны (common_synced.db)"
        )
    finally:
        S.close()
        e.dispose()


def render_cumulative_top_clean_sheets(league_code: str | None, limit: int = 30) -> tuple[str, str]:
    import os

    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker
    from utils import season_paths

    p = season_paths.get_cumulative_common_db_path()
    if not os.path.isfile(p):
        msg = (
            "Накопительная база ещё пуста. После первого «Завершить сезон» "
            "заполняются db/league_synced.db, db/champions_league_synced.db и db/common_synced.db."
        )
        return msg, msg
    e = create_engine(f"sqlite:///{p}")
    S = sessionmaker(bind=e)()
    try:
        lc = None if not league_code or league_code in ("a", "all") else league_code
        return _render_clean_sheets_from_session(
            S, league_code=lc, limit=limit, title_suffix=" — все сезоны (common_synced.db)"
        )
    finally:
        S.close()
        e.dispose()


def render_archived_season_stat(
    season_num: int,
    league_code: str | None,
    metric: str,
    limit: int = 30,
) -> str:
    """
    Топ из архива ``db/season_n``: ``g`` | ``as`` | ``ga`` | ``yc`` | ``rc``.

    Одна БД по выбранной кнопке: **ЛЧ** — только ``champions_league.db``; любая нац. лига
    или «все» — только ``league.db`` (без подмешивания ЛЧ).
    """
    import os

    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker

    import player_stats
    from utils import season_paths

    m = (metric or "g").lower()
    if m in ("goals", "g"):
        mkey = "g"
    elif m in ("assists", "as", "a"):
        mkey = "as"
    elif m in ("ga", "g+a"):
        mkey = "ga"
    elif m in ("yc", "yellow", "yellow_cards"):
        mkey = "yc"
    elif m in ("rc", "red", "red_cards"):
        mkey = "rc"
    else:
        return f"Неизвестная метрика: {metric!r}"

    base = season_paths.season_archive_directory(season_num)
    lp = os.path.join(base, season_paths.SEASON_LEAGUE_NAME)
    cp = os.path.join(base, season_paths.SEASON_CL_NAME)
    lc = None if not league_code or league_code in ("a", "all") else league_code
    suf = f" — сезон {season_num} (архив)"

    def _block(session, filter_code: str | None, db_label: str) -> str:
        tsuf = f"{suf} · {db_label}"
        if mkey == "g":
            return player_stats.format_top_scorers_from_session(
                session, league_code=filter_code, limit=limit, title_suffix=tsuf
            )
        if mkey == "as":
            return player_stats.format_top_assists_from_session(
                session, league_code=filter_code, limit=limit, title_suffix=tsuf
            )
        if mkey == "ga":
            return player_stats.format_top_ga_from_session(
                session, league_code=filter_code, limit=limit, title_suffix=tsuf
            )
        return _render_cards_from_session(
            session, league_code=filter_code, metric=mkey, limit=limit, title_suffix=tsuf
        )

    if lc == "cl":
        if not os.path.isfile(cp):
            return f"В архиве нет champions_league.db для сезона {season_num}."
        ec = create_engine(f"sqlite:///{cp}")
        Sc = sessionmaker(bind=ec)()
        try:
            return _block(Sc, "cl", "champions_league.db (только ЛЧ)").rstrip()
        finally:
            Sc.close()
            ec.dispose()

    if not os.path.isfile(lp):
        return f"В архиве нет league.db для сезона {season_num}."
    el = create_engine(f"sqlite:///{lp}")
    Sl = sessionmaker(bind=el)()
    try:
        return _block(Sl, lc, "league.db (только национальные матчи)").rstrip()
    finally:
        Sl.close()
        el.dispose()


def render_archived_season_top_scorers(
    season_num: int,
    league_code: str | None,
    limit: int = 30,
) -> str:
    """Топ бомбардиров из архива db/season_n."""
    return render_archived_season_stat(season_num, league_code, "g", limit)


def render_archived_season_clean_sheets(
    season_num: int,
    league_code: str | None,
    limit: int = 30,
) -> tuple[str, str]:
    """Сухие из архива: только ``league.db`` для нац. лиг / «все», только ``champions_league.db`` для ЛЧ."""
    import os

    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker
    from utils import season_paths

    base = season_paths.season_archive_directory(season_num)
    lp = os.path.join(base, season_paths.SEASON_LEAGUE_NAME)
    cp = os.path.join(base, season_paths.SEASON_CL_NAME)
    suf = f" — сезон {season_num} (архив)"
    lc = None if not league_code or league_code in ("a", "all") else league_code

    if lc == "cl":
        if not os.path.isfile(cp):
            msg = f"В архиве сезона {season_num} нет champions_league.db."
            return msg, msg
        ec = create_engine(f"sqlite:///{cp}")
        Sc = sessionmaker(bind=ec)()
        try:
            return _render_clean_sheets_from_session(
                Sc,
                league_code="cl",
                limit=limit,
                title_suffix=f"{suf} · champions_league.db (только ЛЧ)",
            )
        finally:
            Sc.close()
            ec.dispose()

    if not os.path.isfile(lp):
        msg = f"В архиве сезона {season_num} нет league.db."
        return msg, msg
    el = create_engine(f"sqlite:///{lp}")
    Sl = sessionmaker(bind=el)()
    try:
        return _render_clean_sheets_from_session(
            Sl,
            league_code=lc,
            limit=limit,
            title_suffix=f"{suf} · league.db (только национальные матчи)",
        )
    finally:
        Sl.close()
        el.dispose()


def split_text_chunks(text: str, max_len: int = 3800) -> list[str]:
    """Не рвём UTF-8 и по возможности по строкам."""
    if len(text) <= max_len:
        return [text]
    lines = text.split("\n")
    chunks: list[str] = []
    cur: list[str] = []
    cur_len = 0
    for line in lines:
        add = len(line) + (1 if cur else 0)
        if cur and cur_len + add > max_len:
            chunks.append("\n".join(cur))
            cur = [line]
            cur_len = len(line)
        else:
            cur.append(line)
            cur_len += add
    if cur:
        chunks.append("\n".join(cur))
    return chunks


def to_pre_html(text: str) -> str:
    return f"<pre>{html_escape(text)}</pre>"


def needs_cl_penalty_shootout(
    home: str,
    away: str,
    home_score: int,
    away_score: int,
    league_code: str,
    cl_phase: str | None,
) -> bool:
    """
    Нужен ли ввод серии пенальти (ответный матч нокаута ЛЧ, ничья по сумме двух матчей).
    Имена команд — как в process_match (.title()).
    """
    if league_code != "cl":
        return False
    from main import cl_knockout_aggregate_tie_needs_penalties

    h = home.strip().title()
    a = away.strip().title()
    return cl_knockout_aggregate_tie_needs_penalties(
        h, a, home_score, away_score, cl_phase
    )


def run_process_match_bot(
    home: str,
    away: str,
    home_score: int,
    away_score: int,
    league_code: str,
    *,
    round_num: int | None = None,
    cl_phase: str | None = None,
    penalties_override: dict[str, int] | None = None,
) -> tuple[bool, str]:
    """
    Запись матча как в main.process_match, без input().
    penalties_override — {хозяева ответного: голы в серии, гости: ...} для ЛЧ-стыка.
    """
    import contextlib
    import io

    from main import process_match

    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        ok = process_match(
            home,
            away,
            home_score,
            away_score,
            league_code,
            round_num=round_num,
            with_stats=False,
            cl_phase=cl_phase,
            interactive=False,
            penalties_override=penalties_override,
        )
    if ok:
        try:
            from utils.player_loans import process_loan_expirations

            process_loan_expirations(round_num)
        except Exception:
            logging.getLogger(__name__).exception("process_loan_expirations")
    return ok, (buf.getvalue() or "").strip()
