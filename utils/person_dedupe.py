# -*- coding: utf-8 -*-
"""Слияние дублей игроков и выравнивание ``person_id`` во всех БД проекта."""
from __future__ import annotations

import os
import sqlite3
from collections import defaultdict
from typing import Any

from utils import season_paths
from utils.person_registry import _identity_pos_key
from utils.player_transfer import _norm_cmp

_TABLES = ("forwards", "midfielders", "defenders", "goalkeepers")

_OUTFIELD_STAT = (
    "matches",
    "goals",
    "assists",
    "ga",
    "trophies",
    "yellow_cards",
    "red_cards",
    "golden_balls",
    "golden_boots",
    "golden_boys",
)
_GK_STAT = (
    "matches",
    "clean_sheets",
    "missed_goals",
    "trophies",
    "yellow_cards",
    "red_cards",
    "golden_balls",
    "golden_boots",
    "golden_gloves",
    "golden_boys",
)


def iter_player_db_paths() -> list[str]:
    paths: list[str] = []
    for getter in (
        season_paths.get_league_db_path,
        season_paths.get_cl_db_path,
        season_paths.get_cumulative_league_db_path,
        season_paths.get_cumulative_cl_db_path,
        season_paths.get_cumulative_common_db_path,
    ):
        p = getter()
        if p and os.path.isfile(p):
            paths.append(os.path.abspath(p))

    db_dir = os.path.join(season_paths.PROJECT_ROOT, "db")
    if os.path.isdir(db_dir):
        for entry in sorted(os.listdir(db_dir)):
            if not entry.startswith("season_"):
                continue
            for fname in (
                season_paths.SEASON_LEAGUE_NAME,
                season_paths.SEASON_CL_NAME,
                season_paths.SEASON_COMMON_NAME,
            ):
                path = os.path.join(db_dir, entry, fname)
                if os.path.isfile(path):
                    paths.append(os.path.abspath(path))

    out: list[str] = []
    seen: set[str] = set()
    for p in paths:
        if p not in seen:
            seen.add(p)
            out.append(p)
    return out


def _table_stats(tbl: str) -> tuple[str, ...]:
    return _GK_STAT if tbl == "goalkeepers" else _OUTFIELD_STAT


def _row_score(row: dict[str, Any], stats: tuple[str, ...]) -> tuple[int, int]:
    matches = int(row.get("matches", 0) or 0)
    stat_sum = sum(int(row.get(k, 0) or 0) for k in stats if k != "matches")
    pid = int(row.get("person_id", 0) or 0)
    return (matches + stat_sum, -pid if pid > 0 else 0)


def _fold_stat_into(keep: dict[str, Any], other: dict[str, Any], stats: tuple[str, ...]) -> None:
    for k in stats:
        if k not in keep and k not in other:
            continue
        a = int(keep.get(k, 0) or 0)
        b = int(other.get(k, 0) or 0)
        if k in ("yellow_cards", "red_cards"):
            keep[k] = max(a, b)
        else:
            keep[k] = a + b
    if "goals" in keep and "assists" in keep:
        keep["ga"] = int(keep.get("goals", 0) or 0) + int(keep.get("assists", 0) or 0)


def build_person_id_remap(paths: list[str] | None = None) -> dict[int, int]:
    """Лишние ``person_id`` → канонический (max ``matches`` по карьере, иначе min id)."""
    paths = paths or iter_player_db_paths()
    by_identity: dict[tuple[str, str], dict[int, int]] = defaultdict(
        lambda: defaultdict(int)
    )

    for path in paths:
        conn = sqlite3.connect(path)
        try:
            for tbl in _TABLES:
                cols = {r[1] for r in conn.execute(f"PRAGMA table_info({tbl})").fetchall()}
                if "person_id" not in cols or "name" not in cols:
                    continue
                q = f"SELECT name, position, person_id, matches FROM {tbl}"
                for nm, pos_row, pid_raw, matches_raw in conn.execute(q):
                    ident, pos = _identity_pos_key(nm or "", pos_row or "")
                    try:
                        pid = int(pid_raw or 0)
                    except (TypeError, ValueError):
                        continue
                    if pid <= 0:
                        continue
                    m = int(matches_raw or 0)
                    prev = by_identity[(ident, pos)][pid]
                    if m > prev:
                        by_identity[(ident, pos)][pid] = m
        finally:
            conn.close()

    remap: dict[int, int] = {}
    for pid_map in by_identity.values():
        if len(pid_map) <= 1:
            continue
        best_m = max(pid_map.values())
        leaders = [pid for pid, m in pid_map.items() if m == best_m]
        canonical = min(leaders)
        for pid in pid_map:
            if pid != canonical:
                remap[pid] = canonical
    return remap


