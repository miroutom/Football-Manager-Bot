# -*- coding: utf-8 -*-
"""
Статистика для бота «Стата сезонов» и топов (``docs/stats_display_rules.md``,
полные правила — ``docs/stats_menu_rules_full.md``).

**За всё время** — накопительные ``*_synced.db``, одна строка на игрока (**полное** ``name``,
не фамилия — «Мартинез» ≠ «Иниго Мартинез»); сумма за все сезоны и позиции с тем же именем;
**клуб и позиция** — активная заявка (``name`` + позиция, max ``id``, без ``left_team``).

**Один сезон** — ``db/season_N/league.db``, ``champions_league.db`` или ``common.db``:
- нац. лига: строки как в БД (две строки при переходе между лигами); в одной лиге за сезон
  — слияние по игроку, клуб с max ``id`` (финальный клуб), стата суммируется;
- ЛЧ: одна строка на игрока, сумма по ЛЧ, клуб последней записи в ``champions_league.db``;
- ``all``: все нац. лиги (``league.db`` / ``league_synced.db``), одна строка на игрока;
- ``allcl``: лига+ЛЧ (``common.db``), полная сумма за сезон, клуб с max ``id`` в common.
- Слияние внутри сезона — по **полному** ``name`` + позиция (не по одной фамилии).
"""
from __future__ import annotations

import os
from typing import Any

from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from data.defender import Defender
from data.forward import Forward
from data.goalkeeper import Goalkeeper
from data.midfielder import Midfielder
from player_stats import LEAGUE_NAMES, LEAGUE_TEAMS
from utils import season_paths
from utils.cumulative_db import list_season_archives_with_db

_OUTFIELD = (Forward, Midfielder, Defender)
_ALL = (Forward, Midfielder, Defender, Goalkeeper)


def normalize_stats_league_code(league_code: str | None) -> str | None:
    """Нормализация кода из callback: ``a`` → ``allcl`` (раньше «все» = лига+ЛЧ)."""
    if league_code is None:
        return None
    c = str(league_code).strip().lower()
    if not c:
        return None
    if c == "a":
        return "allcl"
    return c


def is_all_leagues_only(league_code: str | None) -> bool:
    """Все национальные лиги, без ЛЧ."""
    c = normalize_stats_league_code(league_code)
    return c == "all"


def is_all_leagues_plus_cl(league_code: str | None) -> bool:
    """Все национальные лиги + ЛЧ (бывший единый «все чемпионаты»)."""
    c = normalize_stats_league_code(league_code)
    return c == "allcl"


def is_all_leagues_plus_cl_plus_wc(league_code: str | None) -> bool:
    """Все национальные лиги + ЛЧ + сборные (ЧМ)."""
    c = normalize_stats_league_code(league_code)
    return c == "allclwc"


def is_all_championships(league_code: str | None) -> bool:
    """Любой режим «все чемпионаты» (лиги, лига+ЛЧ или лига+ЛЧ+сборные)."""
    return (
        is_all_leagues_only(league_code)
        or is_all_leagues_plus_cl(league_code)
        or is_all_leagues_plus_cl_plus_wc(league_code)
    )


def _norm_team(s: str) -> str:
    return (s or "").strip().casefold()


def _identity_key(identity: str, position: str) -> tuple[str, str]:
    return (
        (identity or "").strip().casefold(),
        (position or "").strip().upper(),
    )


def _identity_only_key(identity: str) -> tuple[str]:
    return ((identity or "").strip().casefold(),)


def _full_name_key_from_row(p: Any) -> tuple[str]:
    full = (getattr(p, "name", None) or "").strip().casefold()
    return (full,)


def _roster_display_key(name: str, position: str) -> tuple[str, str]:
    """Ключ подписи в активном сезоне (два «Мартинез» разных ролей — разные ключи)."""
    return (
        (name or "").strip().casefold(),
        (position or "").strip().upper(),
    )


def _player_key(identity: str, team: str, position: str) -> tuple[str, str, str]:
    return (
        (identity or "").strip().casefold(),
        _norm_team(team),
        (position or "").strip().upper(),
    )


def _bucket_key_for_row(
    p: Any,
    *,
    merge_by_player: bool,
    merge_across_positions: bool = False,
) -> tuple:
    from utils.person_registry import row_person_id
    from utils.player_names import player_stats_identity_token

    ident = player_stats_identity_token(p)
    pos = (getattr(p, "position", None) or "").strip().upper()
    pid = row_person_id(p)
    if merge_by_player and pid is not None:
        return ("pid", pid)
    if merge_by_player:
        if merge_across_positions:
            # Карьера в synced: одно полное имя, все позиции; не склеивать однофамильцев.
            return _full_name_key_from_row(p)
        # Один сезон / common: не склеивать омонимов по фамилии
        # («Мартинез» Интер ≠ «Альварес Мартинез» Сассуоло).
        full = (getattr(p, "name", None) or "").strip().casefold()
        return (full, pos)
    return _player_key(ident, p.team, pos)


def _apply_last_club(
    b: dict, p: Any, season_num: int, *, merge_by_player: bool
) -> None:
    if not merge_by_player:
        return
    prev = int(b.get("last_season", -1))
    if season_num > prev:
        b["last_season"] = season_num
        b["team"] = p.team
        b["name"] = p.name
        b["position"] = getattr(p, "position", None) or b.get("position")
        b["overall"] = int(getattr(p, "overall", 0) or 0)
    elif season_num == prev:
        b["team"] = p.team
        b["name"] = p.name
        b["position"] = getattr(p, "position", None) or b.get("position")
        b["overall"] = int(getattr(p, "overall", 0) or 0)


def _apply_last_club_by_matches(b: dict, p: Any, *, merge_by_player: bool) -> None:
    """За всё время: клуб с наибольшим числом матчей в выборке."""
    if not merge_by_player:
        return
    m = int(getattr(p, "matches", 0) or 0)
    if m >= int(b.get("_pick_m", -1)):
        b["_pick_m"] = m
        b["team"] = p.team
        b["name"] = p.name
        b["position"] = getattr(p, "position", None) or b.get("position")
        b["overall"] = int(getattr(p, "overall", 0) or 0)


def _apply_last_club_latest_row(b: dict, p: Any, *, merge_by_player: bool) -> None:
    """Один сезон, 2+ клуба: подпись с наибольшим вкладом (матчи, Г+А), не просто max id."""
    if not merge_by_player:
        return
    rid = int(getattr(p, "id", 0) or 0)
    m = int(getattr(p, "matches", 0) or 0)
    g = int(getattr(p, "goals", 0) or 0)
    a = int(getattr(p, "assists", 0) or 0)
    ga = int(getattr(p, "ga", 0) or 0) or (g + a)
    prev_m = int(b.get("_pick_m", -1))
    prev_ga = int(b.get("_pick_ga", -1))
    prev_id = int(b.get("_pick_id", -1))
    if (m, ga, rid) > (prev_m, prev_ga, prev_id):
        b["_pick_m"] = m
        b["_pick_ga"] = ga
        b["_pick_id"] = rid
        b["team"] = p.team
        b["name"] = p.name
        b["position"] = getattr(p, "position", None) or b.get("position")
        b["overall"] = int(getattr(p, "overall", 0) or 0)


