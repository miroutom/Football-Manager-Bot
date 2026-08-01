# -*- coding: utf-8 -*-
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "tools" / "transfer_window_app"))

from main import _normalize_fa_player, import_fa_payload


def test_normalize_fa_player():
    p = _normalize_fa_player({"name": "Test", "position": "st", "overall": 80})
    assert p["name"] == "Test"
    assert p["position"] == "ST"
    assert p["id"].startswith("Free Agent|")


def test_import_fa_payload_no_db(monkeypatch):
    data = {"players": [{"name": "A", "position": "GK", "overall": 70}]}

    def _boom(*a, **k):
        raise RuntimeError("no db")

    monkeypatch.setattr("utils.free_agents_db.add_free_agent_player", _boom)
    monkeypatch.setattr("utils.free_agents_db.list_free_agents", _boom)

    players, notes = import_fa_payload(data, sync_db=False)
    assert len(players) == 1
    assert not notes
