#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Одноразово начисляет трофеи за **1 сезон** по известным чемпионам (нац. лиги + ЛЧ).

Правило (как при «Завершить сезон»):
+1 к ``trophies`` в **национальной** БД для каждого игрока клуба-чемпиона лиги;
+1 к ``trophies`` в **БД ЛЧ** для каждого игрока клуба-победителя ЛЧ;
``common`` пересобирается как сумма лиги + ЛЧ.

Обрабатываются:
- рабочие БД (``db/season_N/`` из ``season_state``);
- накопительные ``db/league_synced.db``, ``db/champions_league_synced.db``, ``db/common_synced.db``;
- архив ``db/season_1/`` (если есть).

Повторный запуск **удвоит** счётчики — по умолчанию нужен флаг ``--i-know``.

Если счётчики уже «раздулись», сначала:
``python3 scripts/fix_season1_trophies_and_awards.py --apply``.

  python3 scripts/apply_season1_champion_trophies.py --i-know
"""
from __future__ import annotations

import argparse
import os
import sys

# корень проекта в PYTHONPATH
_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from utils import season_paths
from utils.common_db import rebuild_common_database, rebuild_common_database_for_disk_paths
from utils.season_end import _inc_trophies_all_players_of_team
from utils.utils import reinit_db_connections, session_cl, session_league


# Имена клубов как в SQLite (см. distinct team в league.db)
SEASON1_NATIONAL_WINNERS: tuple[tuple[str, str], ...] = (
    ("rpl", "Зенит"),
    ("eng", "Сити"),
    ("esp", "Атлетико"),
    ("ita", "Интер"),
    ("ger", "Бавария"),
)
SEASON1_CL_WINNER = "Интер"


def _bump_pair(sl, sc, league_teams: tuple[str, ...], cl_team: str) -> dict[str, int]:
    counts: dict[str, int] = {}
    for team in league_teams:
        n = _inc_trophies_all_players_of_team(sl, team, 1)
        counts[f"league:{team}"] = n
    n_cl = _inc_trophies_all_players_of_team(sc, cl_team, 1)
    counts["cl"] = n_cl
    sl.commit()
    sc.commit()
    return counts


def _session_pair(league_path: str, cl_path: str):
    el = create_engine(f"sqlite:///{league_path}")
    ec = create_engine(f"sqlite:///{cl_path}")
    Sl = sessionmaker(bind=el)
    Scl = sessionmaker(bind=ec)
    return Sl(), Scl(), el, ec


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument(
        "--i-know",
        action="store_true",
        help="Подтверждение: скрипт не идемпотентен",
    )
    args = ap.parse_args()
    if not args.i_know:
        print("Запуск только с флагом --i-know (иначе trophies задвоятся).")
        sys.exit(2)

    reinit_db_connections()
    teams = tuple(t for _code, t in SEASON1_NATIONAL_WINNERS)

    # 1) Рабочие БД
    print("Рабочие:", season_paths.get_league_db_path())
    log_w = _bump_pair(
        session_league, session_cl, teams, SEASON1_CL_WINNER
    )
    print("  начислено (строки):", log_w)
    rebuild_common_database()
    print("  common пересобран:", season_paths.get_common_db_path())

    # 2) Накопительные synced
    cum_l = season_paths.get_cumulative_league_db_path()
    cum_c = season_paths.get_cumulative_cl_db_path()
    cum_o = season_paths.get_cumulative_common_db_path()
    if os.path.isfile(cum_l) and os.path.isfile(cum_c):
        sl, scl, el, ec = _session_pair(cum_l, cum_c)
        try:
            log_c = _bump_pair(sl, scl, teams, SEASON1_CL_WINNER)
            print("Synced league/cl:", log_c)
        finally:
            sl.close()
            scl.close()
            el.dispose()
            ec.dispose()
        rebuild_common_database_for_disk_paths(
            cum_l, cum_c, cum_o, include_all_cl_teams=True
        )
        print("  common_synced пересобран:", cum_o)
    else:
        print("Пропуск synced: нет файлов", cum_l, cum_c)

    # 3) Архив сезона 1
    s1 = os.path.join(season_paths.PROJECT_ROOT, "db", "season_1")
    p_l = os.path.join(s1, season_paths.SEASON_LEAGUE_NAME)
    p_c = os.path.join(s1, season_paths.SEASON_CL_NAME)
    p_o = os.path.join(s1, season_paths.SEASON_COMMON_NAME)
    if os.path.isfile(p_l) and os.path.isfile(p_c):
        sl, scl, el, ec = _session_pair(p_l, p_c)
        try:
            log_s1 = _bump_pair(sl, scl, teams, SEASON1_CL_WINNER)
            print("season_1:", log_s1)
        finally:
            sl.close()
            scl.close()
            el.dispose()
            ec.dispose()
        rebuild_common_database_for_disk_paths(p_l, p_c, p_o)
        print("  season_1/common.db пересобран")
    else:
        print("Пропуск season_1: нет", p_l, p_c)

    print("Готово.")


if __name__ == "__main__":
    main()
