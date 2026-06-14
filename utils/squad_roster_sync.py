# -*- coding: utf-8 -*-
"""
Синхронизация заявки команды: overall, nation, position, status; опционально удаление лишних
игроков (``prune``). Скрипты: ``scripts/sync_england_apl_rosters.py``,
``scripts/sync_all_national_rosters.py`` (все нац. лиги разом).

Полный прогон АПЛ по умолчанию пишет в ``league_new.db`` и (только для клубов из пула ЛЧ —
``_team_in_cl_pool``, те же ключи что ``teams_champ_league`` / участники из ``get_cl_participants``)
в ``champions_league_new.db``, затем при необходимости пересобирает ``common.db``.

Статусы в БД: ``start`` | ``bench`` | ``reserve``.
"""
from __future__ import annotations

import os
import sqlite3
import sys
from pathlib import Path
from typing import Any, Optional

_ROOT = Path(__file__).resolve().parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from sqlalchemy import func, or_

from data.defender import Defender
from data.forward import Forward
from data.goalkeeper import Goalkeeper
from data.midfielder import Midfielder
from utils.common_db import _team_in_cl_pool
from utils.player_transfer import _norm_cmp, normalize_player_name_for_db
from utils.utils import defenders, forwards, get_session, goalkeepers, midfielders

_ALL_PLAYER = (Forward, Midfielder, Defender, Goalkeeper)


def _filter_team(Cls, team: str):
    """
    Кириллица: SQLite lower() буквы не понижает, поэтому вместо одного
    func.lower(Cls.team) == python_lower(team) сравниваем ещё и по точной строке клуба.
    """
    t = (team or "").strip()
    tl = t.lower()
    return or_(Cls.team == t, func.lower(Cls.team) == tl)


def _cls_for_position(position: str) -> type:
    pos = (position or "").strip().upper()
    if pos in forwards:
        return Forward
    if pos in midfielders:
        return Midfielder
    if pos in defenders:
        return Defender
    return Goalkeeper


def find_player_row(session, name: str, team: str) -> tuple[Any, type | None]:
    from utils.player_names import player_row_matches_query

    for Cls in _ALL_PLAYER:
        for r in session.query(Cls).filter(_filter_team(Cls, team)).all():
            if player_row_matches_query(r, name):
                return r, Cls
    return None, None


def find_player_row_first_match(
    session, name: str, team: str, *alternate_names: str
) -> tuple[Any, type | None, str]:
    """
    Сначала ``name``, затем каждый из ``alternate_names`` (как в заявке / БД).
    Возвращает (row, Cls, совпавшая_строка_поиска) или (None, None, "").
    """
    for cand in ((name or "").strip(),) + tuple(
        (x or "").strip() for x in alternate_names if (x or "").strip()
    ):
        if not cand:
            continue
        row, Cls = find_player_row(session, cand, team)
        if row is not None:
            return row, Cls, cand
    return None, None, ""


def _all_rows_same_player(session, name: str, team: str) -> list[tuple[Any, type]]:
    from utils.player_names import player_row_matches_query

    out: list[tuple[Any, type]] = []
    for Cls in _ALL_PLAYER:
        for r in session.query(Cls).filter(_filter_team(Cls, team)).all():
            if player_row_matches_query(r, name):
                out.append((r, Cls))
    return out


def _merge_carry_dicts(a: dict[str, Any], b: dict[str, Any]) -> dict[str, Any]:
    """Суммирует статистику из двух carry-словарей (дубли строк в БД)."""
    m1 = int(a.get("matches", 0) or 0)
    m2 = int(b.get("matches", 0) or 0)
    mt = m1 + m2
    out: dict[str, Any] = {
        "matches": mt,
        "trophies": int(a.get("trophies", 0) or 0) + int(b.get("trophies", 0) or 0),
        "golden_balls": int(a.get("golden_balls", 0) or 0) + int(b.get("golden_balls", 0) or 0),
    }
    for k in (
        "goals",
        "assists",
        "ga",
        "golden_boots",
        "golden_boys",
        "golden_gloves",
        "clean_sheets",
        "missed_goals",
    ):
        if k in a or k in b:
            out[k] = int(a.get(k, 0) or 0) + int(b.get(k, 0) or 0)
    return out


def _row_stat_score(row: Any) -> int:
    goals = int(getattr(row, "goals", 0) or 0)
    assists = int(getattr(row, "assists", 0) or 0)
    matches = int(getattr(row, "matches", 0) or 0)
    cs = int(getattr(row, "clean_sheets", 0) or 0)
    return matches + goals + assists + cs


