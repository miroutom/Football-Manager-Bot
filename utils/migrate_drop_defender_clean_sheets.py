# -*- coding: utf-8 -*-
"""
Удалить колонку ``clean_sheets`` из таблицы ``defenders`` (только вратари).

  python -m utils.migrate_drop_defender_clean_sheets
  python -m utils.migrate_drop_defender_clean_sheets --db db/season_2/league.db
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

_PLAYER_DBS = frozenset(
    {
        "league.db",
        "champions_league.db",
        "common.db",
        "league_synced.db",
        "champions_league_synced.db",
        "common_synced.db",
    }
)


def drop_defender_clean_sheets(conn, table: str = "defenders") -> bool:
    from sqlalchemy import text

    info = conn.execute(text(f'PRAGMA table_info("{table}")')).fetchall()
    if not info:
        return False
    names = [r[1] for r in info]
    if "clean_sheets" not in names:
        return False
    keep = [c for c in names if c != "clean_sheets"]
    tmp = f"{table}__no_cs_tmp"
    cols_ddl = []
    for r in info:
        if r[1] == "clean_sheets":
            continue
        typ = r[2] or "VARCHAR"
        part = f'"{r[1]}" {typ}'
        if r[5]:
            part += " PRIMARY KEY"
        elif r[3]:
            part += " NOT NULL"
        if r[4] is not None:
            part += f" DEFAULT {r[4]}"
        cols_ddl.append(part)
    col_list = ", ".join(f'"{c}"' for c in keep)
    conn.execute(text(f'DROP TABLE IF EXISTS "{tmp}"'))
    conn.execute(text(f'CREATE TABLE "{tmp}" ({", ".join(cols_ddl)})'))
    conn.execute(
        text(f'INSERT INTO "{tmp}" ({col_list}) SELECT {col_list} FROM "{table}"')
    )
    conn.execute(text(f'DROP TABLE "{table}"'))
    conn.execute(text(f'ALTER TABLE "{tmp}" RENAME TO "{table}"'))
    return True


def migrate_sqlite_file(db_path: str, *, label: str = "") -> bool:
    from sqlalchemy import create_engine

    path = Path(db_path)
    if not path.is_file():
        return False
    tag = label or path.name
    engine = create_engine(f"sqlite:///{path}")
    changed = False
    with engine.begin() as conn:
        try:
            if drop_defender_clean_sheets(conn):
                changed = True
                logger.info("%s: dropped defenders.clean_sheets", tag)
        except Exception:
            logger.exception("%s defenders", tag)
            raise
    engine.dispose()
    return changed


def migrate_all_project_player_dbs() -> list[str]:
    from utils import season_paths

    db_dir = Path(season_paths.PROJECT_ROOT) / "db"
    log: list[str] = []
    if not db_dir.is_dir():
        return log
    for p in sorted(db_dir.rglob("*.db")):
        if p.name not in _PLAYER_DBS:
            continue
        if migrate_sqlite_file(str(p), label=str(p.relative_to(db_dir))):
            log.append(str(p.relative_to(db_dir)))
    return log


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--db", action="append", default=[])
    args = ap.parse_args(argv)
    logging.basicConfig(level=logging.INFO)
    if args.db:
        log = [p for p in args.db if migrate_sqlite_file(p)]
    else:
        log = migrate_all_project_player_dbs()
    if log:
        print("Удалена clean_sheets у defenders:", ", ".join(log))
    else:
        print("Нечего менять (колонки уже нет).")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
