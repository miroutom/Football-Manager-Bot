# -*- coding: utf-8 -*-
from utils.wc_squad_quota import (
    WC_BENCH,
    WC_GK_TOTAL,
    WC_RESERVE,
    WC_START,
    WC_TOTAL,
    evaluate_wc_squad,
    format_wc_quota_hint,
)


def _sample_roster() -> list[dict]:
    starters = [
        {"name": f"S{i}", "position": "ВРТ" if i == 0 else "ЦЗ", "status": "start", "overall": 80 - i}
        for i in range(WC_START)
    ]
    bench = [
        {"name": f"B{i}", "position": "ВРТ" if i == 0 else "ЦП", "status": "bench", "overall": 70 - i}
        for i in range(WC_BENCH)
    ]
    reserve = [
        {"name": f"R{i}", "position": "ЛФА", "status": "reserve", "overall": 65 - i}
        for i in range(WC_RESERVE)
    ]
    return starters + bench + reserve


def test_wc_quota_complete():
    ev = evaluate_wc_squad(_sample_roster())
    assert ev["complete"] is True
    assert ev["total"] == WC_TOTAL
    assert ev["gk_total"] == WC_GK_TOTAL
    assert format_wc_quota_hint(ev) == "OK"


def test_wc_quota_missing_gk_backup():
    roster = _sample_roster()
    roster[WC_START]["position"] = "ЦП"
    ev = evaluate_wc_squad(roster)
    assert ev["complete"] is False
    assert any("ВРТ" in m for m in ev["missing"])


def test_wc_quota_wrong_counts():
    roster = _sample_roster()[:20]
    ev = evaluate_wc_squad(roster)
    assert ev["complete"] is False
    assert any("всего" in m for m in ev["missing"])


def test_wc_squad_lines_apply(tmp_path, monkeypatch):
    import utils.wc_squad_lines as mod
    import utils.world_cup as wc

    data = {
        "season": 4,
        "teams": {
            "Testland": [
                {"name": "Alpha", "position": "ЦЗ", "overall": 80},
                {"name": "Beta", "position": "ВРТ", "overall": 75},
            ]
        },
    }
    path = tmp_path / "squads.json"

    def _load():
        return data

    def _save(d):
        data.update(d)

    monkeypatch.setattr(wc, "load_wc_squads", _load)
    monkeypatch.setattr(wc, "save_wc_squads", _save)
    monkeypatch.setattr(mod, "load_wc_squads", _load)
    monkeypatch.setattr(mod, "save_wc_squads", _save)
    monkeypatch.setattr(mod, "resolve_nation_name", lambda n: n)

    res = mod.apply_wc_squad_status_lines(
        "Testland",
        "Alpha start LW\nBeta bench\n",
    )
    assert len(res.ok) == 2
    assert not res.errors
    alpha = data["teams"]["Testland"][0]
    assert alpha["status"] == "start"
    assert alpha["lineup_slot"] == "LW"
    assert data["teams"]["Testland"][1]["status"] == "bench"
