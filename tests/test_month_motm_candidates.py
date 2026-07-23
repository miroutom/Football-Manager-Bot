# -*- coding: utf-8 -*-
from __future__ import annotations

import json
from pathlib import Path

import utils.match_player_stats_log as msl
import utils.match_potm_log as mpl
from utils.month_motm_candidates import month_motm_candidates


def test_flush_and_candidates(tmp_path: Path, monkeypatch):
    stats_store = tmp_path / "stats.json"
    potm_store = tmp_path / "potm.json"
    stats_store.write_text("[]", encoding="utf-8")
    potm_store.write_text("[]", encoding="utf-8")
    monkeypatch.setattr(msl, "STORE_PATH", str(stats_store))
    monkeypatch.setattr(mpl, "STORE_PATH", str(potm_store))

    msl.flush_session_acc_to_log(
        {
            "a|liv": {
                "display_name": "Салах",
                "team": "Ливерпуль",
                "position": "ПФА",
                "goals": 2,
                "assists": 1,
            },
            "b|che": {
                "display_name": "Палмер",
                "team": "Челси",
                "position": "ПФА",
                "goals": 1,
                "assists": 0,
            },
        },
        home="Ливерпуль",
        away="Челси",
        tournament="league",
        day=6,
        league_code="eng",
        season=3,
        home_score=3,
        away_score=1,
    )
    mpl.record_match_potm(
        player="Салах",
        team="Ливерпуль",
        position="ПФА",
        home="Ливерпуль",
        away="Челси",
        tournament="league",
        day=6,
        league_code="eng",
        season=3,
    )
    # equal potm elsewhere would lose to Salah on goals
    mpl.record_match_potm(
        player="Палмер",
        team="Челси",
        position="ПФА",
        home="Сити",
        away="Челси",
        tournament="league",
        day=6,
        league_code="eng",
        season=3,
    )

    cands = month_motm_candidates(6, "eng", season=3, limit=5)
    assert cands
    assert cands[0].player == "Салах"
    assert cands[0].goals == 2 and cands[0].assists == 1 and cands[0].potm == 1
    # score: 2*3 + 1*2 + 1*5 = 13
    assert cands[0].score == 13
    assert cands[1].player == "Палмер"
    assert cands[1].score == 3 + 5  # 1g + 1 potm

    rows = json.loads(stats_store.read_text(encoding="utf-8"))
    assert len(rows) == 1
    assert len(rows[0]["players"]) == 2
