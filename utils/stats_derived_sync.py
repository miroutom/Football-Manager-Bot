# -*- coding: utf-8 -*-
"""
Инкрементальное обновление ``common.db`` и ``*_synced.db`` после записи статы матча.

Вместо полной пересборки из архивов накапливаются дельты и дописываются в нужные строки.
"""
from __future__ import annotations

from dataclasses import dataclass
from types import SimpleNamespace
from typing import Any

from data.defender import Defender
from data.forward import Forward
from data.goalkeeper import Goalkeeper
from data.midfielder import Midfielder
from utils.common_db import _key
from utils.utils import Base, session_common

_OUTFIELD = (Forward, Midfielder, Defender)

_BUFFER: list[tuple[Any, str, StatWriteDelta]] = []


@dataclass(frozen=True)
class StatWriteDelta:
    d_matches: int = 0
    d_goals: int = 0
    d_assists: int = 0
    d_clean_sheets: int = 0
    d_motm: int = 0


def _player_class(position: str):
    from player_stats import get_player_class

    return get_player_class((position or "").strip().upper())


def _find_row_by_key(session: Any, PlayerCls: type, player: Any) -> Any | None:
    want = _key(player)
    for row in session.query(PlayerCls).all():
        if _key(row) == want:
            return row
    return None


def _weighted_overall(row: Any, player: Any, d_matches: int) -> None:
    if d_matches <= 0:
        return
    old_m = int(getattr(row, "matches", 0) or 0) - d_matches
    new_m = int(getattr(row, "matches", 0) or 0)
    ov = int(getattr(player, "overall", 0) or 0)
    if new_m <= 0:
        return
    if old_m <= 0:
        row.overall = ov
        return
    row.overall = (
        int(getattr(row, "overall", 0) or 0) * old_m + ov * d_matches
    ) // new_m


def _apply_outfield_delta(row: Any, player: Any, delta: StatWriteDelta) -> None:
    row.matches = int(getattr(row, "matches", 0) or 0) + delta.d_matches
    row.goals = int(getattr(row, "goals", 0) or 0) + delta.d_goals
    row.assists = int(getattr(row, "assists", 0) or 0) + delta.d_assists
    row.ga = int(getattr(row, "goals", 0) or 0) + int(getattr(row, "assists", 0) or 0)
    if hasattr(row, "motm"):
        row.motm = int(getattr(row, "motm", 0) or 0) + delta.d_motm
    _weighted_overall(row, player, delta.d_matches)
    if (getattr(player, "name", None) or "").strip():
        row.name = player.name
    if getattr(player, "person_id", None) is not None:
        row.person_id = player.person_id


def _apply_gk_delta(row: Any, player: Any, delta: StatWriteDelta) -> None:
    row.matches = int(getattr(row, "matches", 0) or 0) + delta.d_matches
    row.clean_sheets = int(getattr(row, "clean_sheets", 0) or 0) + delta.d_clean_sheets
    if hasattr(row, "motm"):
        row.motm = int(getattr(row, "motm", 0) or 0) + delta.d_motm
    _weighted_overall(row, player, delta.d_matches)
    if (getattr(player, "name", None) or "").strip():
        row.name = player.name
    if getattr(player, "person_id", None) is not None:
        row.person_id = player.person_id


def _copy_player_row(PlayerCls: type, player: Any) -> Any:
    cols = {
        c.name: getattr(player, c.name)
        for c in PlayerCls.__table__.columns
        if not c.primary_key
    }
    return PlayerCls(**cols)


def _apply_delta_to_session(session: Any, player: Any, delta: StatWriteDelta) -> None:
    PlayerCls = _player_class(player.position)
    Base.metadata.create_all(session.get_bind())
    row = _find_row_by_key(session, PlayerCls, player)
    if row is None:
        session.add(_copy_player_row(PlayerCls, player))
        return
    if PlayerCls is Goalkeeper:
        _apply_gk_delta(row, player, delta)
    else:
        _apply_outfield_delta(row, player, delta)


