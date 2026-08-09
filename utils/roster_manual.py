# -*- coding: utf-8 -*-
"""
Ручное добавление / удаление игрока в состав клуба (нац. БД + ЛЧ при пуле).

- Добавление: если игрок есть в ``common_synced.db`` (той же позиции) — подтягиваем carry
  из накопительной common; иначе нужны ``overall`` и ``нация``. Запись только в текущие
  рабочие БД и зеркало ``*_synced`` (архивные ``db/season_*`` не трогаем).
- Удаление: при ненулевой статистике в нац./ЛЧ ``team = Free Agent`` и ``left_team``;
  иначе строка удаляется из БД.
- Пакетная заявка: ``apply_team_squad_declaration`` + ``parse_squad_declaration_text``
  (через ``|``; «имя … позиция … start»; либо блоки ``==== start ===`` / ``=== bench ===`` /
  ``=== reserve ===`` и строки ``имя [слот] позиция [overall] [нация]`` без суффикса статуса;
  в ``start`` допускается ``имя GK ВРТ 84`` — слот на поле + позиция в БД).
  Кто в клубе не в списке, снимается тем же правилом, что и при удалении.
"""
from __future__ import annotations

import os
import re
from collections import OrderedDict
from typing import Any

from data.defender import Defender
from data.forward import Forward
from data.goalkeeper import Goalkeeper
from data.midfielder import Midfielder

from utils.lineup_slot import is_valid_lineup_slot, normalize_lineup_slot

_ALL = (Forward, Midfielder, Defender, Goalkeeper)

FREE_AGENT_TEAM = "Free Agent"

_RE_SQUAD_SECTION = re.compile(
    r"^\s*=+\s*(start|bench|reserve)\s*=+\s*$",
    re.IGNORECASE,
)


def _norm_pair(name: str, position: str) -> tuple[str, str]:
    from utils.player_transfer import _norm_cmp

    return _norm_cmp(name), _norm_cmp(position)


def _has_meaningful_stats(row: Any) -> bool:
    if int(getattr(row, "matches", 0) or 0) > 0:
        return True
    for k in (
        "goals",
        "assists",
        "trophies",
        "golden_balls",
        "golden_boots",
        "golden_boys",
        "clean_sheets",
        "missed_goals",
        "golden_gloves",
        "yellow_cards",
        "red_cards",
        "potm",
        "motm",
    ):
        if int(getattr(row, k, 0) or 0) > 0:
            return True
    return False


def _find_rows_cumulative_common(name: str, position: str) -> list[tuple[Any, type]]:
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker

    from utils.season_paths import get_cumulative_common_db_path

    path = get_cumulative_common_db_path()
    if not os.path.isfile(path):
        return []
    from utils.migrate_lineup_slot import ensure_lineup_slot_schema

    ensure_lineup_slot_schema(path)
    want_n, want_p = _norm_pair(name, position)
    eng = create_engine(f"sqlite:///{path}")
    sess = sessionmaker(bind=eng)()
    try:
        out: list[tuple[Any, type]] = []
        for Cls in _ALL:
            for r in sess.query(Cls).all():
                if _norm_pair(r.name or "", r.position or "") != (want_n, want_p):
                    continue
                out.append((r, Cls))
        out.sort(key=lambda x: -int(getattr(x[0], "matches", 0) or 0))
        return out
    finally:
        sess.close()
        eng.dispose()


def _purge_name_position_in_session(
    sess: Any, name: str, position: str, team: str | None = None
) -> tuple[dict[str, Any] | None, int | None, str | None]:
    from utils.player_transfer import _norm_cmp
    from utils.squad_roster_sync import _carry_from_row, _merge_carry_dicts

    want_n = _norm_cmp(name)
    want_p = _norm_cmp(position)
    want_t = _norm_cmp(team) if team else None
    merged: dict[str, Any] | None = None
    ovr: int | None = None
    nat: str | None = None
    for Cls in _ALL:
        for r in list(sess.query(Cls).all()):
            if _norm_cmp(r.name or "") != want_n:
                continue
            if _norm_cmp(r.position or "") != want_p:
                continue
            if want_t is not None and _norm_cmp(getattr(r, "team", "") or "") != want_t:
                continue
            if ovr is None:
                ovr = int(r.overall or 0)
            if nat is None and (getattr(r, "nation", None) or "").strip():
                nat = str(r.nation).strip()
            c = _carry_from_row(r)
            merged = c if merged is None else _merge_carry_dicts(merged, c)
            sess.delete(r)
    sess.flush()
    return merged, ovr, nat


def _roster_key(name: str, position: str) -> tuple[str, str]:
    from utils.player_transfer import _norm_cmp, normalize_player_name_for_db
    from utils.transfer_input import normalize_position

    return _norm_cmp(normalize_player_name_for_db(name)), _norm_cmp(
        normalize_position(position)
    )


def _iter_team_players(sess: Any, team: str):
    from utils.squad_roster_sync import _filter_team

    for Cls in _ALL:
        for r in sess.query(Cls).filter(_filter_team(Cls, team)).all():
            yield Cls, r


