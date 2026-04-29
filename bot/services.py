"""
Текстовые отчёты для Telegram: переиспользуют функции main/player_stats без дублирования логики.
"""
from __future__ import annotations

import contextlib
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


def render_standings(league_code: str) -> str:
    from main import LEAGUES, show_table

    league = next((x for x in LEAGUES.values() if x["code"] == league_code), None)
    if not league:
        return f"Неизвестная лига: {league_code}"
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        show_table(league["teams"], league["name"], league_code=league_code)
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
    """Топ бомбардиров: сумма лига + ЛЧ (common.db), как «b»→1+ в консоли."""
    from player_stats import show_top_scorers

    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        show_top_scorers("common", league_code, limit=limit)
    return buf.getvalue()


def render_top_assists_common(league_code: str, limit: int = 25) -> str:
    from player_stats import show_top_assistants

    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        show_top_assistants("common", league_code, limit=limit)
    return buf.getvalue()


def render_top_ga_common(league_code: str, limit: int = 25) -> str:
    from player_stats import show_top_ga

    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        show_top_ga("common", league_code, limit=limit)
    return buf.getvalue()


def render_team_goalscorers_league(league_code: str) -> str:
    """Голеадоры по всем командам лиги — как «b»→4."""
    from player_stats import format_team_goalscorers_league_report

    return format_team_goalscorers_league_report(league_code)


def teams_ordered_for_goalscorers(league_code: str) -> list[str]:
    """Клубы лиги в том же порядке, что и в полном отчёте «голеадоры по клубам»."""
    from player_stats import LEAGUE_TEAMS

    import teams as teams_mod

    if league_code == "cl":
        return sorted(teams_mod.teams_champ_league.keys())
    if league_code not in LEAGUE_TEAMS:
        raise ValueError(f"Неизвестная лига: {league_code}")
    return sorted(LEAGUE_TEAMS[league_code])


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


def render_top100_all_leagues(sort_key: int = 1, limit: int = 100) -> str:
    """Топ-100 объединённая БД — как «b»→5; sort_key 1/2/3."""
    from player_stats import format_all_leagues_combined_list_str

    return format_all_leagues_combined_list_str(limit=limit, sort_key=sort_key)


def render_schedule_mixed(league_filter: str | None, match_filter_code: str) -> str:
    """
    Смешанное расписание матч-дней.
    league_filter: None — все лиги, иначе код лиги (например cl).
    match_filter_code: all | remaining | played
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
                )
            else:
                from player_stats import LEAGUE_NAMES

                nm = LEAGUE_NAMES.get(league_filter, league_filter)
                print_journal_played_matches(
                    league_code=league_filter,
                    team_query="",
                    title=f"Сыгранные матчи — {nm} ({league_filter}), журнал",
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
            )
    return buf.getvalue()


def render_schedule_intrinsic_rounds(league_code: str, match_filter_code: str) -> str:
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
            )
        else:
            print_intrinsic_schedule(
                league_code,
                title=titles.get(league_code, league_code),
                team_query="",
                match_filter=mf,
            )
    return buf.getvalue()


def render_next_match_text() -> str:
    """Как «n» — следующий несыгранный слот по mixed_schedule."""
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
    return (
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


def render_archived_season_stat(
    season_num: int,
    league_code: str | None,
    metric: str,
    limit: int = 30,
) -> str:
    """
    Топ из архива db/season_n: metric — ``g`` | ``as`` | ``ga`` (пересборка common во временный файл).
    """
    import os
    import tempfile

    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker

    import player_stats
    from utils import season_paths
    from utils.common_db import rebuild_common_database_for_disk_paths

    m = (metric or "g").lower()
    if m in ("goals", "g"):
        mkey = "g"
    elif m in ("assists", "as", "a"):
        mkey = "as"
    elif m in ("ga", "g+a"):
        mkey = "ga"
    else:
        return f"Неизвестная метрика: {metric!r}"

    base = season_paths.season_archive_directory(season_num)
    lp = os.path.join(base, season_paths.SEASON_LEAGUE_NAME)
    cp = os.path.join(base, season_paths.SEASON_CL_NAME)
    if not os.path.isfile(lp):
        return f"В архиве нет league.db для сезона {season_num}."
    if not os.path.isfile(cp):
        return f"В архиве нет champions_league.db для сезона {season_num}."

    fd, tmp = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    suf = f" — сезон {season_num} (архив)"
    try:
        rebuild_common_database_for_disk_paths(lp, cp, tmp)
        e = create_engine(f"sqlite:///{tmp}")
        S = sessionmaker(bind=e)()
        try:
            lc = None if not league_code or league_code in ("a", "all") else league_code
            if mkey == "g":
                return player_stats.format_top_scorers_from_session(
                    S, league_code=lc, limit=limit, title_suffix=suf
                )
            if mkey == "as":
                return player_stats.format_top_assists_from_session(
                    S, league_code=lc, limit=limit, title_suffix=suf
                )
            return player_stats.format_top_ga_from_session(
                S, league_code=lc, limit=limit, title_suffix=suf
            )
        finally:
            S.close()
            e.dispose()
    finally:
        try:
            os.remove(tmp)
        except OSError:
            pass


def render_archived_season_top_scorers(
    season_num: int,
    league_code: str | None,
    limit: int = 30,
) -> str:
    """Топ бомбардиров из архива db/season_n."""
    return render_archived_season_stat(season_num, league_code, "g", limit)


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
    return ok, (buf.getvalue() or "").strip()
