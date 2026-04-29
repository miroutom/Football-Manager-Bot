# -*- coding: utf-8 -*-
"""
Накопительная стата за все сезоны — ``db/league_synced.db``, ``db/champions_league_synced.db``,
``db/common_synced.db`` (пути через ``season_paths.get_cumulative_*``).

При завершении сезона в них добавляется снимок из ``db/season_N/``.

Миграции: старая папка ``db/cumulative/`` и плоские ``db/league.db`` (устар.) — перенос в synced,
если целевого файла ещё нет.
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

_ALL = (Forward, Midfielder, Defender, Goalkeeper)


def _migrate_old_cumulative_subfolder() -> None:
    old_d = os.path.join(season_paths.PROJECT_ROOT, "db", "cumulative")
    if not os.path.isdir(old_d):
        return
    pairs = [
        (season_paths.SEASON_LEAGUE_NAME, season_paths.get_cumulative_league_db_path()),
        (season_paths.SEASON_CL_NAME, season_paths.get_cumulative_cl_db_path()),
        (season_paths.SEASON_COMMON_NAME, season_paths.get_cumulative_common_db_path()),
    ]
    for name, dst in pairs:
        src = os.path.join(old_d, name)
        if os.path.isfile(src) and not os.path.isfile(dst):
            os.makedirs(os.path.dirname(dst) or ".", exist_ok=True)
            shutil.copy2(src, dst)


def _migrate_flat_root_all_time_dbs() -> None:
    """Устаревшие ``db/league.db`` и т.п. → в ``*_synced.db``, если synced ещё нет."""
    db = os.path.join(season_paths.PROJECT_ROOT, "db")
    flat = [
        ("league.db", season_paths.get_cumulative_league_db_path()),
        ("champions_league.db", season_paths.get_cumulative_cl_db_path()),
        ("common.db", season_paths.get_cumulative_common_db_path()),
    ]
    for name, dst in flat:
        src = os.path.join(db, name)
        if os.path.isfile(src) and not os.path.isfile(dst):
            shutil.copy2(src, dst)


def _row_as_new(Cls: type, p: Any) -> Any:
    d = {
        c.name: getattr(p, c.name)
        for c in Cls.__table__.columns
        if not c.primary_key
    }
    return Cls(**d)


def _merge_player_tables(src: Any, dst: Any, Cls: type) -> None:
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
                    int(getattr(row, attr, 0) or 0)
                    + int(getattr(p, attr, 0) or 0),
                )
        # Ростер из снимка только что завершённого сезона (совпадает с активной заявкой в архиве)
        row.overall = int(getattr(p, "overall", 0) or 0)
        row.team = getattr(p, "team", row.team)
        row.position = getattr(p, "position", row.position)
        if hasattr(row, "status"):
            row.status = getattr(p, "status", None)
        if hasattr(row, "nation"):
            row.nation = getattr(p, "nation", None)


def append_season_snapshot_to_all_time(league_path: str, cl_path: str) -> dict[str, Any]:
    """
    Добавить статистику из снимка сезона (два sqlite-файла) в общие ``db/league.db`` и
    ``db/champions_league.db``, затем пересобрать ``db/common.db``.
    """
    log: dict[str, Any] = {"cumulative": []}
    _migrate_old_cumulative_subfolder()
    _migrate_flat_root_all_time_dbs()
    os.makedirs(os.path.join(season_paths.PROJECT_ROOT, "db"), exist_ok=True)

    if not os.path.isfile(league_path) or not os.path.isfile(cl_path):
        log["cumulative"].append("skip: snapshot league/cl not found")
        return log

    cum_l = season_paths.get_cumulative_league_db_path()
    cum_c = season_paths.get_cumulative_cl_db_path()

    fresh = not os.path.isfile(cum_l) and not os.path.isfile(cum_c)
    if fresh:
        shutil.copy2(league_path, cum_l)
        shutil.copy2(cl_path, cum_c)
        log["cumulative"].append("initialized all-time DB (copy of ended season)")
    else:
        el_src = create_engine(f"sqlite:///{league_path}")
        ec_src = create_engine(f"sqlite:///{cl_path}")
        el_dst = create_engine(f"sqlite:///{cum_l}")
        ec_dst = create_engine(f"sqlite:///{cum_c}")
        Sl = sessionmaker(bind=el_src)
        Scl = sessionmaker(bind=ec_src)
        Sd = sessionmaker(bind=el_dst)
        Scd = sessionmaker(bind=ec_dst)
        sl, scl, sd, scd = Sl(), Scl(), Sd(), Scd()
        try:
            for Cls in _ALL:
                _merge_player_tables(sl, sd, Cls)
                _merge_player_tables(scl, scd, Cls)
            sd.commit()
            scd.commit()
            log["cumulative"].append("merged season snapshot into all-time league+cl")
        finally:
            sl.close()
            scl.close()
            sd.close()
            scd.close()
            el_src.dispose()
            ec_src.dispose()
            el_dst.dispose()
            ec_dst.dispose()

    from utils.common_db import rebuild_common_database_for_disk_paths

    rebuild_common_database_for_disk_paths(
        cum_l,
        cum_c,
        season_paths.get_cumulative_common_db_path(),
    )
    log["cumulative"].append("rebuilt db/common.db (all-time)")
    return log


def append_current_season_to_cumulative() -> dict[str, Any]:
    """Слить текущие рабочие пути сезона (как в season_paths) в общие db/*.db."""
    return append_season_snapshot_to_all_time(
        season_paths.get_league_db_path(),
        season_paths.get_cl_db_path(),
    )


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