def _apply_club_label(
    b: dict,
    p: Any,
    season_num: int,
    *,
    merge_by_player: bool,
    pick_club: str | None,
) -> None:
    if not merge_by_player:
        return
    if pick_club == "matches":
        _apply_last_club_by_matches(b, p, merge_by_player=True)
    elif pick_club == "latest_row":
        _apply_last_club_latest_row(b, p, merge_by_player=True)
    elif pick_club == "active_season":
        return
    else:
        _apply_last_club(b, p, season_num, merge_by_player=True)


def _build_active_season_club_map() -> tuple[
    dict[tuple[str, str], tuple[str, str, str, int]],
    dict[int, tuple[str, str, str, int]],
]:
    """(name, pos) и person_id → (name, team, position, overall) из активной заявки."""
    from utils.person_registry import row_person_id

    active = season_paths.get_active_season()
    best: dict[tuple[str, str], tuple[int, str, str, str, int]] = {}
    by_pid: dict[int, tuple[int, str, str, str, int]] = {}
    for kind in ("league", "cl", "common"):
        path = _season_path_by_kind(active, kind)
        if not path:
            continue
        session, eng = _open_session(path)
        try:
            for Cls in _ALL:
                for p in session.query(Cls).all():
                    if bool(getattr(p, "left_team", False)):
                        continue
                    key = _roster_display_key(str(p.name), str(p.position or ""))
                    rid = int(getattr(p, "id", 0) or 0)
                    prev = best.get(key)
                    if prev is None or rid > prev[0]:
                        best[key] = (
                            rid,
                            str(p.name),
                            str(p.team),
                            str(p.position or ""),
                            int(getattr(p, "overall", 0) or 0),
                        )
                    pid = row_person_id(p)
                    if pid is not None:
                        pprev = by_pid.get(pid)
                        if pprev is None or rid > pprev[0]:
                            by_pid[pid] = (
                                rid,
                                str(p.name),
                                str(p.team),
                                str(p.position or ""),
                                int(getattr(p, "overall", 0) or 0),
                            )
        finally:
            session.close()
            eng.dispose()
    name_map = {k: (v[1], v[2], v[3], v[4]) for k, v in best.items()}
    pid_map = {k: (v[1], v[2], v[3], v[4]) for k, v in by_pid.items()}
    return name_map, pid_map


def _apply_active_season_club_labels(rows: list[dict]) -> None:
    club_map, pid_map = _build_active_season_club_map()
    if not club_map and not pid_map:
        return
    for b in rows:
        pid = b.get("person_id")
        if pid is not None:
            try:
                hit = pid_map.get(int(pid))
            except (TypeError, ValueError):
                hit = None
            if hit:
                b["name"], b["team"], b["position"], b["overall"] = hit
                continue
        key = _roster_display_key(
            str(b.get("name") or ""),
            str(b.get("position") or ""),
        )
        hit = club_map.get(key)
        if hit:
            b["name"], b["team"], b["position"], b["overall"] = hit


def _finalize_life_rows(rows: list[dict]) -> list[dict]:
    _apply_active_season_club_labels(rows)
    for b in rows:
        b.pop("_pick_m", None)
        b.pop("_pick_ga", None)
        b.pop("_pick_id", None)
        b.pop("last_season", None)
    return rows


def _life_cumulative_db(league_code: str | None) -> tuple[str, str]:
    if is_all_leagues_plus_cl_plus_wc(league_code):
        return (
            season_paths.get_cumulative_common_db_path(),
            "common_synced.db + world_cup.db",
        )
    if is_all_leagues_plus_cl(league_code):
        return (
            season_paths.get_cumulative_common_db_path(),
            "common_synced.db",
        )
    if is_all_leagues_only(league_code):
        return (
            season_paths.get_cumulative_league_db_path(),
            "league_synced.db",
        )
    if league_code == "cl":
        return (
            season_paths.get_cumulative_cl_db_path(),
            "champions_league_synced.db",
        )
    if league_code == "wc":
        return ("", "world_cup.db (архивы сезонов)")
    return (
        season_paths.get_cumulative_league_db_path(),
        "league_synced.db",
    )


def _season_common_path(season_num: int) -> str | None:
    active = season_paths.get_active_season()
    if season_num == active:
        path = season_paths.get_common_db_path()
    else:
        path = os.path.join(
            season_paths.season_archive_directory(season_num),
            season_paths.SEASON_COMMON_NAME,
        )
    return path if os.path.isfile(path) else None


def _team_filter_set(league_code: str | None) -> set[str] | None:
    if is_all_championships(league_code):
        return None
    if league_code == "cl":
        import teams as teams_mod

        return {_norm_team(t) for t in teams_mod.teams_champ_league.keys()}
    teams = LEAGUE_TEAMS.get(league_code)
    if not teams:
        return None
    return {_norm_team(t) for t in teams}


def _season_db_path(season_num: int, *, cl: bool) -> str | None:
    active = season_paths.get_active_season()
    fname = season_paths.SEASON_CL_NAME if cl else season_paths.SEASON_LEAGUE_NAME
    if season_num == active:
        path = season_paths.get_cl_db_path() if cl else season_paths.get_league_db_path()
        return path if os.path.isfile(path) else None
    base = season_paths.season_archive_directory(season_num)
    path = os.path.join(base, fname)
    return path if os.path.isfile(path) else None


def _season_wc_path(season_num: int) -> str | None:
    active = season_paths.get_active_season()
    if season_num == active:
        path = season_paths.get_wc_db_path()
    else:
        path = season_paths.get_wc_db_path_for_season(season_num)
    return path if path and os.path.isfile(path) else None


def _iter_wc_db_paths() -> list[tuple[int, str]]:
    """(номер сезона, путь) ко всем ``world_cup.db`` без дубликатов."""
    out: list[tuple[int, str]] = []
    seen: set[str] = set()
    db_dir = os.path.join(season_paths.PROJECT_ROOT, "db")
    if os.path.isdir(db_dir):
        for name in os.listdir(db_dir):
            if not name.startswith("season_"):
                continue
            tail = name.replace("season_", "")
            if not tail.isdigit():
                continue
            sn = int(tail)
            path = _season_wc_path(sn)
            if not path:
                continue
            ap = os.path.abspath(path)
            if ap in seen:
                continue
            seen.add(ap)
            out.append((sn, path))
    cur = season_paths.get_wc_db_path()
    if cur and os.path.isfile(cur):
        ap = os.path.abspath(cur)
        if ap not in seen:
            out.append((season_paths.get_active_season(), cur))
    return sorted(out, key=lambda x: x[0])


def _row_merge_key(row: dict) -> tuple:
    pid = row.get("person_id")
    if pid is not None:
        try:
            return ("pid", int(pid))
        except (TypeError, ValueError):
            pass
    return (
        "name",
        str(row.get("name") or "").strip().casefold(),
        str(row.get("position") or "").strip().upper(),
    )


def _merge_stat_rows(
    rows_a: list[dict],
    rows_b: list[dict],
    *,
    sum_fields: tuple[str, ...],
) -> list[dict]:
    buckets: dict[tuple, dict] = {}
    for r in rows_a + rows_b:
        key = _row_merge_key(r)
        cur = buckets.get(key)
        if cur is None:
            buckets[key] = dict(r)
            continue
        for f in sum_fields:
            cur[f] = int(cur.get(f, 0) or 0) + int(r.get(f, 0) or 0)
        if int(r.get("_pick_id", 0) or 0) > int(cur.get("_pick_id", 0) or 0):
            for f in ("name", "team", "position", "overall", "person_id"):
                if f in r:
                    cur[f] = r[f]
    return list(buckets.values())


