# -*- coding: utf-8 -*-
"""
Чемпионат мира (ЧМ).

Правила (сезон 4+):
- проходит в сезонах 4, 8, 12, … (``season % 4 == 0``);
- календарный месяц 11 — после финала ЛЧ (месяц 10);
- отдельная БД ``db/season_N/world_cup.db``;
- сборные = вызовы игроков из клубов (+ ручные добавления);
- в сезонах ЧМ личные награды (ЗМ/бутса/перчатка/boy) — после турнира;
- отдельно: лучший игрок ЧМ.
"""
from __future__ import annotations

import json
import os
import sqlite3
from typing import Any

from utils import season_paths

# Месяц турнира (после ЛЧ)
WC_CALENDAR_MONTH = 11
WC_LEAGUE_CODE = "wc"

_PROJECT = season_paths.PROJECT_ROOT
_CONFIG_PATH = os.path.join(_PROJECT, "data", "world_cup_config.json")
_SQUADS_PATH = os.path.join(_PROJECT, "data", "world_cup_squads.json")


def is_world_cup_season(season: int | None = None) -> bool:
    """ЧМ каждые 4 сезона, начиная с 4-го."""
    n = int(season if season is not None else season_paths.get_active_season())
    return n >= 4 and n % 4 == 0


def next_world_cup_season(after: int | None = None) -> int:
    n = int(after if after is not None else season_paths.get_active_season())
    if n < 4:
        return 4
    if is_world_cup_season(n):
        return n
    return n + (4 - n % 4)


def list_world_cup_seasons_up_to(max_season: int | None = None) -> list[int]:
    mx = int(max_season if max_season is not None else season_paths.get_active_season())
    return [s for s in range(4, mx + 1, 4)]


def default_config() -> dict[str, Any]:
    return {
        "version": 2,
        "notes": (
            "Предварительный список сборных · формат FIFA WC 2026 "
            "(12 групп × 4, 8 лучших третьих → 1/16)."
        ),
        "nations_by_confederation": {},
        "nations": [],
        "format": {
            "model": "fifa_wc_2026",
            "teams": 48,
            "groups": 12,
            "group_size": 4,
            "group_matches": "single_rr",
            "qualify_per_group": 2,
            "best_thirds": 8,
            "knockout": ["r32", "r16", "qf", "sf", "third", "final"],
            "calendar_month": WC_CALENDAR_MONTH,
            "after": "cl_final",
        },
        "awards_after_wc": True,
        "awards_manual": True,
    }


def load_wc_config() -> dict[str, Any]:
    if not os.path.isfile(_CONFIG_PATH):
        return default_config()
    try:
        with open(_CONFIG_PATH, encoding="utf-8") as f:
            raw = json.load(f)
    except (OSError, json.JSONDecodeError):
        return default_config()
    out = default_config()
    if isinstance(raw, dict):
        out.update(raw)
        # плоский список для удобства
        by_conf = out.get("nations_by_confederation") or {}
        if isinstance(by_conf, dict) and by_conf:
            from utils.world_cup_format import flatten_nations

            out["nations"] = flatten_nations(by_conf)
    return out


def nations_by_confederation() -> dict[str, list[str]]:
    cfg = load_wc_config()
    raw = cfg.get("nations_by_confederation") or {}
    if isinstance(raw, dict):
        return {str(k): list(v) for k, v in raw.items() if isinstance(v, list)}
    return {}


def wc_final_played(season: int | None = None) -> bool:
    """Финал ЧМ сыгран? (по журналу матчей сезона, phase/final или cl_phase)."""
    n = int(season if season is not None else season_paths.get_active_season())
    if not is_world_cup_season(n):
        return True  # не WC-сезон — ограничение не действует
    try:
        from bot.team_history import iter_all_match_records
    except Exception:
        return False
    for m in iter_all_match_records():
        if int(m.get("_season") or 0) != n:
            continue
        lg = str(m.get("league") or "").strip().lower()
        if lg not in ("wc", "world_cup"):
            continue
        phase = str(m.get("wc_phase") or m.get("cl_phase") or m.get("phase") or "").lower()
        if phase in ("final", "финал"):
            # есть счёт
            if m.get("home_score") is not None and m.get("away_score") is not None:
                return True
    # также смотрим чемпиона в истории
    try:
        from bot.season_history_store import load_history

        for row in load_history().get("world_cup") or []:
            if row and int(row[0]) == n and row[1]:
                return True
    except Exception:
        pass
    return False