def count_team_squad_players(team: str, *, session_league: Any | None = None) -> int:
    """Число игроков клуба в национальной лиге (все позиции)."""
    from utils.transfer_input import resolve_team_name
    from utils.utils import session_league as default_league

    sleague = session_league or default_league
    team_raw = (team or "").strip()
    if len(team_raw) < 2:
        return 0
    resolved = resolve_team_name(team_raw, sleague) or team_raw
    return sum(1 for _ in _iter_team_players(sleague, resolved))


def team_squad_is_complete(team: str, *, session_league: Any | None = None) -> bool:
    """Полная заявка (32 игрока) — повторно применять не нужно."""
    from utils.squad_limits import SQUAD_MAX

    return count_team_squad_players(team, session_league=session_league) >= SQUAD_MAX


def _release_player_from_team_sessions(
    sleague: Any, scl: Any, team: str, nm: str, pos: str
) -> str:
    """Снять игрока с команды (как ``remove_player_from_team_roster`` без commit)."""
    from utils.player_field_edit import find_player_row as fpr

    Cls_l, row_l = fpr(sleague, team, nm, pos)
    if row_l is None:
        return ""
    ovr = int(row_l.overall or 0)
    nat = (getattr(row_l, "nation", None) or "").strip() or None
    if _has_meaningful_stats(row_l):
        from utils.player_transfer import mark_player_left_team

        mark_player_left_team(row_l)
        label = "left_team"
    else:
        sleague.delete(row_l)
        label = "deleted"
    from utils.common_db import resolve_team_name_for_cl_pool

    cl_team = resolve_team_name_for_cl_pool(team)
    if cl_team:
        Cls_c, row_c = fpr(scl, cl_team, nm, pos)
        if row_c is not None:
            if _has_meaningful_stats(row_c):
                from utils.player_transfer import mark_player_left_team

                mark_player_left_team(row_c)
            else:
                scl.delete(row_c)
    return label


def _apply_upsert_and_cascade(
    sess: Any,
    team: str,
    name: str,
    position: str,
    overall: int,
    nation: str | None,
    status: str,
    carry: dict[str, Any] | None,
    *,
    skip_status_cascade: bool = False,
    lineup_slot: str | None = None,
    preferred_person_id: int | None = None,
) -> None:
    from utils.player_transfer import _cascade_status
    from utils.squad_roster_sync import find_player_row, upsert_roster_player

    upsert_roster_player(
        sess,
        team=team,
        name=name,
        position=position,
        overall=overall,
        nation=nation,
        status=status,
        carry_in=carry,
        lineup_slot=lineup_slot,
        preferred_person_id=preferred_person_id,
    )
    sess.flush()
    row, Cls = find_player_row(sess, name, team)
    if row is None or Cls is None:
        from utils.squad_roster_sync import find_player_row_first_match

        row, Cls, _ = find_player_row_first_match(sess, name, team)
    if row is None or Cls is None:
        raise RuntimeError(f"После upsert не найден игрок {name!r} в {team!r}.")
    pos_u = (position or "").strip().upper()
    if not skip_status_cascade:
        _cascade_status(sess, Cls, team.strip(), pos_u, row, status)


