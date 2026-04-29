# -*- coding: utf-8 -*-
"""
Накопительные БД в ``db/cumulative/`` (league.db, champions_league.db, common.db):
при завершении сезона текущие сезонные БД добавляются сюда.
``common.db`` в cumulative пересобирается из двух первых файлов.
"""
from __future__ import annotations

import os
import shutil
from typing import Any

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from data.defender import Defender
from data.forward import Forward
from data.goalkeeper import Goalkeeper
from data.midfielder import Midfielder
from utils import season_paths
from utils.utils import Base

_ALL = (Forward, Midfielder, Defender, Goalkeeper)


def _ensure_cumulative_dir() -> str:
    d = season_paths.get_cumulative_directory()
    os.makedirs(d, exist_ok=True)
    return d


def _row_as_new(Cls: type, p: Any) -> Any:
    d = {
        c.name: getattr(p, c.name)
        for c in Cls.__table__.columns
        if not c.primary_key
    }
    return Cls(**d)


def _merge_player_tables(src: Session, dst: Session, Cls: type) -> None:
    for p in src.query(Cls).all():
        row = (
            dst.query(Cls)
            .filter(
                Cls.name == p.name,
                Cls.team == p.team,
                Cls.position == p.position,
            )
            .first()
        )
        if row is None:
            dst.add(_row_as_new(Cls, p))
            continue
        old_m = int(getattr(row, "matches", 0) or 0)
        add_m = int(getattr(p, "matches", 0) or 0)
        row.matches = old_m + add_m
        if hasattr(row, "goals"):
            row.goals = int(getattr(row, "goals", 0) or 0) + int(
                getattr(p, "goals", 0) or 0
            )
            row.assists = int(getattr(row, "assists", 0) or 0) + int(
                getattr(p, "assists", 0) or 0
            )
            row.ga = int(getattr(row, "ga", 0) or 0) + int(getattr(p, "ga", 0) or 0)
        if hasattr(row, "clean_sheets"):
            row.clean_sheets = int(getattr(row, "clean_sheets", 0) or 0) + int(
                getattr(p, "clean_sheets", 0) or 0
            )
        if hasattr(row, "missed_goals"):
            row.missed_goals = int(getattr(row, "missed_goals", 0) or 0) + int(
                getattr(p, "missed_goals", 0) or 0
            )
        row.trophies = int(getattr(row, "trophies", 0) or 0) + int(
            getattr(p, "trophies", 0) or 0
        )
        row.yellow_cards = int(getattr(row, "yellow_cards", 0) or 0) + int(
            getattr(p, "yellow_cards", 0) or 0
        )
        row.red_cards = int(getattr(row, "red_cards", 0) or 0) + int(
            getattr(p, "red_cards", 0) or 0
        )
        for attr in (
            "golden_balls",
            "golden_boots",
            "golden_boys",
            "golden_gloves",
        ):
            if hasattr(row, attr):
                setattr(
                    row,
                    attr,
                    max(
                        int(getattr(row, attr, 0) or 0),
                        int(getattr(p, attr, 0) or 0),
                    ),
                )
        tot_m = row.matches
        if tot_m > 0 and hasattr(row, "overall"):
            row.overall = (
                int(getattr(row, "overall", 0) or 0) * old_m
                + int(getattr(p, "overall", 0) or 0) * add_m
            ) // tot_m
        if tot_m > 0 and hasattr(row, "rating"):
            row.rating = round(
                (
                    float(getattr(row, "rating", 0) or 0) * old_m
                    + float(getattr(p, "rating", 0) or 0) * add_m
                )
                / tot_m,
                1,
            )


def append_current_season_to_cumulative() -> dict[str, Any]:
    from utils.utils import session_cl, session_league

    log: dict[str, Any] = {"cumulative": []}
    _ensure_cumulative_dir()
    cur_l = season_paths.get_league_db_path()
    cur_c = season_paths.get_cl_db_path()
    cum_l = season_paths.get_cumulative_league_db_path()
    cum_c = season_paths.get_cumulative_cl_db_path()

    if not os.path.isfile(cur_l) or not os.path.isfile(cur_c):
        log["cumulative"].append("skip: season league/cl not on disk")
        return log

    fresh = not os.path.isfile(cum_l) and not os.path.isfile(cum_c)
    if fresh:
        shutil.copy2(cur_l, cum_l)
        shutil.copy2(cur_c, cum_c)
        log["cumulative"].append("initialized cumulative (copy of ending season)")
    else:
        eld = create_engine(f"sqlite:///{cum_l}")
        ecd = create_engine(f"sqlite:///{cum_c}")
        Sd = sessionmaker(bind=eld)
        Scd = sessionmaker(bind=ecd)
        sd, scd = Sd(), Scd()
        try:
            for Cls in _ALL:
                _merge_player_tables(session_league, sd, Cls)
                _merge_player_tables(session_cl, scd, Cls)
            sd.commit()
            scd.commit()
            log["cumulative"].append("merged additive into cumulative league+cl")
        finally:
            sd.close()
            scd.close()
            eld.dispose()
            ecd.dispose()

    from utils.common_db import rebuild_common_database_for_disk_paths

    rebuild_common_database_for_disk_paths(
        cum_l,
        cum_c,
        season_paths.get_cumulative_common_db_path(),
    )
    log["cumulative"].append("rebuilt cumulative common.db")
    return log


def list_season_archives_with_db() -> list[int]:
    """Номера папок db/season_n, где есть league.db."""
    out: list[int] = []
    db_dir = os.path.join(season_paths.PROJECT_ROOT, "db")
    if not os.path.isdir(db_dir):
        return out
    for name in os.listdir(db_dir):
        if not name.startswith("season_"):
            continue
        tail = name.replace("season_", "")
        if not tail.isdigit():
            continue
        n = int(tail)
        lp = os.path.join(db_dir, name, season_paths.SEASON_LEAGUE_NAME)
        if os.path.isfile(lp):
            out.append(n)
    return sorted(out)
