# -*- coding: utf-8 -*-
"""
Состояние: тренер → три схемы (как в ``team_squad_schemas.FORMATION_SLOTS``) и одна active;
команда → текущий тренер. Схемы и тренер могут меняться в любой момент, тренер
может переходить в другую команду (тогда старая привязка снимается).

Данные: ``data/coach_squad_state.json`` (уже в репозитории, можно править вручную
или вызывать ``register_coach`` / ``assign_coach_to_team`` из кода/консоли).
"""
from __future__ import annotations

import json
import re
import threading
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Literal, Mapping

from team_squad_schemas import DEFAULT_FORMATION_KEY, TEAM_FORMATION_KEY

_ROOT = Path(__file__).resolve().parent
_PATH = _ROOT / "data" / "coach_squad_state.json"
_lock = threading.Lock()
_COACH_ID_RE = re.compile(r"^[a-z0-9_]{1,64}$", re.I)

StateLiteral = Literal["active", "inactive"]


@dataclass
class CoachFormation:
    key: str
    state: StateLiteral


@dataclass
class CoachRecord:
    coach_id: str
    name: str
    formations: list[CoachFormation]

    def to_json(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "formations": [asdict(f) for f in self.formations],
        }

    @staticmethod
    def from_json(coach_id: str, raw: Mapping[str, Any]) -> "CoachRecord":
        forms: list[CoachFormation] = []
        for f in raw.get("formations") or []:
            st = str(f.get("state", "inactive")).lower()
            if st in ("unactive", "inactive", ""):
                st = "inactive"
            elif st != "active":
                st = "inactive"
            forms.append(
                CoachFormation(
                    key=str(f.get("key", "")).strip(),
                    state=cast_state(st),
                )
            )
        return CoachRecord(
            coach_id=coach_id,
            name=str(raw.get("name", coach_id)).strip() or coach_id,
            formations=forms,
        )


def cast_state(s: str) -> StateLiteral:
    if s == "active":
        return "active"
    return "inactive"


def _load() -> dict[str, Any]:
    if not _PATH.exists():
        return {"version": 1, "coaches": {}, "team_coach": {}}
    with open(_PATH, encoding="utf-8") as f:
        return json.load(f)


