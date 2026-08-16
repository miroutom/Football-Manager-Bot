#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Сезон 4: счёт + стата по ручному списку (м1–м2, м4)."""
from __future__ import annotations

import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from match_results import is_match_played
from matches_stats_tracking import mark_stats_completed
from player_stats import (
    MatchTeamStatBudget,
    add_player_stats,
    apply_match_potm,
    get_position_type,
    get_session,
    infer_league_code_for_stats,
    _validate_goals_vs_team_score,
)
from utils.match_player_stats_log import record_match_player_stats
from utils.player_discipline import get_calendar_month, try_apply_discipline_line
from utils.player_names import find_players_matching_query

FIXTURES = [
    ("Краснодар", "Локомотив", "rpl", 2, 0, 4, None),
    ("Мю", "Сити", "eng", 1, 1, 4, None),
    ("Аталанта", "Фиорентина", "ita", 1, 5, 1, None),
    ("Краснодар", "Лейпциг", "cl", 1, 2, 2, "league"),
    ("Милан", "Интер", "ita", 1, 0, 5, None),
    ("Наполи", "Аталанта", "ita", 1, 1, 3, None),
    ("Наполи", "Интер", "ita", 4, 1, 3, None),
]


def _record_match(home, away, league, day, hs, aws, cl_phase=None) -> bool:
    if is_match_played(home, away, league, cl_phase=cl_phase):
        print(f"  · журнал: {home} — {away} уже есть")
        return True
    from main import process_match

    ok = process_match(
        home,
        away,
        hs,
        aws,
        league,
        round_num=day,
        with_stats=False,
        cl_phase=cl_phase,
        interactive=False,
    )
    if not ok:
        print(f"  ✗ не записан счёт: {home} {hs}:{aws} {away}")
    return ok


def _apply_one(
    sess,
    name: str,
    pos: str,
    team: str,
    g: int,
    a: int,
    *,
    tournament: str,
    mcs,
    day: int,
    lc: str,
    budget: MatchTeamStatBudget,
) -> bool:
    matches = find_players_matching_query(sess, team, name, include_left=True)
    if matches:
        player = matches[0]
        if mcs and (g or a):
            ok_g, err_g = _validate_goals_vs_team_score(
                team,
                g,
                a,
                mcs,
                team_goals_already=budget.goals_used(team),
                team_assists_already=budget.assists_used(team),
            )
            if not ok_g:
                print(f"  ✗ {player.name} ({team}): {err_g}")
                return False
        pos_type = get_position_type(player.position)
        player.matches += 1
        if pos_type in ("forward", "midfielder", "defender"):
            player.goals += g
            player.assists += a
            player.ga = player.goals + player.assists
        sess.commit()
        from utils.stats_derived_sync import record_stat_write

        record_stat_write(player, tournament, d_matches=1, d_goals=g, d_assists=a)
        budget.add(team, g, a)
        print(f"  ✓ {player.name} {player.position} {team} {g} {a}")
        return True
    return add_player_stats(
        name,
        pos,
        team,
        g,
        a,
        tournament=tournament,
        auto_find=True,
        match_for_cs=mcs,
        discipline_league_code=lc,
        schedule_day=day,
        skip_discipline_check=True,
        team_goals_already=budget.goals_used(team),
        team_assists_already=budget.assists_used(team),
    )


