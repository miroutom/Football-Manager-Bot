#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Экспорт сборных ЧМ в national_rosters.json для Transfer Window App."""
from __future__ import annotations

import json
import sys
import time
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[2]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from tools.transfer_window_app.export_rosters import _export_formations_catalog  # noqa: E402
from utils import season_paths  # noqa: E402
from utils.wc_squad_app import nation_team_template, wc_nations_flat  # noqa: E402
from utils.wc_callups import resolve_nation_name  # noqa: E402
from utils.world_cup import load_wc_squads  # noqa: E402


def export_all_national_rosters() -> dict:
    data = load_wc_squads()
    meta = data.get("meta") if isinstance(data.get("meta"), dict) else {}
    wc_teams = data.get("teams") or {}
    season = season_paths.get_active_season()
    teams: list[dict] = []
    baseline_home: dict[str, str] = {}

    for nation in wc_nations_flat():
        canon = resolve_nation_name(nation) or nation
        roster = wc_teams.get(canon) or []
        if not isinstance(roster, list):
            roster = []
        nm = meta.get(canon) if isinstance(meta.get(canon), dict) else {}
        coach = str((nm or {}).get("coach") or "").strip()
        fid = int((nm or {}).get("formation_id") or 1)
        block = nation_team_template(
            canon,
            formation_id=fid,
            coach=coach,
            roster=roster,
            season=season,
        )
        teams.append(block)
        for pid in block.get("baseline_ids") or []:
            baseline_home[pid] = canon

    exported_at = int(time.time())
    return {
        "mode": "nations",
        "season": season,
        "exported_at": exported_at,
        "squad_rules": {
            "total": 26,
            "start": 11,
            "bench": 7,
            "reserve": 8,
            "hint": "26 игроков: 11 старт + 7 запас + 8 резерв (ЧМ)",
        },
        "formations": _export_formations_catalog(),
        "teams": teams,
        "baseline_home": baseline_home,
        "free_agents": [],
    }


def main() -> int:
    out_dir = Path(__file__).resolve().parent
    data = export_all_national_rosters()
    out_path = out_dir / "national_rosters.json"
    with out_path.open("w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
        f.write("\n")
    print(
        f"Сборные ЧМ: {len(data['teams'])} наций → {out_path}\n"
        f"  сезон {data['season']}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
