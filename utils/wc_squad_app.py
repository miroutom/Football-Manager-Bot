# -*- coding: utf-8 -*-
"""Мост Transfer Window App (режим сборных) ↔ world_cup_squads.json."""
from __future__ import annotations

import re
from typing import Any

from formation_catalog import label_for_formation_id
from team_squad_schemas import get_slots_for_formation_key
from utils.wc_callups import resolve_nation_name
from utils.wc_squad_quota import WC_BENCH, WC_RESERVE, WC_START
from utils.world_cup import load_wc_squads, save_wc_squads

_EMPTY_SLOT = {"id": None, "name": None, "position": None, "overall": None, "injured": False}
_WC_BENCH = WC_BENCH
_WC_RESERVE = WC_RESERVE


def wc_nations_flat() -> list[str]:
    from utils.world_cup import nations_by_confederation
    from utils.world_cup_format import flatten_nations

    return flatten_nations(nations_by_confederation())


def _player_club(player_id: str | None, row: dict[str, Any] | None = None) -> str:
    if row and row.get("club"):
        return str(row["club"]).strip()
    pid = (player_id or "").strip()
    parts = pid.split("|")
    if len(parts) >= 3:
        return parts[0]
    return "Free Agent"


def _app_player_from_wc(row: dict[str, Any], nation: str) -> dict[str, Any]:
    name = str(row.get("name") or "").strip()
    pos = str(row.get("position") or "").strip().upper()
    club = str(row.get("club") or "Free Agent").strip() or "Free Agent"
    if club.lower() in ("free agent", "fa"):
        from utils.free_agents_db import fa_player_id

        pid = fa_player_id(name, pos)
    else:
        pid = f"{club}|{name}|{pos}"
    out = {
        "id": pid,
        "name": name,
        "position": pos,
        "overall": int(row.get("overall") or 0),
        "club": club,
        "injured": False,
        "status": str(row.get("status") or "reserve").strip().lower(),
    }
    if row.get("lineup_slot"):
        out["slot"] = str(row["lineup_slot"]).strip().upper()
    if row.get("person_id") is not None:
        out["person_id"] = row.get("person_id")
    if row.get("nickname"):
        out["nickname"] = row.get("nickname")
    _ = nation
    return out


def nation_team_template(
    nation: str,
    *,
    formation_id: int = 1,
    coach: str = "",
    roster: list[dict[str, Any]] | None = None,
    season: int | None = None,
) -> dict[str, Any]:
    """Сборная в формате transfer app (start/bench/reserve + схема + тренер)."""
    from utils import season_paths

    canon = resolve_nation_name(nation) or (nation or "").strip()
    fid = int(formation_id or 1)
    if fid < 1 or fid > 10:
        fid = 1
    key = f"fid_{fid}"
    slots_tpl = get_slots_for_formation_key(key)
    label = label_for_formation_id(fid)
    coach_s = (coach or "").strip()
    caption = f"{label} · {coach_s}" if coach_s else label

    by_status: dict[str, list[dict[str, Any]]] = {
        "start": [],
        "bench": [],
        "reserve": [],
    }
    for row in roster or []:
        if not isinstance(row, dict) or not (row.get("name") or "").strip():
            continue
        st = str(row.get("status") or "reserve").strip().lower()
        if st not in by_status:
            st = "reserve"
        by_status[st].append(dict(row))

    start: list[dict[str, Any]] = []
    assigned: set[str] = set()
    for slot in slots_tpl:
        sid = slot.slot_id
        picked = None
        for row in by_status["start"]:
            ls = str(row.get("lineup_slot") or row.get("slot") or "").strip().upper()
            nm = str(row.get("name") or "").strip().casefold()
            if nm in assigned:
                continue
            if ls == sid:
                picked = row
                break
        if picked is None:
            for row in by_status["start"]:
                nm = str(row.get("name") or "").strip().casefold()
                if nm and nm not in assigned:
                    picked = row
                    break
        if picked:
            assigned.add(str(picked.get("name") or "").strip().casefold())
            pl = _app_player_from_wc(picked, canon)
            pl["slot"] = sid
            pl["x"] = slot.x
            pl["y"] = slot.y
            start.append(pl)
        else:
            start.append(
                {
                    **_EMPTY_SLOT,
                    "slot": sid,
                    "x": slot.x,
                    "y": slot.y,
                }
            )

    bench: list[dict[str, Any]] = []
    for row in by_status["bench"][:_WC_BENCH]:
        bench.append(_app_player_from_wc(row, canon))
    while len(bench) < _WC_BENCH:
        bench.append({**_EMPTY_SLOT})

    reserve: list[dict[str, Any]] = []
    for row in by_status["reserve"][:_WC_RESERVE]:
        reserve.append(_app_player_from_wc(row, canon))
    while len(reserve) < _WC_RESERVE:
        reserve.append({**_EMPTY_SLOT})

    ovrs = [int(s["overall"]) for s in start if s.get("overall")]
    avg = round(sum(ovrs) / len(ovrs), 1) if ovrs else 0.0
    all_ids = [x["id"] for x in start + bench + reserve if x.get("id")]

    return {
        "name": canon,
        "league": "Сборная",
        "caption": caption,
        "coach": coach_s,
        "formation": caption,
        "formation_id": fid,
        "avg_start": avg,
        "start": start,
        "bench": bench,
        "reserve": reserve,
        "baseline_ids": all_ids,
        "season": int(season if season is not None else season_paths.get_active_season()),
    }


