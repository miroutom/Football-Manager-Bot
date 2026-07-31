# -*- coding: utf-8 -*-
"""Дисквал стартует с следующего тура команды игрока, не хозяев."""
from utils.player_discipline import _ban_from_round_after_card


def test_ban_from_uses_player_team_not_home(monkeypatch):
    """Хозяева играют 14-й, гости — 13-й → бан гостя с 14, хозяина с 15."""
    calls: list[str | None] = []

    def fake_round(home, away, league, *, cl_phase=None, for_team=None):
        calls.append(for_team)
        key = (for_team or home or "").strip().casefold()
        return {"динамо": 13, "спартак": 14}.get(key, 14)

    monkeypatch.setattr(
        "utils.player_discipline.find_fixture_round", fake_round
    )

    away_ban = _ban_from_round_after_card(
        fixture_home="Спартак",
        fixture_away="Динамо",
        league_code="rpl",
        cl_phase=None,
        player_team="Динамо",
    )
    home_ban = _ban_from_round_after_card(
        fixture_home="Спартак",
        fixture_away="Динамо",
        league_code="rpl",
        cl_phase=None,
        player_team="Спартак",
    )
    assert calls == ["Динамо", "Спартак"]
    assert away_ban == 14
    assert home_ban == 15


def test_team_round_for_fixture_played_vs_upcoming(monkeypatch):
    from utils import calendar_slot_labels as csl

    monkeypatch.setattr(
        csl, "count_team_league_matches_played", lambda team, lc: 12
    )
    monkeypatch.setattr(
        "match_results.is_match_played", lambda *a, **k: False
    )
    assert csl.team_round_for_fixture("Динамо", "Спартак", "Динамо", "rpl") == 13

    monkeypatch.setattr(
        "match_results.is_match_played", lambda *a, **k: True
    )
    # матч уже в журнале, у команды 12 учтённых → это был 12-й
    assert csl.team_round_for_fixture("Динамо", "Спартак", "Динамо", "rpl") == 12