def dedupe_sqlite_db(path: str, pid_remap: dict[int, int]) -> dict[str, int]:
    """Слить дубли (имя+позиция+клуб) и применить remap ``person_id``."""
    log = {"merged_groups": 0, "deleted_rows": 0, "remapped_rows": 0}
    if not os.path.isfile(path):
        return log

    conn = sqlite3.connect(path)
    try:
        for tbl in _TABLES:
            cols = {r[1] for r in conn.execute(f"PRAGMA table_info({tbl})").fetchall()}
            if "name" not in cols or "team" not in cols or "position" not in cols:
                continue
            stats = _table_stats(tbl)
            sel = ["id", "name", "team", "position", "person_id"] + [
                c for c in stats if c in cols
            ]
            rows = [
                dict(zip(sel, raw))
                for raw in conn.execute(f"SELECT {', '.join(sel)} FROM {tbl}")
            ]
            groups: dict[tuple[str, str, str], list[dict[str, Any]]] = defaultdict(list)
            for row in rows:
                ident, pos = _identity_pos_key(row["name"] or "", row["position"] or "")
                team = _norm_cmp(row.get("team") or "")
                groups[(ident, pos, team)].append(row)

            for group in groups.values():
                stats_cols = [c for c in stats if c in cols]
                if len(group) == 1:
                    row = group[0]
                    pid = int(row.get("person_id") or 0)
                    if pid in pid_remap:
                        conn.execute(
                            f"UPDATE {tbl} SET person_id = ? WHERE id = ?",
                            (pid_remap[pid], row["id"]),
                        )
                        log["remapped_rows"] += 1
                    continue

                ranked = sorted(
                    group,
                    key=lambda r: _row_score(r, stats),
                    reverse=True,
                )
                keep = dict(ranked[0])
                keep_pid = int(keep.get("person_id") or 0)
                if keep_pid in pid_remap:
                    keep_pid = pid_remap[keep_pid]

                for other in ranked[1:]:
                    _fold_stat_into(keep, other, stats_cols)
                    conn.execute(f"DELETE FROM {tbl} WHERE id = ?", (other["id"],))
                    log["deleted_rows"] += 1

                sets = []
                vals: list[Any] = []
                for c in stats_cols:
                    sets.append(f"{c} = ?")
                    vals.append(int(keep.get(c, 0) or 0))
                if "person_id" in cols and keep_pid > 0:
                    sets.append("person_id = ?")
                    vals.append(keep_pid)
                vals.append(keep["id"])
                conn.execute(
                    f"UPDATE {tbl} SET {', '.join(sets)} WHERE id = ?",
                    vals,
                )
                log["merged_groups"] += 1
        conn.commit()
    finally:
        conn.close()
    return log


