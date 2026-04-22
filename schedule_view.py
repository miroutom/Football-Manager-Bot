# -*- coding: utf-8 -*-
"""
Просмотр расписания из mixed_schedule.json и официальных календарей лиг (table.schedule).

Не изменяет данные — только вывод в консоль.

Режим матчей: всё подряд / только ещё не сыгранные по журналу / только уже сыгранные.
"""
from __future__ import annotations

import os
from typing import Callable, Iterable, Optional

from match_results import (
    cl_phase_from_mixed_schedule_line,
    is_match_played as journal_match_played,
    load_records_and_keys,
)
from skipped_matches import load_skipped_matches
from utils.utils import PROJECT_ROOT

MIXED_SCHEDULE_FILE = os.path.join(PROJECT_ROOT, "mixed_schedule.json")


def _skipped_slot(skip: dict, home: str, away: str, league_code: str, cl_phase_expected) -> bool:
    """Совпадение слота с пропуском (как в main.py)."""
    if skip["home"] != home or skip["away"] != away:
        return False
    if skip["tournament"] != league_code:
        return False
    if league_code != "cl":
        return True
    sp = skip.get("cl_phase") or "knockout"
    ep = cl_phase_expected or "knockout"
    return sp == ep


def _mixed_line_is_remaining(line: str, _match_day: int, skipped: list) -> bool:
    """Не в журнале как сыгранный и не в пропущенных (логика как у «следующий матч»)."""
    parts = line.split(";")
    if len(parts) < 3:
        return False
    home, away, league_code = parts[0].strip(), parts[1].strip(), parts[2].strip()
    from teams import (
        teams_champ_league,
        teams_eng,
        teams_germany,
        teams_italy,
        teams_rpl,
        teams_spain,
    )

    teams_map = {
        "rpl": teams_rpl,
        "eng": teams_eng,
        "esp": teams_spain,
        "ita": teams_italy,
        "ger": teams_germany,
        "cl": teams_champ_league,
    }
    teams = teams_map.get(league_code)
    if not teams:
        return True
    cl_ph = cl_phase_from_mixed_schedule_line(line) if league_code == "cl" else None
    ht, at = home.title(), away.title()
    if ht not in teams or at not in teams:
        return True
    if journal_match_played(ht, at, league_code, cl_phase=cl_ph):
        return False
    if any(_skipped_slot(s, home, away, league_code, cl_ph) for s in skipped):
        return False
    return True


def _intrinsic_line_is_remaining(line: str) -> bool:
    """Туровое расписание: матч ещё не в журнале как сыгранный."""
    parts = line.split(";")
    if len(parts) < 3:
        return False
    home, away, league_code = parts[0].strip(), parts[1].strip(), parts[2].strip()
    cl_ph = cl_phase_from_mixed_schedule_line(line) if league_code == "cl" else None
    ht, at = home.title(), away.title()
    return not journal_match_played(ht, at, league_code, cl_phase=cl_ph)


def _mixed_line_is_played(line: str, _skipped: list) -> bool:
    """Слот из смешанного расписания уже занесён в журнал как сыгранный."""
    parts = line.split(";")
    if len(parts) < 3:
        return False
    home, away, league_code = parts[0].strip(), parts[1].strip(), parts[2].strip()
    from teams import (
        teams_champ_league,
        teams_eng,
        teams_germany,
        teams_italy,
        teams_rpl,
        teams_spain,
    )

    teams_map = {
        "rpl": teams_rpl,
        "eng": teams_eng,
        "esp": teams_spain,
        "ita": teams_italy,
        "ger": teams_germany,
        "cl": teams_champ_league,
    }
    teams = teams_map.get(league_code)
    if not teams:
        return False
    cl_ph = cl_phase_from_mixed_schedule_line(line) if league_code == "cl" else None
    ht, at = home.title(), away.title()
    if ht not in teams or at not in teams:
        return False
    return journal_match_played(ht, at, league_code, cl_phase=cl_ph)


