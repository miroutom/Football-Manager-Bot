# -*- coding: utf-8 -*-
"""
Трансфер игрока: новая строка в клубе «куда», строка в клубе «откуда» **остаётся** со статой.

В ``league.db`` / ``champions_league.db`` после трансфера:
  - у **прежнего** клуба — та же строка (имя+позиция+клуб), стата не трогаем,
    выставляется ``left_team=True`` (в заявке/ростере не показывается, в голеадорах клуба — да);
  - у **нового** клуба — новая строка с нулевой полевой статой, overall/нация/заявка как в боте.
  - **ЛЧ, правило 1:** клуб «откуда» не в пуле ЛЧ → игрока нет в ``champions_league.db``,
    клуб «куда» в пуле → новая строка в ЛЧ из свежей записи ``league.db``
    (``_ensure_cl_mirror_from_league_destination``).
  - **ЛЧ, правило 2:** игрок уже есть в ``champions_league.db`` у «откуда» → как в league:
    ``left_team`` у старого клуба, новая строка в «куда» (стата ЛЧ с нуля у нового клуба).

Раньше менялось только поле ``team`` — стата «уезжала» с игроком; это исправлено.

При переходе **между** нац. лигами сбрасывается накопление жк к 4-й в JSON (не колонки
``yellow_cards`` в БД). См. ``reset_yellow_accumulation_for_player``.

Дополнительно: удаление строк из БД ЛЧ (один игрок или вся команда), затем пересборка common.
CLI: см. ``python utils/player_transfer.py -h``.
Поиск строки в league: ``search-league подстрока [--team подстрока_клуба]``.
Правка по id: ``fix-league-id midfielders 123 --assists 3``.
"""
from __future__ import annotations

import logging
import sys
from pathlib import Path
from typing import Any, Literal

_ROOT = Path(__file__).resolve().parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from sqlalchemy import and_, func, or_

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
        if "-" in part:
            part = "-".join(
                (p[:1].upper() + p[1:].lower()) if len(p) > 1 else p.upper()
                for p in part.split("-")
                if p
            )
            parts.append(part)
            continue
        if len(part) == 1:
            parts.append(part.upper())
        else:
            parts.append(part[0].upper() + part[1:].lower())
    return " ".join(parts)


def _player_left_team(row: Any) -> bool:
    return bool(getattr(row, "left_team", False))


def _filter_team(Cls, team: str, *, include_left: bool = False):
    """Строки клуба; по умолчанию без ушедших (``left_team``)."""
    t = (team or "").strip()
    tl = t.lower()
    cond = or_(Cls.team == t, func.lower(Cls.team) == tl)
    if not include_left and hasattr(Cls, "left_team"):
        cond = and_(cond, Cls.left_team.is_(False))
    return cond


def mark_player_left_team(row: Any) -> None:
    """Игрок больше не в заявке клуба; ``team`` и стата не меняются."""
    row.left_team = True
    if hasattr(row, "status"):
        row.status = None


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


def _row_exists_at_team(sess, Cls, name: str, team: str, position: str) -> bool:
    want_name = _norm_cmp(name)
    want_pos = _norm_cmp(position)
    tn = _norm_cmp(team)
    for r in sess.query(Cls).filter(_filter_team(Cls, team)).all():
        if _norm_cmp(getattr(r, "name", "") or "") != want_name:
            continue
        if _norm_cmp(getattr(r, "position", "") or "") != want_pos:
            continue
        if _norm_cmp(getattr(r, "team", "") or "") != tn:
            continue
        return True
    return False


def _insert_fresh_row_at_team(
    sess,
    Cls,
    src,
    to_team: str,
    position: str,
    new_status: str | None,
    *,
    new_overall: int | None = None,
    nation_update: bool = False,
    new_nation: str | None = None,
) -> None:
    """Новая строка в ``to_team``; полевая стата с нуля, overall/нация из трансфера."""
    from utils.person_registry import ensure_row_person_id

    pos_u = position.strip().upper()
    ovr = int(new_overall) if new_overall is not None else int(getattr(src, "overall", 0) or 72)
    nat = (new_nation or "").strip() or None if nation_update else getattr(src, "nation", None)
    if nat is not None and isinstance(nat, str):
        nat = nat.strip() or None
    person_id = ensure_row_person_id(src, persist=True)
    sess.flush()
    kw = _new_player_kwargs(
        Cls,
        name=str(getattr(src, "name", "") or ""),
        team=to_team,
        position=pos_u,
        overall=ovr,
        nation=nat if nation_update else getattr(src, "nation", None),
        person_id=person_id,
    )
    row = Cls(**kw)
    sess.add(row)
    sess.flush()
    _cascade_status(sess, Cls, to_team, pos_u, row, new_status)


