# -*- coding: utf-8 -*-
"""
Аренды: игрок в клубе до N-го «месяца» календаря (1–10), затем в свободные агенты.

Хранение: ``data/player_loans.json``. Срок окончания считается как у травм в
``player_discipline``: ``end_month = min(10, current_month + months)``.
"""
from __future__ import annotations

import json
import re
import threading
import os
from pathlib import Path
from typing import Any

_ROOT = Path(__file__).resolve().parent.parent
_LOANS_PATH = _ROOT / "data" / "player_loans.json"
_lock = threading.Lock()


def _norm(s: str) -> str:
    return (s or "").strip().lower()


def _load() -> dict[str, Any]:
    if not _LOANS_PATH.is_file():
        return {"version": 1, "loans": []}
    try:
        with open(_LOANS_PATH, encoding="utf-8") as f:
            raw = json.load(f)
    except Exception:
        return {"version": 1, "loans": []}
    if not isinstance(raw, dict):
        return {"version": 1, "loans": []}
    raw.setdefault("version", 1)
    raw.setdefault("loans", [])
    if not isinstance(raw["loans"], list):
        raw["loans"] = []
    return raw


def _save(data: dict[str, Any]) -> None:
    _LOANS_PATH.parent.mkdir(parents=True, exist_ok=True)
    tmp = str(_LOANS_PATH) + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    os.replace(tmp, str(_LOANS_PATH))


def _loan_key(name: str, team: str, position: str) -> tuple[str, str, str]:
    return _norm(name), _norm(team), _norm(position)


def _end_month_for_loan(current_month: int, nmonths: int) -> int:
    cur = max(1, min(10, int(current_month)))
    ret = cur + int(nmonths)
    if ret > 10:
        ret = 10
    return ret


def _valid_positions() -> set[str]:
    from utils.utils import defenders, forwards, goalkeepers, midfielders

    return set(forwards) | set(midfielders) | set(defenders) | set(goalkeepers)


_RE_MONTHS = re.compile(r"^(\d+)\s*[мm]\s*$", re.IGNORECASE)


def parse_loan_line(line: str) -> tuple[dict[str, Any] | None, str | None]:
    """
    «имя … позиция overall Nм» — позиция одно слово (ВРТ, ЦП, …), перед ней имя,
    затем overall, в конце срок (7м / 7m).
    """
    from utils.transfer_input import normalize_player_name_for_db, normalize_position

    raw = (line or "").strip()
    if not raw:
        return None, "Пустая строка"
    parts = raw.split()
    if len(parts) < 4:
        return None, "Формат: <code>имя позиция overall Nм</code> (напр. нубель врт 76 7м)"

    last = parts[-1]
    mm = _RE_MONTHS.match(last)
    if not mm:
        return None, "В конце срок аренды: число + м или m (напр. <code>7м</code>)"
    months = int(mm.group(1))
    if months < 1 or months > 24:
        return None, "Срок 1–24 (месяцев календаря; итог не выше 10-го)"

    rest = parts[:-1]
    if len(rest) < 3:
        return None, "Нужны имя, позиция, overall"

    ovr_s = rest[-1]
    if not ovr_s.isdigit():
        return None, "Перед сроком укажи overall числом (1–99)"
    ovr = int(ovr_s)
    if ovr < 1 or ovr > 99:
        return None, "Overall 1–99"

    pos_s = rest[-2]
    pos = normalize_position(pos_s)
    valid = _valid_positions()
    if pos not in valid:
        return None, f"Неизвестная позиция «{pos_s}» (ЦП, ВРТ, ФРВ, …)"

    name_raw = " ".join(rest[:-2]).strip()
    if not name_raw:
        return None, "Укажи имя"
    name = normalize_player_name_for_db(name_raw)

    return (
        {
            "name": name,
            "position": pos,
            "overall": ovr,
            "months": months,
        },
        None,
    )


def register_loan_for_team(
    team: str,
    line: str,
    *,
    schedule_day: int | None = None,
) -> tuple[str, bool]:
    """
    Добавить игрока в состав клуба (нац. БД + ЛЧ при пуле) и записать аренду.
    """
    from utils.player_discipline import get_calendar_month
    from utils.roster_manual import add_player_to_team_roster
    from utils.transfer_input import resolve_team_name
    from utils.utils import session_league

    parsed, err = parse_loan_line(line)
    if err:
        return err, False

    sleague = session_league
    team_r = resolve_team_name((team or "").strip(), sleague) or (team or "").strip()
    name = parsed["name"]
    pos = parsed["position"]
    ovr = parsed["overall"]
    months = parsed["months"]
    cur = get_calendar_month(schedule_day)
    end_m = _end_month_for_loan(cur, months)

    add_player_to_team_roster(
        team_r,
        name,
        pos,
        overall=ovr,
        nation=None,
        status="bench",
    )

    with _lock:
        st = _load()
        loans = st.setdefault("loans", [])
        k_new = _loan_key(name, team_r, pos)
        loans[:] = [x for x in loans if _loan_key(x.get("name", ""), x.get("team", ""), x.get("position", "")) != k_new]
        loans.append(
            {
                "name": name,
                "name_norm": _norm(name),
                "team": team_r,
                "team_norm": _norm(team_r),
                "position": pos,
                "end_month": end_m,
                "started_month": cur,
                "months_planned": months,
            }
        )
        _save(st)

    return (
        f"✓ Аренда: <b>{name}</b> {pos} {ovr} → <b>{team_r}</b> до <b>{end_m}</b>-го мес. "
        f"календаря (сейчас {cur}-й; по истечении срока — в СА).",
        True,
    )


def process_loan_expirations(schedule_day: int | None = None) -> list[str]:
    """
    Текущий месяц календаря ≥ end_month — снять игрока в СА и убрать запись аренды.
    Вызывать после матчей / при закрытии ввода статы (с тем же слотом, что и дисциплина).
    """
    from utils.player_discipline import get_calendar_month

    cur = get_calendar_month(schedule_day)
    logs: list[str] = []
    expired: list[dict[str, Any]] = []
    with _lock:
        st = _load()
        loans = st.setdefault("loans", [])
        kept: list[dict[str, Any]] = []
        for row in loans:
            try:
                end_m = int(row.get("end_month") or 99)
            except (TypeError, ValueError):
                kept.append(row)
                continue
            if cur < end_m:
                kept.append(row)
                continue
            nm = (row.get("name") or "").strip()
            tm = (row.get("team") or "").strip()
            pos = (row.get("position") or "").strip()
            if nm and tm and pos:
                expired.append(dict(row))
        st["loans"] = kept
        _save(st)
    if expired:
        from utils.roster_manual import remove_player_from_team_roster

        for row in expired:
            nm = (row.get("name") or "").strip()
            tm = (row.get("team") or "").strip()
            pos = (row.get("position") or "").strip()
            try:
                remove_player_from_team_roster(tm, nm, pos)
                logs.append(f"✓ Аренда окончена: {nm} ({pos}) — в СА, был клуб «{tm}»")
            except Exception as e:
                logs.append(f"✗ Аренда {nm} ({tm}): {e}")
    return logs
