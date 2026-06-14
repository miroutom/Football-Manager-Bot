# -*- coding: utf-8 -*-
"""Список игроков текущего сезона по позициям (лига + ЛЧ без разделения)."""
from __future__ import annotations

from typing import Any

from data.defender import Defender
from data.forward import Forward
from data.goalkeeper import Goalkeeper
from data.midfielder import Midfielder
from player_stats import get_player_class
from config.leagues_config import manager_side_for_team
from utils.player_names import player_surname
from utils.utils import (
    defenders,
    forwards,
    goalkeepers,
    midfielders,
    session_cl,
    session_league,
)

_ALL = (Forward, Midfielder, Defender, Goalkeeper)

POSITION_ORDER: tuple[str, ...] = tuple(forwards + midfielders + defenders + goalkeepers)


def _norm_pos(p: str) -> str:
    return (p or "").strip().upper()


def _row_key(row: Any) -> tuple:
    from utils.person_registry import row_person_id

    pid = row_person_id(row)
    if pid is not None:
        return ("pid", int(pid))
    sn = (player_surname(row) or "").strip().lower()
    tm = (getattr(row, "team", None) or "").strip().lower()
    return ("nt", sn, tm)


def _iter_active_rows(session) -> list[Any]:
    out: list[Any] = []
    for Cls in _ALL:
        q = session.query(Cls)
        if hasattr(Cls, "left_team"):
            q = q.filter(Cls.left_team.is_(False))
        out.extend(q.all())
    return out


def collect_players_by_position() -> dict[str, list[tuple[str, str, int]]]:
    """
    Позиция → [(фамилия, команда, overall), …] по убыванию рейтинга.
    Дубли league/cl схлопываются по person_id или фамилия+клуб.
    """
    best: dict[tuple, tuple[str, str, int, str]] = {}
    for session in (session_league, session_cl):
        for row in _iter_active_rows(session):
            pos = _norm_pos(getattr(row, "position", "") or "")
            if not pos:
                continue
            sur = (player_surname(row) or "").strip()
            team = (getattr(row, "team", None) or "").strip()
            ovr = int(getattr(row, "overall", 0) or 0)
            if not sur or not team:
                continue
            k = _row_key(row)
            prev = best.get(k)
            if prev is None or ovr > prev[2] or (ovr == prev[2] and pos == prev[3]):
                best[k] = (sur, team, ovr, pos)

    by_pos: dict[str, list[tuple[str, str, int]]] = {}
    for sur, team, ovr, pos in best.values():
        by_pos.setdefault(pos, []).append((sur, team, ovr))
    for pos in by_pos:
        by_pos[pos].sort(key=lambda x: (-x[2], x[0].lower(), x[1].lower()))
    return by_pos


def positions_with_players() -> list[str]:
    data = collect_players_by_position()
    return [p for p in POSITION_ORDER if data.get(p)]


def collect_players_flat() -> list[dict[str, Any]]:
    """
    Все игроки текущего сезона (лига + ЛЧ) в одной таблице.
    Колонки: фамилия, полное имя, команда, позиция, рейтинг, менеджер.
    """
    best: dict[tuple, dict[str, Any]] = {}
    for session in (session_league, session_cl):
        for row in _iter_active_rows(session):
            pos = _norm_pos(getattr(row, "position", "") or "")
            if not pos:
                continue
            sur = (player_surname(row) or "").strip()
            team = (getattr(row, "team", None) or "").strip()
            full = (getattr(row, "name", None) or "").strip()
            ovr = int(getattr(row, "overall", 0) or 0)
            if not sur or not team:
                continue
            k = _row_key(row)
            prev = best.get(k)
            if prev is None or ovr > int(prev.get("overall", 0) or 0):
                best[k] = {
                    "surname": sur,
                    "name": full or sur,
                    "team": team,
                    "position": pos,
                    "overall": ovr,
                    "manager": _manager_label(team),
                }
            elif ovr == int(prev.get("overall", 0) or 0) and pos == prev.get("position"):
                if full:
                    prev["name"] = full

    def _pos_order(p: str) -> int:
        try:
            return POSITION_ORDER.index(p)
        except ValueError:
            return len(POSITION_ORDER)

    rows = list(best.values())
    rows.sort(
        key=lambda r: (
            _pos_order(str(r.get("position") or "")),
            -int(r.get("overall", 0) or 0),
            str(r.get("surname") or "").lower(),
            str(r.get("team") or "").lower(),
        )
    )
    return rows