def _positions_compatible(want: str, have: str) -> bool:
    """Смежные позиции при подписании FA (ЦП↔ЦОП, фланги, борьба)."""
    w, h = _norm_cmp(want), _norm_cmp(have)
    if not w or not h:
        return True
    if w == h:
        return True
    alias_groups = (
        ("ЦП", "ЦОП"),
        ("ЛФА", "ПФА"),
        ("ЛЗ", "ПЗ"),
    )
    for a, b in alias_groups:
        if {w, h} == {_norm_cmp(a), _norm_cmp(b)}:
            return True
    return False


def _find_fa_donor(fa_sess, player: str, position: str) -> tuple[type | None, Any | None]:
    want_name = _norm_cmp(player)
    want_pos = _norm_cmp(position)
    hits: list[tuple[type, Any, int]] = []
    for Cls in _ALL_PLAYER:
        for r in fa_sess.query(Cls).all():
            if _norm_cmp(getattr(r, "name", "") or "") != want_name:
                continue
            rp = _norm_cmp(getattr(r, "position", "") or "")
            if want_pos and rp == want_pos:
                score = 3
            elif _positions_compatible(position, rp):
                score = 2
            elif not want_pos:
                score = 1
            else:
                continue
            hits.append((Cls, r, score))
    if not hits:
        return None, None
    Cls, row, _ = max(hits, key=lambda x: (x[2], int(getattr(x[1], "overall", 0) or 0)))
    return Cls, row


def _find_active_club_source(sess, player: str, position: str) -> tuple[str, str] | None:
    """Если в экспорте ошибочно FA, а игрок ещё в клубе — вернуть (club, position)."""
    from utils.free_agents_db import is_free_agent_team

    want_name = _norm_cmp(player)
    want_pos = _norm_cmp(position)
    hits: list[tuple[str, str, int]] = []
    for Cls in _ALL_PLAYER:
        q = sess.query(Cls)
        if hasattr(Cls, "left_team"):
            q = q.filter(Cls.left_team.is_(False))
        for r in q.all():
            if _norm_cmp(getattr(r, "name", "") or "") != want_name:
                continue
            team = (getattr(r, "team", "") or "").strip()
            if not team or is_free_agent_team(team):
                continue
            rp = _norm_cmp(getattr(r, "position", "") or "")
            if want_pos and rp == want_pos:
                score = 3
            elif _positions_compatible(position, rp):
                score = 2
            elif not want_pos:
                score = 1
            else:
                score = 0
            if score <= 0:
                continue
            hits.append((team, (getattr(r, "position", "") or "").strip().upper(), score))
    if not hits:
        return None
    team, pos, _ = max(hits, key=lambda x: (x[2], x[1]))
    if not pos:
        return None
    return team, pos


