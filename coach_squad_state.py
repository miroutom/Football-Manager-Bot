# -*- coding: utf-8 -*-
"""
Тренер → три **числовых** id схем (1–10, см. ``formation_catalog``), один active;
команда → текущий тренер. Смена схем / тренера — через JSON или API ниже.

JSON v2: ``formation_ids`` (ровно 3 числа), ``active_formation_id`` (одно из трёх).
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
    formation_ids: tuple[int, int, int]
    active_formation_id: int

    def to_json(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "formation_ids": list(self.formation_ids),
            "active_formation_id": self.active_formation_id,
        }

    @staticmethod
    def from_json(coach_id: str, raw: Mapping[str, Any]) -> CoachRecord:
        name = str(raw.get("name", coach_id)).strip() or coach_id
        if "formation_ids" in raw and "active_formation_id" in raw:
            ids = tuple(int(x) for x in raw["formation_ids"])
            aid = int(raw["active_formation_id"])
            CoachRecord._validate_triplet(ids, aid)
            return CoachRecord(coach_id, name, ids, aid)
        return CoachRecord._from_legacy_formations(coach_id, name, raw)

    @staticmethod
    def _from_legacy_formations(
        coach_id: str, name: str, raw: Mapping[str, Any]
    ) -> CoachRecord:
        forms_raw = raw.get("formations") or []
        if len(forms_raw) != 3:
            raise ValueError(
                f"Тренер {coach_id}: нужны formation_ids/active_formation_id или 3 legacy formations."
            )
        ids_list: list[int] = []
        active_fid: int | None = None
        for f in forms_raw:
            k = str(f.get("key", "")).strip()
            if k.lower().startswith("fid_"):
                fid = int(k.split("_", 1)[1])
            else:
                fid = int(k)
            validate_formation_id(fid)
            ids_list.append(fid)
            st = str(f.get("state", "inactive")).lower()
            if st == "active":
                active_fid = fid
        ids = tuple(ids_list)
        if active_fid is None:
            active_fid = ids[0]
        CoachRecord._validate_triplet(ids, active_fid)
        return CoachRecord(coach_id, name, ids, active_fid)

    @staticmethod
    def _validate_triplet(
        formation_ids: tuple[int, int, int], active_formation_id: int
    ) -> None:
        if len(formation_ids) != 3:
            raise ValueError("Должно быть ровно 3 id схем.")
        for fid in formation_ids:
            validate_formation_id(fid)
        validate_formation_id(active_formation_id)
        if active_formation_id not in formation_ids:
            raise ValueError(
                f"active_formation_id={active_formation_id} не входит в {formation_ids!r}."
            )


def _load() -> dict[str, Any]:
    if not _PATH.exists():
        return {"version": 2, "coaches": {}, "team_coach": {}}
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
    formation_ids: tuple[int, int, int],
    active_formation_id: int,
) -> None:
    if not _COACH_ID_RE.match(coach_id):
        raise ValueError(
            "coach_id: латиница, цифры, подчёркивание, 1..64 символа (напр. pep)."
        )
    CoachRecord._validate_triplet(formation_ids, active_formation_id)
    with _lock:
        data = _load()
        coaches = data.setdefault("coaches", {})
        coaches[coach_id] = CoachRecord(
            coach_id=coach_id,
            name=display_name.strip() or coach_id,
            formation_ids=formation_ids,
            active_formation_id=active_formation_id,
        ).to_json()
        data["version"] = 2
        _save(data)


def set_coach_formations(
    coach_id: str,
    formation_ids: tuple[int, int, int],
    active_formation_id: int,
) -> None:
    rec = get_coach_record(coach_id)
    if not rec:
        raise KeyError(f"Нет тренера {coach_id!r}. Сначала register_coach.")
    register_coach(coach_id, rec.name, formation_ids, active_formation_id)


def set_active_formation_index(coach_id: str, active_index: int) -> None:
    """Сделать active схему с индексом 0, 1 или 2 в списке formation_ids."""
    if active_index not in (0, 1, 2):
        raise ValueError("active_index должен быть 0, 1 или 2.")
    rec = get_coach_record(coach_id)
    if not rec:
        raise KeyError(f"Нет тренера {coach_id!r}.")
    new_active = rec.formation_ids[active_index]
    set_active_formation_id(coach_id, new_active)


def set_active_formation_id(coach_id: str, tactical_id: int) -> None:
    """Сделать active одну из трёх схем по числовому id (должен быть в тройке)."""
    validate_formation_id(tactical_id)
    rec = get_coach_record(coach_id)
    if not rec:
        raise KeyError(f"Нет тренера {coach_id!r}.")
    if tactical_id not in rec.formation_ids:
        raise ValueError(
            f"id {tactical_id} не из набора тренера {rec.formation_ids!r}."
        )
    with _lock:
        data = _load()
        c = data.setdefault("coaches", {})[coach_id]
        c["active_formation_id"] = tactical_id
        data["version"] = 2
        _save(data)


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
        data["version"] = 2
        _save(data)


def rename_coach(coach_id: str, new_display_name: str) -> None:
    with _lock:
        data = _load()
        c = data.get("coaches", {}).get(coach_id)
        if not c:
            raise KeyError(f"Нет тренера {coach_id!r}.")
        c["name"] = new_display_name.strip() or coach_id
        _save(data)
