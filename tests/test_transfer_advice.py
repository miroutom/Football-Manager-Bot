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
    from utils.transfer_advice import (
        SCORE_VERDICT_NO,
        SCORE_VERDICT_SO,
        SCORE_VERDICT_SU,
        _score_to_verdict,
    )

    assert _score_to_verdict(80) == "НО"
    assert _score_to_verdict(SCORE_VERDICT_NO) == "НО"
    assert _score_to_verdict(60) == "СО"
    assert _score_to_verdict(SCORE_VERDICT_SO) == "СО"
    assert _score_to_verdict(45) == "СУ"
    assert _score_to_verdict(SCORE_VERDICT_SU) == "СУ"
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


def test_expected_place_scales_to_league_size():
    from utils.transfer_advice import _expected_league_place

    assert _expected_league_place("Жирона") == 8.0
    assert _expected_league_place("Арсенал") == 2.0
    assert _expected_league_place("Атлетик") == 3.0


def test_frustrated_star_pressure_only_for_carriers():
    from utils.transfer_advice import _frustrated_star_pressure

    star = _frustrated_star_pressure(
        position="ФРВ",
        club_amb=0.95,
        completed_play_seasons=2,
        finish_frust=1.0,
        depth_rank=1,
        prod_ratio=1.2,
        ovr_drop_peak=2,
        player_amb=0.85,
        trophy_earned=0.9,
    )
    bench = _frustrated_star_pressure(
        position="ЛЗ",
        club_amb=0.95,
        completed_play_seasons=2,
        finish_frust=1.0,
        depth_rank=1,
        prod_ratio=1.2,
        ovr_drop_peak=-2,
        player_amb=0.5,
        trophy_earned=0.9,
    )
    declined = _frustrated_star_pressure(
        position="ФРВ",
        club_amb=0.95,
        completed_play_seasons=2,
        finish_frust=1.0,
        depth_rank=1,
        prod_ratio=1.2,
        ovr_drop_peak=-2,
        player_amb=0.85,
        trophy_earned=0.2,
    )
    assert star < -15.0
    assert bench == 0.0
    assert declined == 0.0


def test_trophy_earned_low_for_declined_underperformer():
    from utils.transfer_advice import _EARNED_TROPHY_MIN, _trophy_earned_factor

    earned = _trophy_earned_factor(
        prod_ratio=2.0,
        prod_ratio_last=1.6,
        ovr_drop_peak=-2,
        ovr=86,
        depth_rank=1,
    )
    assert earned < _EARNED_TROPHY_MIN


def test_results_reason_codes_tiers():
    from utils.transfer_advice import (
        REASON_RESULTS_BELOW,
        REASON_RESULTS_WELL_BELOW,
        _results_reason_codes,
    )

    assert _results_reason_codes(0.2, 0.0) == []
    assert _results_reason_codes(0.35, -0.5) == [REASON_RESULTS_BELOW]
    assert _results_reason_codes(0.2, -1.2) == [REASON_RESULTS_BELOW]
    assert _results_reason_codes(0.9, 0.0) == [REASON_RESULTS_WELL_BELOW]
    assert _results_reason_codes(0.2, -2.5) == [REASON_RESULTS_WELL_BELOW]


def test_results_reason_codes_tiers():
    from utils.transfer_advice import (
        REASON_RESULTS_BELOW,
        REASON_RESULTS_WELL_BELOW,
        _results_reason_codes,
    )

    assert _results_reason_codes(0.2, 0.0) == []
    assert _results_reason_codes(0.35, -0.5) == [REASON_RESULTS_BELOW]
    assert _results_reason_codes(0.2, -1.2) == [REASON_RESULTS_BELOW]
    assert _results_reason_codes(0.9, 0.0) == [REASON_RESULTS_WELL_BELOW]
    assert _results_reason_codes(0.2, -2.5) == [REASON_RESULTS_WELL_BELOW]
    assert _results_reason_codes(0.9, -2.5, cap_at_below=True) == [
        REASON_RESULTS_BELOW
    ]


def test_team_results_context_trophy_cushion():
    from utils.transfer_advice import (
        REASON_RESULTS_BELOW,
        _results_reason_codes,
        _team_results_context,
    )

    barca = _team_results_context(
        finish_places=[4, 1],
        expected_place=2.0,
        completed_play_seasons=2,
        league_trophies=1,
        cl_trophies=0,
        trophies_critical=True,
    )
    assert barca.finish_frust < 0.30
    assert barca.place_delta > -1.0
    assert barca.suppress_carry_with_results is True

    atleti = _team_results_context(
        finish_places=[1, 8],
        expected_place=2.0,
        completed_play_seasons=2,
        league_trophies=1,
        cl_trophies=0,
        trophies_critical=True,
    )
    assert atleti.cap_results_at_below is True
    assert _results_reason_codes(
        atleti.finish_frust,
        atleti.place_delta,
        cap_at_below=atleti.cap_results_at_below,
    ) == [REASON_RESULTS_BELOW]


