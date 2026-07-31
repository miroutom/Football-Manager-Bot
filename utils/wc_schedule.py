# -*- coding: utf-8 -*-
"""
Календарь ЧМ: месяц 11 в ``mixed_schedule.json``.

Групповой этап: строки ``Home;Away;wc;group``.
Порядок: тур 1 → тур 2 → тур 3 (по 24 матча).
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from utils.schedule_by_months import MIXED_FILE
from utils.world_cup import WC_CALENDAR_MONTH, is_world_cup_season
from utils.world_cup_format import all_group_fixtures
from utils.wc_tournament import groups_drawn, load_tournament

_ROOT = Path(__file__).resolve().parent.parent


def _norm(s: str) -> str:
    return (s or "").strip().title()


def wc_group_line(home: str, away: str) -> str:
    return f"{_norm(home)};{_norm(away)};wc;group"


def _is_wc_line(line: str) -> bool:
    parts = [x.strip() for x in (line or "").split(";")]
    return len(parts) >= 3 and parts[2].lower() == "wc"


def _load_mixed(path: Path) -> dict[str, Any]:
    with open(path, encoding="utf-8") as f:
        raw = json.load(f)
    if not isinstance(raw, dict):
        raise ValueError("mixed_schedule: ожидался объект v3")
    return raw


def _save_mixed(doc: dict[str, Any], path: Path) -> None:
    tmp = path.with_suffix(path.suffix + ".tmp")
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(doc, f, ensure_ascii=False, indent=2)
        f.write("\n")
    tmp.replace(path)


def _month_block(doc: dict[str, Any], month: int) -> dict[str, Any]:
    rounds = doc.setdefault("rounds", [])
    if not isinstance(rounds, list):
        raise ValueError("Некорректный mixed_schedule.rounds")
    for b in rounds:
        if isinstance(b, dict) and int(b.get("day") or 0) == month:
            return b
    block = {"day": month, "matches": []}
    rounds.append(block)
    rounds.sort(key=lambda x: int(x.get("day") or 0))
    return block


def group_stage_lines_ordered(groups: dict[str, list[str]] | None = None) -> list[str]:
    """72 строки группового этапа: сначала все матчи тура 1, затем 2, затем 3."""
    if groups is None:
        data = load_tournament()
        groups = data.get("groups") or {}
    fx = all_group_fixtures(groups)
    # стабильный порядок: round, group, home
    fx_sorted = sorted(
        fx,
        key=lambda m: (int(m.get("round") or 0), str(m.get("group") or ""), str(m.get("home") or "")),
    )
    return [wc_group_line(m["home"], m["away"]) for m in fx_sorted]


def ensure_wc_group_stage_in_schedule(
    *,
    path: Path | str | None = None,
    replace_existing: bool = False,
) -> tuple[bool, str]:
    """
    Идемпотентно добавить групповые матчи ЧМ в месяц 11.
    ``replace_existing=True`` — убрать старые ``;wc`` в месяце 11 и записать заново.
    """
    if not is_world_cup_season():
        return False, "Сейчас не сезон ЧМ — месяц 11 не трогаем."
    if not groups_drawn():
        return False, "Сначала проведите жеребьёвку групп ЧМ."

    p = Path(path) if path else MIXED_FILE
    if not p.is_file():
        return False, f"Нет файла календаря: {p}"

    lines = group_stage_lines_ordered()
    if len(lines) != 72:
        return False, f"Ожидалось 72 матча группы, получилось {len(lines)}."

    doc = _load_mixed(p)
    block = _month_block(doc, WC_CALENDAR_MONTH)
    existing = list(block.get("matches") or [])
    non_wc = [ln for ln in existing if isinstance(ln, str) and not _is_wc_line(ln)]
    wc_existing = [ln for ln in existing if isinstance(ln, str) and _is_wc_line(ln)]

    if not replace_existing and len(wc_existing) >= 72:
        # уже есть полный набор
        have = {(ln.split(";")[0].strip().title(), ln.split(";")[1].strip().title()) for ln in wc_existing if ln.count(";") >= 2}
        need = {(_norm(ln.split(";")[0]), _norm(ln.split(";")[1])) for ln in lines}
        if need <= have:
            return False, f"Месяц {WC_CALENDAR_MONTH}: групповой этап ЧМ уже в календаре ({len(wc_existing)} матчей)."

    if replace_existing:
        block["matches"] = non_wc + lines
        n = len(lines)
    else:
        have_keys = set()
        for ln in wc_existing:
            parts = ln.split(";")
            if len(parts) >= 2:
                have_keys.add((_norm(parts[0]), _norm(parts[1])))
        missing = []
        for ln in lines:
            parts = ln.split(";")
            key = (_norm(parts[0]), _norm(parts[1]))
            if key not in have_keys:
                missing.append(ln)
                have_keys.add(key)
        if not missing:
            return False, f"Месяц {WC_CALENDAR_MONTH}: все матчи группы уже есть."
        block["matches"] = non_wc + wc_existing + missing
        n = len(missing)

    _save_mixed(doc, p)
    return True, (
        f"В календарь (месяц {WC_CALENDAR_MONTH}) добавлены матчи ЧМ · группа: "
        f"<b>{n}</b> шт. (всего wc в месяце: {sum(1 for x in block['matches'] if _is_wc_line(x))})."
    )


def strip_wc_lines_month11(*, path: Path | str | None = None) -> int:
    """Удалить все строки ``;wc`` из месяца 11. Возвращает число удалённых."""
    p = Path(path) if path else MIXED_FILE
    doc = _load_mixed(p)
    block = _month_block(doc, WC_CALENDAR_MONTH)
    matches = list(block.get("matches") or [])
    keep = [ln for ln in matches if not (isinstance(ln, str) and _is_wc_line(ln))]
    removed = len(matches) - len(keep)
    if removed:
        block["matches"] = keep
        _save_mixed(doc, p)
    return removed


def month11_wc_summary() -> str:
    """Краткий статус месяца 11 для бота."""
    p = MIXED_FILE
    if not p.is_file():
        return "Календарь не найден."
    try:
        doc = _load_mixed(p)
    except (OSError, ValueError, json.JSONDecodeError):
        return "Календарь не читается."
    block = None
    for b in doc.get("rounds") or []:
        if isinstance(b, dict) and int(b.get("day") or 0) == WC_CALENDAR_MONTH:
            block = b
            break
    if not block:
        return f"Месяца {WC_CALENDAR_MONTH} в календаре ещё нет."
    matches = [ln for ln in (block.get("matches") or []) if isinstance(ln, str)]
    wc = [ln for ln in matches if _is_wc_line(ln)]
    other = len(matches) - len(wc)
    return (
        f"Месяц <b>{WC_CALENDAR_MONTH}</b>: матчей ЧМ — <b>{len(wc)}</b>"
        + (f", прочих — {other}" if other else "")
        + "."
    )
