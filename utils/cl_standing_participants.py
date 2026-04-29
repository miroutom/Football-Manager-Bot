# -*- coding: utf-8 -*-
"""
Топ-6 из каждой национальной лиги → 30 участников ЛЧ (по таблице pickle).
"""
from __future__ import annotations

from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent
_CL_FILE = _ROOT / "data" / "cl_participants_dynamic.txt"

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
    """Пишет ``data/cl_participants_dynamic.txt`` (30 строк, Title)."""
    _CL_FILE.parent.mkdir(parents=True, exist_ok=True)
    lines = [n.strip().title() for n in names if n.strip()]
    if len(lines) != 30:
        # не валим сезон: всё равно пишем, в логе предупредят
        pass
    with open(_CL_FILE, "w", encoding="utf-8") as f:
        f.write("\n".join(lines))
    return str(_CL_FILE)
