# -*- coding: utf-8 -*-
"""
Никнеймы игроков по ``person_id`` (для короткого ввода статы).

Файл: ``data/player_nicknames.json``::

    {
      "version": 1,
      "by_person_id": { "142": "муани", ... }
    }
"""
from __future__ import annotations

import json
import os
import re
from typing import Any

from utils.utils import PROJECT_ROOT

_PATH = os.path.join(PROJECT_ROOT, "data", "player_nicknames.json")

# Частицы / префиксы составных фамилий (кириллица + латиница).
_PARTICLES = frozenset(
    {
        "ван",
        "дер",
        "де",
        "ди",
        "да",
        "дос",
        "ду",
        "лас",
        "лос",
        "ле",
        "ла",
        "фон",
        "зул",
        "аль",
        "ел",
        "бен",
        "ибн",
        "мак",
        "о",
        "сан",
        "санта",
        "тер",
        "тен",
        "вер",
        "van",
        "der",
        "de",
        "di",
        "da",
        "dos",
        "von",
        "zu",
        "al",
        "el",
        "bin",
        "ben",
        "mac",
        "mc",
        "st",
        "san",
    }
)

_HYPHEN_RE = re.compile(r"[-–—‐‑‒―]")
_APOS_RE = re.compile(r"[''`ʻʼ′]")
# длинная «фамилия» (последний токен или сегмент после дефиса)
_LONG_SURNAME_CHARS = 10


def nicknames_path() -> str:
    return _PATH


def load_nicknames() -> dict[str, Any]:
    if not os.path.isfile(_PATH):
        return {"version": 1, "by_person_id": {}, "notes": "nickname → person_id"}
    try:
        with open(_PATH, encoding="utf-8") as f:
            raw = json.load(f)
    except (OSError, json.JSONDecodeError):
        return {"version": 1, "by_person_id": {}}
    if not isinstance(raw, dict):
        return {"version": 1, "by_person_id": {}}
    raw.setdefault("version", 1)
    raw.setdefault("by_person_id", {})
    if not isinstance(raw["by_person_id"], dict):
        raw["by_person_id"] = {}
    return raw


def save_nicknames(data: dict[str, Any]) -> None:
    os.makedirs(os.path.dirname(_PATH), exist_ok=True)
    tmp = _PATH + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
        f.write("\n")
    os.replace(tmp, _PATH)


def get_nickname(person_id: int | None) -> str | None:
    if person_id is None:
        return None
    mp = load_nicknames().get("by_person_id") or {}
    v = mp.get(str(int(person_id)))
    s = (str(v).strip() if v is not None else "")
    return s or None


def set_nickname(person_id: int, nickname: str) -> str:
    """Записать nickname; пустая строка — удалить. Возвращает сохранённое значение."""
    pid = int(person_id)
    if pid <= 0:
        raise ValueError("person_id must be positive")
    data = load_nicknames()
    mp = data.setdefault("by_person_id", {})
    nick = (nickname or "").strip()
    key = str(pid)
    if not nick:
        mp.pop(key, None)
        save_nicknames(data)
        return ""
    # уникальность: один nickname — один person_id
    want = nick.casefold()
    for other_id, other_nick in list(mp.items()):
        if other_id == key:
            continue
        if str(other_nick).strip().casefold() == want:
            raise ValueError(
                f"Никнейм «{nick}» уже занят person_id={other_id}"
            )
    mp[key] = nick
    save_nicknames(data)
    return nick


def resolve_person_id_by_nickname(nickname: str) -> int | None:
    want = (nickname or "").strip().casefold()
    if not want:
        return None
    for pid_s, nick in (load_nicknames().get("by_person_id") or {}).items():
        if str(nick).strip().casefold() == want:
            try:
                return int(pid_s)
            except (TypeError, ValueError):
                return None
    return None


def complex_name_reasons(full_name: str) -> list[str]:
    """Почему имя попало в список «сложных» (пустой = не сложное)."""
    name = (full_name or "").strip()
    if not name:
        return []
    reasons: list[str] = []
    if _HYPHEN_RE.search(name):
        reasons.append("дефис")
    if _APOS_RE.search(name):
        reasons.append("апостроф")
    # нормализуем дефисы в пробелы для токенов
    tokens = [t for t in re.split(r"[\s\-–—‐‑]+", name) if t]
    words = name.split()
    if len(words) >= 3:
        reasons.append("составное (≥3 слова)")
    # частица внутри имени
    low_tokens = [t.casefold() for t in tokens]
    for i, t in enumerate(low_tokens):
        if t in _PARTICLES and 0 < i < len(low_tokens) - 1:
            reasons.append(f"частица «{t}»")
            break
        if t in _PARTICLES and i == 0 and len(low_tokens) >= 2:
            # «Ван Дейк» как целое имя без имени
            reasons.append(f"частица «{t}»")
            break
    # длинный последний сегмент
    last = tokens[-1] if tokens else ""
    if len(last) >= _LONG_SURNAME_CHARS:
        reasons.append(f"длинная фамилия ({len(last)})")
    # длинный сегмент после дефиса (не только последний)
    for t in tokens:
        if len(t) >= _LONG_SURNAME_CHARS + 2 and t != last:
            reasons.append(f"длинный сегмент «{t}»")
            break
    # уникализируем с сохранением порядка
    seen: set[str] = set()
    out: list[str] = []
    for r in reasons:
        if r not in seen:
            seen.add(r)
            out.append(r)
    return out


def is_complex_player_name(full_name: str) -> bool:
    return bool(complex_name_reasons(full_name))
