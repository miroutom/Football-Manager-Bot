# -*- coding: utf-8 -*-
"""
Травмы и дисквалификации: JSON (активные баны, накопление жк к 4) + колонки yellow_cards / red_cards в БД.

Правила:
- 4 жк = 1 матч дискв. (накопление в JSON, жк в БД копятся за сезон)
- 2жк = КК = 1 матч +1 red в БД
- прямая КК = 3 матча +1 red
- травма: «имя Nм» — недоступен до месяца (календарь v3), колонка в БД не ведётся
"""
from __future__ import annotations

import json
import re
import threading
from pathlib import Path
from typing import Any

_ROOT = Path(__file__).resolve().parent.parent
_STATE_PATH = _ROOT / "data" / "player_discipline.json"
_CAL_PATH = _ROOT / "data" / "calendar_month.txt"
_lock = threading.Lock()

_YEL4 = 4
_RE_2Y = re.compile(r"^(.+?)\s+2\s*жк\s*$", re.IGNORECASE | re.UNICODE)
_RE_Y = re.compile(r"^(.+?)\s+жк\s*$", re.IGNORECASE | re.UNICODE)
_RE_R = re.compile(r"^(.+?)\s+кк\s*$", re.IGNORECASE | re.UNICODE)
_RE_INJ = re.compile(r"^(.+?)\s+(\d+)\s*м\s*$", re.IGNORECASE | re.UNICODE)


def _norm(s: str) -> str:
    return (s or "").strip().lower()


def _load() -> dict[str, Any]:
    if not _STATE_PATH.is_file():
        return {"version": 1, "suspensions": [], "yellow_cycle": [], "injuries": []}
    with open(_STATE_PATH, encoding="utf-8") as f:
        return json.load(f)