def awards_unlocked_for_season(season: int | None = None) -> tuple[bool, str]:
    """
    В WC-сезоне выбор ЗМ/бутсы/… доступен только после финала ЧМ.
    Автовыдачи нет — только ручной выбор в /awards.
    """
    n = int(season if season is not None else season_paths.get_active_season())
    if not is_world_cup_season(n):
        return True, ""
    if wc_final_played(n):
        return True, ""
    return (
        False,
        "Сезон ЧМ: сначала сыграйте финал чемпионата мира (месяц 11), "
        "потом выбирайте ЗМ / бутсу / перчатку / Golden Boy.",
    )


def save_wc_config(data: dict[str, Any]) -> None:
    os.makedirs(os.path.dirname(_CONFIG_PATH), exist_ok=True)
    tmp = _CONFIG_PATH + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
        f.write("\n")
    os.replace(tmp, _CONFIG_PATH)


def load_wc_squads() -> dict[str, Any]:
    """
    Вызовы в сборные.

    Формат::
        {
          "season": 4,
          "teams": {
            "Аргентина": [
              {"name": "…", "club": "…", "position": "ФРВ", "overall": 90, "source": "callup|manual"}
            ]
          }
        }
    """
    if not os.path.isfile(_SQUADS_PATH):
        return {"season": season_paths.get_active_season(), "teams": {}, "notes": "Сборные пока пусты"}
    try:
        with open(_SQUADS_PATH, encoding="utf-8") as f:
            raw = json.load(f)
    except (OSError, json.JSONDecodeError):
        return {"season": season_paths.get_active_season(), "teams": {}, "notes": "Сборные пока пусты"}
    if not isinstance(raw, dict):
        return {"season": season_paths.get_active_season(), "teams": {}}
    raw.setdefault("teams", {})
    return raw


def save_wc_squads(data: dict[str, Any]) -> None:
    os.makedirs(os.path.dirname(_SQUADS_PATH), exist_ok=True)
    tmp = _SQUADS_PATH + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
        f.write("\n")
    os.replace(tmp, _SQUADS_PATH)


def ensure_world_cup_db(season: int | None = None) -> str | None:
    """
    Создать пустую ``world_cup.db`` для WC-сезона (схема как у league.db).
    Для не-WC сезонов — ``None``.
    """
    n = int(season if season is not None else season_paths.get_active_season())
    if not is_world_cup_season(n):
        return None
    path = season_paths.get_wc_db_path_for_season(n)
    if os.path.isfile(path):
        return path
    os.makedirs(os.path.dirname(path), exist_ok=True)
    # шаблон схемы — league.db того же или прошлого сезона
    template = os.path.join(
        season_paths.season_archive_directory(n), season_paths.SEASON_LEAGUE_NAME
    )
    if not os.path.isfile(template):
        template = season_paths.get_league_db_path()
    if not os.path.isfile(template):
        raise FileNotFoundError(f"Нет шаблона league.db для world_cup.db (сезон {n})")
    import shutil

    shutil.copy2(template, path)
    conn = sqlite3.connect(path)
    try:
        tables = [
            r[0]
            for r in conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'"
            )
        ]
        for t in tables:
            conn.execute(f'DELETE FROM "{t}"')
        conn.commit()
    finally:
        conn.close()
    return path


def add_manual_callup(
    nation: str,
    *,
    name: str,
    club: str = "",
    position: str = "",
    overall: int = 0,
    season: int | None = None,
) -> dict[str, Any]:
    """Добавить игрока в заявку сборной вручную (поверх клубных вызовов)."""
    data = load_wc_squads()
    sn = int(season if season is not None else season_paths.get_active_season())
    data["season"] = sn
    teams = data.setdefault("teams", {})
    roster = teams.setdefault(nation.strip(), [])
    entry = {
        "name": name.strip(),
        "club": (club or "").strip(),
        "position": (position or "").strip(),
        "overall": int(overall or 0),
        "source": "manual",
    }
    # не дублировать по имени
    want = entry["name"].casefold()
    for i, row in enumerate(roster):
        if str(row.get("name") or "").casefold() == want:
            roster[i] = {**row, **entry}
            save_wc_squads(data)
            return entry
    roster.append(entry)
    save_wc_squads(data)
    return entry