def build_archive_canonical_person_ids(
    archive_seasons: tuple[int, ...] = (1, 2),
) -> dict[tuple[str, str], int]:
    """Канонический ``person_id`` из зафиксированных архивов (до bulk-заявок)."""
    db_dir = os.path.join(season_paths.PROJECT_ROOT, "db")
    best: dict[tuple[str, str], tuple[int, int]] = {}

    for sn in archive_seasons:
        for fname in (season_paths.SEASON_LEAGUE_NAME, season_paths.SEASON_CL_NAME):
            path = os.path.join(db_dir, f"season_{sn}", fname)
            if not os.path.isfile(path):
                continue
            conn = sqlite3.connect(path)
            try:
                for tbl in _TABLES:
                    cols = {
                        r[1] for r in conn.execute(f"PRAGMA table_info({tbl})").fetchall()
                    }
                    if "person_id" not in cols:
                        continue
                    q = f"SELECT name, position, person_id, matches FROM {tbl}"
                    for nm, pos_row, pid_raw, matches_raw in conn.execute(q):
                        ident, pos = _identity_pos_key(nm or "", pos_row or "")
                        try:
                            pid = int(pid_raw or 0)
                        except (TypeError, ValueError):
                            continue
                        if pid <= 0:
                            continue
                        m = int(matches_raw or 0)
                        key = (ident, pos)
                        prev = best.get(key)
                        if prev is None or (m, -pid) > (prev[0], -prev[1]):
                            best[key] = (m, pid)
            finally:
                conn.close()

    return {key: pid for key, (_m, pid) in best.items()}


def apply_archive_person_ids_to_all_dbs(
    canonical: dict[tuple[str, str], int] | None = None,
) -> dict[str, int]:
    """Переписать ``person_id`` во всех БД по архивному канону (ident+pos)."""
    canonical = canonical or build_archive_canonical_person_ids()
    log = {"updated_rows": 0}
    for path in iter_player_db_paths():
        conn = sqlite3.connect(path)
        try:
            for tbl in _TABLES:
                cols = {r[1] for r in conn.execute(f"PRAGMA table_info({tbl})").fetchall()}
                if "person_id" not in cols:
                    continue
                for row_id, nm, pos_row, pid_raw in conn.execute(
                    f"SELECT id, name, position, person_id FROM {tbl}"
                ):
                    ident, pos = _identity_pos_key(nm or "", pos_row or "")
                    want = canonical.get((ident, pos))
                    if want is None:
                        continue
                    try:
                        cur = int(pid_raw or 0)
                    except (TypeError, ValueError):
                        cur = 0
                    if cur == want:
                        continue
                    conn.execute(
                        f"UPDATE {tbl} SET person_id = ? WHERE id = ?",
                        (want, row_id),
                    )
                    log["updated_rows"] += 1
            conn.commit()
        finally:
            conn.close()
    return log


def dedupe_all_player_databases(*, rebuild_common: bool = True) -> dict[str, Any]:
    paths = iter_player_db_paths()
    archive_restore = apply_archive_person_ids_to_all_dbs()
    remap = build_person_id_remap(paths)
    per_db: dict[str, dict[str, int]] = {}
    for path in paths:
        per_db[os.path.basename(path)] = dedupe_sqlite_db(path, remap)

    out: dict[str, Any] = {
        "archive_person_id_restore": archive_restore,
        "person_id_remap": {str(k): v for k, v in sorted(remap.items())},
        "databases": per_db,
    }

    if rebuild_common:
        from utils.cumulative_db import rebuild_all_time_databases_from_season_archives
        from utils.common_db import rebuild_common_database_for_disk_paths

        out["cumulative_rebuild"] = rebuild_all_time_databases_from_season_archives()
        remap2 = build_person_id_remap(iter_player_db_paths())
        for path in (
            season_paths.get_cumulative_league_db_path(),
            season_paths.get_cumulative_cl_db_path(),
            season_paths.get_cumulative_common_db_path(),
        ):
            if os.path.isfile(path):
                per_db[os.path.basename(path) + ":pass2"] = dedupe_sqlite_db(
                    path, remap2
                )
        rebuild_common_database_for_disk_paths(
            season_paths.get_cumulative_league_db_path(),
            season_paths.get_cumulative_cl_db_path(),
            season_paths.get_cumulative_common_db_path(),
            include_all_cl_teams=True,
        )
        out["common_rebuilt"] = True

        lp = season_paths.get_league_db_path()
        cp = season_paths.get_cl_db_path()
        active_common = season_paths.get_common_db_path()
        if os.path.isfile(lp) and os.path.isfile(cp) and os.path.isfile(active_common):
            rebuild_common_database_for_disk_paths(
                lp, cp, active_common, include_all_cl_teams=False
            )
            out["active_common_rebuilt"] = True

    return out