def _open_session(path: str) -> tuple[Session, Any]:
    from utils.migrate_lineup_slot import ensure_lineup_slot_schema

    ensure_lineup_slot_schema(path)
    eng = create_engine(f"sqlite:///{path}")
    return sessionmaker(bind=eng)(), eng


def _merge_across_positions(merge_by_player: bool, pick_club: str | None) -> bool:
    """Топ-100 / за всё время: одна карьера на игрока, клуб из активного сезона."""
    return bool(merge_by_player and pick_club == "active_season")


def _fold_outfield_bucket(
    buckets: dict,
    p: Any,
    season_num: int,
    *,
    merge_by_player: bool,
    pick_club: str | None = None,
) -> None:
    from utils.player_names import player_stats_identity_token

    k = _bucket_key_for_row(
        p,
        merge_by_player=merge_by_player,
        merge_across_positions=_merge_across_positions(
            merge_by_player, pick_club
        ),
    )
    if k not in buckets:
        buckets[k] = {
            "name": p.name,
            "identity": player_stats_identity_token(p),
            "team": p.team,
            "position": p.position,
            "overall": int(getattr(p, "overall", 0) or 0),
            "goals": 0,
            "assists": 0,
            "ga": 0,
            "matches": 0,
            "potm": 0,
            "motm": 0,
            "last_season": season_num if merge_by_player else None,
        }
    b = buckets[k]
    g = int(getattr(p, "goals", 0) or 0)
    a = int(getattr(p, "assists", 0) or 0)
    b["goals"] += g
    b["assists"] += a
    b["ga"] += int(getattr(p, "ga", 0) or 0) or (g + a)
    b["matches"] += int(getattr(p, "matches", 0) or 0)
    b["potm"] += int(getattr(p, "potm", 0) or 0)
    b["motm"] += int(getattr(p, "motm", 0) or 0)
    from utils.person_registry import row_person_id

    pid = row_person_id(p)
    if pid is not None:
        b["person_id"] = pid
    _apply_club_label(
        b, p, season_num, merge_by_player=merge_by_player, pick_club=pick_club
    )


def _fold_cards_bucket(
    buckets: dict,
    p: Any,
    season_num: int,
    *,
    merge_by_player: bool,
    pick_club: str | None = None,
) -> None:
    from utils.player_names import player_stats_identity_token

    k = _bucket_key_for_row(
        p,
        merge_by_player=merge_by_player,
        merge_across_positions=_merge_across_positions(
            merge_by_player, pick_club
        ),
    )
    if k not in buckets:
        buckets[k] = {
            "name": p.name,
            "identity": player_stats_identity_token(p),
            "team": p.team,
            "position": p.position,
            "overall": int(getattr(p, "overall", 0) or 0),
            "yellow_cards": 0,
            "red_cards": 0,
            "matches": 0,
            "last_season": season_num if merge_by_player else None,
        }
    b = buckets[k]
    b["yellow_cards"] += int(getattr(p, "yellow_cards", 0) or 0)
    b["red_cards"] += int(getattr(p, "red_cards", 0) or 0)
    b["matches"] += int(getattr(p, "matches", 0) or 0)
    _apply_club_label(
        b, p, season_num, merge_by_player=merge_by_player, pick_club=pick_club
    )


def _fold_cs_bucket(
    buckets: dict,
    p: Any,
    season_num: int,
    *,
    merge_by_player: bool,
    pick_club: str | None = None,
) -> None:
    from utils.player_names import player_stats_identity_token

    k = _bucket_key_for_row(
        p,
        merge_by_player=merge_by_player,
        merge_across_positions=_merge_across_positions(
            merge_by_player, pick_club
        ),
    )
    if k not in buckets:
        buckets[k] = {
            "name": p.name,
            "identity": player_stats_identity_token(p),
            "team": p.team,
            "position": p.position,
            "clean_sheets": 0,
            "matches": 0,
            "potm": 0,
            "motm": 0,
            "last_season": season_num if merge_by_player else None,
        }
    b = buckets[k]
    b["clean_sheets"] += int(getattr(p, "clean_sheets", 0) or 0)
    b["matches"] += int(getattr(p, "matches", 0) or 0)
    b["potm"] += int(getattr(p, "potm", 0) or 0)
    b["motm"] += int(getattr(p, "motm", 0) or 0)
    _apply_club_label(
        b, p, season_num, merge_by_player=merge_by_player, pick_club=pick_club
    )


def _filter_code_for_life(league_code: str | None) -> str | None:
    if is_all_championships(league_code):
        return None
    return league_code


def _aggregate_outfield_from_db(
    db_path: str,
    filter_code: str | None,
    *,
    merge_by_player: bool,
    pick_club: str | None,
    skip_zero_ga_cl: bool = False,
) -> list[dict]:
    if not os.path.isfile(db_path):
        return []
    team_set = _team_filter_set(filter_code)
    buckets: dict[tuple, dict] = {}
    session, eng = _open_session(db_path)
    try:
        for Cls in _OUTFIELD:
            for p in session.query(Cls).all():
                if team_set is not None and _norm_team(p.team) not in team_set:
                    continue
                if skip_zero_ga_cl:
                    if int(getattr(p, "goals", 0) or 0) == 0 and int(
                        getattr(p, "assists", 0) or 0
                    ) == 0:
                        continue
                _fold_outfield_bucket(
                    buckets,
                    p,
                    0,
                    merge_by_player=merge_by_player,
                    pick_club=pick_club,
                )
    finally:
        session.close()
        eng.dispose()
    rows = list(buckets.values())
    if pick_club == "active_season":
        return _finalize_life_rows(rows)
    for b in rows:
        b.pop("_pick_m", None)
        b.pop("_pick_ga", None)
        b.pop("_pick_id", None)
    return rows


def _all_season_numbers(*, include_cl: bool) -> list[int]:
    nums = set(list_season_archives_with_db())
    if include_cl:
        nums |= set(_list_season_archives_with_cl())
    return sorted(nums)


def _db_passes_for_season(league_code: str | None) -> list[tuple[str, str | None]]:
    """kind: league | cl | common | wc → filter_code для клубов."""
    if is_all_leagues_plus_cl_plus_wc(league_code):
        return [("common", None), ("wc", None)]
    if is_all_leagues_plus_cl(league_code):
        return [("common", None)]
    if is_all_leagues_only(league_code):
        return [("league", None)]
    if league_code == "cl":
        return [("cl", "cl")]
    if league_code == "wc":
        return [("wc", None)]
    return [("league", league_code)]


def _season_path_by_kind(season_num: int, kind: str) -> str | None:
    if kind == "common":
        return _season_common_path(season_num)
    if kind == "cl":
        return _season_db_path(season_num, cl=True)
    if kind == "wc":
        return _season_wc_path(season_num)
    return _season_db_path(season_num, cl=False)


