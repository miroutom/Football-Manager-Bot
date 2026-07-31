# -*- coding: utf-8 -*-
"""
Выровнять ``person_id``: один человек в лиге и ЛЧ (и по клубам карьеры) → один id.

Проблема: при назначении id в сезоне 3+ ЛЧ иногда получал новый person_id
(Ди Мария: лига 4707, ЛЧ 4708), хотя в сезоне 2 уже был канон 41.

Стратегия (безопасно для однофамильцев):
- группируем по (имя, клуб);
- если у группы несколько person_id — пишем один канон на все строки этой группы;
- канон: id из архива s1–s2 по (имя+позиция), иначе id из активной league.db, иначе min.
"""
from __future__ import annotations

import os
import sqlite3
from collections import defaultdict
from typing import Any

from utils import season_paths
from utils.person_dedupe import iter_player_db_paths
from utils.person_registry import _identity_pos_key
from utils.player_transfer import _norm_cmp

_TABLES = ("forwards", "midfielders", "defenders", "goalkeepers")


def _archive_canonical_by_identity(
    seasons: tuple[int, ...] = (1, 2),
) -> dict[tuple[str, str], int]:
    """(ident, pos) → person_id из ранних архивов."""
    best: dict[tuple[str, str], tuple[int, int]] = {}
    db_dir = os.path.join(season_paths.PROJECT_ROOT, "db")
    for sn in seasons:
        for fname in (season_paths.SEASON_LEAGUE_NAME, season_paths.SEASON_CL_NAME):
            path = os.path.join(db_dir, f"season_{sn}", fname)
            if not os.path.isfile(path):
                continue
            conn = sqlite3.connect(path)
            try:
                for tbl in _TABLES:
                    cols = {
                        r[1] for r in conn.execute(f"PRAGMA table_info({tbl})").fetchall()
                    }
                    if "person_id" not in cols:
                        continue
                    for nm, pos_row, pid_raw, matches_raw in conn.execute(
                        f"SELECT name, position, person_id, matches FROM {tbl}"
                    ):
                        ident, pos = _identity_pos_key(nm or "", pos_row or "")
                        try:
                            pid = int(pid_raw or 0)
                        except (TypeError, ValueError):
                            continue
                        if pid <= 0:
                            continue
                        m = int(matches_raw or 0)
                        prev = best.get((ident, pos))
                        if prev is None or (m, -pid) > (prev[0], -prev[1]):
                            best[(ident, pos)] = (m, pid)
            finally:
                conn.close()
    return {k: pid for k, (_m, pid) in best.items()}


def collect_name_team_pids(
    paths: list[str] | None = None,
) -> dict[tuple[str, str], dict[str, Any]]:
    """
    (name_cf, team_cf) → {pids, name, team, position, samples}.
    """
    paths = paths or iter_player_db_paths()
    out: dict[tuple[str, str], dict[str, Any]] = {}
    for path in paths:
        conn = sqlite3.connect(path)
        try:
            for tbl in _TABLES:
                cols = {r[1] for r in conn.execute(f"PRAGMA table_info({tbl})").fetchall()}
                if "person_id" not in cols or "name" not in cols or "team" not in cols:
                    continue
                for nm, tm, pos, pid_raw in conn.execute(
                    f"SELECT name, team, position, person_id FROM {tbl}"
                ):
                    try:
                        pid = int(pid_raw or 0)
                    except (TypeError, ValueError):
                        continue
                    if pid <= 0:
                        continue
                    name = (nm or "").strip()
                    team = (tm or "").strip()
                    if not name or not team:
                        continue
                    key = (_norm_cmp(name), _norm_cmp(team))
                    slot = out.setdefault(
                        key,
                        {
                            "pids": set(),
                            "name": name,
                            "team": team,
                            "position": (pos or "").strip(),
                        },
                    )
                    slot["pids"].add(pid)
                    if not slot.get("position") and pos:
                        slot["position"] = str(pos).strip()
        finally:
            conn.close()
    return out


