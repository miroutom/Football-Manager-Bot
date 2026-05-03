# -*- coding: utf-8 -*-
"""
Участники ЛЧ (подстрока в нормализованном названии команды из squads_canonical).
Ключи roman / lika — для учёта чьих игроков в какой «корзине»; для отбора в БД ЛЧ объединяются.
"""
from __future__ import annotations

from config.squad_team_aliases import canonical_team_name

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


def _norm(s: str) -> str:
    return s.lower().strip().replace("ё", "е")


def cl_match_keywords() -> list[str]:
    """Все подстроки для проверки; длинные раньше — чтобы «реал сосьедад» не перебивалось коротким «реал» лишним образом (оба матчатся)."""
    out: list[str] = []
    for v in CL_PARTICIPANTS.values():
        out.extend(v)
    return sorted(out, key=len, reverse=True)


def team_matches_champions_league(team: str) -> bool:
    """True, если команда из канона попадает под список участников ЛЧ."""
    t = _norm(canonical_team_name(team))
    for kw in cl_match_keywords():
        if _norm(kw) in t:
            return True
    return False
