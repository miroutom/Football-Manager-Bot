# -*- coding: utf-8 -*-
"""
Брендинг ЧМ: страна-хозяйка + стиль логотипа на сезон.

Хранится в ``data/wc_branding.json``::

    {
      "version": 1,
      "by_season": {
        "4": {
          "host": "Япония",
          "style": "trophy_rings",
          "seed": 40127,
          "season": 4
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

# Стили генератора логотипа (см. bot/wc_logo.py) — все с кубком
LOGO_STYLES: tuple[str, ...] = (
    "trophy_center",
    "trophy_side",
    "trophy_rings",
    "trophy_bands",
)


def branding_path() -> str:
    return _PATH


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
    migrate_branding_styles()
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


def is_wc_start_announced(season: int | None = None) -> bool:
    rec = get_branding(season)
    return bool(rec and rec.get("wc_started_announced"))


def mark_wc_start_announced(season: int | None = None) -> None:
    n = int(season if season is not None else season_paths.get_active_season())
    data = load_branding()
    by = data.setdefault("by_season", {})
    key = str(n)
    rec = by.get(key)
    if not isinstance(rec, dict):
        rec = dict(ensure_branding(n))
    rec["wc_started_announced"] = True
    rec.setdefault("season", n)
    by[key] = rec
    save_branding(data)


def migrate_branding_styles() -> None:
    """Старые стили / год → новые стили с кубком; сброс кэша только при изменении."""
    from bot.wc_logo import _LEGACY_STYLE, clear_logo_cache

    data = load_branding()
    by = data.get("by_season") or {}
    changed = False
    touched: list[int] = []
    for key, rec in list(by.items()):
        if not isinstance(rec, dict):
            continue
        before = dict(rec)
        st = str(rec.get("style") or "")
        if st in _LEGACY_STYLE:
            rec["style"] = _LEGACY_STYLE[st]
        elif st not in LOGO_STYLES:
            rec["style"] = LOGO_STYLES[0]
        rec["season"] = int(rec.get("season") or key)
        rec.pop("display_year", None)
        if rec != before:
            changed = True
            try:
                touched.append(int(key))
            except (TypeError, ValueError):
                pass
        by[key] = rec
    if changed:
        data["by_season"] = by
        save_branding(data)
        for n in touched:
            try:
                clear_logo_cache(n)
            except Exception:
                pass
