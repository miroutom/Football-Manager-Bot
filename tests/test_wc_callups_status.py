# -*- coding: utf-8 -*-
from utils.wc_callups import (
    _norm_status,
    assign_player_to_squad,
    cycle_squad_player_status,
    remove_from_squad,
    set_squad_player_status,
    toggle_assign_player_to_squad,
    toggle_squad_player_status,
)


def test_norm_status_defaults_reserve():
    assert _norm_status("") == "reserve"
    assert _norm_status("start") == "start"


def test_cycle_and_set_status(monkeypatch):
    import utils.wc_callups as mod

    data = {
        "season": 4,
        "teams": {
            "Testland": [
                {"name": "Alpha", "position": "ЦЗ", "overall": 80, "status": "reserve"},
            ]
        },
    }

    box = [dict(data)]

    def _load():
        return box[0]

    def _save(d):
        box[0] = d

    monkeypatch.setattr(mod, "load_wc_squads", _load)
    monkeypatch.setattr(mod, "save_wc_squads", _save)
    monkeypatch.setattr(mod, "resolve_nation_name", lambda n: n)

    st1, _ = cycle_squad_player_status("Testland", "Alpha")
    assert st1 == "start"
    st2, _ = cycle_squad_player_status("Testland", "Alpha")
    assert st2 == "bench"
    row = set_squad_player_status("Testland", "Alpha", "reserve")
    assert row["status"] == "reserve"


def test_assign_and_remove(monkeypatch):
    import utils.wc_callups as mod

    box = [{"season": 4, "teams": {"Testland": []}}]

    def _load():
        return box[0]

    def _save(d):
        box[0] = d

    monkeypatch.setattr(mod, "load_wc_squads", _load)
    monkeypatch.setattr(mod, "save_wc_squads", _save)
    monkeypatch.setattr(mod, "resolve_nation_name", lambda n: n)

    row = assign_player_to_squad(
        "Testland",
        name="Beta",
        club="X",
        position="НП",
        overall=77,
        status="start",
    )
    assert row["status"] == "start"
    assert len(box[0]["teams"]["Testland"]) == 1

    row2 = assign_player_to_squad("Testland", name="Beta", status="bench")
    assert row2["status"] == "bench"
    assert len(box[0]["teams"]["Testland"]) == 1

    assert remove_from_squad("Testland", "Beta") is True
    assert box[0]["teams"]["Testland"] == []
    assert remove_from_squad("Testland", "Beta") is False


def test_toggle_assign_same_status_removes(monkeypatch):
    import utils.wc_callups as mod

    box = [
        {
            "season": 4,
            "teams": {
                "Testland": [
                    {"name": "Gamma", "position": "ЦП", "overall": 70, "status": "bench"},
                ]
            },
        }
    ]

    def _load():
        return box[0]

    def _save(d):
        box[0] = d

    monkeypatch.setattr(mod, "load_wc_squads", _load)
    monkeypatch.setattr(mod, "save_wc_squads", _save)
    monkeypatch.setattr(mod, "resolve_nation_name", lambda n: n)

    action, _ = toggle_assign_player_to_squad("Testland", name="Gamma", status="bench")
    assert action == "removed"
    assert box[0]["teams"]["Testland"] == []

    assign_player_to_squad("Testland", name="Delta", status="start")
    action, _ = toggle_squad_player_status("Testland", "Delta", "start")
    assert action == "removed"
    assert box[0]["teams"]["Testland"] == []
