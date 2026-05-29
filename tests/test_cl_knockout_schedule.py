# -*- coding: utf-8 -*-
from utils.cl_knockout_schedule import (
    CL_KNOCKOUT_ROUND_MONTH,
    _interleave_knockout_into_month,
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
