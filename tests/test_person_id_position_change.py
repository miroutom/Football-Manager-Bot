# -*- coding: utf-8 -*-
"""person_id не меняется при смене позиции в клубе."""
from __future__ import annotations

import os
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

from data.forward import Forward
from data.midfielder import Midfielder
from utils.person_registry import (
    lookup_canonical_person_id,
    lookup_canonical_person_id_by_team,
)
from utils.player_names import player_name_identity_token
from utils.squad_roster_sync import upsert_roster_player


def test_player_name_identity_token_from_string():
    assert player_name_identity_token("Муриэль") == "Муриэль"
    assert player_name_identity_token("Габриэль Жезус") == "Жезус"


@pytest.mark.skipif(
    not os.path.isfile("db/common_synced.db"),
    reason="common_synced.db not present",
)
def test_lookup_by_team_finds_muriel_across_positions():
    pid_old = lookup_canonical_person_id("Муриэль", "ЛФА", team="Аталанта")
    pid_team = lookup_canonical_person_id_by_team("Муриэль", team="Аталанта")
    assert pid_team is not None
    assert pid_team == 60
    assert pid_old == 60


def test_upsert_position_change_keeps_person_id():
    old_row = SimpleNamespace(
        name="Симонс",
        team="Аталанта",
        position="ЦАП",
        overall=83,
        nation=None,
        person_id=347,
        matches=9,
        goals=3,
        assists=3,
        ga=6,
        trophies=0,
        golden_balls=0,
        golden_boots=0,
        golden_boys=0,
        yellow_cards=0,
        red_cards=0,
        status="start",
        left_team=False,
        lineup_slot=None,
    )
    session = MagicMock()
    session.add = MagicMock()
    session.delete = MagicMock()
    session.flush = MagicMock()

    with patch(
        "utils.squad_roster_sync._dedupe_player_rows_for_team",
        return_value=(old_row, Midfielder, None, 347),
    ):
        result = upsert_roster_player(
            session,
            team="Аталанта",
            name="Симонс",
            position="ЛФА",
            overall=83,
            nation=None,
            status="start",
        )

    assert result == "moved"
    session.delete.assert_called_once_with(old_row)
    added = session.add.call_args[0][0]
    assert isinstance(added, Forward)
    assert added.person_id == 347


def test_upsert_after_dedupe_merge_reuses_saved_person_id():
    session = MagicMock()
    session.add = MagicMock()
    session.flush = MagicMock()
    carry = {
        "matches": 5,
        "goals": 2,
        "assists": 1,
        "ga": 3,
        "trophies": 0,
        "golden_balls": 0,
    }

    with (
        patch(
            "utils.squad_roster_sync._dedupe_player_rows_for_team",
            return_value=(None, None, carry, 60),
        ),
        patch("utils.person_registry.allocate_person_id") as alloc,
    ):
        result = upsert_roster_player(
            session,
            team="Аталанта",
            name="Муриэль",
            position="ПФА",
            overall=85,
            nation=None,
            status="bench",
        )

    assert result == "inserted"
    alloc.assert_not_called()
    added = session.add.call_args[0][0]
    assert added.person_id == 60
    assert added.matches == 5
    assert added.goals == 2
