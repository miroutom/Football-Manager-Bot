# -*- coding: utf-8 -*-
from utils.transfer_advice import (
    VERDICT_NO,
    VERDICT_NU,
    VERDICT_SO,
    VERDICT_SU,
    W_CL,
    _expected_trophies,
    _score_to_verdict,
)


def test_score_to_verdict_thresholds():
    assert _score_to_verdict(80) == VERDICT_NO
    assert _score_to_verdict(72) == VERDICT_NO
    assert _score_to_verdict(60) == VERDICT_SO
    assert _score_to_verdict(45) == VERDICT_SU
    assert _score_to_verdict(20) == VERDICT_NU


def test_expected_trophies_cl_weight():
    exp = _expected_trophies(3, league_rank=2, cl_rank=5)
    assert exp > 3 * 0.32
    assert exp == 3 * (0.32 + W_CL * 0.06)


def test_expected_trophies_no_cl():
    exp = _expected_trophies(2, league_rank=10, cl_rank=None)
    assert exp == 2 * 0.04
