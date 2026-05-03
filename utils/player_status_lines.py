# -*- coding: utf-8 -*-
"""
Пакетная правка заявки: строки «фамилия start» / «имя bench» / «игрок reserve».
Обновление ``status`` в нац. БД и ЛЧ, пересборка common, зеркало в cumulative.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field

from sqlalchemy.orm import Session

from utils.common_db import rebuild_common_database
from utils.squad_roster_sync import find_player_row_first_match
from utils.utils import session_cl, session_league

_LINE_RE = re.compile(
    r"^\s*(.+?)\s+(start|bench|reserve)\s*$",
    re.IGNORECASE | re.UNICODE,
)


@dataclass
class StatusApplyResult:
    ok: list[str] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)


def _set_status_in_session(
    session: Session,
    team: str,
    name: str,
    status: str,
    alternate_names: tuple[str, ...] = (),
) -> bool:
    st = status.strip().lower()
    row, _Cls, _m = find_player_row_first_match(session, name, team, *alternate_names)
    if row is None:
        return False
    row.status = st
    return True


def apply_player_status_lines_in_sessions(
    team: str,
    text: str,
    sleague: Session,
    scl: Session,
    *,
    alternate_names: dict[str, tuple[str, ...]] | None = None,
) -> StatusApplyResult:
    team = (team or "").strip()
    if len(team) < 2:
        raise ValueError("Слишком короткое имя команды")
    res = StatusApplyResult()
    alts_map = alternate_names or {}
    for line in (text or "").splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        m = _LINE_RE.match(line)
        if not m:
            res.errors.append(f"не разобрать (нужно: имя + start|bench|reserve): {line!r}")
            continue
        name = m.group(1).strip()
        status = m.group(2).strip().lower()
        if not name:
            res.errors.append(f"пустое имя: {line!r}")
            continue
        alt_key = f"{team.lower()}|{name.strip().lower()}"
        extras = alts_map.get(alt_key, ())
        n_l = 0
        n_c = 0
        try:
            if _set_status_in_session(sleague, team, name, status, extras):
                n_l = 1
            if _set_status_in_session(scl, team, name, status, extras):
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
        res.ok.append(f"{name} → {status} ({', '.join(where)})")
    return res


def apply_player_status_lines_for_team(
    team: str, text: str, *, rebuild_common: bool = True
) -> StatusApplyResult:
    res = apply_player_status_lines_in_sessions(
        team, text, session_league, session_cl
    )
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
        from utils import cumulative_mirror

        cumulative_mirror.mirror_player_status_lines_for_team(team, text)
    else:
        session_league.rollback()
        session_cl.rollback()
    return res
