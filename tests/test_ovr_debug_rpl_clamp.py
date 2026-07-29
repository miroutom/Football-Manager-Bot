# -*- coding: utf-8 -*-
from utils.ovr_debug_advice import clamp_ovr_delta_for_team


def test_clamp_rpl_floor_and_cap():
    # пол 75 / макс +3
    assert clamp_ovr_delta_for_team("Спартак", 75, -2) == 0
    assert clamp_ovr_delta_for_team("Спартак", 76, -3) == -1
    assert clamp_ovr_delta_for_team("Спартак", 77, -3) == -2
    assert clamp_ovr_delta_for_team("Спартак", 78, -3) == -3
    assert clamp_ovr_delta_for_team("Спартак", 80, 5) == 3
    assert clamp_ovr_delta_for_team("Спартак", 74, 0) == 1  # вверх к полу


def test_clamp_other_league_pm3():
    assert clamp_ovr_delta_for_team("Мю", 85, -5) == -3
    assert clamp_ovr_delta_for_team("Мю", 85, 5) == 3
    assert clamp_ovr_delta_for_team("Мю", 85, -1) == -1
