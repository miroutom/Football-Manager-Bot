# -*- coding: utf-8 -*-
"""
Объединённая БД (``common_*.db``): суммарная статистика по лиге и ЛЧ.
Пересборка: ``rebuild_common_database()``.

- ``trophies`` в common = сумма трофеев из нац. БД + ЛЧ (трофей лиги и трофей ЛЧ по отдельным источникам).
  В файле **только** лиги: только национальные; в **только** БД ЛЧ: только трофеи ЛЧ.

- ``overall``: при ненулевой сумме матчей — средневзвешенно по лиге+ЛЧ; иначе из заявки
  (число из нац. БД, если оно >0, иначе из БД ЛЧ). Так в начале сезона (0 матчей) в common
  не пропадают рейтинги из ``league.db`` / ``champions_league.db``.
"""
from __future__ import annotations

import os
import sys
from pathlib import Path
from typing import Any

_ROOT = Path(__file__).resolve().parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from data.defender import Defender
from data.forward import Forward
from data.goalkeeper import Goalkeeper
from data.midfielder import Midfielder
from utils.player_names import player_stats_identity_token
from utils.utils import (
    Base,
    CHAMPIONS_LEAGUE_DB_PATH,
    COMMON_DB_PATH,
    LEAGUE_DB_PATH,
    engine_common,
    session_cl,
    session_common,
    session_league,
)


def _key(p: Any) -> tuple:
    """Слияние common: фамилия (identity) + клуб + позиция — не ломается при смене имени."""
    return (
        player_stats_identity_token(p).casefold(),
        (p.team or "").strip().lower(),
        (p.position or "").strip().upper(),
    )


def _apply_roster_fields(b: dict, p: Any, *, is_cl: bool) -> None:
    """Имя/фамилия в common — из лиги; из ЛЧ только если в бакете ещё пусто."""
    nm = (getattr(p, "name", None) or "").strip()
    sn = (getattr(p, "surname", None) or "").strip()
    if not is_cl:
        if nm:
            b["name"] = nm
        if sn:
            b["surname"] = sn
        elif nm and not (b.get("surname") or "").strip():
            b["surname"] = nm
    else:
        if sn and not (b.get("surname") or "").strip():
            b["surname"] = sn
        if nm and not (b.get("name") or "").strip():
            b["name"] = nm


def resolve_team_name_for_cl_pool(team_name: str) -> str | None:
    """
    Имя клуба, под которым он в пуле ЛЧ (для записей в ``champions_league_*.db``), или None.

    Сначала сверка с ``get_cl_participants()`` (``cl_participants_dynamic.txt``) — актуальные 30;
    иначе с ключами ``champ_league_teams.pkl`` (как раньше), чтобы старые сейвы не ломались.
    """
    import teams as teams_mod

    from champions_league.cl_format import get_cl_participants

    t = (team_name or "").strip()
    if t.casefold() == "цска":
        t = "Цска"
    tl = t.casefold()
    for name in get_cl_participants():
        if (name or "").strip().casefold() == tl:
            return (name or "").strip()
    for name in teams_mod.teams_champ_league.keys():
        if (name or "").strip().casefold() == tl:
            return (name or "").strip()
    return None


def _team_in_cl_pool(team_name: str) -> bool:
    """
    Клуб участвует в ЛЧ (динамический топ-30 и/или pickle): можно писать строки в БД ЛЧ и common.
    """
    return resolve_team_name_for_cl_pool(team_name) is not None


def _merge_bucket_outfield(PlayerCls, session_league, session_cl):
    """Слияние сессий. Счётчики наград сезона (golden_*) в двух БД — одна сущность; в common берётся max."""
    buckets: dict = {}
    for src in (session_league, session_cl):
        is_cl = src is session_cl
        for p in src.query(PlayerCls).all():
            if is_cl and not _team_in_cl_pool(p.team):
                continue
            k = _key(p)
            if k not in buckets:
                buckets[k] = {
                    "name": p.name,
                    "surname": (getattr(p, "surname", None) or "").strip() or None,
                    "team": p.team,
                    "position": p.position,
                    "matches": 0,
                    "goals": 0,
                    "assists": 0,
                    "yellow_cards": 0,
                    "red_cards": 0,
                    "trophies": 0,
                    "golden_balls": 0,
                    "golden_boots": 0,
                    "golden_boys": 0,
                    "overall_num": 0,
                    "overall_den": 0,
                    "nation": None,
                    "status": None,
                }
            b = buckets[k]
            _apply_roster_fields(b, p, is_cl=is_cl)
            nat = getattr(p, "nation", None)
            if nat and not b.get("nation"):
                b["nation"] = str(nat).strip() or None
            st = getattr(p, "status", None)
            if st and not b.get("status"):
                b["status"] = str(st).strip().lower() or None
            m = int(p.matches or 0)
            b["matches"] += m
            b["goals"] += int(getattr(p, "goals", 0) or 0)
            b["assists"] += int(getattr(p, "assists", 0) or 0)
            b["yellow_cards"] = b.get("yellow_cards", 0) + int(
                getattr(p, "yellow_cards", 0) or 0
            )
            b["red_cards"] = b.get("red_cards", 0) + int(
                getattr(p, "red_cards", 0) or 0
            )
            b["trophies"] += int(getattr(p, "trophies", 0) or 0)  # common: лиг. + лч, суммарно
            b["golden_balls"] = max(
                b["golden_balls"], int(getattr(p, "golden_balls", 0) or 0)
            )
            if hasattr(p, "golden_boots"):
                b["golden_boots"] = max(
                    b["golden_boots"],
                    int(getattr(p, "golden_boots", 0) or 0),
                )
            b["golden_boys"] = max(
                b["golden_boys"], int(getattr(p, "golden_boys", 0) or 0)
            )
            if m > 0:
                b["overall_num"] += int(p.overall or 0) * m
                b["overall_den"] += m
            ovi = int(getattr(p, "overall", 0) or 0)
            if ovi > 0:
                if not is_cl:
                    b["overall_ref"] = ovi
                elif int(b.get("overall_ref", 0) or 0) == 0:
                    b["overall_ref"] = ovi
    return buckets


