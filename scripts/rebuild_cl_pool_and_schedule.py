#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Пересборка участников ЛЧ из ``data/draft_config.json`` (топ-6 в каждой из 5 лиг среди 8 клубов игры)
и генерация ``mixed_schedule.json`` (v3).

Удаляет ``champ_league_teams.pkl``, чтобы при следующем импорте ``teams`` подтянулся новый пул.

Запуск из корня проекта (с venv): ``python scripts/rebuild_cl_pool_and_schedule.py``

``match_results.json`` не трогает. Строки уже сыгранных матчей (со счётом, не simulation)
**удаляются** из ``mixed_schedule.json`` при записи (см. ``strip_played_matches_from_v3_document``).
Для ЛЧ учитывается и обратный порядок дом/гостей относительно журнала.
"""
from __future__ import annotations

import os
import random
import sys

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)
os.chdir(_ROOT)


def main() -> None:
    from pathlib import Path

    from utils.cl_standing_participants import (
        build_cl_top30_from_draft_json,
        write_cl_participants_file,
    )
    from utils.schedule_by_months import build_and_write_mixed_v3
    from utils.season_paths import get_pickle_directory

    names = build_cl_top30_from_draft_json()
    path_txt = write_cl_participants_file(names)
    print(path_txt)
    for i, n in enumerate(names, 1):
        print(f"  {i:2} {n}")

    pkl = Path(get_pickle_directory()) / "champ_league_teams.pkl"
    if pkl.is_file():
        pkl.unlink()
        print("removed", pkl)

    mixed_path = os.path.join(_ROOT, "mixed_schedule.json")
    for _attempt in range(500):
        seed = random.randint(1, 80_000_000)
        try:
            out = build_and_write_mixed_v3(seed=seed, path=mixed_path)
            print("mixed_schedule OK seed=", seed)
            print(out)
            return
        except RuntimeError:
            continue
    raise SystemExit(
        "Не удалось сгенерировать 8 туров ЛЧ за 500 попыток — запустите скрипт ещё раз."
    )


if __name__ == "__main__":
    main()
