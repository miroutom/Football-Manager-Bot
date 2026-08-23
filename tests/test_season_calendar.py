# -*- coding: utf-8 -*-
from __future__ import annotations

from utils.season_calendar import (
    add_calendar_months,
    compare_dates,
    distribute_month_days,
    ensure_line_has_month_day,
    format_season_date,
    parse_mixed_match_line,
    season_date,
)


def test_add_calendar_months_aug28_plus_2():
    s, m, d = add_calendar_months(4, 1, 28, 2)
    assert (s, m, d) == (4, 3, 28)


def test_injury_last_match_month1_not_back_month3_day1():
    """Травма 28 авг на 2 мес — не играет 1 окт, играет 28 окт."""
    _, ret_m, ret_d = add_calendar_months(4, 1, 28, 2)
    assert (ret_m, ret_d) == (3, 28)
    assert compare_dates(4, 3, 1, 4, ret_m, ret_d) < 0
    assert compare_dates(4, 3, 28, 4, ret_m, ret_d) == 0


def test_injury_blocks_by_day_not_whole_month():
    """28 авг + 2 мес: блок 1 окт, не блок 28 окт."""
    from utils.player_discipline import _injury_blocks_at_month

    inj = {
        "season": 4,
        "out_from_month": 1,
        "out_from_day": 28,
        "return_month": 3,
        "return_day": 28,
    }
    assert _injury_blocks_at_month(inj, 3, current_season=4, month_day=1)
    assert not _injury_blocks_at_month(inj, 3, current_season=4, month_day=28)


def test_parse_mixed_match_line():
    p = parse_mixed_match_line("Лейпциг;Франкфурт;ger;31")
    assert p["home"] == "Лейпциг"
    assert p["month_day"] == 31
    p2 = parse_mixed_match_line("Арсенал;Бавария;cl;league;15")
    assert p2["cl_phase"] == "league"
    assert p2["month_day"] == 15


def test_distribute_month_days():
    assert distribute_month_days(1) == [1]
    ds = distribute_month_days(3)
    assert ds[0] == 1
    assert ds[-1] == 28


def test_ensure_line_has_month_day():
    assert ensure_line_has_month_day("A;B;ger", 12) == "A;B;ger;12"
    assert ensure_line_has_month_day("A;B;ger;12", 99) == "A;B;ger;12"


def test_format_season_date():
    assert "28" in format_season_date(1, 28)
    assert "авг" in format_season_date(1, 28)


def test_season_date_clamps():
    sd = season_date(2, 99)
    assert sd.month == 2
    assert sd.day == 30
