# -*- coding: utf-8 -*-
"""
Отдельная БД свободных агентов ``db/free_agents.db`` (не строки в ``league.db``).

Игроки с ЧМ и новые без клуба живут здесь с ``person_id``; трансфер IN забирает
строку отсюда и создаёт активную заявку в ``league.db`` / ``champions_league.db``.
"""
from __future__ import annotations

import logging
import os
import shutil
from typing import Any

from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from data.defender import Defender
from data.forward import Forward
from data.goalkeeper import Goalkeeper
from data.midfielder import Midfielder
from utils.roster_manual import FREE_AGENT_TEAM
from utils.utils import Base, PROJECT_ROOT

logger = logging.getLogger(__name__)

_ALL = (Forward, Midfielder, Defender, Goalkeeper)
_FA_DB = os.path.join(PROJECT_ROOT, "db", "free_agents.db")


def get_free_agents_db_path() -> str:
    return _FA_DB


def _fa_db_has_player_tables(path: str) -> bool:
    import sqlite3

    if not os.path.isfile(path):
        return False
    conn = sqlite3.connect(path)
    try:
        row = conn.execute(
            "SELECT 1 FROM sqlite_master WHERE type='table' AND name='forwards' LIMIT 1"
        ).fetchone()
        return row is not None
    finally:
        conn.close()


def ensure_free_agents_db(*, template_league_path: str | None = None) -> str:
    """Создать ``free_agents.db`` по схеме ``league.db``, если файла ещё нет."""
    path = get_free_agents_db_path()
    os.makedirs(os.path.dirname(path), exist_ok=True)
    if os.path.isfile(path) and _fa_db_has_player_tables(path):
        from utils.migrate_fired import ensure_fired_schema
        from utils.migrate_lineup_slot import ensure_lineup_slot_schema

        ensure_lineup_slot_schema(path)
        ensure_fired_schema(path)
        return path
    if os.path.isfile(path):
        try:
            os.remove(path)
        except OSError:
            logger.warning("Не удалось удалить битый free_agents.db: %s", path)
    from utils import season_paths

    template = template_league_path or season_paths.get_league_db_path()
    if not os.path.isfile(template):
        raise FileNotFoundError(f"Нет шаблона league.db: {template}")
    shutil.copy2(template, path)
    import sqlite3

    conn = sqlite3.connect(path)
    try:
        tables = [
            r[0]
            for r in conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'"
            )
        ]
        for t in tables:
            conn.execute(f'DELETE FROM "{t}"')
        conn.commit()
    finally:
        conn.close()
    from utils.migrate_fired import ensure_fired_schema
    from utils.migrate_lineup_slot import ensure_lineup_slot_schema

    ensure_lineup_slot_schema(path)
    ensure_fired_schema(path)
    return path


def open_fa_session() -> tuple[Session, Any]:
    ensure_free_agents_db()
    from utils.migrate_fired import ensure_fired_schema
    from utils.migrate_lineup_slot import ensure_lineup_slot_schema

    path = get_free_agents_db_path()
    ensure_lineup_slot_schema(path)
    ensure_fired_schema(path)
    eng = create_engine(
        f"sqlite:///{path}",
        connect_args={"check_same_thread": False, "timeout": 30},
    )
    Base.metadata.create_all(eng)
    return sessionmaker(bind=eng)(), eng


def _norm_team(s: str) -> str:
    return (s or "").strip().casefold()


def is_free_agent_team(name: str | None) -> bool:
    t = _norm_team(name or "")
    return t in (_norm_team(FREE_AGENT_TEAM), "free_agent", "fa", "свободный агент")


def fa_player_id(name: str, position: str) -> str:
    return f"{FREE_AGENT_TEAM}|{(name or '').strip()}|{(position or '').strip().upper()}"


def fa_player_exists(name: str, position: str) -> bool:
    """Есть ли игрок в ``free_agents.db`` (по имени и позиции)."""
    from utils.player_transfer import _find_fa_donor, normalize_player_name_for_db
    from utils.transfer_input import normalize_position

    nm = normalize_player_name_for_db((name or "").strip())
    pos = normalize_position(position)
    if not nm or not pos:
        return False
    fa_sess, fa_eng = open_fa_session()
    try:
        _, row = _find_fa_donor(fa_sess, nm, pos)
        return row is not None
    finally:
        fa_sess.close()
        fa_eng.dispose()


