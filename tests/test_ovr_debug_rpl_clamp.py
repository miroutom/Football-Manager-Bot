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


def test_clamp_ovr_ceiling_94():
    assert clamp_ovr_delta_for_team("Сити", 93, 3) == 1
    assert clamp_ovr_delta_for_team("Сити", 94, 2) == 0
    assert clamp_ovr_delta_for_team("Сити", 92, 3) == 2


def test_elite_ovr_no_raise_on_good_form():
    """90+: хорошая форма не даёт плюса (калибровка, не гонка за +1)."""
    from utils.ovr_debug_advice import ELITE_OVR, advise_player_ovr

    assert ELITE_OVR == 90
    r = advise_player_ovr("Сити", "Де Брюйне")
    assert r is not None
    assert r.current >= 90
    assert r.delta <= 0
