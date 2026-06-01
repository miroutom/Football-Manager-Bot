# -*- coding: utf-8 -*-
from player_stats import (
    MatchTeamStatBudget,
    _validate_goals_vs_team_score,
)


def _match():
    return ("Хозяева", "Гости", 2, 1)


def test_single_player_limits_unchanged():
    ok, err = _validate_goals_vs_team_score("Хозяева", 2, 0, _match())
    assert ok
    ok, err = _validate_goals_vs_team_score("Хозяева", 3, 0, _match())
    assert not ok


def test_team_goals_budget_exhausted():
    ok, _ = _validate_goals_vs_team_score(
        "Хозяева", 2, 0, _match(), team_goals_already=0
    )
    assert ok
    ok, err = _validate_goals_vs_team_score(
        "Хозяева", 1, 0, _match(), team_goals_already=2
    )
    assert not ok
    assert "уже 2" in (err or "")


def test_team_assists_separate_pool():
    ok, _ = _validate_goals_vs_team_score(
        "Хозяева", 0, 2, _match(), team_assists_already=0
    )
    assert ok
    ok, err = _validate_goals_vs_team_score(
        "Хозяева", 0, 1, _match(), team_assists_already=2
    )
    assert not ok
    assert "передач" in (err or "")


def test_two_scorers_split_team_goals():
    b = MatchTeamStatBudget()
    ok, _ = _validate_goals_vs_team_score(
        "Хозяева", 2, 0, _match(), team_goals_already=b.goals_used("Хозяева")
    )
    assert ok
    b.add("Хозяева", 2, 0)
    ok, err = _validate_goals_vs_team_score(
        "Хозяева", 1, 0, _match(), team_goals_already=b.goals_used("Хозяева")
    )
    assert not ok


def test_budget_from_session_acc():
    acc = {
        "a": {"team": "Мю", "goals": 2, "assists": 0},
        "b": {"team": "Мю", "goals": 0, "assists": 1},
    }
    b = MatchTeamStatBudget.from_session_acc(acc)
    assert b.goals_used("Мю") == 2
    assert b.assists_used("Мю") == 1
