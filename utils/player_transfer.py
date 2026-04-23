# -*- coding: utf-8 -*-
"""
Трансфер игрока: обновление клуба во всех рабочих SQLite (лига + ЛЧ) и пересборка common.db.

Дополнительно: удаление строк из БД ЛЧ (один игрок или вся команда), затем пересборка common.
CLI: ``python utils/player_transfer.py rm-cl-player Имя "Клуб"`` или ``rm-cl-team "Клуб"``.
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


def delete_player_rows_from_cl_database(player_name: str, team_name: str) -> dict[str, int]:
    """
    Удалить все строки игрока (по имени и клубу) из ``champions_league_new.db`` — все позиции.
    Затем пересборка ``common.db``. Для правки одной ошибочной записи (например лишняя статистика ЛЧ).
    """
    player_name = player_name.strip()
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
            .filter(
                func.lower(Cls.name) == player_name.lower(),
                func.lower(Cls.team) == team_name.lower(),
            )
            .delete(synchronize_session=False)
        )
        removed[label] += int(n or 0)
    session_cl.commit()

    from utils.common_db import rebuild_common_database

    rebuild_common_database()
    return removed


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


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="Очистка ЛЧ и пересборка common.db")
    sub = parser.add_subparsers(dest="cmd", required=True)

    p1 = sub.add_parser(
        "rm-cl-player",
        help="Удалить игрока из champions_league_new.db",
    )
    p1.add_argument("player")
    p1.add_argument("team")

    p2 = sub.add_parser("rm-cl-team", help="Удалить всех игроков команды из БД ЛЧ")
    p2.add_argument("team")

    args = parser.parse_args()
    if args.cmd == "rm-cl-player":
        out = delete_player_rows_from_cl_database(args.player, args.team)
        print("Удалено по таблицам:", out)
    else:
        out = delete_team_rows_from_cl_database(args.team)
        print("Удалено по таблицам:", out)
