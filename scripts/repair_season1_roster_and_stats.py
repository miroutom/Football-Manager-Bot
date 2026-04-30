# -*- coding: utf-8 -*-
"""
Разовая правка архива 1-го сезона и накопительных *_synced.db:

1) Позиции, нации, overall из заявок (data/*_squads.py) — только эти поля.
2) Лауриент → Лориент (Реал Сосьедад, ЛФА): в лиге 11 матчей, 5 голов, 6 передач; в ЛЧ — переименование.
3) Симонс (Аталанта, ЦАП): +1 матч ЛЧ, +2 гола; +3 матча лиги, +6 голов, +4 передачи.
4) Палмер (Рубин): ровно 3 матча, 2 гола, 0 передач; позиция ПФА из заявки.

Используется только sqlite3 (старые архивы без колонок golden_boys / yellow_cards и т.д.).
Перед rebuild_common добавляются недостающие колонки под ORM.

Запуск из корня репозитория:
  python3 scripts/repair_season1_roster_and_stats.py

Перед запуском сделайте копию db/.

Скрипт рассчитан на **однократный** запуск (повтор прибавит Симонсу матчи/голы снова).
"""
from __future__ import annotations

import os
import sqlite3
import sys
import time
_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

from data.england_apl_squads import ENGLAND_APL_SQUADS
from data.germany_bundesliga_squads import GERMANY_BUNDESLIGA_SQUADS
from data.italy_seria_a_squads import ITALY_SERIE_A_SQUADS
from data.russia_rpl_squads import RUSSIA_RPL_SQUADS
from data.spain_la_liga_squads import SPAIN_LA_LIGA_SQUADS
from utils import season_paths
from utils.common_db import rebuild_common_database_for_disk_paths

PLAYER_TABLES = ("forwards", "midfielders", "defenders", "goalkeepers")

LAURIENT_OLD = "Лауриент"
LAURIENT_NEW = "Лориент"
LAURIENT_TEAM = "Реал Сосьедад"
LAURIENT_LEAGUE_MATCHES = 11
LAURIENT_LEAGUE_GOALS = 5
LAURIENT_LEAGUE_ASSISTS = 6

SIMMONS_NAME, SIMMONS_TEAM, SIMMONS_POS = "Симонс", "Аталанта", "ЦАП"
SIMMONS_CL_ADD = (1, 2, 0)
SIMMONS_LEAGUE_ADD = (3, 6, 4)

PALMER_NAME, PALMER_TEAM = "Палмер", "Рубин"
PALMER_MATCHES, PALMER_GOALS, PALMER_ASSISTS = 3, 2, 0


def _cols(conn: sqlite3.Connection, table: str) -> set[str]:
    return {r[1] for r in conn.execute(f"PRAGMA table_info({table})")}


def _add_col(conn: sqlite3.Connection, table: str, col: str, ddl: str) -> None:
    if col in _cols(conn, table):
        return
    conn.execute(f"ALTER TABLE {table} ADD COLUMN {col} {ddl}")


def ensure_orm_columns(conn: sqlite3.Connection) -> None:
    """Добавить колонки, которые ожидает SQLAlchemy-модель и rebuild_common."""
    for t in ("forwards", "midfielders", "defenders"):
        _add_col(conn, t, "golden_boys", "INTEGER DEFAULT 0")
        _add_col(conn, t, "yellow_cards", "INTEGER DEFAULT 0")
        _add_col(conn, t, "red_cards", "INTEGER DEFAULT 0")
        if t == "defenders":
            _add_col(conn, t, "golden_boots", "INTEGER DEFAULT 0")
        else:
            _add_col(conn, t, "golden_boots", "INTEGER DEFAULT 0")
    for c, ddl in (
        ("golden_boots", "INTEGER DEFAULT 0"),
        ("golden_gloves", "INTEGER DEFAULT 0"),
        ("golden_boys", "INTEGER DEFAULT 0"),
        ("yellow_cards", "INTEGER DEFAULT 0"),
        ("red_cards", "INTEGER DEFAULT 0"),
    ):
        _add_col(conn, "goalkeepers", c, ddl)


