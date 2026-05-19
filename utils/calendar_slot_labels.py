# -*- coding: utf-8 -*-
"""
Подписи слотов календаря: номер тура для кнопок в боте.

Для национальных лиг: **следующий тур хозяев** = сколько матчей команда уже сыграла
в этом чемпионате (по журналу) + 1. Для ЛЧ в подписи тур не показываем.

Отдельно от ``find_fixture_round`` в ``player_discipline`` (официальный тур пары
для дисквала после карточки).
"""
from __future__ import annotations

_NATIONAL = frozenset({"rpl", "eng", "esp", "ger", "ita"})


def count_team_league_matches_played(team: str, league_code: str) -> int:
    """Сколько матчей команда уже сыграла в лиге (дома или в гостях) по ``match_results``."""
    from match_results import _norm, load_records_and_keys

    tn = _norm(team)
    lc = (league_code or "").strip().lower()
    if lc not in _NATIONAL:
        return 0
    records, _ = load_records_and_keys()
    n = 0
    for r in records:
        if (r.get("league") or "").strip().lower() != lc:
            continue
        h = _norm(r.get("home") or "")
        a = _norm(r.get("away") or "")
        if h == tn or a == tn:
            n += 1
    return n


def home_display_tour(home: str, league_code: str) -> int | None:
    """
    Тур для подписи кнопки: следующий у **домашней** команды в чемпионате.

    ЛЧ и неизвестные коды → ``None`` (в UI без «тN»).
    """
    lc = (league_code or "").strip().lower()
    if lc not in _NATIONAL:
        return None
    played = count_team_league_matches_played(home, lc)
    nxt = played + 1
    if nxt < 1:
        return 1
    if nxt > 14:
        return 14
    return nxt
