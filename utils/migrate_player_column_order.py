# -*- coding: utf-8 -*-
"""
Порядок колонок в SQLite: ``name``, ``surname`` сразу после ``id``.

Колонка ``surname`` раньше добавлялась через ALTER в конец таблицы.

CLI::

    python -m utils.migrate_player_column_order
    python -m utils.migrate_player_column_order --db db/season_2/league.db
"""
from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

logger = logging.getLogger(__name__)

_TABLES = ("forwards", "midfielders", "defenders", "goalkeepers")

# После id, name, surname — как в data/*.py
_OUTFIELD_TAIL = (
    "overall",
    "team",
    "position",
    "matches",
    "goals",
    "assists",
    "ga",
    "trophies",
    "golden_balls",
    "golden_boots",
    "golden_boys",
    "nation",
    "status",
    "left_team",
    "yellow_cards",
    "red_cards",
)

_TABLE_TAIL: dict[str, tuple[str, ...]] = {
    "forwards": _OUTFIELD_TAIL,
    "midfielders": _OUTFIELD_TAIL,
    "defenders": (
        "overall",
        "team",
        "position",
        "matches",
        "goals",
        "assists",
        "ga",
        "trophies",
        "golden_balls",
        "golden_boots",
        "golden_boys",
        "nation",
        "status",
        "left_team",
        "yellow_cards",
        "red_cards",
    ),
    "goalkeepers": (
        "overall",
        "team",
        "position",
        "matches",
        "clean_sheets",
        "missed_goals",
        "trophies",
        "golden_balls",
        "golden_boots",
        "golden_gloves",
        "golden_boys",
        "nation",
        "status",
        "left_team",
        "yellow_cards",
        "red_cards",
    ),
}


def _table_info(conn, table: str) -> list[dict]:
    from sqlalchemy import text

    rows = conn.execute(text(f'PRAGMA table_info("{table}")')).fetchall()
    return [
        {
            "cid": r[0],
            "name": r[1],
            "type": r[2] or "VARCHAR",
            "notnull": bool(r[3]),
            "dflt": r[4],
            "pk": bool(r[5]),
        }
        for r in rows
    ]


def _desired_order(table: str, cols: list[str]) -> list[str]:
    head = ["id", "name", "surname"]
    tail_tpl = _TABLE_TAIL.get(table, ())
    order: list[str] = []
    for c in head + list(tail_tpl):
        if c in cols and c not in order:
            order.append(c)
    for c in cols:
        if c not in order:
            order.append(c)
    return order


def _col_ddl(info: dict) -> str:
    name = info["name"]
    typ = info["type"] or "VARCHAR"
    parts = [f'"{name}"', typ]
    if info["pk"]:
        parts.append("PRIMARY KEY")
    elif info["notnull"]:
        parts.append("NOT NULL")
    if info["dflt"] is not None:
        parts.append(f"DEFAULT {info['dflt']}")
    return " ".join(parts)


def reorder_table_columns(conn, table: str) -> str | None:
    """Пересоздать таблицу с ``name`` / ``surname`` рядом. None — уже ок."""
    from sqlalchemy import text

    info = _table_info(conn, table)
    if not info:
        return None
    names = [x["name"] for x in info]
    if "name" not in names:
        return None
    if "surname" not in names:
        return None
    if names.index("surname") == names.index("name") + 1:
        return None

    by_name = {x["name"]: x for x in info}
    order = _desired_order(table, names)
    tmp = f"{table}__reorder_tmp"
    cols_sql = ", ".join(_col_ddl(by_name[c]) for c in order)
    col_list = ", ".join(f'"{c}"' for c in order)

    conn.execute(text(f'DROP TABLE IF EXISTS "{tmp}"'))
    conn.execute(text(f'CREATE TABLE "{tmp}" ({cols_sql})'))
    conn.execute(
        text(f'INSERT INTO "{tmp}" ({col_list}) SELECT {col_list} FROM "{table}"')
    )
    conn.execute(text(f'DROP TABLE "{table}"'))
    conn.execute(text(f'ALTER TABLE "{tmp}" RENAME TO "{table}"'))
    return table


def reorder_player_columns_for_sqlite(db_path: str, *, label: str = "") -> list[str]:
    from sqlalchemy import create_engine

    path = Path(db_path)
    if not path.is_file():
        return []
    tag = label or path.name
    out: list[str] = []
    engine = create_engine(f"sqlite:///{path}")
    with engine.begin() as conn:
        for table in _TABLES:
            try:
                hit = reorder_table_columns(conn, table)
            except Exception:
                logger.exception("%s %s", tag, table)
                raise
            if hit:
                out.append(f"{tag}:{hit}")
    engine.dispose()
    return out


def reorder_all_project_player_dbs() -> list[str]:
    from utils import season_paths

    db_dir = Path(season_paths.PROJECT_ROOT) / "db"
    paths: list[Path] = []
    if db_dir.is_dir():
        for p in sorted(db_dir.rglob("*.db")):
            if p.name in (
                "league.db",
                "champions_league.db",
                "common.db",
                "league_synced.db",
                "champions_league_synced.db",
                "common_synced.db",
            ):
                paths.append(p)
    log: list[str] = []
    for p in paths:
        log.extend(reorder_player_columns_for_sqlite(str(p), label=str(p.relative_to(db_dir))))
    return log


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument(
        "--db",
        action="append",
        default=[],
        help="Один файл SQLite (можно несколько раз)",
    )
    args = ap.parse_args(argv)
    logging.basicConfig(level=logging.INFO)
    if args.db:
        log: list[str] = []
        for p in args.db:
            log.extend(reorder_player_columns_for_sqlite(p))
    else:
        log = reorder_all_project_player_dbs()
    if log:
        print("Переставлены колонки:", ", ".join(log))
    else:
        print("Уже в порядке id, name, surname, …")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
