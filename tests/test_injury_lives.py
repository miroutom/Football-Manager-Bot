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


def test_goalkeeper_leaves_on_fifth_injury(monkeypatch, tmp_path):
    import utils.player_discipline as pd

    store = tmp_path / "player_discipline.json"
    store.write_text(
        '{"version":1,"suspensions":[],"yellow_cycle":[],"injuries":[]}',
        encoding="utf-8",
    )
    monkeypatch.setattr(pd, "_STATE_PATH", store)
    monkeypatch.setattr(pd, "_get_active_season_or_default", lambda: 4)

    player = SimpleNamespace(name="Нойер", position="ВРТ", overall=88, left_team=False)
    left_calls: list[str] = []

    def fake_find(sess, name, team):
        return player, None

    def fake_sess(t):
        return object()

    def fake_mark(name, team):
        left_calls.append(name)
        return True

    monkeypatch.setattr(pd, "_mark_player_left_team_in_dbs", fake_mark)

    for start in (1, 3, 5, 7):
        pd._apply_injury(
            "Нойер",
            "Бавария",
            "league",
            start,
            2,
            "травма",
            fake_find,
            fake_sess,
        )
    assert not left_calls

    pd._apply_injury(
        "Нойер",
        "Бавария",
        "league",
        9,
        2,
        "травма",
        fake_find,
        fake_sess,
    )
    assert left_calls == ["Нойер"]


def test_close_stale_carryover_injuries(monkeypatch, tmp_path):
    import utils.player_discipline as pd

    store = tmp_path / "player_discipline.json"
    store.write_text(
        """{
      "version": 1,
      "suspensions": [],
      "yellow_cycle": [],
      "injuries": [{
        "name": "Кейн", "name_norm": "кейн", "team": "Бавария", "team_norm": "бавария",
        "out_from_month": 8, "return_month": 15, "season": 3, "type": "травма",
        "key": "кейн|бавария|3|8|15"
      }]
    }""",
        encoding="utf-8",
    )
    monkeypatch.setattr(pd, "_STATE_PATH", store)
    monkeypatch.setattr(pd, "_get_active_season_or_default", lambda: 4)

    n = pd.close_stale_carryover_injuries(season_now=4, month=1)
    assert n == 1
    row = pd._load()["injuries"][0]
    assert row["return_month"] == 11
    assert not pd._injury_blocks_at_month(row, 1, current_season=4)
