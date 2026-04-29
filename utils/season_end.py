# -*- coding: utf-8 -*-
"""
Завершение сезона: трофеи по таблицам, архив в db/season_n/, новый сезон в db/season_m/.
"""
from __future__ import annotations

import os
import shutil
from typing import Any

from sqlalchemy import create_engine, func
from sqlalchemy.orm import sessionmaker

from data.defender import Defender
from data.forward import Forward
from data.goalkeeper import Goalkeeper
from data.midfielder import Midfielder
from utils.common_db import rebuild_common_database

_ALL = (Forward, Midfielder, Defender, Goalkeeper)


def _zero_player_row(row: Any, Cls: type) -> None:
    row.status = None
    row.trophies = 0
    row.golden_balls = 0
    row.golden_boots = 0
    row.golden_boys = 0
    if hasattr(row, "golden_gloves"):
        row.golden_gloves = 0
    if hasattr(row, "yellow_cards"):
        row.yellow_cards = 0
    if hasattr(row, "red_cards"):
        row.red_cards = 0
    row.matches = 0
    row.rating = 0.0
    if hasattr(row, "goals"):
        row.goals = 0
        row.assists = 0
        row.ga = 0
    if hasattr(row, "clean_sheets"):
        row.clean_sheets = 0
    if hasattr(row, "missed_goals"):
        row.missed_goals = 0


def _inc_trophies_all_players_of_team(
    session, team_display_name: str, delta: int = 1
) -> int:
    t = (team_display_name or "").strip().lower()
    n = 0
    for Cls in _ALL:
        q = (
            session.query(Cls)
            .filter(func.lower(Cls.team) == t)
            .all()
        )
        for row in q:
            row.trophies = int(getattr(row, "trophies", 0) or 0) + delta
            n += 1
    return n


def apply_season_trophies_from_standings() -> dict[str, Any]:
    """
    +1 к trophies в БД лиги для чемпиона каждой нац. лиги (1-е место в таблице),
    +1 к trophies в БД ЛЧ для 1-го в групповой таблице ЛЧ (как show_table / бот).
    """
    from main import LEAGUES, get_teams_by_league
    from match_results import compute_cl_group_standings_from_journal
    from teams import get_sorted_teams
    from utils.utils import session_cl, session_league

    out: dict[str, Any] = {
        "national_winners": {},
        "cl_winner": None,
        "league_rows": 0,
        "cl_rows": 0,
    }

    for _k, lg in LEAGUES.items():
        code = lg["code"]
        if code == "cl":
            continue
        teams_d = get_teams_by_league(code)
        if not teams_d:
            continue
        sorted_t = get_sorted_teams(teams_d)
        winner = sorted_t[0][0]
        n = _inc_trophies_all_players_of_team(session_league, winner, 1)
        out["national_winners"][code] = {"team": winner, "rows": n}
        out["league_rows"] += n

    cl_map = get_teams_by_league("cl")
    if cl_map:
        display = compute_cl_group_standings_from_journal(cl_map.keys())
        sorted_cl = get_sorted_teams(display)
        wcl = sorted_cl[0][0]
        n = _inc_trophies_all_players_of_team(session_cl, wcl, 1)
        out["cl_winner"] = {"team": wcl, "rows": n}
        out["cl_rows"] = n

    session_league.commit()
    session_cl.commit()
    return out


def _copy_file(src: str, dst: str) -> None:
    os.makedirs(os.path.dirname(dst), exist_ok=True)
    shutil.copy2(src, dst)


def _clone_db_zero_stats(src: str, dst: str) -> None:
    """Копия файла SQLite + обнуление матчевой/трофейной статистики."""
    shutil.copy2(src, dst)
    eng = create_engine(f"sqlite:///{dst}")
    Sess = sessionmaker(bind=eng)
    s = Sess()
    try:
        for Cls in _ALL:
            for row in s.query(Cls).all():
                _zero_player_row(row, Cls)
        s.commit()
    finally:
        s.close()
        eng.dispose()


