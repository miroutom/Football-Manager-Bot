# -*- coding: utf-8 -*-
"""
Читает/пишет ``data/season_history.json`` — чемпионы лиг и ЛЧ, личные награды по сезонам.
При завершении сезона чемпионы лиг и ЛЧ подставляются из таблиц (см. ``record_tournament_winners_from_finalize``).
Личные награды правятся вручную в JSON или скриптом загрузки фото.
"""
from __future__ import annotations

import json
import logging
import os
from typing import Any

logger = logging.getLogger(__name__)

_PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_HISTORY_PATH = os.path.join(_PROJECT_ROOT, "data", "season_history.json")


def _default_data() -> dict[str, Any]:
    return {
        "version": 1,
        "league_winners": {
            "rpl": [],
            "eng": [],
            "esp": [],
            "ita": [],
            "ger": [],
        },
        "champions_league": [],
        "world_cup": [],
        "cl_knockout_stages": [],
        "golden_ball": [],
        "golden_boot": [],
        "golden_glove": [],
        "golden_boy": [],
        "world_cup_best": [],
    }


def load_history() -> dict[str, Any]:
    if not os.path.isfile(_HISTORY_PATH):
        return _default_data()
    try:
        with open(_HISTORY_PATH, encoding="utf-8") as f:
            raw = json.load(f)
    except (OSError, json.JSONDecodeError) as e:
        logger.warning("season_history.json: %s — подставляю шаблон", e)
        return _default_data()
    out = _default_data()
    if not isinstance(raw, dict):
        return out
    lw = raw.get("league_winners")
    if isinstance(lw, dict):
        for code in out["league_winners"]:
            if code in lw and isinstance(lw[code], list):
                out["league_winners"][code] = lw[code]
    for key in (
        "champions_league",
        "world_cup",
        "cl_knockout_stages",
        "golden_ball",
        "golden_boot",
        "golden_glove",
        "golden_boy",
        "world_cup_best",
    ):
        v = raw.get(key)
        if isinstance(v, list):
            out[key] = v
    return out


def save_history(data: dict[str, Any]) -> None:
    os.makedirs(os.path.dirname(_HISTORY_PATH), exist_ok=True)
    tmp = _HISTORY_PATH + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
        f.write("\n")
    os.replace(tmp, _HISTORY_PATH)


def _upsert_season_row(rows: list[list[Any]], season: int, new_row: list[Any]) -> None:
    s = int(season)
    for i, row in enumerate(rows):
        if row and int(row[0]) == s:
            rows[i] = new_row
            return
    rows.append(new_row)
    rows.sort(key=lambda r: int(r[0]))


def record_tournament_winners_from_finalize(ended_season: int, trophies_log: dict[str, Any]) -> None:
    """Вызывается из ``finalize_season`` после ``apply_season_trophies_from_standings``."""
    data = load_history()
    nat = trophies_log.get("national_winners") or {}
    for code, info in nat.items():
        if code == "cl" or not isinstance(info, dict):
            continue
        team = info.get("team")
        if not team:
            continue
        lw = data.setdefault("league_winners", {}).setdefault(code, [])
        if not isinstance(lw, list):
            continue
        _upsert_season_row(lw, ended_season, [ended_season, team])

    cl_block = trophies_log.get("cl_winner")
    team_cl = None
    if isinstance(cl_block, dict):
        team_cl = cl_block.get("team")
    cl_rows = data.setdefault("champions_league", [])
    if isinstance(cl_rows, list) and team_cl:
        _upsert_season_row(cl_rows, ended_season, [ended_season, team_cl])

    wc_block = trophies_log.get("wc_winner")
    team_wc = None
    if isinstance(wc_block, dict):
        team_wc = wc_block.get("team")
    if team_wc:
        from utils.world_cup import is_world_cup_season

        if is_world_cup_season(ended_season):
            wc_rows = data.setdefault("world_cup", [])
            if isinstance(wc_rows, list):
                _upsert_season_row(wc_rows, ended_season, [ended_season, team_wc])

    save_history(data)


def record_cl_knockout_stages_for_season(
    season: int,
    stages_by_team: dict[str, int],
) -> None:
    """Записать стадии плей-офф ЛЧ всех клубов сезона."""
    if not stages_by_team:
        return
    data = load_history()
    rows = data.setdefault("cl_knockout_stages", [])
    if not isinstance(rows, list):
        rows = []
        data["cl_knockout_stages"] = rows
    clean = {str(k).strip().title(): int(v) for k, v in stages_by_team.items() if k}
    _upsert_season_row(rows, int(season), [int(season), clean])
    save_history(data)


def record_cl_knockout_stages_from_archive(ended_season: int, archive_dir: str) -> str:
    """
    Считать стадии из ``match_results.json`` архива и сохранить в историю.
    Возвращает ``ok``, ``no_journal`` или ``error:…``.
    """
    import os

    jp = os.path.join(archive_dir, "match_results.json")
    if not os.path.isfile(jp):
        return "no_journal"
    try:
        from utils.cl_knockout_results import all_cl_knockout_stages_from_journal

        stages = all_cl_knockout_stages_from_journal(jp)
        if stages:
            record_cl_knockout_stages_for_season(int(ended_season), stages)
        return "ok"
    except Exception as e:
        logger.warning("cl_knockout_stages season %s: %s", ended_season, e)
        return f"error:{e!s}"