def _find_row_by_person_id(
    session, team: str, person_id: int
) -> tuple[Any, type | None]:
    from utils.person_registry import row_person_id

    want = int(person_id)
    if want <= 0:
        return None, None
    for Cls in _ALL_PLAYER:
        for r in session.query(Cls).filter(_filter_team(Cls, team)).all():
            if row_person_id(r) == want:
                return r, Cls
    return None, None


def _apply_carry_to_row(row: Any, carry: dict[str, Any]) -> None:
    row.matches = int(carry.get("matches", getattr(row, "matches", 0)) or 0)
    row.trophies = int(carry.get("trophies", getattr(row, "trophies", 0)) or 0)
    row.golden_balls = int(carry.get("golden_balls", getattr(row, "golden_balls", 0)) or 0)
    if hasattr(row, "goals"):
        row.goals = int(carry.get("goals", getattr(row, "goals", 0)) or 0)
        row.assists = int(carry.get("assists", getattr(row, "assists", 0)) or 0)
        row.ga = int(carry.get("ga", getattr(row, "ga", 0)) or 0)
    if hasattr(row, "golden_boots"):
        row.golden_boots = int(carry.get("golden_boots", getattr(row, "golden_boots", 0)) or 0)
    if hasattr(row, "golden_boys"):
        row.golden_boys = int(carry.get("golden_boys", getattr(row, "golden_boys", 0)) or 0)
    if hasattr(row, "clean_sheets") and not hasattr(row, "goals"):
        row.clean_sheets = int(carry.get("clean_sheets", getattr(row, "clean_sheets", 0)) or 0)
    if hasattr(row, "missed_goals"):
        row.missed_goals = int(carry.get("missed_goals", getattr(row, "missed_goals", 0)) or 0)
    if hasattr(row, "golden_gloves"):
        row.golden_gloves = int(
            carry.get("golden_gloves", getattr(row, "golden_gloves", 0)) or 0
        )


def _dedupe_player_rows_for_team(
    session, name: str, team: str
) -> tuple[Any, type | None, dict[str, Any] | None, int | None]:
    """
    Одна строка на игрока+клуб. Дубли (разные позиции / person_id) сливаются в одну
    существующую строку — без удаления всех и повторного insert.
    """
    from utils.person_registry import row_person_id

    found = _all_rows_same_player(session, name, team)
    if not found:
        return None, None, None, None
    if len(found) == 1:
        r, c = found[0]
        return r, c, None, row_person_id(r)

    ranked = sorted(
        found,
        key=lambda rc: (_row_stat_score(rc[0]), int(getattr(rc[0], "id", 0) or 0)),
        reverse=True,
    )
    keep_r, keep_cls = ranked[0]
    merged = _carry_from_row(keep_r)
    kept_pid = row_person_id(keep_r)
    for r, _Cls in ranked[1:]:
        merged = _merge_carry_dicts(merged, _carry_from_row(r))
        pid = row_person_id(r)
        if pid is not None and (kept_pid is None or pid < kept_pid):
            kept_pid = pid
        session.delete(r)
    _apply_carry_to_row(keep_r, merged)
    if kept_pid is not None:
        keep_r.person_id = kept_pid
    session.flush()
    return keep_r, keep_cls, None, kept_pid


def _resolve_roster_row(
    session,
    name: str,
    team: str,
    *,
    preferred_person_id: int | None = None,
) -> tuple[Any, type | None, dict[str, Any] | None, int | None]:
    """Найти единственную строку игрока в клубе (имя или person_id), сливая дубли."""
    from utils.player_identity import resolve_canonical_name
    from utils.person_registry import lookup_canonical_person_id_by_team

    lookup_name = resolve_canonical_name(team, name)
    for cand in (lookup_name, name):
        if not (cand or "").strip():
            continue
        row, cur_cls, carry, pid = _dedupe_player_rows_for_team(session, cand, team)
        if row is not None:
            return row, cur_cls, carry, pid

    want_pid = (
        int(preferred_person_id)
        if preferred_person_id is not None and int(preferred_person_id) > 0
        else lookup_canonical_person_id_by_team(name, team=team)
    )
    if want_pid:
        row, cur_cls = _find_row_by_person_id(session, team, want_pid)
        if row is not None:
            return row, cur_cls, None, want_pid
    return None, None, None, None