def _aggregate_wc_life_outfield(*, merge_by_player: bool = True) -> list[dict]:
    buckets: dict[tuple, dict] = {}
    for season_num, path in _iter_wc_db_paths():
        session, eng = _open_session(path)
        try:
            for Cls in _OUTFIELD:
                for p in session.query(Cls).all():
                    _fold_outfield_bucket(
                        buckets,
                        p,
                        season_num,
                        merge_by_player=merge_by_player,
                        pick_club="active_season",
                    )
        finally:
            session.close()
            eng.dispose()
    return _finalize_life_rows(list(buckets.values()))


def _aggregate_wc_life_cards(*, merge_by_player: bool = True) -> list[dict]:
    buckets: dict[tuple, dict] = {}
    for season_num, path in _iter_wc_db_paths():
        session, eng = _open_session(path)
        try:
            for Cls in _ALL:
                for p in session.query(Cls).all():
                    _fold_cards_bucket(
                        buckets,
                        p,
                        season_num,
                        merge_by_player=merge_by_player,
                        pick_club="active_season",
                    )
        finally:
            session.close()
            eng.dispose()
    return _finalize_life_rows(list(buckets.values()))


def _aggregate_wc_life_clean_sheets(*, merge_by_player: bool = True) -> list[dict]:
    buckets: dict[tuple, dict] = {}
    for season_num, path in _iter_wc_db_paths():
        session, eng = _open_session(path)
        try:
            for p in session.query(Goalkeeper).all():
                _fold_cs_bucket(
                    buckets,
                    p,
                    season_num,
                    merge_by_player=merge_by_player,
                    pick_club="active_season",
                )
        finally:
            session.close()
            eng.dispose()
    return _finalize_life_rows(list(buckets.values()))


def aggregate_outfield(
    league_code: str | None,
    *,
    season_num: int | None = None,
    merge_by_player: bool = True,
) -> list[dict]:
    """Снимок одного сезона (не накопительные synced)."""
    league_code = normalize_stats_league_code(league_code) or league_code
    if season_num is None:
        return aggregate_life_outfield(league_code, merge_by_player=merge_by_player)
    buckets: dict[tuple, dict] = {}
    for kind, filter_code in _db_passes_for_season(league_code):
        path = _season_path_by_kind(season_num, kind)
        if not path:
            continue
        team_set = _team_filter_set(filter_code)
        session, eng = _open_session(path)
        try:
            for Cls in _OUTFIELD:
                for p in session.query(Cls).all():
                    if team_set is not None and _norm_team(p.team) not in team_set:
                        continue
                    if kind == "cl":
                        if int(getattr(p, "goals", 0) or 0) == 0 and int(
                            getattr(p, "assists", 0) or 0
                        ) == 0:
                            continue
                    _fold_outfield_bucket(
                        buckets,
                        p,
                        season_num,
                        merge_by_player=merge_by_player,
                        pick_club="latest_row",
                    )
        finally:
            session.close()
            eng.dispose()
    rows = list(buckets.values())
    for b in rows:
        b.pop("_pick_m", None)
        b.pop("_pick_ga", None)
        b.pop("_pick_id", None)
        b.pop("last_season", None)
    return rows


def aggregate_life_outfield(
    league_code: str | None,
    *,
    cl: bool = False,
    merge_by_player: bool = True,
) -> list[dict]:
    league_code = normalize_stats_league_code(league_code) or league_code
    if cl:
        code = "cl"
    elif league_code == "wc":
        return _aggregate_wc_life_outfield(merge_by_player=merge_by_player)
    elif is_all_leagues_plus_cl_plus_wc(league_code):
        base = aggregate_life_outfield("allcl", merge_by_player=merge_by_player)
        wc = _aggregate_wc_life_outfield(merge_by_player=merge_by_player)
        merged = _merge_stat_rows(
            base,
            wc,
            sum_fields=("goals", "assists", "ga", "matches", "potm", "motm"),
        )
        return _finalize_life_rows(merged)
    else:
        code = league_code
    db_path, _ = _life_cumulative_db(code)
    if not db_path:
        return []
    return _aggregate_outfield_from_db(
        db_path,
        _filter_code_for_life(code),
        merge_by_player=merge_by_player,
        pick_club="active_season",
        skip_zero_ga_cl=code == "cl",
    )


def aggregate_life_combined_outfield(*, merge_by_player: bool = True) -> list[dict]:
    return aggregate_life_outfield("allcl", merge_by_player=merge_by_player)


def _aggregate_cards_from_db(
    db_path: str,
    filter_code: str | None,
    *,
    merge_by_player: bool,
    pick_club: str | None,
    season_num: int = 0,
) -> list[dict]:
    if not os.path.isfile(db_path):
        return []
    team_set = _team_filter_set(filter_code)
    buckets: dict[tuple, dict] = {}
    session, eng = _open_session(db_path)
    try:
        for Cls in _ALL:
            for p in session.query(Cls).all():
                if team_set is not None and _norm_team(p.team) not in team_set:
                    continue
                _fold_cards_bucket(
                    buckets,
                    p,
                    season_num,
                    merge_by_player=merge_by_player,
                    pick_club=pick_club,
                )
    finally:
        session.close()
        eng.dispose()
    return list(buckets.values())


def aggregate_cards(
    league_code: str | None,
    *,
    season_num: int | None = None,
    merge_by_player: bool = True,
) -> list[dict]:
    league_code = normalize_stats_league_code(league_code) or league_code
    if season_num is None:
        return aggregate_life_cards(league_code, merge_by_player=merge_by_player)
    buckets: dict[tuple, dict] = {}
    for kind, filter_code in _db_passes_for_season(league_code):
        path = _season_path_by_kind(season_num, kind)
        if not path:
            continue
        team_set = _team_filter_set(filter_code)
        session, eng = _open_session(path)
        try:
            for Cls in _ALL:
                for p in session.query(Cls).all():
                    if team_set is not None and _norm_team(p.team) not in team_set:
                        continue
                    _fold_cards_bucket(
                        buckets,
                        p,
                        season_num,
                        merge_by_player=merge_by_player,
                        pick_club="latest_row",
                    )
        finally:
            session.close()
            eng.dispose()
    rows = list(buckets.values())
    for b in rows:
        b.pop("_pick_ga", None)
        b.pop("_pick_id", None)
        b.pop("last_season", None)
    return rows


def aggregate_life_cards(
    league_code: str | None,
    *,
    cl: bool = False,
    merge_by_player: bool = True,
) -> list[dict]:
    league_code = normalize_stats_league_code(league_code) or league_code
    if cl:
        code = "cl"
    elif league_code == "wc":
        return _aggregate_wc_life_cards(merge_by_player=merge_by_player)
    elif is_all_leagues_plus_cl_plus_wc(league_code):
        base = aggregate_life_cards("allcl", merge_by_player=merge_by_player)
        wc = _aggregate_wc_life_cards(merge_by_player=merge_by_player)
        merged = _merge_stat_rows(
            base,
            wc,
            sum_fields=("yellow_cards", "red_cards", "matches", "potm", "motm"),
        )
        return _finalize_life_rows(merged)
    else:
        code = league_code
    db_path, _ = _life_cumulative_db(code)
    if not db_path:
        return []
    rows = _aggregate_cards_from_db(
        db_path,
        _filter_code_for_life(code),
        merge_by_player=merge_by_player,
        pick_club="active_season",
    )
    return _finalize_life_rows(rows)