def _apply_delta_to_synced_career(session: Any, player: Any, delta: StatWriteDelta) -> None:
    from utils.cumulative_db import _find_row_by_identity, _fold_stats_into_row

    PlayerCls = _player_class(player.position)
    Base.metadata.create_all(session.get_bind())
    row = _find_row_by_identity(session, PlayerCls, player)
    if row is None:
        session.add(_copy_player_row(PlayerCls, player))
        return
    if PlayerCls is Goalkeeper:
        row.matches = int(getattr(row, "matches", 0) or 0) + delta.d_matches
        row.clean_sheets = int(getattr(row, "clean_sheets", 0) or 0) + delta.d_clean_sheets
        if hasattr(row, "motm"):
            row.motm = int(getattr(row, "motm", 0) or 0) + delta.d_motm
        _weighted_overall(row, player, delta.d_matches)
        return
    stub = SimpleNamespace(
        matches=delta.d_matches,
        goals=delta.d_goals,
        assists=delta.d_assists,
        ga=delta.d_goals + delta.d_assists,
        clean_sheets=0,
        missed_goals=0,
        trophies=0,
        yellow_cards=0,
        red_cards=0,
        motm=delta.d_motm,
        golden_balls=0,
        golden_boots=0,
        golden_boys=0,
        golden_gloves=0,
    )
    _fold_stats_into_row(row, stub)
    _weighted_overall(row, player, delta.d_matches)


def record_stat_write(
    player: Any,
    tournament: str,
    *,
    d_matches: int = 0,
    d_goals: int = 0,
    d_assists: int = 0,
    d_clean_sheets: int = 0,
    d_motm: int = 0,
    flush: bool = False,
) -> None:
    """Запомнить дельту; при ``flush=True`` сразу применить буфер."""
    t = "cl" if (tournament or "").strip().lower() in ("cl", "champ_league") else "league"
    _BUFFER.append(
        (
            player,
            t,
            StatWriteDelta(
                d_matches=int(d_matches or 0),
                d_goals=int(d_goals or 0),
                d_assists=int(d_assists or 0),
                d_clean_sheets=int(d_clean_sheets or 0),
                d_motm=int(d_motm or 0),
            ),
        )
    )
    if flush:
        flush_stat_deltas()


def flush_stat_deltas() -> None:
    """Применить накопленные дельты к common и synced (без полной пересборки архивов)."""
    if not _BUFFER:
        return
    batch = list(_BUFFER)
    _BUFFER.clear()

    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker
    from utils import season_paths

    for player, _tournament, delta in batch:
        _apply_delta_to_session(session_common, player, delta)
    session_common.commit()

    if season_paths.is_legacy_mode():
        return

    cum_l = season_paths.get_cumulative_league_db_path()
    cum_c = season_paths.get_cumulative_cl_db_path()
    cum_o = season_paths.get_cumulative_common_db_path()
    el = create_engine(f"sqlite:///{cum_l}")
    ec = create_engine(f"sqlite:///{cum_c}")
    eo = create_engine(f"sqlite:///{cum_o}")
    Sl = sessionmaker(bind=el)
    Scl = sessionmaker(bind=ec)
    So = sessionmaker(bind=eo)
    sl, scl, so = Sl(), Scl(), So()
    try:
        for player, tournament, delta in batch:
            if tournament == "cl":
                _apply_delta_to_synced_career(scl, player, delta)
            else:
                _apply_delta_to_synced_career(sl, player, delta)
            _apply_delta_to_session(so, player, delta)
        sl.commit()
        scl.commit()
        so.commit()
    finally:
        sl.close()
        scl.close()
        so.close()
        el.dispose()
        ec.dispose()
        eo.dispose()


def sync_stats_derived_databases(*, full_rebuild: bool = False) -> None:
    """
    После статы: инкремент из буфера; ``full_rebuild=True`` — полная пересборка (ремонт).
    """
    if _BUFFER and not full_rebuild:
        flush_stat_deltas()
        return
    if _BUFFER:
        _BUFFER.clear()
    from utils.common_db import ensure_common_db_fresh

    from utils import season_paths

    ensure_common_db_fresh()
    if season_paths.is_legacy_mode():
        return
    from utils.cumulative_db import rebuild_all_time_databases_from_season_archives

    rebuild_all_time_databases_from_season_archives()


def clear_stat_delta_buffer() -> None:
    _BUFFER.clear()
