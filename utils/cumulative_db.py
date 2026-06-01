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
from utils.player_names import player_stats_identity_token

_ALL = (Forward, Midfielder, Defender, Goalkeeper)

# (tablename, row_id) → номер сезона, откуда взяты имя/клуб/рейтинг
_roster_season_meta: dict[tuple[str, int], int] = {}


def _clear_roster_season_meta() -> None:
    _roster_season_meta.clear()


def _player_identity_key(row: Any) -> tuple[str, str]:
    """Один игрок за карьеру: фамилия (identity token) + позиция, без клуба."""
    return (
        player_stats_identity_token(row).casefold(),
        (row.position or "").strip().upper(),
    )


def _row_key(row: Any) -> tuple[str, str, str]:
    """Дубли в одной накопительной БД: identity + клуб + позиция."""
    return (
        player_stats_identity_token(row).casefold(),
        (row.team or "").strip().casefold(),
        (row.position or "").strip().upper(),
    )


def _find_row_by_identity(dst: Any, Cls: type, src_row: Any) -> Any | None:
    want = _player_identity_key(src_row)
    for row in dst.query(Cls).all():
        if _player_identity_key(row) == want:
            return row
    return None


def _roster_score(row: Any) -> int:
    """Выше — осмысленнее раздельные имя и фамилия (не «Фати / Фати»)."""
    fn = (getattr(row, "name", None) or "").strip()
    sn = (getattr(row, "surname", None) or "").strip()
    if fn and sn and fn.casefold() != sn.casefold():
        return 3
    if sn and fn and fn.casefold() in sn.casefold() and len(sn.split()) > len(fn.split()):
        return 2
    if sn:
        return 1
    return 0


def _apply_roster_from_source(dst: Any, src: Any, *, season_num: int, tbl: str) -> None:
    """Имя, фамилия, клуб, рейтинг — из более позднего сезона; при равенстве — лучшая подпись."""
    meta_key = (tbl, int(getattr(dst, "id", 0) or 0))
    prev_season = _roster_season_meta.get(meta_key, 0)
    src_score = _roster_score(src)
    dst_score = _roster_score(dst)

    if season_num > prev_season:
        take = True
    elif season_num < prev_season:
        take = False
    else:
        take = src_score > dst_score or (
            src_score == dst_score
            and int(getattr(src, "overall", 0) or 0) >= int(getattr(dst, "overall", 0) or 0)
        )

    if not take:
        return

    dst.name = getattr(src, "name", dst.name)
    dst.overall = int(getattr(src, "overall", 0) or 0)
    dst.team = getattr(src, "team", dst.team)
    dst.position = getattr(src, "position", dst.position)
    if hasattr(dst, "status"):
        dst.status = getattr(src, "status", None)
    if hasattr(dst, "nation"):
        dst.nation = getattr(src, "nation", None)
    _roster_season_meta[meta_key] = season_num


def _fold_stats_into_row(dst_row: Any, src_row: Any) -> None:
    dst_row.matches = int(getattr(dst_row, "matches", 0) or 0) + int(
        getattr(src_row, "matches", 0) or 0
    )
    if hasattr(dst_row, "goals"):
        dst_row.goals = int(getattr(dst_row, "goals", 0) or 0) + int(
            getattr(src_row, "goals", 0) or 0
        )
        dst_row.assists = int(getattr(dst_row, "assists", 0) or 0) + int(
            getattr(src_row, "assists", 0) or 0
        )
        dst_row.ga = int(getattr(dst_row, "ga", 0) or 0) + int(
            getattr(src_row, "ga", 0) or 0
        )
    if hasattr(dst_row, "clean_sheets") and not hasattr(dst_row, "goals"):
        dst_row.clean_sheets = int(getattr(dst_row, "clean_sheets", 0) or 0) + int(
            getattr(src_row, "clean_sheets", 0) or 0
        )
    if hasattr(dst_row, "missed_goals"):
        dst_row.missed_goals = int(getattr(dst_row, "missed_goals", 0) or 0) + int(
            getattr(src_row, "missed_goals", 0) or 0
        )
    dst_row.trophies = int(getattr(dst_row, "trophies", 0) or 0) + int(
        getattr(src_row, "trophies", 0) or 0
    )
    # В рабочих БД жк/кк накапливаются карьерно; снимок сезона — монотонный итог → max, не sum.
    dst_row.yellow_cards = max(
        int(getattr(dst_row, "yellow_cards", 0) or 0),
        int(getattr(src_row, "yellow_cards", 0) or 0),
    )
    dst_row.red_cards = max(
        int(getattr(dst_row, "red_cards", 0) or 0),
        int(getattr(src_row, "red_cards", 0) or 0),
    )
    for attr in ("golden_balls", "golden_boots", "golden_boys", "golden_gloves"):
        if hasattr(dst_row, attr):
            setattr(
                dst_row,
                attr,
                int(getattr(dst_row, attr, 0) or 0)
                + int(getattr(src_row, attr, 0) or 0),
            )


