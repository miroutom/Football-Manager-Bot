#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
После правки ``config/leagues_config.py`` и удаления pickle сезона 2:
- удалить ``data/cl_participants_dynamic.txt`` (если есть);
- пересчитать топ-30 ЛЧ по силе из **текущей** нац. БД активного сезона;
- записать ``mixed_schedule.json`` (v3).

Запускать **из корня**, venv с зависимостями. Активный сезон в ``db/season_state.json`` должен быть 2.
"""
from __future__ import annotations

import glob
import os
import sys

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

os.chdir(_ROOT)


def main() -> None:
    from pathlib import Path

    from utils import season_paths

    if int(season_paths.get_state().get("active_season") or 1) != 2:
        print("Внимание: active_season не 2 — проверь season_state.json.")

    pkl_dir = season_paths.get_pickle_directory()
    for p in glob.glob(os.path.join(pkl_dir, "*.pkl")):
        os.remove(p)
        print("removed pickle:", p)

    dyn = Path(_ROOT) / "data" / "cl_participants_dynamic.txt"
    if dyn.is_file():
        dyn.unlink()
        print("removed", dyn)

    from config.leagues_config import CL_PARTICIPANTS
    from utils.cl_standing_participants import write_cl_participants_file
    from utils.schedule_by_months import build_and_write_mixed_v3

    names = [t.strip().title() for t in CL_PARTICIPANTS["roman"]] + [
        t.strip().title() for t in CL_PARTICIPANTS["lika"]
    ]
    if len(names) != 30:
        raise SystemExit(f"CL_PARTICIPANTS: ожидалось 30 команд, сейчас {len(names)}")
    write_cl_participants_file(names)
    print("cl_participants_dynamic:", len(names), "teams (из leagues_config)")

    out = build_and_write_mixed_v3(seed=20260429, path=os.path.join(_ROOT, "mixed_schedule.json"))
    print("mixed_schedule written", out)


if __name__ == "__main__":
    main()
