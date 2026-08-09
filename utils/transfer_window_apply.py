# -*- coding: utf-8 -*-
"""Применение выгрузки трансферного окна к БД сезона (бот + scripts)."""
from __future__ import annotations

import json
import re
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Optional

# done, total, phase_label, detail, phase_done, phase_total
ApplyProgressCallback = Callable[[int, int, str, Optional[str], int, int], None]


def _report_progress(
    on_progress: ApplyProgressCallback | None,
    *,
    done: int,
    total: int,
    phase: str,
    detail: Optional[str] = None,
    phase_done: int = 0,
    phase_total: int = 0,
) -> None:
    if on_progress and total > 0:
        on_progress(done, total, phase, detail, phase_done, phase_total)


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
        transfers, teams = parse_transfers_json(content)
    else:
        transfers, teams = parse_transfers_text(content), None
    return _dedupe_transfer_rows(list(transfers)), teams


def _dedupe_transfer_rows(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Один (имя, позиция, куда) — один трансфер; предпочитаем id, согласованный с from_team."""
    best: dict[tuple[str, str, str], dict[str, Any]] = {}

    def _score(row: dict[str, Any]) -> tuple[int, int]:
        rid = str(row.get("id") or "")
        parts = rid.split("|")
        id_home = parts[0].strip() if parts else ""
        from_team = str(row.get("from_team") or "").strip()
        pts = 0
        if id_home and id_home.casefold() == from_team.casefold():
            pts += 10
        try:
            ovr = int(row.get("overall") or 0)
        except (TypeError, ValueError):
            ovr = 0
        return pts, ovr

    for row in rows or []:
        key = (
            str(row.get("name") or "").strip().casefold(),
            str(row.get("position") or "").strip().upper(),
            str(row.get("to_team") or "").strip().casefold(),
        )
        prev = best.get(key)
        if prev is None or _score(row) > _score(prev):
            best[key] = row
    out = list(best.values())
    out.sort(
        key=lambda r: (
            str(r.get("to_team") or ""),
            -int(r.get("overall") or 0),
            str(r.get("name") or ""),
        )
    )
    return out


@dataclass
class TransferApplyResult:
    transfers_ok: int = 0
    squads_ok: int = 0
    squads_skipped: int = 0
    formations_ok: int = 0
    errors: list[str] = field(default_factory=list)
    lines: list[str] = field(default_factory=list)


def apply_transfers(
    transfers: list[dict[str, Any]],
    *,
    dry_run: bool = False,
    on_progress: ApplyProgressCallback | None = None,
    progress_base: int = 0,
    progress_total: int = 0,
) -> int:
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
        if on_progress and progress_total > 0:
            detail = f"{name} → {to}"
            _report_progress(
                on_progress,
                done=progress_base + n_ok,
                total=progress_total,
                phase="Трансферы",
                detail=detail,
                phase_done=n_ok,
                phase_total=len(transfers),
            )
    return n_ok


def apply_squads_text(
    text: str,
    *,
    dry_run: bool = False,
    mirror_synced: bool = True,
    rebuild_common: bool = True,
    on_progress: ApplyProgressCallback | None = None,
    progress_base: int = 0,
    progress_total: int = 0,
) -> tuple[int, int]:
    from scripts.apply_bulk_squad_declarations import resolve_team_label, split_bulk_blocks
    from utils.roster_manual import (
        apply_team_squad_declaration,
        parse_squad_declaration_text,
        team_squad_matches_declaration,
    )

    body = strip_transfers_appendix(text)
    blocks = split_bulk_blocks(body)
    applied = 0
    skipped = 0
    step = 0
    for team_raw, block in blocks:
        team = resolve_team_label(team_raw)
        entries, errors = parse_squad_declaration_text(block)
        if errors:
            raise ValueError(f"Разбор заявки {team}: {errors[0]}")
        if not dry_run and team_squad_matches_declaration(team, entries):
            skipped += 1
            step += 1
            if on_progress and progress_total > 0:
                _report_progress(
                    on_progress,
                    done=progress_base + step,
                    total=progress_total,
                    phase="Составы",
                    detail=f"{team} · без изменений",
                    phase_done=step,
                    phase_total=len(blocks),
                )
            continue
        if dry_run:
            applied += 1
            step += 1
            continue
        apply_team_squad_declaration(
            team,
            entries,
            mirror_synced=mirror_synced,
            rebuild_common=rebuild_common,
        )
        applied += 1
        step += 1
        if on_progress and progress_total > 0:
            _report_progress(
                on_progress,
                done=progress_base + step,
                total=progress_total,
                phase="Составы",
                detail=team,
                phase_done=step,
                phase_total=len(blocks),
            )
    return applied, skipped


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


def _count_formation_updates(teams: list[dict[str, Any]] | None) -> int:
    if not teams:
        return 0
    from coach_squad_state import get_coach_id_for_team

    n = 0
    for t in teams:
        name = str(t.get("name") or "").strip()
        fid = t.get("formation_id")
        if not name or fid is None:
            continue
        if get_coach_id_for_team(name):
            n += 1
    return n


def apply_transfer_window_upload(
    *,
    squads_text: str,
    transfers_content: str,
    transfers_filename: str,
    dry_run: bool = False,
    on_progress: ApplyProgressCallback | None = None,
) -> TransferApplyResult:
    from scripts.apply_bulk_squad_declarations import split_bulk_blocks

    res = TransferApplyResult()
    transfers, teams_from_json = parse_transfers_file(transfers_content, transfers_filename)
    res.lines.append(f"Трансферов в файле: {len(transfers)}")

    squad_body = strip_transfers_appendix(squads_text)
    n_squads = len(split_bulk_blocks(squad_body)) if "@" in squad_body else 0
    n_form = _count_formation_updates(teams_from_json) if not dry_run else 0
    rebuild_step = 0 if dry_run else int(bool(transfers or n_squads))
    progress_total = len(transfers) + n_squads + rebuild_step + n_form
    progress_done = 0

    if on_progress and progress_total > 0:
        _report_progress(on_progress, done=0, total=progress_total, phase="Старт")

    if dry_run:
        res.transfers_ok = len(transfers)
        res.lines.append(f"(dry-run) трансферов: {len(transfers)}")
    elif transfers:
        res.transfers_ok = apply_transfers(
            transfers,
            dry_run=False,
            on_progress=on_progress,
            progress_base=progress_done,
            progress_total=progress_total,
        )
        progress_done += res.transfers_ok
        res.lines.append(f"✓ Трансферы: {res.transfers_ok}")

    if "@" not in squad_body and "==== start ===" not in squad_body.lower():
        raise ValueError(
            "Файл составов не похож на squads_export_*.txt (@Клуб, секции start/bench/reserve)."
        )
    if dry_run:
        res.squads_ok = n_squads
        res.lines.append(f"(dry-run) клубов в заявках: {res.squads_ok}")
    else:
        squads_applied, squads_skipped = apply_squads_text(
            squads_text,
            dry_run=False,
            mirror_synced=False,
            rebuild_common=False,
            on_progress=on_progress,
            progress_base=progress_done,
            progress_total=progress_total,
        )
        res.squads_ok = squads_applied
        res.squads_skipped = squads_skipped
        progress_done += squads_applied + squads_skipped
        if squads_skipped:
            res.lines.append(
                f"✓ Заявки клубов: {squads_applied} "
                f"(пропущено готовых: {squads_skipped})"
            )
        else:
            res.lines.append(f"✓ Заявки клубов: {squads_applied}")

    if not dry_run and rebuild_step:
        if on_progress and progress_total > 0:
            _report_progress(
                on_progress,
                done=progress_done,
                total=progress_total,
                phase="common.db",
                detail="пересборка (1–3 мин)",
                phase_done=0,
                phase_total=1,
            )
        from utils.common_db import rebuild_common_database

        rebuild_common_database()
        progress_done += 1
        if on_progress and progress_total > 0:
            _report_progress(
                on_progress,
                done=progress_done,
                total=progress_total,
                phase="common.db",
                phase_done=1,
                phase_total=1,
            )
        res.lines.append("✓ common.db пересобрана (один раз)")

    if teams_from_json:
        if not dry_run:
            for t in teams_from_json:
                name = str(t.get("name") or "").strip()
                fid = t.get("formation_id")
                if not name or fid is None:
                    continue
                from coach_squad_state import get_coach_id_for_team, set_active_formation_id

                cid = get_coach_id_for_team(name)
                if not cid:
                    continue
                set_active_formation_id(cid, int(fid))
                res.formations_ok += 1
                progress_done += 1
                if on_progress and progress_total > 0:
                    _report_progress(
                        on_progress,
                        done=progress_done,
                        total=progress_total,
                        phase="Схемы",
                        detail=name,
                        phase_done=res.formations_ok,
                        phase_total=n_form,
                    )
        else:
            res.formations_ok = sum(
                1 for t in teams_from_json if t.get("formation_id") is not None
            )
        if res.formations_ok:
            res.lines.append(f"✓ Схемы тренеров: {res.formations_ok}")

    if on_progress and progress_total > 0:
        _report_progress(
            on_progress,
            done=progress_total,
            total=progress_total,
            phase="Готово",
            phase_done=progress_total,
            phase_total=progress_total,
        )

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
