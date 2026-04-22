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
) -> None:
    row = {
        "ts": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "user_id": user_id,
        "player": player.strip(),
        "from_team": from_team.strip(),
        "position": position.strip(),
        "to_team": to_team.strip(),
    }
    with _lock:
        data = _load()
        data.setdefault("transfers", []).append(row)
        data["version"] = int(data.get("version") or 1)
        _PATH.parent.mkdir(parents=True, exist_ok=True)
        with open(_PATH, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