def add_player_to_team_roster(
    team: str,
    name: str,
    position: str,
    *,
    overall: int | None = None,
    nation: str | None = None,
    status: str = "bench",
    lineup_slot: str | None = None,
    session_league: Any | None = None,
    session_cl: Any | None = None,
    rebuild_common: bool = True,
    mirror_synced: bool = True,
    commit: bool = True,
    skip_status_cascade: bool = False,
) -> dict[str, Any]:
    from utils import cumulative_mirror
    from utils.common_db import rebuild_common_database, resolve_team_name_for_cl_pool
    from utils.player_field_edit import find_player_row as fpr
    from utils.player_transfer import normalize_player_name_for_db
    from utils.transfer_input import normalize_nation, normalize_position
    from utils.utils import session_cl as default_cl
    from utils.utils import session_league as default_league

    sleague = session_league or default_league
    scl = session_cl or default_cl

    team = (team or "").strip()
    nm = normalize_player_name_for_db(name)
    pos = normalize_position(position)
    st = (status or "bench").strip().lower()
    if st not in ("start", "bench", "reserve"):
        raise ValueError("status: start | bench | reserve")

    cl_team = resolve_team_name_for_cl_pool(team)
    _Cls_l, row_l = fpr(sleague, team, nm, pos)
    row_c = None
    if cl_team:
        _Cls_c, row_c = fpr(scl, cl_team, nm, pos)

    cum = _find_rows_cumulative_common(nm, pos)
    existing = row_l is not None or row_c is not None

    if existing:
        ovr_res = int(
            overall
            if overall is not None
            else (
                int(getattr(row_l, "overall", 0) or 0)
                or int(getattr(row_c, "overall", 0) or 0)
                or 72
            )
        )
        if nation is not None:
            ns = str(nation).strip()
            nat_res = (
                None
                if ns in ("", "-", "—")
                else normalize_nation(nation)
            )
        else:
            nat_l = (getattr(row_l, "nation", None) or "").strip() if row_l else ""
            nat_c = (getattr(row_c, "nation", None) or "").strip() if row_c else ""
            nat_res = normalize_nation(nat_l or nat_c) if (nat_l or nat_c) else None
        carry = None
    elif cum:
        # Только overall/нация из накопительной common; полевая стата в клубе — с нулей.
        r0 = cum[0][0]
        ovr_res = max(
            1,
            min(99, int(overall if overall is not None else int(r0.overall or 72))),
        )
        if nation is not None:
            ns = str(nation).strip()
            nat_res = (
                None
                if ns in ("", "-", "—")
                else normalize_nation(nation)
            )
        elif (getattr(r0, "nation", None) or "").strip():
            nat_res = normalize_nation(str(r0.nation))
        else:
            nat_res = None
        carry = None
    else:
        if overall is None:
            raise ValueError(
                "Игрок не найден в common_synced.db — укажи overall (число 1–99)."
            )
        ovr_res = max(1, min(99, int(overall)))
        if nation is None:
            nat_res = None
        else:
            ns = str(nation).strip()
            nat_res = None if ns in ("", "-", "—") else normalize_nation(nation)
        carry = None

    from utils.person_registry import (
        lookup_canonical_person_id,
        lookup_canonical_person_id_by_team,
        row_person_id,
    )

    preferred_pid = None
    if existing:
        preferred_pid = row_person_id(row_l) or row_person_id(row_c)
    if preferred_pid is None:
        preferred_pid = lookup_canonical_person_id_by_team(nm, team=team) or lookup_canonical_person_id(
            nm, pos, team=team
        )

    ovr_res = max(1, min(99, int(ovr_res)))

    _apply_upsert_and_cascade(
        sleague,
        team,
        nm,
        pos,
        ovr_res,
        nat_res,
        st,
        carry,
        skip_status_cascade=skip_status_cascade,
        lineup_slot=lineup_slot if st == "start" else None,
        preferred_person_id=preferred_pid,
    )
    if cl_team:
        _apply_upsert_and_cascade(
            scl,
            cl_team,
            nm,
            pos,
            ovr_res,
            nat_res,
            st,
            carry,
            skip_status_cascade=skip_status_cascade,
            lineup_slot=lineup_slot if st == "start" else None,
            preferred_person_id=preferred_pid,
        )

    if commit:
        sleague.commit()
        scl.commit()

    if rebuild_common:
        rebuild_common_database()

    if mirror_synced:

        def _dup(sl: Any, sc: Any) -> None:
            add_player_to_team_roster(
                team,
                nm,
                pos,
                overall=overall,
                nation=nation,
                status=st,
                session_league=sl,
                session_cl=sc,
                rebuild_common=False,
                mirror_synced=False,
                commit=True,
                skip_status_cascade=skip_status_cascade,
            )

        cumulative_mirror.mirror_roster_manual(_dup)

    return {"team": team, "player": nm, "position": pos, "overall": ovr_res}


def remove_player_from_team_roster(
    team: str,
    name: str,
    position: str,
    *,
    session_league: Any | None = None,
    session_cl: Any | None = None,
    rebuild_common: bool = True,
    mirror_synced: bool = True,
    commit: bool = True,
) -> dict[str, Any]:
    from utils import cumulative_mirror
    from utils.common_db import rebuild_common_database
    from utils.player_field_edit import find_player_row
    from utils.player_transfer import normalize_player_name_for_db
    from utils.transfer_input import normalize_position
    from utils.utils import session_cl as default_cl
    from utils.utils import session_league as default_league

    sleague = session_league or default_league
    scl = session_cl or default_cl
    team = (team or "").strip()
    nm = normalize_player_name_for_db(name)
    pos = normalize_position(position)

    Cls_l, row_l = find_player_row(sleague, team, nm, pos)
    if row_l is None:
        raise ValueError(f"В нац. БД нет игрока «{nm}» ({pos}) в клубе «{team}».")

    stats = _has_meaningful_stats(row_l)
    _release_player_from_team_sessions(sleague, scl, team, nm, pos)

    if commit:
        sleague.commit()
        scl.commit()

    if rebuild_common:
        rebuild_common_database()

    if mirror_synced:

        def _dup(sl: Any, sc: Any) -> None:
            remove_player_from_team_roster(
                team,
                nm,
                pos,
                session_league=sl,
                session_cl=sc,
                rebuild_common=False,
                mirror_synced=False,
                commit=True,
            )

        cumulative_mirror.mirror_roster_manual(_dup)

    return {"removed_as": FREE_AGENT_TEAM if stats else "deleted", "player": nm}


