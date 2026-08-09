# -*- coding: utf-8 -*-
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from data.forward import Forward
from utils.player_field_edit import apply_player_field_update, parse_field_value


def test_parse_nation_field_normalizes_wc_name():
    assert parse_field_value(Forward, "nation", "австрия") == "Австрия"
    assert parse_field_value(Forward, "nation", "босния и герцеговина") == "Босния"
    assert parse_field_value(Forward, "nation", "-") is None


def test_apply_nation_skips_duplicate_merge():
    existing = SimpleNamespace(
        id=1290,
        name="Жегрова",
        team="Вольфсбург",
        position="ПФА",
        overall=75,
        nation="Австрия",
        person_id=100,
        matches=0,
        goals=0,
        assists=0,
        ga=0,
        status="bench",
        left_team=False,
    )

    mock_league = MagicMock()
    mock_league.no_autoflush = MagicMock()
    mock_league.no_autoflush.return_value.__enter__ = MagicMock(return_value=None)
    mock_league.no_autoflush.return_value.__exit__ = MagicMock(return_value=False)

    with (
        patch("utils.player_field_edit._assert_league_db_writable"),
        patch(
            "utils.player_field_edit.resolve_player_row",
            return_value=(Forward, existing),
        ),
        patch(
            "utils.player_field_edit.merge_same_name_duplicates_in_session"
        ) as merge_dup,
        patch("utils.player_field_edit._sync_field_to_cl", return_value=0),
        patch("utils.common_db.rebuild_common_database"),
        patch("utils.utils.session_league", mock_league),
    ):
        r = apply_player_field_update(
            "Вольфсбург",
            "Жегрова",
            "ПФА",
            "nation",
            "Босния",
            rebuild_common=False,
            row_id=1290,
            table="forwards",
        )

    merge_dup.assert_not_called()
    assert r["after"] == "Босния"
    mock_league.commit.assert_called_once()
