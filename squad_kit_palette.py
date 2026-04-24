# -*- coding: utf-8 -*-
"""Цвета формы для PNG состава.

- 1 цвет: только ``primary``, заливка без полос; воротник тёмный по умолчанию.
- 2 цвета: ``primary`` + ``secondary`` — вертикальные полосы; воротник тёмный.
- 3 цвета: как 2, плюс ``tertiary`` — заливка воротника (полигон у горловины).
"""
from __future__ import annotations

import hashlib
from dataclasses import dataclass
from typing import Final

_RGB = tuple[int, int, int]
_DEFAULT_COLLAR: _RGB = (18, 20, 26)


@dataclass(frozen=True)
class KitSpec:
    primary: _RGB
    secondary: _RGB | None = None
    tertiary: _RGB | None = None

    @property
    def striped(self) -> bool:
        return self.secondary is not None

    def collar_rgb(self) -> _RGB:
        return self.tertiary if self.tertiary is not None else _DEFAULT_COLLAR


# Имя команды как в БД / подписи к составу (см. ``_team_name_as_in_db`` в squad_pitch).
_PRESET: dict[str, KitSpec] = {
    "Рубин": KitSpec((123, 30, 58), (0, 122, 94)),
    "Зенит": KitSpec((0, 132, 209)),
    "Цска": KitSpec((210, 32, 52), (0, 51, 153)),
    "Мю": KitSpec((218, 41, 28)),
    "Сити": KitSpec((108, 171, 221)),
    "Реал": KitSpec((255, 255, 255)),
    "Ливерпуль": KitSpec((200, 16, 46), (255, 255, 255)),
    "Челси": KitSpec((3, 70, 148)),
    "Севилья": KitSpec((255, 255, 255), (210, 0, 42)),
    "Астон Вилла": KitSpec((103, 14, 54), (149, 191, 229)),
    "Атлетико": KitSpec((200, 16, 46), (255, 255, 255), (0, 51, 153)),
    "Локомотив": KitSpec((200, 16, 46), (0, 122, 61)),
    "Краснодар": KitSpec((0, 99, 65), (0, 0, 0)),
    "Байер": KitSpec((220, 0, 0), (0, 0, 0)),
    "Барселона": KitSpec((0, 77, 152), (165, 0, 68)),
    "Бавария": KitSpec((220, 0, 0)),
    "Ньюкасл": KitSpec((0, 0, 0), (255, 255, 255)),
    "Лацио": KitSpec((135, 206, 235)),
    "Арсенал": KitSpec((206, 17, 38), (255, 255, 255)),
    "Тоттенхэм": KitSpec((255, 255, 255), (19, 34, 87)),
    "Дортмунд": KitSpec((255, 221, 0), (0, 0, 0)),
    "Бетис": KitSpec((0, 153, 68), (255, 255, 255)),
    "Милан": KitSpec((220, 0, 0), (0, 0, 0)),
    "Жирона": KitSpec((218, 41, 28), (255, 255, 255)),
    "Интер": KitSpec((0, 85, 164), (0, 0, 0)),
    "Спартак": KitSpec((220, 20, 60), (255, 255, 255)),
    "Урал": KitSpec((255, 102, 0), (0, 0, 0)),
    "Крылья Советов": KitSpec((0, 102, 204), (255, 255, 255)),
    "Ростов": KitSpec((255, 204, 0), (0, 51, 153)),
    "Брайтон": KitSpec((0, 87, 184), (255, 255, 255)),
    "Фулхэм": KitSpec((255, 255, 255), (0, 0, 0), (200, 16, 46)),
    "Боруссия М": KitSpec((0, 153, 102), (0, 0, 0)),
    "Вильярреал": KitSpec((255, 221, 0)),
    "Фиорентина": KitSpec((90, 45, 130)),
    "Реал Сосьедад": KitSpec((0, 102, 204), (255, 255, 255)),
    "Вольфсбург": KitSpec((101, 184, 46)),
    "Фрайбург": KitSpec((220, 0, 0), (255, 255, 255)),
    "Франкфурт": KitSpec((0, 0, 0), (220, 0, 0)),
    "Лейпциг": KitSpec((255, 255, 255), (220, 0, 0)),
    "Наполи": KitSpec((77, 166, 255)),
    "Атлетик": KitSpec((200, 16, 46), (255, 255, 255)),
    "Торино": KitSpec((128, 0, 32)),
    "Хоффенхайм": KitSpec((0, 102, 204), (255, 255, 255)),
    "Аталанта": KitSpec((0, 76, 153), (0, 0, 0)),
    "Штутгарт": KitSpec((255, 255, 255), (220, 0, 0)),
    "Рома": KitSpec((128, 0, 32), (255, 204, 0)),
    "Райо Вальекано": KitSpec((255, 255, 255), (220, 0, 0)),
    "Динамо": KitSpec((0, 102, 204), (255, 255, 255)),
    "Ювентус": KitSpec((0, 0, 0), (255, 255, 255)),
    "Сассуоло": KitSpec((0, 153, 68), (0, 0, 0)),
}

_FALLBACK_KITS: Final[tuple[KitSpec, ...]] = (
    KitSpec((70, 70, 90)),
    KitSpec((90, 40, 50), (240, 220, 200)),
    KitSpec((40, 80, 110), (230, 240, 250)),
    KitSpec((110, 60, 30), (240, 230, 200)),
    KitSpec((50, 90, 60), (230, 245, 230)),
    KitSpec((100, 40, 90), (240, 220, 240)),
)


def kit_for_team(team_db: str) -> KitSpec:
    t = (team_db or "").strip()
    if t in _PRESET:
        return _PRESET[t]
    h = int(hashlib.md5(t.encode("utf-8")).hexdigest()[:8], 16)
    return _FALLBACK_KITS[h % len(_FALLBACK_KITS)]