_AWARD_KIND_KEYS = {
    "ball": "golden_ball",
    "golden_ball": "golden_ball",
    "boot": "golden_boot",
    "golden_boot": "golden_boot",
    "glove": "golden_glove",
    "golden_glove": "golden_glove",
    "boy": "golden_boy",
    "golden_boy": "golden_boy",
    "wc_best": "world_cup_best",
    "world_cup_best": "world_cup_best",
}


def record_award_winner(
    season: int,
    kind: str,
    player: str,
    team: str,
    *,
    photo_slug: str | None = None,
) -> None:
    """Записать победителя личной награды в ``season_history.json``."""
    key = _AWARD_KIND_KEYS.get((kind or "").strip().lower())
    if not key:
        raise ValueError(f"Неизвестная награда для истории: {kind!r}")
    p = (player or "").strip()
    t = (team or "").strip()
    if not p or not t:
        raise ValueError("Игрок и клуб обязательны для season_history")
    row: list[Any] = [int(season), p, t]
    if photo_slug and str(photo_slug).strip():
        row.append(str(photo_slug).strip())
    data = load_history()
    rows = data.setdefault(key, [])
    if not isinstance(rows, list):
        rows = []
        data[key] = rows
    _upsert_season_row(rows, int(season), row)
    save_history(data)


def _rows_by_season(rows: list[Any]) -> dict[int, list[Any]]:
    out: dict[int, list[Any]] = {}
    if not isinstance(rows, list):
        return out
    for row in rows:
        if not row or len(row) < 2:
            continue
        try:
            out[int(row[0])] = row
        except (TypeError, ValueError):
            continue
    return out


def timeline_league(league_code: str, max_season: int) -> list[tuple[int, str | None]]:
    """Сезоны 1..max_season; ``None`` — ещё не занесено (показываем «?»)."""
    data = load_history()
    raw = (data.get("league_winners") or {}).get(league_code) or []
    by_s = _rows_by_season(raw)
    out: list[tuple[int, str | None]] = []
    for s in range(1, int(max_season) + 1):
        row = by_s.get(s)
        if not row:
            out.append((s, None))
            continue
        team = row[1]
        if team is None or (isinstance(team, str) and not team.strip()):
            out.append((s, None))
        else:
            out.append((s, str(team).strip()))
    return out


def timeline_cl(max_season: int) -> list[tuple[int, str | None]]:
    data = load_history()
    raw = data.get("champions_league") or []
    by_s = _rows_by_season(raw)
    out: list[tuple[int, str | None]] = []
    for s in range(1, int(max_season) + 1):
        row = by_s.get(s)
        if not row:
            out.append((s, None))
            continue
        team = row[1]
        if team is None or (isinstance(team, str) and not team.strip()):
            out.append((s, None))
        else:
            out.append((s, str(team).strip()))
    return out


def timeline_wc(max_season: int) -> list[tuple[int, str | None]]:
    """Только сезоны ЧМ (4, 8, 12…); ``None`` — ещё нет чемпиона."""
    from utils.world_cup import list_world_cup_seasons_up_to

    data = load_history()
    raw = data.get("world_cup") or []
    by_s = _rows_by_season(raw)
    out: list[tuple[int, str | None]] = []
    seasons = list_world_cup_seasons_up_to(max_season)
    # если активный сезон ещё не WC, всё равно показать ближайший слот с «?»
    if not seasons and int(max_season) >= 4:
        from utils.world_cup import next_world_cup_season

        seasons = [next_world_cup_season(max_season)]
    elif int(max_season) >= 4:
        from utils.world_cup import is_world_cup_season, next_world_cup_season

        nxt = next_world_cup_season(max_season)
        if is_world_cup_season(max_season) and max_season not in seasons:
            seasons.append(int(max_season))
        elif nxt not in seasons and nxt <= int(max_season):
            seasons.append(nxt)
        seasons = sorted(set(seasons))
    for s in seasons:
        row = by_s.get(s)
        if not row:
            out.append((s, None))
            continue
        team = row[1]
        if team is None or (isinstance(team, str) and not team.strip()):
            out.append((s, None))
        else:
            out.append((s, str(team).strip()))
    return out


def timeline_award(kind: str, max_season: int) -> list[tuple[int, str | None, str | None, str | None]]:
    """
    kind: golden_ball | golden_boot | golden_glove | golden_boy | world_cup_best
    Возвращает (сезон, игрок, клуб, slug_фото_без_расширения).
    Для ``world_cup_best`` — только сезоны ЧМ (4, 8, 12…).
    """
    data = load_history()
    raw = data.get(kind) or []
    by_s = _rows_by_season(raw)
    out: list[tuple[int, str | None, str | None, str | None]] = []
    if kind == "world_cup_best":
        from utils.world_cup import list_world_cup_seasons_up_to

        season_list = list_world_cup_seasons_up_to(int(max_season))
        if not season_list and int(max_season) >= 4:
            from utils.world_cup import next_world_cup_season

            season_list = [next_world_cup_season(int(max_season))]
    else:
        season_list = list(range(1, int(max_season) + 1))
    for s in season_list:
        row = by_s.get(s)
        if not row:
            out.append((s, None, None, None))
            continue
        p = row[1] if len(row) > 1 else None
        t = row[2] if len(row) > 2 else None
        slug = row[3] if len(row) > 3 else None
        if p is not None and isinstance(p, str) and not p.strip():
            p = None
        if t is not None and isinstance(t, str) and not t.strip():
            t = None
        if slug is not None and isinstance(slug, str) and not slug.strip():
            slug = None
        out.append((s, p, t, slug))
    return out
