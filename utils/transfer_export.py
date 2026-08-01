# -*- coding: utf-8 -*-
"""Выгрузки для бота и desktop transfer app."""
from __future__ import annotations

import json
from typing import Any


def export_squads_txt_for_bot() -> str:
    """Текст составов 40 клубов (формат squads_export для бота)."""
    from tools.transfer_window_app.export_rosters import export_all
    from tools.transfer_window_app.main import build_state_payload, compute_transfers

    data = export_all()
    state = build_state_payload(
        {
            "window": "summer",
            "baseline_home": data.get("baseline_home") or {},
            "teams": data.get("teams") or [],
        }
    )
    state["transfers"] = compute_transfers(state)
    lines: list[str] = []
    for team in state.get("teams") or []:
        tname = team["name"]
        lines.append(f"@{tname}")
        lines.append("==== start ===")
        for s in team.get("start") or []:
            if s.get("name"):
                slot = s.get("slot") or ""
                lines.append(
                    f"{s['name']} {slot} {s['position']} {s['overall']}".strip()
                )
        lines.append("=== bench ===")
        for p in team.get("bench") or []:
            if p.get("name"):
                lines.append(f"{p['name']} {p['position']} {p['overall']}")
        lines.append("=== reserve ===")
        for p in team.get("reserve") or []:
            if p.get("name"):
                lines.append(f"{p['name']} {p['position']} {p['overall']}")
        lines.append("")
    transfers = state.get("transfers") or []
    if transfers:
        lines.append("=== transfers ===")
        for t in transfers:
            status = t.get("status") or ""
            status_suffix = f" ({status})" if status else ""
            lines.append(
                f"{t['name']} {t['position']} {t['overall']}  "
                f"{t['from_team']} -> {t['to_team']}{status_suffix}"
            )
        lines.append("")
    return "\n".join(lines).rstrip() + "\n"


def export_free_agents_payload() -> dict[str, Any]:
    """JSON пул свободных агентов для transfer app."""
    from utils import season_paths
    from utils.free_agents_db import list_free_agents

    return {
        "season": season_paths.get_active_season(),
        "team_label": "Free Agent",
        "players": list_free_agents(),
    }


def export_free_agents_json_for_bot() -> str:
    return json.dumps(export_free_agents_payload(), ensure_ascii=False, indent=2)


def export_free_agents_txt_for_bot() -> str:
    """TSV для быстрого просмотра."""
    lines = ["person_id\tИгрок\tПоз\tРейтинг\tНация\tНик"]
    for p in export_free_agents_payload().get("players") or []:
        lines.append(
            f"{p.get('person_id') or ''}\t{p.get('name')}\t{p.get('position')}\t"
            f"{p.get('overall')}\t{p.get('nation') or ''}\t{p.get('nickname') or ''}"
        )
    return "\n".join(lines) + "\n"


def export_national_pools_bundle_for_bot() -> tuple[str, str, dict[str, Any]]:
    """TXT + JSON всех игроков по нациям (клуб + FA) для бота / transfer app."""
    from tools.transfer_window_app.national_pools import (
        build_all_national_pools,
        format_national_pools_json,
        format_national_pools_txt,
    )

    data = build_all_national_pools()
    return format_national_pools_txt(data), format_national_pools_json(data), data


def export_wc_squads_txt_for_bot() -> str:
    """Готовые заявки сборных ЧМ (wc_squads_export.txt) из world_cup_squads.json."""
    from tools.transfer_window_app.export_national_rosters import export_all_national_rosters
    from utils.wc_squad_app import format_wc_squads_export_txt

    data = export_all_national_rosters()
    return format_wc_squads_export_txt(data.get("teams") or [])
