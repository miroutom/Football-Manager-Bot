# -*- coding: utf-8 -*-
"""
Подписи слотов календаря: номер тура для кнопок в боте.

Для национальных лиг: **следующий тур хозяев** = сколько матчей команда уже сыграла
в этом чемпионате (по журналу) + 1. Для ЛЧ в подписи тур не показываем.

Дисквалификации считают тур **команды игрока** (``team_round_for_fixture`` /
``team_display_round``), а не всегда хозяев — у соперников номера матчей могут
различаться.
"""
from __future__ import annotations

_NATIONAL = frozenset({"rpl", "eng", "esp", "ger", "ita"})


def is_national_league(league_code: str) -> bool:
    return (league_code or "").strip().lower() in _NATIONAL


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


def _clamp_round(n: int) -> int:
    if n < 1:
        return 1
    if n > 14:
        return 14
    return n


def team_display_round(team: str, league_code: str) -> int | None:
    """Следующий тур команды в чемпионате (сыграно + 1), 1–14."""
    lc = (league_code or "").strip().lower()
    if lc not in _NATIONAL:
        return None
    return _clamp_round(count_team_league_matches_played(team, lc) + 1)


def home_display_round(home: str, league_code: str) -> int | None:
    """
    Тур для подписи кнопки: следующий у **домашней** команды в чемпионате.

    ЛЧ и неизвестные коды → ``None`` (в UI без «тN»).
    """
    return team_display_round(home, league_code)


def team_round_for_fixture(
    team: str,
    home: str,
    away: str,
    league_code: str,
) -> int | None:
    """
    Номер **этого** матча для ``team`` в нац. лиге (1–14).

    Если матч уже в журнале — ``played`` (матч учтён); иначе ``played + 1``.
    """
    lc = (league_code or "").strip().lower()
    if lc not in _NATIONAL:
        return None
    played = count_team_league_matches_played(team, lc)
    try:
        from match_results import is_match_played

        if is_match_played(home, away, lc):
            return _clamp_round(played) if played > 0 else 1
    except Exception:
        pass
    return _clamp_round(played + 1)
