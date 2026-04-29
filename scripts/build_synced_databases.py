#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Собрать рабочие БД ``*_synced.db``:
  1) заявки из всех лиг → игроки с нулевой статой;
  2) перенос статистики из ``db/league_new.db`` и ``db/champions_league_new.db`` (архив, только чтение);
  3) пересборка ``common_synced.db``.

Архивные файлы не изменяются. Перед запуском сделайте копию ``db/*.db`` при необходимости.

  python scripts/build_synced_databases.py
"""
from __future__ import annotations

import shutil
import sqlite3
import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))


def _norm_team(team: str) -> str:
    t = (team or "").strip()
    if t == "ЦСКА":
        return "цска"
    return t.lower()


def _stat_key(name: str, team: str) -> tuple[str, str]:
    return ((name or "").strip().lower(), _norm_team(team))


def _row_i(row: sqlite3.Row, col: str, default: int = 0) -> int:
    try:
        v = row[col]
    except (KeyError, IndexError):
        return default
    if v is None:
        return default
    return int(v)


def _aggregate_archive_sqlite(db_path: Path) -> dict[tuple[str, str], dict]:
    """
    Читает архивную SQLite без ORM (старые файлы могут быть без колонки ``status``).
    """
    agg: dict[tuple[str, str], dict] = {}

    def bump(k: tuple[str, str], **kwargs) -> None:
        slot = agg.setdefault(
            k,
            {
                "matches": 0,
                "goals": 0,
                "assists": 0,
                "trophies": 0,
                "golden_balls": 0,
                "golden_boots": 0,
                "clean_sheets": 0,
                "missed_goals": 0,
                "overall_num": 0,
                "overall_den": 0,
            },
        )
        for key, val in kwargs.items():
            if key in ("overall_num", "overall_den"):
                slot[key] = slot.get(key, 0) + val
            else:
                slot[key] = int(slot.get(key, 0) or 0) + int(val or 0)

    uri = f"file:{db_path}?mode=ro"
    conn = sqlite3.connect(uri, uri=True)
    conn.row_factory = sqlite3.Row
    try:
        for table in ("forwards", "midfielders", "defenders"):
            for row in conn.execute(f"SELECT * FROM {table}"):
                k = _stat_key(row["name"], row["team"])
                m = _row_i(row, "matches")
                bump(
                    k,
                    matches=m,
                    goals=_row_i(row, "goals"),
                    assists=_row_i(row, "assists"),
                    trophies=_row_i(row, "trophies"),
                    golden_balls=_row_i(row, "golden_balls"),
                    golden_boots=_row_i(row, "golden_boots"),
                    clean_sheets=_row_i(row, "clean_sheets"),
                )
                if m > 0:
                    bump(
                        k,
                        overall_num=_row_i(row, "overall") * m,
                        overall_den=m,
                    )

        for row in conn.execute("SELECT * FROM goalkeepers"):
            k = _stat_key(row["name"], row["team"])
            m = _row_i(row, "matches")
            bump(
                k,
                matches=m,
                clean_sheets=_row_i(row, "clean_sheets"),
                missed_goals=_row_i(row, "missed_goals"),
                trophies=_row_i(row, "trophies"),
                golden_balls=_row_i(row, "golden_balls"),
            )
            if m > 0:
                bump(
                    k,
                    overall_num=_row_i(row, "overall") * m,
                    overall_den=m,
                )
    finally:
        conn.close()

    for s in agg.values():
        g, a = int(s.get("goals", 0)), int(s.get("assists", 0))
        s["ga"] = g + a
        od = int(s.get("overall_den", 0) or 0)
        s["overall_w"] = s["overall_num"] // od if od else 0
    return agg


def _apply_agg_to_target(target_session, agg: dict[tuple[str, str], dict]) -> int:
    from data.defender import Defender
    from data.forward import Forward
    from data.goalkeeper import Goalkeeper
    from data.midfielder import Midfielder

    n = 0
    for Cls in (Forward, Midfielder, Defender):
        for row in target_session.query(Cls).all():
            s = agg.get(_stat_key(row.name, row.team))
            if not s:
                continue
            n += 1
            row.matches = int(s["matches"] or 0)
            row.goals = int(s.get("goals", 0) or 0)
            row.assists = int(s.get("assists", 0) or 0)
            row.ga = int(s.get("ga", 0) or 0)
            row.trophies = int(s.get("trophies", 0) or 0)
            row.golden_balls = int(s.get("golden_balls", 0) or 0)
            if hasattr(row, "golden_boots"):
                row.golden_boots = int(s.get("golden_boots", 0) or 0)
            if hasattr(row, "clean_sheets"):
                row.clean_sheets = int(s.get("clean_sheets", 0) or 0)

    for row in target_session.query(Goalkeeper).all():
        s = agg.get(_stat_key(row.name, row.team))
        if not s:
            continue
        n += 1
        row.matches = int(s["matches"] or 0)
        row.clean_sheets = int(s.get("clean_sheets", 0) or 0)
        row.missed_goals = int(s.get("missed_goals", 0) or 0)
        row.trophies = int(s.get("trophies", 0) or 0)
        row.golden_balls = int(s.get("golden_balls", 0) or 0)

    target_session.commit()
    return n


def main() -> None:
    db_dir = _ROOT / "db"
    archive_league = db_dir / "league_new.db"
    archive_cl = db_dir / "champions_league_new.db"
    if not archive_league.is_file():
        raise SystemExit(f"Нет архива для чтения статистики: {archive_league}")

    backup_dir = db_dir / "backup_before_synced_build"
    for name in ("league_synced.db", "champions_league_synced.db", "common_synced.db"):
        p = db_dir / name
        if p.is_file() and p.stat().st_size > 0:
            backup_dir.mkdir(parents=True, exist_ok=True)
            shutil.copy2(p, backup_dir / name)

    for name in ("league_synced.db", "champions_league_synced.db", "common_synced.db"):
        p = db_dir / name
        if p.exists():
            p.unlink()

    from data.defender import Defender  # noqa: F401
    from data.forward import Forward  # noqa: F401
    from data.goalkeeper import Goalkeeper  # noqa: F401
    from data.midfielder import Midfielder  # noqa: F401

    from utils.utils import (
        Base,
        CHAMPIONS_LEAGUE_DB_PATH,
        COMMON_DB_PATH,
        LEAGUE_DB_PATH,
        engine_cl,
        engine_common,
        engine_league,
        session_cl,
        session_common,
        session_league,
    )

    for eng in (engine_league, engine_cl, engine_common):
        Base.metadata.create_all(eng)

    from utils.migrate_player_status import migrate_all_player_status_columns

    migrate_all_player_status_columns()

    from utils.merged_national_squads import merged_national_squads
    from utils.squad_roster_sync import run_squads_sync

    squads = merged_national_squads()
    run_squads_sync(squads, label="merged_national", rebuild_common=False)

    agg_le = _aggregate_archive_sqlite(archive_league)
    agg_cl = _aggregate_archive_sqlite(archive_cl)
    n_le = _apply_agg_to_target(session_league, agg_le)
    n_cl = _apply_agg_to_target(session_cl, agg_cl)

    from utils.common_db import rebuild_common_database

    rebuild_common_database()

    print("OK: собраны рабочие БД.")
    print(f"  league:   {LEAGUE_DB_PATH}")
    print(f"  cl:       {CHAMPIONS_LEAGUE_DB_PATH}")
    print(f"  common:   {COMMON_DB_PATH}")
    print(f"  архив лига (чтение): {archive_league}")
    print(f"  строк с перенесённой статой (лига): {n_le}, (ЛЧ): {n_cl}")


if __name__ == "__main__":
    main()
