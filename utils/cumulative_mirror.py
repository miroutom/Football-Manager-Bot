# -*- coding: utf-8 -*-
"""
Дублирование операций ростера/overall в накопительные ``*_synced.db`` при ``per_season``.

В режиме ``legacy`` рабочие БД уже совпадают с cumulative — зеркалирование не вызывается.
"""
from __future__ import annotations

import os

from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker


def _cumulative_paths() -> tuple[str, str, str] | None:
    from utils import season_paths

    if season_paths.is_legacy_mode():
        return None
    lp = season_paths.get_cumulative_league_db_path()
    cp = season_paths.get_cumulative_cl_db_path()
    cop = season_paths.get_cumulative_common_db_path()
    if not (os.path.isfile(lp) and os.path.isfile(cp)):
        return None
    return lp, cp, cop


def _open_pair(league_path: str, cl_path: str) -> tuple[Session, Session, object, object]:
    el = create_engine(f"sqlite:///{league_path}")
    ec = create_engine(f"sqlite:///{cl_path}")
    Sl = sessionmaker(bind=el)
    Scl = sessionmaker(bind=ec)
    return Sl(), Scl(), el, ec


def _dispose_pair(sl: Session, scl: Session, el: object, ec: object) -> None:
    sl.close()
    scl.close()
    el.dispose()
    ec.dispose()


def mirror_transfer_with_status(
    player: str,
    from_team: str,
    position: str,
    to_team: str,
    new_status: str | None,
    *,
    new_overall: int | None = None,
    nation_update: bool = False,
    new_nation: str | None = None,
) -> None:
    paths = _cumulative_paths()
    if not paths:
        return
    lp, cp, cop = paths
    from utils.player_transfer import _apply_transfer_with_status_to_sessions
    from utils.common_db import rebuild_common_database_for_disk_paths

    sl, scl, el, ec = _open_pair(lp, cp)
    try:
        _apply_transfer_with_status_to_sessions(
            sl,
            scl,
            player,
            from_team,
            position,
            to_team,
            new_status,
            new_overall=new_overall,
            nation_update=nation_update,
            new_nation=new_nation,
        )
        rebuild_common_database_for_disk_paths(lp, cp, cop)
    except Exception:
        sl.rollback()
        scl.rollback()
        raise
    finally:
        _dispose_pair(sl, scl, el, ec)


def mirror_add_free_agent(
    player: str,
    position: str,
    to_team: str,
    new_status: str,
    overall: int = 72,
    *,
    nation: str | None = None,
) -> None:
    paths = _cumulative_paths()
    if not paths:
        return
    lp, cp, cop = paths
    from utils.player_transfer import _add_free_agent_to_sessions
    from utils.common_db import rebuild_common_database_for_disk_paths

    sl, scl, el, ec = _open_pair(lp, cp)
    try:
        _add_free_agent_to_sessions(
            sl,
            scl,
            player,
            position,
            to_team,
            new_status,
            overall,
            nation=nation,
            on_league_duplicate="skip",
        )
        rebuild_common_database_for_disk_paths(lp, cp, cop)
    except Exception:
        sl.rollback()
        scl.rollback()
        raise
    finally:
        _dispose_pair(sl, scl, el, ec)


def mirror_player_status_lines_for_team(team: str, text: str) -> None:
    paths = _cumulative_paths()
    if not paths:
        return
    lp, cp, cop = paths
    from utils.player_status_lines import apply_player_status_lines_in_sessions
    from utils.common_db import rebuild_common_database_for_disk_paths

    sl, scl, el, ec = _open_pair(lp, cp)
    try:
        res = apply_player_status_lines_in_sessions(team, text, sl, scl)
        if res.ok:
            sl.commit()
            scl.commit()
            rebuild_common_database_for_disk_paths(lp, cp, cop)
        else:
            sl.rollback()
            scl.rollback()
    except Exception:
        sl.rollback()
        scl.rollback()
        raise
    finally:
        _dispose_pair(sl, scl, el, ec)


def mirror_overall_bumps_for_team(
    team: str,
    text: str,
    *,
    alternate_names: dict[str, tuple[str, ...]] | None = None,
) -> None:
    paths = _cumulative_paths()
    if not paths:
        return
    lp, cp, cop = paths
    from utils.player_overall_bumps import apply_overall_bumps_in_sessions
    from utils.common_db import rebuild_common_database_for_disk_paths

    sl, scl, el, ec = _open_pair(lp, cp)
    try:
        res = apply_overall_bumps_in_sessions(
            team, text, sl, scl, alternate_names=alternate_names
        )
        if res.ok:
            sl.commit()
            scl.commit()
            rebuild_common_database_for_disk_paths(lp, cp, cop)
        else:
            sl.rollback()
            scl.rollback()
    finally:
        _dispose_pair(sl, scl, el, ec)