def _new_player_kwargs(
    tgt_cls: type,
    *,
    name: str,
    team: str,
    position: str,
    overall: int,
    nation: str | None,
    status: str,
    carry: dict[str, Any] | None = None,
    person_id: int | None = None,
    lineup_slot: str | None = None,
) -> dict[str, Any]:
    pos = position.strip().upper()
    st = status.strip().lower()
    nm = normalize_player_name_for_db(name)
    c = carry or {}
    kw: dict[str, Any] = dict(
        name=nm,
        team=team,
        position=pos,
        overall=int(overall),
        nation=(nation.strip() if nation else None) or None,
        status=st,
        lineup_slot=lineup_slot,
        matches=int(c.get("matches", 0) or 0),
        trophies=int(c.get("trophies", 0) or 0),
        golden_balls=int(c.get("golden_balls", 0) or 0),
        person_id=int(person_id) if person_id is not None else None,
        left_team=False,
    )
    kw["golden_boys"] = int(c.get("golden_boys", 0) or 0)
    if tgt_cls is Forward:
        kw.update(
            goals=int(c.get("goals", 0) or 0),
            assists=int(c.get("assists", 0) or 0),
            ga=int(c.get("ga", 0) or 0),
            golden_boots=int(c.get("golden_boots", 0) or 0),
        )
    elif tgt_cls is Midfielder:
        kw.update(
            goals=int(c.get("goals", 0) or 0),
            assists=int(c.get("assists", 0) or 0),
            ga=int(c.get("ga", 0) or 0),
            golden_boots=int(c.get("golden_boots", 0) or 0),
        )
    elif tgt_cls is Defender:
        kw.update(
            goals=int(c.get("goals", 0) or 0),
            assists=int(c.get("assists", 0) or 0),
            ga=int(c.get("ga", 0) or 0),
            golden_boots=int(c.get("golden_boots", 0) or 0),
        )
    else:
        kw.update(
            clean_sheets=int(c.get("clean_sheets", 0) or 0),
            missed_goals=int(c.get("missed_goals", 0) or 0),
            golden_boots=int(c.get("golden_boots", 0) or 0),
            golden_gloves=int(c.get("golden_gloves", 0) or 0),
        )
    return kw


def _carry_from_row(row: Any) -> dict[str, Any]:
    out: dict[str, Any] = {
        "matches": getattr(row, "matches", 0),
        "trophies": getattr(row, "trophies", 0),
        "golden_balls": getattr(row, "golden_balls", 0),
    }
    if hasattr(row, "goals"):
        out["goals"] = getattr(row, "goals", 0)
        out["assists"] = getattr(row, "assists", 0)
        out["ga"] = getattr(row, "ga", 0)
    if hasattr(row, "golden_boots"):
        out["golden_boots"] = getattr(row, "golden_boots", 0)
    if hasattr(row, "golden_boys"):
        out["golden_boys"] = getattr(row, "golden_boys", 0)
    if hasattr(row, "clean_sheets") and not hasattr(row, "goals"):
        out["clean_sheets"] = getattr(row, "clean_sheets", 0)
    if hasattr(row, "missed_goals"):
        out["missed_goals"] = getattr(row, "missed_goals", 0)
    if hasattr(row, "golden_gloves"):
        out["golden_gloves"] = getattr(row, "golden_gloves", 0)
    return out


