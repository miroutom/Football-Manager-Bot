# -*- coding: utf-8 -*-
from __future__ import annotations

from utils.player_discipline import _resolve_discipline_player


def test_resolve_discipline_player_searches_fixture_teams(monkeypatch):
    calls: list[str] = []

    class Player:
        name = "Клаудиньо"
        team = "Лейпциг"

    def fake_resolve(_sess, team, _name):
        calls.append(team)
        if team == "Лейпциг":
            return Player(), None
        return None, "Не найден в БД"

    monkeypatch.setattr(
        "utils.player_names.resolve_player_query_in_team",
        fake_resolve,
    )
    monkeypatch.setattr("utils.utils.get_session", lambda _t: object())

    player, err, team = _resolve_discipline_player(
        "клаудиньо",
        current_team="Франкфурт",
        tournament="league",
        league_code="ger",
        fixture_home="Лейпциг",
        fixture_away="Франкфурт",
    )
    assert err is None
    assert player is not None
    assert player.name == "Клаудиньо"
    assert team == "Лейпциг"
    assert "Лейпциг" in calls