def _player_already_at_team(sess, player: str, team: str, position: str) -> bool:
    for Cls in _ALL_PLAYER:
        if _row_exists_at_team(sess, Cls, player, team, position):
            return True
    return False


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
    """Трансфер: копия в новый клуб, стата остаётся у прежнего; коммитит обе сессии."""
    player = player.strip()
    from_team = from_team.strip()
    to_team = to_team.strip()
    position = position.strip()

    counts: dict[str, int] = {"league": 0, "cl": 0}
    if _player_already_at_team(sess_league, player, to_team, position):
        st = (new_status or "bench")
        st = str(st).strip().lower() if st else "bench"
        if st not in ("start", "bench", "reserve"):
            st = "bench"
        counts["cl"] = _ensure_cl_mirror_from_league_destination(
            sess_league,
            sess_cl,
            player,
            to_team,
            position,
            st,
            new_overall=new_overall,
            nation_update=nation_update,
            new_nation=new_nation,
        )
        if counts["cl"]:
            sess_cl.commit()
        return counts
    want_name = _norm_cmp(player)
    want_pos = _norm_cmp(position)

    def _run_session(sess, key: str) -> None:
        sources: list[tuple[type, Any]] = []
        for Cls in _ALL_PLAYER:
            for r in sess.query(Cls).filter(
                _filter_team(Cls, from_team, include_left=True)
            ).all():
                if _norm_cmp(getattr(r, "name", "") or "") != want_name:
                    continue
                sources.append((Cls, r))
        if not sources:
            return

        def _donor_score(item: tuple[type, Any]) -> tuple:
            _Cls, row = item
            pos_match = (
                _norm_cmp(getattr(row, "position", "") or "") == want_pos
            )
            return (
                pos_match,
                int(getattr(row, "matches", 0) or 0),
                int(getattr(row, "id", 0) or 0),
            )

        donor_cls, donor = max(sources, key=_donor_score)
        from utils.person_registry import ensure_row_person_id

        for _Cls, r in sources:
            ensure_row_person_id(r, persist=True)
        if _row_exists_at_team(sess, donor_cls, player, to_team, position):
            return
        _insert_fresh_row_at_team(
            sess,
            donor_cls,
            donor,
            to_team,
            position,
            new_status,
            new_overall=new_overall,
            nation_update=nation_update,
            new_nation=new_nation,
        )
        for Cls, r in sources:
            mark_player_left_team(r)
            counts[key] += 1

    _run_session(sess_league, "league")
    sess_league.commit()
    _run_session(sess_cl, "cl")
    if counts["league"] > 0 and counts["cl"] == 0:
        counts["cl"] = _ensure_cl_mirror_from_league_destination(
            sess_league,
            sess_cl,
            player,
            to_team,
            position,
            new_status,
            new_overall=new_overall,
            nation_update=nation_update,
            new_nation=new_nation,
        )
    sess_cl.commit()
    return counts


def _find_active_row_at_team(sess, player: str, team: str, position: str) -> tuple[type, Any] | None:
    want_name = _norm_cmp(player)
    want_pos = _norm_cmp(position)
    for Cls in _ALL_PLAYER:
        for r in sess.query(Cls).filter(_filter_team(Cls, team)).all():
            if _norm_cmp(getattr(r, "name", "") or "") != want_name:
                continue
            if want_pos and _norm_cmp(getattr(r, "position", "") or "") != want_pos:
                continue
            return Cls, r
    return None


def _ensure_cl_mirror_from_league_destination(
    sess_league,
    sess_cl,
    player: str,
    to_team: str,
    position: str,
    new_status: str | None,
    *,
    new_overall: int | None = None,
    nation_update: bool = False,
    new_nation: str | None = None,
) -> int:
    """
    Правило 1: донора не было в БД ЛЧ (клуб «откуда» вне пула ЛЧ) — после записи в
    ``league.db`` создать зеркало в ``champions_league.db`` для клуба «куда» из пула ЛЧ.
    """
    from utils.common_db import _team_in_cl_pool

    if not _team_in_cl_pool(to_team):
        return 0
    hit = _find_active_row_at_team(sess_league, player, to_team, position)
    if hit is None:
        return 0
    donor_cls, donor = hit
    if _row_exists_at_team(sess_cl, donor_cls, player, to_team, position):
        return 0
    _insert_fresh_row_at_team(
        sess_cl,
        donor_cls,
        donor,
        to_team,
        position,
        new_status if new_status is not None else getattr(donor, "status", None),
        new_overall=new_overall,
        nation_update=nation_update,
        new_nation=new_nation,
    )
    return 1


