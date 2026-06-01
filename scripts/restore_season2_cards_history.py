#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Восстановить историю жк/кк в season_2 (league.db + champions_league.db).

Источники (для каждой строки имя+клуб+позиция):
  1. max по всем ``db/season_2/backup_*``;
  2. max с текущим значением в активной БД;
  3. ``yellow_cycle.count`` из ``data/player_discipline.json`` (только жк, по клубу из записи).

Строки с жк/кк в бэкапе, но отсутствующие в активной БД, копируются из основного снимка
(``backup_20260526_201438`` по умолчанию) — чтобы сохранить историю на старом клубе после трансфера.

После --apply: common season_2 + пересборка ``*_synced.db``.

  python3 scripts/restore_season2_cards_history.py
  python3 scripts/restore_season2_cards_history.py --apply
"""
from __future__ import annotations

import argparse
import glob
import os
import sys
from typing import Any

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from data.defender import Defender
from data.forward import Forward
from data.goalkeeper import Goalkeeper
from data.midfielder import Midfielder
from utils import season_paths

_ALL = (Forward, Midfielder, Defender, Goalkeeper)
TABLE_FOR = {
    Forward: "forwards",
    Midfielder: "midfielders",
    Defender: "defenders",
    Goalkeeper: "goalkeepers",
}
S2 = os.path.join(ROOT, "db", "season_2")
DEFAULT_ROW_SRC = os.path.join(S2, "backup_20260526_201438")


def _key(name: str, team: str, position: str) -> tuple[str, str, str]:
    return (
        (name or "").strip().casefold(),
        (team or "").strip().casefold(),
        (position or "").strip().upper(),
    )


def _db_kind(path: str) -> str:
    return "cl" if "champions" in path.replace("\\", "/") else "league"


def _load_cards(path: str) -> dict[tuple[str, str, str], tuple[int, int]]:
    eng = create_engine(f"sqlite:///{path}")
    Sess = sessionmaker(bind=eng)
    s = Sess()
    out: dict[tuple[str, str, str], tuple[int, int]] = {}
    try:
        for Cls in _ALL:
            for r in s.query(Cls).all():
                y = int(getattr(r, "yellow_cards", 0) or 0)
                rd = int(getattr(r, "red_cards", 0) or 0)
                if y or rd:
                    out[_key(r.name, r.team, r.position)] = (y, rd)
    finally:
        s.close()
        eng.dispose()
    return out


def _merge_max(
    acc: dict[tuple[str, str, str], tuple[int, int]], src: dict[tuple[str, str, str], tuple[int, int]]
) -> None:
    for k, (y, rd) in src.items():
        oy, ord_ = acc.get(k, (0, 0))
        acc[k] = (max(oy, y), max(ord_, rd))


def _yellow_from_discipline() -> tuple[dict[tuple[str, str, str], int], dict[tuple[str, str, str], int]]:
    from utils.player_discipline import _load

    st = _load()
    league_y: dict[tuple[str, str, str], int] = {}
    cl_y: dict[tuple[str, str, str], int] = {}
    for row in st.get("yellow_cycle", []):
        scope = (row.get("scope") or "league").strip().lower()
        name = (row.get("name") or "").strip()
        team = (row.get("team") or "").strip()
        pos_rows = []  # position unknown in JSON — match by name+team only later
        c = int(row.get("count") or 0)
        if not name or not team or c <= 0:
            continue
        # store by partial key; resolve position when applying
        partial = ((name.casefold(), team.casefold()), c)
        if scope == "cl":
            cl_y[partial[0]] = max(cl_y.get(partial[0], 0), c)
        else:
            league_y[partial[0]] = max(league_y.get(partial[0], 0), c)
    return league_y, cl_y


def _resolve_discipline_targets(
    sess, kind: str, partial: dict[tuple[str, str], int]
) -> dict[tuple[str, str, str], int]:
    """name+team -> max count; если несколько позиций — всем строкам этого клуба тот же floor."""
    out: dict[tuple[str, str, str], int] = {}
    for Cls in _ALL:
        for r in sess.query(Cls).all():
            nk = ((r.name or "").strip().casefold(), (r.team or "").strip().casefold())
            if nk not in partial:
                continue
            out[_key(r.name, r.team, r.position)] = max(
                out.get(_key(r.name, r.team, r.position), 0), partial[nk]
            )
    return out


def _row_as_new(Cls: type, p) -> Any:
    d = {
        c.name: getattr(p, c.name)
        for c in Cls.__table__.columns
        if not c.primary_key
    }
    return Cls(**d)


def _find_row(sess, Cls: type, name: str, team: str, position: str):
    nk = _key(name, team, position)
    for r in sess.query(Cls).all():
        if _key(r.name, r.team, r.position) == nk:
            return r
    return None


def _apply_to_db(
    dst_path: str,
    targets: dict[tuple[str, str, str], tuple[int, int]],
    row_src_path: str | None,
    *,
    apply: bool,
) -> tuple[int, int, int]:
    """updated, inserted, target_keys."""
    eng = create_engine(f"sqlite:///{dst_path}")
    Sess = sessionmaker(bind=eng)
    s = Sess()
    updated = inserted = 0
    try:
        existing_keys: set[tuple[str, str, str]] = set()
        for Cls in _ALL:
            for r in s.query(Cls).all():
                existing_keys.add(_key(r.name, r.team, r.position))

        for Cls in _ALL:
            for r in s.query(Cls).all():
                k = _key(r.name, r.team, r.position)
                if k not in targets:
                    continue
                y, rd = targets[k]
                cy = int(r.yellow_cards or 0)
                cr = int(r.red_cards or 0)
                if cy != y or cr != rd:
                    if apply:
                        r.yellow_cards = y
                        r.red_cards = rd
                    updated += 1

        missing = [k for k in targets if k not in existing_keys and (targets[k][0] or targets[k][1])]
        if missing and row_src_path and os.path.isfile(row_src_path):
            eng_src = create_engine(f"sqlite:///{row_src_path}")
            s_src = sessionmaker(bind=eng_src)()
            try:
                for Cls in _ALL:
                    for r in s_src.query(Cls).all():
                        k = _key(r.name, r.team, r.position)
                        if k not in missing:
                            continue
                        y, rd = targets[k]
                        if apply:
                            s.add(_row_as_new(Cls, r))
                            row = _find_row(s, Cls, r.name, r.team, r.position)
                            if row is not None:
                                row.yellow_cards = y
                                row.red_cards = rd
                        inserted += 1
            finally:
                s_src.close()
                eng_src.dispose()

        if apply:
            s.commit()
    finally:
        s.close()
        eng.dispose()
    return updated, inserted, len(targets)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true")
    ap.add_argument(
        "--row-src",
        default=DEFAULT_ROW_SRC,
        help="Папка backup_* для копирования отсутствующих строк",
    )
    args = ap.parse_args()

    dst_l = os.path.join(S2, season_paths.SEASON_LEAGUE_NAME)
    dst_c = os.path.join(S2, season_paths.SEASON_CL_NAME)
    dst_common = os.path.join(S2, season_paths.SEASON_COMMON_NAME)
    for p in (dst_l, dst_c):
        if not os.path.isfile(p):
            print(f"Нет файла: {p}")
            return 1

    merged_l: dict[tuple[str, str, str], tuple[int, int]] = {}
    merged_c: dict[tuple[str, str, str], tuple[int, int]] = {}

    _merge_max(merged_l, _load_cards(dst_l))
    _merge_max(merged_c, _load_cards(dst_c))

    backup_dirs = sorted(glob.glob(os.path.join(S2, "backup_*")))
    for bdir in backup_dirs:
        pl = os.path.join(bdir, season_paths.SEASON_LEAGUE_NAME)
        pc = os.path.join(bdir, season_paths.SEASON_CL_NAME)
        if os.path.isfile(pl):
            _merge_max(merged_l, _load_cards(pl))
        if os.path.isfile(pc):
            _merge_max(merged_c, _load_cards(pc))

    league_part, cl_part = _yellow_from_discipline()
    eng_l = create_engine(f"sqlite:///{dst_l}")
    eng_c = create_engine(f"sqlite:///{dst_c}")
    sl = sessionmaker(bind=eng_l)()
    sc = sessionmaker(bind=eng_c)()
    try:
        disc_l = _resolve_discipline_targets(sl, "league", league_part)
        disc_c = _resolve_discipline_targets(sc, "cl", cl_part)
    finally:
        sl.close()
        sc.close()
        eng_l.dispose()
        eng_c.dispose()

    for k, c in disc_l.items():
        y, rd = merged_l.get(k, (0, 0))
        merged_l[k] = (max(y, c), rd)
    for k, c in disc_c.items():
        y, rd = merged_c.get(k, (0, 0))
        merged_c[k] = (max(y, c), rd)

    # JSON: строки ещё не в БД (трансфер / потеря строки) — добавить target по name+team из row-src
    if os.path.isdir(args.row_src):
        src_l = os.path.join(args.row_src, season_paths.SEASON_LEAGUE_NAME)
        src_c = os.path.join(args.row_src, season_paths.SEASON_CL_NAME)
        for src_path, partial, merged in (
            (src_l, league_part, merged_l),
            (src_c, cl_part, merged_c),
        ):
            if not os.path.isfile(src_path):
                continue
            cards_src = _load_cards(src_path)
            eng = create_engine(f"sqlite:///{src_path}")
            ss = sessionmaker(bind=eng)()
            try:
                for Cls in _ALL:
                    for r in ss.query(Cls).all():
                        nk = (
                            (r.name or "").strip().casefold(),
                            (r.team or "").strip().casefold(),
                        )
                        if nk not in partial:
                            continue
                        k = _key(r.name, r.team, r.position)
                        y_b, rd_b = cards_src.get(k, (0, 0))
                        c = partial[nk]
                        y = max(y_b, c)
                        oy, ord_ = merged.get(k, (0, 0))
                        merged[k] = (max(oy, y), max(ord_, rd_b))
            finally:
                ss.close()
                eng.dispose()

    sum_l_y = sum(v[0] for v in merged_l.values())
    sum_c_y = sum(v[0] for v in merged_c.values())
    print(f"Целевых строк league: {len(merged_l)} (сумма жк={sum_l_y})")
    print(f"Целевых строк ЛЧ:     {len(merged_c)} (сумма жк={sum_c_y})")
    print(f"Бэкапов: {len(backup_dirs)}, row-src: {args.row_src}")

    santos_k = _key("Сантос", "Зенит", "ЛЗ")
    print(f"Сантос Зенит ЛЧ: {merged_c.get(santos_k, (0, 0))}")

    if not args.apply:
        print("\n(dry-run) Добавьте --apply для записи и пересборки synced.")
        return 0

    src_l = os.path.join(args.row_src, season_paths.SEASON_LEAGUE_NAME)
    src_c = os.path.join(args.row_src, season_paths.SEASON_CL_NAME)
    u_l, i_l, _ = _apply_to_db(dst_l, merged_l, src_l if os.path.isfile(src_l) else None, apply=True)
    u_c, i_c, _ = _apply_to_db(dst_c, merged_c, src_c if os.path.isfile(src_c) else None, apply=True)
    print(f"\nОбновлено: league={u_l}, ЛЧ={u_c}; вставлено строк: league={i_l}, ЛЧ={i_c}")

    from utils.common_db import rebuild_common_database_for_disk_paths

    rebuild_common_database_for_disk_paths(dst_l, dst_c, dst_common)
    print("season_2/common.db пересобран.")

    from utils.cumulative_db import rebuild_all_time_databases_from_season_archives
    from utils.utils import reinit_db_connections

    print(rebuild_all_time_databases_from_season_archives())
    reinit_db_connections()
    from utils.common_db import rebuild_common_database

    rebuild_common_database()
    print("Активный common (текущий сезон) пересобран.")
    print("Готово.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
