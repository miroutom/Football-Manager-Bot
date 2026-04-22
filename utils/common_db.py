# -*- coding: utf-8 -*-
"""
Объединённая БД ``common.db``: сумма статистики из ``league_new.db`` и ``champions_league_new.db``.
Пересборка: ``rebuild_common_database()`` (вызывается перед топами с tournament='common').
"""
from __future__ import annotations

from data.defender import Defender
from data.forward import Forward
from data.goalkeeper import Goalkeeper
from data.midfielder import Midfielder
from utils.utils import (
    Base,
    CHAMPIONS_LEAGUE_DB_PATH,
    LEAGUE_DB_PATH,
    SessionCommon,
    engine_common,
    session_cl,
    session_league,
)


def _key(name: str, team: str, position: str) -> tuple:
    return (name.strip().lower(), team.strip().lower(), position.strip())


def _merge_bucket_outfield(PlayerCls, src_sessions: tuple):
    buckets: dict = {}
    for src in src_sessions:
        for p in src.query(PlayerCls).all():
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
                }
            b = buckets[k]
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
                    nation=None,
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
                    nation=None,
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
                    nation=None,
                )
            )


def rebuild_common_database() -> None:
    """Полная перезапись ``common.db`` слиянием двух источников (имя+команда+позиция)."""
    Base.metadata.create_all(engine_common)
    common = SessionCommon()

    for cls in (Forward, Midfielder, Defender, Goalkeeper):
        common.query(cls).delete()
    common.commit()

    srcs = (session_league, session_cl)

    for Cls in (Forward, Midfielder, Defender):
        buckets = _merge_bucket_outfield(Cls, srcs)
        _add_outfield_rows(common, Cls, buckets)

    gk_buckets: dict = {}
    for src in srcs:
        for p in src.query(Goalkeeper).all():
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
                }
            b = gk_buckets[k]
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
                nation=None,
            )
        )

    common.commit()
    common.close()


def common_db_paths_info() -> str:
    return (
        f"league: {LEAGUE_DB_PATH}\n"
        f"cl: {CHAMPIONS_LEAGUE_DB_PATH}\n"
        f"common: {engine_common.url}"
    )