def parse_roster_add_lines(text: str) -> tuple[list[tuple[str, str, int | None, str | None]], list[str]]:
    """
  Разбор построчного ввода для добавления в состав:
  ``имя позиция [overall] [нация]`` — по одной строке; статус по умолчанию bench.
  """
    blob = "==== bench ===\n" + (text or "").strip()
    entries, errs = parse_squad_declaration_text(blob)
    out: list[tuple[str, str, int | None, str | None]] = []
    for nm, pos, _st, ovr, nat, _slot in entries:
        out.append((nm, pos, ovr, nat))
    return out, errs


def add_players_to_team_roster_bulk(
    team: str,
    players: list[tuple[str, str, int | None, str | None]],
    *,
    status: str = "bench",
) -> dict[str, Any]:
    """Добавить нескольких игроков; одна транзакция нац.+ЛЧ и пересборка common/synced."""
    from utils.utils import session_cl, session_league

    if not players:
        return {"team": team, "added": [], "errors": []}
    team = (team or "").strip()
    st = (status or "bench").strip().lower()
    sleague = session_league
    scl = session_cl
    added: list[str] = []
    errors: list[str] = []
    ok_rows: list[tuple[str, str, int | None, str | None]] = []
    for nm, pos, ovr, nat in players:
        try:
            add_player_to_team_roster(
                team,
                nm,
                pos,
                overall=ovr,
                nation=nat,
                status=st,
                session_league=sleague,
                session_cl=scl,
                rebuild_common=False,
                mirror_synced=False,
                commit=False,
            )
            added.append(f"{nm} ({pos})")
            ok_rows.append((nm, pos, ovr, nat))
        except Exception as e:
            errors.append(f"{nm} ({pos}): {e}")
    if ok_rows:
        sleague.commit()
        scl.commit()
        from utils.common_db import rebuild_common_database

        rebuild_common_database()
        from utils import cumulative_mirror

        def _dup(sl: Any, sc: Any) -> None:
            for nm, pos, ovr, nat in ok_rows:
                add_player_to_team_roster(
                    team,
                    nm,
                    pos,
                    overall=ovr,
                    nation=nat,
                    status=st,
                    session_league=sl,
                    session_cl=sc,
                    rebuild_common=False,
                    mirror_synced=False,
                    commit=True,
                )

        cumulative_mirror.mirror_roster_manual(_dup)
    return {"team": team, "added": added, "errors": errors}


def remove_players_from_team_roster_bulk(
    team: str,
    players: list[tuple[str, str]],
) -> dict[str, Any]:
    """Исключить нескольких игроков; одна транзакция и пересборка common/synced."""
    from utils.player_transfer import normalize_player_name_for_db
    from utils.transfer_input import normalize_position
    from utils.utils import session_cl, session_league

    if not players:
        return {"team": team, "removed": [], "errors": []}
    team = (team or "").strip()
    sleague = session_league
    scl = session_cl
    removed: list[str] = []
    errors: list[str] = []
    ok_rows: list[tuple[str, str]] = []
    for name, position in players:
        nm = normalize_player_name_for_db(name)
        pos = normalize_position(position)
        try:
            remove_player_from_team_roster(
                team,
                nm,
                pos,
                session_league=sleague,
                session_cl=scl,
                rebuild_common=False,
                mirror_synced=False,
                commit=False,
            )
            removed.append(f"{nm} ({pos})")
            ok_rows.append((name, position))
        except Exception as e:
            errors.append(f"{nm} ({pos}): {e}")
    if ok_rows:
        sleague.commit()
        scl.commit()
        from utils.common_db import rebuild_common_database

        rebuild_common_database()
        from utils import cumulative_mirror

        def _dup(sl: Any, sc: Any) -> None:
            for name, position in ok_rows:
                remove_player_from_team_roster(
                    team,
                    normalize_player_name_for_db(name),
                    normalize_position(position),
                    session_league=sl,
                    session_cl=sc,
                    rebuild_common=False,
                    mirror_synced=False,
                    commit=True,
                )

        cumulative_mirror.mirror_roster_manual(_dup)
    return {"team": team, "removed": removed, "errors": errors}


def _is_valid_game_position(s: str) -> bool:
    from utils.utils import defenders, forwards, goalkeepers, midfielders

    u = (s or "").strip().upper()
    if not u:
        return False
    valid = set(forwards) | set(midfielders) | set(defenders) | set(goalkeepers)
    return u in valid


def _tail_ovr_nation_after_position(
    tail: list[str], line_num: int
) -> tuple[int | None, str | None, str | None]:
    """
    После позиции в строке заявки: ``[overall]`` и/или нация из одного или нескольких слов
    (например «др конго», «южная корея»).
    Возвращает ``(overall, nation, error_message)``.
    """
    from utils.transfer_input import normalize_nation

    if not tail:
        return None, None, None
    if tail[0].isdigit():
        v = int(tail[0])
        if v < 1 or v > 99:
            return (
                None,
                None,
                f"строка {line_num}: overall 1–99, не {tail[0]!r}",
            )
        if len(tail) == 1:
            return v, None, None
        rest_nat = " ".join(tail[1:]).strip()
        if rest_nat in ("", "-", "—"):
            return v, None, None
        return v, normalize_nation(rest_nat), None
    joined = " ".join(tail).strip()
    if joined in ("", "-", "—"):
        return None, None, None
    return None, normalize_nation(joined), None


