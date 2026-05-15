# -*- coding: utf-8 -*-
from utils.match_stats_bot import (
    PlayerMatchAcc,
    format_player_acc,
    merge_player_acc,
    parse_player_stat_line,
)


def _acc_after(*lines: str) -> str:
    acc = PlayerMatchAcc()
    for line in lines:
        merge_player_acc(acc, parse_player_stat_line(line))
    return format_player_acc(acc)


def test_format_correction_yellows():
    assert _acc_after("1 0 жк") == "1+0 жк"
    assert _acc_after("1 0 жк", "0 1 жк") == "1+1 2жк"


def test_format_correction_red_and_injury():
    assert _acc_after("1 0 жк", "0 1 кк") == "1+1 кк"
    assert _acc_after("1 0 жк", "0 1 3м") == "1+1 жк 3м"


def test_parse_token_only():
    assert parse_player_stat_line("жк").yellow
    assert parse_player_stat_line("3м").injury_months == 3
    assert parse_player_stat_line("cs").clean_sheet
    assert parse_player_stat_line("0 0").goals == 0 and parse_player_stat_line("0 0").assists == 0
