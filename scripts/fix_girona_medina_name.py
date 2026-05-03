#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Исправить имя «Медина» у «Жироны»: в БД было «медина» и т.п. — записать «Медина».

По умолчанию обрабатывает:
  • активные league/cl из season_paths (как у бота);
  • при наличии файлов — db/league_synced.db, db/champions_league_synced.db;
  • при наличии — db/season_2/league.db и db/season_2/champions_league.db.

После правок пересобирает common для активных путей (reinit + rebuild).
"""
from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from data.defender import Defender
from data.forward import Forward
from data.goalkeeper import Goalkeeper
from data.midfielder import Midfielder
from utils import season_paths
from utils.player_transfer import _norm_cmp

_ALL = (Forward, Midfielder, Defender, Goalkeeper)
TEAM_WANT = "Жирона"
NAME_CORRECT = "Медина"


def _paths_default() -> list[str]:
    out: list[str] = []
    for getter in (season_paths.get_league_db_path, season_paths.get_cl_db_path):
        p = getter()
        if p and os.path.isfile(p) and p not in out:
            out.append(p)
    db = Path(season_paths.PROJECT_ROOT) / "db"
    for rel in (
        "league_synced.db",
        "champions_league_synced.db",
        "season_2/league.db",
        "season_2/champions_league.db",
    ):
        p = str(db / rel)
        if os.path.isfile(p) and p not in out:
            out.append(p)
    return out


def fix_on_sqlite(path: str) -> int:
    engine = create_engine(f"sqlite:///{path}")
    Sess = sessionmaker(bind=engine)
    sess = Sess()
    changed = 0
    try:
        for Cls in _ALL:
            for r in sess.query(Cls).all():
                team = (getattr(r, "team", None) or "").strip()
                nm = (getattr(r, "name", None) or "").strip()
                if _norm_cmp(team) != _norm_cmp(TEAM_WANT):
                    continue
                if _norm_cmp(nm) != _norm_cmp(NAME_CORRECT):
                    continue
                if nm != NAME_CORRECT:
                    r.name = NAME_CORRECT
                    changed += 1
        if changed:
            sess.commit()
        else:
            sess.rollback()
    except Exception:
        sess.rollback()
        raise
    finally:
        sess.close()
        engine.dispose()
    return changed


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument(
        "paths",
        nargs="*",
        help="Дополнительные пути к SQLite (если не указано — набор по умолчанию)",
    )
    args = ap.parse_args()
    paths = [os.path.abspath(p) for p in args.paths] if args.paths else _paths_default()
    total = 0
    for p in paths:
        if not os.path.isfile(p):
            print(f"skip (нет файла): {p}")
            continue
        n = fix_on_sqlite(p)
        print(f"{p}: обновлено строк: {n}")
        total += n
    print(f"Итого правок имени: {total}")
    if total:
        from utils.utils import reinit_db_connections
        from utils.common_db import rebuild_common_database

        reinit_db_connections()
        rebuild_common_database()
        print("common.db пересобран (активные league/cl).")


if __name__ == "__main__":
    main()