def _load_fired_map(sess: Session) -> dict[tuple[str, int], bool]:
    from sqlalchemy import text
    from sqlalchemy.exc import OperationalError

    out: dict[tuple[str, int], bool] = {}
    for table in ("forwards", "midfielders", "defenders", "goalkeepers"):
        try:
            for rid, val in sess.execute(text(f'SELECT id, fired FROM "{table}"')).fetchall():
                out[(table, int(rid))] = bool(val)
        except OperationalError:
            pass
    return out


def _set_row_fired(sess: Session, table: str, row_id: int, fired: bool) -> None:
    from sqlalchemy import text

    sess.execute(
        text(f'UPDATE "{table}" SET fired = :f WHERE id = :id'),
        {"f": int(fired), "id": int(row_id)},
    )


def list_free_agents(*, include_left: bool = False) -> list[dict[str, Any]]:
    """Все свободные агенты для UI / экспорта."""
    from utils.player_names import player_display_name
    from utils.player_nicknames import get_nickname

    sess, eng = open_fa_session()
    rows: list[dict[str, Any]] = []
    try:
        fired_map = _load_fired_map(sess)
        for Cls in _ALL:
            table = Cls.__tablename__
            q = sess.query(Cls)
            if not include_left and hasattr(Cls, "left_team"):
                q = q.filter((Cls.left_team.is_(False)) | (Cls.left_team.is_(None)))
            for r in q.all():
                team = (getattr(r, "team", None) or "").strip()
                if team and not is_free_agent_team(team):
                    continue
                name = player_display_name(r)
                pos = (getattr(r, "position", None) or "").strip().upper()
                if not name or not pos:
                    continue
                pid = getattr(r, "person_id", None)
                rows.append(
                    {
                        "id": fa_player_id(name, pos),
                        "person_id": int(pid) if pid is not None else None,
                        "name": name,
                        "position": pos,
                        "overall": int(getattr(r, "overall", 0) or 0),
                        "nation": (getattr(r, "nation", None) or "") or "",
                        "nickname": get_nickname(pid) or "",
                        "status": (getattr(r, "status", None) or "bench") or "bench",
                        "fired": fired_map.get((table, int(r.id)), False),
                    }
                )
    finally:
        sess.close()
        eng.dispose()
    rows.sort(key=lambda x: (-int(x["overall"]), str(x["name"]).casefold()))
    return rows


def add_free_agent_player(
    *,
    name: str,
    position: str,
    overall: int,
    nation: str | None = None,
    status: str = "bench",
    person_id: int | None = None,
    nickname: str | None = None,
) -> dict[str, Any]:
    """Новый свободный агент (ЧМ, ручной ввод, desktop app)."""
    from utils.person_registry import allocate_person_id, ensure_row_person_id
    from utils.player_nicknames import set_nickname
    from utils.player_transfer import (
        _cls_for_position,
        _new_player_kwargs,
        normalize_player_name_for_db,
    )

    name = normalize_player_name_for_db((name or "").strip())
    position = (position or "").strip().upper()
    if not name or not position:
        raise ValueError("Нужны имя и позиция.")
    st = (status or "bench").strip().lower()
    if st not in ("start", "bench", "reserve"):
        st = "bench"

    sess, eng = open_fa_session()
    try:
        Cls = _cls_for_position(position)
        nl = name.casefold()
        pl = position.casefold()
        for r in sess.query(Cls).all():
            if (r.name or "").strip().casefold() == nl and (r.position or "").strip().casefold() == pl:
                raise ValueError(f"Свободный агент уже есть: {name} ({position})")
        pid = int(person_id) if person_id is not None else allocate_person_id(notes=f"FA · {name}")
        kw = _new_player_kwargs(
            Cls,
            name=name,
            team=FREE_AGENT_TEAM,
            position=position,
            overall=int(overall or 72),
            nation=(nation or "").strip() or None,
            person_id=pid,
        )
        row = Cls(**kw)
        if hasattr(row, "status"):
            row.status = st
        if hasattr(row, "left_team"):
            row.left_team = False
        sess.add(row)
        sess.flush()
        _set_row_fired(sess, Cls.__tablename__, int(row.id), False)
        ensure_row_person_id(row, persist=True)
        sess.commit()
        if nickname and str(nickname).strip():
            set_nickname(int(row.person_id), str(nickname).strip(), name=name, team=FREE_AGENT_TEAM)
        return {
            "id": fa_player_id(name, position),
            "person_id": int(row.person_id) if row.person_id else pid,
            "name": name,
            "position": position,
            "overall": int(row.overall or 0),
            "nation": (getattr(row, "nation", None) or "") or "",
            "nickname": (nickname or "").strip(),
            "status": st,
            "fired": False,
        }
    finally:
        sess.close()
        eng.dispose()


