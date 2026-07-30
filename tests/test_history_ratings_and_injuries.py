# -*- coding: utf-8 -*-
from __future__ import annotations

from bot.team_history import (
    club_career_conceded,
    rank_clubs_by_attack,
    rank_clubs_by_defense,
)
from utils.player_discipline import format_never_injured_report_text


def test_club_career_conceded_sorted_ascending():
    rows = club_career_conceded(pool_only=True)
    assert len(rows) == 40
    assert all(r.total_ga == r.league_ga + r.cl_ga for r in rows)
    totals = [r.total_ga for r in rows]
    assert totals == sorted(totals)


def test_attack_defense_ratings_cover_pool():
    atk = rank_clubs_by_attack(pool_only=True)
    dfn = rank_clubs_by_defense(pool_only=True)
    assert len(atk) == 40
    assert len(dfn) == 40
    assert atk[0].score >= atk[-1].score
    assert dfn[0].score >= dfn[-1].score


def test_never_injured_report_has_header():
    text = format_never_injured_report_text(limit=10, min_matches=1)
    assert "НИ РАЗУ НЕ ТРАВМИРОВАЛИСЬ" in text
    assert "Игрок" in text
    assert "OVR" in text
    assert "всех сезонов" in text or "все сезоны" in text.lower() or "архивам всех сезонов" in text


def test_injury_frequency_shows_ovr_column():
    from utils.player_discipline import format_injury_frequency_report_text

    text = format_injury_frequency_report_text(limit=10)
    assert "OVR" in text
    assert "ЧАЩЕ ВСЕГО" in text


def test_inter_calhanoglu_influence_heuristic():
    from bot.team_history import club_player_win_influence

    rows = club_player_win_influence("Интер", min_played=10, limit=40)
    by_name = {r.player.casefold(): r for r in rows}
    assert "чалханоглу" in by_name
    c = by_name["чалханоглу"]
    assert c.played >= 40
    assert c.missed_injury >= 1
    assert c.wins + c.draws + c.losses == c.played
    assert c.score > 0


def test_city_influence_prefers_volume_over_small_sample_winpct():
    from bot.team_history import club_player_win_influence

    rows = club_player_win_influence("Сити", min_played=10, limit=25)
    assert rows
    by = {r.player.casefold(): r for r in rows}
    assert "де брюйне" in by
    kdb = by["де брюйне"]
    # короткий сезон с высоким Win% не должен быть выше Де Брюйне
    for name in ("кержаков", "ковачич", "фернандес"):
        if name in by:
            assert kdb.score >= by[name].score - 0.01, (name, by[name].score, kdb.score)
    # Де Брюйне в верхней половине / топ-5 при 60+ матчах
    ranks = {r.player.casefold(): i for i, r in enumerate(rows)}
    assert ranks["де брюйне"] <= 6


def test_bench_influence_uses_db_matches_not_club_fixture_count():
    """Скамейка: matches из БД, не «все матчи клуба»."""
    from bot.team_history import club_player_win_influence

    rows = club_player_win_influence("Мю", min_played=1, limit=80)
    by = {r.player.casefold(): r for r in rows}
    # Шоу в БД ~2 матча — не должен получить десятки матчей клуба
    if "шоу" in by:
        assert by["шоу"].played <= 5
        assert by["шоу"].mode in ("db", "lineup", "lineup+db")
    # Мухтар: bench, matches в БД = 11
    assert "мухтар" in by
    assert by["мухтар"].played == 11
    assert by["мухтар"].mode == "db"


def test_reserve_influence_same_db_logic_as_bench():
    """Резерв считается так же, как скамейка: matches из БД."""
    from bot.team_history import club_player_win_influence

    rows = club_player_win_influence("Спартак", min_played=1, limit=80)
    by = {r.player.casefold(): r for r in rows}
    # Эдвардс — reserve, в БД 11 матчей
    assert "эдвардс" in by
    assert by["эдвардс"].status == "reserve"
    assert by["эдвардс"].played == 11
    assert by["эдвардс"].mode == "db"
