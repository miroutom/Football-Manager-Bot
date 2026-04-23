# -*- coding: utf-8 -*-
"""
Трансфер игрока: обновление клуба во всех рабочих SQLite (лига + ЛЧ) и пересборка common.db.

Дополнительно: удаление всех строк команды из БД ЛЧ — если статистика попала ошибочно.
"""
from __future__ import annotations

import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from sqlalchemy import func

from data.defender import Defender
from data.forward import Forward
from data.goalkeeper import Goalkeeper
from data.midfielder import Midfielder


_ALL_PLAYER = (Forward, Midfielder, Defender, Goalkeeper)


def apply_transfer(
    player: str,
    from_team: str,
    position: str,
    to_team: str,
    *,
    rebuild_common: bool = True,
) -> dict[str, int]:
    """
    Ищет игрока по имени (без учёта регистра), клубу «откуда» и позиции (как в БД),
    поле ``team`` меняет на новый клуб в league_new.db и champions_league_new.db.

    Возвращает счётчики обновлённых строк: ``league``, ``cl``.
    """
    player = player.strip()
    from_team = from_team.strip()
    to_team = to_team.strip()
    position = position.strip()

    from utils.utils import session_cl, session_league

    counts = {"league": 0, "cl": 0}

    def _run(sess, key: str) -> None:
        for Cls in _ALL_PLAYER:
            rows = (
                sess.query(Cls)
                .filter(
                    func.lower(Cls.name) == player.lower(),
                    func.lower(Cls.team) == from_team.lower(),
                    func.lower(Cls.position) == position.lower(),
                )
                .all()
            )
            for r in rows:
                r.team = to_team
                counts[key] += 1

    _run(session_league, "league")
    session_league.commit()
    _run(session_cl, "cl")
    session_cl.commit()

    if rebuild_common:
        from utils.common_db import rebuild_common_database

        rebuild_common_database()

    return counts


def delete_team_rows_from_cl_database(team_name: str) -> dict[str, int]:
    """
    Удалить всех игроков указанной команды из БД ЛЧ (имя команды как в таблице, без учёта регистра).
    Полезно, если в ЛЧ «залилась» лишняя статистика; после вызова пересоберите common.db.
    """
    team_name = team_name.strip()
    from utils.utils import session_cl

    removed = {"forward": 0, "midfielder": 0, "defender": 0, "goalkeeper": 0}
    mapping = [
        (Forward, "forward"),
        (Midfielder, "midfielder"),
        (Defender, "defender"),
        (Goalkeeper, "goalkeeper"),
    ]
    for Cls, label in mapping:
        n = (
            session_cl.query(Cls)
            .filter(func.lower(Cls.team) == team_name.lower())
            .delete(synchronize_session=False)
        )
        removed[label] += int(n or 0)
    session_cl.commit()

    from utils.common_db import rebuild_common_database

    rebuild_common_database()
    return removed
