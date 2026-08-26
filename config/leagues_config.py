# -*- coding: utf-8 -*-
"""Конфигурация лиг, команд и менеджеров (Roman/Lika) для ЛЧ.

Roman = синие, Lika = оранжевые.
По **8** команд в каждой национальной лиге (по 4 от каждого менеджера).
В ЛЧ — 30 команд: по 15 от каждого менеджера (топ по силе из пула, см. ``select_cl_teams``).
"""
from __future__ import annotations

# Россия — РПЛ (8 команд)
rpl = [
    "цска", "зенит", "краснодар", "локомотив", "спартак",
    "динамо", "крылья советов", "урал",
]

# Англия — АПЛ (8 команд)
england = [
    "сити", "мю", "ливерпуль", "арсенал", "астон вилла", "челси",
    "тоттенхэм", "ньюкасл",
]

# Испания — Ла Лига (8 команд)
spain = [
    "реал", "барселона", "атлетико", "атлетик", "реал сосьедад", "севилья",
    "жирона", "бетис",
]

# Италия — Серия А (8 команд)
italy = [
    "интер", "милан", "ювентус", "наполи", "аталанта", "фиорентина",
    "лацио", "рома",
]

# Германия — Бундеслига (8 команд)
germany = [
    "бавария", "дортмунд", "байер", "лейпциг", "франкфурт",
    "боруссия м", "вольфсбург", "хоффенхайм",
]

# Менеджеры: Roman (синие) / Lika (оранжевые) — по 4 команды в каждой лиге
MANAGER_TEAMS = {
    "roman": [
        "цска", "краснодар", "спартак", "урал",  # Россия
        "мю", "ливерпуль", "астон вилла", "челси",  # Англия
        "реал", "атлетико", "бетис", "жирона",  # Испания
        "милан", "наполи", "фиорентина", "рома",  # Италия
        "бавария", "байер", "франкфурт", "вольфсбург",  # Германия
    ],
    "lika": [
        "зенит", "локомотив", "динамо", "крылья советов",  # Россия
        "сити", "арсенал", "тоттенхэм", "ньюкасл",  # Англия
        "барселона", "атлетик", "севилья", "реал сосьедад",  # Испания
        "интер", "ювентус", "аталанта", "лацио",  # Италия
        "дортмунд", "лейпциг", "боруссия м", "хоффенхайм",  # Германия
    ],
}

# Лига Чемпионов — фиксированный список 30 (Roman + Lika); динамика — ``cl_participants_dynamic.txt``
CL_PARTICIPANTS = {
    "roman": [
        "мю",
        "ливерпуль",
        "реал",
        "атлетико",
        "милан",
        "челси",
        "фиорентина",
        "рома",
        "франкфурт",
        "спартак",
        "наполи",
        "бавария",
        "байер",
        "цска",
        "краснодар",
    ],
    "lika": [
        "сити",
        "арсенал",
        "барселона",
        "атлетик",
        "интер",
        "ювентус",
        "дортмунд",
        "лейпциг",
        "зенит",
        "локомотив",
        "тоттенхэм",
        "реал сосьедад",
        "аталанта",
        "лацио",
        "динамо",
    ],
}

# Коды лиг для расписания
LEAGUE_CODES = {
    "rpl": "rpl",
    "eng": "eng",
    "esp": "esp",
    "ita": "ita",
    "ger": "ger",
    "cl": "cl",
}

# Все лиги с командами
ALL_LEAGUES = {
    "rpl": {"name": "РПЛ", "teams": rpl},
    "eng": {"name": "АПЛ", "teams": england},
    "esp": {"name": "Ла Лига", "teams": spain},
    "ita": {"name": "Серия А", "teams": italy},
    "ger": {"name": "Бундеслига", "teams": germany},
}


def _norm_club_token(s: str) -> str:
    return " ".join((s or "").strip().lower().split())


def is_rpl_club(team_display: str) -> bool:
    """Клуб из списка РПЛ (``rpl`` или реестр команд)."""
    n = _norm_club_token(team_display)
    if not n:
        return False
    for c in rpl:
        if _norm_club_token(c) == n:
            return True
    try:
        from utils.team_registry import league_code_for_team

        return (league_code_for_team(team_display) or "").strip().lower() == "rpl"
    except Exception:
        return False


def manager_side_for_team(team_display: str) -> str | None:
    """
    К какому менеджеру относится клуб (Roman / Lika), по ``MANAGER_TEAMS``.
    Для сборных ЧМ — по ``data/wc_tournament.json`` → managers (Roman/Lika).
    Имя как в расписании или в конфиге — без учёта регистра.
    """
    n = _norm_club_token(team_display)
    if not n:
        return None
    for side, clubs in MANAGER_TEAMS.items():
        for c in clubs:
            if _norm_club_token(c) == n:
                return side
    # сборные ЧМ
    try:
        from utils.wc_tournament import load_tournament

        mgr = (load_tournament().get("managers") or {})
        for side_key, label in (("Roman", "roman"), ("Lika", "lika")):
            for nation in mgr.get(side_key) or []:
                if _norm_club_token(str(nation)) == n:
                    return label
    except Exception:
        pass
    return None


def manager_session_label(home: str, away: str) -> str | None:
    """
    Подпись к матчу: оба клуба одного менеджера — «Симуляция», разные — «Игра».
    Любой матч с клубом РПЛ — тоже «Симуляция» (лига и ЛЧ).
    Если клуб не найден в разбиении — None.
    """
    if is_rpl_club(home) or is_rpl_club(away):
        return "Симуляция"
    a = manager_side_for_team(home)
    b = manager_side_for_team(away)
    if a is None or b is None:
        return None
    return "Симуляция" if a == b else "Игра"


def match_journal_entry_type(home: str, away: str) -> str:
    """``entry_type`` для ``match_results``: ``simulation`` или ``play``."""
    return "simulation" if manager_session_label(home, away) == "Симуляция" else "play"
