# -*- coding: utf-8 -*-
from __future__ import annotations

from types import SimpleNamespace


def test_field_first_strike_life_only_no_block(monkeypatch, tmp_path):
    import utils.player_discipline as pd

    store = tmp_path / "player_discipline.json"
    store.write_text(
        '{"version":1,"suspensions":[],"yellow_cycle":[],"injuries":[]}',
        encoding="utf-8",
    )
    monkeypatch.setattr(pd, "_STATE_PATH", store)
    monkeypatch.setattr(pd, "_get_active_season_or_default", lambda: 4)

    player = SimpleNamespace(name="Тестов", position="ЦП", overall=80, left_team=False)

    def fake_find(sess, name, team):
        return player, None

    def fake_sess(t):
        return object()

    msg, ok = pd._apply_injury(
        "Тестов",
        "Интер",
        "league",
        1,
        2,
        "травма",
        fake_find,
        fake_sess,
    )
    assert ok
    assert "1/2" in msg
    assert "без пропуска" in msg

    st = pd._load()
    assert len(st["injuries"]) == 1
    assert st["injuries"][0]["life_only"] is True
    assert not pd._injury_blocks_at_month(st["injuries"][0], 1, current_season=4)


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

    st = pd._load()
    actual = [r for r in st["injuries"] if not r.get("life_only")]
    assert len(actual) == 1
    assert pd._injury_blocks_at_month(actual[0], 3, current_season=4)


def test_goalkeeper_four_strikes_no_block(monkeypatch, tmp_path):
    import utils.player_discipline as pd

    store = tmp_path / "player_discipline.json"
    store.write_text(
        '{"version":1,"suspensions":[],"yellow_cycle":[],"injuries":[]}',
        encoding="utf-8",
    )
    monkeypatch.setattr(pd, "_STATE_PATH", store)
    monkeypatch.setattr(pd, "_get_active_season_or_default", lambda: 4)

    player = SimpleNamespace(name="Нойер", position="ВРТ", overall=88, left_team=False)

    def fake_find(sess, name, team):
        return player, None

    def fake_sess(t):
        return object()

    for start in (1, 2, 3, 4):
        msg, ok = pd._apply_injury(
            "Нойер",
            "Бавария",
            "league",
            start,
            2,
            "травма",
            fake_find,
            fake_sess,
        )
        assert ok
        assert "без пропуска" in msg

    st = pd._load()
    assert len(st["injuries"]) == 4
    assert all(r.get("life_only") for r in st["injuries"])
    assert not any(
        pd._injury_blocks_at_month(r, start, current_season=4) for r in st["injuries"]
    )


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

    for start in (1, 2, 3, 4):
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
        5,
        2,
        "травма",
        fake_find,
        fake_sess,
    )
    assert left_calls == ["Нойер"]


def test_actual_injury_resets_pending_strikes(monkeypatch, tmp_path):
    import utils.player_discipline as pd

    store = tmp_path / "player_discipline.json"
    store.write_text(
        '{"version":1,"suspensions":[],"yellow_cycle":[],"injuries":[]}',
        encoding="utf-8",
    )
    monkeypatch.setattr(pd, "_STATE_PATH", store)
    monkeypatch.setattr(pd, "_get_active_season_or_default", lambda: 4)

    player = SimpleNamespace(name="Тестов", position="ЦП", overall=80, left_team=False)

    def fake_find(sess, name, team):
        return player, None

    def fake_sess(t):
        return object()

    monkeypatch.setattr(pd, "_mark_player_left_team_in_dbs", lambda *a: False)

    pd._apply_injury("Тестов", "Интер", "league", 1, 2, "т", fake_find, fake_sess)
    pd._apply_injury("Тестов", "Интер", "league", 3, 2, "т", fake_find, fake_sess)

    st = pd._load()
    assert pd._injury_pending_strikes(st, "Тестов", "Интер") == 0

    msg, _ = pd._apply_injury("Тестов", "Интер", "league", 6, 2, "т", fake_find, fake_sess)
    assert "1/2" in msg


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
