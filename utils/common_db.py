# -*- coding: utf-8 -*-
"""
Объединённая БД ``common.db``: сумма статистики из ``league_new.db`` и ``champions_league_new.db``.
Пересборка: ``rebuild_common_database()`` (вызывается перед топами с tournament='common').
"""
from __future__ import annotations

import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from data.defender import Defender
from data.forward import Forward
from data.goalkeeper import Goalkeeper
from data.midfielder import Midfielder
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


def _key(name: str, team: str, position: str) -> tuple:
    return (name.strip().lower(), team.strip().lower(), position.strip())


def _team_in_cl_pool(team_name: str) -> bool:
    """
    Только клубы из списка участников ЛЧ (pickle champ_league_teams) должны давать строки из БД ЛЧ в common.
    Иначе ошибочные/чужие записи в champions_league_new.db не суммируются с лигой.
    """
    import teams as teams_mod

    pool = teams_mod.teams_champ_league.keys()
    t = (team_name or "").strip()
    if t == "ЦСКА":
        t = "Цска"
    tl = t.lower()
    for name in pool:
        if name.lower() == tl:
            return True
    return False


def _merge_bucket_outfield(PlayerCls, session_league, session_cl):
    buckets: dict = {}
    for src in (session_league, session_cl):
        is_cl = src is session_cl
        for p in src.query(PlayerCls).all():
            if is_cl and not _team_in_cl_pool(p.team):
                continue
            k = _key(p.name, p.team, p.position)
            if k not in buckets:
                buckets[k] = {
                    "name": p.name,
                    "team": p.team,
                    "position": p.position,
                    "matches": 0,
                    "goals": 0,
                    "assists": 0,
                    "trophies": 0,
                    "golden_balls": 0,
                    "golden_boots": 0,
                    "clean_sheets": 0,
                    "overall_num": 0,
                    "overall_den": 0,
                    "rating_num": 0.0,
                    "rating_den": 0,
                    "nation": None,
                    "status": None,
                }
            b = buckets[k]
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
            b["trophies"] += int(getattr(p, "trophies", 0) or 0)
            b["golden_balls"] += int(getattr(p, "golden_balls", 0) or 0)
            if hasattr(p, "golden_boots"):
                b["golden_boots"] += int(getattr(p, "golden_boots", 0) or 0)
            if hasattr(p, "clean_sheets"):
                b["clean_sheets"] += int(getattr(p, "clean_sheets", 0) or 0)
            if m > 0:
                b["overall_num"] += int(p.overall or 0) * m
                b["overall_den"] += m
                b["rating_num"] += float(p.rating or 0) * m
                b["rating_den"] += m
    return buckets


def _add_outfield_rows(common, PlayerCls, buckets: dict) -> None:
    for b in buckets.values():
        mtot = b["matches"]
        ov = b["overall_num"] // b["overall_den"] if b["overall_den"] else 0
        rt = (
            round(b["rating_num"] / b["rating_den"], 1) if b["rating_den"] else 0.0
        )
        g, a = b["goals"], b["assists"]
        ga = g + a
        if PlayerCls is Forward:
            common.add(
                Forward(
                    name=b["name"],
                    team=b["team"],
                    position=b["position"],
                    overall=ov,
                    matches=mtot,
                    goals=g,
                    assists=a,
                    ga=ga,
                    rating=rt,
                    trophies=b["trophies"],
                    golden_balls=b["golden_balls"],
                    golden_boots=b["golden_boots"],
                    nation=b.get("nation"),
                    status=b.get("status"),
                )
            )
        elif PlayerCls is Midfielder:
            common.add(
                Midfielder(
                    name=b["name"],
                    team=b["team"],
                    position=b["position"],
                    overall=ov,
                    matches=mtot,
                    goals=g,
                    assists=a,
                    ga=ga,
                    rating=rt,
                    trophies=b["trophies"],
                    golden_balls=b["golden_balls"],
                    golden_boots=b["golden_boots"],
                    nation=b.get("nation"),
                    status=b.get("status"),
                )
            )
        else:
            common.add(
                Defender(
                    name=b["name"],
                    team=b["team"],
                    position=b["position"],
                    overall=ov,
                    matches=mtot,
                    goals=g,
                    assists=a,
                    ga=ga,
                    rating=rt,
                    clean_sheets=b["clean_sheets"],
                    trophies=b["trophies"],
                    golden_balls=b["golden_balls"],
                    nation=b.get("nation"),
                    status=b.get("status"),
                )
            )


def rebuild_common_database() -> None:
    """Полная перезапись ``common.db`` слиянием двух источников (имя+команда+позиция)."""
    Base.metadata.create_all(engine_common)
    common = session_common

    for cls in (Forward, Midfielder, Defender, Goalkeeper):
        common.query(cls).delete()
    common.commit()

    for Cls in (Forward, Midfielder, Defender):
        buckets = _merge_bucket_outfield(Cls, session_league, session_cl)
        _add_outfield_rows(common, Cls, buckets)

    gk_buckets: dict = {}
    for src in (session_league, session_cl):
        is_cl = src is session_cl
        for p in src.query(Goalkeeper).all():
            if is_cl and not _team_in_cl_pool(p.team):
                continue
            k = _key(p.name, p.team, p.position)
            if k not in gk_buckets:
                gk_buckets[k] = {
                    "name": p.name,
                    "team": p.team,
                    "position": p.position,
                    "matches": 0,
                    "clean_sheets": 0,
                    "missed_goals": 0,
                    "trophies": 0,
                    "golden_balls": 0,
                    "overall_num": 0,
                    "overall_den": 0,
                    "rating_num": 0.0,
                    "rating_den": 0,
                    "nation": None,
                    "status": None,
                }
            b = gk_buckets[k]
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
            b["trophies"] += int(getattr(p, "trophies", 0) or 0)
            b["golden_balls"] += int(getattr(p, "golden_balls", 0) or 0)
            if m > 0:
                b["overall_num"] += int(p.overall or 0) * m
                b["overall_den"] += m
                b["rating_num"] += float(p.rating or 0) * m
                b["rating_den"] += m

    for b in gk_buckets.values():
        mtot = b["matches"]
        ov = b["overall_num"] // b["overall_den"] if b["overall_den"] else 0
        rt = round(b["rating_num"] / b["rating_den"], 1) if b["rating_den"] else 0.0
        common.add(
            Goalkeeper(
                name=b["name"],
                team=b["team"],
                position=b["position"],
                overall=ov,
                matches=mtot,
                rating=rt,
                clean_sheets=b["clean_sheets"],
                missed_goals=b["missed_goals"],
                trophies=b["trophies"],
                golden_balls=b["golden_balls"],
                nation=b.get("nation"),
                status=b.get("status"),
            )
        )

    common.commit()


def common_db_paths_info() -> str:
    return (
        f"league: {LEAGUE_DB_PATH}\n"
        f"cl: {CHAMPIONS_LEAGUE_DB_PATH}\n"
        f"common: {engine_common.url}"
    )


if __name__ == "__main__":
    rebuild_common_database()
    print("Пересобран:", COMMON_DB_PATH)
    print(common_db_paths_info())
