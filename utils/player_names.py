# -*- coding: utf-8 -*-
"""
Имя игрока — одно поле ``name`` (полное имя или прозвище одним словом).

В боте и стате показывается ``name`` как есть, без сокращения до инициала.
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


def _name_parts(name: str) -> tuple[str, str]:
    """(всё кроме последнего слова, последнее слово) или ('', единственное слово)."""
    s = (name or "").strip()
    if not s:
        return "", ""
    parts = s.split()
    if len(parts) == 1:
        return "", parts[0]
    return " ".join(parts[:-1]), parts[-1]


def player_first_name(row: Any) -> str:
    fn, _ = _name_parts((getattr(row, "name", None) or "").strip())
    return fn.title() if fn else ""


def player_surname(row: Any) -> str:
    """Последнее слово ``name`` (для поиска/алиасов; отдельной колонки нет)."""
    _, sn = _name_parts((getattr(row, "name", None) or "").strip())
    return sn.title() if sn else (getattr(row, "name", None) or "").strip().title()


def player_short_display(row: Any) -> str:
    """Полное имя из ``name`` (без «К. Муани»)."""
    return player_full_name(row)


def player_display_name(row: Any) -> str:
    return player_full_name(row)


def player_full_name(row: Any) -> str:
    return (getattr(row, "name", None) or "").strip().title()


def player_stats_identity_token(row: Any) -> str:
    """Токен для слияния сезонов: последнее слово ``name`` или всё имя."""
    _, sn = _name_parts((getattr(row, "name", None) or "").strip())
    return sn or (getattr(row, "name", None) or "").strip()


def player_name_identity_token(name: str) -> str:
    """Токен идентичности по строке имени (без ORM-строки)."""
    _, sn = _name_parts((name or "").strip())
    return sn or (name or "").strip()


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
    raw = (getattr(row, "name", None) or "").strip()
    fn, sn = _name_parts(raw)
    fn_n = _norm_cmp(fn)
    sn_n = _norm_cmp(sn)
    full = _norm_cmp(raw)
    short = _norm_cmp(player_short_display(row))
    short_nd = _norm_cmp(player_short_display(row).replace(".", ""))

    if qn in (full, fn_n, sn_n, short, short_nd):
        return True

    # nickname по person_id
    try:
        from utils.person_registry import row_person_id
        from utils.player_nicknames import get_nickname, resolve_person_id_by_nickname

        pid = row_person_id(row)
        nick = get_nickname(pid)
        if nick and _norm_cmp(nick) == qn:
            return True
        resolved = resolve_person_id_by_nickname(q_raw)
        if resolved is not None and pid is not None and int(resolved) == int(pid):
            return True
    except Exception:
        pass

    init, sn_q = _parse_initial_surname_query(q_raw)
    if init is not None and sn_q:
        return bool(fn) and fn[0:1].casefold() == init and sn_n == sn_q

    if " " not in q_raw and "." not in q_raw:
        return qn == fn_n or qn == sn_n

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
    if len(players) <= 1:
        return players
    full_keys = {_norm_cmp((getattr(p, "name", None) or "").strip()) for p in players}
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
            f"В команде {team_t} {n} игрока с именем «{q.title()}». "
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
    return player_matches_query(row, query)


def parse_name_surname_input(raw: str) -> tuple[str, str]:
    """Совместимость: ввод → (не используется, полное имя); полное имя для ``name``."""
    s = normalize_player_name_for_db(raw)
    return "", s


def apply_parsed_names_to_row(row: Any, first_name: str, surname: str) -> None:
    """Записать полное имя в одно поле ``name``."""
    if first_name and surname:
        row.name = f"{first_name.strip().title()} {surname.strip().title()}"
    elif surname:
        row.name = surname.strip().title()
    elif first_name:
        row.name = first_name.strip().title()
