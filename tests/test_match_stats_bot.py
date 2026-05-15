# -*- coding: utf-8 -*-
from utils.match_stats_bot import (
    PlayerMatchAcc,
    format_player_acc,
    merge_player_acc,
    parse_player_stat_line,
    validate_stat_delta,
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


def test_parse_negative_delta():
    p = parse_player_stat_line("-1 1")
    assert p.goals == -1 and p.assists == 1


def test_validate_delta_floor():
    acc = PlayerMatchAcc(goals=1, assists=0)
    assert not validate_stat_delta(acc, parse_player_stat_line("-1 1"))
    assert validate_stat_delta(acc, parse_player_stat_line("-2 0"))
    assert not validate_stat_delta(PlayerMatchAcc(), parse_player_stat_line("-1 0"))
