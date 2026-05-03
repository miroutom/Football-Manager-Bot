# -*- coding: utf-8 -*-
"""
Трансфер игрока: обновление клуба во всех рабочих SQLite (лига + ЛЧ) и пересборка common.db.

Дополнительно: удаление строк из БД ЛЧ (один игрок или вся команда), затем пересборка common.
CLI: см. ``python utils/player_transfer.py -h``.
Поиск строки в league: ``search-league подстрока [--team подстрока_клуба]``.
Правка по id: ``fix-league-id midfielders 123 --assists 3``.
"""
from __future__ import annotations

import sys
from pathlib import Path
from typing import Any, Literal

_ROOT = Path(__file__).resolve().parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from sqlalchemy import func, or_

from data.defender import Defender
from data.forward import Forward
from data.goalkeeper import Goalkeeper
from data.midfielder import Midfielder


_ALL_PLAYER = (Forward, Midfielder, Defender, Goalkeeper)


def _norm_pos_key(position: str) -> str:
    return (position or "").strip().upper()


def _start_cap_for_position(position: str) -> int:
    """
    Сколько игроков с одной строкой позиции (ЦЗ, ЦП, …) может быть со статусом start одновременно.
    Для пары центральных защитников — 2; для одиночных ролей — 1; полузащита 433 — до 3 ЦП и т.д.
    Неизвестные аббревиатуры: 2 (разумный дефолт между 1 и 3).
    """
    caps: dict[str, int] = {
        "ЦЗ": 2,
        "ПЗ": 2,
        "ЛЗ": 2,
        "ЦП": 3,
        "ЦОП": 2,
        "ЦАП": 1,
        "ЛФА": 2,
        "ПФА": 2,
        "ФРВ": 2,
        "ЦН": 1,
        "ВРТ": 1,
        "ЛП": 2,
        "ПП": 2,
        "ЛЦП": 2,
        "ПЦП": 2,
    }
    return caps.get(_norm_pos_key(position), 2)


def _norm_cmp(s: str) -> str:
    """
    Сравнение без учёта регистра для кириллицы и латиницы.
    В SQLite ``lower()`` кириллицу часто не меняет — нельзя сравнивать с ``.lower()`` из Python.
    """
    return (s or "").strip().casefold()


def normalize_player_name_for_db(name: str) -> str:
    """
    Имя для записи в БД: каждое слово — с заглавной буквы, остальные строчные
    (например «медина» → «Медина»).
    """
    s = (name or "").strip()
    if not s:
        return s
    parts: list[str] = []
    for part in s.split():
        if not part:
            continue
        if len(part) == 1:
            parts.append(part.upper())
        else:
            parts.append(part[0].upper() + part[1:].lower())
    return " ".join(parts)


def _filter_team(Cls, team: str):
    t = (team or "").strip()
    tl = t.lower()
    return or_(Cls.team == t, func.lower(Cls.team) == tl)


def _all_for_team(sess, Cls, team: str) -> list[Any]:
    return sess.query(Cls).filter(_filter_team(Cls, team)).all()


def _cascade_status(
    sess, Cls, to_team: str, position: str, incoming: Any, new_status: str | None
) -> None:
    """
    Правила заявки в новом клубе: start / bench / reserve.
    new_status None — только сброс status (как раньше).
    """
    if new_status is None:
        incoming.status = None
        return
    pos = position.strip()
    pos_l = pos.lower()
    ns = new_status.strip().lower()
    if ns not in ("start", "bench", "reserve"):
        raise ValueError("status: start | bench | reserve")

    def _same_pos(r: Any) -> bool:
        return (r.position or "").strip().lower() == pos_l

    if ns == "reserve":
        incoming.status = "reserve"
        return

    if ns == "start":
        # Раньше все стартующие с той же позицией (два ЦЗ) уходили на скамейку — на поле пусто.
        # Оставляем лучших по overall в пределах лимита на позицию (ЦЗ → 2 и т.д.).
        cap = _start_cap_for_position(pos)
        others = [
            r
            for r in _all_for_team(sess, Cls, to_team)
            if r.id != incoming.id
            and _same_pos(r)
            and (r.status or "").strip().lower() == "start"
        ]
        pool = others + [incoming]
        pool_sorted = sorted(
            pool,
            key=lambda x: (-(x.overall or 0), (x.name or "").lower()),
        )
        keep_ids = {id(r) for r in pool_sorted[:cap]}
        for r in pool:
            r.status = "start" if id(r) in keep_ids else "bench"
        bench = [
            r
            for r in _all_for_team(sess, Cls, to_team)
            if (r.status or "").strip().lower() == "bench"
        ]
        if bench:
            worst = min(bench, key=lambda x: (x.overall or 0, (x.name or "")))
            worst.status = "reserve"
        return

    # bench
    incoming.status = "bench"
    bench = [
        r
        for r in _all_for_team(sess, Cls, to_team)
        if (r.status or "").strip().lower() == "bench"
    ]
    if len(bench) >= 2:
        worst = min(bench, key=lambda x: (x.overall or 0, (x.name or "")))
        worst.status = "reserve"


