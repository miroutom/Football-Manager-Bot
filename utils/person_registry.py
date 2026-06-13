# -*- coding: utf-8 -*-
"""Реестр игроков: стабильный ``person_id`` на всю карьеру в проекте."""
from __future__ import annotations

import os
from datetime import datetime, timezone

from sqlalchemy import Column, DateTime, Integer, String, create_engine, text
from sqlalchemy.orm import declarative_base, sessionmaker

from utils.utils import PROJECT_ROOT

_REGISTRY_PATH = os.path.join(PROJECT_ROOT, "db", "players_registry.db")

_RegistryBase = declarative_base()


class Person(_RegistryBase):
    __tablename__ = "persons"
    person_id = Column(Integer, primary_key=True, autoincrement=True)
    created_at = Column(DateTime, nullable=False)
    notes = Column(String, nullable=True)


def registry_db_path() -> str:
    return _REGISTRY_PATH


def _engine():
    os.makedirs(os.path.dirname(_REGISTRY_PATH) or ".", exist_ok=True)
    eng = create_engine(f"sqlite:///{_REGISTRY_PATH}")
    _RegistryBase.metadata.create_all(eng)
    return eng


def init_registry_db() -> None:
    _engine().dispose()


def register_existing_person_id(person_id: int, *, notes: str = "") -> None:
    """Записать id из backfill, чтобы ``allocate_person_id`` не выдал его снова."""
    pid = int(person_id)
    if pid <= 0:
        raise ValueError("person_id must be positive")
    eng = _engine()
    Session = sessionmaker(bind=eng)
    sess = Session()
    try:
        exists = sess.get(Person, pid)
        if exists is not None:
            return
        sess.add(
            Person(
                person_id=pid,
                created_at=datetime.now(timezone.utc),
                notes=(notes or "").strip() or None,
            )
        )
        sess.commit()
    finally:
        sess.close()
        eng.dispose()


def sync_registry_after_backfill(assigned_ids: list[int]) -> int:
    """Зарегистрировать все выданные id; вернуть max person_id."""
    for pid in sorted(set(int(x) for x in assigned_ids if int(x) > 0)):
        register_existing_person_id(pid)
    if not assigned_ids:
        return 0
    return max(int(x) for x in assigned_ids)


def allocate_person_id(*, notes: str = "") -> int:
    """Новый ``person_id`` (монотонный, без переиспользования)."""
    eng = _engine()
    Session = sessionmaker(bind=eng)
    sess = Session()
    try:
        row_max = sess.execute(text("SELECT COALESCE(MAX(person_id), 0) FROM persons")).scalar()
        next_id = int(row_max or 0) + 1
        sess.add(
            Person(
                person_id=next_id,
                created_at=datetime.now(timezone.utc),
                notes=(notes or "").strip() or None,
            )
        )
        sess.commit()
        return next_id
    finally:
        sess.close()
        eng.dispose()


def row_person_id(row) -> int | None:
    pid = getattr(row, "person_id", None)
    if pid is None:
        return None
    try:
        v = int(pid)
    except (TypeError, ValueError):
        return None
    return v if v > 0 else None


def _identity_pos_key(name: str, position: str) -> tuple[str, str]:
    from utils.player_names import player_stats_identity_token

    class _Row:
        def __init__(self, n: str, p: str) -> None:
            self.name = n
            self.position = p

    ident = player_stats_identity_token(_Row((name or "").strip(), position)).casefold()
    pos = (position or "").strip().upper()
    return ident, pos


def lookup_canonical_person_id(
    name: str,
    position: str,
    *,
    team: str | None = None,
) -> int | None:
    """
    Стабильный ``person_id`` из накопительных БД и архивов сезонов.

    Канон: строка с max ``matches``; при равенстве — min ``person_id``.
    """
    import sqlite3

    from utils import season_paths
    from utils.player_transfer import _norm_cmp

    ident, pos = _identity_pos_key(name, position)
    want_team = _norm_cmp(team) if team else None
    best: tuple[int, int] | None = None  # (matches, -person_id for min pid)

    def _consider(pid_raw: object, matches_raw: object) -> None:
        nonlocal best
        try:
            pid = int(pid_raw or 0)
        except (TypeError, ValueError):
            return
        if pid <= 0:
            return
        m = int(matches_raw or 0)
        cand = (m, -pid)
        if best is None or cand > best:
            best = cand

    db_paths: list[str] = []
    for getter in (
        season_paths.get_cumulative_common_db_path,
        season_paths.get_cumulative_league_db_path,
        season_paths.get_cumulative_cl_db_path,
    ):
        p = getter()
        if p and os.path.isfile(p):
            db_paths.append(p)

    db_dir = os.path.join(PROJECT_ROOT, "db")
    if os.path.isdir(db_dir):
        for entry in os.listdir(db_dir):
            if not entry.startswith("season_"):
                continue
            for fname in (
                season_paths.SEASON_LEAGUE_NAME,
                season_paths.SEASON_CL_NAME,
                season_paths.SEASON_COMMON_NAME,
            ):
                path = os.path.join(db_dir, entry, fname)
                if os.path.isfile(path):
                    db_paths.append(path)

    for active in (season_paths.get_league_db_path(), season_paths.get_cl_db_path()):
        if active and os.path.isfile(active):
            db_paths.append(active)

    seen_paths: set[str] = set()
    tables = ("forwards", "midfielders", "defenders", "goalkeepers")
    for path in db_paths:
        path = os.path.abspath(path)
        if path in seen_paths:
            continue
        seen_paths.add(path)
        conn = sqlite3.connect(path)
        try:
            for tbl in tables:
                cols = {
                    r[1] for r in conn.execute(f"PRAGMA table_info({tbl})").fetchall()
                }
                if "person_id" not in cols or "name" not in cols:
                    continue
                team_sql = ", team" if "team" in cols else ""
                q = (
                    f"SELECT name, position, person_id, matches{team_sql} FROM {tbl}"
                )
                for row in conn.execute(q):
                    nm, pos_row, pid, matches = row[0], row[1], row[2], row[3]
                    tm = row[4] if len(row) > 4 else None
                    if _identity_pos_key(nm or "", pos_row or "") != (ident, pos):
                        continue
                    if want_team is not None and _norm_cmp(tm or "") != want_team:
                        continue
                    _consider(pid, matches)
        finally:
            conn.close()

    if best is None:
        return None
    return -best[1]


def ensure_row_person_id(row, *, notes: str = "", persist: bool = True) -> int:
    """
    Вернуть ``person_id`` строки; если NULL — выделить и записать в row.
    ``persist=False`` — только выделить id (для kwargs до insert).
    """
    existing = row_person_id(row)
    if existing is not None:
        return existing
    nm = (getattr(row, "name", None) or "").strip()
    tm = (getattr(row, "team", None) or "").strip()
    hint = (notes or "").strip() or f"{nm} · {tm}".strip(" ·")
    pid = allocate_person_id(notes=hint)
    if persist:
        row.person_id = pid
    return pid
