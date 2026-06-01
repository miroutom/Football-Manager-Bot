# -*- coding: utf-8 -*-
"""
Раньше добавлялась колонка ``surname`` — отключено, только поле ``name``.

Функции оставлены как no-op для совместимости со старыми скриптами.
"""
from __future__ import annotations


def migrate_all_player_surname_columns() -> list[str]:
    return []


def migrate_surname_columns_for_sqlite(db_path: str, *, label: str = "") -> list[str]:
    return []


def migrate_season_archive_surnames(season_num: int) -> list[str]:
    return []


def ensure_season_player_columns(season_num: int) -> list[str]:
    from utils.migrate_player_left_team import migrate_left_team_for_sqlite
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
    return log


prepare_season_archive_schema = ensure_season_player_columns


if __name__ == "__main__":
    print("Миграция surname отключена (только name).")
