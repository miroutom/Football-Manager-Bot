# -*- coding: utf-8 -*-
"""Общие правки игрока (рейтинг/позиция/имя) для clubs + nations в Transfer Window."""
from __future__ import annotations

import json
import threading
from pathlib import Path
from typing import Any

_lock = threading.Lock()


def profiles_path(data_dir: Path) -> Path:
    return data_dir / "player_profile_overrides.json"


def load_profiles(data_dir: Path) -> dict[str, dict[str, Any]]:
    path = profiles_path(data_dir)
    if not path.is_file():
        return {}
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    if not isinstance(raw, dict):
        return {}
    out: dict[str, dict[str, Any]] = {}
    for k, v in raw.items():
        if isinstance(v, dict):
            out[str(k)] = dict(v)
    return out


def save_profiles(data_dir: Path, profiles: dict[str, dict[str, Any]]) -> None:
    path = profiles_path(data_dir)
    path.parent.mkdir(parents=True, exist_ok=True)
    with _lock:
        path.write_text(
            json.dumps(profiles, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )


def merge_profile(
    profiles: dict[str, dict[str, Any]],
    person_id: int,
    *,
    name: str | None = None,
    position: str | None = None,
    overall: int | None = None,
    nation: str | None = None,
    nickname: str | None = None,
    nickname_set: bool = False,
) -> dict[str, dict[str, Any]]:
    pid = int(person_id)
    if pid <= 0:
        return profiles
    key = str(pid)
    cur = dict(profiles.get(key) or {})
    if name is not None and str(name).strip():
        cur["name"] = str(name).strip()
    if position is not None and str(position).strip():
        cur["position"] = str(position).strip().upper()
    if overall is not None:
        cur["overall"] = int(overall)
    if nation is not None:
        cur["nation"] = str(nation).strip()
    if nickname_set:
        cur["nickname"] = str(nickname or "").strip()
    profiles[key] = cur
    return profiles


def patch_player_dict(p: dict[str, Any], profiles: dict[str, dict[str, Any]]) -> dict[str, Any]:
    if not p or not isinstance(p, dict):
        return p
    pid = p.get("person_id")
    try:
        pid_i = int(pid) if pid is not None else 0
    except (TypeError, ValueError):
        pid_i = 0
    if pid_i <= 0:
        return p
    prof = profiles.get(str(pid_i))
    if not prof:
        return p
    out = dict(p)
    if prof.get("name"):
        out["name"] = prof["name"]
    if prof.get("position"):
        out["position"] = prof["position"]
    if prof.get("overall") is not None:
        out["overall"] = int(prof["overall"])
    if prof.get("nation"):
        out["nation"] = prof["nation"]
    if "nickname" in prof:
        out["nickname"] = prof.get("nickname") or ""
    return out