def finalize_season() -> dict[str, Any]:
    """
    1) Трофеи по таблицам
    2) Архив в db/season_n, новый сезон в db/season_m
    3) Переключение season_state, reinit БД, reset pickle, rebuild common
    """
    from teams import reset_all_teams, reload_teams_from_disk
    from utils import season_paths
    from utils.utils import reinit_db_connections

    log: dict[str, Any] = {"trophies": None, "archive": None, "new_season": None}

    tr = apply_season_trophies_from_standings()
    log["trophies"] = tr

    from utils.cumulative_db import append_current_season_to_cumulative

    log["cumulative_merge"] = append_current_season_to_cumulative().get("cumulative", [])
    from utils.cl_standing_participants import (
        build_cl_top30_from_current_pickles,
        write_cl_participants_file,
    )
    from utils.player_discipline import clear_discipline_state

    try:
        top30 = build_cl_top30_from_current_pickles()
        log["cl_participants_file"] = write_cl_participants_file(top30)
    except Exception as e:
        log["cl_participants_file"] = f"error: {e!s}"

    try:
        clear_discipline_state()
        log["discipline_json_cleared"] = True
    except OSError as e:
        log["discipline_json_cleared"] = f"error: {e!s}"
    _mixed = os.path.join(season_paths.PROJECT_ROOT, "mixed_schedule.json")
    if os.path.isfile(_mixed):
        try:
            os.remove(_mixed)
            log["mixed_schedule_removed"] = _mixed
        except OSError as e:
            log["mixed_schedule_removed"] = f"error: {e!s}"
    rebuild_common_database()
    log["trophies"]["common_rebuilt"] = True

    st = season_paths.get_state()
    db_root = os.path.join(season_paths.PROJECT_ROOT, "db")
    root_pickle = os.path.join(season_paths.PROJECT_ROOT, "pickle")
    if st["data_mode"] == "legacy":
        n = int(st.get("active_season") or 1)
        next_n = n + 1
        arch = os.path.join(db_root, f"season_{n}")
        nxt = os.path.join(db_root, f"season_{next_n}")
        os.makedirs(arch, exist_ok=True)
        league_src = season_paths.get_league_db_path()
        cl_src = season_paths.get_cl_db_path()
        com_src = season_paths.get_common_db_path()
        _copy_file(league_src, os.path.join(arch, season_paths.SEASON_LEAGUE_NAME))
        _copy_file(cl_src, os.path.join(arch, season_paths.SEASON_CL_NAME))
        _copy_file(com_src, os.path.join(arch, season_paths.SEASON_COMMON_NAME))
        p_arch = os.path.join(arch, "pickle")
        if os.path.isdir(root_pickle):
            if os.path.isdir(p_arch):
                shutil.rmtree(p_arch)
            shutil.copytree(root_pickle, p_arch)
        log["archive"] = arch

        os.makedirs(nxt, exist_ok=True)
        np = os.path.join(nxt, "pickle")
        _clone_db_zero_stats(league_src, os.path.join(nxt, season_paths.SEASON_LEAGUE_NAME))
        _clone_db_zero_stats(cl_src, os.path.join(nxt, season_paths.SEASON_CL_NAME))
        _clone_db_zero_stats(com_src, os.path.join(nxt, season_paths.SEASON_COMMON_NAME))
        if os.path.isdir(root_pickle):
            if os.path.isdir(np):
                shutil.rmtree(np)
            shutil.copytree(root_pickle, np)
        # обнулим таблицы в pickle (новый сезон в папке next)
        season_paths.write_state(
            {
                "data_mode": "per_season",
                "active_season": next_n,
            }
        )
        reinit_db_connections()
        # каталог pickle активного сезона — season_next/pickle: reset
        reset_all_teams()
        log["new_season"] = nxt
    else:
        cur = int(st["active_season"] or 1)
        nxt = cur + 1
        cur_dir = os.path.join(db_root, f"season_{cur}")
        next_dir = os.path.join(db_root, f"season_{nxt}")
        # архив: копия текущего (cur уже «закончен» логически) — дублируем в season_cur_stamped? ТЗ: cur остаётся снимком
        # новый: копия из cur с нулевой статой
        l_src = os.path.join(cur_dir, season_paths.SEASON_LEAGUE_NAME)
        c_src = os.path.join(cur_dir, season_paths.SEASON_CL_NAME)
        o_src = os.path.join(cur_dir, season_paths.SEASON_COMMON_NAME)
        os.makedirs(next_dir, exist_ok=True)
        _clone_db_zero_stats(l_src, os.path.join(next_dir, season_paths.SEASON_LEAGUE_NAME))
        _clone_db_zero_stats(c_src, os.path.join(next_dir, season_paths.SEASON_CL_NAME))
        _clone_db_zero_stats(o_src, os.path.join(next_dir, season_paths.SEASON_COMMON_NAME))
        pcur = os.path.join(cur_dir, "pickle")
        pnew = os.path.join(next_dir, "pickle")
        if os.path.isdir(pcur):
            if os.path.isdir(pnew):
                shutil.rmtree(pnew)
            shutil.copytree(pcur, pnew)
        season_paths.write_state(
            {
                "data_mode": "per_season",
                "active_season": nxt,
            }
        )
        reinit_db_connections()
        reset_all_teams()
        log["new_season"] = next_dir
        log["archive"] = cur_dir

    reload_teams_from_disk()
    # common после reinit указывает на новую БД — пересчитать из league+cl
    rebuild_common_database()
    return log