def delete_free_agent_player(
    *,
    name: str = "",
    position: str = "",
    person_id: int | None = None,
    fa_id: str | None = None,
) -> bool:
    """Удалить свободного агента из ``free_agents.db`` (ручное удаление из пула)."""
    nm = (name or "").strip()
    pos = (position or "").strip()
    if fa_id:
        parts = str(fa_id).split("|")
        if len(parts) >= 3:
            if not nm:
                nm = parts[1].strip()
            if not pos:
                pos = parts[2].strip()
    if person_id is not None:
        pid = int(person_id)
        if pid > 0:
            sess, eng = open_fa_session()
            removed = False
            try:
                for Cls in _ALL:
                    for r in list(sess.query(Cls).all()):
                        if getattr(r, "person_id", None) == pid:
                            sess.delete(r)
                            removed = True
                if removed:
                    sess.commit()
            finally:
                sess.close()
                eng.dispose()
            if removed:
                return True
    if nm and pos:
        return remove_free_agent_after_signing(nm, pos)
    return False


def update_free_agent_player_fields(
    name: str,
    position: str,
    *,
    new_name: str | None = None,
    new_position: str | None = None,
    new_overall: int | None = None,
    new_nation: str | None = None,
    nation_clear: bool = False,
    person_id: int | None = None,
) -> dict[str, Any]:
    """Обновить существующую строку FA (без создания новой)."""
    from utils.player_field_edit import find_player_row, parse_field_value
    from utils.player_transfer import normalize_player_name_for_db

    nm = normalize_player_name_for_db((name or "").strip())
    pos = (position or "").strip().upper()
    if not nm or not pos:
        raise ValueError("Нужны имя и позиция.")

    sess, eng = open_fa_session()
    try:
        _, row = find_player_row(sess, FREE_AGENT_TEAM, nm, pos)
        if row is None and person_id:
            for Cls in _ALL:
                for r in sess.query(Cls).all():
                    if getattr(r, "person_id", None) == int(person_id):
                        row = r
                        break
                if row is not None:
                    break
        if row is None:
            raise ValueError(f"Свободный агент не найден: {nm} ({pos})")

        Cls = type(row)
        cur_name = (row.name or "").strip()
        cur_pos = (row.position or "").strip().upper()

        if new_name is not None:
            row.name = parse_field_value(Cls, "name", str(new_name))
            cur_name = (row.name or "").strip()
        if new_position is not None:
            new_pos = parse_field_value(Cls, "position", str(new_position))
            if new_pos != cur_pos:
                from utils.player_transfer import _cls_for_position

                Target = _cls_for_position(new_pos)
                if Target is not Cls:
                    cols = {c.name for c in Target.__table__.columns}
                    data = {c: getattr(row, c) for c in cols if c != "id" and hasattr(row, c)}
                    data["position"] = new_pos
                    new_row = Target(**data)
                    sess.add(new_row)
                    sess.delete(row)
                    sess.flush()
                    row = new_row
                    Cls = Target
                else:
                    row.position = new_pos
                cur_pos = new_pos
        if new_overall is not None:
            row.overall = parse_field_value(Cls, "overall", str(new_overall))
        if nation_clear:
            row.nation = None
        elif new_nation is not None:
            nat = (str(new_nation).strip() or None)
            row.nation = nat

        sess.commit()
        pid = int(row.person_id) if getattr(row, "person_id", None) else None
        return {
            "id": fa_player_id(cur_name, cur_pos),
            "person_id": pid,
            "name": cur_name,
            "position": cur_pos,
            "overall": int(row.overall or 0),
            "nation": (getattr(row, "nation", None) or "") or "",
            "team": FREE_AGENT_TEAM,
            "is_fa": True,
        }
    finally:
        sess.close()
        eng.dispose()


