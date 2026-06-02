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