def _apply_rows(
    rows,
    *,
    tournament,
    mcs,
    home,
    away,
    day,
    league_code,
    cl_phase=None,
    skip_players: set[tuple[str, str]] | None = None,
    potm: tuple[str, str, str] | None = None,
    discipline: list[tuple[str, str, str]] | None = None,
    team_goals_seed: dict[str, tuple[int, int]] | None = None,
):
    skip_players = skip_players or set()
    budget = MatchTeamStatBudget()
    if team_goals_seed:
        for team, (g, a) in team_goals_seed.items():
            budget.add(team, g, a)

    applied: list[tuple] = []
    ok_n, fail_n = 0, 0
    lc = infer_league_code_for_stats(home, away, tournament)
    sess = get_session(tournament)

    for name, pos, team, g, a in rows:
        key = (name.strip().title(), team.strip().title())
        if key in skip_players:
            print(f"  · пропуск (уже в БД): {name} ({team})")
            continue
        matches = find_players_matching_query(sess, team, name, include_left=True)
        db_name = matches[0].name if matches else name
        ok_row = _apply_one(
            sess,
            db_name,
            pos,
            team,
            g,
            a,
            tournament=tournament,
            mcs=mcs,
            day=day,
            lc=lc,
            budget=budget,
        )
        if ok_row:
            applied.append((db_name, pos, team, g, a))
            ok_n += 1
        else:
            fail_n += 1

    if potm:
        pm = find_players_matching_query(sess, potm[2], potm[0], include_left=True)
        if pm:
            player = pm[0]
            player.potm = int(getattr(player, "potm", 0) or 0) + 1
            sess.commit()
            from utils.stats_derived_sync import record_stat_write

            record_stat_write(player, tournament, d_potm=1)
            print(f"  ✓ POTM: {player.name} ({player.team})")
            potm_name = player.name
        else:
            potm_name = potm[0]
        apply_match_potm(
            potm_name,
            potm[1],
            potm[2],
            tournament=tournament,
            home=home,
            away=away,
            day=day,
            home_score=mcs[2],
            away_score=mcs[3],
            league_code=league_code,
            cl_phase=cl_phase,
            log_journal=not pm,
        )

    month = get_calendar_month(day)
    for disc_line, team in discipline or []:
        msg, handled = try_apply_discipline_line(
            disc_line,
            current_team=team,
            tournament=tournament,
            league_code=lc,
            schedule_month=month,
            fixture_home=home,
            fixture_away=away,
            cl_phase=cl_phase,
        )
        print(f"  {'✓' if handled else '✗'} {msg or disc_line}")

    if applied:
        record_match_player_stats(
            players=[
                {"player": n, "team": t, "position": p, "goals": g, "assists": a}
                for n, p, t, g, a in applied
            ],
            home=home,
            away=away,
            tournament=tournament,
            day=day,
            home_score=mcs[2],
            away_score=mcs[3],
            league_code=league_code,
            cl_phase=cl_phase,
        )

    mark_stats_completed(home, away, tournament, day=day, cl_phase=cl_phase)
    print(f"  → стата: ok={ok_n} fail={fail_n}")
    return fail_n == 0


def main() -> int:
    fails = 0
    retry = "--retry-failed" in sys.argv

    if not retry:
        print("=== Новые счета в журнал ===")
        for home, away, league, day, hs, aws, cl_ph in FIXTURES:
            if not _record_match(home, away, league, day, hs, aws, cl_phase=cl_ph):
                fails += 1

        print("\n=== Барселона 3:4 Жирона (дописать стату, Лева уже 1+0) ===")
        if not _apply_rows(
            [
                ("Сон", "ЛФА", "Барселона", 1, 1),
                ("Педри", "ЦАП", "Барселона", 0, 1),
                ("Де Томас", "ФРВ", "Жирона", 1, 1),
                ("Талиска", "ЦАП", "Жирона", 2, 0),
                ("Батурина", "ЦП", "Жирона", 0, 1),
                ("Перейра", "ЦП", "Жирона", 1, 0),
            ],
            tournament="league",
            mcs=("Барселона", "Жирона", 3, 4),
            home="Барселона",
            away="Жирона",
            day=1,
            league_code="esp",
            skip_players={("Лева", "Барселона")},
            potm=("Талиска", "ЦАП", "Жирона"),
            discipline=[("Канселу 2м", "Барселона")],
            team_goals_seed={"Барселона": (1, 0)},
        ):
            fails += 1

        for block in (
            _block_mu_city,
            _block_milan_inter,
            _block_napoli_atalanta,
            _block_napoli_inter,
        ):
            if not block():
                fails += 1

    print("\n=== Краснодар 0:4 Локомотив ===")
    if not _apply_rows(
        [
            ("Мартинш", "ПП", "Локомотив", 1, 0),
            ("Капрари", "ФРВ", "Локомотив", 1, 1),
            ("Кордова", "ЦАП", "Локомотив", 1, 1),
            ("Колпани", "ЦП", "Локомотив", 0, 1),
        ],
        tournament="league",
        mcs=("Краснодар", "Локомотив", 0, 4),
        home="Краснодар",
        away="Локомотив",
        day=2,
        league_code="rpl",
        skip_players={("Муса", "Локомотив")},
        potm=("Кордова", "ЦАП", "Локомотив"),
        discipline=[("Диатта 2м", "Локомотив")],
        team_goals_seed={"Локомотив": (1, 1)},  # Муса уже 1+1
    ):
        fails += 1

    print("\n=== Аталанта 5:1 Фиорентина (Пашалич) ===")
    if not _apply_rows(
        [("Пашалич", "ЦАП", "Аталанта", 1, 0)],
        tournament="league",
        mcs=("Аталанта", "Фиорентина", 5, 1),
        home="Аталанта",
        away="Фиорентина",
        day=1,
        league_code="ita",
        team_goals_seed={"Аталанта": (5, 0)},
    ):
        fails += 1

    print("\n=== Краснодар 2:2 Лейпциг (ЛЧ) ===")
    if not _apply_rows(
        [("Кривцов", "ЦАП", "Краснодар", 2, 0)],
        tournament="cl",
        mcs=("Краснодар", "Лейпциг", 2, 2),
        home="Краснодар",
        away="Лейпциг",
        day=1,
        league_code="cl",
        cl_phase="league",
        potm=("Кривцов", "ЦАП", "Краснодар"),
        team_goals_seed={"Лейпциг": (2, 2)},
    ):
        fails += 1

    try:
        from utils.common_db import rebuild_common_database

        rebuild_common_database()
        print("\ncommon.db пересобран")
    except Exception as e:
        print(f"\ncommon: {e}")

    if fails:
        print(f"\n✗ Ошибок: {fails}")
        return 1
    print("\n✓ Готово")
    return 0