def aggregate_clean_sheets(
    league_code: str | None,
    *,
    season_num: int | None = None,
    merge_by_player: bool = True,
) -> tuple[list[dict], list[dict]]:
    if season_num is None:
        return aggregate_life_clean_sheets(league_code, merge_by_player=merge_by_player)
    gk_buckets: dict[tuple, dict] = {}
    for kind, filter_code in _db_passes_for_season(league_code):
        path = _season_path_by_kind(season_num, kind)
        if not path:
            continue
        team_set = _team_filter_set(filter_code)
        session, eng = _open_session(path)
        try:
            for p in session.query(Goalkeeper).all():
                if team_set is not None and _norm_team(p.team) not in team_set:
                    continue
                _fold_cs_bucket(
                    gk_buckets,
                    p,
                    season_num,
                    merge_by_player=merge_by_player,
                    pick_club="latest_row",
                )
        finally:
            session.close()
            eng.dispose()
    gk = list(gk_buckets.values())
    for b in gk:
        b.pop("_pick_ga", None)
        b.pop("_pick_id", None)
        b.pop("last_season", None)
    return gk, []


def aggregate_life_clean_sheets(
    league_code: str | None,
    *,
    cl: bool = False,
    merge_by_player: bool = True,
) -> tuple[list[dict], list[dict]]:
    league_code = normalize_stats_league_code(league_code) or league_code
    if cl:
        code = "cl"
    elif league_code == "wc":
        return _aggregate_wc_life_clean_sheets(merge_by_player=merge_by_player), []
    elif is_all_leagues_plus_cl_plus_wc(league_code):
        base_gk, _ = aggregate_life_clean_sheets("allcl", merge_by_player=merge_by_player)
        wc_gk = _aggregate_wc_life_clean_sheets(merge_by_player=merge_by_player)
        merged = _merge_stat_rows(
            base_gk,
            wc_gk,
            sum_fields=("clean_sheets", "matches", "potm", "motm"),
        )
        return _finalize_life_rows(merged), []
    else:
        code = league_code
    db_path, _ = _life_cumulative_db(code)
    if not os.path.isfile(db_path):
        return [], []
    team_set = _team_filter_set(_filter_code_for_life(code))
    gk_buckets: dict[tuple, dict] = {}
    session, eng = _open_session(db_path)
    try:
        for p in session.query(Goalkeeper).all():
            if team_set is not None and _norm_team(p.team) not in team_set:
                continue
            _fold_cs_bucket(
                gk_buckets,
                p,
                0,
                merge_by_player=merge_by_player,
                pick_club="active_season",
            )
    finally:
        session.close()
        eng.dispose()
    gk = list(gk_buckets.values())
    return _finalize_life_rows(gk), []


def _list_season_archives_with_cl() -> list[int]:
    out: list[int] = []
    db_dir = os.path.join(season_paths.PROJECT_ROOT, "db")
    if not os.path.isdir(db_dir):
        return out
    for name in os.listdir(db_dir):
        if not name.startswith("season_"):
            continue
        tail = name.replace("season_", "")
        if not tail.isdigit():
            continue
        n = int(tail)
        cp = os.path.join(db_dir, name, season_paths.SEASON_CL_NAME)
        if os.path.isfile(cp):
            out.append(n)
    active = season_paths.get_active_season()
    if active not in out and os.path.isfile(season_paths.get_cl_db_path()):
        out.append(active)
    return sorted(set(out))


def _display_league_name(league_code: str | None, *, cl: bool = False) -> str:
    if cl:
        return LEAGUE_NAMES["cl"]
    if is_all_leagues_plus_cl_plus_wc(league_code):
        return "Все чемпионаты (лиги + ЛЧ + сборные)"
    if is_all_leagues_plus_cl(league_code):
        return "Все чемпионаты (лиги + ЛЧ)"
    if is_all_leagues_only(league_code):
        return "Все чемпионаты (нац. лиги)"
    return LEAGUE_NAMES.get(league_code or "", league_code or "?")


def _life_title_suffix(league_code: str | None, *, cl: bool) -> str:
    code = "cl" if cl else league_code
    _, db_label = _life_cumulative_db(code)
    return f" — все сезоны ({db_label}, сумма по игроку)"


def _season_title_suffix(season_num: int, league_code: str | None, *, cl: bool) -> str:
    if is_all_leagues_plus_cl_plus_wc(league_code):
        return f" — сезон {season_num} (лига+ЛЧ+сборные · сумма · текущий клуб)"
    if is_all_leagues_plus_cl(league_code):
        return f" — сезон {season_num} (лига+ЛЧ · сумма · текущий клуб)"
    if is_all_leagues_only(league_code):
        return f" — сезон {season_num} (все нац. лиги · сумма · текущий клуб)"
    if cl or league_code == "cl":
        return f" — сезон {season_num} (ЛЧ · одна строка · последний клуб)"
    if league_code == "wc":
        return f" — сезон {season_num} (ЧМ · одна строка · последняя сборная)"
    return f" — сезон {season_num} (сумма в лиге · финальный клуб)"


def life_has_archive_data(*, cl: bool = False) -> bool:
    if cl:
        return os.path.isfile(season_paths.get_cumulative_cl_db_path())
    return os.path.isfile(season_paths.get_cumulative_league_db_path())


def life_has_combined_archive_data() -> bool:
    return os.path.isfile(season_paths.get_cumulative_common_db_path())


def life_has_wc_archive_data() -> bool:
    return bool(_iter_wc_db_paths())


def life_has_allclwc_archive_data() -> bool:
    return life_has_combined_archive_data() or life_has_wc_archive_data()


def format_life_top_scorers(league_code: str | None, limit: int = 30) -> str:
    import contextlib
    import io

    cl = league_code == "cl"
    players = aggregate_life_outfield(league_code, merge_by_player=True)
    players = [p for p in players if int(p.get("goals", 0) or 0) > 0]
    players.sort(key=lambda x: (-x["goals"], -x["assists"]))
    league_name = _display_league_name(league_code, cl=cl) + _life_title_suffix(
        league_code, cl=cl
    )

    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        print(f"\n{'='*65}")
        print(f"  ТОП-{limit} БОМБАРДИРОВ - {league_name}")
        print(f"{'='*65}")
        print(
            f"{'#':<4} {'Игрок':<18} {'Команда':<15} {'Поз':<5} {'Г':<4} {'А':<4} {'Г+А':<5} {'POTM':<4} {'MOTM':<4}"
        )
        print("-" * 69)
        if not players:
            print("  Нет данных")
        else:
            for i, p in enumerate(players[:limit], 1):
                print(
                    f"{i:<4} {p['name']:<18} {p['team']:<15} {p['position']:<5} "
                    f"{p['goals']:<4} {p['assists']:<4} {p['ga']:<5} "
                    f"{int(p.get('potm', 0)):<4} {int(p.get('motm', 0)):<4}"
                )
    return buf.getvalue()


