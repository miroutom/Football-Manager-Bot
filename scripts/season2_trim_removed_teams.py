#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Разовая правка **только** ``db/season_2/{league,champions_league}.db``:
удаление игроков из выбывающих клубов с исключениями по имени; затем ``common.db`` сезона 2.

Не трогает season_1 и *_synced.db.
Запуск из корня проекта (venv с sqlalchemy):

  python scripts/season2_trim_removed_teams.py
"""
from __future__ import annotations

import os
import sys

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from data.defender import Defender
from data.forward import Forward
from data.goalkeeper import Goalkeeper
from data.midfielder import Midfielder
from utils import season_paths
from utils.common_db import rebuild_common_database_for_disk_paths
from utils.player_transfer import _filter_team

_SEASON = 2
_ALL_PLAYER = (Forward, Midfielder, Defender, Goalkeeper)

# Команда в БД → множество имён (как в SQLite), которые **оставить**.
KEEP: dict[str, frozenset[str]] = {
    "Ростов": frozenset({"Ранделович"}),
    "Фрайбург": frozenset({"Рёль"}),
    "Райо Вальекано": frozenset({"Шешко"}),
    "Штутгарт": frozenset({"Ито"}),
    "Торино": frozenset({"Бонджорно", "Риччи"}),
    "Брайтон": frozenset({"Адингра", "Симеоне", "Гроб", "Эступинан", "Лампти", "Игорь"}),
    "Фулхэм": frozenset({"Перейра", "Бейси", "Диоп", "Лекуе", "Лено"}),
    "Вильярреал": frozenset({"Гризманн"}),
    "Сассуоло": frozenset({"Кастильехо", "Байер"}),
}

# Полностью очистить состав (нац. + полностью из ЛЧ).
FULL_DROP = frozenset({"Рубин"})


def _norm_name(s: str) -> str:
    return " ".join((s or "").strip().split()).lower()


def _rows_to_delete(sess, team: str, keep: frozenset[str]) -> list[tuple[type, int]]:
    """Список (Cls, id) на удаление в одной сессии."""
    keep_l = {_norm_name(x) for x in keep}
    out: list[tuple[type, int]] = []
    for Cls in _ALL_PLAYER:
        for r in sess.query(Cls).filter(_filter_team(Cls, team)).all():
            nk = _norm_name(getattr(r, "name", "") or "")
            if nk and nk not in keep_l:
                rid = getattr(r, "id", None)
                if rid is not None:
                    out.append((Cls, int(rid)))
    return out


def _purge_team_league(sess, team: str) -> int:
    n = 0
    for Cls in _ALL_PLAYER:
        q = sess.query(Cls).filter(_filter_team(Cls, team))
        c = q.delete(synchronize_session=False)
        n += int(c or 0)
    return n


def _purge_team_cl(sess, team: str) -> int:
    return _purge_team_league(sess, team)


def run() -> None:
    base = os.path.join(season_paths.PROJECT_ROOT, "db", f"season_{_SEASON}")
    p_l = os.path.join(base, season_paths.SEASON_LEAGUE_NAME)
    p_c = os.path.join(base, season_paths.SEASON_CL_NAME)
    p_o = os.path.join(base, season_paths.SEASON_COMMON_NAME)

    teams = sorted(set(KEEP) | FULL_DROP)
    el = create_engine(f"sqlite:///{p_l}")
    ec = create_engine(f"sqlite:///{p_c}")
    Sl = sessionmaker(bind=el)
    Scl = sessionmaker(bind=ec)
    sl, scl = Sl(), Scl()
    try:
        for t in teams:
            if t in FULL_DROP:
                nl = _purge_team_league(sl, t)
                nc = _purge_team_cl(scl, t)
                print(f"{t}: league deleted {nl}, cl deleted {nc} (полный сброс)")
                continue
            keep = KEEP[t]
            pairs_l = _rows_to_delete(sl, t, keep)
            pairs_c = _rows_to_delete(scl, t, keep)
            for Cls, rid in pairs_l:
                sl.query(Cls).filter(Cls.id == rid).delete(synchronize_session=False)
            for Cls, rid in pairs_c:
                scl.query(Cls).filter(Cls.id == rid).delete(synchronize_session=False)
            print(
                f"{t}: league removed {len(pairs_l)}, cl removed {len(pairs_c)}, "
                f"kept {sorted(keep)}",
            )
        sl.commit()
        scl.commit()
    except Exception:
        sl.rollback()
        scl.rollback()
        raise
    finally:
        sl.close()
        scl.close()
        el.dispose()
        ec.dispose()

    rebuild_common_database_for_disk_paths(p_l, p_c, p_o)
    print("Пересобран:", p_o)


if __name__ == "__main__":
    run()
