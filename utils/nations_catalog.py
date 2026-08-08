# -*- coding: utf-8 -*-
"""Полный список стран (RU) для подсказок в UI — не только сборные ЧМ."""
from __future__ import annotations

import json
import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[1]

# Синонимы для автокомpleta (зеркало utils.player_nation._NATION_ALIASES).
NATION_ALIASES: dict[str, str] = {
    "босния и герцеговина": "Босния",
    "босния и герцеговна": "Босния",
    "д р конго": "ДР Конго",
    "д.р. конго": "ДР Конго",
    "др конго": "ДР Конго",
    "конго": "Конго",
    "коста рика": "Коста-Рика",
    "коста-рика": "Коста-Рика",
    "центральноафриканская республика": "ЦАР",
    "цар": "ЦАР",
    "тринидад и тобаго": "Тринидад и Тобаго",
    "юж корея": "Южная Корея",
    "юж. корея": "Южная Корея",
    "кот-д'ивуар": "Кот-д'Ивуар",
    "кот д'ивуар": "Кот-д'Ивуар",
    "котдивуар": "Кот-д'Ивуар",
    "франци": "Франция",
    "франйция": "Франция",
    "gb eng": "Англия",
    "gb sct": "Шотландия",
    "gb wls": "Уэльс",
    "gb nir": "Северная Ирландия",
    "оаэ": "ОАЭ",
    "эмираты": "ОАЭ",
    "косово": "Косово",
}


def _nations_json_paths() -> list[Path]:
    paths: list[Path] = []
    if getattr(sys, "frozen", False):
        paths.append(Path(sys._MEIPASS) / "data" / "nations_all.json")  # type: ignore[attr-defined]
    paths.extend(
        [
            _ROOT / "data" / "nations_all.json",
            Path(__file__).resolve().parents[2] / "data" / "nations_all.json",
        ]
    )
    return paths


def load_all_nations_ru() -> list[str]:
    """Список стран из data/nations_all.json."""
    for path in _nations_json_paths():
        if not path.is_file():
            continue
        try:
            raw = json.loads(path.read_text(encoding="utf-8"))
            if isinstance(raw, list):
                return [str(x).strip() for x in raw if str(x).strip()]
        except (OSError, json.JSONDecodeError, TypeError):
            continue
    return []


def nations_for_picker(*, extra: list[str] | None = None) -> list[str]:
    """Объединённый отсортированный список для автокompleta наций."""
    seen: set[str] = set()
    out: list[str] = []
    for name in load_all_nations_ru():
        s = str(name).strip()
        if not s or s in seen:
            continue
        seen.add(s)
        out.append(s)
    for name in extra or []:
        s = str(name).strip()
        if not s or s in seen:
            continue
        seen.add(s)
        out.append(s)
    out.sort(key=str.casefold)
    return out


def resolve_nation_alias(raw: str) -> str | None:
    """Нормализует ввод через алиасы (casefold)."""
    s = (raw or "").strip().casefold()
    s = s.replace("\u2019", "'").replace("\u2018", "'")
    s = " ".join(s.split())
    if not s:
        return None
    return NATION_ALIASES.get(s)