def _league_name_team_pids() -> dict[tuple[str, str], int]:
    """Активная league.db: (name, team) → person_id (min при дублях)."""
    out: dict[tuple[str, str], int] = {}
    lp = season_paths.get_league_db_path()
    if not lp or not os.path.isfile(lp):
        return out
    conn = sqlite3.connect(lp)
    try:
        for tbl in _TABLES:
            cols = {r[1] for r in conn.execute(f"PRAGMA table_info({tbl})").fetchall()}
            if "person_id" not in cols:
                continue
            for nm, tm, pid_raw in conn.execute(
                f"SELECT name, team, person_id FROM {tbl}"
            ):
                try:
                    pid = int(pid_raw or 0)
                except (TypeError, ValueError):
                    continue
                if pid <= 0:
                    continue
                key = (_norm_cmp(nm or ""), _norm_cmp(tm or ""))
                if key not in out or pid < out[key]:
                    out[key] = pid
    finally:
        conn.close()
    return out


def _archive_pid_by_full_name(
    seasons: tuple[int, ...] = (1, 2),
) -> dict[str, int]:
    """
    Точное полное имя → person_id из s1–s2.

    Не используем identity-токен («мария» / «альварез») — иначе однофамильцы схлопнутся.
    """
    best: dict[str, tuple[int, int]] = {}
    db_dir = os.path.join(season_paths.PROJECT_ROOT, "db")
    for sn in seasons:
        for fname in (season_paths.SEASON_LEAGUE_NAME, season_paths.SEASON_CL_NAME):
            path = os.path.join(db_dir, f"season_{sn}", fname)
            if not os.path.isfile(path):
                continue
            conn = sqlite3.connect(path)
            try:
                for tbl in _TABLES:
                    cols = {
                        r[1] for r in conn.execute(f"PRAGMA table_info({tbl})").fetchall()
                    }
                    if "person_id" not in cols:
                        continue
                    for nm, pid_raw, matches_raw in conn.execute(
                        f"SELECT name, person_id, matches FROM {tbl}"
                    ):
                        key = _norm_cmp(nm or "")
                        if not key:
                            continue
                        try:
                            pid = int(pid_raw or 0)
                        except (TypeError, ValueError):
                            continue
                        if pid <= 0:
                            continue
                        m = int(matches_raw or 0)
                        prev = best.get(key)
                        if prev is None or (m, -pid) > (prev[0], -prev[1]):
                            best[key] = (m, pid)
            finally:
                conn.close()
    return {k: pid for k, (_m, pid) in best.items()}


def build_name_team_canonical_map(
    *,
    archive_seasons: tuple[int, ...] = (1, 2),
) -> dict[tuple[str, str], int]:
    """
    Для групп (имя, клуб) с >1 person_id — канонический id.

    1) id из активной league для этого клуба (выровнять ЛЧ → лига);
    2) иначе min(pids).
    """
    groups = collect_name_team_pids()
    league_pref = _league_name_team_pids()

    canon: dict[tuple[str, str], int] = {}
    for key, slot in groups.items():
        pids = set(slot["pids"])
        if len(pids) <= 1:
            continue
        if key in league_pref:
            chosen = int(league_pref[key])
        else:
            chosen = min(pids)
        canon[key] = chosen
    return canon


def build_full_name_career_canonical(
    *,
    archive_seasons: tuple[int, ...] = (1, 2),
) -> dict[str, int]:
    """
    Полное имя → один person_id на всю карьеру (все клубы).

    Если в s1–s2 уже был id — возвращаем его (Ди Мария → 41).
    Пропуск: однофамильцы — если в активной лиге >1 клуба с этим именем
    без ``left_team`` (например несколько «Альварез»).
    """
    arch = _archive_pid_by_full_name(archive_seasons)
    by_name: dict[str, set[int]] = defaultdict(set)
    for path in iter_player_db_paths():
        conn = sqlite3.connect(path)
        try:
            for tbl in _TABLES:
                cols = {r[1] for r in conn.execute(f"PRAGMA table_info({tbl})").fetchall()}
                if "person_id" not in cols:
                    continue
                for nm, pid_raw in conn.execute(f"SELECT name, person_id FROM {tbl}"):
                    key = _norm_cmp(nm or "")
                    if not key:
                        continue
                    try:
                        pid = int(pid_raw or 0)
                    except (TypeError, ValueError):
                        continue
                    if pid <= 0:
                        continue
                    by_name[key].add(pid)
        finally:
            conn.close()

    # сколько «живых» клубов в активной лиге на это имя
    open_teams: dict[str, set[str]] = defaultdict(set)
    lp = season_paths.get_league_db_path()
    if lp and os.path.isfile(lp):
        conn = sqlite3.connect(lp)
        try:
            for tbl in _TABLES:
                cols = {r[1] for r in conn.execute(f"PRAGMA table_info({tbl})").fetchall()}
                if "person_id" not in cols:
                    continue
                left_sql = "left_team" if "left_team" in cols else "0"
                q = f"SELECT name, team, {left_sql} FROM {tbl}"
                for nm, tm, left in conn.execute(q):
                    if int(left or 0):
                        continue
                    key = _norm_cmp(nm or "")
                    team = _norm_cmp(tm or "")
                    if key and team:
                        open_teams[key].add(team)
        finally:
            conn.close()

    out: dict[str, int] = {}
    for key, pids in by_name.items():
        if len(pids) <= 1:
            continue
        if key not in arch:
            # без архивного канона не склеиваем — риск однофамильцев
            continue
        if len(open_teams.get(key) or ()) > 1:
            # сейчас в лиге несколько «живых» клубов с этим именем
            continue
        out[key] = int(arch[key])
    return out