def _manager_label(team: str) -> str:
    side = manager_side_for_team(team)
    if side == "roman":
        return "roma"
    if side == "lika":
        return "lika"
    return "?"


def _aligned_position_table_lines(
    rows: list[tuple[str, str, int]],
) -> list[str]:
    """Колонки фиксированной ширины для моноширинного PNG."""
    sur_w = max([len("Фамилия"), *[len(s) for s, _, _ in rows]])
    team_w = max([len("Команда"), *[len(t) for _, t, _ in rows]])
    rate_w = max([len("Рейтинг"), *[len(str(o)) for _, _, o in rows]])
    mgr_w = max(len("Менеджер"), 4)

    def _row(sur: str, team: str, ovr: int | str, mgr: str) -> str:
        return (
            f"{sur:<{sur_w}}  {team:<{team_w}}  "
            f"{str(ovr):>{rate_w}}  {mgr:<{mgr_w}}"
        )

    out = [
        _row("Фамилия", "Команда", "Рейтинг", "Менеджер"),
        "",
    ]
    out.extend(
        _row(sur, team, ovr, _manager_label(team)) for sur, team, ovr in rows
    )
    return out


def format_position_list(position: str) -> str:
    pos = _norm_pos(position)
    rows = collect_players_by_position().get(pos) or []
    if not rows:
        return f"{pos}\n(нет игроков)"
    lines = [f"{pos} · сезон { _active_season_label() }", ""]
    lines.extend(_aligned_position_table_lines(rows))
    return "\n".join(lines)


def _active_season_label() -> str:
    from utils.season_paths import get_active_season

    return str(get_active_season())


def set_player_position(
    team: str,
    name: str,
    new_position: str,
    *,
    old_position: str | None = None,
    rebuild_common: bool = True,
) -> dict[str, Any]:
    """Смена позиции в league (+ cl при необходимости), с переносом между таблицами."""
    from utils.common_db import rebuild_common_database
    from utils.squad_roster_sync import _resolve_roster_row

    team_t = (team or "").strip().title()
    new_pos = _norm_pos(new_position)
    if new_pos not in POSITION_ORDER:
        raise ValueError(f"Неизвестная позиция: {new_position!r}")

    def _apply(session, label: str) -> str | None:
        row, SrcCls, _, _ = _resolve_roster_row(session, name, team_t)
        if not row or not SrcCls:
            return None
        if old_position:
            if _norm_pos(getattr(row, "position", "") or "") != _norm_pos(old_position):
                return None
        DstCls = get_player_class(new_pos)
        old_id = int(row.id)
        if SrcCls is DstCls:
            row.position = new_pos
            return f"{label}: id={old_id} → {new_pos}"
        cols = {
            c.name: getattr(row, c.name)
            for c in SrcCls.__table__.columns
            if not c.primary_key
        }
        cols["position"] = new_pos
        session.add(DstCls(**cols))
        session.delete(row)
        session.flush()
        return f"{label}: {SrcCls.__tablename__} id={old_id} → {DstCls.__tablename__} {new_pos}"

    logs: list[str] = []
    r_l = _apply(session_league, "league")
    if not r_l:
        raise ValueError(f"Не найден «{name}» в «{team_t}» (league)")
    logs.append(r_l)
    session_league.commit()

    try:
        r_c = _apply(session_cl, "cl")
        if r_c:
            logs.append(r_c)
            session_cl.commit()
    except Exception:
        session_cl.rollback()

    if rebuild_common:
        rebuild_common_database()

    return {"team": team_t, "name": name, "position": new_pos, "log": logs}
