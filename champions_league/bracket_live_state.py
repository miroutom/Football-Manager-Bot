# -*- coding: utf-8 -*-
"""
Опциональные результаты для PNG-сетки ЛЧ (стыки и 1/8): загрузка из JSON рядом с модулем
или путь из переменной окружения CL_BRACKET_STATE_JSON.
"""
from __future__ import annotations

import json
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal

BracketStatePathEnv = "CL_BRACKET_STATE_JSON"


@dataclass
class R1TieLive:
    winner: str | None = None
    leg1: str | None = None
    leg2: str | None = None
    agg: str | None = None
    first_leg_only: bool = False
    note: str | None = None


@dataclass
class R2TieLive:
    winner: str | None = None
    leg1: str | None = None
    leg2: str | None = None
    agg: str | None = None
    note: str | None = None


def _coerce_str(x: Any) -> str | None:
    if x is None:
        return None
    s = str(x).strip()
    return s if s else None


def _parse_r1(obj: Any) -> R1TieLive | None:
    if not isinstance(obj, dict):
        return None
    return R1TieLive(
        winner=_coerce_str(obj.get("winner")),
        leg1=_coerce_str(obj.get("leg1")),
        leg2=_coerce_str(obj.get("leg2")),
        agg=_coerce_str(obj.get("agg")),
        first_leg_only=bool(obj.get("first_leg_only")),
        note=_coerce_str(obj.get("note")),
    )


def _parse_r2(obj: Any) -> R2TieLive | None:
    if not isinstance(obj, dict):
        return None
    return R2TieLive(
        winner=_coerce_str(obj.get("winner")),
        leg1=_coerce_str(obj.get("leg1")),
        leg2=_coerce_str(obj.get("leg2")),
        agg=_coerce_str(obj.get("agg")),
        note=_coerce_str(obj.get("note")),
    )


def _matches_fragment(fragment: str, team: str) -> bool:
    f = fragment.strip().lower()
    t = team.strip().lower()
    if not f or not t:
        return False
    if f == t:
        return True
    if len(f) >= 3:
        return f in t or t.startswith(f)
    # короткие ярлыки (Мю, Сити и т.д.)
    return t.startswith(f) or f in t


def winner_side_r1(winner_hint: str | None, home: str, away: str) -> Literal["home", "away"] | None:
    """Сопоставить подсказку из JSON с хозяином/гостем пары R1."""
    if not winner_hint:
        return None
    mh, ma = _matches_fragment(winner_hint, home), _matches_fragment(winner_hint, away)
    if mh and not ma:
        return "home"
    if ma and not mh:
        return "away"
    if mh and ma:
        return "home" if home.lower() == winner_hint.strip().lower() else "away"
    return None


def winner_side_r2(winner_hint: str | None, seed: str, opponent: str | None) -> Literal["seed", "opp"] | None:
    """Победитель стыка 1/8: посев или пришедший из R1 (opponent)."""
    if not winner_hint:
        return None
    if opponent is None:
        ms = _matches_fragment(winner_hint, seed)
        return "seed" if ms else None
    ms, mo = _matches_fragment(winner_hint, seed), _matches_fragment(winner_hint, opponent)
    if ms and not mo:
        return "seed"
    if mo and not ms:
        return "opp"
    if ms and mo:
        return "seed" if seed.lower() == winner_hint.strip().lower() else "opp"
    return None


def default_state_path() -> Path:
    return Path(__file__).resolve().parent / "cl_bracket_state.json"


def load_live_state(path: Path | str | None = None) -> tuple[list[R1TieLive | None], list[R2TieLive | None]] | None:
    """Вернуть два списка длины 8 или None, если файла нет / ошибка / пусто."""
    p: Path | None
    if path is not None:
        p = Path(path)
    else:
        env = os.environ.get(BracketStatePathEnv)
        p = Path(env) if env else default_state_path()
    if not p.is_file():
        return None
    try:
        raw = json.loads(p.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None

    r1_raw = raw.get("r1")
    r2_raw = raw.get("r2")
    r1_list = r1_raw if isinstance(r1_raw, list) else []
    r2_list = r2_raw if isinstance(r2_raw, list) else []

    def fill8(lst: list[Any], parser: Any) -> list[Any | None]:
        out: list[Any | None] = [None] * 8
        for i in range(min(8, len(lst))):
            item = lst[i]
            if item is None:
                continue
            out[i] = parser(item)
        return out

    r1 = fill8(r1_list, _parse_r1)
    r2 = fill8(r2_list, _parse_r2)
    if all(x is None for x in r1) and all(x is None for x in r2):
        return None
    return r1, r2
