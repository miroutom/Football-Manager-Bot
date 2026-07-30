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


def test_elite_ovr_season_plus_benchmark():
    """90+: плюс только от планки полного сезона; обычная хорошая форма → 0."""
    from utils.ovr_debug_advice import ELITE_OVR, _elite_season_plus, advise_player_ovr

    assert ELITE_OVR == 90
    assert _elite_season_plus("ФРВ", 90, 59, 30)[0] == 1
    assert _elite_season_plus("ФРВ", 90, 58, 30)[0] == 0
    assert _elite_season_plus("ПП", 90, 54, 30)[0] == 1
    assert _elite_season_plus("ПП", 90, 53, 30)[0] == 0
    r = advise_player_ovr("Сити", "Де Брюйне")
    assert r is not None and r.current >= 90
    assert r.delta <= 0


def test_implied_ovr_roundtrip_ga():
    from utils.ovr_debug_advice import _expected_ga_per_match, _implied_ovr_from_ga_rate

    for pos, ovr in (("ФРВ", 90), ("ПП", 88), ("ЦП", 88), ("ФРВ", 93)):
        rate = _expected_ga_per_match(pos, ovr)
        assert abs(_implied_ovr_from_ga_rate(pos, rate) - ovr) < 0.05


def test_martinez_anchor_64_is_93_fwd():
    from utils.ovr_debug_advice import _implied_ovr_from_season_ga

    # 56+8 в ~30 матч. → 93
    assert abs(_implied_ovr_from_season_ga("ФРВ", 64, 30) - 93) < 0.05
    # пз на −10 G+A к тому же якорю
    assert abs(_implied_ovr_from_season_ga("ЦАП", 54, 30) - 93) < 0.05