def backfill_cl_rows_from_league(*, rebuild_common: bool = True) -> list[str]:
    """
    Строки в league у клубов пула ЛЧ, которых нет в champions_league.db
    (типично после трансфера из клуба вне ЛЧ).
    """
    from utils.common_db import _team_in_cl_pool
    from utils.utils import session_cl, session_league

    log: list[str] = []
    for Cls in _ALL_PLAYER:
        for r in session_league.query(Cls).filter(Cls.left_team.is_(False)).all():
            team = (getattr(r, "team", None) or "").strip()
            if not team or not _team_in_cl_pool(team):
                continue
            name = (getattr(r, "name", None) or "").strip()
            pos = (getattr(r, "position", None) or "").strip()
            if not name or not pos:
                continue
            if _row_exists_at_team(session_cl, Cls, name, team, pos):
                continue
            st = (getattr(r, "status", None) or "bench").strip().lower()
            if st not in ("start", "bench", "reserve"):
                st = "bench"
            _insert_fresh_row_at_team(
                session_cl,
                Cls,
                r,
                team,
                pos,
                st,
            )
            log.append(f"{Cls.__tablename__}: {name} {pos} · {team}")
    session_cl.commit()
    if log and rebuild_common:
        from utils.common_db import rebuild_common_database

        rebuild_common_database()
    return log


def _apply_fa_sign_with_status(
    player: str,
    from_team: str,
    position: str,
    to_team: str,
    new_status: str | None,
    *,
    new_overall: int | None = None,
) -> dict[str, int]:
    """Подписание из ``free_agents.db`` в клуб."""
    from utils.free_agents_db import is_free_agent_team, open_fa_session, remove_free_agent_after_signing
    from utils.utils import session_cl, session_league

    if not is_free_agent_team(from_team):
        raise ValueError(f"Не свободный агент: {from_team!r}")

    fa_sess, fa_eng = open_fa_session()
    counts: dict[str, int] = {"league": 0, "cl": 0}
    donor = None
    donor_cls = None
    try:
        donor_cls, donor = _find_fa_donor(fa_sess, player, position)
        if donor is None or donor_cls is None:
            src = _find_active_club_source(session_league, player, position)
            if src is not None:
                actual_team, actual_pos = src
                return _apply_transfer_with_status_to_sessions(
                    session_league,
                    session_cl,
                    player,
                    actual_team,
                    actual_pos,
                    to_team,
                    new_status,
                    new_overall=new_overall,
                )
            raise ValueError(f"Свободный агент не найден: {player} ({position})")

        pos_u = (position or getattr(donor, "position", "") or "").strip().upper()
        donor_pos = (getattr(donor, "position", "") or pos_u).strip().upper()
        st = (new_status or getattr(donor, "status", None) or "bench")
        st = str(st).strip().lower() if st else "bench"
        if st not in ("start", "bench", "reserve"):
            st = "bench"

        if _player_already_at_team(session_league, player, to_team, pos_u):
            counts["cl"] = _ensure_cl_mirror_from_league_destination(
                session_league,
                session_cl,
                player,
                to_team,
                pos_u,
                st,
                new_overall=new_overall,
            )
            if counts["cl"]:
                session_cl.commit()
            remove_free_agent_after_signing(player, donor_pos)
            return counts

        _insert_fresh_row_at_team(
            session_league,
            donor_cls,
            donor,
            to_team,
            pos_u,
            st,
            new_overall=new_overall,
        )
        counts["league"] = 1
        session_league.commit()

        counts["cl"] = _ensure_cl_mirror_from_league_destination(
            session_league,
            session_cl,
            player,
            to_team,
            pos_u,
            st,
            new_overall=new_overall,
        )
        session_cl.commit()
    finally:
        fa_sess.close()
        fa_eng.dispose()

    remove_free_agent_after_signing(player, donor_pos)
    return counts


def _apply_release_to_fa_with_status(
    player: str,
    from_team: str,
    position: str,
    new_status: str | None,
    *,
    new_overall: int | None = None,
) -> dict[str, int]:
    """Снять с заявки клуба → ``free_agents.db`` (трансфер OUT в FA)."""
    from utils.free_agents_db import is_free_agent_team, release_club_player_to_fa

    if is_free_agent_team(from_team):
        raise ValueError(f"Игрок уже свободный агент: {from_team!r}")
    st = (new_status or "bench")
    st = str(st).strip().lower() if st else "bench"
    if st not in ("start", "bench", "reserve"):
        st = "bench"
    release_club_player_to_fa(
        player,
        position,
        from_team,
        new_status=st,
        new_overall=new_overall,
    )
    return {"league": 1, "cl": 0, "fa": 1}


