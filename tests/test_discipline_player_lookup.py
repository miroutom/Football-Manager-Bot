# -*- coding: utf-8 -*-
from __future__ import annotations

from utils.player_discipline import _resolve_discipline_player


def test_resolve_discipline_player_uses_include_left(monkeypatch):
    calls: list[tuple[str, bool]] = []

    class Player:
        name = "Клаудиньо"
        team = "Лейпциг"

    def fake_resolve(_sess, team, _name, *, include_left=False):
        calls.append((team, include_left))
        if include_left and team == "Лейпциг":
            return Player(), None
        return None, "Не найден в БД"

    monkeypatch.setattr(
        "utils.player_names.resolve_player_query_in_team",
        fake_resolve,
    )
    monkeypatch.setattr("utils.utils.get_session", lambda _t: object())

    player, err, team = _resolve_discipline_player(
        "клаудиньо",
        current_team="Лейпциг",
        tournament="league",
        league_code="ger",
        fixture_home="Лейпциг",
        fixture_away="Франкфурт",
        include_left=True,
    )
    assert err is None
    assert player is not None
    assert player.name == "Клаудиньо"
    assert team == "Лейпциг"
    assert any(flag for _team, flag in calls)
