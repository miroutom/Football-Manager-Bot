# -*- coding: utf-8 -*-
"""
**Тренер** (тактика на поле) → одна активная схема (id 1–10, см. ``formation_catalog``);
**команда** → текущий тренер в ``team_coach``. Смена — через JSON или API ниже.

**Менеджеры** Roman / Lika (кто ведёт клуб в карьере) задаются в ``config/leagues_config.MANAGER_TEAMS``,
не в этом файле — здесь только тренерские схемы.

JSON: ``active_formation_id`` (1–10). Поле ``formation_ids`` в старых файлах игнорируется.
Старый формат с ``formations`` [{key, state}] читается, если key вида ``fid_6`` или ``"6"``.
"""
from __future__ import annotations

import json
import re
import threading
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping

from formation_catalog import (
    label_for_formation_id,
    slot_key_for_formation_id,
    validate_formation_id,
)
from team_squad_schemas import DEFAULT_FORMATION_KEY, TEAM_FORMATION_KEY

_ROOT = Path(__file__).resolve().parent
_PATH = _ROOT / "data" / "coach_squad_state.json"
_lock = threading.Lock()
_COACH_ID_RE = re.compile(r"^[a-z0-9_]{1,64}$", re.I)


@dataclass
class CoachRecord:
    coach_id: str
    name: str
    active_formation_id: int

    def to_json(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "active_formation_id": self.active_formation_id,
        }

    @staticmethod
    def from_json(coach_id: str, raw: Mapping[str, Any]) -> CoachRecord:
        name = str(raw.get("name", coach_id)).strip() or coach_id
        if "active_formation_id" in raw:
            aid = int(raw["active_formation_id"])
            validate_formation_id(aid)
            return CoachRecord(coach_id, name, aid)
        return CoachRecord._from_legacy_formations(coach_id, name, raw)

    @staticmethod
    def _from_legacy_formations(
        coach_id: str, name: str, raw: Mapping[str, Any]
    ) -> CoachRecord:
        forms_raw = raw.get("formations") or []
        if not forms_raw:
            raise ValueError(
                f"Тренер {coach_id}: нужен active_formation_id или legacy formations."
            )
        active_fid: int | None = None
        for f in forms_raw:
            k = str(f.get("key", "")).strip()
            if k.lower().startswith("fid_"):
                fid = int(k.split("_", 1)[1])
            else:
                fid = int(k)
            validate_formation_id(fid)
            st = str(f.get("state", "inactive")).lower()
            if st == "active":
                active_fid = fid
        if active_fid is None:
            k = str(forms_raw[0].get("key", "")).strip()
            if k.lower().startswith("fid_"):
                active_fid = int(k.split("_", 1)[1])
            else:
                active_fid = int(k)
            validate_formation_id(active_fid)
        return CoachRecord(coach_id, name, active_fid)


def _load() -> dict[str, Any]:
    if not _PATH.exists():
        return {"version": 3, "coaches": {}, "team_coach": {}}
    with open(_PATH, encoding="utf-8") as f:
        return json.load(f)