def build_roster_meta() -> dict[tuple[str, str], tuple[str, str | None, int]]:
    meta: dict[tuple[str, str], tuple[str, str | None, int]] = {}
    for squads in (
        SPAIN_LA_LIGA_SQUADS,
        ITALY_SERIE_A_SQUADS,
        RUSSIA_RPL_SQUADS,
        ENGLAND_APL_SQUADS,
        GERMANY_BUNDESLIGA_SQUADS,
    ):
        for team, rows in squads.items():
            for name, pos, ov, nation, _st in rows:
                meta[(team, name)] = (pos, nation, int(ov))
    if (LAURIENT_TEAM, LAURIENT_OLD) in meta:
        meta[(LAURIENT_TEAM, LAURIENT_NEW)] = meta[(LAURIENT_TEAM, LAURIENT_OLD)]
    return meta


def sync_roster_sqlite(path: str, meta: dict[tuple[str, str], tuple[str, str | None, int]]) -> int:
    conn = sqlite3.connect(path)
    try:
        ensure_orm_columns(conn)
        n = 0
        for table in PLAYER_TABLES:
            cur = conn.execute(
                f"SELECT id, team, name FROM {table}"  # noqa: S608
            )
            for row_id, team, name in cur.fetchall():
                key = (str(team).strip(), str(name).strip())
                if key not in meta:
                    continue
                pos, nation, ov = meta[key]
                conn.execute(
                    f"UPDATE {table} SET position=?, overall=?, nation=? WHERE id=?",  # noqa: S608
                    (pos, ov, nation, row_id),
                )
                n += 1
        conn.commit()
        return n
    finally:
        conn.close()


def rename_sqlite(path: str, old: str, new: str, team: str) -> int:
    conn = sqlite3.connect(path)
    try:
        ensure_orm_columns(conn)
        total = 0
        for table in PLAYER_TABLES:
            r = conn.execute(
                f"UPDATE {table} SET name=? WHERE name=? AND team=?",  # noqa: S608
                (new, old, team),
            )
            total += r.rowcount or 0
        conn.commit()
        return total
    finally:
        conn.close()


def apply_lauriente_league_stats(path: str) -> int:
    conn = sqlite3.connect(path)
    try:
        ensure_orm_columns(conn)
        cur = conn.execute(
            "UPDATE forwards SET matches=?, goals=?, assists=?, ga=? "
            "WHERE team=? AND position='ЛФА' AND name IN (?, ?)",
            (
                LAURIENT_LEAGUE_MATCHES,
                LAURIENT_LEAGUE_GOALS,
                LAURIENT_LEAGUE_ASSISTS,
                LAURIENT_LEAGUE_GOALS + LAURIENT_LEAGUE_ASSISTS,
                LAURIENT_TEAM,
                LAURIENT_OLD,
                LAURIENT_NEW,
            ),
        )
        n = cur.rowcount or 0
        conn.commit()
        return n
    finally:
        conn.close()


def bump_simmons_sqlite(path: str, add_m: int, add_g: int, add_a: int) -> int:
    conn = sqlite3.connect(path)
    try:
        ensure_orm_columns(conn)
        cur = conn.execute(
            "UPDATE midfielders SET matches=COALESCE(matches,0)+?, "
            "goals=COALESCE(goals,0)+?, assists=COALESCE(assists,0)+? "
            "WHERE name=? AND team=? AND position=?",
            (add_m, add_g, add_a, SIMMONS_NAME, SIMMONS_TEAM, SIMMONS_POS),
        )
        n = cur.rowcount or 0
        conn.execute(
            "UPDATE midfielders SET ga=COALESCE(goals,0)+COALESCE(assists,0) "
            "WHERE name=? AND team=? AND position=?",
            (SIMMONS_NAME, SIMMONS_TEAM, SIMMONS_POS),
        )
        conn.commit()
        return n
    finally:
        conn.close()


def set_palmer_sqlite(path: str) -> int:
    conn = sqlite3.connect(path)
    try:
        ensure_orm_columns(conn)
        cur = conn.execute(
            "UPDATE forwards SET matches=?, goals=?, assists=?, ga=?, position=? "
            "WHERE name=? AND team=?",
            (
                PALMER_MATCHES,
                PALMER_GOALS,
                PALMER_ASSISTS,
                PALMER_GOALS + PALMER_ASSISTS,
                "ПФА",
                PALMER_NAME,
                PALMER_TEAM,
            ),
        )
        n = cur.rowcount or 0
        conn.commit()
        return n
    finally:
        conn.close()