def test_build_reasons_one_tag_when_team_has_trophy():
    from utils.transfer_advice import (
        REASON_CARRY_STAR,
        REASON_NO_TROPHIES,
        REASON_OUTGREW,
        REASON_RESULTS_BELOW,
        REASON_RESULTS_WELL_BELOW,
        _BADGE_TROPHY,
        _build_reasons,
        _team_results_context,
    )

    ctx = _team_results_context(
        finish_places=[1, 8],
        expected_place=2.0,
        completed_play_seasons=2,
        league_trophies=1,
        cl_trophies=0,
        trophies_critical=True,
    )
    reasons = _build_reasons(
        badges=[_BADGE_TROPHY],
        frustration_pen=-10.0,
        skill_norm=1.1,
        ovr=88,
        team_median_overall=82.0,
        depth_rank=1,
        prod_ratio=1.1,
        ovr_delta_live=4,
        completed_play_seasons=2,
        stable_core=False,
        usage_pen=0.0,
        matches=20,
        finish_frust=ctx.finish_frust,
        place_delta=ctx.place_delta,
        league_trophies=1,
        cl_trophies=0,
        suppress_carry_with_results=ctx.suppress_carry_with_results,
        cap_results_at_below=ctx.cap_results_at_below,
    )
    assert REASON_RESULTS_BELOW in reasons
    assert REASON_RESULTS_WELL_BELOW not in reasons
    assert REASON_CARRY_STAR not in reasons
    assert REASON_NO_TROPHIES not in reasons
    assert REASON_OUTGREW not in reasons


def test_build_reasons_zero_trophies_tag():
    from utils.transfer_advice import REASON_NO_TROPHIES, _build_reasons

    reasons = _build_reasons(
        badges=[],
        frustration_pen=0.0,
        skill_norm=0.5,
        ovr=85,
        team_median_overall=82.0,
        depth_rank=1,
        prod_ratio=1.0,
        ovr_delta_live=2,
        completed_play_seasons=2,
        stable_core=False,
        usage_pen=0.0,
        matches=30,
        finish_frust=0.1,
        league_trophies=0,
        cl_trophies=0,
        trophies_critical=True,
    )
    assert REASON_NO_TROPHIES in reasons


def test_build_reasons_outgrown_and_new():
    from utils.transfer_advice import REASON_NEW, REASON_OUTGREW, _build_reasons

    outgrown_ok = _build_reasons(
        badges=[],
        frustration_pen=0.0,
        skill_norm=1.1,
        ovr=88,
        team_median_overall=82.0,
        depth_rank=1,
        prod_ratio=1.1,
        ovr_delta_live=4,
        completed_play_seasons=2,
        stable_core=False,
        usage_pen=0.0,
        matches=20,
        finish_frust=0.2,
    )
    assert REASON_OUTGREW in outgrown_ok

    newbie = _build_reasons(
        badges=[],
        frustration_pen=0.0,
        skill_norm=0.0,
        ovr=83,
        team_median_overall=82.0,
        depth_rank=1,
        prod_ratio=0.8,
        ovr_delta_live=0,
        completed_play_seasons=1,
        stable_core=True,
        usage_pen=0.0,
        matches=10,
    )
    assert REASON_NEW in newbie


def test_starter_never_gets_depth_surplus_reason():
    from utils.transfer_advice import _BADGE_DEPTH, _BADGE_PROD, _build_reasons

    reasons = _build_reasons(
        badges=[_BADGE_DEPTH, _BADGE_PROD],
        frustration_pen=0.0,
        skill_norm=0.0,
        ovr=80,
        team_median_overall=82.0,
        depth_rank=3,
        prod_ratio=0.5,
        ovr_delta_live=0,
        completed_play_seasons=1,
        stable_core=False,
        usage_pen=0.0,
        matches=5,
        in_start=True,
    )
    assert _BADGE_DEPTH not in reasons
    assert _BADGE_PROD in reasons


def test_format_summary_view():
    from utils.transfer_advice import (
        TransferAdviceRow,
        VERDICT_SU,
        format_team_advice_html,
    )

    rows = [
        TransferAdviceRow(
            name="Хаверц",
            position="ФРВ",
            overall=88,
            verdict=VERDICT_SU,
            reasons=["П+", "Р−"],
        )
    ]
    text, pages = format_team_advice_html("Арсенал", rows, view="summary")
    assert pages == 1
    assert "Хаверц" in text
    assert "СУ" in text


