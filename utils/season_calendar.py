# -*- coding: utf-8 -*-
"""
Календарь сезона: 10 месяцев с августа, дни внутри месяца.

``day`` в журнале / mixed_schedule — номер месяца сезона (1 = август … 10 = май).
``month_day`` — день внутри этого месяца (1..31).

Травмы: срок N месяцев = календарные месяцы от даты травмы (28 авг + 2 мес → 28 окт),
а не «с 1-го по 1-го следующего месяца».
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any

# Август … май (10 «игровых» месяцев)
SEASON_MONTH_NAMES_RU = (
    "август",
    "сентябрь",
    "октябрь",
    "ноябрь",
    "декабрь",
    "январь",
    "февраль",
    "март",
    "апрель",
    "май",
)
SEASON_MONTH_NAMES_RU_SHORT = (
    "авг",
    "сен",
    "окт",
    "ноя",
    "дек",
    "янв",
    "фев",
    "мар",
    "апр",
    "май",
)
DAYS_IN_SEASON_MONTH = (31, 30, 31, 30, 31, 31, 30, 31, 30, 31)
SEASON_MONTHS = len(DAYS_IN_SEASON_MONTH)
LEGACY_DEFAULT_MONTH_DAY = 15


@dataclass(frozen=True)
class SeasonDate:
    month: int
    day: int

    def __post_init__(self) -> None:
        m = int(self.month)
        d = int(self.day)
        if not (1 <= m <= SEASON_MONTHS):
            raise ValueError(f"month must be 1..{SEASON_MONTHS}, got {m}")
        max_d = days_in_month(m)
        if not (1 <= d <= max_d):
            raise ValueError(f"day must be 1..{max_d} for month {m}, got {d}")


def days_in_month(month: int) -> int:
    m = int(month)
    if 1 <= m <= SEASON_MONTHS:
        return DAYS_IN_SEASON_MONTH[m - 1]
    return 30


def season_date(month: int | None, day: int | None) -> SeasonDate:
    m = max(1, min(SEASON_MONTHS, int(month or 1)))
    d = int(day or LEGACY_DEFAULT_MONTH_DAY)
    d = max(1, min(days_in_month(m), d))
    return SeasonDate(m, d)


def to_ordinal(season: int, month: int, day: int) -> int:
    """Абсолютный индекс дня от начала сезона ``season`` (season 1 → 0)."""
    s = max(1, int(season))
    base = (s - 1) * sum(DAYS_IN_SEASON_MONTH)
    m = max(1, min(SEASON_MONTHS, int(month)))
    for i in range(1, m):
        base += DAYS_IN_SEASON_MONTH[i - 1]
    base += max(1, min(days_in_month(m), int(day))) - 1
    return base


def add_calendar_months(
    season: int,
    month: int,
    day: int,
    n_months: int,
) -> tuple[int, int, int]:
    """Прибавить ``n_months`` календарных месяцев сезона (день clamp по длине месяца)."""
    idx = int(month) - 1 + int(n_months)
    new_season = int(season) + idx // SEASON_MONTHS
    new_month = idx % SEASON_MONTHS + 1
    new_day = min(int(day), days_in_month(new_month))
    return new_season, new_month, new_day


def compare_dates(
    season_a: int,
    month_a: int,
    day_a: int,
    season_b: int,
    month_b: int,
    day_b: int,
) -> int:
    oa = to_ordinal(season_a, month_a, day_a)
    ob = to_ordinal(season_b, month_b, day_b)
    if oa < ob:
        return -1
    if oa > ob:
        return 1
    return 0


def format_month_name(month: int | None, *, short: bool = False) -> str:
    if month is None:
        return "—"
    try:
        m = int(month)
    except (TypeError, ValueError):
        return "—"
    if not (1 <= m <= SEASON_MONTHS):
        return f"{m} мес."
    names = SEASON_MONTH_NAMES_RU_SHORT if short else SEASON_MONTH_NAMES_RU
    return names[m - 1]


def format_season_date(month: int | None, day: int | None, *, short: bool = True) -> str:
    if month is None:
        return "—"
    d = int(day or LEGACY_DEFAULT_MONTH_DAY)
    mn = format_month_name(month, short=short)
    if short:
        return f"{d} {mn}"
    return f"{d} {mn}"


def format_season_date_range(
    out_month: int | None,
    out_day: int | None,
    ret_month: int | None,
    ret_day: int | None,
) -> str:
    a = format_season_date(out_month, out_day)
    b = format_season_date(ret_month, ret_day)
    return f"с {a} до {b}"


def parse_mixed_match_line(match_str: str) -> dict[str, Any]:
    """
    Разбор строки расписания.

    ``Home;Away;ger`` или ``Home;Away;ger;15``
    ``Home;Away;cl;league;15`` / ``Home;Away;cl;knockout;28``
    Последний числовой сегмент — ``month_day``.
    """
    from match_results import _normalize_cl_phase

    parts = [x.strip() for x in str(match_str or "").split(";") if x.strip()]
    if len(parts) < 3:
        return {
            "home": "",
            "away": "",
            "league_code": "",
            "cl_phase": None,
            "month_day": None,
            "match_str": match_str,
        }
    home, away, lg = parts[0], parts[1], parts[2].lower()
    month_day: int | None = None
    cl_phase: str | None = None
    tail = parts[3:]
    if tail and tail[-1].isdigit():
        month_day = int(tail.pop())
    if lg == "cl" and tail:
        cl_phase = _normalize_cl_phase(tail[0])
    return {
        "home": home,
        "away": away,
        "league_code": lg,
        "cl_phase": cl_phase,
        "month_day": month_day,
        "match_str": match_str,
    }


def distribute_month_days(n_matches: int, *, max_day: int = 28) -> list[int]:
    """Распределить ``n_matches`` матчей по дням 1..``max_day`` внутри месяца."""
    n = max(0, int(n_matches))
    if n == 0:
        return []
    if n == 1:
        return [1]
    out: list[int] = []
    for i in range(n):
        # равномерно: первый — 1, последний — max_day
        d = 1 + (i * (max_day - 1)) // max(n - 1, 1)
        out.append(max(1, min(max_day, d)))
    return out


def ensure_line_has_month_day(match_str: str, month_day: int) -> str:
    """Добавить ``;day`` в конец строки, если его ещё нет."""
    parsed = parse_mixed_match_line(match_str)
    if parsed.get("month_day") is not None:
        return match_str
    d = max(1, min(28, int(month_day)))
    return f"{match_str.strip()};{d}"


def ensure_flat_schedule_month_days(flat: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Плоское расписание: проставить ``month_day`` в строках матчей."""
    out: list[dict[str, Any]] = []
    for block in flat:
        if not isinstance(block, dict):
            out.append(block)
            continue
        matches = block.get("matches") or []
        if not isinstance(matches, list):
            out.append(block)
            continue
        days = distribute_month_days(len(matches))
        new_lines: list[str] = []
        for i, ln in enumerate(matches):
            if not isinstance(ln, str):
                new_lines.append(ln)
                continue
            md = days[i] if i < len(days) else 1
            new_lines.append(ensure_line_has_month_day(ln, md))
        nb = dict(block)
        nb["matches"] = new_lines
        out.append(nb)
    return out
