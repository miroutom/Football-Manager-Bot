#!/usr/bin/env python3
"""Превью: 15 матчей м3–м5 — лига/ЛЧ, журнал, что пойдёт в БД (без записи)."""
from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from utils.team_country import country_code_for_team, same_country
from utils.transfer_input import resolve_team_name
from utils.utils import session_league

MATCHES = [
    ("Атлетик", "Лейпциг", 1, 1, 3),
    ("Атлетик", "Дортмунд", 0, 2, 3),
    ("Реал", "Франкфурт", 3, 2, 3),
    ("Дортмунд", "Сити", 1, 2, 4),
    ("Интер", "Барселона", 0, 3, 4),
    ("Атлетик", "Динамо", 2, 4, 4),
    ("Зенит", "Севилья", 2, 1, 4),
    ("Реал", "Вольфсбург", 1, 1, 4),
    ("Цска", "Фиорентина", 2, 4, 4),
    ("Наполи", "Ливерпуль", 1, 3, 4),
    ("Севилья", "Лейпциг", 1, 1, 5),
    ("Ювентус", "Арсенал", 1, 0, 5),
    ("Зенит", "Дортмунд", 0, 1, 5),
    ("Бавария", "Мю", 2, 1, 5),
    ("Атлетик", "Сити", 1, 3, 5),
]

COUNTRY = {"rpl": "Россия", "eng": "Англия", "esp": "Испания", "ita": "Италия", "ger": "Германия"}


def _norm(s: str) -> str:
    return (s or "").strip().casefold()


def _find_journal(home: str, away: str, hs: int, aws: int, day: int) -> dict | None:
    p = ROOT / "match_results.json"
    raw = json.loads(p.read_text(encoding="utf-8"))
    recs = raw.get("matches") or []
    for r in recs:
        if _norm(r.get("home")) != _norm(home) or _norm(r.get("away")) != _norm(away):
            continue
        if int(r.get("day") or 0) != day:
            continue
        r_hs, r_aws = r.get("home_score"), r.get("away_score")
        if r_hs is None or r_aws is None:
            continue
        if int(r_hs) == hs and int(r_aws) == aws:
            return r
    return None


def resolve(h: str, a: str) -> tuple[str, str]:
    sleague = session_league
    rh = resolve_team_name(h, sleague) or h.strip().title()
    ra = resolve_team_name(a, sleague) or a.strip().title()
    return rh, ra


def main() -> None:
    out_lines: list[str] = []
    out_lines.append("# Превью: стата по 15 матчам (м3–м5)\n")
    out_lines.append("**Запись в БД не выполнялась** — только проверка.\n")

    for i, (h, a, hs, aws, month) in enumerate(MATCHES, 1):
        rh, ra = resolve(h, a)
        ch = country_code_for_team(rh)
        ca = country_code_for_team(ra)
        same = same_country(rh, ra)
        if same:
            tourn = "league"
            db = f"league.db ({COUNTRY.get(ch, ch)})"
            lc = ch or "?"
        else:
            tourn = "cl"
            db = "champions_league.db (ЛЧ)"
            lc = "cl"

        rec = _find_journal(rh, ra, hs, aws, month)
        journal = "✓ в журнале" if rec else "⚠ нет / другой счёт"
        if rec and (rec.get("home_score") != hs or rec.get("away_score") != aws):
            journal += f" (в журнале {rec.get('home_score')}:{rec.get('away_score')}, день {rec.get('day')})"

        out_lines.append(f"\n## {i}. м{month} · {rh} {hs}:{aws} {ra}\n")
        out_lines.append(f"- Страны: {COUNTRY.get(ch, '?')} — {COUNTRY.get(ca, '?')}\n")
        out_lines.append(f"- Тип: **{'лига (' + (ch or '?') + ')' if same else 'ЛЧ'}** → БД `{db}`\n")
        out_lines.append(f"- Журнал `match_results.json`: {journal}\n")
        out_lines.append(f"- `tournament` для статы: `{tourn}`\n")
        out_lines.append("- Строки игроков (голы/передачи): **не заданы в запросе** — нужны из скринов «Статистика игроков»\n")
        out_lines.append("```\n# пример формата (пока пусто):\n# Имя 2 1\n```\n")

    out_lines.append("\n---\n")
    out_lines.append("### Что будет сделано после подтверждения\n")
    out_lines.append("1. Матчи уже в журнале — **повторно счёт не пишем** (иначе «уже сыгран»).\n")
    out_lines.append("2. Для каждой строки игрока: `add_player_stats(..., tournament='cl'|'league', schedule_day=месяц)`.\n")
    out_lines.append("3. Пересборка `common.db` при необходимости.\n")
    out_lines.append("\n**Пришли текстом** голы/передачи по матчам (или один файл `scripts/stats_input_m3_m5.txt`), затем сделаю запись.\n")

    text = "".join(out_lines)
    path = ROOT / "scripts" / "STATS_PREVIEW_m3_m5.md"
    path.write_text(text, encoding="utf-8")
    print(text)
    print(f"\n(written {path})")


if __name__ == "__main__":
    main()