def _block_mu_city() -> bool:
    print("\n=== Мю 1:4 Сити ===")
    return _apply_rows(
        [
            ("Нуньес", "ФРВ", "Мю", 0, 1),
            ("Брозович", "ЦП", "Мю", 1, 0),
            ("Рэшфорд", "ЛФА", "Сити", 0, 2),
            ("Клюйверт", "ФРВ", "Сити", 0, 1),
            ("Хаверц", "ФРВ", "Сити", 2, 0),
            ("Месси", "ПФА", "Сити", 1, 0),
            ("Де Брюйне", "ЦАП", "Сити", 0, 1),
            ("Барелла", "ЦП", "Сити", 1, 0),
        ],
        tournament="league",
        mcs=("Мю", "Сити", 1, 4),
        home="Мю",
        away="Сити",
        day=1,
        league_code="eng",
        potm=("Барелла", "ЦП", "Сити"),
        discipline=[("Хаверц жк", "Сити")],
    )


def _block_milan_inter() -> bool:
    print("\n=== Милан 0:5 Интер ===")
    return _apply_rows(
        [
            ("Бензема", "ФРВ", "Интер", 1, 0),
            ("Мартинез", "ФРВ", "Интер", 2, 1),
            ("Роналдиньо", "ЦАП", "Интер", 0, 1),
            ("Собослай", "ЦАП", "Интер", 1, 1),
            ("Чалханоглу", "ЦП", "Интер", 1, 1),
            ("Льоренте", "ЦП", "Интер", 0, 1),
        ],
        tournament="league",
        mcs=("Милан", "Интер", 0, 5),
        home="Милан",
        away="Интер",
        day=1,
        league_code="ita",
        potm=("Мартинез", "ФРВ", "Интер"),
        discipline=[("Лапорт жк", "Милан"), ("Льоренте 2м", "Интер")],
    )


def _block_napoli_atalanta() -> bool:
    print("\n=== Наполи 1:3 Аталанта ===")
    return _apply_rows(
        [
            ("Миранчук", "ФРВ", "Аталанта", 2, 0),
            ("Костич", "ПФА", "Аталанта", 0, 1),
            ("Торрес", "ЦАП", "Аталанта", 0, 2),
            ("Пашалич", "ЦАП", "Аталанта", 1, 0),
            ("Габриэль Жезус", "ФРВ", "Наполи", 0, 1),
            ("Рафинья", "ПФА", "Наполи", 1, 0),
        ],
        tournament="league",
        mcs=("Наполи", "Аталанта", 1, 3),
        home="Наполи",
        away="Аталанта",
        day=1,
        league_code="ita",
        potm=("Пашалич", "ЦАП", "Аталанта"),
        discipline=[
            ("Буригард 2м", "Аталанта"),
            ("Кох жк", "Наполи"),
            ("Родри кк", "Наполи"),
        ],
    )


def _block_napoli_inter() -> bool:
    print("\n=== Наполи 1:3 Интер (м4) ===")
    return _apply_rows(
        [
            ("Квара", "ЛФА", "Наполи", 1, 0),
            ("Габриэль Жезус", "ФРВ", "Наполи", 0, 1),
            ("Бензема", "ФРВ", "Интер", 1, 0),
            ("Мартинез", "ФРВ", "Интер", 1, 1),
            ("Чалханоглу", "ЦП", "Интер", 0, 1),
            ("Льоренте", "ЦП", "Интер", 1, 0),
        ],
        tournament="league",
        mcs=("Наполи", "Интер", 1, 3),
        home="Наполи",
        away="Интер",
        day=4,
        league_code="ita",
        potm=("Льоренте", "ЦП", "Интер"),
        discipline=[
            ("Кох жк", "Наполи"),
            ("Ди Лоренцо жк", "Наполи"),
            ("Роналдиньо 2м", "Интер"),
        ],
    )


if __name__ == "__main__":
    raise SystemExit(main())