def _cl_team_allowlist(cl_path: str) -> dict[str, object]:
    names: set[str] = set()
    conn = sqlite3.connect(cl_path)
    try:
        for tbl in ("forwards", "midfielders", "defenders", "goalkeepers"):
            try:
                for (t,) in conn.execute(
                    f"SELECT DISTINCT team FROM {tbl} "  # noqa: S608
                    "WHERE team IS NOT NULL AND trim(team) != ''"
                ):
                    s = str(t).strip()
                    if s:
                        names.add(s)
            except sqlite3.OperationalError:
                pass
    finally:
        conn.close()
    return dict.fromkeys(sorted(names), True)


def prepare_db_file_for_orm(path: str) -> None:
    if not os.path.isfile(path):
        return
    conn = sqlite3.connect(path)
    try:
        ensure_orm_columns(conn)
        conn.commit()
    finally:
        conn.close()


def repair_triplet(
    label: str,
    league_path: str,
    cl_path: str,
    common_path: str,
    meta: dict[tuple[str, str], tuple[str, str | None, int]],
) -> None:
    if not (os.path.isfile(league_path) and os.path.isfile(cl_path)):
        print(f"skip {label}: нет файлов league/cl")
        return

    print(f"--- {label} ---")
    n = sync_roster_sqlite(league_path, meta)
    n += sync_roster_sqlite(cl_path, meta)
    print(f"  roster sync: {n} обновлений (liga+cl)")

    m = apply_lauriente_league_stats(league_path)
    print(f"  Лориент лига (11/5/6): строк обновлено {m}")

    bump_simmons_sqlite(league_path, *SIMMONS_LEAGUE_ADD)
    bump_simmons_sqlite(cl_path, *SIMMONS_CL_ADD)
    print("  Симонс: прибавки лига + ЛЧ применены")

    p = set_palmer_sqlite(league_path)
    print(f"  Палмер (3 матча, 2 гола, ПФА): строк {p}")

    r_league = rename_sqlite(league_path, LAURIENT_OLD, LAURIENT_NEW, LAURIENT_TEAM)
    r_cl = rename_sqlite(cl_path, LAURIENT_OLD, LAURIENT_NEW, LAURIENT_TEAM)
    print(f"  переименование Лауриент→Лориент: лига {r_league}, лч {r_cl}")

    n2 = sync_roster_sqlite(league_path, meta)
    n2 += sync_roster_sqlite(cl_path, meta)
    print(f"  повторный roster sync: {n2}")

    prepare_db_file_for_orm(league_path)
    prepare_db_file_for_orm(cl_path)
    os.makedirs(os.path.dirname(os.path.abspath(common_path)) or ".", exist_ok=True)
    prepare_db_file_for_orm(common_path)

    import teams as teams_mod

    saved = teams_mod.teams_champ_league
    try:
        teams_mod.teams_champ_league = _cl_team_allowlist(cl_path)
        rebuild_common_database_for_disk_paths(league_path, cl_path, common_path)
    finally:
        teams_mod.teams_champ_league = saved
    print(f"  common пересобран → {common_path}")


def main() -> None:
    print("Бэкап db/ рекомендован. Старт через 2 с…")
    time.sleep(2)
    meta = build_roster_meta()
    s1 = season_paths.season_archive_directory(1)
    repair_triplet(
        "season_1",
        os.path.join(s1, season_paths.SEASON_LEAGUE_NAME),
        os.path.join(s1, season_paths.SEASON_CL_NAME),
        os.path.join(s1, season_paths.SEASON_COMMON_NAME),
        meta,
    )
    repair_triplet(
        "cumulative",
        season_paths.get_cumulative_league_db_path(),
        season_paths.get_cumulative_cl_db_path(),
        season_paths.get_cumulative_common_db_path(),
        meta,
    )
    print("Готово.")


if __name__ == "__main__":
    main()
