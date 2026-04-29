# -*- coding: utf-8 -*-
"""Объединение заявок всех национальных лиг (ключи команд не пересекаются)."""

from __future__ import annotations

from typing import Optional, Tuple

from data.england_apl_squads import ENGLAND_APL_SQUADS
from data.germany_bundesliga_squads import GERMANY_BUNDESLIGA_SQUADS
from data.italy_seria_a_squads import ITALY_SERIE_A_SQUADS
from data.russia_rpl_squads import RUSSIA_RPL_SQUADS
from data.spain_la_liga_squads import SPAIN_LA_LIGA_SQUADS

Row = Tuple[str, str, int, Optional[str], str]


def merged_national_squads() -> dict[str, list[Row]]:
    out: dict[str, list[Row]] = {}
    for part in (
        ENGLAND_APL_SQUADS,
        GERMANY_BUNDESLIGA_SQUADS,
        ITALY_SERIE_A_SQUADS,
        SPAIN_LA_LIGA_SQUADS,
        RUSSIA_RPL_SQUADS,
    ):
        for team, rows in part.items():
            if team in out:
                raise ValueError(f"Дублируется команда в заявках: {team!r}")
            out[team] = list(rows)
    return out