def _intrinsic_line_is_played(line: str) -> bool:
    """Туровый матч уже есть в журнале."""
    parts = line.split(";")
    if len(parts) < 3:
        return False
    home, away, league_code = parts[0].strip(), parts[1].strip(), parts[2].strip()
    cl_ph = cl_phase_from_mixed_schedule_line(line) if league_code == "cl" else None
    ht, at = home.title(), away.title()
    return journal_match_played(ht, at, league_code, cl_phase=cl_ph)


# Фильтр строк расписания: all | remaining | played
MATCH_FILTER_ALL = "all"
MATCH_FILTER_REMAINING = "remaining"
MATCH_FILTER_PLAYED = "played"


def print_journal_played_matches(
    *,
    league_code: Optional[str],
    team_query: str,
    title: str,
) -> None:
    """
    Все сыгранные матчи из match_results.json по лиге (или по всем лигам).

    Не ограничивается смешанным календарём — только журнал и счёт.
    """
    records, _ = load_records_and_keys()
    q = _norm_q(team_query)
    rows: list[tuple] = []
    for r in records:
        leg = str(r.get("league") or "").strip()
        if league_code is not None and leg != league_code:
            continue
        hs, aws = r.get("home_score"), r.get("away_score")
        if hs is None or aws is None:
            continue
        try:
            hi, ai = int(hs), int(aws)
        except (TypeError, ValueError):
            continue
        h = str(r.get("home") or "").strip()
        a = str(r.get("away") or "").strip()
        if q and not (
            team_matches_query(h, q) or team_matches_query(a, q)
        ):
            continue
        day = r.get("day")
        cl_ph = r.get("cl_phase")
        rows.append((day, h, a, leg, hi, ai, cl_ph))

    rows.sort(key=lambda x: (x[0] if isinstance(x[0], int) else 99999, x[1], x[2]))

    print("\n" + "=" * 70)
    print(f"  {title}")
    note = (
        "  (полный журнал сыгранных для выбранной лиги — все матчи из match_results,"
        "\n    не только строки смешанного календаря матч-дней)"
        if league_code is not None
        else (
            "  (все сыгранные записи из match_results по всем лигам)"
        )
    )
    print(note)
    if q:
        print(f"  (фильтр команды: «{_norm_q(team_query)}»)")
    print("=" * 70)
    if not rows:
        print("  Нет записей с счётом по условию.")
        return
    for day, h, a, leg, hi, ai, cl_ph in rows:
        extra = []
        if isinstance(day, int):
            extra.append(f"тур/день {day}")
        if leg == "cl" and cl_ph:
            extra.append(f"фаза {cl_ph}")
        tail = ("  |  " + ", ".join(extra)) if extra else ""
        print(f"    {h};{a};{leg}  {hi}:{ai}{tail}")
    print(f"\n  Всего: {len(rows)} матчей")


def _norm_q(s: str) -> str:
    return (s or "").strip()


def team_matches_query(team_name: str, query: str) -> bool:
    """Подстрочное совпадение без учёта регистра (название команды из строки расписания)."""
    q = _norm_q(query).lower()
    if not q:
        return True
    t = _norm_q(team_name).lower()
    return q in t or t.startswith(q)


def load_mixed_schedule_from_disk() -> list:
    import json

    if not os.path.isfile(MIXED_SCHEDULE_FILE):
        return []
    with open(MIXED_SCHEDULE_FILE, "r", encoding="utf-8") as f:
        return json.load(f)


def iter_mixed_filtered(
    mixed_schedule: list,
    *,
    league_code: Optional[str] = None,
    team_query: str = "",
    match_filter: str = MATCH_FILTER_ALL,
    skipped_list: Optional[list] = None,
) -> Iterable[tuple[int, str]]:
    """Пары (день, строка матча)."""
    q = _norm_q(team_query)
    skipped = skipped_list if skipped_list is not None else load_skipped_matches()
    mf = match_filter if match_filter in (
        MATCH_FILTER_ALL,
        MATCH_FILTER_REMAINING,
        MATCH_FILTER_PLAYED,
    ) else MATCH_FILTER_ALL
    for day_data in mixed_schedule:
        day = int(day_data.get("day", 0))
        for line in day_data.get("matches", []):
            parts = line.split(";")
            if len(parts) < 3:
                continue
            if league_code is not None and parts[2].strip() != league_code:
                continue
            if mf == MATCH_FILTER_REMAINING and not _mixed_line_is_remaining(
                line, day, skipped
            ):
                continue
            if mf == MATCH_FILTER_PLAYED and not _mixed_line_is_played(line, skipped):
                continue
            if q:
                home, away = parts[0].strip(), parts[1].strip()
                if not (
                    team_matches_query(home, q) or team_matches_query(away, q)
                ):
                    continue
            yield day, line