def remove_free_agent_after_signing(name: str, position: str) -> bool:
    """Удалить строку FA после подписания в клуб (стата уходит в league.db)."""
    from utils.player_transfer import _find_fa_donor, _norm_cmp

    sess, eng = open_fa_session()
    removed = False
    try:
        donor_cls, donor = _find_fa_donor(sess, name, position)
        if donor is None or donor_cls is None:
            return False
        want_n = _norm_cmp(name)
        for r in list(sess.query(donor_cls).all()):
            if _norm_cmp(getattr(r, "name", "") or "") != want_n:
                continue
            if int(getattr(r, "id", 0) or 0) != int(getattr(donor, "id", 0) or 0):
                continue
            sess.delete(r)
            removed = True
        if removed:
            sess.commit()
    finally:
        sess.close()
        eng.dispose()
    return removed


def _upsert_league_row_into_fa(
    fa_sess: Session,
    row: Any,
    Cls: type,
    *,
    status: str = "bench",
    new_overall: int | None = None,
    fired: bool | None = None,
) -> tuple[Any, bool]:
    """Скопировать/обновить строку клуба в ``free_agents.db``. Возвращает (row, created_new)."""
    from utils.person_registry import ensure_row_person_id

    cols = {c.name for c in Cls.__table__.columns}
    data = {c: getattr(row, c) for c in cols if c != "id"}
    data["team"] = FREE_AGENT_TEAM
    if "left_team" in data:
        data["left_team"] = False
    if new_overall is not None:
        data["overall"] = int(new_overall)
    st = (status or "bench").strip().lower()
    if st not in ("start", "bench", "reserve"):
        st = "bench"
    if "status" in data:
        data["status"] = st

    dup = None
    want_n = (data.get("name") or "").strip().casefold()
    want_p = (data.get("position") or "").strip().casefold()
    for ex in fa_sess.query(Cls).all():
        if (ex.name or "").strip().casefold() == want_n and (
            ex.position or ""
        ).strip().casefold() == want_p:
            dup = ex
            break
    if dup is not None:
        for k, v in data.items():
            if k == "id":
                continue
            if k in ("goals", "assists", "matches", "ga", "potm", "motm", "clean_sheets"):
                cur = int(getattr(dup, k, 0) or 0)
                add = int(v or 0)
                if add > cur:
                    setattr(dup, k, add)
            elif k == "overall" and int(v or 0) > int(getattr(dup, "overall", 0) or 0):
                dup.overall = int(v)
            elif k == "person_id" and v and not getattr(dup, "person_id", None):
                dup.person_id = v
            elif k == "nation" and v and not getattr(dup, "nation", None):
                dup.nation = v
            elif k == "status":
                dup.status = v
        ensure_row_person_id(dup, persist=True)
        if fired is not None:
            _set_row_fired(fa_sess, Cls.__tablename__, int(dup.id), fired)
        return dup, False
    obj = Cls(**data)
    fa_sess.add(obj)
    fa_sess.flush()
    ensure_row_person_id(obj, persist=True)
    if fired is not None:
        _set_row_fired(fa_sess, Cls.__tablename__, int(obj.id), fired)
    return obj, True


