#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Удалить строки-заглушки, где имя == фамилия (Карраско/Карраско), если в names.xlsx
нет явной пары name==surname.

Перед удалением стата сливается в «нормальную» строку того же клуба+позиции с той же фамилией.

  python3 scripts/remove_placeholder_player_rows.py
  python3 scripts/remove_placeholder_player_rows.py --apply
"""
from __future__ import annotations

import argparse
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from data.defender import Defender
from data.forward import Forward
from data.goalkeeper import Goalkeeper
from data.midfielder import Midfielder
from utils import season_paths

_ALL = (Forward, Midfielder, Defender, Goalkeeper)

STAT_FIELDS = (
    "matches",
    "goals",
    "assists",
    "ga",
    "clean_sheets",
    "missed_goals",
    "trophies",
    "golden_balls",
    "golden_boots",
    "golden_gloves",
    "golden_boys",
    "yellow_cards",
    "red_cards",
)


def _load_xlsx_same_name_pairs(xlsx_path: str) -> set[tuple[str, str, str]]:
    """(team, position, token) для строк xlsx, где имя == фамилия — не трогать."""
    if not os.path.isfile(xlsx_path):
        return set()
    try:
        import openpyxl
    except ImportError:
        return set()
    from scripts.import_player_names_xlsx import (  # noqa: WPS433
        _canonical_xlsx_team,
        load_names_xlsx,
    )

    out: set[tuple[str, str, str]] = set()
    for xp in load_names_xlsx(xlsx_path):
        fn = (xp.first_name or "").strip()
        sn = (xp.surname_label or "").strip()
        if fn and sn and fn.casefold() == sn.casefold():
            team = _canonical_xlsx_team(xp.team)
            out.add(
                (
                    team.casefold(),
                    (xp.position or "").strip().upper(),
                    sn.casefold(),
                )
            )
    return out


def _is_placeholder(row: object) -> bool:
    n = (getattr(row, "name", None) or "").strip()
    s = (getattr(row, "surname", None) or "").strip()
    return bool(n and s and n.casefold() == s.casefold())


def _merge_stats(keeper: object, donor: object) -> None:
    for fld in STAT_FIELDS:
        if not hasattr(keeper, fld) or not hasattr(donor, fld):
            continue
        setattr(
            keeper,
            fld,
            int(getattr(keeper, fld, 0) or 0) + int(getattr(donor, fld, 0) or 0),
        )
    if hasattr(keeper, "goals") and hasattr(keeper, "assists"):
        keeper.ga = int(getattr(keeper, "goals", 0) or 0) + int(
            getattr(keeper, "assists", 0) or 0
        )


def _find_canonical_in_session(session, Cls: type, ph: object) -> object | None:
    team = (getattr(ph, "team", None) or "").strip().casefold()
    pos = (getattr(ph, "position", None) or "").strip().upper()
    token = (getattr(ph, "name", None) or "").strip().casefold()
    best = None
    best_score = -1
    for r in session.query(Cls).all():
        if int(getattr(r, "id", 0) or 0) == int(getattr(ph, "id", 0) or 0):
            continue
        if (getattr(r, "team", None) or "").strip().casefold() != team:
            continue
        if (getattr(r, "position", None) or "").strip().upper() != pos:
            continue
        sn = (getattr(r, "surname", None) or "").strip().casefold()
        nm = (getattr(r, "name", None) or "").strip().casefold()
        if sn != token and nm != token:
            continue
        if _is_placeholder(r):
            continue
        score = 2 if sn == token else 1
        if score > best_score:
            best_score = score
            best = r
    return best


def _league_companion_path(db_path: str) -> str | None:
    """``season_N/champions_league.db`` → ``season_N/league.db`` для поиска канона."""
    norm = db_path.replace("\\", "/")
    if "/champions_league.db" not in norm:
        return None
    cand = norm.replace("/champions_league.db", "/league.db")
    return cand if os.path.isfile(cand) else None


def _process_db(
    db_path: str,
    *,
    allow: set[tuple[str, str, str]],
    apply: bool,
    extra_sessions: list | None = None,
) -> tuple[int, int]:
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker

    from utils.utils import Base

    if not os.path.isfile(db_path):
        return 0, 0
    eng = create_engine(f"sqlite:///{db_path}")
    Base.metadata.create_all(eng)
    Sess = sessionmaker(bind=eng)
    s = Sess()
    extra: list = []
    league_path = _league_companion_path(db_path)
    league_eng = None
    if league_path:
        league_eng = create_engine(f"sqlite:///{league_path}")
        extra.append(sessionmaker(bind=league_eng)())
    merged = skipped = 0
    try:
        for Cls in _ALL:
            for ph in list(s.query(Cls).all()):
                if not _is_placeholder(ph):
                    continue
                team_cf = (getattr(ph, "team", None) or "").strip().casefold()
                pos = (getattr(ph, "position", None) or "").strip().upper()
                token = (getattr(ph, "name", None) or "").strip().casefold()
                if (team_cf, pos, token) in allow:
                    skipped += 1
                    continue
                canon_local = _find_canonical_in_session(s, Cls, ph)
                if canon_local is not None:
                    if apply:
                        _merge_stats(canon_local, ph)
                        s.delete(ph)
                    merged += 1
                    continue
                canon_league = None
                for es in extra:
                    canon_league = _find_canonical_in_session(es, Cls, ph)
                    if canon_league is not None:
                        break
                if canon_league is None:
                    continue
                if apply:
                    ph.name = canon_league.name
                    if hasattr(ph, "surname"):
                        ph.surname = getattr(canon_league, "surname", None)
                merged += 1
        if apply:
            s.commit()
    finally:
        for es in extra:
            es.close()
        if league_eng is not None:
            league_eng.dispose()
        s.close()
        eng.dispose()
    return merged, skipped


def _default_db_paths() -> list[str]:
    db = os.path.join(ROOT, "db")
    names = (
        "league.db",
        "champions_league.db",
        "common.db",
        "league_synced.db",
        "champions_league_synced.db",
        "common_synced.db",
    )
    paths: list[str] = []
    for n in names:
        p = os.path.join(db, n)
        if os.path.isfile(p):
            paths.append(p)
    from utils.cumulative_db import list_season_archives_with_db

    for sn in list_season_archives_with_db():
        for n in ("league.db", "champions_league.db", "common.db"):
            p = os.path.join(db, f"season_{sn}", n)
            if os.path.isfile(p):
                paths.append(p)
    return paths


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--apply", action="store_true")
    ap.add_argument("--db", action="append", default=[])
    ap.add_argument(
        "--xlsx",
        default=os.path.join(ROOT, "db", "names.xlsx"),
        help="Исключения name==surname из xlsx",
    )
    args = ap.parse_args()
    allow = _load_xlsx_same_name_pairs(args.xlsx)
    if allow:
        print(f"Исключений из xlsx (name==surname): {len(allow)}")
    paths = args.db or _default_db_paths()
    t_m = t_s = 0
    for p in paths:
        m, sk = _process_db(p, allow=allow, apply=args.apply)
        rel = os.path.relpath(p, ROOT)
        print(f"{'APPLY' if args.apply else 'dry-run'} {rel}: merged={m} skip_xlsx={sk}")
        t_m += m
        t_s += sk
    print(f"Итого: merged={t_m} skip={t_s}")
    if not args.apply:
        print("Повторите с --apply.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
