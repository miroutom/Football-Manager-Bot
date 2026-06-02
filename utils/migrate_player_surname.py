# -*- coding: utf-8 -*-
"""
Удаление устаревшей колонки ``surname`` из SQLite (остаётся только ``name``).

Перед удалением: пустой ``name`` заполняется из ``surname``; иначе ``name`` не трогаем.
"""
from __future__ import annotations

import logging
from pathlib import Path

logger = logging.getLogger(__name__)

_TABLES = ("forwards", "midfielders", "defenders", "goalkeepers")


def _table_info(conn, table: str) -> list[dict]:
    from sqlalchemy import text

    rows = conn.execute(text(f'PRAGMA table_info("{table}")')).fetchall()
    return [
        {
            "name": r[1],
            "type": r[2] or "VARCHAR",
            "notnull": bool(r[3]),
            "dflt": r[4],
            "pk": bool(r[5]),
        }
        for r in rows
    ]


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


def _drop_surname_column(conn, table: str) -> str | None:
    from sqlalchemy import text

    info = _table_info(conn, table)
    if not info:
        return None
    names = [x["name"] for x in info]
    if "surname" not in names:
        return None

    by_name = {x["name"]: x for x in info}
    new_order = [c for c in names if c != "surname"]
    tmp = f"{table}__drop_surname_tmp"
    cols_sql = ", ".join(_col_ddl(by_name[c]) for c in new_order)
    col_list = ", ".join(f'"{c}"' for c in new_order)

    if "name" in names:
        conn.execute(
            text(
                f'UPDATE "{table}" SET name = surname '
                f'WHERE (name IS NULL OR TRIM(name) = "") '
                f'AND surname IS NOT NULL AND TRIM(surname) != ""'
            )
        )

    conn.execute(text(f'DROP TABLE IF EXISTS "{tmp}"'))
    conn.execute(text(f'CREATE TABLE "{tmp}" ({cols_sql})'))
    conn.execute(
        text(f'INSERT INTO "{tmp}" ({col_list}) SELECT {col_list} FROM "{table}"')
    )
    conn.execute(text(f'DROP TABLE "{table}"'))
    conn.execute(text(f'ALTER TABLE "{tmp}" RENAME TO "{table}"'))
    return table


def drop_surname_columns_for_sqlite(db_path: str, *, label: str = "") -> list[str]:
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
                hit = _drop_surname_column(conn, table)
            except Exception:
                logger.exception("%s %s", tag, table)
                raise
            if hit:
                out.append(f"{tag}:{hit}")
    engine.dispose()
    return out


def migrate_surname_columns_for_sqlite(db_path: str, *, label: str = "") -> list[str]:
    """Совместимость: удалить колонку ``surname``, если есть."""
    return drop_surname_columns_for_sqlite(db_path, label=label)


def migrate_all_player_surname_columns() -> list[str]:
    from utils import season_paths

    db_dir = Path(season_paths.PROJECT_ROOT) / "db"
    log: list[str] = []
    if not db_dir.is_dir():
        return log
    for p in sorted(db_dir.rglob("*.db")):
        if "backup" in p.parts or ".bak" in p.name:
            continue
        log.extend(drop_surname_columns_for_sqlite(str(p), label=str(p.relative_to(db_dir))))
    return log


def migrate_season_archive_surnames(season_num: int) -> list[str]:
    from utils import season_paths

    log: list[str] = []
    d = season_paths.season_archive_directory(season_num)
    for fname in (
        season_paths.SEASON_LEAGUE_NAME,
        season_paths.SEASON_CL_NAME,
        season_paths.SEASON_COMMON_NAME,
    ):
        p = f"{d}/{fname}"
        log.extend(drop_surname_columns_for_sqlite(p, label=f"s{season_num}/{fname}"))
    return log


def ensure_season_player_columns(season_num: int) -> list[str]:
    from utils.migrate_player_left_team import migrate_left_team_for_sqlite
    from utils.migrate_player_person_id import migrate_person_id_for_sqlite
    from utils import season_paths

    log: list[str] = []
    d = season_paths.season_archive_directory(season_num)
    for fname in (
        season_paths.SEASON_LEAGUE_NAME,
        season_paths.SEASON_CL_NAME,
        season_paths.SEASON_COMMON_NAME,
    ):
        p = f"{d}/{fname}"
        log.extend(migrate_left_team_for_sqlite(p, label=f"s{season_num}/{fname}"))
        log.extend(migrate_person_id_for_sqlite(p, label=f"s{season_num}/{fname}"))
        log.extend(drop_surname_columns_for_sqlite(p, label=f"s{season_num}/{fname}"))
    return log


prepare_season_archive_schema = ensure_season_player_columns


if __name__ == "__main__":
    import sys

    hits = migrate_all_player_surname_columns()
    if hits:
        print("Удалена колонка surname:", ", ".join(hits))
    else:
        print("Колонки surname нет (или уже удалена).")
    raise SystemExit(0)