def apply_name_team_person_ids(
    canonical: dict[tuple[str, str], int] | None = None,
) -> dict[str, Any]:
    """Проставить канон по (имя, клуб) во всех БД. Возвращает лог."""
    canonical = canonical if canonical is not None else build_name_team_canonical_map()
    log: dict[str, Any] = {
        "groups": len(canonical),
        "updated_rows": 0,
        "examples": [],
        "per_db": {},
    }
    for key, want in sorted(canonical.items(), key=lambda x: x[0][0]):
        if len(log["examples"]) < 25:
            log["examples"].append(
                {"name_team": list(key), "person_id": want}
            )

    for path in iter_player_db_paths():
        n_upd = 0
        conn = sqlite3.connect(path)
        try:
            for tbl in _TABLES:
                cols = {r[1] for r in conn.execute(f"PRAGMA table_info({tbl})").fetchall()}
                if "person_id" not in cols or "name" not in cols or "team" not in cols:
                    continue
                rows = list(
                    conn.execute(f"SELECT id, name, team, person_id FROM {tbl}")
                )
                for row_id, nm, tm, pid_raw in rows:
                    key = (_norm_cmp(nm or ""), _norm_cmp(tm or ""))
                    want = canonical.get(key)
                    if want is None:
                        continue
                    try:
                        cur = int(pid_raw or 0)
                    except (TypeError, ValueError):
                        cur = 0
                    if cur == want:
                        continue
                    conn.execute(
                        f"UPDATE {tbl} SET person_id = ? WHERE id = ?",
                        (want, row_id),
                    )
                    n_upd += 1
            conn.commit()
        finally:
            conn.close()
        if n_upd:
            log["per_db"][
                os.path.basename(os.path.dirname(path))
                + "/"
                + os.path.basename(path)
            ] = n_upd
            log["updated_rows"] += n_upd
    return log


def apply_full_name_career_ids(
    canonical: dict[str, int] | None = None,
) -> dict[str, Any]:
    """Все клубы одного полного имени → один person_id."""
    canonical = (
        canonical if canonical is not None else build_full_name_career_canonical()
    )
    log: dict[str, Any] = {
        "names": len(canonical),
        "updated_rows": 0,
        "examples": [],
        "per_db": {},
    }
    for key, want in sorted(canonical.items()):
        if len(log["examples"]) < 20:
            log["examples"].append({"name": key, "person_id": want})

    for path in iter_player_db_paths():
        n_upd = 0
        conn = sqlite3.connect(path)
        try:
            for tbl in _TABLES:
                cols = {r[1] for r in conn.execute(f"PRAGMA table_info({tbl})").fetchall()}
                if "person_id" not in cols or "name" not in cols:
                    continue
                for row_id, nm, pid_raw in conn.execute(
                    f"SELECT id, name, person_id FROM {tbl}"
                ):
                    key = _norm_cmp(nm or "")
                    want = canonical.get(key)
                    if want is None:
                        continue
                    try:
                        cur = int(pid_raw or 0)
                    except (TypeError, ValueError):
                        cur = 0
                    if cur == want:
                        continue
                    conn.execute(
                        f"UPDATE {tbl} SET person_id = ? WHERE id = ?",
                        (want, row_id),
                    )
                    n_upd += 1
            conn.commit()
        finally:
            conn.close()
        if n_upd:
            log["per_db"][
                os.path.basename(os.path.dirname(path))
                + "/"
                + os.path.basename(path)
            ] = n_upd
            log["updated_rows"] += n_upd
    return log


