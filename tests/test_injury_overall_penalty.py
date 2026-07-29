# -*- coding: utf-8 -*-
from utils.player_discipline import injury_overall_penalty


def test_injury_overall_penalty_disabled():
    """Штраф за травмы отключён — overall не меняем."""
    assert injury_overall_penalty(1) == 0
    assert injury_overall_penalty(2) == 0
    assert injury_overall_penalty(3) == 0
    assert injury_overall_penalty(6) == 0
    assert injury_overall_penalty(7) == 0
    assert injury_overall_penalty(8) == 0
    assert injury_overall_penalty(10) == 0
