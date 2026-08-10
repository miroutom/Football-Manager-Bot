#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Игроки по нациям (клуб + FA) для Transfer Window App."""
from __future__ import annotations

import json
import time
from typing import Any

from utils.wc_callups import _norm_nat, resolve_nation_name


def _display_nation(raw: str) -> str:
    s = (raw or "").strip()
    if not s:
        return "Без нации"
    return resolve_nation_name(s) or s


def _player_id(team: str, name: str, position: str, *, is_fa: bool) -> str:
    pos = (position or "").strip().upper()
    nm = (name or "").strip()
    if is_fa:
        from utils.free_agents_db import fa_player_id

        return fa_player_id(nm, pos)
    return f"{team}|{nm}|{pos}"


def build_all_national_pools() -> dict[str, Any]:
    """Все активные игроки лиги + FA, сгруппированные по нации."""
    from data.defender import Defender
    from data.forward import Forward
    from data.goalkeeper import Goalkeeper
    from data.midfielder import Midfielder
    from utils.free_agents_db import fa_player_id, is_free_agent_team, list_free_agents
    from utils.player_names import player_display_name
    from utils.player_nation import effective_player_nation
    from utils import season_paths
    from utils.utils import session_league

    buckets: dict[str, dict[str, Any]] = {}
    seen_ids: set[str] = set()

    def _bucket(nation_raw: str) -> dict[str, Any]:
        key = _norm_nat(nation_raw) or "__none__"
        if key not in buckets:
            buckets[key] = {
                "name": _display_nation(nation_raw),
                "players": [],
            }
        return buckets[key]

    def _add(
        *,
        name: str,
        position: str,
        overall: int,
        team: str,
        nation_raw: str,
        is_fa: bool,
        person_id: int | None = None,
    ) -> None:
        nm = (name or "").strip()
        pos = (position or "").strip().upper()
        if not nm or not pos:
            return
        pid = fa_player_id(nm, pos) if is_fa else _player_id(team, nm, pos, is_fa=False)
        if pid in seen_ids:
            return
        seen_ids.add(pid)
        _bucket(nation_raw)["players"].append(
            {
                "id": pid,
                "name": nm,
                "position": pos,
                "overall": int(overall or 0),
                "team": team,
                "nation": _display_nation(nation_raw),
                "is_fa": is_fa,
                "person_id": person_id,
            }
        )

    sleague = session_league
    for Cls in (Forward, Midfielder, Defender, Goalkeeper):
        for r in sleague.query(Cls).all():
            if bool(getattr(r, "left_team", False)):
                continue
            team = (getattr(r, "team", "") or "").strip()
            if not team or is_free_agent_team(team):
                continue
            name = player_display_name(r)
            db_nat = (getattr(r, "nation", None) or "") or ""
            nat = effective_player_nation(name, team, db_nat or None, sleague) or ""
            if not nat:
                continue
            _add(
                name=name,
                position=getattr(r, "position", "") or "",
                overall=int(getattr(r, "overall", 0) or 0),
                team=team,
                nation_raw=nat,
                is_fa=False,
                person_id=getattr(r, "person_id", None),
            )

    for p in list_free_agents():
        fa_name = str(p.get("name") or "")
        db_nat = str(p.get("nation") or "")
        nat = effective_player_nation(fa_name, "Free Agent", db_nat or None, sleague) or ""
        if not nat:
            continue
        _add(
            name=fa_name,
            position=str(p.get("position") or ""),
            overall=int(p.get("overall") or 0),
            team="Free Agent",
            nation_raw=nat,
            is_fa=True,
            person_id=p.get("person_id"),
        )

    nations = sorted(buckets.values(), key=lambda b: b["name"].casefold())
    for b in nations:
        b["players"].sort(
            key=lambda p: (-int(p.get("overall") or 0), str(p.get("name") or "").casefold())
        )

    return {
        "season": season_paths.get_active_season(),
        "exported_at": int(time.time()),
        "nations": nations,
        "player_count": sum(len(b["players"]) for b in nations),
    }


def format_national_pools_txt(data: dict[str, Any]) -> str:
    lines: list[str] = []
    lines.append(f"# сборные · сезон {data.get('season', '?')} · игроков {data.get('player_count', 0)}")
    lines.append("")
    for block in data.get("nations") or []:
        name = block.get("name") or "?"
        lines.append(f"@{name}")
        lines.append("====")
        for p in block.get("players") or []:
            club = p.get("team") or "?"
            lines.append(
                f"{p.get('name', '?')} {p.get('position', '?')} {p.get('overall', 0)}  {club}"
            )
        lines.append("")
    return "\n".join(lines).rstrip() + "\n"


def format_national_pools_json(data: dict[str, Any]) -> str:
    return json.dumps(data, ensure_ascii=False, indent=2) + "\n"


def write_national_pools_txt(path: str, data: dict[str, Any]) -> None:
    with open(path, "w", encoding="utf-8") as f:
        f.write(format_national_pools_txt(data))


def write_national_pools_json(path: str, data: dict[str, Any]) -> None:
    with open(path, "w", encoding="utf-8") as f:
        f.write(format_national_pools_json(data))


def parse_national_pools_json(raw: dict[str, Any]) -> dict[str, Any]:
    nations = raw.get("nations")
    if not isinstance(nations, list):
        raise ValueError("Нужен JSON с полем nations (export national_pools.json).")
    out_nations: list[dict[str, Any]] = []
    for block in nations:
        if not isinstance(block, dict):
            continue
        players = block.get("players") or []
        if not isinstance(players, list):
            players = []
        out_nations.append(
            {
                "name": str(block.get("name") or "?"),
                "players": [p for p in players if isinstance(p, dict) and p.get("name")],
            }
        )
    return {
        "season": raw.get("season"),
        "exported_at": raw.get("exported_at"),
        "nations": out_nations,
        "player_count": sum(len(b["players"]) for b in out_nations),
    }
