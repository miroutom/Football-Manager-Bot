# -*- coding: utf-8 -*-
from utils.team_registry import (
    TIER_AMBITION,
    club_trophy_ambition,
    count_teams,
    get_team,
    league_code_for_team,
)


def test_tier_ambition_monotonic():
    assert TIER_AMBITION[5] > TIER_AMBITION[3] > TIER_AMBITION[1]


def test_registry_seeded_teams():
    from scripts.seed_teams_registry import seed

    seed(refresh_strength=False)
    assert count_teams() >= 50
    tm = get_team("Арсенал")
    assert tm is not None
    assert tm.league_code == "eng"
    assert tm.trophy_tier >= 4
    assert league_code_for_team("Жирона") == "esp"
    assert club_trophy_ambition("Жирона") < club_trophy_ambition("Реал")
