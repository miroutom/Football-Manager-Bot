# -*- coding: utf-8 -*-
import json
import tempfile
from pathlib import Path

from utils.cl_knockout_schedule import (
    CL_KNOCKOUT_ROUND_MONTH,
    _interleave_knockout_into_month,
    _knockout_schedule_line_keys,
    ensure_knockout_round_in_schedule,
)


def test_knockout_months():
    assert CL_KNOCKOUT_ROUND_MONTH["round_1"] == 6
    assert CL_KNOCKOUT_ROUND_MONTH["final"] == 10


def test_interleave_no_adjacent_knockout():
    base = ["А;Б;eng", "В;Г;ita"]
    new = ["Х;У;cl;knockout", "У;Х;cl;knockout", "С;Т;cl;knockout"]
    out = _interleave_knockout_into_month(base, new, seed=1)
    for i in range(1, len(out)):
        if "cl;knockout" in out[i - 1] and "cl;knockout" in out[i]:
            raise AssertionError("adjacent knockout", out)


def test_knockout_keys_ignore_league_and_national_collisions():
    doc = {
        "version": 3,
        "rounds": [
            {
                "day": 1,
                "matches": ["Барселона;Динамо;cl;league", "Аталанта;Ювентус;ita"],
            },
            {"day": 7, "matches": ["Наполи;Севилья;cl;knockout"]},
        ],
    }
    keys = _knockout_schedule_line_keys(doc)
    assert ("Барселона", "Динамо") not in keys
    assert ("Аталанта", "Ювентус") not in keys
    assert ("Наполи", "Севилья") in keys


def test_ensure_round_2_adds_pairs_colliding_with_league_schedule(tmp_path: Path):
    doc = {
        "version": 3,
        "kind": "months",
        "rounds": [
            {"day": 1, "matches": ["Барселона;Динамо;cl;league"]},
            {"day": 4, "matches": ["Аталанта;Ювентус;ita"]},
            {
                "day": 7,
                "matches": [
                    "Наполи;Севилья;cl;knockout",
                    "Севилья;Наполи;cl;knockout",
                ],
            },
        ],
    }
    p = tmp_path / "mixed_schedule.json"
    p.write_text(json.dumps(doc, ensure_ascii=False), encoding="utf-8")
    added, _ = ensure_knockout_round_in_schedule("round_2", path=p, seed=0)
    assert added
    saved = json.loads(p.read_text(encoding="utf-8"))
    month7 = next(b for b in saved["rounds"] if b["day"] == 7)
    joined = "\n".join(month7["matches"])
    assert "Барселона;Динамо;cl;knockout" in joined
    assert "Динамо;Барселона;cl;knockout" in joined
    assert "Аталанта;Ювентус;cl;knockout" in joined
    assert "Ювентус;Аталанта;cl;knockout" in joined
