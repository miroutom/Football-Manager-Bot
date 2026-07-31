# -*- coding: utf-8 -*-
"""
Состояние турнира ЧМ: группы, менеджеры, жеребьёвка.

Файл: ``data/wc_tournament.json``
"""
from __future__ import annotations

import json
import os
from typing import Any

from utils import season_paths
from utils.world_cup import is_world_cup_season, nations_by_confederation
from utils.world_cup_format import (
    GROUP_IDS,
    all_group_fixtures,
    draw_groups_fifa,
    format_rules_ru,
    validate_nation_count,
)

_PATH = os.path.join(season_paths.PROJECT_ROOT, "data", "wc_tournament.json")


def default_tournament(season: int | None = None) -> dict[str, Any]:
    n = int(season if season is not None else season_paths.get_active_season())
    return {
        "version": 1,
        "season": n,
        "drawn": False,
        "draw_seed": None,
        "groups": {g: [] for g in GROUP_IDS},
        "managers": {
            "Roman": [],
            "Lika": [],
        },
        "notes": "Менеджеров по сборным пришлёте позже · Roman / Lika.",
    }


def load_tournament() -> dict[str, Any]:
    if not os.path.isfile(_PATH):
        return default_tournament()
    try:
        with open(_PATH, encoding="utf-8") as f:
            raw = json.load(f)
    except (OSError, json.JSONDecodeError):
        return default_tournament()
    out = default_tournament()
    if isinstance(raw, dict):
        out.update(raw)
        out.setdefault("groups", {g: [] for g in GROUP_IDS})
        out.setdefault("managers", {"Roman": [], "Lika": []})
    return out


def save_tournament(data: dict[str, Any]) -> None:
    os.makedirs(os.path.dirname(_PATH), exist_ok=True)
    tmp = _PATH + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
        f.write("\n")
    os.replace(tmp, _PATH)


def tournament_path() -> str:
    return _PATH


def groups_drawn() -> bool:
    data = load_tournament()
    if not data.get("drawn"):
        return False
    groups = data.get("groups") or {}
    return all(len(groups.get(g) or []) == 4 for g in GROUP_IDS)


def run_group_draw(*, seed: int | None = None, force: bool = False) -> dict[str, Any]:
    """
    Жеребьёвка групп. Пишет ``wc_tournament.json``.
    ``force=True`` — пережеребить даже если уже было.
    """
    if not is_world_cup_season():
        raise RuntimeError("Жеребьёвка ЧМ доступна только в сезоне ЧМ (4/8/12…).")
    by = nations_by_confederation()
    ok, msg = validate_nation_count(by)
    if not ok:
        raise ValueError(msg)
    data = load_tournament()
    if data.get("drawn") and groups_drawn() and not force:
        return data
    season = season_paths.get_active_season()
    use_seed = int(seed) if seed is not None else int(season) * 10007 + 48
    groups = draw_groups_fifa(by, seed=use_seed)
    data["season"] = season
    data["drawn"] = True
    data["draw_seed"] = use_seed
    data["groups"] = groups
    data["format_rules"] = format_rules_ru()
    # сохранить менеджеров, если уже были
    data.setdefault("managers", {"Roman": [], "Lika": []})
    save_tournament(data)
    # сразу пробуем дописать месяц 11
    try:
        from utils.wc_schedule import ensure_wc_group_stage_in_schedule

        ensure_wc_group_stage_in_schedule(replace_existing=force)
    except Exception:
        pass
    return data


def set_manager_nations(manager: str, nations: list[str]) -> dict[str, Any]:
    """Roman / Lika → списки сборных ЧМ."""
    key = (manager or "").strip()
    if key not in ("Roman", "Lika"):
        raise ValueError("manager: Roman или Lika")
    data = load_tournament()
    mgr = data.setdefault("managers", {"Roman": [], "Lika": []})
    mgr[key] = [str(n).strip() for n in nations if str(n).strip()]
    data["notes"] = "Менеджеры: Roman / Lika — по 24 сборные."
    save_tournament(data)
    return data


def managers_html(data: dict[str, Any] | None = None) -> str:
    """Текст меню менеджеров с разбивкой по конфедерациям."""
    from html import escape as html_escape

    from utils.world_cup import nations_by_confederation

    data = data or load_tournament()
    mgr = data.get("managers") or {}
    by_conf = nations_by_confederation()
    # nation → conf
    nat_conf: dict[str, str] = {}
    for conf, teams in by_conf.items():
        for t in teams or []:
            nat_conf[str(t).strip().casefold()] = str(conf)

    conf_order = list(by_conf.keys()) or [
        "Европа",
        "Азия",
        "Африка",
        "Сев. Америка",
        "Юж. Америка",
    ]

    lines = ["<b>Менеджеры ЧМ</b>", ""]
    for key in ("Roman", "Lika"):
        nations = [str(x).strip() for x in (mgr.get(key) or []) if str(x).strip()]
        lines.append(f"<b>{key}</b> — {len(nations)} сборных")
        if not nations:
            lines.append("· пока пусто")
            lines.append("")
            continue
        buckets: dict[str, list[str]] = {c: [] for c in conf_order}
        other: list[str] = []
        for n in nations:
            conf = nat_conf.get(n.casefold())
            if conf and conf in buckets:
                buckets[conf].append(n)
            else:
                other.append(n)
        for conf in conf_order:
            chunk = buckets.get(conf) or []
            if not chunk:
                continue
            lines.append(f"<i>{html_escape(conf)}</i>")
            for t in chunk:
                lines.append(f"· {html_escape(t)}")
        for t in other:
            lines.append(f"· {html_escape(t)}")
        lines.append("")
    return "\n".join(lines).rstrip()


def groups_html(data: dict[str, Any] | None = None) -> str:
    data = data or load_tournament()
    if not data.get("drawn"):
        return "<b>ЧМ</b>\n\nЖеребьёвка ещё не проведена."
    lines = ["<b>ЧМ · группы</b>", f"Сезон {data.get('season')}", ""]
    for g in GROUP_IDS:
        teams = data.get("groups", {}).get(g) or []
        lines.append(f"<b>Группа {g}</b>")
        for t in teams:
            lines.append(f"· {t}")
        lines.append("")
    return "\n".join(lines).rstrip()


def fixtures_for_drawn_groups() -> list[dict[str, Any]]:
    data = load_tournament()
    if not data.get("drawn"):
        return []
    return all_group_fixtures(data.get("groups") or {})