def test_paginate_view_no_filters_verdict():
    from utils.transfer_advice import (
        TransferAdviceRow,
        VERDICT_NO,
        VERDICT_NU,
        VERDICT_SU,
        paginate_advice_view,
    )

    rows = [
        TransferAdviceRow(name="А", position="ЦП", overall=80, verdict=VERDICT_NU, reasons=[]),
        TransferAdviceRow(name="Б", position="ЦП", overall=81, verdict=VERDICT_SU, reasons=[]),
        TransferAdviceRow(name="В", position="ЦП", overall=82, verdict=VERDICT_NO, reasons=[]),
        TransferAdviceRow(name="Г", position="ЦП", overall=83, verdict=VERDICT_NO, reasons=[]),
    ]
    chunk, page, total_pages = paginate_advice_view(rows, "no", 0, 10)
    assert total_pages == 1
    assert page == 0
    assert len(chunk) == 2
    assert all(r.verdict == VERDICT_NO for r in chunk)
    assert {r.name for r in chunk} == {"В", "Г"}


def test_archived_season_counts_with_few_matches():
    """Завершённый сезон в архиве — в стаже даже при 1–2 матчах (не ждать ≥3)."""
    from utils.transfer_advice import _collect_club_stint_stats
    from player_stats import national_league_code_for_team

    lc = national_league_code_for_team("Ливерпуль")
    st = _collect_club_stint_stats(
        "Ливерпуль", person_id=None, name="Смоллинг", league_code=lc
    )
    assert st.matches >= 2
    assert st.play_seasons >= 1
    assert st.completed_play_seasons >= 1


def test_collect_club_stint_league_plus_cl_for_advice():
    """Стаж в карточке совета — лига + ЛЧ за каждый сезон."""
    import os

    from utils import season_paths
    from utils.transfer_advice import _collect_club_stint_stats

    s1_league = os.path.join(
        season_paths.season_archive_directory(1), season_paths.SEASON_LEAGUE_NAME
    )
    if not os.path.isfile(s1_league):
        import pytest

        pytest.skip("season 1 archives missing")

    st = _collect_club_stint_stats(
        "Интер", person_id=62, name="Мартинез", league_code="ita_serie_a"
    )
    assert st.matches == 33
    assert st.goals == 65
    assert st.assists == 12
    assert st.completed_play_seasons >= 2


def test_flat_advice_sorted_by_overall():
    from utils.transfer_advice import (
        TransferAdviceRow,
        VERDICT_NO,
        flat_advice_rows,
    )

    rows = [
        TransferAdviceRow(name="А", position="ЦП", overall=80, verdict=VERDICT_NO, reasons=[]),
        TransferAdviceRow(name="Б", position="ЦП", overall=90, verdict=VERDICT_NO, reasons=[]),
        TransferAdviceRow(name="В", position="ЦП", overall=85, verdict=VERDICT_NO, reasons=[]),
    ]
    flat = flat_advice_rows(rows, "no")
    assert [r.overall for r in flat] == [90, 85, 80]


def test_injury_peak_and_score_penalty():
    from utils.transfer_advice import (
        TransferAdviceRow,
        VERDICT_SU,
        _collect_club_stint_stats,
        _injury_stint_score_penalty,
    )

    st = _collect_club_stint_stats(
        "Интер", person_id=62, name="Мартинез", league_code="ita_serie_a"
    )
    assert st.injury_periods == 2
    assert st.injury_months == 9
    assert st.ovr_peak_hist == 93
    assert _injury_stint_score_penalty(2, 9) < 0
    assert _injury_stint_score_penalty(2, 9) >= -2.5


def test_result_pm_martinez_top_at_inter():
    from utils.transfer_advice import collect_transfer_advice

    _, rows, err = collect_transfer_advice("Интер")
    assert not err
    mart = next(r for r in rows if r.name == "Мартинез")
    assert "П+" not in mart.reasons
    pms = [float(r.detail.get("result_pm") or -999) for r in rows]
    assert mart.detail.get("result_pm") == max(pms)
    assert float(mart.detail["result_pm"]) > 20.0


