# -*- coding: utf-8 -*-
"""Общие утилиты ростера клуба (списки игроков в клавиатурах бота)."""
from __future__ import annotations

# Сколько игроков на одной странице клавиатуры (Telegram — много коротких рядов).
ROSTER_PAGE_SIZE = 12

# Обратная совместимость с импортом ``_ROSTER_PAGE_SIZE``.
_ROSTER_PAGE_SIZE = ROSTER_PAGE_SIZE


def _team_name_as_in_db(team: str) -> str:
    if (team or "").strip().casefold() == "цска":
        return "Цска"
    return (team or "").strip()


def league_roster_tuples(team: str) -> list[tuple[str, str, int, str]]:
    """Ростер клуба из нац. БД: имя, позиция, overall, team как в строке БД."""
    from data.defender import Defender
    from data.forward import Forward
    from data.goalkeeper import Goalkeeper
    from data.midfielder import Midfielder
    from utils.player_names import player_display_name
    from utils.player_transfer import _filter_team
    from utils.transfer_input import resolve_team_name
    from utils.utils import session_league

    resolved = resolve_team_name(team, session_league)
    t = resolved if resolved else _team_name_as_in_db(team.strip())
    out: list[tuple[str, str, int, str]] = []
    for Cls in (Forward, Midfielder, Defender, Goalkeeper):
        for r in session_league.query(Cls).filter(_filter_team(Cls, t)).all():
            nm = player_display_name(r)
            pos = (r.position or "").strip()
            db_team = (r.team or "").strip()
            if not nm:
                continue
            out.append((nm, pos, int(r.overall or 0), db_team))
    out.sort(key=lambda x: (-x[2], x[0].lower()))
    return out


# Обратная совместимость с импортом ``_league_roster_tuples``.
_league_roster_tuples = league_roster_tuples
