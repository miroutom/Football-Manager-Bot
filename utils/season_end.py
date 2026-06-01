# -*- coding: utf-8 -*-
"""
Завершение сезона: трофеи по таблицам, архив в db/season_n/, новый сезон в db/season_m/.
"""
from __future__ import annotations

import os
import shutil
from typing import Any

from sqlalchemy import create_engine, func, or_
from sqlalchemy.orm import sessionmaker

from data.defender import Defender
from data.forward import Forward
from data.goalkeeper import Goalkeeper
from data.midfielder import Midfielder
from utils.common_db import rebuild_common_database

_ALL = (Forward, Midfielder, Defender, Goalkeeper)


def _zero_player_row(row: Any, Cls: type) -> None:
    """Полный сброс строки (редко нужен отдельно от матчевой статистики)."""
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
    if hasattr(row, "goals"):
        row.goals = 0
        row.assists = 0
        row.ga = 0
    if hasattr(row, "clean_sheets"):
        row.clean_sheets = 0
    if hasattr(row, "missed_goals"):
        row.missed_goals = 0


def _zero_match_stats_for_new_season(row: Any, Cls: type) -> None:
    """
    Старт нового сезона: обнуляем матчи, голы/передачи/Г+А, трофеи и награды сезона.

    ``yellow_cards`` / ``red_cards`` **не** обнуляем — это накопительная история в SQLite;
    цикл жк к 4-й сбрасывается в JSON (``clear_discipline_for_new_season``); дисквалы с
    ``matches_left > 0`` переносятся; жк/кк в SQLite не обнуляются.

    Сохраняем: имя, команда, позиция, overall, нация, status, жк/кк.
    """
    row.matches = 0
    if hasattr(row, "goals"):
        row.goals = 0
        row.assists = 0
        row.ga = 0
    if hasattr(row, "clean_sheets"):
        row.clean_sheets = 0
    if hasattr(row, "missed_goals"):
        row.missed_goals = 0
    row.trophies = 0
    row.golden_balls = 0
    row.golden_boots = 0
    row.golden_boys = 0
    if hasattr(row, "golden_gloves"):
        row.golden_gloves = 0


