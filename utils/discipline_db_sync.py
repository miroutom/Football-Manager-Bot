# -*- coding: utf-8 -*-
"""
Синхронизация дисциплины из ``data/player_discipline.json`` в SQLite сезона (лига / ЛЧ).

- **ЖК (накопительно к 4):** для ``yellow_cycle`` выставляет ``yellow_cards = max(текущее, count)``
  на строке клуба — цикл 0–3, **не** полная карьерная сумма. История жк/кк: ввод матча
  (``_bump_db_cards``) или ``scripts/restore_season2_cards_history.py``. После смены сезона цикл
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
            # История в БД не уменьшаем: count в JSON — только цикл 0–3 на клуб.
            player.yellow_cards = max(int(getattr(player, "yellow_cards", 0) or 0), c)
            touched = True
        if touched:
            sess.commit()

    return log
