# -*- coding: utf-8 -*-
"""
Справочник клубов и лиг: ``db/teams_registry.db``.

Метаданные команды (лига, менеджер, тир трофеев, ЛЧ) — не турнирная таблица и не состав.
"""
from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Any

from sqlalchemy import Column, Float, Integer, String, create_engine, text
from sqlalchemy.orm import declarative_base, sessionmaker

from utils.utils import PROJECT_ROOT

_REGISTRY_PATH = os.path.join(PROJECT_ROOT, "db", "teams_registry.db")

_RegistryBase = declarative_base()

# trophy_tier 1..5 → множитель амбиций (до league.trophy_scale)
TIER_AMBITION: dict[int, float] = {
    1: 0.10,
    2: 0.28,
    3: 0.50,
    4: 0.72,
    5: 0.95,
}


class LeagueRow(_RegistryBase):
    __tablename__ = "leagues"
    league_code = Column(String, primary_key=True)
    display_name = Column(String, nullable=False)
    trophy_scale = Column(Float, nullable=False, default=1.0)
    cl_scale = Column(Float, nullable=False, default=1.0)
    competitiveness = Column(Float, nullable=False, default=1.0)


class TeamRow(_RegistryBase):
    __tablename__ = "teams"
    team_id = Column(Integer, primary_key=True, autoincrement=True)
    name = Column(String, unique=True, nullable=False)
    name_norm = Column(String, nullable=False, index=True)
    league_code = Column(String, nullable=False)
    manager = Column(String, nullable=True)
    in_cl_pool = Column(Integer, nullable=False, default=0)
    trophy_tier = Column(Integer, nullable=False, default=3)
    fifa_stars = Column(Float, nullable=True)
    strength_cached = Column(Float, nullable=True)
    active = Column(Integer, nullable=False, default=1)


@dataclass(frozen=True)
class LeagueMeta:
    league_code: str
    display_name: str
    trophy_scale: float
    cl_scale: float
    competitiveness: float


@dataclass(frozen=True)
class TeamMeta:
    team_id: int
    name: str
    name_norm: str
    league_code: str
    manager: str | None
    in_cl_pool: bool
    trophy_tier: int
    fifa_stars: float | None
    strength_cached: float | None
    active: bool

    @property
    def trophy_ambition(self) -> float:
        """0..1 — трофейные ожидания клуба (без учёта лиги)."""
        tier = max(1, min(5, int(self.trophy_tier)))
        return TIER_AMBITION.get(tier, 0.5)


def registry_db_path() -> str:
    return _REGISTRY_PATH


def _norm_name(name: str) -> str:
    t = (name or "").strip()
    if t.casefold() == "цска":
        return "цска"
    return " ".join(t.casefold().split())


def _engine():
    os.makedirs(os.path.dirname(_REGISTRY_PATH) or ".", exist_ok=True)
    eng = create_engine(f"sqlite:///{_REGISTRY_PATH}")
    _RegistryBase.metadata.create_all(eng)
    return eng


def init_teams_registry_db() -> None:
    _engine().dispose()


def _row_to_league(r: LeagueRow) -> LeagueMeta:
    return LeagueMeta(
        league_code=r.league_code,
        display_name=r.display_name,
        trophy_scale=float(r.trophy_scale or 1.0),
        cl_scale=float(r.cl_scale or 1.0),
        competitiveness=float(r.competitiveness or 1.0),
    )


def _row_to_team(r: TeamRow) -> TeamMeta:
    return TeamMeta(
        team_id=int(r.team_id),
        name=r.name,
        name_norm=r.name_norm,
        league_code=r.league_code,
        manager=r.manager,
        in_cl_pool=bool(int(r.in_cl_pool or 0)),
        trophy_tier=int(r.trophy_tier or 3),
        fifa_stars=float(r.fifa_stars) if r.fifa_stars is not None else None,
        strength_cached=float(r.strength_cached) if r.strength_cached is not None else None,
        active=bool(int(r.active or 0)),
    )


def get_league(league_code: str) -> LeagueMeta | None:
    code = (league_code or "").strip().lower()
    if not code:
        return None
    eng = _engine()
    Session = sessionmaker(bind=eng)
    sess = Session()
    try:
        row = sess.get(LeagueRow, code)
        return _row_to_league(row) if row else None
    finally:
        sess.close()
        eng.dispose()