def wc_roster_from_nation_team(team: dict[str, Any]) -> list[dict[str, Any]]:
    """Заявка одной сборной для world_cup_squads.json."""
    nation = str(team.get("name") or "").strip()
    out: list[dict[str, Any]] = []

    def _append(zone: str, players: list[dict], *, with_slot: bool) -> None:
        for p in players or []:
            if not p or not p.get("name"):
                continue
            row = {
                "name": str(p.get("name") or "").strip(),
                "club": _player_club(p.get("id"), p),
                "position": str(p.get("position") or "").strip().upper(),
                "overall": int(p.get("overall") or 0),
                "status": zone,
                "source": "callup",
            }
            if p.get("person_id") is not None:
                row["person_id"] = p.get("person_id")
            if with_slot and p.get("slot"):
                row["lineup_slot"] = str(p["slot"]).strip().upper()
            out.append(row)

    _append("start", team.get("start") or [], with_slot=True)
    _append("bench", team.get("bench") or [], with_slot=False)
    _append("reserve", team.get("reserve") or [], with_slot=False)
    _ = nation
    return out


def nation_meta_from_teams(teams: list[dict]) -> dict[str, dict[str, Any]]:
    meta: dict[str, dict[str, Any]] = {}
    for team in teams or []:
        name = str(team.get("name") or "").strip()
        if not name:
            continue
        meta[name] = {
            "coach": str(team.get("coach") or "").strip(),
            "formation_id": int(team.get("formation_id") or 1),
        }
    return meta


def apply_nation_teams_to_wc_squads(teams: list[dict], *, save: bool = True) -> dict[str, Any]:
    """Записать заявки сборных из transfer app в world_cup_squads.json."""
    from utils import season_paths

    data = load_wc_squads()
    wc_teams = data.setdefault("teams", {})
    meta = data.setdefault("meta", {})
    if not isinstance(meta, dict):
        meta = {}
        data["meta"] = meta
    count = 0
    for team in teams or []:
        name = str(team.get("name") or "").strip()
        canon = resolve_nation_name(name) or name
        if not canon:
            continue
        roster = wc_roster_from_nation_team(team)
        if roster:
            wc_teams[canon] = roster
            count += 1
        meta[canon] = {
            "coach": str(team.get("coach") or "").strip(),
            "formation_id": int(team.get("formation_id") or 1),
        }
    data["season"] = season_paths.get_active_season()
    if save:
        save_wc_squads(data)
    return {"nations": count, "players": sum(len(v) for v in wc_teams.values() if isinstance(v, list))}


def format_wc_squads_export_txt(teams: list[dict]) -> str:
    lines: list[str] = []
    for team in teams or []:
        name = team.get("name") or "?"
        fid = int(team.get("formation_id") or 1)
        coach = str(team.get("coach") or "").strip()
        lines.append(f"@{name}")
        if coach:
            lines.append(f"coach: {coach}")
        lines.append(f"formation_id: {fid}")
        lines.append("==== start ===")
        for s in team.get("start") or []:
            if s.get("name"):
                slot = s.get("slot") or ""
                club = _player_club(s.get("id"), s)
                lines.append(
                    f"{s['name']} {slot} {s['position']} {s['overall']}  {club}".strip()
                )
        lines.append("=== bench ===")
        for p in team.get("bench") or []:
            if p.get("name"):
                club = _player_club(p.get("id"), p)
                lines.append(f"{p['name']} {p['position']} {p['overall']}  {club}")
        lines.append("=== reserve ===")
        for p in team.get("reserve") or []:
            if p.get("name"):
                club = _player_club(p.get("id"), p)
                lines.append(f"{p['name']} {p['position']} {p['overall']}  {club}")
        lines.append("")
    return "\n".join(lines).rstrip() + "\n"