def _add_outfield_rows(common, PlayerCls, buckets: dict) -> None:
    for b in buckets.values():
        mtot = b["matches"]
        ov = (
            b["overall_num"] // b["overall_den"]
            if b["overall_den"]
            else int(b.get("overall_ref", 0) or 0)
        )
        g, a = b["goals"], b["assists"]
        ga = g + a
        sn = (b.get("surname") or "").strip() or b["name"]
        if PlayerCls is Forward:
            common.add(
                Forward(
                    name=b["name"],
                    surname=sn,
                    team=b["team"],
                    position=b["position"],
                    overall=ov,
                    matches=mtot,
                    goals=g,
                    assists=a,
                    ga=ga,
                    trophies=b["trophies"],
                    golden_balls=b["golden_balls"],
                    golden_boots=b["golden_boots"],
                    golden_boys=b["golden_boys"],
                    nation=b.get("nation"),
                    status=b.get("status"),
                    yellow_cards=int(b.get("yellow_cards", 0) or 0),
                    red_cards=int(b.get("red_cards", 0) or 0),
                )
            )
        elif PlayerCls is Midfielder:
            common.add(
                Midfielder(
                    name=b["name"],
                    surname=sn,
                    team=b["team"],
                    position=b["position"],
                    overall=ov,
                    matches=mtot,
                    goals=g,
                    assists=a,
                    ga=ga,
                    trophies=b["trophies"],
                    golden_balls=b["golden_balls"],
                    golden_boots=b["golden_boots"],
                    golden_boys=b["golden_boys"],
                    nation=b.get("nation"),
                    status=b.get("status"),
                    yellow_cards=int(b.get("yellow_cards", 0) or 0),
                    red_cards=int(b.get("red_cards", 0) or 0),
                )
            )
        else:
            common.add(
                Defender(
                    name=b["name"],
                    surname=sn,
                    team=b["team"],
                    position=b["position"],
                    overall=ov,
                    matches=mtot,
                    goals=g,
                    assists=a,
                    ga=ga,
                    trophies=b["trophies"],
                    golden_balls=b["golden_balls"],
                    golden_boots=b["golden_boots"],
                    golden_boys=b["golden_boys"],
                    nation=b.get("nation"),
                    status=b.get("status"),
                    yellow_cards=int(b.get("yellow_cards", 0) or 0),
                    red_cards=int(b.get("red_cards", 0) or 0),
                )
            )