def _consolidate_identity_duplicates(dst: Any, Cls: type) -> None:
    """Слить дубли (identity + клуб + позиция) в накопительной БД."""
    groups: dict[tuple[str, str, str], list[Any]] = {}
    for row in list(dst.query(Cls).all()):
        groups.setdefault(_row_key(row), []).append(row)
    for rows in groups.values():
        if len(rows) <= 1:
            continue
        rows.sort(key=lambda r: int(getattr(r, "id", 0) or 0))
        keep = rows[-1]
        for other in rows[:-1]:
            _fold_stats_into_row(keep, other)
            dst.delete(other)


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


def _merge_player_tables(
    src: Any, dst: Any, Cls: type, *, season_num: int
) -> None:
    tbl = Cls.__tablename__
    players = list(src.query(Cls).all())
    # Сначала слабые подписи (Фати/Фати), потом нормальные (Ансу/Фати)
    players.sort(
        key=lambda p: (
            _roster_score(p),
            int(getattr(p, "matches", 0) or 0),
            int(getattr(p, "id", 0) or 0),
        )
    )
    for p in players:
        row = _find_row_by_identity(dst, Cls, p)
        if row is None:
            new_row = _row_as_new(Cls, p)
            dst.add(new_row)
            dst.flush()
            _apply_roster_from_source(new_row, p, season_num=season_num, tbl=tbl)
            continue
        _fold_stats_into_row(row, p)
        _apply_roster_from_source(row, p, season_num=season_num, tbl=tbl)


def _season_num_from_path(league_path: str) -> int:
    import re

    m = re.search(r"season_(\d+)", league_path.replace("\\", "/"))
    return int(m.group(1)) if m else 0


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

    season_num = _season_num_from_path(league_path)
    fresh = not os.path.isfile(cum_l) and not os.path.isfile(cum_c)
    if fresh:
        shutil.copy2(league_path, cum_l)
        shutil.copy2(cl_path, cum_c)
        _clear_roster_season_meta()
        if season_num:
            from sqlalchemy import create_engine as ce
            from sqlalchemy.orm import sessionmaker as sm

            for path, Cls_list in (
                (cum_l, _ALL),
                (cum_c, _ALL),
            ):
                eng = ce(f"sqlite:///{path}")
                S = sm(bind=eng)
                sess = S()
                try:
                    for Cls in Cls_list:
                        tbl = Cls.__tablename__
                        for row in sess.query(Cls).all():
                            _roster_season_meta[(tbl, int(row.id))] = season_num
                    sess.commit()
                finally:
                    sess.close()
                    eng.dispose()
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
            sn = season_num or 99
            for Cls in _ALL:
                _merge_player_tables(sl, sd, Cls, season_num=sn)
                _merge_player_tables(scl, scd, Cls, season_num=sn)
                _consolidate_identity_duplicates(sd, Cls)
                _consolidate_identity_duplicates(scd, Cls)
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


def rebuild_all_time_databases_from_season_archives() -> dict[str, Any]:
    """Пересобрать ``*_synced.db`` из ``db/season_n/{league,champions_league}.db``."""
    _clear_roster_season_meta()
    seasons = list_season_archives_with_db()
    log: dict[str, Any] = {"cumulative": [], "seasons": seasons}
    if not seasons:
        log["cumulative"].append("no season archives")
        return log

    _migrate_old_cumulative_subfolder()
    _migrate_flat_root_all_time_dbs()
    db_dir = os.path.join(season_paths.PROJECT_ROOT, "db")
    cum_l = season_paths.get_cumulative_league_db_path()
    cum_c = season_paths.get_cumulative_cl_db_path()
    cum_o = season_paths.get_cumulative_common_db_path()
    for path in (cum_l, cum_c, cum_o):
        if os.path.isfile(path):
            os.unlink(path)

    first = seasons[0]
    lp1 = os.path.join(db_dir, f"season_{first}", season_paths.SEASON_LEAGUE_NAME)
    cp1 = os.path.join(db_dir, f"season_{first}", season_paths.SEASON_CL_NAME)
    shutil.copy2(lp1, cum_l)
    shutil.copy2(cp1, cum_c)
    log["cumulative"].append(f"seed season_{first}")

    for sn in seasons[1:]:
        lp = os.path.join(db_dir, f"season_{sn}", season_paths.SEASON_LEAGUE_NAME)
        cp = os.path.join(db_dir, f"season_{sn}", season_paths.SEASON_CL_NAME)
        part = append_season_snapshot_to_all_time(lp, cp)
        log["cumulative"].extend(part.get("cumulative", []))

    if len(seasons) == 1:
        from utils.common_db import rebuild_common_database_for_disk_paths

        rebuild_common_database_for_disk_paths(cum_l, cum_c, cum_o)
        log["cumulative"].append("rebuilt db/common.db (all-time)")
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