def get_team(name: str) -> TeamMeta | None:
    nn = _norm_name(name)
    if not nn:
        return None
    eng = _engine()
    Session = sessionmaker(bind=eng)
    sess = Session()
    try:
        row = sess.query(TeamRow).filter(TeamRow.name_norm == nn).first()
        return _row_to_team(row) if row else None
    finally:
        sess.close()
        eng.dispose()


def league_code_for_team(name: str) -> str | None:
    tm = get_team(name)
    return tm.league_code if tm else None


def teams_in_league(
    league_code: str, *, active_only: bool = True
) -> list[TeamMeta]:
    code = (league_code or "").strip().lower()
    eng = _engine()
    Session = sessionmaker(bind=eng)
    sess = Session()
    try:
        q = sess.query(TeamRow).filter(TeamRow.league_code == code)
        if active_only:
            q = q.filter(TeamRow.active == 1)
        rows = q.order_by(TeamRow.name).all()
        return [_row_to_team(r) for r in rows]
    finally:
        sess.close()
        eng.dispose()


def club_trophy_ambition(team_name: str, *, league_rank: int | None = None) -> float:
    """
    0..1 — трофейная амбиция клуба: лига × тир из реестра.
    ``league_rank`` не используется, если в БД задан ``trophy_tier``.
    """
    tm = get_team(team_name)
    if tm is None:
        return 0.35
    lg = get_league(tm.league_code)
    scale = float(lg.trophy_scale) if lg else 0.7
    cl_amb = scale * tm.trophy_ambition
    return max(0.0, min(1.0, cl_amb))


def refresh_team_strength_cache(team_name: str) -> float | None:
    """Обновить ``strength_cached`` из среднего overall в league.db."""
    from utils.team_strength import get_team_strength

    tm = get_team(team_name)
    if tm is None:
        return None
    val = float(get_team_strength(tm.name, "league"))
    eng = _engine()
    Session = sessionmaker(bind=eng)
    sess = Session()
    try:
        row = sess.query(TeamRow).filter(TeamRow.team_id == tm.team_id).first()
        if row:
            row.strength_cached = val
            sess.commit()
    finally:
        sess.close()
        eng.dispose()
    return val


def upsert_league(
    *,
    league_code: str,
    display_name: str,
    trophy_scale: float,
    cl_scale: float,
    competitiveness: float = 1.0,
) -> None:
    eng = _engine()
    Session = sessionmaker(bind=eng)
    sess = Session()
    try:
        code = league_code.strip().lower()
        row = sess.get(LeagueRow, code)
        if row is None:
            row = LeagueRow(league_code=code)
            sess.add(row)
        row.display_name = display_name
        row.trophy_scale = float(trophy_scale)
        row.cl_scale = float(cl_scale)
        row.competitiveness = float(competitiveness)
        sess.commit()
    finally:
        sess.close()
        eng.dispose()


def upsert_team(
    *,
    name: str,
    league_code: str,
    manager: str | None = None,
    in_cl_pool: bool = False,
    trophy_tier: int = 3,
    fifa_stars: float | None = None,
    active: bool = True,
) -> int:
    eng = _engine()
    Session = sessionmaker(bind=eng)
    sess = Session()
    try:
        nn = _norm_name(name)
        row = sess.query(TeamRow).filter(TeamRow.name_norm == nn).first()
        if row is None:
            row = TeamRow(name=name.strip(), name_norm=nn)
            sess.add(row)
        row.name = name.strip()
        row.league_code = league_code.strip().lower()
        row.manager = (manager or "").strip().lower() or None
        row.in_cl_pool = 1 if in_cl_pool else 0
        row.trophy_tier = max(1, min(5, int(trophy_tier)))
        row.fifa_stars = float(fifa_stars) if fifa_stars is not None else None
        row.active = 1 if active else 0
        sess.commit()
        return int(row.team_id)
    finally:
        sess.close()
        eng.dispose()


def count_teams() -> int:
    eng = _engine()
    try:
        with eng.connect() as conn:
            n = conn.execute(text("SELECT COUNT(*) FROM teams")).scalar()
            return int(n or 0)
    finally:
        eng.dispose()
