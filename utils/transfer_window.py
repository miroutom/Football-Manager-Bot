# -*- coding: utf-8 -*-
"""
Трансферное окно: статус open/closed, квоты in/out по клубам.

Пока окно **открыто** — матчи блокируются, трансферы разрешены (в пределах квот).
Пока **закрыто** — наоборот.

Состояние: ``data/transfer_window.json``.
"""
from __future__ import annotations

import json
import threading
from pathlib import Path
from typing import Any

_ROOT = Path(__file__).resolve().parent.parent
_PATH = _ROOT / "data" / "transfer_window.json"
_lock = threading.Lock()

DEFAULT_MAX_IN = 5
DEFAULT_MAX_OUT = 5


def _norm_team(team: str) -> str:
    t = (team or "").strip()
    if t.casefold() == "цска":
        return "цска"
    return t.casefold()


def _default_state() -> dict[str, Any]:
    return {
        "version": 1,
        "status": "open",
        "max_in": DEFAULT_MAX_IN,
        "max_out": DEFAULT_MAX_OUT,
        "teams": {},
    }


def _load() -> dict[str, Any]:
    if not _PATH.is_file():
        return _default_state()
    with open(_PATH, encoding="utf-8") as f:
        data = json.load(f)
    data.setdefault("version", 1)
    data.setdefault("status", "open")
    data.setdefault("max_in", DEFAULT_MAX_IN)
    data.setdefault("max_out", DEFAULT_MAX_OUT)
    data.setdefault("teams", {})
    return data


def _save(data: dict[str, Any]) -> None:
    _PATH.parent.mkdir(parents=True, exist_ok=True)
    with open(_PATH, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


def is_window_open() -> bool:
    return (_load().get("status") or "closed").strip().lower() == "open"


def blocks_matches() -> bool:
    return is_window_open()


def blocks_transfers() -> bool:
    return not is_window_open()


def get_limits() -> tuple[int, int]:
    st = _load()
    return int(st.get("max_in") or DEFAULT_MAX_IN), int(st.get("max_out") or DEFAULT_MAX_OUT)


def _team_row(st: dict[str, Any], team: str) -> dict[str, Any]:
    key = _norm_team(team)
    teams = st.setdefault("teams", {})
    row = teams.get(key)
    if not isinstance(row, dict):
        row = {"team": team.strip(), "in": 0, "out": 0}
        teams[key] = row
    if not row.get("team"):
        row["team"] = team.strip()
    return row


def get_quota(team: str) -> dict[str, int | str]:
    with _lock:
        st = _load()
        row = _team_row(st, team)
        max_in, max_out = get_limits()
        return {
            "team": str(row.get("team") or team),
            "in": int(row.get("in") or 0),
            "out": int(row.get("out") or 0),
            "max_in": max_in,
            "max_out": max_out,
        }


def quota_line(team: str) -> str:
    q = get_quota(team)
    return f"in {q['in']}/{q['max_in']}  out {q['out']}/{q['max_out']}"


def can_transfer_in(team: str) -> tuple[bool, str | None]:
    if blocks_transfers():
        return False, "Трансферное окно закрыто. Открой: /transfer → «Закрыть/открыть окно»."
    q = get_quota(team)
    if int(q["in"]) >= int(q["max_in"]):
        return (
            False,
            f"Квота входа исчерпана у {q['team']}: in {q['in']}/{q['max_in']}.",
        )
    return True, None


def can_transfer_out(team: str) -> tuple[bool, str | None]:
    if blocks_transfers():
        return False, "Трансферное окно закрыто."
    q = get_quota(team)
    if int(q["out"]) >= int(q["max_out"]):
        return (
            False,
            f"Квота выхода исчерпана у {q['team']}: out {q['out']}/{q['max_out']}.",
        )
    return True, None


def check_transfer(
    from_team: str, to_team: str, *, free_agent: bool = False
) -> tuple[bool, str | None]:
    ok, err = can_transfer_in(to_team)
    if not ok:
        return ok, err
    if not free_agent:
        ok, err = can_transfer_out(from_team)
        if not ok:
            return ok, err
    return True, None


def record_transfer(
    from_team: str, to_team: str, *, free_agent: bool = False
) -> None:
    with _lock:
        st = _load()
        to_row = _team_row(st, to_team)
        to_row["in"] = int(to_row.get("in") or 0) + 1
        if not free_agent:
            from_row = _team_row(st, from_team)
            from_row["out"] = int(from_row.get("out") or 0) + 1
        _save(st)


def set_window_open(*, reset_quotas: bool = False) -> bool:
    with _lock:
        st = _load()
        st["status"] = "open"
        if reset_quotas:
            st["teams"] = {}
        _save(st)
    return True


def set_window_closed() -> bool:
    with _lock:
        st = _load()
        st["status"] = "closed"
        _save(st)
    return False


def toggle_window(*, reset_quotas_on_open: bool = False) -> bool:
    if is_window_open():
        set_window_closed()
        return False
    set_window_open(reset_quotas=reset_quotas_on_open)
    return True


def window_status_html() -> str:
    if is_window_open():
        return "🟢 <b>Трансферное окно открыто</b> — матчи недоступны, трансферы по квотам."
    return "🔴 <b>Трансферное окно закрыто</b> — можно играть матчи."


def match_block_message_html() -> str:
    return (
        f"{window_status_html()}\n\n"
        "Закрой окно в <b>/transfer</b> (кнопка «Закрыть окно»), "
        "когда закончите трансферы — тогда снова можно вводить матчи."
    )
