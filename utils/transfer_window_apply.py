# -*- coding: utf-8 -*-
"""Применение выгрузки трансферного окна к БД сезона (бот + scripts)."""
from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


def strip_transfers_appendix(text: str) -> str:
    """Убрать хвост ``=== transfers ===`` из экспорта составов."""
    m = re.search(r"(?im)^===\s*transfers\s*===", text)
    if m:
        return text[: m.start()].rstrip() + "\n"
    return text


def parse_transfers_text(text: str) -> list[dict[str, Any]]:
    """
    ``transfers_export*.txt`` (TSV) или ``transfers_simple*.txt``.
    """
    lines = [ln.strip() for ln in (text or "").splitlines() if ln.strip()]
    if not lines:
        return []
    header = lines[0].lower()
    rows: list[dict[str, Any]] = []
    if "клуб (из)" in header or "команда (из)" in header:
        for ln in lines[1:]:
            parts = ln.split("\t")
            if len(parts) < 5:
                continue
            name, pos, ovr_s, frm, to = parts[0], parts[1], parts[2], parts[3], parts[4]
            try:
                ovr = int(ovr_s)
            except (TypeError, ValueError):
                ovr = 0
            rows.append(
                {
                    "name": name.strip(),
                    "position": pos.strip(),
                    "overall": ovr,
                    "from_team": frm.strip(),
                    "to_team": to.strip(),
                    "status": "bench",
                }
            )
        return rows
    if header.startswith("игрок") and "из" in header:
        for ln in lines[1:]:
            parts = ln.split("\t")
            if len(parts) < 3:
                continue
            rows.append(
                {
                    "name": parts[0].strip(),
                    "position": "",
                    "overall": 0,
                    "from_team": parts[1].strip(),
                    "to_team": parts[2].strip(),
                    "status": "bench",
                }
            )
        return rows
    raise ValueError(
        "Не разобрал файл трансферов: нужен TSV из приложения "
        "(transfers_export_*.txt или transfers_simple_*.txt)."
    )


def _transfers_from_state_dict(data: dict[str, Any]) -> list[dict[str, Any]]:
    direct = list(data.get("transfers") or [])
    if direct:
        return direct
    baseline_home: dict[str, str] = dict(data.get("baseline_home") or {})
    removed = set((data.get("removed_from_squad") or {}).keys())
    teams = list(data.get("teams") or [])
    loc: dict[str, tuple[str, str, dict]] = {}
    for team in teams:
        tname = str(team.get("name") or "")
        for zone in ("start", "bench", "reserve"):
            for p in team.get(zone) or []:
                if p and p.get("id") and p.get("name"):
                    loc[str(p["id"])] = (tname, zone, dict(p))
    for p in data.get("free_agents") or []:
        if p and p.get("id") and p.get("name"):
            st = (p.get("status") or "bench") or "bench"
            loc[str(p["id"])] = ("Free Agent", st, dict(p))
    rows: list[dict[str, Any]] = []
    for pid, from_team in sorted(baseline_home.items(), key=lambda x: x[1]):
        if pid in removed:
            continue
        if pid not in loc:
            continue
        to_team, status, p = loc[pid]
        if to_team == from_team:
            continue
        parts = str(pid).split("|")
        rows.append(
            {
                "name": p.get("name") or parts[1] if len(parts) >= 2 else pid,
                "position": p.get("position") or (parts[2] if len(parts) >= 3 else ""),
                "overall": int(p.get("overall") or 0),
                "from_team": from_team,
                "to_team": to_team,
                "status": status,
            }
        )
    rows.sort(key=lambda r: (r["to_team"], -int(r.get("overall") or 0), r["name"]))
    return rows


def parse_transfers_json(text: str) -> tuple[list[dict[str, Any]], list[dict[str, Any]] | None]:
    data = json.loads(text or "{}")
    if not isinstance(data, dict):
        raise ValueError("JSON трансферов: ожидается объект.")
    transfers = _transfers_from_state_dict(data)
    teams = data.get("teams")
    return transfers, teams if isinstance(teams, list) else None


def parse_transfers_file(content: str, filename: str) -> tuple[list[dict[str, Any]], list[dict[str, Any]] | None]:
    fn = (filename or "").lower()
    if fn.endswith(".json"):
        return parse_transfers_json(content)
    return parse_transfers_text(content), None


@dataclass
class TransferApplyResult:
    transfers_ok: int = 0
    squads_ok: int = 0
    formations_ok: int = 0
    errors: list[str] = field(default_factory=list)
    lines: list[str] = field(default_factory=list)


