# -*- coding: utf-8 -*-
"""Создание db/free_agents.db, заливка из data/free_agents.tsv, вычёркивание уже подписанных."""
from __future__ import annotations

import csv
import logging
import os
from pathlib import Path

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from data.free_agent import FreeAgent
from utils.free_agent_catalog_name import catalog_display_name_from_sheet_full
from utils.player_transfer import _norm_cmp
from utils.season_paths import PROJECT_ROOT, get_free_agents_db_path
from utils.transfer_input import normalize_nation, normalize_position

logger = logging.getLogger(__name__)

_TSV = Path(PROJECT_ROOT) / "data" / "free_agents.tsv"

# Уже оформлены в клубы — убрать из справочника (имя как в БД после catalog_display_name).
_ALREADY_SIGNED: tuple[tuple[str, str], ...] = (
    ("Гиббс-Уайт", "ЦАП"),
    ("Тадич", "ЛФА"),
    ("Отаменди", "ЦЗ"),
    ("Малком", "ЛФА"),
    ("Шмейхель", "ВРТ"),
    ("Алдервейрельд", "ЦЗ"),
    ("Аурснес", "ПЗ"),
    ("Фирмино", "ФРВ"),
    ("Ибаньес", "ЦЗ"),
)


def _prune_already_signed(sess) -> int:
    removed = 0
    for want_name, want_pos in _ALREADY_SIGNED:
        wp = normalize_position(want_pos)
        for r in list(sess.query(FreeAgent).all()):
            if _norm_cmp(r.name or "") != _norm_cmp(want_name):
                continue
            if _norm_cmp(r.position or "") != _norm_cmp(wp):
                continue
            sess.delete(r)
            removed += 1
            break
    return removed


def migrate_free_agents_db() -> None:
    path = get_free_agents_db_path()
    os.makedirs(os.path.dirname(path), exist_ok=True)
    engine = create_engine(f"sqlite:///{path}")
    FreeAgent.__table__.create(engine, checkfirst=True)
    Sess = sessionmaker(bind=engine)
    sess = Sess()
    try:
        if sess.query(FreeAgent).count() == 0:
            if not _TSV.is_file():
                logger.warning("Нет файла %s — free_agents.db пустая.", _TSV)
            else:
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
                logger.info("Залито свободных агентов: %s", sess.query(FreeAgent).count())

        removed = _prune_already_signed(sess)
        if removed:
            logger.info("Удалено из справочника СА (уже в командах): %s", removed)
        sess.commit()
    except Exception:
        sess.rollback()
        logger.exception("migrate_free_agents_db")
        raise
    finally:
        sess.close()
        engine.dispose()
        try:
            from utils.free_agents_catalog import invalidate_free_agents_engine

            invalidate_free_agents_engine()
        except Exception:
            pass
