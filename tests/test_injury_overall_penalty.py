# -*- coding: utf-8 -*-
from utils.player_discipline import injury_overall_penalty


def test_injury_overall_penalty_short():
    assert injury_overall_penalty(1) == 0
    assert injury_overall_penalty(2) == 0


def test_injury_overall_penalty_mid():
    assert injury_overall_penalty(3) == -2
    assert injury_overall_penalty(6) == -2


def test_injury_overall_penalty_long():
    assert injury_overall_penalty(7) == -4
    assert injury_overall_penalty(8) == -7
    assert injury_overall_penalty(10) == -7
