# -*- coding: utf-8 -*-
"""Revision/conflict helpers for shared transfer window state."""
from __future__ import annotations

import time
from typing import Any


def state_revision(state: dict[str, Any] | None) -> int:
    if not state:
        return 0
    try:
        return int(state.get("revision") or 0)
    except (TypeError, ValueError):
        return 0


def state_meta(state: dict[str, Any] | None) -> dict[str, Any]:
    if not state:
        return {"revision": 0, "updated_by": "", "updated_at": ""}
    return {
        "revision": state_revision(state),
        "updated_by": str(state.get("updated_by") or ""),
        "updated_at": str(state.get("updated_at") or ""),
    }


def has_save_conflict(current: dict[str, Any] | None, expected_revision: int | None) -> bool:
    if expected_revision is None:
        return False
    if current is None:
        return int(expected_revision) != 0
    return state_revision(current) != int(expected_revision)


def bump_state_meta(
    payload: dict[str, Any],
    *,
    revision: int,
    client_name: str = "",
    client_id: str = "",
) -> dict[str, Any]:
    out = dict(payload)
    out["revision"] = int(revision)
    out["updated_at"] = time.strftime("%Y-%m-%dT%H:%M:%S")
    out["updated_by"] = (client_name or "").strip() or "игрок"
    if client_id:
        out["last_client_id"] = str(client_id)
    return out