def print_mixed_schedule(
    mixed_schedule: list,
    *,
    title: str,
    league_code: Optional[str] = None,
    team_query: str = "",
    match_filter: str = MATCH_FILTER_ALL,
) -> None:
    lines_out: list[tuple[int, str]] = list(
        iter_mixed_filtered(
            mixed_schedule,
            league_code=league_code,
            team_query=team_query,
            match_filter=match_filter,
        )
    )
    print("\n" + "=" * 70)
    print(f"  {title}")
    if match_filter == MATCH_FILTER_REMAINING:
        print("  (только не сыгранные: нет в журнале и не среди пропусков)")
    elif match_filter == MATCH_FILTER_PLAYED:
        print("  (только уже сыгранные по журналу match_results)")
    if team_query:
        print(f"  (фильтр команды: «{_norm_q(team_query)}»)")
    print("=" * 70)
    if not lines_out:
        print("  Нет матчей по условию.")
        return
    cur_day: int | None = None
    for day, line in lines_out:
        if cur_day != day:
            cur_day = day
            print(f"\n  --- Матч-день {day} ---")
        print(f"    {line}")


def print_intrinsic_schedule(
    league_code: str,
    *,
    title: str,
    team_query: str = "",
    match_filter: str = MATCH_FILTER_ALL,
) -> None:
    from table.schedule import get_schedule

    sch = get_schedule(league_code)
    print("\n" + "=" * 70)
    print(f"  {title}")
    mf = match_filter if match_filter in (
        MATCH_FILTER_ALL,
        MATCH_FILTER_REMAINING,
        MATCH_FILTER_PLAYED,
    ) else MATCH_FILTER_ALL
    if mf == MATCH_FILTER_REMAINING:
        print(
            "  (только не сыгранные по журналу; пропуски по турам не учитываются)"
        )
    elif mf == MATCH_FILTER_PLAYED:
        print("  (только уже сыгранные по журналу)")
    if team_query:
        print(f"  (фильтр команды: «{_norm_q(team_query)}»)")
    print("=" * 70)
    if not sch:
        print("  Расписание не найдено.")
        return
    q = _norm_q(team_query)
    any_printed = False
    for rnd in sorted(sch.keys()):
        chunk: list[str] = []
        for line in sch[rnd]:
            parts = line.split(";")
            if len(parts) < 2:
                continue
            if mf == MATCH_FILTER_REMAINING and not _intrinsic_line_is_remaining(line):
                continue
            if mf == MATCH_FILTER_PLAYED and not _intrinsic_line_is_played(line):
                continue
            if q:
                if not (
                    team_matches_query(parts[0], q)
                    or team_matches_query(parts[1], q)
                ):
                    continue
            chunk.append(line)
        if chunk:
            any_printed = True
            print(f"\n  --- Тур {rnd} ---")
            for line in chunk:
                print(f"    {line}")
    if not any_printed:
        print("  Нет матчей по условию.")


LEAGUE_MENU = """
  Коды лиг:
    1 — РПЛ (rpl)
    2 — АПЛ (eng)
    3 — Ла Лига (esp)
    4 — Серия А (ita)
    5 — Бундеслига (ger)
    6 — Лига чемпионов (cl)
"""


