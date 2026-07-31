# -*- coding: utf-8 -*-
"""
Брендинг ЧМ: страна-хозяйка + стиль логотипа на сезон.

Хранится в ``data/wc_branding.json``::

    {
      "version": 1,
      "by_season": {
        "4": {
          "host": "Япония",
          "style": "ribbon",
          "seed": 40127,
          "display_year": 2022
        }
      }
    }
"""
from __future__ import annotations

import json
import os
import random
from typing import Any

from utils import season_paths
from utils.world_cup import is_world_cup_season, load_wc_config, nations_by_confederation
from utils.world_cup_format import flatten_nations

_PATH = os.path.join(season_paths.PROJECT_ROOT, "data", "wc_branding.json")

# Стили генератора логотипа (см. bot/wc_logo.py)
LOGO_STYLES: tuple[str, ...] = (
    "big_year",
    "horizontal",
    "ribbon",
    "faces",
    "swoosh",
    "burst",
    "circle",
    "stack",
)


def branding_path() -> str:
    return _PATH


def display_year_for_season(season: int) -> int:
    """Календарный год «как у FIFA»: сезон 4 → 2022, 8 → 2026, 12 → 2030…"""
    n = int(season)
    return 2022 + ((max(n, 4) - 4) // 4) * 4


def load_branding() -> dict[str, Any]:
    if not os.path.isfile(_PATH):
        return {"version": 1, "by_season": {}}
    try:
        with open(_PATH, encoding="utf-8") as f:
            raw = json.load(f)
    except (OSError, json.JSONDecodeError):
        return {"version": 1, "by_season": {}}
    if not isinstance(raw, dict):
        return {"version": 1, "by_season": {}}
    raw.setdefault("version", 1)
    raw.setdefault("by_season", {})
    if not isinstance(raw["by_season"], dict):
        raw["by_season"] = {}
    return raw


def save_branding(data: dict[str, Any]) -> None:
    os.makedirs(os.path.dirname(_PATH), exist_ok=True)
    tmp = _PATH + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
        f.write("\n")
    os.replace(tmp, _PATH)


def _host_pool() -> list[str]:
    by = nations_by_confederation()
    if by:
        names = flatten_nations(by)
        if names:
            return names
    return [str(n).strip() for n in (load_wc_config().get("nations") or []) if str(n).strip()]


def get_branding(season: int | None = None) -> dict[str, Any] | None:
    n = int(season if season is not None else season_paths.get_active_season())
    rec = (load_branding().get("by_season") or {}).get(str(n))
    return dict(rec) if isinstance(rec, dict) else None


def ensure_branding(
    season: int | None = None,
    *,
    force: bool = False,
    host: str | None = None,
) -> dict[str, Any]:
    """
    Получить или создать брендинг сезона.
    ``force=True`` — новый рандомный хост (или явный ``host``) и стиль.
    """
    n = int(season if season is not None else season_paths.get_active_season())
    data = load_branding()
    by = data.setdefault("by_season", {})
    key = str(n)
    if not force and isinstance(by.get(key), dict) and by[key].get("host"):
        return dict(by[key])

    pool = _host_pool()
    if not pool:
        raise RuntimeError("Нет списка сборных для выбора хоста ЧМ")

    rng = random.Random(n * 10007 + 26)
    if force:
        rng = random.Random(os.urandom(8))

    want_host = (host or "").strip()
    if want_host:
        # каноническое имя, если есть в пуле
        from utils.wc_callups import resolve_nation_name

        canon = resolve_nation_name(want_host) or want_host
        chosen = canon
    else:
        # не повторять предыдущего хоста этого сезона при force
        prev = (by.get(key) or {}).get("host") if isinstance(by.get(key), dict) else None
        candidates = [x for x in pool if x != prev] or list(pool)
        chosen = rng.choice(candidates)

    style = rng.choice(list(LOGO_STYLES))
    seed = int(rng.randint(1, 2**31 - 1))
    rec = {
        "host": chosen,
        "style": style,
        "seed": seed,
        "display_year": display_year_for_season(n),
        "season": n,
        "is_wc_season": is_world_cup_season(n),
    }
    by[key] = rec
    save_branding(data)
    # сбросить кэш PNG
    try:
        from bot.wc_logo import clear_logo_cache

        clear_logo_cache(n)
    except Exception:
        pass
    return dict(rec)