def rebuild_common_database(
    *,
    session_league_: Any = None,
    session_cl_: Any = None,
    session_common_: Any = None,
) -> None:
    """
    Полная перезапись common слиянием двух источников (имя+команда+позиция).
    По умолчанию — глобальные сессии из ``utils``; можно передать свои (например, в тестах).
    """
    sleague = session_league_ or session_league
    scl = session_cl_ or session_cl
    scommon = session_common_ or session_common

    Base.metadata.create_all(scommon.get_bind())
    common = scommon

    for cls in (Forward, Midfielder, Defender, Goalkeeper):
        common.query(cls).delete()
    common.commit()

    for Cls in (Forward, Midfielder, Defender):
        buckets = _merge_bucket_outfield(Cls, sleague, scl)
        _add_outfield_rows(common, Cls, buckets)

    gk_buckets: dict = {}
    for src in (sleague, scl):
        is_cl = src is scl
        for p in src.query(Goalkeeper).all():
            if is_cl and not _team_in_cl_pool(p.team):
                continue
            k = _key(p)
            if k not in gk_buckets:
                gk_buckets[k] = {
                    "name": p.name,
                    "surname": (getattr(p, "surname", None) or "").strip() or None,
                    "team": p.team,
                    "position": p.position,
                    "matches": 0,
                    "clean_sheets": 0,
                    "missed_goals": 0,
                    "trophies": 0,
                    "yellow_cards": 0,
                    "red_cards": 0,
                    "golden_balls": 0,
                    "golden_boots": 0,
                    "golden_gloves": 0,
                    "golden_boys": 0,
                    "overall_num": 0,
                    "overall_den": 0,
                    "nation": None,
                    "status": None,
                }
            b = gk_buckets[k]
            _apply_roster_fields(b, p, is_cl=is_cl)
            nat = getattr(p, "nation", None)
            if nat and not b.get("nation"):
                b["nation"] = str(nat).strip() or None
            st = getattr(p, "status", None)
            if st and not b.get("status"):
                b["status"] = str(st).strip().lower() or None
            m = int(p.matches or 0)
            b["matches"] += m
            b["clean_sheets"] += int(getattr(p, "clean_sheets", 0) or 0)
            b["missed_goals"] += int(getattr(p, "missed_goals", 0) or 0)
            b["trophies"] += int(getattr(p, "trophies", 0) or 0)  # common: лиг. + лч, суммарно
            b["yellow_cards"] = b.get("yellow_cards", 0) + int(
                getattr(p, "yellow_cards", 0) or 0
            )
            b["red_cards"] = b.get("red_cards", 0) + int(
                getattr(p, "red_cards", 0) or 0
            )
            b["golden_balls"] = max(
                b["golden_balls"], int(getattr(p, "golden_balls", 0) or 0)
            )
            b["golden_boots"] = max(
                b["golden_boots"], int(getattr(p, "golden_boots", 0) or 0)
            )
            b["golden_gloves"] = max(
                b["golden_gloves"], int(getattr(p, "golden_gloves", 0) or 0)
            )
            b["golden_boys"] = max(
                b["golden_boys"], int(getattr(p, "golden_boys", 0) or 0)
            )
            if m > 0:
                b["overall_num"] += int(p.overall or 0) * m
                b["overall_den"] += m
            ovi = int(getattr(p, "overall", 0) or 0)
            if ovi > 0:
                if not is_cl:
                    b["overall_ref"] = ovi
                elif int(b.get("overall_ref", 0) or 0) == 0:
                    b["overall_ref"] = ovi

    for b in gk_buckets.values():
        mtot = b["matches"]
        ov = (
            b["overall_num"] // b["overall_den"]
            if b["overall_den"]
            else int(b.get("overall_ref", 0) or 0)
        )
        gk_sn = (b.get("surname") or "").strip() or b["name"]
        common.add(
            Goalkeeper(
                name=b["name"],
                surname=gk_sn,
                team=b["team"],
                position=b["position"],
                overall=ov,
                matches=mtot,
                clean_sheets=b["clean_sheets"],
                missed_goals=b["missed_goals"],
                trophies=b["trophies"],
                golden_balls=b["golden_balls"],
                golden_boots=b["golden_boots"],
                golden_gloves=b["golden_gloves"],
                golden_boys=b["golden_boys"],
                nation=b.get("nation"),
                status=b.get("status"),
                yellow_cards=int(b.get("yellow_cards", 0) or 0),
                red_cards=int(b.get("red_cards", 0) or 0),
            )
        )

    scommon.commit()


def common_db_paths_info() -> str:
    return (
        f"league: {LEAGUE_DB_PATH}\n"
        f"cl: {CHAMPIONS_LEAGUE_DB_PATH}\n"
        f"common: {engine_common.url}"
    )


def rebuild_common_database_for_disk_paths(
    league_path: str,
    cl_path: str,
    common_path: str,
) -> None:
    """
    Пересобрать ``common`` на диске из двух указанных SQLite (лига + ЛЧ).
    Не трогает глобальные сессии ``utils``.
    """
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker

    if not os.path.isfile(league_path) or not os.path.isfile(cl_path):
        return
    parent = os.path.dirname(os.path.abspath(common_path))
    if parent:
        os.makedirs(parent, exist_ok=True)
    el = create_engine(f"sqlite:///{league_path}")
    ec = create_engine(f"sqlite:///{cl_path}")
    eo = create_engine(f"sqlite:///{common_path}")
    Sl = sessionmaker(bind=el)
    Scl = sessionmaker(bind=ec)
    So = sessionmaker(bind=eo)
    sl, scl, so = Sl(), Scl(), So()
    try:
        rebuild_common_database(
            session_league_=sl,
            session_cl_=scl,
            session_common_=so,
        )
    finally:
        sl.close()
        scl.close()
        so.close()
        el.dispose()
        ec.dispose()
        eo.dispose()


if __name__ == "__main__":
    rebuild_common_database()
    print("Пересобран:", COMMON_DB_PATH)
    print(common_db_paths_info())
