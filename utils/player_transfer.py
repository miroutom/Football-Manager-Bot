# -*- coding: utf-8 -*-
"""
Трансфер игрока: обновление клуба во всех рабочих SQLite (лига + ЛЧ) и пересборка common.db.

Дополнительно: удаление строк из БД ЛЧ (один игрок или вся команда), затем пересборка common.
CLI: ``rm-cl-player``, ``rm-cl-team``, ``fix-league Имя "Клуб" --assists 3 [--position ЦП]``.
"""
from __future__ import annotations

import sys
from pathlib import Path
from typing import Any

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


def fix_league_player_stats(
    player_name: str,
    team_name: str,
    *,
    goals: int | None = None,
    assists: int | None = None,
    matches: int | None = None,
    position: str | None = None,
    rebuild_common: bool = True,
) -> dict[str, Any]:
    """
    Прямая подстановка чисел в ``league_new.db`` (нац. лиги): одна строка на игрока+клуб.
    Если без ``position`` находится больше одной строки — ошибка (уточни позицию).

    После правки пересчитывается ``ga = goals + assists``, коммит, затем ``rebuild_common_database``.
    """
    if goals is None and assists is None and matches is None:
        raise ValueError("Задай хотя бы одно из: goals, assists, matches")

    player_name = player_name.strip()
    team_name = team_name.strip()
    position = position.strip() if position else None

    from utils.utils import session_league

    hits: list[tuple[str, Any]] = []
    for Cls in (Forward, Midfielder, Defender):
        q = session_league.query(Cls).filter(
            func.lower(Cls.name) == player_name.lower(),
            func.lower(Cls.team) == team_name.lower(),
        )
        if position:
            q = q.filter(func.lower(Cls.position) == position.lower())
        for row in q.all():
            hits.append((Cls.__tablename__, row))

    if not hits:
        raise ValueError(
            f"Не найден игрок «{player_name}» в клубе «{team_name}»"
            + (f", позиция «{position}»" if position else "")
            + " в league_new.db (forwards/midfielders/defenders).",
        )
    if len(hits) > 1:
        tabs = [h[0] for h in hits]
        raise ValueError(
            f"Найдено {len(hits)} строк ({tabs}) — повтори с --position (например ЦП).",
        )

    tablename, row = hits[0]
    before = {
        "goals": int(row.goals or 0),
        "assists": int(row.assists or 0),
        "matches": int(row.matches or 0),
        "ga": int(getattr(row, "ga", 0) or 0),
    }
    if goals is not None:
        row.goals = int(goals)
    if assists is not None:
        row.assists = int(assists)
    if matches is not None:
        row.matches = int(matches)
    row.ga = int(row.goals or 0) + int(row.assists or 0)

    session_league.commit()

    after = {
        "goals": int(row.goals or 0),
        "assists": int(row.assists or 0),
        "matches": int(row.matches or 0),
        "ga": int(row.ga or 0),
    }

    if rebuild_common:
        from utils.common_db import rebuild_common_database

        rebuild_common_database()

    return {
        "table": tablename,
        "player": row.name,
        "team": row.team,
        "position": row.position,
        "before": before,
        "after": after,
    }


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

    p3 = sub.add_parser(
        "fix-league",
        help="Задать голы / передачи / матчи в league_new.db и пересобрать common",
    )
    p3.add_argument("player")
    p3.add_argument("team")
    p3.add_argument("--goals", type=int, default=None)
    p3.add_argument("--assists", type=int, default=None)
    p3.add_argument("--matches", type=int, default=None)
    p3.add_argument("--position", default=None, help="Если несколько строк у игрока в клубе")

    args = parser.parse_args()
    if args.cmd == "rm-cl-player":
        out = delete_player_rows_from_cl_database(args.player, args.team)
        print("Удалено по таблицам:", out)
    elif args.cmd == "rm-cl-team":
        out = delete_team_rows_from_cl_database(args.team)
        print("Удалено по таблицам:", out)
    else:
        out = fix_league_player_stats(
            args.player,
            args.team,
            goals=args.goals,
            assists=args.assists,
            matches=args.matches,
            position=args.position,
        )
        print(out)