def format_life_top_assists(league_code: str | None, limit: int = 30) -> str:
    import contextlib
    import io

    cl = league_code == "cl"
    players = aggregate_life_outfield(league_code, merge_by_player=True)
    players = [p for p in players if int(p.get("assists", 0) or 0) > 0]
    players.sort(key=lambda x: (-x["assists"], -x["goals"]))
    league_name = _display_league_name(league_code, cl=cl) + _life_title_suffix(
        league_code, cl=cl
    )

    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        print(f"\n{'='*65}")
        print(f"  ТОП-{limit} АССИСТЕНТОВ - {league_name}")
        print(f"{'='*65}")
        print(
            f"{'#':<4} {'Игрок':<18} {'Команда':<15} {'Поз':<5} {'А':<4} {'Г':<4} {'Г+А':<5} {'POTM':<4} {'MOTM':<4}"
        )
        print("-" * 69)
        if not players:
            print("  Нет данных")
        else:
            for i, p in enumerate(players[:limit], 1):
                print(
                    f"{i:<4} {p['name']:<18} {p['team']:<15} {p['position']:<5} "
                    f"{p['assists']:<4} {p['goals']:<4} {p['ga']:<5} "
                    f"{int(p.get('potm', 0)):<4} {int(p.get('motm', 0)):<4}"
                )
    return buf.getvalue()


def format_life_top_ga(league_code: str | None, limit: int = 30) -> str:
    import contextlib
    import io

    cl = league_code == "cl"
    players = aggregate_life_outfield(league_code, merge_by_player=True)
    players = [p for p in players if int(p.get("ga", 0) or 0) > 0]
    players.sort(key=lambda x: (-x["ga"], -x["goals"]))
    league_name = _display_league_name(league_code, cl=cl) + _life_title_suffix(
        league_code, cl=cl
    )

    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        print(f"\n{'='*65}")
        print(f"  ТОП-{limit} ПО Г+А - {league_name}")
        print(f"{'='*65}")
        print(
            f"{'#':<4} {'Игрок':<18} {'Команда':<15} {'Поз':<5} {'Г+А':<5} {'Г':<4} {'А':<4} {'MOTM':<4}"
        )
        print("-" * 69)
        if not players:
            print("  Нет данных")
        else:
            for i, p in enumerate(players[:limit], 1):
                print(
                    f"{i:<4} {p['name']:<18} {p['team']:<15} {p['position']:<5} "
                    f"{p['ga']:<5} {p['goals']:<4} {p['assists']:<4} "
                    f"{int(p.get('potm', 0)):<4} {int(p.get('motm', 0)):<4}"
                )
    return buf.getvalue()


def format_life_top_cards(
    league_code: str | None, metric: str, limit: int = 30
) -> str:
    cl = league_code == "cl"
    rows = aggregate_cards(league_code, merge_by_player=True)
    m = metric.lower()
    field = "yellow_cards" if m == "yc" else "red_cards"
    title = "жёлтые карточки" if m == "yc" else "красные карточки"
    picked = [r for r in rows if int(r.get(field, 0) or 0) > 0]
    picked.sort(
        key=lambda x: (
            -int(x.get(field, 0) or 0),
            -int(x.get("matches", 0) or 0),
            str(x.get("name", "")).casefold(),
        )
    )
    lg_label = _display_league_name(league_code, cl=cl)
    out = [f"Топ {title}{_life_title_suffix(league_code, cl=cl)}"]
    out.append(f"Лига: {lg_label}")
    out.append("")
    if not picked:
        out.append("Нет данных.")
        return "\n".join(out)
    out.append(f"{'№':>2} {'Игрок':<24} {'Клуб':<18} {'Матч':>5} {'Знач':>5}")
    for i, r in enumerate(picked[:limit], start=1):
        out.append(
            f"{i:>2} {str(r['name'])[:24]:<24} {str(r['team'])[:18]:<18} "
            f"{int(r.get('matches', 0) or 0):>5} {int(r.get(field, 0) or 0):>5}"
        )
    return "\n".join(out)


def format_life_clean_sheets(
    league_code: str | None, limit: int = 30
) -> tuple[str, str]:
    cl = league_code == "cl"
    gk_rows, df_rows = aggregate_clean_sheets(league_code, merge_by_player=True)

    def _sort(rows: list[dict]) -> list[dict]:
        rows = [r for r in rows if int(r.get("clean_sheets", 0) or 0) > 0]
        rows.sort(
            key=lambda x: (
                -int(x.get("clean_sheets", 0) or 0),
                -int(x.get("matches", 0) or 0),
                str(x.get("name", "")).casefold(),
            )
        )
        return rows

    gk_rows = _sort(gk_rows)
    df_rows = _sort(df_rows)
    lg_label = _display_league_name(league_code, cl=cl)
    suf = _life_title_suffix(league_code, cl=cl)

    def _fmt(rows: list[dict], role: str) -> str:
        title = f"Сухие матчи · {role}{suf}"
        out = [title, f"Лига: {lg_label}", ""]
        if not rows:
            out.append("Нет данных.")
            return "\n".join(out)
        out.append(f"{'№':>2} {'Игрок':<24} {'Клуб':<18} {'Матч':>5} {'Сух':>5}")
        for i, r in enumerate(rows[:limit], start=1):
            out.append(
                f"{i:>2} {str(r['name'])[:24]:<24} {str(r['team'])[:18]:<18} "
                f"{int(r.get('matches', 0) or 0):>5} "
                f"{int(r.get('clean_sheets', 0) or 0):>5}"
            )
        return "\n".join(out)

    return _fmt(gk_rows, "вратари"), _fmt([], "защитники")


def season_has_db(season_num: int, league_code: str | None) -> bool:
    for kind, _fc in _db_passes_for_season(league_code):
        if _season_path_by_kind(season_num, kind):
            return True
    return False