def _inc_trophies_all_players_of_team(
    session, team_display_name: str, delta: int = 1
) -> int:
    """
    Кириллица: в SQLite ``lower(колонка)`` часто не совпадает с ``str.lower()`` в Python,
    поэтому фильтр — точное имя клуба ИЛИ ``func.lower`` (как в ``squad_roster_sync``).
    """
    raw = (team_display_name or "").strip()
    tl = raw.lower()
    n = 0
    for Cls in _ALL:
        q = (
            session.query(Cls)
            .filter(or_(Cls.team == raw, func.lower(Cls.team) == tl))
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
    """
    Копия SQLite + обнуление сезонной статистики для нового сезона.

    Сохраняются: имя, команда, позиция, overall, нация, status.
    Обнуляются: матчи, голы/передачи/Г+А, сухие/пропущенные (ВР), трофеи и
    награды сезона (golden_*). Жк/кк переносятся в новый сезон (история в БД).
    """
    shutil.copy2(src, dst)
    eng = create_engine(f"sqlite:///{dst}")
    Sess = sessionmaker(bind=eng)
    s = Sess()
    try:
        for Cls in _ALL:
            for row in s.query(Cls).all():
                _zero_match_stats_for_new_season(row, Cls)
        s.commit()
    finally:
        s.close()
        eng.dispose()


def _safe_copy2_db(src: str, dst: str) -> None:
    if not os.path.isfile(src):
        return
    os.makedirs(os.path.dirname(dst), exist_ok=True)
    if os.path.abspath(src) == os.path.abspath(dst):
        return
    shutil.copy2(src, dst)


def _safe_copytree_pickle(src: str, dst: str) -> None:
    if not os.path.isdir(src):
        return
    if os.path.abspath(src) == os.path.abspath(dst):
        return
    os.makedirs(os.path.dirname(dst), exist_ok=True)
    if os.path.isdir(dst):
        shutil.rmtree(dst)
    shutil.copytree(src, dst)


def _freeze_working_season_into_season_folder(season_dir: str) -> None:
    """
    Снимок завершённого сезона в ``db/season_N/``: три БД + pickle.
    Если рабочие файлы уже лежат в этой папке, лишний раз не копируем.
    """
    from utils import season_paths

    os.makedirs(season_dir, exist_ok=True)
    lp = season_paths.get_league_db_path()
    cp = season_paths.get_cl_db_path()
    op = season_paths.get_common_db_path()
    dst_l = os.path.join(season_dir, season_paths.SEASON_LEAGUE_NAME)
    dst_c = os.path.join(season_dir, season_paths.SEASON_CL_NAME)
    dst_o = os.path.join(season_dir, season_paths.SEASON_COMMON_NAME)
    _safe_copy2_db(lp, dst_l)
    _safe_copy2_db(cp, dst_c)
    _safe_copy2_db(op, dst_o)
    p_live = season_paths.get_pickle_directory()
    p_dst = os.path.join(season_dir, "pickle")
    _safe_copytree_pickle(p_live, p_dst)


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

    try:
        ended_n = int(season_paths.get_state().get("active_season") or 1)
        from bot.season_history_store import record_tournament_winners_from_finalize

        record_tournament_winners_from_finalize(ended_n, tr)
        log["season_history_tournaments"] = "ok"
    except Exception as e:
        log["season_history_tournaments"] = repr(e)

    from utils.cl_standing_participants import (
        build_cl_top30_from_current_pickles,
        write_cl_participants_file,
    )
    from utils.player_discipline import clear_discipline_for_new_season

    try:
        top30 = build_cl_top30_from_current_pickles()
        log["cl_participants_file"] = write_cl_participants_file(top30)
    except Exception as e:
        log["cl_participants_file"] = f"error: {e!s}"

    try:
        log["discipline_json_new_season"] = clear_discipline_for_new_season()
    except OSError as e:
        log["discipline_json_new_season"] = f"error: {e!s}"
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

    from utils.cumulative_db import append_season_snapshot_to_all_time

    ended: int | None = None
    snap_league: str | None = None
    snap_cl: str | None = None
    archive_dir: str | None = None

    if st["data_mode"] == "legacy":
        n = int(st.get("active_season") or 1)
        ended = n
        arch = os.path.join(db_root, f"season_{n}")
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
        archive_dir = arch
        snap_league = os.path.join(arch, season_paths.SEASON_LEAGUE_NAME)
        snap_cl = os.path.join(arch, season_paths.SEASON_CL_NAME)
        log["archive"] = arch
    else:
        cur = int(st["active_season"] or 1)
        ended = cur
        cur_dir = os.path.join(db_root, f"season_{cur}")
        _freeze_working_season_into_season_folder(cur_dir)
        archive_dir = cur_dir
        snap_league = os.path.join(cur_dir, season_paths.SEASON_LEAGUE_NAME)
        snap_cl = os.path.join(cur_dir, season_paths.SEASON_CL_NAME)
        log["archive"] = cur_dir

    if not snap_league or not snap_cl:
        raise FileNotFoundError(
            "Не удалось зафиксировать архив сезона (нет путей league/cl)."
        )
    if not os.path.isfile(snap_league) or not os.path.isfile(snap_cl):
        raise FileNotFoundError(
            f"Архив сезона неполный после снимка: {snap_league!s}, {snap_cl!s}"
        )
    try:
        from match_results import archive_match_results_json_to_dir, clear_match_results_journal

        mr_dest = os.path.join(archive_dir, "match_results.json")
        ar_st = archive_match_results_json_to_dir(mr_dest)
        log["match_results_archived"] = ar_st
        if ar_st == "copy_failed":
            log["match_results_cleared"] = "skipped: archive copy failed"
        else:
            clear_match_results_journal()
            log["match_results_cleared"] = True
    except OSError as e:
        log["match_results_cleared"] = f"error: {e!s}"
    except Exception as e:
        log["match_results_cleared"] = f"error: {e!s}"
    try:
        from champions_league.knockout_bracket import (
            reset_cl_playoff_bracket_json_to_placeholders,
        )

        reset_cl_playoff_bracket_json_to_placeholders()
        log["cl_playoff_bracket_json_reset"] = True
    except OSError as e:
        log["cl_playoff_bracket_json_reset"] = f"error: {e!s}"
    except Exception as e:
        log["cl_playoff_bracket_json_reset"] = f"error: {e!s}"
    log["cumulative_merge"] = append_season_snapshot_to_all_time(
        snap_league, snap_cl
    ).get("cumulative", [])

    if st["data_mode"] == "legacy":
        n = int(ended or 1)
        next_n = n + 1
        arch = archive_dir or os.path.join(db_root, f"season_{n}")
        nxt = os.path.join(db_root, f"season_{next_n}")
        os.makedirs(nxt, exist_ok=True)
        np = os.path.join(nxt, "pickle")
        l_arch = os.path.join(arch, season_paths.SEASON_LEAGUE_NAME)
        c_arch = os.path.join(arch, season_paths.SEASON_CL_NAME)
        o_arch = os.path.join(arch, season_paths.SEASON_COMMON_NAME)
        _clone_db_zero_stats(l_arch, os.path.join(nxt, season_paths.SEASON_LEAGUE_NAME))
        _clone_db_zero_stats(c_arch, os.path.join(nxt, season_paths.SEASON_CL_NAME))
        _clone_db_zero_stats(o_arch, os.path.join(nxt, season_paths.SEASON_COMMON_NAME))
        p_snap = os.path.join(arch, "pickle")
        src_pick = p_snap if os.path.isdir(p_snap) else root_pickle
        if os.path.isdir(src_pick):
            if os.path.isdir(np):
                shutil.rmtree(np)
            shutil.copytree(src_pick, np)
        season_paths.write_state(
            {
                "data_mode": "per_season",
                "active_season": next_n,
            }
        )
        reinit_db_connections()
        reset_all_teams()
        log["new_season"] = nxt
    else:
        cur = int(ended or 1)
        nxt = cur + 1
        cur_dir = archive_dir or os.path.join(db_root, f"season_{cur}")
        next_dir = os.path.join(db_root, f"season_{nxt}")
        os.makedirs(next_dir, exist_ok=True)
        l_arch = os.path.join(cur_dir, season_paths.SEASON_LEAGUE_NAME)
        c_arch = os.path.join(cur_dir, season_paths.SEASON_CL_NAME)
        o_arch = os.path.join(cur_dir, season_paths.SEASON_COMMON_NAME)
        _clone_db_zero_stats(l_arch, os.path.join(next_dir, season_paths.SEASON_LEAGUE_NAME))
        _clone_db_zero_stats(c_arch, os.path.join(next_dir, season_paths.SEASON_CL_NAME))
        _clone_db_zero_stats(o_arch, os.path.join(next_dir, season_paths.SEASON_COMMON_NAME))
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

    reload_teams_from_disk()
    # common после reinit указывает на новую БД — пересчитать из league+cl
    rebuild_common_database()
    return log