def _apply_transfer_with_status_to_sessions(
    sess_league,
    sess_cl,
    player: str,
    from_team: str,
    position: str,
    to_team: str,
    new_status: str | None,
    *,
    new_overall: int | None = None,
    nation_update: bool = False,
    new_nation: str | None = None,
) -> dict[str, int]:
    """Трансфер в указанных сессиях; коммитит обе."""
    player = player.strip()
    from_team = from_team.strip()
    to_team = to_team.strip()
    position = position.strip()

    counts: dict[str, int] = {"league": 0, "cl": 0}
    want_name = _norm_cmp(player)
    want_pos = _norm_cmp(position)

    def _run_session(sess, key: str) -> None:
        for Cls in _ALL_PLAYER:
            for r in sess.query(Cls).filter(_filter_team(Cls, from_team)).all():
                if _norm_cmp(getattr(r, "name", "") or "") != want_name:
                    continue
                if _norm_cmp(getattr(r, "position", "") or "") != want_pos:
                    continue
                r.team = to_team
                if new_overall is not None:
                    r.overall = max(1, min(99, int(new_overall)))
                if nation_update:
                    r.nation = (new_nation or "").strip() or None
                _cascade_status(sess, Cls, to_team, position, r, new_status)
                counts[key] += 1

    _run_session(sess_league, "league")
    sess_league.commit()
    _run_session(sess_cl, "cl")
    sess_cl.commit()
    return counts


