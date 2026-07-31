# -*- coding: utf-8 -*-
from __future__ import annotations

from types import SimpleNamespace


def test_field_player_leaves_on_second_injury(monkeypatch, tmp_path):
    import utils.player_discipline as pd

    store = tmp_path / "player_discipline.json"
    store.write_text(
        '{"version":1,"suspensions":[],"yellow_cycle":[],"injuries":[]}',
        encoding="utf-8",
    )
    monkeypatch.setattr(pd, "_STATE_PATH", store)
    monkeypatch.setattr(pd, "_get_active_season_or_default", lambda: 4)

    player = SimpleNamespace(name="Тестов", position="ЦП", overall=80, left_team=False)
    left_calls: list[str] = []

    def fake_find(sess, name, team):
        return player, None

    def fake_sess(t):
        return object()

    def fake_mark(name, team):
        left_calls.append(name)
        return True

    monkeypatch.setattr(pd, "_mark_player_left_team_in_dbs", fake_mark)

    pd._apply_injury(
        "Тестов",
        "Интер",
        "league",
        1,
        2,
        "травма",
        fake_find,
        fake_sess,
    )
    assert not left_calls

    pd._apply_injury(
        "Тестов",
        "Интер",
        "league",
        3,
        2,
        "травма",
        fake_find,
        fake_sess,
    )
    assert left_calls == ["Тестов"]