def upsert_roster_player(
    session,
    *,
    team: str,
    name: str,
    position: str,
    overall: int,
    nation: str | None,
    status: str,
    carry_in: dict[str, Any] | None = None,
    lineup_slot: str | None = None,
    preferred_person_id: int | None = None,
) -> str:
    name = normalize_player_name_for_db(name)
    st = status.strip().lower()
    if st not in ("start", "bench", "reserve"):
        raise ValueError(f"status must be start|bench|reserve, got {status!r}")

    from utils.lineup_slot import normalize_lineup_slot

    slot_val: str | None = None
    if st == "start" and lineup_slot:
        slot_val = normalize_lineup_slot(lineup_slot)

    from utils.player_identity import resolve_canonical_name

    lookup_name = resolve_canonical_name(team, name)
    tgt_cls = _cls_for_position(position)
    row, cur_cls, dedupe_carry, dedupe_pid = _resolve_roster_row(
        session,
        name,
        team,
        preferred_person_id=preferred_person_id,
    )
    if row is None and _norm_cmp(lookup_name) != _norm_cmp(name):
        row, cur_cls, dedupe_carry, dedupe_pid = _resolve_roster_row(
            session,
            lookup_name,
            team,
            preferred_person_id=preferred_person_id,
        )
    pos_u = position.strip().upper()
    insert_carry = carry_in
    if dedupe_carry is not None:
        insert_carry = dedupe_carry

    if row is None:
        from utils.person_registry import (
            allocate_person_id,
            lookup_canonical_person_id,
            lookup_canonical_person_id_by_team,
            row_person_id,
        )

        new_pid = (
            int(preferred_person_id)
            if preferred_person_id is not None and int(preferred_person_id) > 0
            else dedupe_pid
            or lookup_canonical_person_id_by_team(name, team=team)
            or lookup_canonical_person_id(name, pos_u, team=team)
            or allocate_person_id(notes=f"{name} · {team}")
        )
        session.add(
            tgt_cls(
                **_new_player_kwargs(
                    tgt_cls,
                    name=name,
                    team=team,
                    position=pos_u,
                    overall=overall,
                    nation=nation,
                    status=st,
                    carry=insert_carry,
                    person_id=new_pid,
                    lineup_slot=slot_val,
                )
            )
        )
        return "inserted"

    if cur_cls is not tgt_cls:
        from utils.person_registry import ensure_row_person_id, row_person_id

        carry = _carry_from_row(row)
        keep_pid = row_person_id(row) or ensure_row_person_id(
            row, notes=f"{name} · {team}", persist=True
        )
        from utils.person_registry import lookup_canonical_person_id_by_team

        canon_pid = lookup_canonical_person_id_by_team(name, team=team)
        if canon_pid:
            keep_pid = canon_pid
        session.delete(row)
        session.flush()
        session.add(
            tgt_cls(
                **_new_player_kwargs(
                    tgt_cls,
                    name=(row.name or name).strip(),
                    team=team,
                    position=pos_u,
                    overall=overall,
                    nation=nation,
                    status=st,
                    carry=carry,
                    person_id=keep_pid,
                    lineup_slot=slot_val,
                )
            )
        )
        return "moved"

    row.name = name
    row.position = pos_u
    row.overall = int(overall)
    row.nation = (nation.strip() if nation else None) or None
    row.status = st
    from utils.person_registry import lookup_canonical_person_id_by_team, row_person_id

    canon_pid = lookup_canonical_person_id_by_team(name, team=team)
    if canon_pid and row_person_id(row) != canon_pid:
        row.person_id = canon_pid
    if preferred_person_id is not None and int(preferred_person_id) > 0:
        if row_person_id(row) is None:
            row.person_id = int(preferred_person_id)
    if hasattr(row, "lineup_slot"):
        row.lineup_slot = slot_val
    if hasattr(row, "left_team"):
        row.left_team = False
    return "updated"


def consolidate_player_team_duplicates(
    session, *, team: str | None = None
) -> dict[str, int]:
    """
    Слить дубли «один игрок — один клуб — две строки» в одну строку (все таблицы).
    """
    from collections import defaultdict

    from utils.player_names import player_name_identity_token

    buckets: dict[tuple[str, str], list[tuple[Any, type]]] = defaultdict(list)
    for Cls in _ALL_PLAYER:
        q = session.query(Cls)
        if team:
            q = q.filter(_filter_team(Cls, team))
        for r in q.all():
            if getattr(r, "left_team", False):
                continue
            ident = player_name_identity_token(getattr(r, "name", "") or "").casefold()
            tm = _norm_cmp(getattr(r, "team", "") or "")
            if ident and tm:
                buckets[(ident, tm)].append((r, Cls))

    log = {"groups_merged": 0, "rows_deleted": 0}
    for (_ident, _tm), found in buckets.items():
        if len(found) <= 1:
            continue
        nm = (found[0][0].name or "").strip()
        club = (found[0][0].team or "").strip()
        before = len(found)
        _dedupe_player_rows_for_team(session, nm, club)
        log["groups_merged"] += 1
        log["rows_deleted"] += before - 1
    return log


def delete_team_players_not_in_names(session, team: str, roster_names: set[str]) -> int:
    nset = {n.strip().lower() for n in roster_names}
    deleted = 0
    for Cls in _ALL_PLAYER:
        for r in session.query(Cls).filter(_filter_team(Cls, team)).all():
            if (r.name or "").strip().lower() not in nset:
                session.delete(r)
                deleted += 1
    return deleted