def merge_nicknames_after_unify() -> dict[str, int]:
    """Схлопнуть ники: если у строки сменился pid — перенести nick на канон."""
    from utils.player_nicknames import load_nicknames, save_nicknames

    # после unify: собрать актуальные pid по имени из БД и оставить nick на живых pid
    # проще: для каждого nick-ключа, если pid больше нигде нет — найти канон по имени из sibling
    data = load_nicknames()
    mp = data.get("by_person_id") or {}
    if not mp:
        return {"moved": 0, "removed_orphan": 0}

    # все живые pid → (name, team)
    live: dict[int, tuple[str, str]] = {}
    for path in (
        season_paths.get_league_db_path(),
        season_paths.get_cl_db_path(),
    ):
        if not path or not os.path.isfile(path):
            continue
        conn = sqlite3.connect(path)
        try:
            for tbl in _TABLES:
                cols = {r[1] for r in conn.execute(f"PRAGMA table_info({tbl})").fetchall()}
                if "person_id" not in cols:
                    continue
                for nm, tm, pid_raw in conn.execute(
                    f"SELECT name, team, person_id FROM {tbl}"
                ):
                    try:
                        pid = int(pid_raw or 0)
                    except (TypeError, ValueError):
                        continue
                    if pid > 0 and nm:
                        live[pid] = ((nm or "").strip(), (tm or "").strip())
        finally:
            conn.close()

    # name+team → current pids
    by_nt: dict[tuple[str, str], set[int]] = defaultdict(set)
    for pid, (nm, tm) in live.items():
        by_nt[(_norm_cmp(nm), _norm_cmp(tm))].add(pid)

    moved = 0
    removed = 0
    new_mp: dict[str, str] = {}
    # сначала переносим ники с мёртвых pid
    for pid_s, nick in list(mp.items()):
        nick_s = str(nick).strip()
        if not nick_s:
            continue
        try:
            pid = int(pid_s)
        except (TypeError, ValueError):
            continue
        if pid in live:
            new_mp[str(pid)] = nick_s.capitalize()
            continue
        # мёртвый pid — ищем живые того же игрока по… нет имени. Просто drop orphan.
        removed += 1

    # дубли ников на разные pid одного name+team — оставить на всех живых
    # reverse: nick → pids
    nick_to_meta: dict[str, list[int]] = defaultdict(list)
    for pid_s, nick in new_mp.items():
        nick_to_meta[nick.casefold()].append(int(pid_s))

    # для каждого name+team: если хоть у одного pid есть nick — проставить всем pid группы
    for (_nk, _tk), pids in by_nt.items():
        nicks = []
        for p in pids:
            n = new_mp.get(str(p))
            if n:
                nicks.append(n)
        if not nicks:
            continue
        # один ник на группу
        chosen = nicks[0].capitalize()
        for p in pids:
            if new_mp.get(str(p)) != chosen:
                new_mp[str(p)] = chosen
                moved += 1

    data["by_person_id"] = new_mp
    save_nicknames(data)
    return {"moved": moved, "removed_orphan": removed, "nick_keys": len(new_mp)}


def unify_split_person_ids(*, rebuild_common: bool = True) -> dict[str, Any]:
    # 1) ЛЧ → тот же id, что в лиге (по клубу)
    nt = build_name_team_canonical_map()
    applied_nt = apply_name_team_person_ids(nt)
    # 2) карьера по полному имени (Ди Мария Севилья/Тоттенхэм → 41 из s2)
    career = build_full_name_career_canonical()
    applied_career = apply_full_name_career_ids(career)
    nicks = merge_nicknames_after_unify()
    out: dict[str, Any] = {
        "name_team_fix": {
            f"{k[0]}|{k[1]}": v for k, v in sorted(nt.items())
        },
        "apply_name_team": applied_nt,
        "full_name_career": career,
        "apply_career": applied_career,
        "nicknames": nicks,
    }
    if rebuild_common:
        from utils.common_db import rebuild_common_database_for_disk_paths

        lp = season_paths.get_league_db_path()
        cp = season_paths.get_cl_db_path()
        ap = season_paths.get_common_db_path()
        if os.path.isfile(lp) and os.path.isfile(cp) and os.path.isfile(ap):
            rebuild_common_database_for_disk_paths(lp, cp, ap)
            out["active_common_rebuilt"] = True
    return out
