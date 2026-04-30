#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Синхронизация заявок **всех** национальных лиг из Python-модулей в рабочие БД (лига + ЛЧ + common).

Источник: ``utils.merged_national_squads`` (АПЛ, Бундес, Серия А, Ла Лига, РПЛ).

По умолчанию **без prune**: не удаляются игроки, которых нет в заявке (меньше риска потерять
статистику из‑за опечатки в имени). Обновляются только ``overall``, ``position``, ``nation``,
``status``; при смене позиции строка переносится между таблицами с сохранением матчевой статы.

  python scripts/sync_all_national_rosters.py
  python scripts/sync_all_national_rosters.py --prune
  python scripts/sync_all_national_rosters.py --no-common-rebuild

Архивы и накопительные БД (пулы ЛЧ берутся из соответствующего ``champions_league*.db``):

  python scripts/sync_all_national_rosters.py --stores season_1,season_2,cumulative
  python scripts/sync_all_national_rosters.py --stores season_1,season_2,cumulative,active
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))


def main() -> None:
    p = argparse.ArgumentParser(description="Синк заявок всех нац. лиг в рабочие SQLite.")
    p.add_argument(
        "--prune",
        action="store_true",
        help="Удалить из команд игроков, которых нет в заявке (осторожно с именами).",
    )
    p.add_argument(
        "--no-common-rebuild",
        action="store_true",
        help="Не пересобирать common после синка.",
    )
    p.add_argument(
        "--stores",
        default=None,
        metavar="LIST",
        help=(
            "Через запятую: active, season_1, season_2, cumulative. "
            "По умолчанию только active (текущие пути из season_state). "
            "Пример: season_1,season_2,cumulative"
        ),
    )
    args = p.parse_args()

    from utils import season_paths
    from utils.merged_national_squads import merged_national_squads
    from utils.squad_roster_sync import (
        run_all_national_leagues_roster_sync,
        run_squads_sync_on_disk_paths,
    )

    rebuild = not args.no_common_rebuild
    raw_stores = args.stores if args.stores is not None else "active"
    stores = [x.strip() for x in raw_stores.split(",") if x.strip()]
    if not stores:
        stores = ["active"]

    out: dict[str, object] = {}
    squads = merged_national_squads()

    def triplet_for_season(n: int) -> tuple[str, str, str] | None:
        base = season_paths.season_archive_directory(n)
        lp = os.path.join(base, season_paths.SEASON_LEAGUE_NAME)
        cp = os.path.join(base, season_paths.SEASON_CL_NAME)
        op = os.path.join(base, season_paths.SEASON_COMMON_NAME)
        if not (os.path.isfile(lp) and os.path.isfile(cp)):
            return None
        return lp, cp, op

    for key in ("season_1", "season_2"):
        if key not in stores:
            continue
        n = int(key.split("_")[1])
        t = triplet_for_season(n)
        if t is None:
            out[key] = f"skip: нет league/champions_league в db/season_{n}"
            continue
        lp, cp, op = t
        out[key] = run_squads_sync_on_disk_paths(
            lp,
            cp,
            op,
            squads,
            prune=args.prune,
            rebuild_common=rebuild,
        )

    if "cumulative" in stores:
        lp = season_paths.get_cumulative_league_db_path()
        cp = season_paths.get_cumulative_cl_db_path()
        op = season_paths.get_cumulative_common_db_path()
        if not (os.path.isfile(lp) and os.path.isfile(cp)):
            out["cumulative"] = "skip: нет league_synced / champions_league_synced"
        else:
            out["cumulative"] = run_squads_sync_on_disk_paths(
                lp,
                cp,
                op,
                squads,
                prune=args.prune,
                rebuild_common=rebuild,
            )

    if "active" in stores:
        out["active"] = run_all_national_leagues_roster_sync(
            prune=args.prune,
            rebuild_common=rebuild,
        )

    print(json.dumps(out, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
