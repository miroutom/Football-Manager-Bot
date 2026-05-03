# -*- coding: utf-8 -*-
"""Свободные агенты: справочник без матчевой статистики (отдельная БД)."""
from __future__ import annotations

from sqlalchemy import Column, Integer, String

from utils.utils import Base


class FreeAgent(Base):
    __tablename__ = "free_agents"

    id = Column(Integer, primary_key=True, autoincrement=True)
    name = Column(String, nullable=False)
    position = Column(String, nullable=False)
    overall = Column(Integer, nullable=False)
    nation = Column(String, nullable=True)
