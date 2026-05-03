"""Журнал трансферов из бота — data/transfers.json."""
from __future__ import annotations

import json
import threading
from datetime import datetime, timezone
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent
_PATH = _ROOT / "data" / "transfers.json"
_lock = threading.Lock()


def _load() -> dict:
    if not _PATH.exists():
        return {"version": 1, "transfers": []}
    with open(_PATH, encoding="utf-8") as f:
        return json.load(f)


def append_transfer(
    *,
    user_id: int | None,
    player: str,
    from_team: str,
    position: str,
    to_team: str,
    new_status: str | None = None,
    free_agent: bool = False,
    overall: int | None = None,
    nation: str | None = None,
) -> None:
    row = {
        "ts": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "user_id": user_id,
        "player": player.strip(),
        "from_team": from_team.strip(),
        "position": position.strip(),
        "to_team": to_team.strip(),
    }
    if new_status is not None:
        row["new_status"] = new_status.strip()
    if free_agent:
        row["free_agent"] = True
    if overall is not None:
        row["overall"] = int(overall)
    if nation is not None:
        ns = nation.strip()
        if ns:
            row["nation"] = ns
    with _lock:
        data = _load()
        data.setdefault("transfers", []).append(row)
        data["version"] = int(data.get("version") or 1)
        _PATH.parent.mkdir(parents=True, exist_ok=True)
        with open(_PATH, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)


_SHORTCUTS_PATH = _ROOT / "data" / "transfer_shortcuts.json"


def save_transfer_shortcut(
    user_id: int | None, from_team: str, to_team: str
) -> None:
    """Запоминает пару клубов для кнопки «тот же маршрут» в трансфере."""
    if user_id is None:
        return
    ft = (from_team or "").strip()
    tt = (to_team or "").strip()
    if len(ft) < 2 or len(tt) < 2:
        return
    with _lock:
        data: dict = {}
        if _SHORTCUTS_PATH.exists():
            with open(_SHORTCUTS_PATH, encoding="utf-8") as f:
                data = json.load(f)
        data.setdefault("version", 1)
        users = data.setdefault("users", {})
        users[str(int(user_id))] = {"from": ft, "to": tt}
        _SHORTCUTS_PATH.parent.mkdir(parents=True, exist_ok=True)
        with open(_SHORTCUTS_PATH, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)


def get_transfer_shortcut(user_id: int | None) -> dict[str, str] | None:
    if user_id is None or not _SHORTCUTS_PATH.exists():
        return None
    with _lock:
        try:
            with open(_SHORTCUTS_PATH, encoding="utf-8") as f:
                data = json.load(f)
        except (OSError, json.JSONDecodeError):
            return None
    row = (data.get("users") or {}).get(str(int(user_id)))
    if not isinstance(row, dict):
        return None
    ft = (row.get("from") or "").strip()
    tt = (row.get("to") or "").strip()
    if len(ft) < 2 or len(tt) < 2:
        return None
    return {"from": ft, "to": tt}