def _parse_squad_line_pipe(
    parts: list[str], line_num: int
) -> tuple[tuple[str, str, str, int | None, str | None, str | None] | None, str | None]:
    from utils.player_transfer import normalize_player_name_for_db
    from utils.transfer_input import normalize_nation, normalize_position

    if len(parts) < 3:
        return None, f"строка {line_num}: минимум 3 колонки через |"
    slot: str | None = None
    if (
        len(parts) >= 4
        and is_valid_lineup_slot(parts[1])
        and _is_valid_game_position(parts[2])
    ):
        name_raw, slot_raw, pos_raw, st_raw = parts[0], parts[1], parts[2], parts[3]
        tail_parts = parts[4:]
    else:
        name_raw, pos_raw, st_raw = parts[0], parts[1], parts[2]
        tail_parts = parts[3:]
    if not name_raw or not pos_raw:
        return None, f"строка {line_num}: пустое имя или позиция"
    st = st_raw.strip().lower()
    if st not in ("start", "bench", "reserve"):
        return (
            None,
            f"строка {line_num}: статус start, bench или reserve (латиницей), не {st_raw!r}",
        )
    if not _is_valid_game_position(pos_raw):
        return None, f"строка {line_num}: неизвестная позиция {pos_raw!r}"
    pos = normalize_position(pos_raw)
    nm = normalize_player_name_for_db(name_raw)
    ovr: int | None = None
    if len(tail_parts) >= 1 and tail_parts[0] not in ("", "-", "—"):
        if not tail_parts[0].isdigit():
            return None, f"строка {line_num}: overall — целое 1–99 или пропуск"
        v = int(tail_parts[0])
        if v < 1 or v > 99:
            return None, f"строка {line_num}: overall в диапазоне 1–99"
        ovr = v
    nat: str | None = None
    if len(tail_parts) >= 2 and tail_parts[1] not in ("", "-", "—"):
        nat = normalize_nation(tail_parts[1])
    slot_norm: str | None = None
    if st == "start" and len(parts) >= 4 and is_valid_lineup_slot(parts[1]):
        try:
            slot_norm = normalize_lineup_slot(slot_raw)
        except ValueError as e:
            return None, f"строка {line_num}: {e}"
    return (nm, pos, st, ovr, nat, slot_norm), None


def _parse_squad_line_space(
    line: str, line_num: int
) -> tuple[tuple[str, str, str, int | None, str | None, str | None] | None, str | None]:
    """
    ``имя … позиция [overall] [нация …] start|bench|reserve`` — статус всегда последний;
    нация может быть из нескольких слов (например «др конго», «южная корея»).
    """
    from utils.player_transfer import normalize_player_name_for_db
    from utils.transfer_input import normalize_position

    tokens = line.split()
    if len(tokens) < 3:
        return (
            None,
            f"строка {line_num}: через пробел нужно минимум «имя позиция start» "
            f"(последнее слово — start, bench или reserve)",
        )
    st = tokens[-1].strip().lower()
    if st not in ("start", "bench", "reserve"):
        return (
            None,
            f"строка {line_num}: последнее слово должно быть start, bench или reserve "
            f"(латиницей), не {tokens[-1]!r}",
        )
    rest = list(tokens[:-1])
    pos_idx: int | None = None
    for j in range(len(rest) - 1, -1, -1):
        if _is_valid_game_position(rest[j]):
            pos_idx = j
            break
    if pos_idx is None:
        return (
            None,
            f"строка {line_num}: нет позиции (ЦП, ФРВ, ВРТ, …) перед статусом",
        )
    name_raw = " ".join(rest[:pos_idx]).strip()
    tail = rest[pos_idx + 1 :]
    if st == "start" and pos_idx > 0 and is_valid_lineup_slot(rest[pos_idx - 1]):
        try:
            slot_norm = normalize_lineup_slot(rest[pos_idx - 1])
        except ValueError as e:
            return None, f"строка {line_num}: {e}"
        name_raw = " ".join(rest[: pos_idx - 1]).strip()
        tail = rest[pos_idx + 1 :]
    else:
        slot_norm = None
    if not name_raw:
        return None, f"строка {line_num}: пустое имя"
    pos_raw = rest[pos_idx]
    if not _is_valid_game_position(pos_raw):
        return (
            None,
            f"строка {line_num}: «{pos_raw}» не распознана как позиция (ЦП, ФРВ, ВРТ, …)",
        )
    pos = normalize_position(pos_raw)
    nm = normalize_player_name_for_db(name_raw)
    ovr, nat, terr = _tail_ovr_nation_after_position(tail, line_num)
    if terr:
        return None, terr
    return (nm, pos, st, ovr, nat, slot_norm), None


