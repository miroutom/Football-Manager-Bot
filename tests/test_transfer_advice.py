# -*- coding: utf-8 -*-
import pytest

from utils.transfer_advice import (
    VERDICT_NU,
    W_CL,
    _expected_trophies,
    _player_ambition,
    _score_to_verdict,
    _trophy_sensitivity,
)
from utils.team_registry import club_trophy_ambition, get_league


@pytest.fixture(scope="module", autouse=True)
def _seed_teams_registry():
    from scripts.seed_teams_registry import seed

    seed(refresh_strength=False)


def test_score_to_verdict_thresholds():
    assert _score_to_verdict(80) == "НО"
    assert _score_to_verdict(72) == "НО"
    assert _score_to_verdict(60) == "СО"
    assert _score_to_verdict(45) == "СУ"
    assert _score_to_verdict(20) == "НУ"


def test_club_ambition_la_liga_tiers():
    barca = club_trophy_ambition("Барселона")
    ath = club_trophy_ambition("Атлетик")
    sev = club_trophy_ambition("Севилья")
    gir = club_trophy_ambition("Жирона")
    assert barca > 0.85
    assert ath > sev > gir
    assert gir < 0.12


def test_club_ambition_rpl_dampened_vs_eng():
    rpl_top = club_trophy_ambition("Зенит")
    eng_top = club_trophy_ambition("Арсенал")
    assert rpl_top < eng_top * 0.45


def test_player_ambition_star_vs_rotation():
    star = _player_ambition(ovr=88, depth_rank=1, skill_norm=1.0, fit=True)
    rot = _player_ambition(ovr=75, depth_rank=4, skill_norm=-0.5, fit=False)
    assert star > 0.70
    assert rot < 0.30
    assert star > rot * 2.5


def test_trophy_sensitivity_combined():
    _, _, sens_star = _trophy_sensitivity(
        team="Арсенал",
        ovr=88,
        depth_rank=1,
        skill_norm=1.0,
        fit=True,
    )
    _, _, sens_bench = _trophy_sensitivity(
        team="Арсенал",
        ovr=75,
        depth_rank=4,
        skill_norm=-0.5,
        fit=False,
    )
    assert sens_star > 0.55
    assert sens_bench < 0.25
    assert sens_star > sens_bench * 2


def test_expected_trophies_rpl_low_cl_weight():
    club = club_trophy_ambition("Зенит")
    exp_rpl = _expected_trophies(
        3, league_rank=2, cl_rank=8, league_code="rpl", club_ambition=club
    )
    club_eng = club_trophy_ambition("Арсенал")
    exp_eng = _expected_trophies(
        3, league_rank=2, cl_rank=8, league_code="eng", club_ambition=club_eng
    )
    assert exp_eng > exp_rpl * 2


def test_expected_trophies_cl_weight_legacy_shape():
    club = club_trophy_ambition("Арсенал")
    lg = get_league("eng")
    cl_scale = float(lg.cl_scale) if lg else 1.0
    exp = _expected_trophies(
        3, league_rank=2, cl_rank=5, league_code="eng", club_ambition=club
    )
    assert exp > 3 * 0.32 * club
    assert exp == 3 * club * (0.32 + W_CL * 0.06 * cl_scale)


def test_league_meta_seeded():
    rpl = get_league("rpl")
    assert rpl is not None
    assert rpl.trophy_scale < 0.35


def test_tenure_trophy_factor_grace():
    from utils.transfer_advice import _tenure_trophy_factor

    assert _tenure_trophy_factor(1) < _tenure_trophy_factor(2) < _tenure_trophy_factor(3)


def test_finish_frustration_ambitious_club_underperform():
    from utils.transfer_advice import _finish_frustration

    assert _finish_frustration([5, 5], 2.0) > 0.85
    assert _finish_frustration([2, 1], 2.0) < 0.2


def test_frustrated_star_pressure_only_for_carriers():
    from utils.transfer_advice import _frustrated_star_pressure

    star = _frustrated_star_pressure(
        position="ФРВ",
        club_amb=0.95,
        completed_play_seasons=2,
        finish_frust=1.0,
        depth_rank=1,
        prod_ratio=1.2,
        ovr_delta=4,
        player_amb=0.85,
    )
    bench = _frustrated_star_pressure(
        position="ЛЗ",
        club_amb=0.95,
        completed_play_seasons=2,
        finish_frust=1.0,
        depth_rank=1,
        prod_ratio=1.2,
        ovr_delta=-2,
        player_amb=0.5,
    )
    assert star < -15.0
    assert bench == 0.0