def sync_team_roster(
    session,
    team: str,
    rows: list[tuple[str, str, int, str | None, str]],
    *,
    prune: bool = True,
) -> dict[str, int]:
    stats: dict[str, int] = {"inserted": 0, "updated": 0, "moved": 0, "deleted": 0}
    names = {r[0] for r in rows}
    if prune:
        stats["deleted"] = delete_team_players_not_in_names(session, team, names)
    for name, position, overall, nation, status in rows:
        k = upsert_roster_player(
            session,
            team=team,
            name=name,
            position=position,
            overall=overall,
            nation=nation,
            status=status,
        )
        stats[k] += 1
    return stats


RosterRow = tuple[str, str, int, Optional[str], str]


def run_squads_sync(
    squads: dict[str, list[RosterRow]],
    *,
    label: str = "squads",
    tournaments: tuple[str, ...] | None = None,
    rebuild_common: bool = True,
    prune: bool = True,
) -> dict[str, dict[str, dict[str, int]]]:
    """
    Миграция ``status`` во все SQLite (лига + ЛЧ + common), затем синк переданного словаря заявок.

    Для ``cl`` — только команды из ``_team_in_cl_pool`` (участники ЛЧ).

    ``prune``: если True — удалить из команды строк игроков, которых нет в переданной заявке.
    Если False — только upsert по списку; лишние строки в БД не трогаются (стата не теряется
    из‑за расхождения имён).
    """
    from utils.migrate_player_status import migrate_all_player_status_columns

    migrate_all_player_status_columns()
    if not squads:
        raise RuntimeError(f"Словарь заявок пуст ({label}).")

    keys = tournaments if tournaments is not None else ("league", "cl")
    out: dict[str, dict[str, dict[str, int]]] = {}
    for tkey in keys:
        session = get_session(tkey)
        per_team: dict[str, dict[str, int]] = {}
        for team, rows in squads.items():
            if tkey in ("cl", "champ_league") and not _team_in_cl_pool(team):
                continue
            per_team[team] = sync_team_roster(session, team, rows, prune=prune)
        session.commit()
        out[tkey] = per_team
    if rebuild_common:
        from utils.common_db import rebuild_common_database

        rebuild_common_database()
    return out


def _cl_teams_dict_from_sqlite(cl_path: str) -> dict[str, Any]:
    """Клубы, для которых строки из БД ЛЧ участвуют в merge common (как пул участников этого файла)."""
    names: set[str] = set()
    conn = sqlite3.connect(cl_path)
    try:
        for tbl in ("forwards", "midfielders", "defenders", "goalkeepers"):
            try:
                for (t,) in conn.execute(
                    f"SELECT DISTINCT team FROM {tbl} "  # noqa: S608
                    "WHERE team IS NOT NULL AND trim(team) != ''"
                ):
                    s = str(t).strip()
                    if s:
                        names.add(s)
            except sqlite3.OperationalError:
                pass
    finally:
        conn.close()
    out = dict.fromkeys(sorted(names), True)
    if not out:
        import teams as teams_mod

        return dict.fromkeys(teams_mod.teams_champ_league.keys(), True)
    return out


def run_squads_sync_on_disk_paths(
    league_path: str,
    cl_path: str,
    common_path: str,
    squads: dict[str, list[RosterRow]] | None = None,
    *,
    prune: bool = False,
    tournaments: tuple[str, ...] | None = None,
    rebuild_common: bool = True,
) -> dict[str, dict[str, dict[str, int]]]:
    """
    Тот же синк заявок, что ``run_squads_sync``, но по **явным** путям к SQLite (архив сезона,
    накопительные *_synced.db и т.д.). Без вызова ``migrate_all_player_status_columns`` —
    схему мигрируйте отдельно при необходимости.

    Для ЛЧ пул клубов берётся из ``cl_path`` (DISTINCT team), чтобы архив не фильтровался
    текущим pickle ЛЧ.
    """
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker

    from utils.common_db import rebuild_common_database_for_disk_paths
    from utils.merged_national_squads import merged_national_squads

    if squads is None:
        squads = merged_national_squads()
    if not squads:
        raise RuntimeError("Словарь заявок пуст.")
    if not os.path.isfile(league_path) or not os.path.isfile(cl_path):
        raise FileNotFoundError(
            f"Нет league или cl: {league_path!s} / {cl_path!s}"
        )

    keys = tournaments if tournaments is not None else ("league", "cl")
    el = create_engine(f"sqlite:///{league_path}")
    ec = create_engine(f"sqlite:///{cl_path}")
    Sl = sessionmaker(bind=el)
    Scl = sessionmaker(bind=ec)
    sl, scl = Sl(), Scl()
    import teams as teams_mod

    saved_cl = teams_mod.teams_champ_league
    try:
        teams_mod.teams_champ_league = _cl_teams_dict_from_sqlite(cl_path)
        out: dict[str, dict[str, dict[str, int]]] = {}
        for tkey in keys:
            session = sl if tkey == "league" else scl
            per_team: dict[str, dict[str, int]] = {}
            for team, rows in squads.items():
                if tkey in ("cl", "champ_league") and not _team_in_cl_pool(team):
                    continue
                per_team[team] = sync_team_roster(session, team, rows, prune=prune)
            session.commit()
            out[tkey] = per_team
    finally:
        teams_mod.teams_champ_league = saved_cl

    sl.close()
    scl.close()
    el.dispose()
    ec.dispose()

    if rebuild_common:
        saved2 = teams_mod.teams_champ_league
        try:
            teams_mod.teams_champ_league = _cl_teams_dict_from_sqlite(cl_path)
            rebuild_common_database_for_disk_paths(league_path, cl_path, common_path)
        finally:
            teams_mod.teams_champ_league = saved2
    return out