def _parse_squad_line_implicit_status(
    line: str, line_num: int, status: str
) -> tuple[tuple[str, str, str, int | None, str | None, str | None] | None, str | None]:
    """
    Строка под секцией: ``имя [слот] позиция [overall] [нация …]`` — статус задаётся секцией.
    В ``start`` допускается ``имя GK ВРТ 84`` (слот + позиция в БД).
    """
    from utils.player_transfer import normalize_player_name_for_db
    from utils.transfer_input import normalize_position

    tokens = line.split()
    if len(tokens) < 2:
        return None, f"строка {line_num}: мало токенов (нужны имя и позиция)"
    st = (status or "").strip().lower()
    if st not in ("start", "bench", "reserve"):
        return None, f"строка {line_num}: внутренняя ошибка статуса {status!r}"

    pos_idx: int | None = None
    for j in range(len(tokens) - 1, -1, -1):
        if _is_valid_game_position(tokens[j]):
            pos_idx = j
            break
    if pos_idx is None:
        return None, f"строка {line_num}: нет позиции (ЦП, ФРВ, ВРТ, …) в строке"

    slot_norm: str | None = None
    if st == "start" and pos_idx > 0 and is_valid_lineup_slot(tokens[pos_idx - 1]):
        try:
            slot_norm = normalize_lineup_slot(tokens[pos_idx - 1])
        except ValueError as e:
            return None, f"строка {line_num}: {e}"
        name_raw = " ".join(tokens[: pos_idx - 1]).strip()
        tail = tokens[pos_idx + 1 :]
    else:
        name_raw = " ".join(tokens[:pos_idx]).strip()
        tail = tokens[pos_idx + 1 :]

    if not name_raw:
        return None, f"строка {line_num}: пустое имя"
    pos = normalize_position(tokens[pos_idx])
    nm = normalize_player_name_for_db(name_raw)
    ovr, nat, terr = _tail_ovr_nation_after_position(tail, line_num)
    if terr:
        return None, terr
    return (nm, pos, st, ovr, nat, slot_norm), None


def build_squad_declaration_template_from_db(team: str) -> str:
    """
    Текст для правки: секции ``==== start ===`` / ``=== bench ===`` / ``=== reserve ===``
    и строки ``имя позиция overall нация`` (нация и overall опционально).
    """
    from utils.player_transfer import _filter_team
    from utils.transfer_input import resolve_team_name, _team_name_as_in_db
    from utils.utils import session_league

    sleague = session_league
    resolved = resolve_team_name(team, sleague)
    t = resolved if resolved else _team_name_as_in_db((team or "").strip())

    buckets: dict[str, list[tuple[str, str, int, str | None, str | None]]] = {
        "start": [],
        "bench": [],
        "reserve": [],
    }
    for Cls in _ALL:
        for r in sleague.query(Cls).filter(_filter_team(Cls, t)).all():
            nm = (r.name or "").strip()
            pos = (r.position or "").strip()
            if not nm or not pos:
                continue
            ovr = int(r.overall or 0)
            nat_raw = (getattr(r, "nation", None) or "").strip() or None
            slot_raw = (getattr(r, "lineup_slot", None) or "").strip() or None
            st_raw = (getattr(r, "status", None) or "").strip().lower()
            if st_raw not in buckets:
                st_raw = "bench"
            buckets[st_raw].append((nm, pos, ovr, nat_raw, slot_raw))

    for key in buckets:
        buckets[key].sort(key=lambda x: x[0].lower())

    def _line(nm: str, pos: str, ovr: int, nat: str | None, slot: str | None, st_key: str) -> str:
        parts = [nm.lower()]
        if st_key == "start" and slot:
            parts.append(slot)
        parts.extend([pos.lower(), str(ovr)])
        if nat:
            parts.append(nat.lower())
        return " ".join(parts)

    lines: list[str] = []
    sec_meta = [
        ("start", "==== start ==="),
        ("bench", "=== bench ==="),
        ("reserve", "=== reserve ==="),
    ]
    for st_key, hdr in sec_meta:
        lines.append(hdr)
        for nm, pos, ovr, nat, slot in buckets[st_key]:
            lines.append(_line(nm, pos, ovr, nat, slot, st_key))
        lines.append("")

    return "\n".join(lines).rstrip() + "\n"


