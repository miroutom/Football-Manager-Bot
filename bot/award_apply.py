# -*- coding: utf-8 -*-
"""
Начисление +1 к полю награды у игрока в одной БД (сезонная награда не дублируется
в лиге и ЛЧ: пишем в национальную лигу, если игрок найден там, иначе в БД ЛЧ) и
пересборка common.db.
"""
from __future__ import annotations

from dataclasses import dataclass

from data.goalkeeper import Goalkeeper
from utils.common_db import rebuild_common_database
from utils.squad_roster_sync import find_player_row
from utils.utils import session_cl, session_league


@dataclass
class AwardApplyResult:
    league: int
    cl: int
    player_class: str
    player_name: str = ""
    team: str = ""


_KIND_TO_ATTR: dict[str, str] = {
    "ball": "golden_balls",
    "boot": "golden_boots",
    "glove": "golden_gloves",
    "boy": "golden_boys",
}


def apply_trophy(
    kind: str,
    player_name: str,
    team: str,
    *,
    rebuild_common: bool = True,
) -> AwardApplyResult:
    """
    kind: ball | boot | glove | boy
    """
    k = (kind or "").strip().lower()
    attr = _KIND_TO_ATTR.get(k)
    if not attr:
        raise ValueError(f"Неизвестная награда: {kind!r}")

    name = (player_name or "").strip()
    team = (team or "").strip()
    if len(name) < 2 or len(team) < 2:
        raise ValueError("Имя и клуб слишком короткие")

    n_league = 0
    n_cl = 0
    last_cls: str = ""
    resolved_name = name
    resolved_team = team

    def _bump(session) -> int:
        nonlocal last_cls, resolved_name, resolved_team
        row, Cls = find_player_row(session, name, team)
        if not row or not Cls:
            return 0
        if k == "glove" and Cls is not Goalkeeper:
            raise ValueError("Золотая перчатка только для вратарей (позиция ВР в БД).")
        cur = int(getattr(row, attr, 0) or 0)
        setattr(row, attr, cur + 1)
        last_cls = Cls.__name__
        resolved_name = str(getattr(row, "name", None) or name).strip()
        resolved_team = str(getattr(row, "team", None) or team).strip()
        return 1

    try:
        n_league = _bump(session_league)
        if n_league:
            n_cl = 0
        else:
            n_cl = _bump(session_cl)
    except ValueError:
        session_league.rollback()
        session_cl.rollback()
        raise
    if n_league == 0 and n_cl == 0:
        session_league.rollback()
        session_cl.rollback()
        raise ValueError(
            "Игрок не найден в БД (проверь имя и клуб как в игре, без лишних пробелов)."
        )

    if n_league:
        session_league.commit()
    if n_cl:
        session_cl.commit()

    if rebuild_common:
        rebuild_common_database()

    try:
        from bot.season_history_store import record_award_winner
        from utils.season_paths import get_active_season

        record_award_winner(
            get_active_season(),
            k,
            resolved_name,
            resolved_team,
        )
    except Exception:
        import logging

        logging.getLogger(__name__).exception("record_award_winner")

    return AwardApplyResult(
        league=n_league,
        cl=n_cl,
        player_class=last_cls or "—",
        player_name=resolved_name,
        team=resolved_team,
    )
