# -*- coding: utf-8 -*-
"""Парсинг scripts/stats_from_screens_m3_m5.txt для dry-run / apply."""
from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DEFAULT_TXT = ROOT / "scripts" / "stats_from_screens_m3_m5.txt"

HEADER_NEW = re.compile(
    r"# === (м\d+) · (CL|league) · (.+?) (\d+):(\d+) (.+?) ===",
    re.IGNORECASE,
)
HEADER_OLD = re.compile(r"# === (м\d+) · (.+?) (\d+):(\d+) (.+?) ===")


def _month_num(label: str) -> int:
    return int(label.replace("м", ""))


def parse_stats_txt(path: Path | None = None) -> list[tuple[str, str, str, int, int, int, list[str]]]:
    """
    Возвращает список:
      (label, home, away, home_score, away_score, month, stat_lines)
    tournament определяется отдельно: cl / league.
    """
    text = (path or DEFAULT_TXT).read_text(encoding="utf-8")
    blocks: list[tuple[str, str, str, int, int, int, list[str]]] = []
    cur: tuple[str, str, str, int, int, int, list[str]] | None = None

    for raw_line in text.splitlines():
        line = raw_line.strip()
        if not line:
            continue
        m = HEADER_NEW.match(line)
        if m:
            if cur:
                blocks.append(cur)
            label, _tourn, home, hs, aws, away = m.groups()
            cur = (label, home.strip(), away.strip(), int(hs), int(aws), _month_num(label), [])
            continue
        m = HEADER_OLD.match(line)
        if m:
            if cur:
                blocks.append(cur)
            label, home, hs, aws, away = m.groups()
            cur = (label, home.strip(), away.strip(), int(hs), int(aws), _month_num(label), [])
            continue
        if line.startswith("#"):
            continue
        if cur is not None:
            cur[-1].append(line)
    if cur:
        blocks.append(cur)
    return blocks


def tournament_for_header_line(line: str) -> str:
    m = HEADER_NEW.match(line.strip())
    if m:
        return "cl" if m.group(2).upper() == "CL" else "league"
    return "cl"


def blocks_with_tournament(
    path: Path | None = None,
) -> list[tuple[str, str, str, int, int, int, str, list[str]]]:
    """(label, home, away, hs, aws, month, tournament, stat_lines)."""
    text = (path or DEFAULT_TXT).read_text(encoding="utf-8")
    out: list[tuple[str, str, str, int, int, int, str, list[str]]] = []
    cur_tournament = "cl"
    cur_block: tuple[str, str, str, int, int, int, list[str]] | None = None

    for raw_line in text.splitlines():
        line = raw_line.strip()
        if not line:
            continue
        m = HEADER_NEW.match(line)
        if m:
            if cur_block:
                lb, h, a, hs, aws, mo, sl = cur_block
                out.append((lb, h, a, hs, aws, mo, cur_tournament, sl))
            cur_tournament = "cl" if m.group(2).upper() == "CL" else "league"
            label, _, home, hs, aws, away = m.groups()
            cur_block = (label, home.strip(), away.strip(), int(hs), int(aws), _month_num(label), [])
            continue
        m = HEADER_OLD.match(line)
        if m:
            if cur_block:
                lb, h, a, hs, aws, mo, sl = cur_block
                out.append((lb, h, a, hs, aws, mo, cur_tournament, sl))
            cur_tournament = "cl"
            label, home, hs, aws, away = m.groups()
            cur_block = (label, home.strip(), away.strip(), int(hs), int(aws), _month_num(label), [])
            continue
        if line.startswith("#"):
            continue
        if cur_block is not None:
            cur_block[-1].append(line)
    if cur_block:
        lb, h, a, hs, aws, mo, sl = cur_block
        out.append((lb, h, a, hs, aws, mo, cur_tournament, sl))
    return out
