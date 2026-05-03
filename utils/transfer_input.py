# -*- coding: utf-8 -*-
"""Нормализация ввода для трансферов: регистр не важен — приводим к виду БД."""
from __future__ import annotations

from typing import Iterable

from utils.player_transfer import _norm_cmp, normalize_player_name_for_db


def normalize_position(position: str) -> str:
    return (position or "").strip().upper()


def normalize_display_name(name: str) -> str:
    return normalize_player_name_for_db(name)


def normalize_nation(nation: str) -> str:
    return (nation or "").strip()


def _team_name_as_in_db(team: str) -> str:
    if (team or "").strip().casefold() == "цска":
        return "Цска"
    return (team or "").strip()


def distinct_teams_from_league(session_league) -> list[str]:
    from data.defender import Defender
    from data.forward import Forward
    from data.goalkeeper import Goalkeeper
    from data.midfielder import Midfielder

    seen: set[str] = set()
    out: list[str] = []
    for Cls in (Forward, Midfielder, Defender, Goalkeeper):
        for r in session_league.query(Cls).all():
            tm = (getattr(r, "team", None) or "").strip()
            if tm and tm not in seen:
                seen.add(tm)
                out.append(tm)
    return out


def resolve_team_name(user_team: str, session_league) -> str | None:
    """
    Находит точное имя клуба в БД по безрегистровому совпадению (casefold).
    """
    raw = (user_team or "").strip()
    if len(raw) < 2:
        return None
    special = _team_name_as_in_db(raw)
    want = _norm_cmp(special)
    for tm in distinct_teams_from_league(session_league):
        if _norm_cmp(tm) == want:
            return tm
    return None


def validate_batch_parts(total: int, parts: Iterable[int]) -> tuple[bool, str | None]:
    """Сумма частей должна равняться total; каждая часть >= 0; total <= 5."""
    ps = list(parts)
    if total < 1 or total > 5:
        return False, "Общее число трансферов должно быть от 1 до 5."
    s = sum(ps)
    if s != total:
        return False, (
            f"Сумма трансферов по источникам ({s}) должна совпадать с объявленным "
            f"числом ({total}). Допустимые разбиения, например: {total}+0, {total-1}+1, …"
        )
    if any(p < 0 for p in ps):
        return False, "Отрицательные числа недопустимы."
    return True, None
