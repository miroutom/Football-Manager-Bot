# -*- coding: utf-8 -*-
from __future__ import annotations

import json
from pathlib import Path

import matches_stats_tracking as mst


def test_mark_pending_then_completed(tmp_path: Path, monkeypatch):
    pending = tmp_path / "pending.json"
    completed = tmp_path / "completed.json"
    pending.write_text("[]", encoding="utf-8")
    completed.write_text("[]", encoding="utf-8")
    monkeypatch.setattr(mst, "PENDING_FILE", str(pending))
    monkeypatch.setattr(mst, "COMPLETED_FILE", str(completed))

    mst.mark_stats_pending("Интер", "Милан", "league", day=6)
    mst.mark_stats_pending("Интер", "Милан", "league", day=6)  # idempotent
    rows = json.loads(pending.read_text(encoding="utf-8"))
    assert len(rows) == 1
    assert rows[0]["home"] == "Интер"
    assert rows[0]["away"] == "Милан"
    assert rows[0]["day"] == 6
    assert mst.is_stats_pending("Интер", "Милан", "league")

    mst.mark_stats_completed("Интер", "Милан", "league", day=6)
    assert json.loads(pending.read_text(encoding="utf-8")) == []
    assert mst.is_stats_completed("Интер", "Милан", "league")
    # completed blocks re-pending
    mst.mark_stats_pending("Интер", "Милан", "league", day=6)
    assert json.loads(pending.read_text(encoding="utf-8")) == []