def format_season_stat(
    season_num: int,
    league_code: str | None,
    metric: str,
    limit: int = 30,
) -> str:
    """Топ из одного сезона: g | as | ga | yc | rc."""
    import contextlib
    import io

    m = (metric or "g").lower()
    cl = league_code == "cl"
    suf = _season_title_suffix(season_num, league_code, cl=cl)
    league_name = _display_league_name(league_code, cl=cl) + suf

    if m in ("yc", "rc"):
        rows = aggregate_cards(league_code, season_num=season_num, merge_by_player=True)
        field = "yellow_cards" if m == "yc" else "red_cards"
        title = "жёлтые карточки" if m == "yc" else "красные карточки"
        picked = [r for r in rows if int(r.get(field, 0) or 0) > 0]
        picked.sort(
            key=lambda x: (
                -int(x.get(field, 0) or 0),
                -int(x.get("matches", 0) or 0),
                str(x.get("name", "")).casefold(),
            )
        )
        out = [f"Топ {title}{suf}", f"Лига: {_display_league_name(league_code, cl=cl)}", ""]
        if not picked:
            out.append("Нет данных.")
            return "\n".join(out)
        out.append(f"{'№':>2} {'Игрок':<24} {'Клуб':<18} {'Матч':>5} {'Знач':>5}")
        for i, r in enumerate(picked[:limit], start=1):
            out.append(
                f"{i:>2} {str(r['name'])[:24]:<24} {str(r['team'])[:18]:<18} "
                f"{int(r.get('matches', 0) or 0):>5} {int(r.get(field, 0) or 0):>5}"
            )
        return "\n".join(out)

    players = aggregate_outfield(
        league_code, season_num=season_num, merge_by_player=True
    )
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        if m in ("g", "goals"):
            players = [p for p in players if int(p.get("goals", 0) or 0) > 0]
            players.sort(key=lambda x: (-x["goals"], -x["assists"]))
            print(f"\n{'='*65}")
            print(f"  ТОП-{limit} БОМБАРДИРОВ - {league_name}")
            print(f"{'='*65}")
            print(
                f"{'#':<4} {'Игрок':<18} {'Команда':<15} {'Поз':<5} "
                f"{'Г':<4} {'А':<4} {'Г+А':<5} {'POTM':<4} {'MOTM':<4}"
            )
            print("-" * 69)
            if not players:
                print("  Нет данных")
            else:
                for i, p in enumerate(players[:limit], 1):
                    print(
                        f"{i:<4} {p['name']:<18} {p['team']:<15} {p['position']:<5} "
                        f"{p['goals']:<4} {p['assists']:<4} {p['ga']:<5} "
                        f"{int(p.get('potm', 0)):<4} {int(p.get('motm', 0)):<4}"
                    )
        elif m in ("as", "a", "assists"):
            players = [p for p in players if int(p.get("assists", 0) or 0) > 0]
            players.sort(key=lambda x: (-x["assists"], -x["goals"]))
            print(f"\n{'='*65}")
            print(f"  ТОП-{limit} АССИСТЕНТОВ - {league_name}")
            print(f"{'='*65}")
            print(
                f"{'#':<4} {'Игрок':<18} {'Команда':<15} {'Поз':<5} "
                f"{'А':<4} {'Г':<4} {'Г+А':<5} {'POTM':<4} {'MOTM':<4}"
            )
            print("-" * 69)
            if not players:
                print("  Нет данных")
            else:
                for i, p in enumerate(players[:limit], 1):
                    print(
                        f"{i:<4} {p['name']:<18} {p['team']:<15} {p['position']:<5} "
                        f"{p['assists']:<4} {p['goals']:<4} {p['ga']:<5} "
                        f"{int(p.get('potm', 0)):<4} {int(p.get('motm', 0)):<4}"
                    )
        elif m in ("ga", "g+a"):
            players = [p for p in players if int(p.get("ga", 0) or 0) > 0]
            players.sort(key=lambda x: (-x["ga"], -x["goals"]))
            print(f"\n{'='*65}")
            print(f"  ТОП-{limit} ПО Г+А - {league_name}")
            print(f"{'='*65}")
            print(
                f"{'#':<4} {'Игрок':<18} {'Команда':<15} {'Поз':<5} "
                f"{'Г+А':<5} {'Г':<4} {'А':<4} {'MOTM':<4}"
            )
            print("-" * 69)
            if not players:
                print("  Нет данных")
            else:
                for i, p in enumerate(players[:limit], 1):
                    print(
                        f"{i:<4} {p['name']:<18} {p['team']:<15} {p['position']:<5} "
                        f"{p['ga']:<5} {p['goals']:<4} {p['assists']:<4} "
                        f"{int(p.get('potm', 0)):<4} {int(p.get('motm', 0)):<4}"
                    )
        else:
            return f"Неизвестная метрика: {metric!r}"
    return buf.getvalue()


def format_season_clean_sheets(
    season_num: int,
    league_code: str | None,
    limit: int = 30,
) -> tuple[str, str]:
    cl = league_code == "cl"
    gk_rows, df_rows = aggregate_clean_sheets(
        league_code, season_num=season_num, merge_by_player=True
    )
    suf = _season_title_suffix(season_num, league_code, cl=cl)
    lg_label = _display_league_name(league_code, cl=cl)

    def _sort(rows: list[dict]) -> list[dict]:
        rows = [r for r in rows if int(r.get("clean_sheets", 0) or 0) > 0]
        rows.sort(
            key=lambda x: (
                -int(x.get("clean_sheets", 0) or 0),
                -int(x.get("matches", 0) or 0),
                str(x.get("name", "")).casefold(),
            )
        )
        return rows

    def _fmt(rows: list[dict], role: str) -> str:
        title = f"Сухие матчи · {role}{suf}"
        out = [title, f"Лига: {lg_label}", ""]
        if not rows:
            out.append("Нет данных.")
            return "\n".join(out)
        out.append(f"{'№':>2} {'Игрок':<24} {'Клуб':<18} {'Матч':>5} {'Сух':>5}")
        for i, r in enumerate(rows[:limit], start=1):
            out.append(
                f"{i:>2} {str(r['name'])[:24]:<24} {str(r['team'])[:18]:<18} "
                f"{int(r.get('matches', 0) or 0):>5} "
                f"{int(r.get('clean_sheets', 0) or 0):>5}"
            )
        return "\n".join(out)

    return _fmt(_sort(gk_rows), "вратари"), _fmt(_sort(df_rows), "защитники")


def collect_top100_rows(
    league_code: str | None,
    limit: int = 100,
    sort_key: int = 1,
) -> tuple[str | None, list[dict], int, str | None]:
    """
    Топ-N за всё время: ``all`` — нац. лиги; ``allcl`` — лига + ЛЧ.

    Возвращает (scope_line, rows, n_candidates, error_message).
    При ошибке ``error_message`` не None, ``rows`` пустой.
    """
    code = normalize_stats_league_code(league_code) or league_code
    if is_all_leagues_plus_cl_plus_wc(code):
        if not life_has_allclwc_archive_data():
            return (
                None,
                [],
                0,
                (
                    "Пока нет архивов сезонов с common.db / world_cup.db. "
                    "После игры и «Завершить сезон» появятся снимки в db/season_N/."
                ),
            )
        scope_line = "лига + ЛЧ + сборные, все лиги"
    elif is_all_leagues_plus_cl(code):
        if not life_has_combined_archive_data():
            return (
                None,
                [],
                0,
                (
                    "Пока нет архивов сезонов с league.db / champions_league.db. "
                    "После игры и «Завершить сезон» появятся снимки в db/season_N/."
                ),
            )
        scope_line = "лига + ЛЧ, все лиги"
    elif is_all_leagues_only(code):
        if not life_has_archive_data():
            return (
                None,
                [],
                0,
                (
                    "Пока нет архивов сезонов с league.db. "
                    "После «Завершить сезон» появятся снимки в db/season_N/."
                ),
            )
        scope_line = "все нац. лиги (без ЛЧ)"
    elif code == "wc":
        if not life_has_wc_archive_data():
            return (
                None,
                [],
                0,
                (
                    "Пока нет архивов сезонов с world_cup.db. "
                    "После «Завершить сезон» появятся снимки в db/season_N/."
                ),
            )
        scope_line = "ЧМ (сборные)"
    else:
        return None, [], 0, "Топ-100: укажите all, allcl или allclwc."

    rows = aggregate_life_outfield(code, merge_by_player=True)
    rows = [
        r
        for r in rows
        if int(r.get("goals", 0) or 0) > 0 or int(r.get("assists", 0) or 0) > 0
    ]
    n_cand = len(rows)

    if sort_key == 2:
        rows.sort(key=lambda x: (-x["assists"], -x["goals"], x["name"].casefold()))
    elif sort_key == 3:
        rows.sort(key=lambda x: (-x["ga"], -x["goals"], x["name"].casefold()))
    else:
        rows.sort(key=lambda x: (-x["goals"], -x["assists"], x["name"].casefold()))

    return scope_line, rows[:limit], n_cand, None