def apply_transfer_with_status(
    player: str,
    from_team: str,
    position: str,
    to_team: str,
    new_status: str | None,
    *,
    rebuild_common: bool = True,
    new_overall: int | None = None,
    nation_update: bool = False,
    new_nation: str | None = None,
) -> dict[str, int]:
    """
    Трансфер + заявка в новом клубе. ``new_status`` is None — сброс status (старое поведение).
    """
    from utils.utils import session_cl, session_league

    counts = _apply_transfer_with_status_to_sessions(
        session_league,
        session_cl,
        player,
        from_team,
        position,
        to_team,
        new_status,
        new_overall=new_overall,
        nation_update=nation_update,
        new_nation=new_nation,
    )

    if rebuild_common:
        from utils.common_db import rebuild_common_database

        rebuild_common_database()
    from utils import cumulative_mirror

    cumulative_mirror.mirror_transfer_with_status(
        player,
        from_team,
        position,
        to_team,
        new_status,
        new_overall=new_overall,
        nation_update=nation_update,
        new_nation=new_nation,
    )
    return counts


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
    поле ``team`` меняет на новый клуб в национальной БД и в БД ЛЧ.
    ``status`` сбрасывается (см. ``apply_transfer_with_status`` для start/bench/reserve).

    Возвращает счётчики обновлённых строк: ``league``, ``cl``.
    """
    return apply_transfer_with_status(
        player, from_team, position, to_team, None, rebuild_common=rebuild_common
    )


def _cls_for_position(position: str):
    from utils.squad_roster_sync import _cls_for_position as resolve

    return resolve(position)


def _new_player_kwargs(
    Cls: type,
    *,
    name: str,
    team: str,
    position: str,
    overall: int,
    nation: str | None = None,
) -> dict[str, Any]:
    u = max(1, min(99, int(overall)))
    pos_u = position.strip().upper()
    nat = (nation or "").strip() or None
    nm = normalize_player_name_for_db(name)
    kw: dict[str, Any] = dict(
        name=nm,
        team=team.strip(),
        position=pos_u,
        overall=u,
        matches=0,
        trophies=0,
        golden_balls=0,
        nation=nat,
        status=None,
    )
    if Cls is Forward:
        kw.update(
            goals=0,
            assists=0,
            ga=0,
            golden_boots=0,
            golden_boys=0,
        )
    elif Cls is Midfielder:
        kw.update(
            goals=0,
            assists=0,
            ga=0,
            golden_boots=0,
            golden_boys=0,
        )
    elif Cls is Defender:
        kw.update(
            goals=0,
            assists=0,
            ga=0,
            clean_sheets=0,
            golden_boots=0,
            golden_boys=0,
        )
    else:
        kw.update(
            clean_sheets=0,
            missed_goals=0,
            golden_boots=0,
            golden_gloves=0,
            golden_boys=0,
        )
    return kw


def _add_free_agent_to_sessions(
    session_league,
    session_cl,
    player: str,
    position: str,
    to_team: str,
    new_status: str,
    overall: int = 72,
    *,
    nation: str | None = None,
    on_league_duplicate: Literal["raise", "skip"] = "raise",
) -> dict[str, int]:
    from utils.common_db import _team_in_cl_pool

    player = normalize_player_name_for_db(player.strip())
    position = position.strip()
    to_team = to_team.strip()
    ns = new_status.strip().lower()
    if ns not in ("start", "bench", "reserve"):
        raise ValueError("status: start | bench | reserve")

    Cls = _cls_for_position(position)
    pos_u = position.strip().upper()
    nl = player.lower()
    pl = pos_u.lower()

    def _dup(sess) -> bool:
        # SQLite lower() кириллицу не нормализует — сравниваем в Python (как в squad_roster_sync).
        for r in sess.query(Cls).filter(_filter_team(Cls, to_team)).all():
            if (r.name or "").strip().lower() == nl and (r.position or "").strip().lower() == pl:
                return True
        return False

    kw = _new_player_kwargs(
        Cls,
        name=player,
        team=to_team,
        position=position,
        overall=overall,
        nation=nation,
    )
    counts = {"league": 0, "cl": 0}
    if _dup(session_league):
        if on_league_duplicate == "raise":
            raise ValueError("Такой игрок с этой позицией в клубе уже есть (нац. БД).")
    else:
        row_l = Cls(**kw)
        session_league.add(row_l)
        session_league.flush()
        _cascade_status(session_league, Cls, to_team, pos_u, row_l, ns)
        counts["league"] = 1
    session_league.commit()

    if _team_in_cl_pool(to_team):
        if not _dup(session_cl):
            row_c = Cls(**{**kw, "id": None})
            session_cl.add(row_c)
            session_cl.flush()
            _cascade_status(session_cl, Cls, to_team, pos_u, row_c, ns)
            counts["cl"] = 1
    session_cl.commit()
    return counts


def add_free_agent(
    player: str,
    position: str,
    to_team: str,
    new_status: str,
    overall: int = 72,
    *,
    nation: str | None = None,
    rebuild_common: bool = True,
) -> dict[str, int]:
    """
    Новый игрок (свободный агент): вставка строки в нац. БД и в БД ЛЧ, если клуб в пуле ЛЧ.
    """
    from utils.utils import session_cl, session_league

    counts = _add_free_agent_to_sessions(
        session_league,
        session_cl,
        player,
        position,
        to_team,
        new_status,
        overall,
        nation=nation,
        on_league_duplicate="raise",
    )

    if rebuild_common:
        from utils.common_db import rebuild_common_database

        rebuild_common_database()
    from utils import cumulative_mirror

    cumulative_mirror.mirror_add_free_agent(
        player, position, to_team, new_status, overall, nation=nation
    )
    return counts


_OUTFIELD_TABLES: dict[str, type] = {
    "forwards": Forward,
    "midfielders": Midfielder,
    "defenders": Defender,
}


def _cyrillic_to_latin_lc(s: str) -> str:
    """Грубая транслитерация для поиска (кириллица → латиница в стиле паспорта)."""
    m = {
        "а": "a",
        "б": "b",
        "в": "v",
        "г": "g",
        "д": "d",
        "е": "e",
        "ё": "e",
        "ж": "zh",
        "з": "z",
        "и": "i",
        "й": "y",
        "к": "k",
        "л": "l",
        "м": "m",
        "н": "n",
        "о": "o",
        "п": "p",
        "р": "r",
        "с": "s",
        "т": "t",
        "у": "u",
        "ф": "f",
        "х": "h",
        "ц": "ts",
        "ч": "ch",
        "ш": "sh",
        "щ": "sch",
        "ъ": "",
        "ы": "y",
        "ь": "",
        "э": "e",
        "ю": "yu",
        "я": "ya",
    }
    return "".join(m.get(c, c) for c in s.lower())


def _name_like_variants(needle: str) -> list[str]:
    """Подстроки для SQL LIKE: как ввели + латиница от кириллицы (имена в БД часто латиницей)."""
    n = needle.strip().lower()
    if not n:
        return []
    seen: set[str] = set()
    out: list[str] = []
    for cand in (n, _cyrillic_to_latin_lc(n)):
        if cand and cand not in seen:
            seen.add(cand)
            out.append(cand)
    return out


def search_league_players(
    name_contains: str | None,
    *,
    team_contains: str | None = None,
    limit: int = 800,
) -> list[dict[str, Any]]:
    """
    Строки из ``league_new.db`` (см. ``utils.utils.LEAGUE_DB_PATH``).

    Имя: подстрока в ``name``; если ввели кириллицу — дополнительно ищется латиница («камара» → ``%kamara%``).
    Можно указать только клуб (``name`` пустой): ``search-league "" --team вилла``.
    """
    nm = (name_contains or "").strip()
    tm = (team_contains or "").strip()

    if not nm and not tm:
        raise ValueError("Задай подстроку имени и/или --team для клуба.")

    from utils.utils import session_league

    rows_out: list[dict[str, Any]] = []
    name_vars = _name_like_variants(nm) if nm else []

    team_pat = f"%{tm.lower()}%" if tm else None

    for Cls in (Forward, Midfielder, Defender):
        q = session_league.query(Cls)
        if name_vars:
            name_conds = [
                func.lower(Cls.name).like(f"%{v}%") for v in name_vars
            ]
            q = q.filter(or_(*name_conds))
        if team_pat:
            q = q.filter(func.lower(Cls.team).like(team_pat))
        for row in q.all():
            rows_out.append(
                {
                    "table": Cls.__tablename__,
                    "id": row.id,
                    "name": row.name,
                    "team": row.team,
                    "position": row.position,
                    "goals": int(row.goals or 0),
                    "assists": int(row.assists or 0),
                    "matches": int(row.matches or 0),
                    "ga": int(getattr(row, "ga", 0) or 0),
                }
            )

    rows_out.sort(key=lambda x: (x["team"].lower(), x["name"].lower()))
    return rows_out[:limit]


def _apply_fix_numbers_to_row(
    row: Any,
    *,
    goals: int | None,
    assists: int | None,
    matches: int | None,
) -> tuple[dict[str, int], dict[str, int]]:
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
    after = {
        "goals": int(row.goals or 0),
        "assists": int(row.assists or 0),
        "matches": int(row.matches or 0),
        "ga": int(row.ga or 0),
    }
    return before, after


def fix_league_row_by_table_id(
    table: str,
    row_id: int,
    *,
    goals: int | None = None,
    assists: int | None = None,
    matches: int | None = None,
    rebuild_common: bool = True,
) -> dict[str, Any]:
    """Правка строки по имени таблицы SQLite и первичному ключу ``id``."""
    if goals is None and assists is None and matches is None:
        raise ValueError("Задай хотя бы одно из: goals, assists, matches")

    tbl = table.strip().lower()
    if tbl not in _OUTFIELD_TABLES:
        raise ValueError(f"Таблица: один из {sorted(_OUTFIELD_TABLES)}")
    Cls = _OUTFIELD_TABLES[tbl]

    from utils.utils import session_league

    row = session_league.query(Cls).filter(Cls.id == int(row_id)).first()
    if row is None:
        raise ValueError(f"Нет строки id={row_id} в «{tbl}».")

    before, after = _apply_fix_numbers_to_row(row, goals=goals, assists=assists, matches=matches)
    session_league.commit()

    if rebuild_common:
        from utils.common_db import rebuild_common_database

        rebuild_common_database()

    return {
        "table": tbl,
        "id": row.id,
        "player": row.name,
        "team": row.team,
        "position": row.position,
        "before": before,
        "after": after,
    }


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

    pn = _norm_cmp(player_name)
    tn = _norm_cmp(team_name)
    pos_want = _norm_cmp(position) if position else None

    hits: list[tuple[str, Any]] = []
    for Cls in (Forward, Midfielder, Defender):
        for row in session_league.query(Cls).filter(_filter_team(Cls, team_name)).all():
            if _norm_cmp(row.name or "") != pn:
                continue
            if _norm_cmp(row.team or "") != tn:
                continue
            if pos_want is not None and _norm_cmp(row.position or "") != pos_want:
                continue
            hits.append((Cls.__tablename__, row))

    if not hits:
        raise ValueError(
            f"Не найден игрок «{player_name}» в клубе «{team_name}»"
            + (f", позиция «{position}»" if position else "")
            + " в league_new.db (forwards/midfielders/defenders).\n"
            "Подсказка: найди строку командой "
            f'python3 utils/player_transfer.py search-league "{player_name}" --team часть_названия_клуба',
        )
    if len(hits) > 1:
        tabs = [h[0] for h in hits]
        raise ValueError(
            f"Найдено {len(hits)} строк ({tabs}) — повтори с --position (например ЦП).",
        )

    tablename, row = hits[0]
    before, after = _apply_fix_numbers_to_row(row, goals=goals, assists=assists, matches=matches)
    session_league.commit()

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

    parser = argparse.ArgumentParser(description="Трансферы, очистка ЛЧ, правка league.db")
    sub = parser.add_subparsers(dest="cmd", required=True)

    p0 = sub.add_parser("db-path", help="Показать пути к league / cl / common (как в коде бота)")

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
        help="Задать голы / передачи / матчи в league_new.db (точное имя и клуб)",
    )
    p3.add_argument("player")
    p3.add_argument("team")
    p3.add_argument("--goals", type=int, default=None)
    p3.add_argument("--assists", type=int, default=None)
    p3.add_argument("--matches", type=int, default=None)
    p3.add_argument("--position", default=None, help="Если несколько строк у игрока в клубе")

    p4 = sub.add_parser(
        "search-league",
        help="Найти игроков в league_new.db по подстроке имени (и опционально клуба)",
    )
    p4.add_argument(
        "needle",
        nargs="?",
        default=None,
        help="Подстрока в имени (например камара или Kamara); можно пусто вместе с --team",
    )
    p4.add_argument(
        "--team",
        dest="team_needle",
        default=None,
        help="Подстрока в названии клуба (например вилла)",
    )

    p5 = sub.add_parser(
        "fix-league-id",
        help="Правка по таблице и id (как в выводе search-league)",
    )
    p5.add_argument(
        "table",
        choices=sorted(_OUTFIELD_TABLES.keys()),
        help="forwards / midfielders / defenders",
    )
    p5.add_argument("row_id", type=int)
    p5.add_argument("--goals", type=int, default=None)
    p5.add_argument("--assists", type=int, default=None)
    p5.add_argument("--matches", type=int, default=None)

    args = parser.parse_args()
    if args.cmd == "db-path":
        from utils.utils import CHAMPIONS_LEAGUE_DB_PATH, COMMON_DB_PATH, LEAGUE_DB_PATH

        print("league (нац. лиги):", LEAGUE_DB_PATH)
        print("ЛЧ:                ", CHAMPIONS_LEAGUE_DB_PATH)
        print("common (merge):    ", COMMON_DB_PATH)
    elif args.cmd == "rm-cl-player":
        out = delete_player_rows_from_cl_database(args.player, args.team)
        print("Удалено по таблицам:", out)
    elif args.cmd == "rm-cl-team":
        out = delete_team_rows_from_cl_database(args.team)
        print("Удалено по таблицам:", out)
    elif args.cmd == "fix-league":
        out = fix_league_player_stats(
            args.player,
            args.team,
            goals=args.goals,
            assists=args.assists,
            matches=args.matches,
            position=args.position,
        )
        print(out)
    elif args.cmd == "search-league":
        rows = search_league_players(args.needle, team_contains=args.team_needle)
        if not rows:
            print("Ничего не найдено.")
            print(
                "Подсказка: имена часто латиницей — попробуй "
                "`search-league kamara` или `search-league \"\" --team вилла` "
                "и проверь `db-path`, что открыт league_new.db."
            )
        else:
            for r in rows:
                print(
                    f"id={r['id']:>5}  {r['table']:<14}  {r['name']:<22}  {r['team']:<22}  "
                    f"{r['position']:<6}  И={r['matches']}  Г={r['goals']}  А={r['assists']}  Г+А={r['ga']}",
                )
            print(f"\nВсего строк: {len(rows)}")
    else:
        out = fix_league_row_by_table_id(
            args.table,
            args.row_id,
            goals=args.goals,
            assists=args.assists,
            matches=args.matches,
        )
        print(out)
