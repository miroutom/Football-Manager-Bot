# -*- coding: utf-8 -*-
"""Создание db/free_agents.db, первичная заливка из data/free_agents.tsv, синхронизация с составами.

После заливки: строки СА, для которых в ``common.db`` выбранного сезона есть игрок с тем же
именем и позицией в **клубе** (не ``Free Agent``), удаляются. Остальные остаются.

Дополнительно — вычёркивание по списку ``_ALREADY_SIGNED``. Из непустой БД не подмешивать TSV целиком.
"""
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
from utils.season_paths import (
    PROJECT_ROOT,
    get_common_db_path_for_season,
    get_free_agents_db_path,
)
from utils.transfer_input import normalize_nation, normalize_position

logger = logging.getLogger(__name__)

_TSV = Path(PROJECT_ROOT) / "data" / "free_agents.tsv"

# Обрезка по объединённой статистике сезона (имя+позиция совпадают с игроком не из СА в common).
FA_PRUNE_SOURCE_SEASON = 2

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
    ("Суарес", "ФРВ"),
    ("Витинья", "ЦП"),
    ("Ханко", "ЦЗ"),
    ("Менди", "ВРТ"),
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


def _norm_team_free_agent(team: str) -> bool:
    return _norm_cmp(team or "") == _norm_cmp("Free Agent")


def _collect_club_player_keys_from_common(common_path: str) -> set[tuple[str, str]]:
    """
    Ключи (имя, позиция) игроков из common, которые числятся в клубе, не в «Free Agent».
    """
    from data.defender import Defender
    from data.forward import Forward
    from data.goalkeeper import Goalkeeper
    from data.midfielder import Midfielder

    out: set[tuple[str, str]] = set()
    if not os.path.isfile(common_path):
        return out
    eng = create_engine(f"sqlite:///{common_path}")
    Sess = sessionmaker(bind=eng)
    cs = Sess()
    try:
        for Cls in (Forward, Midfielder, Defender, Goalkeeper):
            for r in cs.query(Cls).all():
                if _norm_team_free_agent(getattr(r, "team", "") or ""):
                    continue
                out.add(
                    (
                        _norm_cmp(r.name or ""),
                        _norm_cmp(r.position or ""),
                    )
                )
    finally:
        cs.close()
        eng.dispose()
    return out


def _prune_free_agents_present_in_season_common(sess, season_num: int) -> int:
    common_path = get_common_db_path_for_season(season_num)
    if not os.path.isfile(common_path):
        logger.debug(
            "Нет common сезона %s (%s) — пропуск синхронизации СА с составами.",
            season_num,
            common_path,
        )
        return 0
    keys = _collect_club_player_keys_from_common(common_path)
    if not keys:
        return 0
    removed = 0
    for r in list(sess.query(FreeAgent).all()):
        k = (_norm_cmp(r.name or ""), _norm_cmp(r.position or ""))
        if k in keys:
            sess.delete(r)
            removed += 1
    if removed:
        logger.info(
            "Удалено из справочника СА (есть в клубе в common сезона %s): %s",
            season_num,
            removed,
        )
    return removed


def _iter_tsv_free_agent_rows():
    """Строки из TSV: имя в БД, позиция, overall, нация."""
    if not _TSV.is_file():
        return
    with _TSV.open(encoding="utf-8", newline="") as f:
        rdr = csv.DictReader(f, delimiter="\t")
        for row in rdr:
            full = (row.get("sheet_full") or "").strip()
            pos = normalize_position(row.get("position") or "")
            try:
                ovr = int(row.get("overall") or 0)
            except (TypeError, ValueError):
                ovr = 0
            nat_raw = (row.get("nation") or "").strip()
            nation = normalize_nation(nat_raw) if nat_raw else None
            name = catalog_display_name_from_sheet_full(full)
            if not name or not pos:
                continue
            yield name, pos, max(1, min(99, ovr)), nation


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
                n0 = 0
                for name, pos, ovr, nation in _iter_tsv_free_agent_rows():
                    sess.add(
                        FreeAgent(
                            name=name,
                            position=pos,
                            overall=ovr,
                            nation=nation,
                        )
                    )
                    n0 += 1
                logger.info("Залито свободных агентов: %s", n0)

        # Не дозаливать из TSV в непустую БД: после подписания игрок удаляется из
        # free_agents.db — «отсутствующая» строка означает «уже в клубе», а не
        # «надо добавить из шаблона». Новые СА — upsert_free_agent_catalog или
        # пересоздать db с нуля из актуального TSV.

        _prune_free_agents_present_in_season_common(sess, FA_PRUNE_SOURCE_SEASON)

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