def _save(data: dict[str, Any]) -> None:
    _STATE_PATH.parent.mkdir(parents=True, exist_ok=True)
    with open(_STATE_PATH, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


def get_calendar_month(schedule_day: int | None) -> int:
    """
    Текущий «месяц» календаря: из слота матча (1–10) или data/calendar_month.txt, иначе 1.
    """
    if schedule_day is not None and 1 <= int(schedule_day) <= 10:
        return int(schedule_day)
    if _CAL_PATH.is_file():
        try:
            t = _CAL_PATH.read_text(encoding="utf-8").strip().split()
            if t:
                m = int(t[0])
                if 1 <= m <= 10:
                    return m
        except (OSError, ValueError):
            pass
    return 1


def _susp_key(name: str, team: str, league_code: str, scope: str) -> str:
    return f"{_norm(name)}|{_norm(team)}|{league_code}|{scope}"


def _find_injury(st: dict, name: str, team: str) -> dict | None:
    nn, tn = _norm(name), _norm(team)
    for row in st.get("injuries", []):
        if row.get("name_norm") == nn and row.get("team_norm") == tn:
            return row
    return None


def _find_susp(st: dict, name: str, team: str, league_code: str, scope: str) -> dict | None:
    k = _susp_key(name, team, league_code, scope)
    for row in st.get("suspensions", []):
        if row.get("key") == k:
            return row
    return None


def _find_yellow_cycle(st: dict, name: str, team: str, league_code: str, scope: str) -> dict | None:
    k = _susp_key(name, team, league_code, scope)
    for row in st.get("yellow_cycle", []):
        if row.get("key") == k:
            return row
    return None


def check_player_eligible(
    name: str,
    team: str,
    *,
    league_code: str,
    tournament: str,
    schedule_month: int,
) -> tuple[bool, str | None]:
    """
    Можно ли вписать матчевую стату (голы и т.д.). Возвращает (ok, сообщение при запрете).
    """
    scope = "cl" if tournament == "cl" else "league"
    lc = "cl" if scope == "cl" else league_code
    with _lock:
        st = _load()
    month = max(1, min(10, int(schedule_month)))

    inj = _find_injury(st, name, team)
    if inj:
        ret = int(inj.get("return_month") or 99)
        if month < ret:
            left = ret - month
            return (
                False,
                f"🚫 {name} — выбыл на {left} мес. (травма; выход с {ret} месяца)",
            )

    row = _find_susp(st, name, team, lc, scope)
    if row and int(row.get("matches_left") or 0) > 0:
        m = int(row["matches_left"])
        w = "матч" if m == 1 else "матча" if 2 <= m <= 4 else "матчей"
        return (False, f"🚫 {name} — {m} {w} дисквалификации (турнир: {lc})")

    return (True, None)


def register_match_played_for_discipline(
    home: str,
    away: str,
    league_code: str,
    tournament: str,
) -> None:
    """После ввода статистики по матчу: −1 матч дискв. у игроков команд home/away в этом турнире."""
    scope = "cl" if tournament == "cl" else "league"
    lc = "cl" if scope == "cl" else league_code
    th, ta = _norm(home), _norm(away)
    with _lock:
        st = _load()
        changed = False
        for row in st.get("suspensions", []):
            if row.get("league_code") != lc or row.get("scope") != scope:
                continue
            rt = row.get("team_norm")
            if rt not in (th, ta):
                continue
            left = int(row.get("matches_left") or 0)
            if left > 0:
                row["matches_left"] = left - 1
                changed = True
        if changed:
            _save(st)


def _upsert_susp(
    st: dict, name: str, team: str, league_code: str, scope: str, add: int
) -> None:
    k = _susp_key(name, team, league_code, scope)
    row = _find_susp(st, name, team, league_code, scope)
    if row is None:
        st.setdefault("suspensions", []).append(
            {
                "key": k,
                "name": name.strip().title(),
                "name_norm": _norm(name),
                "team": team.strip().title(),
                "team_norm": _norm(team),
                "league_code": league_code,
                "scope": scope,
                "matches_left": add,
            }
        )
    else:
        row["matches_left"] = int(row.get("matches_left") or 0) + add


def _inc_yellow_cycle(
    st: dict, name: str, team: str, league_code: str, scope: str
) -> str | None:
    """
    +1 к циклу жк. При достижении 4 — бан 1 матч, цикл 0. Возвращает сообщение при бане.
    """
    k = _susp_key(name, team, league_code, scope)
    ylist = st.setdefault("yellow_cycle", [])
    row = _find_yellow_cycle(st, name, team, league_code, scope)
    if row is None:
        row = {
            "key": k,
            "name": name.strip().title(),
            "name_norm": _norm(name),
            "team": team.strip().title(),
            "team_norm": _norm(team),
            "league_code": league_code,
            "scope": scope,
            "count": 0,
        }
        ylist.append(row)
    c = int(row.get("count") or 0) + 1
    if c >= _YEL4:
        _upsert_susp(st, name, team, league_code, scope, 1)
        row["count"] = 0
        return (
            f"⚠ 4-я жёлтая: {name} — 1 матч дисквалификации (и отсечка жк сброшена)."
        )
    row["count"] = c
    return f"Накопительно жк: {c}/{_YEL4} (к 4 — 1 матч дискв.)."


def _bump_db_cards(
    session, player: Any, *, add_yellow: int = 0, add_red: int = 0
) -> None:
    y = int(getattr(player, "yellow_cards", 0) or 0) + add_yellow
    r = int(getattr(player, "red_cards", 0) or 0) + add_red
    if hasattr(player, "yellow_cards"):
        player.yellow_cards = y
    if hasattr(player, "red_cards"):
        player.red_cards = r


def try_apply_discipline_line(
    line: str,
    *,
    current_team: str,
    tournament: str,
    league_code: str,
    schedule_month: int,
) -> tuple[str | None, bool]:
    """
    Разбор строки дисциплины/травмы. (сообщение, обработано_ли).
    Если обработано — обновлены JSON/БД и common.
    """
    raw = (line or "").strip()
    if not raw:
        return (None, False)
    # порядок: 2жк, жк, Nм, кк
    m2 = _RE_2Y.match(raw)
    if m2:
        name = m2.group(1).strip()
        return _apply_red_card(
            name,
            current_team,
            tournament,
            league_code,
            schedule_month,
            matches=1,
            add_yellow=0,
            add_red=1,
            kind_label="2-я жёлтая (кк)",
        )
    m3 = _RE_INJ.match(raw)
    if m3:
        name, nm = m3.group(1).strip(), int(m3.group(2))
        if nm < 1 or nm > 10:
            return ("Некорректно: число месяцев 1–10.", True)
        return _apply_injury(
            name, current_team, tournament, schedule_month, nm, find_player_by_name, get_session
        )
    if _RE_Y.match(raw):
        my = _RE_Y.match(raw)
        name = my.group(1).strip()
        return _apply_yellow(
            name,
            current_team,
            tournament,
            league_code,
        )
    if _RE_R.match(raw) and not m2:
        mr = _RE_R.match(raw)
        name = mr.group(1).strip()
        return _apply_red_card(
            name,
            current_team,
            tournament,
            league_code,
            schedule_month,
            matches=3,
            add_yellow=0,
            add_red=1,
            kind_label="прямая кк",
        )
    return (None, False)


def _apply_yellow(
    name: str,
    current_team: str,
    tournament: str,
    league_code: str,
) -> tuple[str | None, bool]:
    from player_stats import find_player_by_name, get_session
    from utils.common_db import rebuild_common_database

    t = "cl" if tournament == "cl" or (league_code or "") == "cl" else "league"
    sess = get_session(t)
    team = current_team.strip().title()
    nmt = name.title()
    player, _ = find_player_by_name(sess, nmt, team)
    if not player:
        return (f"✗ Не найден в БД: {nmt} ({team})", True)
    scope = "cl" if t == "cl" else "league"
    lc = "cl" if scope == "cl" else league_code
    with _lock:
        st = _load()
        msg_c = _inc_yellow_cycle(st, player.name, team, lc, scope)
        _bump_db_cards(sess, player, add_yellow=1)
        sess.commit()
        _save(st)
    try:
        rebuild_common_database()
    except Exception:
        pass
    return (f"✓ Жк: {player.name}. {msg_c} В БД жк+1.", True)


def _apply_red_card(
    name: str,
    current_team: str,
    tournament: str,
    league_code: str,
    schedule_month: int,
    *,
    matches: int,
    add_yellow: int,
    add_red: int,
    kind_label: str,
) -> tuple[str | None, bool]:
    from player_stats import find_player_by_name, get_session
    from utils.common_db import rebuild_common_database

    t = "cl" if tournament == "cl" or league_code == "cl" else "league"
    sess = get_session(t)
    team = current_team.strip().title()
    nmt = name.title()
    player, _ = find_player_by_name(sess, nmt, team)
    if not player:
        return (f"✗ Не найден в БД: {nmt} ({team})", True)
    scope = "cl" if t == "cl" else "league"
    lc = "cl" if scope == "cl" else league_code
    with _lock:
        st = _load()
        _upsert_susp(st, player.name, team, lc, scope, matches)
        _bump_db_cards(sess, player, add_yellow=add_yellow, add_red=add_red)
        sess.commit()
        _save(st)
    try:
        rebuild_common_database()
    except Exception:
        pass
    return (
        f"✓ {kind_label}: {player.name} — +{matches} к дискв., кк в БД +1.",
        True,
    )


def _apply_injury(
    name: str,
    current_team: str,
    tournament: str,
    month: int,
    nmonths: int,
    find_pl,
    get_sess,
) -> tuple[str | None, bool]:
    t = "cl" if tournament == "cl" else "league"
    sess = get_sess(t)
    team = current_team.strip().title()
    nmt = name.title()
    player, _ = find_pl(sess, nmt, team)
    if not player:
        return (f"✗ Не найден: {nmt} ({team})", True)
    cur = max(1, min(10, int(month)))
    ret = cur + int(nmonths)
    if ret > 10:
        ret = 10
    with _lock:
        st = _load()
        inj = _find_injury(st, player.name, team)
        if inj is None:
            st.setdefault("injuries", []).append(
                {
                    "name": player.name,
                    "name_norm": _norm(player.name),
                    "team": team,
                    "team_norm": _norm(team),
                    "return_month": ret,
                }
            )
        else:
            inj["return_month"] = ret
        _save(st)
    return (
        f"✓ Травма: {player.name} — недоступен до {ret} месяца (сейчас {cur}, срок {nmonths} мес).",
        True,
    )


def clear_discipline_state() -> None:
    """Сброс JSON (например при новом сезоне)."""
    with _lock:
        if _STATE_PATH.is_file():
            _STATE_PATH.unlink()


def line_looks_discipline(s: str) -> bool:
    t = (s or "").strip().lower()
    if re.search(r"\d+\s*м\s*$", t):
        return True
    if t.endswith("2жк"):
        return True
    if t.endswith("жк") or t.endswith("кк"):
        return True
    return False
