# -*- coding: utf-8 -*-
"""
Имя и фамилия в БД: ``name`` — имя, ``surname`` — фамилия (то, что видно в боте и отчётах).
"""
from __future__ import annotations

from typing import Any

from utils.player_transfer import _norm_cmp, normalize_player_name_for_db


def player_first_name(row: Any) -> str:
    return (getattr(row, "name", None) or "").strip().title()


def player_surname(row: Any) -> str:
    s = (getattr(row, "surname", None) or "").strip()
    if s:
        return s.title()
    # Пока не заполнили surname — показываем прежнее поле name
    return (getattr(row, "name", None) or "").strip().title()


def player_display_name(row: Any) -> str:
    """Подпись в боте, голеадорах, стата матча."""
    return player_surname(row)


def player_full_name(row: Any) -> str:
    fn = player_first_name(row)
    sn = player_surname(row)
    if fn and _norm_cmp(fn) != _norm_cmp(sn):
        return f"{fn} {sn}"
    return sn


def player_row_matches_query(row: Any, query: str) -> bool:
    """Поиск по вводу: имя, фамилия или полное."""
    q = _norm_cmp(query)
    if not q:
        return False
    for label in (
        player_first_name(row),
        player_surname(row),
        player_full_name(row),
        (getattr(row, "name", None) or "").strip(),
    ):
        if label and _norm_cmp(label) == q:
            return True
    return False


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
