#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Локально для текущего ``active_season`` из ``db/season_state.json``:

1. **Перегенерирует** ``mixed_schedule.json`` по актуальным правилам (v3, 10 месяцев, ЛЧ только 1–5).
   Старый файл удаляется.

2. **Достраивает БД сезона** в ``db/season_{N}/``, если файлов нет (или с ``--reclone-season-dbs`` — пересоздать):
   копия из ``db/season_{N-1}/`` + **обнуление только матчевой** статистики (голы, ассисты, Г+А, матчи, карточки…).
   ``*_synced.db`` — только накопительная стата, **не** подставляем их как шаблон папки сезона, если есть архив N−1.

3. **Pickle** — если папки нет или пуста: копия из предыдущего сезона или из ``pickle/`` в корне проекта.

4. Вызывает ``repair_per_season_database_files`` и ``reinit_db_connections``.

Запуск из корня репозитория::

  python3 scripts/local_bootstrap_active_season.py

Опционально зафиксировать RNG расписания::

  python3 scripts/local_bootstrap_active_season.py --seed 42

Только расписание (БД не трогать)::

  python3 scripts/local_bootstrap_active_season.py --schedule-only

Пересоздать БД активного сезона (матчи обнулятся, трофеи из снимка N−1 сохранятся)::

  python3 scripts/local_bootstrap_active_season.py --reclone-season-dbs
"""
from __future__ import annotations

import argparse
import os
import shutil
import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))
os.chdir(_ROOT)


def _regenerate_schedule(seed: int | None) -> Path:
    from utils.schedule_by_months import MIXED_FILE, build_and_write_mixed_v3

    p = Path(MIXED_FILE)
    if p.is_file():
        p.unlink()
        print(f"Удалён: {p}")
    out = build_and_write_mixed_v3(path=p, seed=seed)
    print(f"Записано новое расписание v3: {out}")
    return p


def _ensure_season_dbs_and_pickle(*, force_reclone: bool = False) -> None:
    from utils import season_paths
    from utils.season_end import _clone_db_zero_stats
    from utils.utils import reinit_db_connections

    st = season_paths.get_state()
    if st.get("data_mode") != "per_season":
        print("Режим не per_season — пропускаю создание db/season_N (только расписание).")
        return

    active = int(st.get("active_season") or 1)
    db_root = Path(season_paths.PROJECT_ROOT) / "db"
    cur_dir = db_root / f"season_{active}"
    cur_dir.mkdir(parents=True, exist_ok=True)

    leg_l = db_root / season_paths.LEGACY_LEAGUE
    leg_c = db_root / season_paths.LEGACY_CL
    leg_o = db_root / season_paths.LEGACY_COMMON

    prev = active - 1
    prev_dir = db_root / f"season_{prev}" if prev >= 1 else None

    def _src_triple() -> tuple[Path | None, Path | None, Path | None]:
        if prev_dir and prev_dir.is_dir():
            lp = prev_dir / season_paths.SEASON_LEAGUE_NAME
            cp = prev_dir / season_paths.SEASON_CL_NAME
            op = prev_dir / season_paths.SEASON_COMMON_NAME
            if lp.is_file() and cp.is_file() and op.is_file():
                return lp, cp, op
        if active == 1 and leg_l.is_file() and leg_c.is_file() and leg_o.is_file():
            return leg_l, leg_c, leg_o
        return None, None, None

    dst_l = cur_dir / season_paths.SEASON_LEAGUE_NAME
    dst_c = cur_dir / season_paths.SEASON_CL_NAME
    dst_o = cur_dir / season_paths.SEASON_COMMON_NAME

    if force_reclone:
        for f in (dst_l, dst_c, dst_o):
            if f.is_file():
                f.unlink()
                print(f"Удалён для пересоздания: {f}")

    if dst_l.is_file() and dst_c.is_file() and dst_o.is_file():
        print(f"БД сезона уже на месте: {cur_dir}")
    else:
        sl, sc, so = _src_triple()
        if not sl or not sc or not so:
            raise FileNotFoundError(
                "Нет источника для БД: нужен полный архив db/season_{N-1}/*.db "
                f"(для первого сезона — {season_paths.LEGACY_LEAGUE} и пара файлов)."
            )
        print(f"Клонирую БД (матчевая стата → 0) из {sl.parent} → {cur_dir}")
        _clone_db_zero_stats(str(sl), str(dst_l))
        _clone_db_zero_stats(str(sc), str(dst_c))
        _clone_db_zero_stats(str(so), str(dst_o))

    p_dst = cur_dir / "pickle"
    root_pickle = Path(season_paths.PROJECT_ROOT) / "pickle"
    if p_dst.is_dir() and any(p_dst.iterdir()):
        print(f"Pickle уже есть: {p_dst}")
    else:
        src_p = None
        if prev_dir and (prev_dir / "pickle").is_dir():
            src_p = prev_dir / "pickle"
        elif root_pickle.is_dir():
            src_p = root_pickle
        if not src_p:
            print("Предупреждение: не найдена папка pickle для копирования.")
        else:
            if p_dst.is_dir():
                shutil.rmtree(p_dst)
            shutil.copytree(src_p, p_dst)
            print(f"Скопирован pickle: {src_p} → {p_dst}")
            from teams import reset_all_teams, reload_teams_from_disk

            reset_all_teams()
            reload_teams_from_disk()
            print("Pickle обнулён (таблицы сезона с 0 матчей).")

    actions = season_paths.repair_per_season_database_files()
    if actions:
        print("repair_per_season_database_files:", actions)
    reinit_db_connections()
    print("reinit_db_connections() выполнен.")

    from utils.common_db import rebuild_common_database

    rebuild_common_database()
    print("rebuild_common_database() для активного сезона выполнен.")


def main() -> int:
    ap = argparse.ArgumentParser(description="Расписание v3 + БД активного сезона (локально).")
    ap.add_argument("--seed", type=int, default=None, help="Seed RNG для mixed_schedule.json")
    ap.add_argument(
        "--schedule-only",
        action="store_true",
        help="Только пересоздать mixed_schedule.json",
    )
    ap.add_argument(
        "--reclone-season-dbs",
        action="store_true",
        help="Удалить league/cl/common активного сезона и заново клонировать из season_{N-1}",
    )
    args = ap.parse_args()

    _regenerate_schedule(args.seed)

    if args.schedule_only:
        print("Готово (--schedule-only).")
        return 0

    _ensure_season_dbs_and_pickle(force_reclone=args.reclone_season_dbs)
    print("Готово.")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as e:
        print(f"Ошибка: {e}", file=sys.stderr)
        raise SystemExit(1) from e
