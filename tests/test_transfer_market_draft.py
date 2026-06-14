# -*- coding: utf-8 -*-
from __future__ import annotations

import json
from pathlib import Path

from utils.transfer_market_draft import load_draft, validate_draft


def test_transfer_window_draft_balanced():
    moves = load_draft(Path("data/transfer_window_draft.json"))
    assert len(moves) == 200
    errors, _warnings = validate_draft(moves)
    assert errors == [], errors

def test_transfer_window_draft_json_shape():
    raw = json.loads(Path("data/transfer_window_draft.json").read_text(encoding="utf-8"))
    assert raw.get("status") == "draft_review"
    assert len(raw.get("moves") or []) == 200
