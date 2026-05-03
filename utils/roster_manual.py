# -*- coding: utf-8 -*-
"""
Ручное добавление / удаление игрока в состав клуба (нац. БД + ЛЧ при пуле).

- Добавление: если игрок есть в ``common_synced.db`` (той же позиции) — подтягиваем carry
  из накопительной common; иначе нужны ``overall`` и ``нация``. Запись только в текущие
  рабочие БД и зеркало ``*_synced`` (архивные ``db/season_*`` не трогаем).
- Удаление: игрок попадает в ``free_agents``; при ненулевой статистике в нац./ЛЧ
  ``team = Free Agent``, иначе строка удаляется.
- Пакетная заявка: ``apply_team_squad_declaration`` + ``parse_squad_declaration_text``
  (строки через ``|`` или «имя … позиция start» через пробелы); кто в клубе не в списке,
  уходит в СА тем же правилом, что и при удалении.
"""
from __future__ import annotations

import os
from collections import OrderedDict
from typing import Any

from data.defender import Defender
from data.forward import Forward
from data.goalkeeper import Goalkeeper
from data.midfielder import Midfielder

_ALL = (Forward, Midfielder, Defender, Goalkeeper)

FREE_AGENT_TEAM = "Free Agent"


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
    sess: Any, name: str, position: str
) -> tuple[dict[str, Any] | None, int | None, str | None]:
    from utils.player_transfer import _norm_cmp
    from utils.squad_roster_sync import _carry_from_row, _merge_carry_dicts

    want_n = _norm_cmp(name)
    want_p = _norm_cmp(position)
    merged: dict[str, Any] | None = None
    ovr: int | None = None
    nat: str | None = None
    for Cls in _ALL:
        for r in list(sess.query(Cls).all()):
            if _norm_cmp(r.name or "") != want_n:
                continue
            if _norm_cmp(r.position or "") != want_p:
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


def _release_player_from_team_sessions(
    sleague: Any, scl: Any, team: str, nm: str, pos: str
) -> str:
    """Снять игрока с команды (как ``remove_player_from_team_roster`` без commit)."""
    from utils.common_db import _team_in_cl_pool
    from utils.free_agents_catalog import upsert_free_agent_catalog
    from utils.player_field_edit import find_player_row as fpr

    Cls_l, row_l = fpr(sleague, team, nm, pos)
    if row_l is None:
        return ""
    ovr = int(row_l.overall or 0)
    nat = (getattr(row_l, "nation", None) or "").strip() or None
    upsert_free_agent_catalog(nm, pos, ovr, nat)
    if _has_meaningful_stats(row_l):
        row_l.team = FREE_AGENT_TEAM
        label = FREE_AGENT_TEAM
    else:
        sleague.delete(row_l)
        label = "deleted"
    if _team_in_cl_pool(team):
        Cls_c, row_c = fpr(scl, team, nm, pos)
        if row_c is not None:
            if _has_meaningful_stats(row_c):
                row_c.team = FREE_AGENT_TEAM
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
    )
    sess.flush()
    row, Cls = find_player_row(sess, name, team)
    if row is None or Cls is None:
        raise RuntimeError(f"После upsert не найден игрок {name!r} в {team!r}.")
    pos_u = (position or "").strip().upper()
    _cascade_status(sess, Cls, team.strip(), pos_u, row, status)


def add_player_to_team_roster(
    team: str,
    name: str,
    position: str,
    *,
    overall: int | None = None,
    nation: str | None = None,
    status: str = "bench",
    session_league: Any | None = None,
    session_cl: Any | None = None,
    rebuild_common: bool = True,
    mirror_synced: bool = True,
    commit: bool = True,
) -> dict[str, Any]:
    from utils import cumulative_mirror
    from utils.common_db import _team_in_cl_pool, rebuild_common_database
    from utils.player_transfer import normalize_player_name_for_db
    from utils.squad_roster_sync import _carry_from_row, _merge_carry_dicts
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

    cum = _find_rows_cumulative_common(nm, pos)
    carry_l, ovr_l, nat_l = _purge_name_position_in_session(sleague, nm, pos)
    carry_c, ovr_c, nat_c = _purge_name_position_in_session(scl, nm, pos)

    carry: dict[str, Any] | None = carry_l
    if carry_c:
        carry = _merge_carry_dicts(carry_l or {}, carry_c) if carry_l else carry_c

    if carry is not None:
        ovr_res = int(overall if overall is not None else (ovr_l or ovr_c or 72))
        if nation is not None:
            ns = str(nation).strip()
            nat_res = (
                None
                if ns in ("", "-", "—")
                else normalize_nation(nation)
            )
        else:
            nat_res = normalize_nation(nat_l) if nat_l else None
    elif cum:
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
        carry = _carry_from_row(r0)
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

    ovr_res = max(1, min(99, int(ovr_res)))

    _apply_upsert_and_cascade(sleague, team, nm, pos, ovr_res, nat_res, st, carry)
    if _team_in_cl_pool(team):
        _apply_upsert_and_cascade(scl, team, nm, pos, ovr_res, nat_res, st, carry)

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


def _is_valid_game_position(s: str) -> bool:
    from utils.utils import defenders, forwards, goalkeepers, midfielders

    u = (s or "").strip().upper()
    if not u:
        return False
    valid = set(forwards) | set(midfielders) | set(defenders) | set(goalkeepers)
    return u in valid


