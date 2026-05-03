# -*- coding: utf-8 -*-
"""Чтение справочника свободных агентов (db/free_agents.db)."""
from __future__ import annotations

import os
from typing import Any

from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from data.free_agent import FreeAgent
from utils.player_transfer import _norm_cmp

_engine: Any = None
_Session: Any = None


def invalidate_free_agents_engine() -> None:
    """Сбросить пул после миграции/ручного изменения free_agents.db на диске."""
    global _engine, _Session
    if _engine is not None:
        try:
            _engine.dispose()
        except Exception:
            pass
    _engine = None
    _Session = None


def _ensure_engine() -> None:
    global _engine, _Session
    if _engine is not None:
        return
    from utils.migrate_free_agents import migrate_free_agents_db
    from utils.season_paths import get_free_agents_db_path

    migrate_free_agents_db()
    path = get_free_agents_db_path()
    os.makedirs(os.path.dirname(path), exist_ok=True)
    _engine = create_engine(f"sqlite:///{path}")
    _Session = sessionmaker(bind=_engine)


def session_free_agents() -> Session:
    _ensure_engine()
    return _Session()


def delete_signed_free_agent(name: str, position: str) -> int:
    """
    Удаляет строку СА после успешного оформления в клуб (имя и позиция как в справочнике).
    Возвращает число удалённых строк (0 или 1).
    """
    want_n = _norm_cmp(name)
    want_p = _norm_cmp(position)
    sess = session_free_agents()
    try:
        for r in sess.query(FreeAgent).all():
            if _norm_cmp(r.name or "") != want_n:
                continue
            if _norm_cmp(r.position or "") != want_p:
                continue
            sess.delete(r)
            sess.commit()
            return 1
        return 0
    except Exception:
        sess.rollback()
        raise
    finally:
        sess.close()


def list_free_agents_tuples() -> list[tuple[str, str, int, str | None]]:
    """(имя в БД, позиция, overall, нация) — для клавиатуры трансфера."""
    sess = session_free_agents()
    try:
        rows = (
            sess.query(FreeAgent)
            .order_by(FreeAgent.overall.desc(), FreeAgent.name)
            .all()
        )
        return [
            (
                (r.name or "").strip(),
                (r.position or "").strip(),
                int(r.overall or 0),
                (r.nation or "").strip() or None,
            )
            for r in rows
        ]
    finally:
        sess.close()


def verify_free_agent_for_transfer(
    name: str,
    position: str,
    overall: int,
    nation: str | None,
) -> bool:
    """Проверка, что в справочнике есть такая же строка (защита от подмены FSM)."""
    row = find_free_agent_row(name, position)
    if row is None:
        return False
    _n, _p, o, nat = row
    if int(o) != int(overall):
        return False
    a = (nat or "").strip()
    b = (nation or "").strip()
    return _norm_cmp(a) == _norm_cmp(b)


def find_free_agent_row(
    name: str, position: str
) -> tuple[str, str, int, str | None] | None:
    want_n = _norm_cmp(name)
    want_p = _norm_cmp(position)
    sess = session_free_agents()
    try:
        for r in sess.query(FreeAgent).all():
            if _norm_cmp(r.name or "") != want_n:
                continue
            if _norm_cmp(r.position or "") != want_p:
                continue
            return (
                (r.name or "").strip(),
                (r.position or "").strip(),
                int(r.overall or 0),
                (r.nation or "").strip() or None,
            )
    finally:
        sess.close()
    return None