def apply_transfer_with_status(
    player: str,
    from_team: str,
    position: str,
    to_team: str,
    new_status: str | None,
    *,
    rebuild_common: bool = True,
    mirror_synced: bool = True,
    new_overall: int | None = None,
    nation_update: bool = False,
    new_nation: str | None = None,
) -> dict[str, int]:
    """
    Трансфер + заявка в новом клубе. ``new_status`` is None — сброс status (старое поведение).
    """
    from utils.free_agents_db import is_free_agent_team
    from utils.utils import session_cl, session_league

    if is_free_agent_team(from_team):
        counts = _apply_fa_sign_with_status(
            player,
            from_team,
            position,
            to_team,
            new_status,
            new_overall=new_overall,
        )
        if rebuild_common:
            from utils.common_db import rebuild_common_database

            rebuild_common_database()
        if mirror_synced:
            from utils import cumulative_mirror

            cumulative_mirror.mirror_transfer_with_status(
                player,
                from_team,
                position,
                to_team,
                new_status,
                new_overall=new_overall,
            )
        return counts

    if is_free_agent_team(to_team):
        counts = _apply_release_to_fa_with_status(
            player,
            from_team,
            position,
            new_status,
            new_overall=new_overall,
        )
        if rebuild_common:
            from utils.common_db import rebuild_common_database

            rebuild_common_database()
        if mirror_synced:
            from utils import cumulative_mirror

            cumulative_mirror.mirror_transfer_with_status(
                player,
                from_team,
                position,
                to_team,
                new_status,
                new_overall=new_overall,
            )
        return counts

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

    from player_stats import national_league_code_for_team
    from utils.player_discipline import reset_yellow_accumulation_for_player

    from_lc = national_league_code_for_team(from_team)
    to_lc = national_league_code_for_team(to_team)
    if from_lc and to_lc and from_lc != to_lc:
        reset_yellow_accumulation_for_player(
            player,
            league_codes=[from_lc, to_lc],
            include_cl=False,
        )

    from utils.player_discipline import migrate_cl_discipline_team

    migrate_cl_discipline_team(player, to_team)

    if mirror_synced:
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
    Ищет игрока в клубе «откуда», добавляет строку в клуб «куда» (стата там с нуля).
    Строка в старом клубе и её матчи/голы/передачи не меняются.

    Возвращает счётчики **добавленных** строк: ``league``, ``cl``.
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
    person_id: int | None = None,
) -> dict[str, Any]:
    u = max(1, min(99, int(overall)))
    pos_u = position.strip().upper()
    nat = (nation or "").strip() or None
    full = normalize_player_name_for_db(name) or (name or "").strip()
    kw: dict[str, Any] = dict(
        name=full,
        team=team.strip(),
        position=pos_u,
        overall=u,
        matches=0,
        trophies=0,
        golden_balls=0,
        nation=nat,
        status=None,
        left_team=False,
        person_id=int(person_id) if person_id is not None else None,
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


def add_player_to_club_sessions(
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

    from utils.person_registry import allocate_person_id

    new_pid = allocate_person_id(notes=f"{player} · {to_team}")
    kw = _new_player_kwargs(
        Cls,
        name=player,
        team=to_team,
        position=position,
        overall=overall,
        nation=nation,
        person_id=new_pid,
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


def add_player_to_club(
    player: str,
    position: str,
    to_team: str,
    new_status: str,
    overall: int = 72,
    *,
    nation: str | None = None,
    rebuild_common: bool = True,
) -> dict[str, int]:
    """Новый игрок в клуб: вставка в нац. БД и в БД ЛЧ, если клуб в пуле ЛЧ."""
    from utils.utils import session_cl, session_league

    counts = add_player_to_club_sessions(
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

    cumulative_mirror.mirror_add_player_to_club(
        player, position, to_team, new_status, overall, nation=nation
    )
    return counts


# Устаревшие имена (скрипты/импорты)
_add_free_agent_to_sessions = add_player_to_club_sessions
add_free_agent = add_player_to_club


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
