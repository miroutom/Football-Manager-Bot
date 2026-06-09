# -*- coding: utf-8 -*-
from main import cl_knockout_aggregate_tie_needs_penalties


def test_final_draw_needs_penalties(monkeypatch):
    monkeypatch.setattr(
        "utils.cl_knockout_schedule.find_knockout_tie_for_match",
        lambda h, a: ("final", "Ливерпуль"),
    )
    assert cl_knockout_aggregate_tie_needs_penalties(
        "Ливерпуль", "Аталанта", 2, 2, "knockout"
    )


def test_final_winner_no_penalties(monkeypatch):
    monkeypatch.setattr(
        "utils.cl_knockout_schedule.find_knockout_tie_for_match",
        lambda h, a: ("final", "Ливерпуль"),
    )
    assert not cl_knockout_aggregate_tie_needs_penalties(
        "Ливерпуль", "Аталанта", 3, 1, "knockout"
    )


def test_group_draw_no_penalties():
    assert not cl_knockout_aggregate_tie_needs_penalties(
        "Ливерпуль", "Аталанта", 1, 1, "league"
    )
