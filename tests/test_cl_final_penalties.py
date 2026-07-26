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


def test_two_leg_aggregate_draw_needs_penalties_even_if_second_leg_not_draw(monkeypatch):
    """Байер 3:2 Аталанта + Аталанта 4:3 Байер = 6:6 → пенальти, хотя ответный не ничья."""
    monkeypatch.setattr(
        "utils.cl_knockout_schedule.find_knockout_tie_for_match",
        lambda h, a: ("r2", 0),
    )
    first = {
        "home": "Байер",
        "away": "Аталанта",
        "home_score": 3,
        "away_score": 2,
        "league": "cl",
        "cl_phase": "knockout",
    }
    monkeypatch.setattr(
        "main.find_cl_knockout_first_leg_record",
        lambda h, a: first,
    )
    assert cl_knockout_aggregate_tie_needs_penalties(
        "Аталанта", "Байер", 4, 3, "knockout"
    )


def test_two_leg_aggregate_winner_no_penalties(monkeypatch):
    monkeypatch.setattr(
        "utils.cl_knockout_schedule.find_knockout_tie_for_match",
        lambda h, a: ("r2", 0),
    )
    first = {
        "home": "Байер",
        "away": "Аталанта",
        "home_score": 3,
        "away_score": 2,
        "league": "cl",
        "cl_phase": "knockout",
    }
    monkeypatch.setattr(
        "main.find_cl_knockout_first_leg_record",
        lambda h, a: first,
    )
    # Аталанта 5:3 Байер → 5:6 по сумме в пользу Байера
    assert not cl_knockout_aggregate_tie_needs_penalties(
        "Аталанта", "Байер", 5, 3, "knockout"
    )


def test_first_leg_no_penalties(monkeypatch):
    monkeypatch.setattr(
        "utils.cl_knockout_schedule.find_knockout_tie_for_match",
        lambda h, a: ("r2", 0),
    )
    monkeypatch.setattr(
        "main.find_cl_knockout_first_leg_record",
        lambda h, a: None,
    )
    assert not cl_knockout_aggregate_tie_needs_penalties(
        "Байер", "Аталанта", 1, 1, "knockout"
    )
