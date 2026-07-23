# -*- coding: utf-8 -*-
from __future__ import annotations

import json
from pathlib import Path

import utils.match_potm_log as mpl


def test_record_and_filter_by_month(tmp_path: Path, monkeypatch):
    store = tmp_path / "match_potm_log.json"
    store.write_text("[]", encoding="utf-8")
    monkeypatch.setattr(mpl, "STORE_PATH", str(store))

    mpl.record_match_potm(
        player="Салах",
        team="Ливерпуль",
        position="ПФА",
        home="Ливерпуль",
        away="Челси",
        tournament="league",
        day=3,
        home_score=2,
        away_score=0,
        league_code="eng",
        season=3,
    )
    mpl.record_match_potm(
        player="Кейн",
        team="Бавария",
        position="ФРВ",
        home="Бавария",
        away="Дортмунд",
        tournament="league",
        day=4,
        league_code="ger",
        season=3,
    )
    # overwrite same slot
    mpl.record_match_potm(
        player="Мбаппе",
        team="Ливерпуль",
        position="ЛФА",
        home="Ливерпуль",
        away="Челси",
        tournament="league",
        day=3,
        home_score=2,
        away_score=0,
        league_code="eng",
        season=3,
    )

    rows = json.loads(store.read_text(encoding="utf-8"))
    assert len(rows) == 2
    m3 = mpl.potm_by_month(season=3, day=3)
    assert len(m3) == 1
    assert m3[0]["player"] == "Мбаппе"
    assert m3[0]["day"] == 3
    assert m3[0]["home"] == "Ливерпуль"