def browse_schedule_interactive(load_mixed: Callable[[], list]) -> None:
    """
    Интерактивное меню просмотра.

    ``load_mixed`` — обычно ``load_or_generate_mixed_schedule`` из main,
    чтобы файл создавался при отсутствии (как в основном цикле).
    """
    print("\n" + "=" * 70)
    print("  ПРОСМОТР РАСПИСАНИЯ")
    print("=" * 70)
    print(
        """
  Что смотреть:
    1 — всё смешанное расписание (матч-дни, все лиги)
    2 — только одна лига из смешанного (матч-дни)
    3 — только матчи ЛЧ из смешанного
    4 — календарь по турам (официальное расписание лиги из проекта)
"""
    )
    print(LEAGUE_MENU)

    mode = input("Выбор (1–4): ").strip()

    team_q = input(
        "\nКоманду для фильтра (подстрочный поиск, Enter — без фильтра): "
    ).strip()

    print(
        """
  Какие матчи показать:
    1 — всё расписание (как в файле календаря)
    2 — только оставшиеся (нет в журнале и не в пропусках смешанного календаря)
    3 — только уже сыгранные: полный список из журнала по лиге / ЛЧ (не только матч-дни)
"""
    )
    mf_raw = input("Выбор [1]: ").strip() or "1"
    mf_map = {"1": MATCH_FILTER_ALL, "2": MATCH_FILTER_REMAINING, "3": MATCH_FILTER_PLAYED}
    match_filter = mf_map.get(mf_raw, MATCH_FILTER_ALL)

    mixed = load_mixed()

    if mode == "1":
        if match_filter == MATCH_FILTER_PLAYED:
            print_journal_played_matches(
                league_code=None,
                team_query=team_q,
                title="Сыгранные матчи — все лиги (журнал)",
            )
        else:
            print_mixed_schedule(
                mixed,
                title="Смешанное расписание — все лиги",
                league_code=None,
                team_query=team_q,
                match_filter=match_filter,
            )
        return

    if mode == "2":
        lc = input(
            "Номер лиги 1–6 (см. список выше), например 2 для АПЛ: "
        ).strip()
        codes = {"1": "rpl", "2": "eng", "3": "esp", "4": "ita", "5": "ger", "6": "cl"}
        league_code = codes.get(lc)
        if not league_code:
            print("Неверный выбор.")
            return
        names = {
            "rpl": "РПЛ",
            "eng": "АПЛ",
            "esp": "Ла Лига",
            "ita": "Серия А",
            "ger": "Бундеслига",
            "cl": "ЛЧ",
        }
        if match_filter == MATCH_FILTER_PLAYED:
            print_journal_played_matches(
                league_code=league_code,
                team_query=team_q,
                title=f"Сыгранные матчи — {names[league_code]} ({league_code}), весь журнал",
            )
        else:
            print_mixed_schedule(
                mixed,
                title=f"Смешанное расписание — только {names[league_code]} ({league_code})",
                league_code=league_code,
                team_query=team_q,
                match_filter=match_filter,
            )
        return

    if mode == "3":
        if match_filter == MATCH_FILTER_PLAYED:
            print_journal_played_matches(
                league_code="cl",
                team_query=team_q,
                title="Сыгранные матчи ЛЧ — весь журнал (группа и нокаут)",
            )
        else:
            print_mixed_schedule(
                mixed,
                title="Смешанное расписание — только Лига чемпионов",
                league_code="cl",
                team_query=team_q,
                match_filter=match_filter,
            )
        return

    if mode == "4":
        lc = input(
            "Номер лиги 1–6 для календаря по турам: "
        ).strip()
        codes = {"1": "rpl", "2": "eng", "3": "esp", "4": "ita", "5": "ger", "6": "cl"}
        league_code = codes.get(lc)
        if not league_code:
            print("Неверный выбор.")
            return
        titles = {
            "rpl": "РПЛ — туры",
            "eng": "АПЛ — туры",
            "esp": "Ла Лига — туры",
            "ita": "Серия А — туры",
            "ger": "Бундеслига — туры",
            "cl": "ЛЧ (групповый календарь) — туры",
        }
        if match_filter == MATCH_FILTER_PLAYED:
            print_journal_played_matches(
                league_code=league_code,
                team_query=team_q,
                title=f"Сыгранные — {titles[league_code]} (журнал, все матчи лиги)",
            )
        else:
            print_intrinsic_schedule(
                league_code,
                title=titles[league_code],
                team_query=team_q,
                match_filter=match_filter,
            )
        return

    print("Неверный выбор.")
