# -*- coding: utf-8 -*-
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "tools" / "transfer_window_app"))

from multiplayer_state import (
    bump_state_meta,
    has_save_conflict,
    state_revision,
)


def test_revision_conflict():
    assert state_revision(None) == 0
    assert state_revision({"revision": 3}) == 3
    assert not has_save_conflict(None, 0)
    assert not has_save_conflict(None, None)
    assert has_save_conflict({"revision": 2}, 1)
    assert not has_save_conflict({"revision": 2}, 2)


def test_bump_meta():
    out = bump_state_meta({"teams": []}, revision=1, client_name="A", client_id="x")
    assert out["revision"] == 1
    assert out["updated_by"] == "A"
    assert out["last_client_id"] == "x"
