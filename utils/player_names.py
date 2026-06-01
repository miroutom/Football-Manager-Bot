# -*- coding: utf-8 -*-
"""
Имя и фамилия в БД: ``name`` — имя, ``surname`` — фамилия.

Отображение: «Л. Мартинез». Поиск: полное имя, имя, фамилия, «И. Фамилия».
"""
from __future__ import annotations

import re
from typing import Any, Iterator

from utils.player_transfer import _filter_team, _norm_cmp, normalize_player_name_for_db

_ALL_PLAYER_CLASSES: tuple[type, ...] | None = None


def _all_classes() -> tuple[type, ...]:
    global _ALL_PLAYER_CLASSES
    if _ALL_PLAYER_CLASSES is None:
        from data.defender import Defender
        from data.forward import Forward
        from data.goalkeeper import Goalkeeper
        from data.midfielder import Midfielder

        _ALL_PLAYER_CLASSES = (Forward, Midfielder, Defender, Goalkeeper)
    return _ALL_PLAYER_CLASSES


def player_first_name(row: Any) -> str:
    return (getattr(row, "name", None) or "").strip().title()


def player_surname(row: Any) -> str:
    s = (getattr(row, "surname", None) or "").strip()
    if s:
        return s.title()
    return (getattr(row, "name", None) or "").strip().title()


def player_short_display(row: Any) -> str:
    """Краткая подпись: «Л. Мартинез»."""
    fn = player_first_name(row)
    sn = player_surname(row)
    if not sn:
        return ""
    if fn:
        return f"{fn[0].upper()}. {sn}"
    return sn


def player_display_name(row: Any) -> str:
    return player_short_display(row)


def player_full_name(row: Any) -> str:
    fn = player_first_name(row)
    sn = player_surname(row)
    if fn and _norm_cmp(fn) != _norm_cmp(sn):
        return f"{fn} {sn}"
    return sn


def player_stats_identity_token(row: Any) -> str:
    """
    Стабильный идентификатор для слияния сезонов и топ-100.

    Фамилия (``surname``), если есть; иначе ``name`` — чтобы в season_1 было
    «Хаверц», а в season_2 «Кай» + «Хаверц» попали в одну строку.
    """
    sn = (getattr(row, "surname", None) or "").strip()
    if sn:
        return sn
    return (getattr(row, "name", None) or "").strip()


def _parse_initial_surname_query(query: str) -> tuple[str | None, str | None]:
    """«Л. Мартинез», «Л Мартинез», «л.мартинез» → (буква, фамилия)."""
    s = (query or "").strip()
    if not s:
        return None, None
    m = re.match(r"^([^\s.])\.\s*(.+)$", s, re.UNICODE)
    if m:
        return m.group(1).casefold(), _norm_cmp(m.group(2))
    parts = s.split()
    if len(parts) == 2 and len(parts[0].rstrip(".")) == 1:
        return parts[0].rstrip(".").casefold(), _norm_cmp(parts[1])
    return None, None


def player_matches_query(row: Any, query: str) -> bool:
    q_raw = (query or "").strip()
    if not q_raw:
        return False
    qn = _norm_cmp(q_raw)
    fn = _norm_cmp(player_first_name(row))
    sn = _norm_cmp(player_surname(row))
    full = _norm_cmp(player_full_name(row))
    short = _norm_cmp(player_short_display(row))
    short_nd = _norm_cmp(player_short_display(row).replace(".", ""))

    if qn in (full, fn, sn, short, short_nd):
        return True

    init, sn_q = _parse_initial_surname_query(q_raw)
    if init is not None and sn_q:
        return bool(fn) and fn[0:1].casefold() == init and sn == sn_q

    if " " not in q_raw and "." not in q_raw:
        return qn == fn or qn == sn

    return qn == full


def _row_key(row: Any) -> tuple[str, int]:
    return (type(row).__name__, int(getattr(row, "id", 0) or 0))


def iter_team_players(
    session: Any, team: str, *, include_left: bool = False
) -> Iterator[Any]:
    team_t = (team or "").strip()
    for Cls in _all_classes():
        for r in session.query(Cls).filter(_filter_team(Cls, team_t, include_left=include_left)).all():
            yield r


def find_players_matching_query(
    session: Any,
    team: str,
    query: str,
    *,
    include_left: bool = False,
) -> list[Any]:
    seen: set[tuple[str, int]] = set()
    out: list[Any] = []
    for r in iter_team_players(session, team, include_left=include_left):
        key = _row_key(r)
        if key in seen:
            continue
        if player_matches_query(r, query):
            seen.add(key)
            out.append(r)
    return out


def _collapse_same_person_position_duplicates(players: list[Any]) -> list[Any]:
    """Две строки одного человека (разные позиции в заявке) → одна с max matches."""
    if len(players) <= 1:
        return players
    full_keys = {_norm_cmp(player_full_name(p)) for p in players}
    if len(full_keys) != 1:
        return players
    pick = max(
        players,
        key=lambda p: (
            int(getattr(p, "matches", 0) or 0),
            int(getattr(p, "overall", 0) or 0),
            int(getattr(p, "id", 0) or 0),
        ),
    )
    return [pick]


def format_ambiguity_message(team: str, query: str, players: list[Any]) -> str:
    labels = [f"{player_display_name(p)} · {p.position}" for p in players]
    n = len(players)
    q = (query or "").strip()
    team_t = (team or "").strip().title()
    if " " not in q and "." not in q:
        return (
            f"В команде {team_t} {n} игрока с фамилией «{q.title()}». "
            f"Уточните: {', '.join(labels)}"
        )
    return (
        f"В команде {team_t} {n} совпадения на «{q}». "
        f"Уточните: {', '.join(labels)}"
    )


def resolve_player_query_in_team(
    session: Any,
    team: str,
    query: str,
    *,
    include_left: bool = False,
    position: str | None = None,
) -> tuple[Any | None, str]:
    """
    Однозначный игрок в клубе по вводу или текст ошибки / уточнения.
    """
    team_t = (team or "").strip().title()
    q = (query or "").strip()
    if not q:
        return None, "Пустая строка."

    matches = find_players_matching_query(
        session, team_t, q, include_left=include_left
    )
    if position:
        want_p = _norm_cmp(position)
        matches = [r for r in matches if _norm_cmp(r.position or "") == want_p]
    else:
        matches = _collapse_same_person_position_duplicates(matches)

    if not matches:
        return None, f"Не найден в БД «{q}» ({team_t})"
    if len(matches) == 1:
        return matches[0], ""
    return None, format_ambiguity_message(team_t, q, matches)


def player_row_matches_query(row: Any, query: str) -> bool:
    """Совместимость: тот же критерий, что и ``find_players_matching_query``."""
    return player_matches_query(row, query)


def parse_name_surname_input(raw: str) -> tuple[str, str]:
    """Ввод «Имя Фамилия» или одно слово (только фамилия) → (first_name, surname)."""
    s = normalize_player_name_for_db(raw)
    if not s:
        return "", ""
    parts = s.split()
    if len(parts) == 1:
        return "", parts[0]
    return " ".join(parts[:-1]), parts[-1]


def apply_parsed_names_to_row(row: Any, first_name: str, surname: str) -> None:
    row.name = (first_name or "").strip().title() or ""
    row.surname = (surname or "").strip().title() or player_surname(row)
