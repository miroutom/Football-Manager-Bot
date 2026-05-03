# -*- coding: utf-8 -*-
"""Имя для БД из полной строки из таблицы СА: в основном фамилия; исключения — полное имя."""
from __future__ import annotations

from utils.player_transfer import normalize_player_name_for_db


def catalog_display_name_from_sheet_full(full: str) -> str:
    """
    Короткое имя для строки в league.db (как в заявке).
    По умолчанию — последнее «слово» (фамилия); частицы Ди/Ван/… — с фамилией;
    дефис в последнем токене — сложная фамилия одним токеном; Фофана — с именем;
    Люка Эрнандез — целиком.
    """
    s = (full or "").strip().replace("\u2019", "'").replace("\u2018", "'")
    if not s:
        return ""
    low = s.casefold()
    if "люка" in low and "эрнандез" in low:
        return normalize_player_name_for_db("Люка Эрнандез")
    if "тео" in low and "эрнандез" in low:
        return normalize_player_name_for_db("Тео Эрнандез")
    # Трёхчастные имена, где фамилия не последнее слово
    if low.replace("ё", "е") in (
        "ли кан ин",
        "энцо ле фе",
    ):
        return normalize_player_name_for_db(s)

    parts = [p for p in s.split() if p]
    if len(parts) == 1:
        return normalize_player_name_for_db(parts[0])

    if parts[-1].casefold() == "фофана" and len(parts) >= 2:
        return normalize_player_name_for_db(f"{parts[0]} {parts[-1]}")

    if "-" in parts[-1]:
        if len(parts) == 2:
            return normalize_player_name_for_db(parts[-1])
        return normalize_player_name_for_db(f"{parts[-2]} {parts[-1]}")

    particles = {
        "ди",
        "да",
        "ван",
        "де",
        "ль",
        "аль",
        "ле",
        "бен",
        "ст.",
        "аль-",
    }
    p2 = parts[-2].casefold().replace("'", "").replace("’", "")
    if len(parts) >= 2 and (p2 in particles or parts[-2].casefold().startswith("аль-")):
        return normalize_player_name_for_db(f"{parts[-2]} {parts[-1]}")
    if len(parts) >= 3:
        p3 = parts[-3].casefold().replace("'", "")
        if p3 in particles:
            return normalize_player_name_for_db(
                f"{parts[-3]} {parts[-2]} {parts[-1]}"
            )

    return normalize_player_name_for_db(parts[-1])