def run_all_national_leagues_roster_sync(
    *,
    prune: bool = False,
    rebuild_common: bool = True,
    tournaments: tuple[str, ...] | None = None,
) -> dict[str, dict[str, dict[str, int]]]:
    """
    Заявки **всех** нац. лиг из кода (АПЛ, Бундес, Серия А, Ла Лига, РПЛ) → рабочие league/cl (+ common).

    По умолчанию ``prune=False``: не удалять игроков вне списка заявки (безопаснее для статистики).
    Обновляются ``overall``, ``position``, ``nation``, ``status``; при смене позиции — перенос
    между таблицами с сохранением carry (матчи, голы, …).
    """
    from utils.merged_national_squads import merged_national_squads

    squads = merged_national_squads()
    return run_squads_sync(
        squads,
        label="all_national_leagues",
        tournaments=tournaments,
        rebuild_common=rebuild_common,
        prune=prune,
    )


def run_full_england_sync(
    *,
    tournaments: tuple[str, ...] | None = None,
    rebuild_common: bool = True,
) -> dict[str, dict[str, dict[str, int]]]:
    from data.england_apl_squads import ENGLAND_APL_SQUADS

    return run_squads_sync(
        ENGLAND_APL_SQUADS,
        label="ENGLAND_APL_SQUADS",
        tournaments=tournaments,
        rebuild_common=rebuild_common,
    )


def run_bundesliga_sync(
    *,
    tournaments: tuple[str, ...] | None = None,
    rebuild_common: bool = True,
) -> dict[str, dict[str, dict[str, int]]]:
    from data.germany_bundesliga_squads import GERMANY_BUNDESLIGA_SQUADS

    return run_squads_sync(
        GERMANY_BUNDESLIGA_SQUADS,
        label="GERMANY_BUNDESLIGA_SQUADS",
        tournaments=tournaments,
        rebuild_common=rebuild_common,
    )


def run_italy_seria_sync(
    *,
    tournaments: tuple[str, ...] | None = None,
    rebuild_common: bool = True,
) -> dict[str, dict[str, dict[str, int]]]:
    from data.italy_seria_a_squads import ITALY_SERIE_A_SQUADS

    return run_squads_sync(
        ITALY_SERIE_A_SQUADS,
        label="ITALY_SERIE_A_SQUADS",
        tournaments=tournaments,
        rebuild_common=rebuild_common,
    )


def run_spain_la_liga_sync(
    *,
    tournaments: tuple[str, ...] | None = None,
    rebuild_common: bool = True,
) -> dict[str, dict[str, dict[str, int]]]:
    from data.spain_la_liga_squads import SPAIN_LA_LIGA_SQUADS

    return run_squads_sync(
        SPAIN_LA_LIGA_SQUADS,
        label="SPAIN_LA_LIGA_SQUADS",
        tournaments=tournaments,
        rebuild_common=rebuild_common,
    )


def run_russia_rpl_sync(
    *,
    tournaments: tuple[str, ...] | None = None,
    rebuild_common: bool = True,
) -> dict[str, dict[str, dict[str, int]]]:
    from data.russia_rpl_squads import RUSSIA_RPL_SQUADS

    return run_squads_sync(
        RUSSIA_RPL_SQUADS,
        label="RUSSIA_RPL_SQUADS",
        tournaments=tournaments,
        rebuild_common=rebuild_common,
    )