def parse_squad_declaration_text(
    text: str,
) -> tuple[list[tuple[str, str, str, int | None, str | None, str | None]], list[str]]:
    """
    Строка заявки — одно из:

    - ``имя | позиция | start`` … [, ``| overall`` [, ``| нация``]]
    - ``имя | слот | позиция | start`` … (только start)
    - ``имя … позиция [overall] [нация] start`` (пробелы; статус — последнее слово)
    - блоки ``==== start ===`` / ``=== bench ===`` / ``=== reserve ===``, затем строки
      ``имя [слот] позиция [overall] [нация]`` (статус из секции)
    """
    entries: list[tuple[str, str, str, int | None, str | None, str | None]] = []
    errors: list[str] = []
    ctx_status: str | None = None
    for i, raw in enumerate((text or "").splitlines(), start=1):
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        sec_m = _RE_SQUAD_SECTION.match(line)
        if sec_m:
            ctx_status = sec_m.group(1).lower()
            continue
        if "|" in line:
            parts = [p.strip() for p in line.split("|")]
            row, err = _parse_squad_line_pipe(parts, i)
        else:
            tok = line.split()
            last_l = tok[-1].lower() if tok else ""
            if last_l in ("start", "bench", "reserve"):
                row, err = _parse_squad_line_space(line, i)
            elif ctx_status:
                row, err = _parse_squad_line_implicit_status(line, i, ctx_status)
            else:
                row, err = _parse_squad_line_space(line, i)
        if err:
            errors.append(err)
            continue
        if row:
            entries.append(row)
    return entries, errors


def apply_team_squad_declaration(
    team: str,
    entries: list[tuple[str, str, str, int | None, str | None, str | None]],
    *,
    session_league: Any | None = None,
    session_cl: Any | None = None,
    rebuild_common: bool = True,
    mirror_synced: bool = True,
) -> dict[str, Any]:
    """
    Полная заявка клуба: все (имя, позиция) из списка остаются / добавляются с указанным
    статусом; остальные в нац. БД (и ЛЧ при пуле) снимаются по правилам
    ``remove_player_from_team_roster``.

    Статусы в БД совпадают с текстом заявки: при upsert не вызывается ``_cascade_status``.
    """
    from utils import cumulative_mirror
    from utils.common_db import rebuild_common_database, resolve_team_name_for_cl_pool
    from utils.player_transfer import normalize_player_name_for_db
    from utils.transfer_input import normalize_position, resolve_team_name
    from utils.utils import session_cl as default_cl
    from utils.utils import session_league as default_league

    sleague = session_league or default_league
    scl = session_cl or default_cl
    team_raw = (team or "").strip()
    if len(team_raw) < 2:
        raise ValueError("Слишком короткое имя клуба")
    team = resolve_team_name(team_raw, sleague) or team_raw
    if not entries:
        raise ValueError("Список заявки пуст")

    od: OrderedDict[tuple[str, str], tuple[str, str, str, int | None, str | None, str | None]] = (
        OrderedDict()
    )
    for name, pos, st, ovr, nat, slot in entries:
        nm = normalize_player_name_for_db(name)
        pp = normalize_position(pos)
        k = _roster_key(nm, pp)
        od[k] = (nm, pp, st, ovr, nat, slot)
    deduped = list(od.values())
    declared = set(od.keys())

    released_labels: list[str] = []
    try:
        for _Cls, r in list(_iter_team_players(sleague, team)):
            nm = normalize_player_name_for_db(r.name or "")
            pp = normalize_position(r.position or "")
            k = _roster_key(nm, pp)
            if k in declared:
                continue
            tag = _release_player_from_team_sessions(sleague, scl, team, nm, pp)
            if tag:
                released_labels.append(f"{nm} ({pp}): {tag}")

        for nm, pp, st, ovr, nat, slot in deduped:
            add_player_to_team_roster(
                team,
                nm,
                pp,
                overall=ovr,
                nation=nat,
                status=st,
                lineup_slot=slot if st == "start" else None,
                session_league=sleague,
                session_cl=scl,
                rebuild_common=False,
                mirror_synced=False,
                commit=False,
                skip_status_cascade=True,
            )

        sleague.commit()
        scl.commit()
    except Exception:
        sleague.rollback()
        scl.rollback()
        raise

    if rebuild_common:
        rebuild_common_database()

    if mirror_synced:

        def _dup(sl: Any, sc: Any) -> None:
            apply_team_squad_declaration(
                team,
                deduped,
                session_league=sl,
                session_cl=sc,
                rebuild_common=False,
                mirror_synced=False,
            )

        cumulative_mirror.mirror_roster_manual(_dup)

    return {
        "team": team,
        "declared": len(deduped),
        "released": len(released_labels),
        "released_detail": released_labels,
        "cl_pool": bool(resolve_team_name_for_cl_pool(team)),
    }