def format_top100_str(
    league_code: str | None,
    limit: int = 100,
    sort_key: int = 1,
) -> str:
    """Топ-100 за всё время: ``all`` — нац. лиги; ``allcl`` — лига + ЛЧ."""
    import contextlib
    import io

    scope_line, rows, n_cand, err = collect_top100_rows(
        league_code, limit=limit, sort_key=sort_key
    )
    if err:
        return err

    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        print("\n" + "=" * 76)
        print(
            f"  ТОП-{limit} — {scope_line} (снимки сезонов, сумма по игроку) "
            f"(с голом или передачей; кандидатов: {n_cand})"
        )
        print("=" * 76)
        hdr = (
            f"{'#':<4} {'Игрок':<20} {'Команда':<18} {'Поз':<5} "
            f"{'И':>4} {'Г':>4} {'А':>4} {'Г+А':>5} {'POTM':>4} {'MOTM':>4}"
        )
        print()
        print(hdr)
        print("-" * 80)
        for i, p in enumerate(rows, 1):
            print(
                f"{i:<4} {p['name']:<20} {p['team']:<18} {p['position']:<5} "
                f"{int(p.get('matches', 0) or 0):>4} {p['goals']:>4} {p['assists']:>4} "
                f"{p['ga']:>5} {int(p.get('potm', 0)):>4} {int(p.get('motm', 0)):>4}"
            )
        print("-" * 80)
    return buf.getvalue().strip()


def format_top100_combined_str(limit: int = 100, sort_key: int = 1) -> str:
    """Топ-100: лига + ЛЧ (``allcl``)."""
    return format_top100_str("allcl", limit=limit, sort_key=sort_key)


def _sort_outfield_for_metric(rows: list[dict], metric: str) -> list[dict]:
    m = (metric or "g").lower()
    if m in ("as", "a", "assists"):
        rows = [r for r in rows if int(r.get("assists", 0) or 0) > 0]
        rows.sort(key=lambda x: (-x["assists"], -x["goals"], str(x.get("name", "")).casefold()))
    elif m in ("ga", "g+a"):
        rows = [r for r in rows if int(r.get("ga", 0) or 0) > 0]
        rows.sort(key=lambda x: (-x["ga"], -x["goals"], str(x.get("name", "")).casefold()))
    else:
        rows = [r for r in rows if int(r.get("goals", 0) or 0) > 0]
        rows.sort(key=lambda x: (-x["goals"], -x["assists"], str(x.get("name", "")).casefold()))
    return rows


def _sort_cards_for_metric(rows: list[dict], metric: str) -> list[dict]:
    m = (metric or "yc").lower()
    field = "yellow_cards" if m == "yc" else "red_cards"
    picked = [r for r in rows if int(r.get(field, 0) or 0) > 0]
    picked.sort(
        key=lambda x: (
            -int(x.get(field, 0) or 0),
            -int(x.get("matches", 0) or 0),
            str(x.get("name", "")).casefold(),
        )
    )
    return picked


def _sort_clean_sheets(rows: list[dict]) -> list[dict]:
    rows = [r for r in rows if int(r.get("clean_sheets", 0) or 0) > 0]
    rows.sort(
        key=lambda x: (
            -int(x.get("clean_sheets", 0) or 0),
            -int(x.get("matches", 0) or 0),
            str(x.get("name", "")).casefold(),
        )
    )
    return rows


def collect_stats_history_rows(
    scope: str,
    league_code: str | None,
    metric: str,
    limit: int,
    *,
    season_num: int | None = None,
    role: str | None = None,
) -> tuple[str, list[dict], str | None]:
    """
    Строки для инфографики «Стата сезонов».

    ``scope``: ``life`` | ``season``; ``role``: ``gk`` | ``df`` только для ``cs``.
    Возвращает (заголовок, rows, error).
    """
    code = normalize_stats_league_code(league_code) or league_code
    m = (metric or "g").lower()
    cl = code == "cl"

    if scope == "life":
        if is_all_leagues_plus_cl_plus_wc(code):
            if not life_has_allclwc_archive_data():
                return "", [], (
                    "Пока нет архивов сезонов. "
                    "После «Завершить сезон» появятся снимки в db/season_N/."
                )
        elif is_all_leagues_plus_cl(code):
            if not life_has_combined_archive_data():
                return "", [], (
                    "Пока нет архивов сезонов. "
                    "После «Завершить сезон» появятся снимки в db/season_N/."
                )
        elif code == "wc":
            if not life_has_wc_archive_data():
                return "", [], (
                    "Пока нет архивов сезонов с world_cup.db. "
                    "После «Завершить сезон» появятся снимки в db/season_N/."
                )
        elif code == "cl":
            if not life_has_archive_data(cl=True):
                return "", [], (
                    "Пока нет архивов сезонов с champions_league.db. "
                    "После «Завершить сезон» появятся снимки в db/season_N/."
                )
        elif not life_has_archive_data():
            return "", [], (
                "Пока нет архивов сезонов с league.db. "
                "После «Завершить сезон» появятся снимки в db/season_N/."
            )
        lg = _display_league_name(code, cl=cl)
        suf = _life_title_suffix(code, cl=cl)
    elif scope == "season":
        if season_num is None:
            return "", [], "Ошибка: не указан сезон."
        if not season_has_db(season_num, code):
            return "", [], (
                f"В архиве сезона {season_num} нет данных для выбранного чемпионата."
            )
        lg = _display_league_name(code, cl=cl)
        suf = _season_title_suffix(season_num, code, cl=cl)
    else:
        return "", [], f"Неизвестный период: {scope!r}"

    if m == "cs":
        if scope == "life":
            gk_rows, df_rows = aggregate_life_clean_sheets(code, cl=cl)
        else:
            gk_rows, df_rows = aggregate_clean_sheets(
                code, season_num=season_num, merge_by_player=True
            )
        role_l = (role or "gk").lower()
        pool = _sort_clean_sheets(gk_rows if role_l == "gk" else df_rows)
        role_label = "вратари" if role_l == "gk" else "защитники"
        title = f"Сухие матчи · {role_label}{suf}"
        return title, pool[:limit], None

    if m in ("yc", "rc"):
        if scope == "life":
            rows = aggregate_cards(code, merge_by_player=True)
        else:
            rows = aggregate_cards(
                code, season_num=season_num, merge_by_player=True
            )
        field = "yellow_cards" if m == "yc" else "red_cards"
        label = "жёлтые карточки" if m == "yc" else "красные карточки"
        title = f"Топ {label}{suf}"
        return title, _sort_cards_for_metric(rows, m)[:limit], None

    if scope == "life":
        players = aggregate_life_outfield(code, merge_by_player=True)
    else:
        players = aggregate_outfield(
            code, season_num=season_num, merge_by_player=True
        )

    if m in ("g", "goals"):
        title = f"Топ бомбардиров{suf}"
    elif m in ("as", "a", "assists"):
        title = f"Топ ассистентов{suf}"
    elif m in ("ga", "g+a"):
        title = f"Топ по Г+А{suf}"
    else:
        return "", [], f"Неизвестная метрика: {metric!r}"

    return title, _sort_outfield_for_metric(players, m)[:limit], None
