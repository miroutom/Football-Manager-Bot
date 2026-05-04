# -*- coding: utf-8 -*-
"""
Топ-6 из каждой национальной лиги → 30 участников ЛЧ.

Источники:
- ``build_cl_top30_from_draft_json`` — места из ``data/draft_config.json`` (клубы из конфига лиг);
- ``build_cl_top30_from_current_pickles`` — текущие таблицы из pickle (старый режим).
"""
from __future__ import annotations

import json
from pathlib import Path

from config.leagues_config import ALL_LEAGUES, _norm_club_token

_ROOT = Path(__file__).resolve().parent.parent
_CL_FILE = _ROOT / "data" / "cl_participants_dynamic.txt"
_DRAFT_JSON = _ROOT / "data" / "draft_config.json"

_LEAGUE_ORDER = ("rpl", "eng", "esp", "ita", "ger")


def build_cl_top30_from_draft_json(path: Path | None = None) -> list[str]:
    """
    По полю ``place`` в черновике турнирной таблицы: в каждой лиге топ-6 среди клубов,
    которые есть в ``ALL_LEAGUES`` (8 команд на лигу в игре). Имена — как в JSON.
    """
    p = path or _DRAFT_JSON
    if not p.is_file():
        raise FileNotFoundError(p)
    raw = json.loads(p.read_text(encoding="utf-8"))
    rows = raw.get("teams") or []
    if not isinstance(rows, list):
        raise ValueError("draft_config: нет teams")

    out: list[str] = []
    for code in _LEAGUE_ORDER:
        lg = ALL_LEAGUES.get(code)
        if not lg:
            continue
        roster_norms = {_norm_club_token(x): x for x in lg["teams"]}
        cand: list[tuple[int, str]] = []
        for row in rows:
            if not isinstance(row, dict):
                continue
            if (row.get("league") or "").strip() != code:
                continue
            nm = (row.get("name") or "").strip()
            nn = _norm_club_token(nm)
            if nn not in roster_norms:
                continue
            try:
                place = int(row.get("place") or 999)
            except (TypeError, ValueError):
                place = 999
            cand.append((place, nm))
        cand.sort(key=lambda x: (x[0], x[1].lower()))
        top = [name for _, name in cand[:6]]
        if len(top) != 6:
            raise ValueError(
                f"{code}: нужно 6 клубов из конфига с местами в draft, собрано {len(top)}"
            )
        out.extend(top)
    if len(out) != 30:
        raise ValueError(f"ожидалось 30 участников ЛЧ, получилось {len(out)}")
    return out


def build_cl_top30_from_current_pickles() -> list[str]:
    """
    6 лучших по таблице из rpl, eng, esp, ita, ger (5×6=30), порядок фиксирован.
    """
    from main import LEAGUES, get_teams_by_league
    from teams import get_sorted_teams

    order = ("rpl", "eng", "esp", "ita", "ger")
    by_code = {lg["code"]: (_k, lg) for _k, lg in LEAGUES.items()}
    out: list[str] = []
    for code in order:
        item = by_code.get(code)
        if not item:
            continue
        _k, lg = item
        teams = get_teams_by_league(code)
        if not teams:
            continue
        top6 = get_sorted_teams(teams)[:6]
        for name, _t in top6:
            out.append((name or "").strip())
    return out


def write_cl_participants_file(names: list[str]) -> str:
    """Пишет ``data/cl_participants_dynamic.txt`` (30 строк). Чтение в ЛЧ — через ``str.title()``."""
    _CL_FILE.parent.mkdir(parents=True, exist_ok=True)
    lines = [n.strip() for n in names if n.strip()]
    if len(lines) != 30:
        # не валим сезон: всё равно пишем, в логе предупредят
        pass
    with open(_CL_FILE, "w", encoding="utf-8") as f:
        f.write("\n".join(lines))
    return str(_CL_FILE)