def apply_transfers(transfers: list[dict[str, Any]], *, dry_run: bool = False) -> int:
    from utils.free_agents_db import is_free_agent_team
    from utils.player_transfer import apply_transfer_with_status, normalize_player_name_for_db
    from utils.roster_manual import FREE_AGENT_TEAM
    from utils.transfer_input import normalize_position, resolve_team_name
    from utils.utils import session_league

    n_ok = 0
    for t in transfers:
        name = normalize_player_name_for_db(str(t.get("name") or ""))
        pos = normalize_position(str(t.get("position") or ""))
        frm_raw = str(t.get("from_team") or "")
        if is_free_agent_team(frm_raw):
            frm = FREE_AGENT_TEAM
        else:
            frm = resolve_team_name(frm_raw, session_league) or frm_raw
        to_raw = str(t.get("to_team") or "")
        if is_free_agent_team(to_raw):
            to = FREE_AGENT_TEAM
        else:
            to = resolve_team_name(to_raw, session_league) or to_raw
        if not pos:
            from player_stats import find_player_by_name, get_session

            pl, _ = find_player_by_name(get_session(session_league), name, frm)
            if pl is None:
                raise ValueError(f"Нет позиции для {name} ({frm} → {to}) — укажи в transfers_export.")
            pos = str(pl.position or "").strip()
        if not pos:
            raise ValueError(f"Нет позиции у трансфера: {name}")
        st = (t.get("status") or "bench")
        st = str(st).strip().lower() if st else None
        if st not in ("start", "bench", "reserve"):
            st = "bench"
        ovr = t.get("overall")
        ovr_i = int(ovr) if ovr else None
        if dry_run:
            n_ok += 1
            continue
        apply_transfer_with_status(
            name,
            frm,
            pos,
            to,
            st,
            rebuild_common=False,
            mirror_synced=False,
            new_overall=ovr_i if ovr_i else None,
        )
        n_ok += 1
    return n_ok


def apply_squads_text(text: str, *, dry_run: bool = False, mirror_synced: bool = True) -> int:
    from scripts.apply_bulk_squad_declarations import resolve_team_label, split_bulk_blocks
    from utils.roster_manual import apply_team_squad_declaration, parse_squad_declaration_text

    body = strip_transfers_appendix(text)
    blocks = split_bulk_blocks(body)
    n = 0
    for team_raw, block in blocks:
        team = resolve_team_label(team_raw)
        entries, errors = parse_squad_declaration_text(block)
        if errors:
            raise ValueError(f"Разбор заявки {team}: {errors[0]}")
        if dry_run:
            n += 1
            continue
        apply_team_squad_declaration(team, entries, mirror_synced=mirror_synced)
        n += 1
    return n


def apply_formations(teams: list[dict[str, Any]], *, dry_run: bool = False) -> int:
    from coach_squad_state import get_coach_id_for_team, set_active_formation_id

    n = 0
    for t in teams:
        name = str(t.get("name") or "").strip()
        fid = t.get("formation_id")
        if not name or fid is None:
            continue
        cid = get_coach_id_for_team(name)
        if not cid:
            continue
        if not dry_run:
            set_active_formation_id(cid, int(fid))
        n += 1
    return n


def apply_transfer_window_upload(
    *,
    squads_text: str,
    transfers_content: str,
    transfers_filename: str,
    dry_run: bool = False,
) -> TransferApplyResult:
    res = TransferApplyResult()
    transfers, teams_from_json = parse_transfers_file(transfers_content, transfers_filename)
    res.lines.append(f"Трансферов в файле: {len(transfers)}")
    if not dry_run and transfers:
        res.transfers_ok = apply_transfers(transfers, dry_run=False)
        from utils.common_db import rebuild_common_database

        rebuild_common_database()
        res.lines.append(f"✓ Трансферы: {res.transfers_ok}")
    elif dry_run:
        res.transfers_ok = len(transfers)
        res.lines.append(f"(dry-run) трансферов: {len(transfers)}")

    squad_blocks = strip_transfers_appendix(squads_text)
    if "@" not in squad_blocks and "==== start ===" not in squad_blocks.lower():
        raise ValueError(
            "Файл составов не похож на squads_export_*.txt (@Клуб, секции start/bench/reserve)."
        )
    if not dry_run:
        res.squads_ok = apply_squads_text(squads_text, dry_run=False, mirror_synced=False)
        res.lines.append(f"✓ Заявки клубов: {res.squads_ok}")
    else:
        from scripts.apply_bulk_squad_declarations import split_bulk_blocks

        res.squads_ok = len(split_bulk_blocks(strip_transfers_appendix(squads_text)))
        res.lines.append(f"(dry-run) клубов в заявках: {res.squads_ok}")

    if teams_from_json:
        if not dry_run:
            res.formations_ok = apply_formations(teams_from_json, dry_run=False)
        else:
            res.formations_ok = sum(
                1 for t in teams_from_json if t.get("formation_id") is not None
            )
        if res.formations_ok:
            res.lines.append(f"✓ Схемы тренеров: {res.formations_ok}")

    return res


def apply_from_paths(
    *,
    squads_path: Path,
    transfers_path: Path,
    dry_run: bool = False,
) -> TransferApplyResult:
    squads_text = squads_path.read_text(encoding="utf-8")
    transfers_content = transfers_path.read_text(encoding="utf-8")
    return apply_transfer_window_upload(
        squads_text=squads_text,
        transfers_content=transfers_content,
        transfers_filename=transfers_path.name,
        dry_run=dry_run,
    )