def _parse_squad_line_pipe(
    parts: list[str], line_num: int
) -> tuple[tuple[str, str, str, int | None, str | None] | None, str | None]:
    from utils.player_transfer import normalize_player_name_for_db
    from utils.transfer_input import normalize_nation, normalize_position

    if len(parts) < 3:
        return None, f"строка {line_num}: минимум 3 колонки через |"
    name_raw, pos_raw, st_raw = parts[0], parts[1], parts[2]
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
    if len(parts) >= 4 and parts[3] not in ("", "-", "—"):
        if not parts[3].isdigit():
            return None, f"строка {line_num}: overall — целое 1–99 или пропуск"
        v = int(parts[3])
        if v < 1 or v > 99:
            return None, f"строка {line_num}: overall в диапазоне 1–99"
        ovr = v
    nat: str | None = None
    if len(parts) >= 5 and parts[4] not in ("", "-", "—"):
        nat = normalize_nation(parts[4])
    return (nm, pos, st, ovr, nat), None


def _parse_squad_line_space(
    line: str, line_num: int
) -> tuple[tuple[str, str, str, int | None, str | None] | None, str | None]:
    """
    ``имя … позиция [overall] [нация] start|bench|reserve`` — статус **всегда последний**;
    позиция — слово перед блоком optional (число 1–99 и одно слово нации).
    """
    from utils.player_transfer import normalize_player_name_for_db
    from utils.transfer_input import normalize_nation, normalize_position

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
    ovr: int | None = None
    nat: str | None = None
    if len(rest) >= 3:
        if rest[-2].isdigit():
            v2 = int(rest[-2])
            if 1 <= v2 <= 99:
                ovr = v2
                tail = (rest[-1] or "").strip()
                if tail not in ("", "-", "—"):
                    nat = normalize_nation(tail)
                rest = rest[:-2]
    if ovr is None and len(rest) >= 2 and rest[-1].isdigit():
        v = int(rest[-1])
        if 1 <= v <= 99:
            ovr = v
            rest = rest[:-1]
    if len(rest) < 2:
        return (
            None,
            f"строка {line_num}: после разбора статуса/overall не остались имя и позиция",
        )
    pos_raw = rest[-1]
    name_raw = " ".join(rest[:-1]).strip()
    if not name_raw:
        return None, f"строка {line_num}: пустое имя"
    if not _is_valid_game_position(pos_raw):
        return (
            None,
            f"строка {line_num}: «{pos_raw}» не распознана как позиция (ЦП, ФРВ, ВРТ, …)",
        )
    pos = normalize_position(pos_raw)
    nm = normalize_player_name_for_db(name_raw)
    return (nm, pos, st, ovr, nat), None


def parse_squad_declaration_text(
    text: str,
) -> tuple[list[tuple[str, str, str, int | None, str | None]], list[str]]:
    """
    Строка заявки — одно из:

    - ``имя | позиция | start`` … [, ``| overall`` [, ``| нация``]]
    - ``имя … позиция [overall] [нация] start`` (пробелы; статус — последнее слово;
      при двух хвостовых полях после позиции: сначала overall 1–99, затем нация одним словом).
    """
    entries: list[tuple[str, str, str, int | None, str | None]] = []
    errors: list[str] = []
    for i, raw in enumerate((text or "").splitlines(), start=1):
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        if "|" in line:
            parts = [p.strip() for p in line.split("|")]
            row, err = _parse_squad_line_pipe(parts, i)
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
    entries: list[tuple[str, str, str, int | None, str | None]],
    *,
    session_league: Any | None = None,
    session_cl: Any | None = None,
    rebuild_common: bool = True,
    mirror_synced: bool = True,
) -> dict[str, Any]:
    """
    Полная заявка клуба: все (имя, позиция) из списка остаются / добавляются с указанным
    статусом; остальные в нац. БД (и ЛЧ при пуле) снимаются в СА по правилам
    ``remove_player_from_team_roster``.
    """
    from utils import cumulative_mirror
    from utils.common_db import rebuild_common_database
    from utils.player_transfer import normalize_player_name_for_db
    from utils.transfer_input import normalize_position
    from utils.utils import session_cl as default_cl
    from utils.utils import session_league as default_league

    sleague = session_league or default_league
    scl = session_cl or default_cl
    team = (team or "").strip()
    if len(team) < 2:
        raise ValueError("Слишком короткое имя клуба")
    if not entries:
        raise ValueError("Список заявки пуст")

    od: OrderedDict[tuple[str, str], tuple[str, str, str, int | None, str | None]] = (
        OrderedDict()
    )
    for name, pos, st, ovr, nat in entries:
        nm = normalize_player_name_for_db(name)
        pp = normalize_position(pos)
        k = _roster_key(nm, pp)
        od[k] = (nm, pp, st, ovr, nat)
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

        for nm, pp, st, ovr, nat in deduped:
            add_player_to_team_roster(
                team,
                nm,
                pp,
                overall=ovr,
                nation=nat,
                status=st,
                session_league=sleague,
                session_cl=scl,
                rebuild_common=False,
                mirror_synced=False,
                commit=False,
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
    }