def _save(data: dict[str, Any]) -> None:
    _PATH.parent.mkdir(parents=True, exist_ok=True)
    with open(_PATH, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


def _validate_coach_formations(formations: list[CoachFormation]) -> None:
    if len(formations) != 3:
        raise ValueError("У тренера должно быть ровно 3 схемы (formation).")
    active = [f for f in formations if f.state == "active"]
    if len(active) != 1:
        raise ValueError("Ровно одна схема должна быть active, две — inactive.")
    for f in formations:
        if not f.key:
            raise ValueError("Пустой ключ схемы (formation key).")


def get_coach_record(coach_id: str) -> CoachRecord | None:
    data = _load()
    raw = data.get("coaches", {}).get(coach_id)
    if not raw:
        return None
    return CoachRecord.from_json(coach_id, raw)


def list_coach_ids() -> list[str]:
    return sorted(_load().get("coaches", {}).keys())


def get_team_for_coach(coach_id: str) -> str | None:
    """Имя команды (как в БД), за которой закреплён тренер, иначе None."""
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
    """
    Ключ схемы из ``team_squad_schemas.FORMATION_SLOTS``:
    1) active-схема тренера команды (если настроено);
    2) иначе ``TEAM_FORMATION_KEY[team]``;
    3) иначе ``DEFAULT`` (433).
    """
    norm = (team_db or "").strip()
    if not norm:
        return DEFAULT_FORMATION_KEY
    c = get_coach_for_team(norm)
    if c:
        for f in c.formations:
            if f.state == "active" and f.key:
                return f.key
        for f in c.formations:
            if f.key:
                return f.key
    return TEAM_FORMATION_KEY.get(norm, DEFAULT_FORMATION_KEY)


def label_for_squad_caption(team_db: str) -> str:
    """Короткая подпись: ключ схемы + имя тренера, если есть."""
    key = resolve_formation_key_for_team((team_db or "").strip())
    c = get_coach_for_team((team_db or "").strip())
    if c:
        return f"{key} · {c.name}"
    return key


def register_coach(
    coach_id: str,
    display_name: str,
    formation_keys: tuple[str, str, str],
    active_index: int = 0,
) -> None:
    """
    Создать/заменить тренера с тремя схемами.
    active_index: 0..2 — какой из трёх ключей сделать active.
    """
    if not _COACH_ID_RE.match(coach_id):
        raise ValueError(
            "coach_id: латиница, цифры, подчёркивание, 1..64 символа (напр. guardiola)."
        )
    if active_index not in (0, 1, 2):
        raise ValueError("active_index должен быть 0, 1 или 2.")
    keys = [k.strip() for k in formation_keys]
    if not all(keys):
        raise ValueError("Все три ключа схемы должны быть непустыми.")
    forms = []
    for i, k in enumerate(keys):
        st: StateLiteral = "active" if i == active_index else "inactive"
        forms.append(CoachFormation(key=k, state=st))
    _validate_coach_formations(forms)
    with _lock:
        data = _load()
        coaches = data.setdefault("coaches", {})
        coaches[coach_id] = CoachRecord(
            coach_id=coach_id, name=display_name.strip() or coach_id, formations=forms
        ).to_json()
        data["version"] = int(data.get("version", 1))
        _save(data)


def set_coach_formations(
    coach_id: str,
    formation_keys: tuple[str, str, str],
    active_index: int = 0,
) -> None:
    """Поменять тройку схем; у существующего тренера сохраняется display name."""
    rec = get_coach_record(coach_id)
    if not rec:
        raise KeyError(f"Нет тренера {coach_id!r}. Сначала register_coach.")
    name = rec.name
    register_coach(coach_id, name, formation_keys, active_index=active_index)


def set_active_formation_index(coach_id: str, active_index: int) -> None:
    """Какая из трёх (0,1,2) схем становится active, остальные inactive."""
    if active_index not in (0, 1, 2):
        raise ValueError("active_index должен быть 0, 1 или 2.")
    rec = get_coach_record(coach_id)
    if not rec or len(rec.formations) != 3:
        raise KeyError(f"Нет тренера {coach_id!r} с тремя схемами.")
    forms: list[CoachFormation] = []
    for i, f in enumerate(rec.formations):
        st: StateLiteral = "active" if i == active_index else "inactive"
        forms.append(CoachFormation(key=f.key, state=st))
    _validate_coach_formations(forms)
    with _lock:
        data = _load()
        c = data.setdefault("coaches", {})[coach_id]
        c["formations"] = [asdict(x) for x in forms]
        _save(data)


def set_active_formation_key(coach_id: str, key: str) -> None:
    """Сделать active схему с данным ключом (должна совпадать с одной из трёх)."""
    key = key.strip()
    rec = get_coach_record(coach_id)
    if not rec or len(rec.formations) != 3:
        raise KeyError(f"Нет тренера {coach_id!r} с тремя схемами.")
    for i, f in enumerate(rec.formations):
        if f.key == key:
            set_active_formation_index(coach_id, i)
            return
    raise ValueError(f"Ключ {key!r} не найден среди схем тренера {coach_id!r}.")


def assign_coach_to_team(*, team_db: str, coach_id: str | None) -> None:
    """
    Закрепить тренера за командой; один тренер — не больше одной команды.
    coach_id None — снять тренера с команды.
    """
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
        _save(data)


def rename_coach(coach_id: str, new_display_name: str) -> None:
    with _lock:
        data = _load()
        c = data.get("coaches", {}).get(coach_id)
        if not c:
            raise KeyError(f"Нет тренера {coach_id!r}.")
        c["name"] = new_display_name.strip() or coach_id
        _save(data)