_TEAM_HDR = re.compile(r"^@(.+)$")
_COACH_RE = re.compile(r"^coach:\s*(.+)$", re.I)
_FID_RE = re.compile(r"^formation_id:\s*(\d+)$", re.I)
_SECTION_RE = re.compile(r"^====?\s*(start|bench|reserve)\s*====?$", re.I)
_PLAYER_START = re.compile(
    r"^(.+?)\s+([A-Za-z]{2,4})\s+(\S+)\s+(\d+)\s*(.*)$", re.UNICODE
)
_PLAYER_LINE = re.compile(r"^(.+?)\s+(\S+)\s+(\d+)\s*(.*)$", re.UNICODE)


def parse_wc_squads_export_txt(text: str) -> list[dict[str, Any]]:
    """Разбор wc_squads_export.txt → список team-объектов transfer app."""
    teams: list[dict[str, Any]] = []
    cur_name: str | None = None
    cur_coach = ""
    cur_fid = 1
    cur_zone = ""
    start_rows: list[dict] = []
    bench_rows: list[dict] = []
    reserve_rows: list[dict] = []

    def _flush() -> None:
        nonlocal cur_name, cur_coach, cur_fid, start_rows, bench_rows, reserve_rows
        if not cur_name:
            return
        roster: list[dict[str, Any]] = []
        for row in start_rows:
            r = dict(row)
            r["status"] = "start"
            if r.get("slot"):
                r["lineup_slot"] = r["slot"]
            roster.append(r)
        for row in bench_rows:
            r = dict(row)
            r["status"] = "bench"
            roster.append(r)
        for row in reserve_rows:
            r = dict(row)
            r["status"] = "reserve"
            roster.append(r)
        teams.append(
            nation_team_template(
                cur_name,
                formation_id=cur_fid,
                coach=cur_coach,
                roster=roster,
            )
        )
        cur_name = None
        cur_coach = ""
        cur_fid = 1
        start_rows = []
        bench_rows = []
        reserve_rows = []

    for raw in (text or "").splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        m = _TEAM_HDR.match(line)
        if m:
            _flush()
            cur_name = m.group(1).strip()
            continue
        m = _COACH_RE.match(line)
        if m:
            cur_coach = m.group(1).strip()
            continue
        m = _FID_RE.match(line)
        if m:
            cur_fid = int(m.group(1))
            continue
        m = _SECTION_RE.match(line)
        if m:
            cur_zone = m.group(1).lower()
            continue
        if cur_zone == "start":
            m = _PLAYER_START.match(line)
            if not m:
                continue
            name, slot, pos, ovr, tail = m.groups()
            club = (tail or "").strip() or "Free Agent"
            start_rows.append(
                {
                    "name": name.strip(),
                    "slot": slot.strip().upper(),
                    "lineup_slot": slot.strip().upper(),
                    "position": pos.strip().upper(),
                    "overall": int(ovr),
                    "club": club,
                }
            )
        elif cur_zone in ("bench", "reserve"):
            m = _PLAYER_LINE.match(line)
            if not m:
                continue
            name, pos, ovr, tail = m.groups()
            club = (tail or "").strip() or "Free Agent"
            row = {
                "name": name.strip(),
                "position": pos.strip().upper(),
                "overall": int(ovr),
                "club": club,
            }
            if cur_zone == "bench":
                bench_rows.append(row)
            else:
                reserve_rows.append(row)
    _flush()
    return teams


def import_wc_squads_export_txt(text: str, *, apply_db: bool = True) -> dict[str, Any]:
    teams = parse_wc_squads_export_txt(text)
    if not teams:
        raise ValueError("Не найдено ни одной сборной (@Нация …)")
    stats = apply_nation_teams_to_wc_squads(teams, save=apply_db)
    stats["teams_parsed"] = len(teams)
    return stats
