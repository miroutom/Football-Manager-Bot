# -*- coding: utf-8 -*-
"""Создание db/free_agents.db и первичная заливка из data/free_agents.tsv."""
from __future__ import annotations

import csv
import logging
import os
from pathlib import Path

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from data.free_agent import FreeAgent
from utils.free_agent_catalog_name import catalog_display_name_from_sheet_full
from utils.season_paths import PROJECT_ROOT, get_free_agents_db_path
from utils.transfer_input import normalize_nation, normalize_position

logger = logging.getLogger(__name__)

_TSV = Path(PROJECT_ROOT) / "data" / "free_agents.tsv"


def migrate_free_agents_db() -> None:
    path = get_free_agents_db_path()
    os.makedirs(os.path.dirname(path), exist_ok=True)
    engine = create_engine(f"sqlite:///{path}")
    FreeAgent.__table__.create(engine, checkfirst=True)
    Sess = sessionmaker(bind=engine)
    sess = Sess()
    try:
        if sess.query(FreeAgent).count() > 0:
            return
        if not _TSV.is_file():
            logger.warning("Нет файла %s — free_agents.db создана пустой.", _TSV)
            return
        with _TSV.open(encoding="utf-8", newline="") as f:
            rdr = csv.DictReader(f, delimiter="\t")
            for row in rdr:
                full = (row.get("sheet_full") or "").strip()
                pos = normalize_position(row.get("position") or "")
                ovr = int(row.get("overall") or 0)
                nat_raw = (row.get("nation") or "").strip()
                nation = normalize_nation(nat_raw) if nat_raw else None
                name = catalog_display_name_from_sheet_full(full)
                if not name or not pos:
                    continue
                sess.add(
                    FreeAgent(
                        name=name,
                        position=pos,
                        overall=max(1, min(99, ovr)),
                        nation=nation,
                    )
                )
        sess.commit()
        logger.info("Залито свободных агентов: %s", sess.query(FreeAgent).count())
    except Exception:
        sess.rollback()
        logger.exception("migrate_free_agents_db")
        raise
    finally:
        sess.close()
        engine.dispose()