def release_club_player_to_fa(
    name: str,
    position: str,
    from_team: str,
    *,
    new_status: str = "bench",
    new_overall: int | None = None,
) -> dict[str, Any]:
    """
    Снять игрока с активной заявки клуба → пул ``free_agents.db``.
    В league/cl строка остаётся с ``left_team=True`` (стата сезона сохраняется).
    """
    from utils.common_db import resolve_team_name_for_cl_pool
    from utils.player_field_edit import find_player_row
    from utils.player_transfer import mark_player_left_team, normalize_player_name_for_db
    from utils.transfer_input import normalize_position, resolve_team_name
    from utils.utils import session_cl, session_league

    nm = normalize_player_name_for_db((name or "").strip())
    pos = normalize_position(position)
    team_raw = (from_team or "").strip()
    if not nm or not pos or not team_raw:
        raise ValueError("Нужны имя, позиция и клуб.")

    sleague = session_league
    scl = session_cl
    team = resolve_team_name(team_raw, sleague) or team_raw
    Cls_l, row_l = find_player_row(sleague, team, nm, pos)
    if row_l is None:
        if fa_player_exists(nm, pos):
            return {
                "name": nm,
                "position": pos,
                "from_team": team,
                "person_id": None,
                "fa_id": fa_player_id(nm, pos),
                "skipped": True,
            }
        raise ValueError(f"Нет игрока «{nm}» ({pos}) в «{team}».")
    if bool(getattr(row_l, "left_team", False)):
        if fa_player_exists(nm, pos):
            return {
                "name": nm,
                "position": pos,
                "from_team": team,
                "person_id": int(row_l.person_id) if getattr(row_l, "person_id", None) else None,
                "fa_id": fa_player_id(nm, pos),
                "skipped": True,
            }
        raise ValueError(f"«{nm}» уже снят с заявки «{team}».")

    fa_sess, fa_eng = open_fa_session()
    try:
        fa_row, _created = _upsert_league_row_into_fa(
            fa_sess,
            row_l,
            Cls_l,
            status=new_status,
            new_overall=new_overall,
            fired=True,
        )
        fa_sess.commit()
        pid = int(fa_row.person_id) if getattr(fa_row, "person_id", None) else None
    finally:
        fa_sess.close()
        fa_eng.dispose()

    mark_player_left_team(row_l)
    cl_team = resolve_team_name_for_cl_pool(team)
    if cl_team:
        Cls_c, row_c = find_player_row(scl, cl_team, nm, pos)
        if row_c is not None and not bool(getattr(row_c, "left_team", False)):
            mark_player_left_team(row_c)
    sleague.commit()
    scl.commit()

    return {
        "name": nm,
        "position": pos,
        "from_team": team,
        "person_id": pid,
        "fa_id": fa_player_id(nm, pos),
    }


def migrate_free_agents_from_league_dbs(*, dry_run: bool = False) -> dict[str, int]:
    """
    Перенести все строки ``team = Free Agent`` из league/cl/common → ``free_agents.db``,
    затем удалить их из исходных БД.
    """
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker

    from utils import season_paths
    from utils.player_transfer import _ALL_PLAYER

    stats = {"migrated": 0, "removed_league": 0, "removed_cl": 0, "removed_common": 0}
    ensure_free_agents_db()
    fa_sess, fa_eng = open_fa_session()

    sources = [
        ("league", season_paths.get_league_db_path()),
        ("cl", season_paths.get_cl_db_path()),
        ("common", season_paths.get_common_db_path()),
    ]

    def _copy_row_to_fa(row, Cls) -> bool:
        nonlocal stats
        _obj, created = _upsert_league_row_into_fa(fa_sess, row, Cls)
        if created:
            stats["migrated"] += 1
        return created

    try:
        seen_keys: set[tuple[str, str]] = set()
        for label, path in sources:
            if not os.path.isfile(path):
                continue
            eng = create_engine(f"sqlite:///{path}")
            S = sessionmaker(bind=eng)
            sess = S()
            try:
                for Cls in _ALL_PLAYER:
                    for row in list(sess.query(Cls).all()):
                        team = (getattr(row, "team", None) or "").strip()
                        if not is_free_agent_team(team):
                            continue
                        key = (
                            (getattr(row, "name", "") or "").strip().casefold(),
                            (getattr(row, "position", "") or "").strip().casefold(),
                        )
                        if label == "league" or key not in seen_keys:
                            _copy_row_to_fa(row, Cls)
                            seen_keys.add(key)
                        if not dry_run:
                            sess.delete(row)
                            if label == "league":
                                stats["removed_league"] += 1
                            elif label == "cl":
                                stats["removed_cl"] += 1
                            else:
                                stats["removed_common"] += 1
                if not dry_run:
                    sess.commit()
            finally:
                sess.close()
                eng.dispose()
        if not dry_run:
            fa_sess.commit()
    finally:
        fa_sess.close()
        fa_eng.dispose()

    if not dry_run and stats["removed_league"] + stats["removed_cl"]:
        try:
            from utils.common_db import rebuild_common_database

            rebuild_common_database()
        except Exception:
            logger.exception("rebuild_common after FA migration")
    return stats
