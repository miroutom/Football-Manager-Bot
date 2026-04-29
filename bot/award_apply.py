# -*- coding: utf-8 -*-
"""Начисление индивидуальных наград (сезон) в БД лиги/ЛЧ."""
from __future__ import annotations

from data.goalkeeper import Goalkeeper
from player_stats import find_player_by_name
from utils.common_db import rebuild_common_database


KIND_TITLES = {
    "ball": "Золотой мяч (ЗМ)",
    "glove": "Золотая перчатка",
    "boot": "Золотая бутса",
    "boy": "Golden Boy",
}


def apply_trophy(
    session,
    team: str,
    name: str,
    kind: str,
) -> tuple[bool, str]:
    """
    +1 в соответствующую колонку у найденного игрока.
    kind: ball | glove | boot | boy
    """
    if kind not in KIND_TITLES:
        return False, f"Неизвестный вид награды: {kind!r}"

    player, pos = find_player_by_name(session, name.strip(), team=team.strip())
    if not player:
        return (
            False,
            f"Игрок «{name.strip().title()}» в команде «{team.strip().title()}» не найден в базе.",
        )

    if kind == "glove" and pos != "goalkeeper":
        return (
            False,
            "Золотая перчатка выдаётся только вратарю (в базе позиция ВРТ).",
        )

    if kind == "ball":
        player.golden_balls = int(getattr(player, "golden_balls", 0) or 0) + 1
    elif kind == "glove":
        if not isinstance(player, Goalkeeper):
            return False, "Вратарь не найден (внутренняя проверка)."
        player.golden_gloves = int(getattr(player, "golden_gloves", 0) or 0) + 1
    elif kind == "boot":
        player.golden_boots = int(getattr(player, "golden_boots", 0) or 0) + 1
    else:  # boy
        player.golden_boys = int(getattr(player, "golden_boys", 0) or 0) + 1

    session.commit()
    t = KIND_TITLES[kind]
    pl_name = player.name
    pl_team = player.team
    pos_ru = getattr(player, "position", "")
    return (
        True,
        f"✓ {t}\n"
        f"<b>{pl_name}</b> · {pl_team} · {pos_ru}\n"
        f"Счётчик +1 (в «{t}»).",
    )


def save_trophy_and_rebuild_common() -> None:
    """После правки league/cl пересобрать common (как после трансфера)."""
    rebuild_common_database()