def rewrite_team_player_identity(
    team: str,
    old_name: str,
    old_position: str,
    *,
    new_name: str,
    new_position: str,
    overall: int | None = None,
    nation: str | None = None,
    status: str | None = None,
    session_league: Any | None = None,
    session_cl: Any | None = None,
    rebuild_common: bool = True,
    mirror_synced: bool = True,
) -> dict[str, Any]:
    """
    Переименовать/перепозиционировать игрока внутри клуба c переносом статистики.

    Важный кейс: в БД уже есть строка в новой идентичности (новая позиция/имя). Тогда
    статистика старой и новой строк объединяется; старая строка удаляется.
    """
    from utils import cumulative_mirror
    from utils.common_db import rebuild_common_database, resolve_team_name_for_cl_pool
    from utils.player_field_edit import find_player_row as fpr
    from utils.player_transfer import normalize_player_name_for_db
    from utils.squad_roster_sync import _carry_from_row, _merge_carry_dicts
    from utils.transfer_input import normalize_nation, normalize_position, resolve_team_name
    from utils.utils import session_cl as default_cl
    from utils.utils import session_league as default_league

    sleague = session_league or default_league
    scl = session_cl or default_cl
    team_raw = (team or "").strip()
    if len(team_raw) < 2:
        raise ValueError("Слишком короткое имя клуба")
    team = resolve_team_name(team_raw, sleague) or team_raw

    old_nm = normalize_player_name_for_db(old_name)
    old_pos = normalize_position(old_position)
    new_nm = normalize_player_name_for_db(new_name)
    new_pos = normalize_position(new_position)
    if not old_nm or not old_pos or not new_nm or not new_pos:
        raise ValueError("Заполни old/new имя и позицию.")

    _Cls_old_l, row_old_l = fpr(sleague, team, old_nm, old_pos)
    if row_old_l is None:
        raise ValueError(
            f"В нац. БД не найден «{old_nm}» ({old_pos}) в клубе «{team}»."
        )
    old_status = (getattr(row_old_l, "status", None) or "bench").strip().lower()
    st = (status or old_status).strip().lower()
    if st not in ("start", "bench", "reserve"):
        raise ValueError("status: start | bench | reserve")

    carry_l = _carry_from_row(row_old_l)
    ovr_from_old = int(getattr(row_old_l, "overall", 0) or 0)
    nat_from_old = (getattr(row_old_l, "nation", None) or "").strip() or None
    from utils.person_registry import row_person_id

    keep_pid = row_person_id(row_old_l)

    cl_team = resolve_team_name_for_cl_pool(team)
    carry_c = None
    ovr_from_old_c = 0
    nat_from_old_c = None
    row_old_c = None
    if cl_team:
        _Cls_old_c, row_old_c = fpr(scl, cl_team, old_nm, old_pos)
        if row_old_c is not None:
            carry_c = _carry_from_row(row_old_c)
            ovr_from_old_c = int(getattr(row_old_c, "overall", 0) or 0)
            nat_from_old_c = (getattr(row_old_c, "nation", None) or "").strip() or None
            if keep_pid is None:
                keep_pid = row_person_id(row_old_c)

    try:
        if row_old_c is not None:
            scl.delete(row_old_c)
        sleague.delete(row_old_l)
        sleague.flush()
        scl.flush()

        carry_new_l, ovr_new_l, nat_new_l = _purge_name_position_in_session(
            sleague, new_nm, new_pos, team=team
        )
        carry_new_c, ovr_new_c, nat_new_c = _purge_name_position_in_session(
            scl, new_nm, new_pos, team=team
        )

        merged = carry_l
        if carry_c:
            merged = _merge_carry_dicts(merged, carry_c)
        if carry_new_l:
            merged = _merge_carry_dicts(merged, carry_new_l)
        if carry_new_c:
            merged = _merge_carry_dicts(merged, carry_new_c)

        ovr_res = int(
            overall
            if overall is not None
            else (
                ovr_new_l
                or ovr_new_c
                or ovr_from_old
                or ovr_from_old_c
                or 72
            )
        )
        ovr_res = max(1, min(99, ovr_res))
        if nation is not None:
            ns = str(nation).strip()
            nat_res = None if ns in ("", "-", "—") else normalize_nation(ns)
        else:
            nat_res = nat_new_l or nat_new_c or nat_from_old or nat_from_old_c
            nat_res = normalize_nation(nat_res) if nat_res else None

        _apply_upsert_and_cascade(
            sleague,
            team,
            new_nm,
            new_pos,
            ovr_res,
            nat_res,
            st,
            merged,
            skip_status_cascade=True,
            preferred_person_id=keep_pid,
        )
        if cl_team:
            _apply_upsert_and_cascade(
                scl,
                cl_team,
                new_nm,
                new_pos,
                ovr_res,
                nat_res,
                st,
                merged,
                skip_status_cascade=True,
                preferred_person_id=keep_pid,
            )
        sleague.commit()
        scl.commit()
    except Exception:
        sleague.rollback()
        scl.rollback()
        raise

    if rebuild_common:
        rebuild_common_database()

    if mirror_synced:

        def _dup(sl: Any, sc: Any) -> None:
            rewrite_team_player_identity(
                team,
                old_nm,
                old_pos,
                new_name=new_nm,
                new_position=new_pos,
                overall=overall,
                nation=nation,
                status=st,
                session_league=sl,
                session_cl=sc,
                rebuild_common=False,
                mirror_synced=False,
            )

        cumulative_mirror.mirror_roster_manual(_dup)

    return {
        "team": team,
        "old": (old_nm, old_pos),
        "new": (new_nm, new_pos),
        "overall": ovr_res,
        "nation": nat_res,
        "status": st,
        "cl_pool": bool(cl_team),
    }
