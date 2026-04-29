# -*- coding: utf-8 -*-
"""
Пакетная правка overall: строки «имя +2», «павар -3»; обновление в league, cl, пересборка common.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field

from utils.common_db import rebuild_common_database
from utils.squad_roster_sync import find_player_row
from utils.utils import session_cl, session_league

_LINE_RE = re.compile(
    r"^\s*(.+?)\s*([+-]\d{1,2})\s*$",
    re.IGNORECASE | re.UNICODE,
)


@dataclass
class OverallBumpResult:
    ok: list[str] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)


def _clamp(v: int) -> int:
    return max(1, min(99, v))


def _bump_in_session(session, name: str, team: str, delta: int) -> bool:
    row, _Cls = find_player_row(session, name, team)
    if not row:
        return False
    cur = int(getattr(row, "overall", 0) or 0)
    row.overall = _clamp(cur + delta)
    return True


def apply_overall_bumps_for_team(
    team: str, text: str, *, rebuild_common: bool = True
) -> OverallBumpResult:
    """
    team — как в БД (как в pickle). Текст: по строке, «имя +2» / «z павар -3».
    """
    team = (team or "").strip()
    if len(team) < 2:
        raise ValueError("Слишком короткое имя команды")
    res = OverallBumpResult()
    for line in (text or "").splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        m = _LINE_RE.match(line)
        if not m:
            res.errors.append(f"не разобрать: {line!r}")
            continue
        name = m.group(1).strip()
        delta = int(m.group(2))
        if not name:
            res.errors.append(f"пустое имя: {line!r}")
            continue
        n_l = 0
        n_c = 0
        try:
            if _bump_in_session(session_league, name, team, delta):
                n_l = 1
            if _bump_in_session(session_cl, name, team, delta):
                n_c = 1
        except Exception as e:
            res.errors.append(f"{name}: {e}")
            continue
        if n_l == 0 and n_c == 0:
            res.errors.append(f"не найден: {name}")
            continue
        where = []
        if n_l:
            where.append("нац.")
        if n_c:
            where.append("ЛЧ")
        res.ok.append(f"{name} {delta:+d} ({', '.join(where)})")
    if res.ok:
        try:
            session_league.commit()
        except Exception:
            session_league.rollback()
            raise
        try:
            session_cl.commit()
        except Exception:
            session_cl.rollback()
            raise
        if rebuild_common:
            rebuild_common_database()
    else:
        session_league.rollback()
        session_cl.rollback()
    return res