def _save(data: dict[str, Any]) -> None:
    _PATH.parent.mkdir(parents=True, exist_ok=True)
    with open(_PATH, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


def get_coach_record(coach_id: str) -> CoachRecord | None:
    data = _load()
    raw = data.get("coaches", {}).get(coach_id)
    if not raw:
        return None
    return CoachRecord.from_json(coach_id, raw)


def list_coach_ids() -> list[str]:
    return sorted(_load().get("coaches", {}).keys())


def list_coach_display_names() -> list[str]:
    """Уникальные отображаемые имена тренеров (для UI сборных ЧМ)."""
    names = {
        str(c.get("name", "")).strip()
        for c in _load().get("coaches", {}).values()
        if str(c.get("name", "")).strip()
    }
    return sorted(names, key=str.casefold)


def get_team_for_coach(coach_id: str) -> str | None:
    for team, cid in _load().get("team_coach", {}).items():
        if cid == coach_id:
            return team
    return None


def get_coach_id_for_team(team_db: str) -> str | None:
    return _load().get("team_coach", {}).get((team_db or "").strip())


def get_coach_for_team(team_db: str) -> CoachRecord | None:
    cid = get_coach_id_for_team(team_db)
    if not cid:
        return None
    return get_coach_record(cid)


def resolve_formation_key_for_team(team_db: str) -> str:
    norm = (team_db or "").strip()
    if not norm:
        return DEFAULT_FORMATION_KEY
    c = get_coach_for_team(norm)
    if c:
        return slot_key_for_formation_id(c.active_formation_id)
    return TEAM_FORMATION_KEY.get(norm, DEFAULT_FORMATION_KEY)


def label_for_squad_caption(team_db: str) -> str:
    """Подпись: название активной схемы по id + тренер."""
    norm = (team_db or "").strip()
    c = get_coach_for_team(norm)
    if c:
        lab = label_for_formation_id(c.active_formation_id)
        return f"{lab} · {c.name}"
    key = TEAM_FORMATION_KEY.get(norm, DEFAULT_FORMATION_KEY)
    return key


def register_coach(
    coach_id: str,
    display_name: str,
    active_formation_id: int,
) -> None:
    if not _COACH_ID_RE.match(coach_id):
        raise ValueError(
            "coach_id: латиница, цифры, подчёркивание, 1..64 символа (напр. pep)."
        )
    validate_formation_id(active_formation_id)
    with _lock:
        data = _load()
        coaches = data.setdefault("coaches", {})
        coaches[coach_id] = CoachRecord(
            coach_id,
            display_name.strip() or coach_id,
            active_formation_id,
        ).to_json()
        data["version"] = 3
        _save(data)


def set_coach_formations(
    coach_id: str,
    formation_ids: tuple[int, ...] | list[int],
    active_formation_id: int,
) -> None:
    """Совместимость: ``formation_ids`` игнорируется, меняется только active."""
    rec = get_coach_record(coach_id)
    if not rec:
        raise KeyError(f"Нет тренера {coach_id!r}. Сначала register_coach.")
    register_coach(coach_id, rec.name, active_formation_id)


def set_active_formation_index(coach_id: str, active_index: int) -> None:
    """Устарело: используйте ``set_active_formation_id`` с числовым id схемы."""
    raise ValueError(
        "set_active_formation_index устарел: задайте схему через set_active_formation_id."
    )


def set_active_formation_id(coach_id: str, tactical_id: int) -> None:
    """Сделать active любую схему 1–10."""
    validate_formation_id(tactical_id)
    rec = get_coach_record(coach_id)
    if not rec:
        raise KeyError(f"Нет тренера {coach_id!r}.")
    with _lock:
        data = _load()
        c = data.setdefault("coaches", {})[coach_id]
        c["name"] = rec.name
        c["active_formation_id"] = tactical_id
        c.pop("formation_ids", None)
        data["version"] = 3
        _save(data)


def set_active_formation_id_any(coach_id: str, tactical_id: int) -> None:
    """Алиас для ``set_active_formation_id`` (любая из 10 схем)."""
    set_active_formation_id(coach_id, tactical_id)


def assign_coach_to_team(*, team_db: str, coach_id: str | None) -> None:
    team = (team_db or "").strip()
    if not team:
        raise ValueError("Пустое имя команды.")
    with _lock:
        data = _load()
        tc = data.setdefault("team_coach", {})
        if coach_id is None:
            if team in tc:
                del tc[team]
            _save(data)
            return
        if not get_coach_record(coach_id):
            raise KeyError(f"Нет тренера {coach_id!r} в данных.")
        for t, cid in list(tc.items()):
            if cid == coach_id and t != team:
                del tc[t]
        tc[team] = coach_id
        data["version"] = 3
        _save(data)


def rename_coach(coach_id: str, new_display_name: str) -> None:
    with _lock:
        data = _load()
        c = data.get("coaches", {}).get(coach_id)
        if not c:
            raise KeyError(f"Нет тренера {coach_id!r}.")
        c["name"] = new_display_name.strip() or coach_id
        _save(data)
