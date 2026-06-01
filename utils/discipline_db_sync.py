# -*- coding: utf-8 -*-
"""
Синхронизация дисциплины из ``data/player_discipline.json`` в SQLite сезона (лига / ЛЧ).

- **ЖК (накопительно к 4):** для каждой записи ``yellow_cycle`` **перезаписывает** ``yellow_cards = count``
  в БД — это только счётчик цикла (0–3), **не** карьерная сумма жк. Для истории жк/кк в БД
  используйте ввод статы матча (``_bump_db_cards``), не этот sync. После смены сезона цикл
  сбрасывается в JSON; колонки ``yellow_cards``/``red_cards`` в SQLite не обнуляются при
  ``finalize_season``.
- **КК / травмы:** в JSON нет отдельного поля «число кк»; травмы хранятся только в JSON
  (``injuries``) — в таблицы не пишем. Дисквалы по ``suspensions`` тоже остаются в JSON.
"""
from __future__ import annotations

from typing import Any

from player_stats import find_player_by_name, get_session
from utils.player_discipline import _load


def sync_yellow_cards_from_discipline_json() -> list[str]:
    """
    Прочитать ``player_discipline.json`` и обновить ``yellow_cards`` в активных league/cl БД.

    Возвращает короткий журнал (предупреждения о пропусках).
    """
    st: dict[str, Any] = _load()
    log: list[str] = []

    for tkey in ("league", "cl"):
        sess = get_session(tkey)
        touched = False
        for row in st.get("yellow_cycle", []):
            scope = (row.get("scope") or "league").strip().lower()
            want = "cl" if scope == "cl" else "league"
            if want != tkey:
                continue
            name = (row.get("name") or "").strip().title()
            team = (row.get("team") or "").strip().title()
            c = int(row.get("count") or 0)
            player, _ = find_player_by_name(sess, name, team)
            if player is None or not hasattr(player, "yellow_cards"):
                log.append(f"{tkey}: не найден {name} ({team})")
                continue
            player.yellow_cards = c
            touched = True
        if touched:
            sess.commit()

    return log