def test_score_respects_result_pm_sane_below_kane():
    from utils.transfer_advice import collect_transfer_advice

    _, bayern, _ = collect_transfer_advice("Бавария")
    sane = next(r for r in bayern if r.name == "Сане")
    kane = next(r for r in bayern if r.name == "Кейн")
    assert float(sane.detail["result_pm"]) < float(kane.detail["result_pm"])
    assert float(sane.score) < float(kane.score)
    assert sane.verdict in ("СО", "СУ")
    assert 52.0 <= float(sane.score) <= 72.0
    assert "≈" not in sane.reasons


def test_result_pm_shown_for_rohl():
    from utils.transfer_advice import collect_transfer_advice, format_player_advice_card_html

    _, rows, err = collect_transfer_advice("Бавария")
    assert not err
    rohl = next(r for r in rows if r.name == "Рёль")
    assert rohl.detail.get("result_pm") is not None
    card = format_player_advice_card_html("Бавария", rohl)
    assert "Вклад в результаты" in card
    assert "вклад в трофеи" not in card
    assert "<i>" in card
    assert "<small>" not in card


def test_team_is_apex_inter():
    from utils.transfer_advice import (
        _cl_strength_rank,
        _league_strength_rank,
        _team_is_apex_destination,
    )
    from player_stats import national_league_code_for_team

    lc = national_league_code_for_team("Интер")
    assert _team_is_apex_destination(
        "Интер", lc, _league_strength_rank("Интер", lc), _cl_strength_rank("Интер")
    )


def test_defender_pm_clean_sheets_and_cards():
    from utils.transfer_advice import (
        TeamSeasonDefense,
        _defender_ga_pm,
        _defender_pm_season,
    )

    rates = {("ЦЗ", 84, "cs"): 0.35, ("ЦЗ", 84, "ga"): 0.05}
    good_def = TeamSeasonDefense(gk_cs=12, gk_matches=20, table_matches=18, conceded=14)
    bad_def = TeamSeasonDefense(gk_cs=4, gk_matches=20, table_matches=18, conceded=28)
    good = _defender_pm_season(
        position="ЦЗ",
        overall=85,
        ga=1,
        matches=15,
        yellow=0,
        red=0,
        injury_months=0,
        depth_rank=1,
        expected_rates=rates,
        team_defense=good_def,
    )
    bad = _defender_pm_season(
        position="ЦЗ",
        overall=85,
        ga=1,
        matches=15,
        yellow=4,
        red=1,
        injury_months=3,
        depth_rank=1,
        expected_rates=rates,
        team_defense=bad_def,
    )
    assert good > 0
    assert bad < good

    wide_zero = _defender_ga_pm(
        position="ЛЗ", overall=82, ga=0, matches=10, expected_rates=rates
    )
    center_zero = _defender_ga_pm(
        position="ЦЗ", overall=82, ga=0, matches=10, expected_rates=rates
    )
    assert wide_zero < 0
    assert center_zero == 0.0


def test_defender_rating_progress_pm():
    from utils.transfer_advice import ClubStintStats, _defender_rating_progress_pm

    growth = ClubStintStats(
        matches=30,
        completed_play_seasons=2,
        ovr_first=82,
        ovr_last_completed=84,
        season_nums=[1, 2],
        per_season_matches={1: 15, 2: 15},
        per_season_ovr={1: 82, 2: 84},
    )
    flat = ClubStintStats(
        matches=14,
        completed_play_seasons=1,
        ovr_first=85,
        ovr_last_completed=85,
        season_nums=[1],
        per_season_matches={1: 14},
        per_season_ovr={1: 85},
    )
    drop = ClubStintStats(
        matches=28,
        completed_play_seasons=2,
        ovr_first=86,
        ovr_last_completed=83,
        season_nums=[1, 2],
        per_season_matches={1: 14, 2: 14},
        per_season_ovr={1: 86, 2: 83},
    )
    assert _defender_rating_progress_pm(growth) > 0
    assert _defender_rating_progress_pm(flat) < 0
    assert _defender_rating_progress_pm(drop) < _defender_rating_progress_pm(flat)

    bastoni_arc = ClubStintStats(
        matches=14,
        completed_play_seasons=1,
        ovr_first=85,
        ovr_last_completed=85,
        ovr_peak=87,
        season_nums=[1, 2, 3],
        per_season_matches={1: 14, 2: 0, 3: 0},
        per_season_ovr={1: 85, 2: 87, 3: 85},
    )
    assert _defender_rating_progress_pm(bastoni_arc, current_ovr=85) < -5.0


def test_result_pm_hint_labels():
    from utils.transfer_advice import _result_pm_hint

    assert _result_pm_hint(62.0, position="ФРВ", is_gk=False)[0] == "выдающийся"
    assert _result_pm_hint(8.5, position="ЛЗ", is_gk=False)[0] == "заметный плюс"
    assert _result_pm_hint(-11.9, position="ЦЗ", is_gk=False)[0] == "ниже ожиданий"


