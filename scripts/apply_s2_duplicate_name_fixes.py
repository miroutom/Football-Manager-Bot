#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Пакет правок по дублям имён (season 2): left_team, слияние, переименование, удаление FA.

  python3 scripts/apply_s2_duplicate_name_fixes.py --dry-run
  python3 scripts/apply_s2_duplicate_name_fixes.py --apply
"""
from __future__ import annotations

import argparse
import os
import sqlite3
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from player_stats import _norm_cmp
from utils import season_paths
from utils.migrate_player_left_team import migrate_left_team_for_sqlite
from utils.transfer_input import _team_name_as_in_db

_TABLES = ("forwards", "midfielders", "defenders", "goalkeepers")
_STAT_COLS = (
    "matches",
    "goals",
    "assists",
    "ga",
    "clean_sheets",
    "missed_goals",
    "trophies",
    "golden_balls",
    "golden_boots",
    "golden_gloves",
    "golden_boys",
    "yellow_cards",
    "red_cards",
)

_ALL_DBS = [
    "season_1/league.db",
    "season_1/champions_league.db",
    "season_1/common.db",
    "season_2/league.db",
    "season_2/champions_league.db",
    "season_2/common.db",
    "league_synced.db",
    "champions_league_synced.db",
    "common_synced.db",
]


def _db_paths() -> list[tuple[str, str]]:
    out: list[tuple[str, str]] = []
    for rel in _ALL_DBS:
        p = os.path.join(ROOT, "db", rel)
        if os.path.isfile(p):
            out.append((rel, p))
    return out


def _resolve_team(conn: sqlite3.Connection, team: str) -> str:
    want = _norm_cmp(_team_name_as_in_db(team.strip()))
    for table in _TABLES:
        try:
            for (tm,) in conn.execute(
                f"SELECT DISTINCT team FROM {table} WHERE team IS NOT NULL"
            ):
                if tm and _norm_cmp(str(tm)) == want:
                    return str(tm).strip()
        except sqlite3.OperationalError:
            pass
    return team.strip()


def _fetch(
    conn: sqlite3.Connection,
    *,
    name: str | None = None,
    team: str | None = None,
    position: str | None = None,
    table: str | None = None,
    row_id: int | None = None,
) -> list[dict]:
    rows: list[dict] = []
    tables = [table] if table else list(_TABLES)
    rteam = _resolve_team(conn, team) if team else None
    for tbl in tables:
        cols = {r[1] for r in conn.execute(f"PRAGMA table_info({tbl})")}
        if "name" not in cols:
            continue
        sel = ["id", "name", "team", "position"]
        if "left_team" in cols:
            sel.append("left_team")
        for rec in conn.execute(f"SELECT {', '.join(sel)} FROM {tbl}"):
            rid, nm, tm, pos = rec[0], rec[1], rec[2], rec[3]
            left = bool(rec[4]) if len(rec) > 4 else False
            if row_id is not None and int(rid) != int(row_id):
                continue
            if name and _norm_cmp(nm or "") != _norm_cmp(name):
                continue
            if rteam and _norm_cmp(tm or "") != _norm_cmp(rteam):
                continue
            if position and _norm_cmp(pos or "") != _norm_cmp(position):
                continue
            rows.append(
                {
                    "table": tbl,
                    "id": int(rid),
                    "name": (nm or "").strip(),
                    "team": (tm or "").strip(),
                    "position": (pos or "").strip().upper(),
                    "left_team": left,
                }
            )
    return rows


def _log(msg: str, *, dry_run: bool) -> None:
    print(f"{'[dry] ' if dry_run else ''}{msg}")


def _set_left(
    conn: sqlite3.Connection,
    name: str,
    team: str,
    position: str,
    *,
    dry_run: bool,
    label: str,
) -> int:
    n = 0
    for r in _fetch(conn, name=name, team=team, position=position):
        if r["left_team"]:
            continue
        _log(
            f"{label} left_team {r['table']} id={r['id']} {r['name']} "
            f"{r['position']} @{r['team']}",
            dry_run=dry_run,
        )
        if not dry_run:
            cols = {x[1] for x in conn.execute(f"PRAGMA table_info({r['table']})")}
            sql = f"UPDATE {r['table']} SET left_team = 1"
            if "status" in cols:
                sql += ", status = NULL"
            sql += " WHERE id = ?"
            conn.execute(sql, (r["id"],))
        n += 1
    return n


def _rename(
    conn: sqlite3.Connection,
    name: str,
    new_name: str,
    *,
    team: str | None = None,
    position: str | None = None,
    table: str | None = None,
    dry_run: bool,
    label: str,
) -> int:
    n = 0
    for r in _fetch(conn, name=name, team=team, position=position, table=table):
        if r["name"] == new_name:
            continue
        _log(
            f"{label} rename {r['table']} id={r['id']} {r['name']!r} → {new_name!r} "
            f"({r['position']} {r['team']})",
            dry_run=dry_run,
        )
        if not dry_run:
            conn.execute(
                f"UPDATE {r['table']} SET name = ? WHERE id = ?",
                (new_name, r["id"]),
            )
        n += 1
    return n


def _set_position_row(
    conn: sqlite3.Connection,
    name: str,
    team: str,
    old_pos: str,
    new_pos: str,
    *,
    dry_run: bool,
    label: str,
) -> int:
    n = 0
    for r in _fetch(conn, name=name, team=team, position=old_pos):
        _log(
            f"{label} position {r['table']} id={r['id']} {r['name']} "
            f"{old_pos} → {new_pos} @{r['team']}",
            dry_run=dry_run,
        )
        if not dry_run:
            conn.execute(
                f"UPDATE {r['table']} SET position = ? WHERE id = ?",
                (new_pos.strip().upper(), r["id"]),
            )
        n += 1
    return n


def _delete_row(
    conn: sqlite3.Connection,
    table: str,
    row_id: int,
    *,
    dry_run: bool,
    label: str,
    note: str = "",
) -> int:
    _log(f"{label} DELETE {table} id={row_id} {note}", dry_run=dry_run)
    if not dry_run:
        conn.execute(f"DELETE FROM {table} WHERE id = ?", (row_id,))
    return 1


def _delete_free_agents(conn: sqlite3.Connection, *, dry_run: bool, label: str) -> int:
    n = 0
    for tbl in _TABLES:
        try:
            for rid, nm, tm in conn.execute(
                f"SELECT id, name, team FROM {tbl} WHERE "
                f"LOWER(TRIM(team)) IN ('free agent', 'free_agent', 'fa')"
            ):
                _log(f"{label} DELETE FA {tbl} id={rid} {nm} @{tm}", dry_run=dry_run)
                if not dry_run:
                    conn.execute(f"DELETE FROM {tbl} WHERE id = ?", (rid,))
                n += 1
        except sqlite3.OperationalError:
            pass
    return n


def _merge_club(
    conn: sqlite3.Connection,
    name: str,
    team: str,
    keep_position: str,
    *,
    dry_run: bool,
    label: str,
) -> int:
    keep_pos = keep_position.strip().upper()
    group = _fetch(conn, name=name, team=team)
    if len(group) < 2:
        return 0
    keeper = None
    donors: list[dict] = []
    for r in group:
        if r["position"] == keep_pos:
            if keeper is None or r["id"] > keeper["id"]:
                keeper = r
        else:
            donors.append(r)
    if keeper is None:
        _log(f"{label} merge {name}@{team}: нет строки {keep_pos}", dry_run=dry_run)
        return 0
    if not donors:
        return 0
    _log(
        f"{label} merge {name}@{team} → keep {keeper['table']} id={keeper['id']} "
        f"{keep_pos}, drop {len(donors)}",
        dry_run=dry_run,
    )
    if dry_run:
        for d in donors:
            _log(f"  drop {d['table']} id={d['id']} {d['position']}", dry_run=True)
        return len(donors)
    kcols = {x[1] for x in conn.execute(f"PRAGMA table_info({keeper['table']})")}
    for d in donors:
        dcols = {x[1] for x in conn.execute(f"PRAGMA table_info({d['table']})")}
        for fld in _STAT_COLS:
            if fld not in kcols or fld not in dcols:
                continue
            kv = conn.execute(
                f"SELECT {fld} FROM {keeper['table']} WHERE id = ?",
                (keeper["id"],),
            ).fetchone()[0]
            dv = conn.execute(
                f"SELECT {fld} FROM {d['table']} WHERE id = ?",
                (d["id"],),
            ).fetchone()[0]
            conn.execute(
                f"UPDATE {keeper['table']} SET {fld} = ? WHERE id = ?",
                (int(kv or 0) + int(dv or 0), keeper["id"]),
            )
        conn.execute(f"DELETE FROM {d['table']} WHERE id = ?", (d["id"],))
    return len(donors)


def _apply_all(*, dry_run: bool) -> None:
    total = 0
    for rel, path in _db_paths():
        migrate_left_team_for_sqlite(path, label=rel)
        conn = sqlite3.connect(path)
        try:
            L = rel

            # —— left_team (бывший клуб) ——
            for name, team, pos in [
                ("Адли", "Байер", "ФРВ"),
                ("Ангисса", "Наполи", "ЦОП"),
                ("Батши", "Краснодар", "ПФА"),
                ("Джака", "Байер", "ЦП"),
                ("Джикия", "Спартак", "ЦЗ"),
                ("Джонсон", "Тоттенхэм", "ПФА"),
                ("Модрич", "Реал", "ЦОП"),
                ("Науфф", "Франкфурт", "ПФА"),
                ("Нуньес", "Ливерпуль", "ФРВ"),
                ("Промес", "Спартак", "ФРВ"),
                ("Санчес", "Интер", "ФРВ"),
                ("Сков", "Хоффенхайм", "ЛЗ"),
                ("Тонали", "Ньюкасл", "ЦАП"),
                ("Фати", "Челси", "ФРВ"),
                ("Фернандес", "Зенит", "ПЗ"),
                ("Хоселу", "Реал", "ФРВ"),
                ("Эндо", "Ливерпуль", "ЦП"),
                ("Эриксен", "Мю", "ЦП"),
            ]:
                total += _set_left(conn, name, team, pos, dry_run=dry_run, label=L)

            # Залевски: бывший Рома (после слияния)
            total += _merge_club(conn, "Залевски", "Рома", "ПФА", dry_run=dry_run, label=L)
            total += _set_left(conn, "Залевски", "Рома", "ПФА", dry_run=dry_run, label=L)

            # —— слияния ——
            for name, team, keep in [
                ("Буанга", "Краснодар", "ФРВ"),
                ("Газинский", "Урал", "ЦП"),
                ("Зобнин", "Спартак", "ЦП"),
                ("Каземиро", "Мю", "ЦП"),
                ("Кох", "Франкфурт", "ЦП"),
                ("Мишкич", "Урал", "ЦП"),
                ("Ольмо", "Лейпциг", "ЦАП"),
                ("Уиллок", "Ньюкасл", "ЦП"),
            ]:
                total += _merge_club(conn, name, team, keep, dry_run=dry_run, label=L)

            total += _merge_club(conn, "Коне", "Боруссия М", "ЦП", dry_run=dry_run, label=L)
            total += _set_position_row(
                conn, "Коне", "Ньюкасл", "ЦАП", "ЦП", dry_run=dry_run, label=L
            )

            # —— переименования ——
            total += _rename(
                conn,
                "Камара",
                "Бубакар Камара",
                team="Астон Вилла",
                dry_run=dry_run,
                label=L,
            )
            total += _rename(
                conn,
                "Камара",
                "Бубакар Камара",
                team="Франкфурт",
                dry_run=dry_run,
                label=L,
            )
            total += _rename(
                conn,
                "Камара",
                "Мохамед Камара",
                team="Севилья",
                dry_run=dry_run,
                label=L,
            )
            total += _rename(
                conn,
                "Жезус",
                "Габриэль Жезус",
                team="Арсенал",
                dry_run=dry_run,
                label=L,
            )
            total += _rename(
                conn,
                "Лопес",
                "Давид Лопес",
                team="Жирона",
                position="ЦЗ",
                dry_run=dry_run,
                label=L,
            )
            total += _rename(
                conn,
                "Лопес",
                "Макс Лопес",
                team="Фиорентина",
                position="ЦП",
                dry_run=dry_run,
                label=L,
            )
            total += _rename(
                conn,
                "Мартин",
                "Иван Мартин",
                team="Жирона",
                position="ЦП",
                dry_run=dry_run,
                label=L,
            )
            total += _rename(
                conn,
                "Мартин",
                "Генри Мартин",
                team="Хоффенхайм",
                position="ФРВ",
                dry_run=dry_run,
                label=L,
            )
            total += _rename(
                conn,
                "Мартинез",
                "Лисандро Мартинез",
                team="Мю",
                position="ЦЗ",
                dry_run=dry_run,
                label=L,
            )
            total += _rename(
                conn,
                "Мартинез",
                "Иниго Мартинез",
                team="Лейпциг",
                position="ЦЗ",
                dry_run=dry_run,
                label=L,
            )
            total += _rename(
                conn,
                "Муньоз",
                "Дани Муньоз",
                team="Хоффенхайм",
                position="ПЗ",
                dry_run=dry_run,
                label=L,
            )
            total += _rename(
                conn,
                "Санчес",
                "Алексис Санчес",
                team="Барселона",
                position="ФРВ",
                dry_run=dry_run,
                label=L,
            )
            total += _rename(
                conn,
                "Санчес",
                "Эрик Санчес",
                team="Мю",
                position="ЦП",
                dry_run=dry_run,
                label=L,
            )
            total += _rename(
                conn,
                "Сильва",
                "Антониу Сильва",
                team="Аталанта",
                position="ЦЗ",
                table="defenders",
                dry_run=dry_run,
                label=L,
            )
            total += _rename(
                conn,
                "Эррера",
                "Андер Эррера",
                team="Атлетик",
                position="ЦП",
                dry_run=dry_run,
                label=L,
            )

            # —— удаления ——
            for r in _fetch(conn, name="Коке", team="Free Agent"):
                total += _delete_row(
                    conn, r["table"], r["id"], dry_run=dry_run, label=L, note="Коке FA"
                )
            for r in _fetch(
                conn, name="Сильва", team="Аталанта", position="ФРВ", table="forwards"
            ):
                total += _delete_row(
                    conn,
                    r["table"],
                    r["id"],
                    dry_run=dry_run,
                    label=L,
                    note="Сильва нападающий Аталанта",
                )
            for r in _fetch(
                conn, name="Тонали", team="Сити", position="ФРВ", table="forwards"
            ):
                total += _delete_row(
                    conn,
                    r["table"],
                    r["id"],
                    dry_run=dry_run,
                    label=L,
                    note="Тонали ошибочно в Сити",
                )

            total += _delete_free_agents(conn, dry_run=dry_run, label=L)

            if not dry_run:
                conn.commit()
        finally:
            conn.close()

    print(f"\nОпераций (строк событий): ~{total}")
    if dry_run:
        print("Повторите с --apply")


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--apply", action="store_true")
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()
    dry = not args.apply
    if args.dry_run:
        dry = True
    _apply_all(dry_run=dry)
    if args.apply:
        fa_db = os.path.join(ROOT, "db", "free_agents.db")
        if os.path.isfile(fa_db):
            os.remove(fa_db)
            print(f"Удалён {fa_db}")
        try:
            from utils.common_db import rebuild_common_database

            rebuild_common_database()
            print("common пересобран.")
        except Exception as e:
            print(f"common не пересобран: {e}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