def test_goalkeeper_pm_missed_goals():
    from utils.transfer_advice import _goalkeeper_pm_season

    rates = {("ВРТ", 90, "cs"): 0.35, ("ВРТ", 90, "mg"): 1.0}
    good = _goalkeeper_pm_season(
        position="ВРТ",
        overall=90,
        clean_sheets=12,
        missed_goals=8,
        matches=15,
        yellow=0,
        red=0,
        injury_months=0,
        depth_rank=1,
        expected_rates=rates,
    )
    bad = _goalkeeper_pm_season(
        position="ВРТ",
        overall=90,
        clean_sheets=4,
        missed_goals=22,
        matches=15,
        yellow=1,
        red=0,
        injury_months=2,
        depth_rank=1,
        expected_rates=rates,
    )
    assert good > bad


def test_lewa_barcelona_no_results_pressure_with_title():
    from utils.transfer_advice import (
        REASON_CARRY_STAR,
        REASON_RESULTS_BELOW,
        REASON_RESULTS_WELL_BELOW,
        collect_transfer_advice,
    )

    _, rows, _ = collect_transfer_advice("Барселона")
    lewa = next(r for r in rows if "Лева" in r.name)
    assert REASON_RESULTS_BELOW not in lewa.reasons
    assert REASON_RESULTS_WELL_BELOW not in lewa.reasons
    assert REASON_CARRY_STAR not in lewa.reasons


def test_morata_atletico_one_results_tag_with_title():
    from utils.transfer_advice import (
        REASON_CARRY_STAR,
        REASON_RESULTS_BELOW,
        REASON_RESULTS_WELL_BELOW,
        collect_transfer_advice,
    )

    _, rows, _ = collect_transfer_advice("Атлетико")
    morata = next(r for r in rows if "Мората" in r.name)
    assert REASON_RESULTS_BELOW in morata.reasons
    assert REASON_RESULTS_WELL_BELOW not in morata.reasons
    assert REASON_CARRY_STAR not in morata.reasons


def test_havertz_frustrated_star_not_hard_no():
    """Звезда при слабых местах без трофеев — не НО, с метками результатов и «тащит»."""
    from utils.transfer_advice import (
        REASON_CARRY_STAR,
        REASON_OUTGREW,
        REASON_RESULTS_BELOW,
        REASON_RESULTS_WELL_BELOW,
        VERDICT_NO,
        VERDICT_SU,
        collect_transfer_advice,
    )

    _, rows, _ = collect_transfer_advice("Арсенал")
    h = next(r for r in rows if "Хаверц" in r.name)
    assert h.verdict == VERDICT_SU
    assert h.verdict != VERDICT_NO
    assert REASON_RESULTS_WELL_BELOW in h.reasons or REASON_CARRY_STAR in h.reasons
    assert REASON_OUTGREW not in h.reasons
    assert h.score < 72.0


def test_giroud_girona_new_starter_not_no():
    from utils.transfer_advice import (
        REASON_NEW,
        REASON_OUTGREW,
        VERDICT_NO,
        VERDICT_SO,
        _expected_league_place,
        collect_transfer_advice,
    )

    assert _expected_league_place("Жирона") == 8.0
    _, rows, _ = collect_transfer_advice("Жирона")
    g = next(r for r in rows if "Жиру" in r.name)
    assert g.verdict == VERDICT_SO
    assert g.verdict != VERDICT_NO
    assert REASON_NEW in g.reasons
    assert REASON_OUTGREW not in g.reasons
    assert float(g.detail["expected_place"]) == 8.0
    assert float(g.detail["place_delta"]) > 0


def test_club_stint_league_plus_cl_matches_synced():
    from player_stats import national_league_code_for_team
    from utils.transfer_advice import _collect_club_stint_stats

    lc = national_league_code_for_team("Реал")
    st = _collect_club_stint_stats(
        "Реал", person_id=30, name="Лукаку", league_code=lc
    )
    assert st.goals == 29
    assert st.assists == 8
    assert st.matches == 41
    assert st.per_season_matches[1] == 18
    assert st.per_season_matches[2] == 23


def test_brahim_real_stint_league_plus_cl():
    from player_stats import national_league_code_for_team
    from utils.transfer_advice import _collect_club_stint_stats

    lc = national_league_code_for_team("Реал")
    st = _collect_club_stint_stats(
        "Реал", person_id=316, name="Браим", league_code=lc
    )
    assert st.goals == 18
    assert st.assists == 16
    assert st.matches == 33
