# -*- coding: utf-8 -*-
"""
Черновик трансферного окна: анализ составов и рендер рекомендаций.

Не применяет переходы в БД — только отчёт для ручной оценки.
"""
from __future__ import annotations

import json
from collections import defaultdict
from dataclasses import dataclass, field
from pathlib import Path
from statistics import median
from typing import Any

from coach_squad_state import resolve_formation_key_for_team
from team_squad_schemas import get_slots_for_formation_key
from utils.team_registry import get_team, teams_in_league
from utils.team_strength import get_team_strength
from utils.transfer_advice import (
    VERDICT_NU,
    VERDICT_SO,
    VERDICT_SU,
    _BADGE_DEPTH,
    _min_depth_for_position,
    all_league_teams,
    collect_transfer_advice,
)
from player_stats import national_league_code_for_team

_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_DRAFT_PATH = _ROOT / "data" / "transfer_window_draft.json"

_LEAGUE_ORDER = ("rpl", "eng", "esp", "ita", "ger")
_LEAGUE_LABEL = {
    "rpl": "РПЛ",
    "eng": "АПЛ",
    "esp": "Ла Лига",
    "ita": "Серия А",
    "ger": "Бундеслига",
}

# Клубы вне игры (S2) — не участвуют в окне.
_EXCLUDED_TEAMS = frozenset(
    {
        "Фрайбург",
        "Штутгарт",
        "Торино",
        "Сассуоло",
        "Райо Вальекано",
        "Вильярреал",
        "Рубин",
        "Ростов",
        "Брайтон",
        "Фулхэм",
    }
)

# Топ-3 силы лиги — не цель для первого шага «повышения» из РПЛ 81+.
_APEX_RANK_IN_LEAGUE = 3


@dataclass(frozen=True)
class DraftMove:
    player: str
    position: str
    overall: int
    from_team: str
    to_team: str
    note: str = ""

    def as_dict(self) -> dict[str, Any]:
        return {
            "player": self.player,
            "position": self.position,
            "overall": self.overall,
            "from_team": self.from_team,
            "to_team": self.to_team,
            "note": self.note,
        }


@dataclass
class TeamSnapshot:
    team: str
    league: str
    strength: float
    median_ovr: float
    deficits: list[str] = field(default_factory=list)
    top_sell: list[str] = field(default_factory=list)
    rpl_stars: list[str] = field(default_factory=list)


def _league_rank(team: str, league_code: str) -> int:
    reg = teams_in_league(league_code, active_only=False)
    names = [t.name for t in reg] if reg else []
    if not names:
        return 99
    from utils.team_strength import get_teams_sorted_by_strength

    ranked = [t for t, _ in get_teams_sorted_by_strength(names, "league")]
    try:
        return ranked.index(team) + 1
    except ValueError:
        return 99


def analyze_teams(teams: list[str] | None = None) -> dict[str, TeamSnapshot]:
    """Снимок потребностей и кандидатов на продажу по каждому клубу."""
    out: dict[str, TeamSnapshot] = {}
    for t in teams or all_league_teams():
        if t in _EXCLUDED_TEAMS:
            continue
        canon, rows, err = collect_transfer_advice(t)
        if err:
            continue
        lc = national_league_code_for_team(canon) or "rpl"
        slots = get_slots_for_formation_key(resolve_formation_key_for_team(canon))
        by_pos: dict[str, list] = defaultdict(list)
        for r in rows:
            by_pos[r.position].append(r)

        deficits: list[str] = []
        for pos, plist in sorted(by_pos.items()):
            need = _min_depth_for_position(pos, slots)
            if len(plist) < need:
                deficits.append(f"{pos} {len(plist)}/{need}")

        su = [r for r in rows if r.verdict in (VERDICT_SU, VERDICT_NU)]
        su.sort(key=lambda r: (r.overall, -float(r.score or 0)))
        depth_so = [
            r
            for r in rows
            if r.verdict == VERDICT_SO and _BADGE_DEPTH in (r.badges or [])
        ]
        depth_so.sort(key=lambda r: -r.overall)

        top_sell: list[str] = []
        for r in su[:6]:
            tags = "".join(r.badges or []) or ",".join((r.reasons or [])[:3])
            top_sell.append(f"{r.overall} {r.position} {r.name} ({r.verdict}, {tags})")
        for r in depth_so[:2]:
            if len(top_sell) >= 8:
                break
            top_sell.append(f"{r.overall} {r.position} {r.name} (СО, З+)")

        rpl_stars: list[str] = []
        if lc == "rpl":
            for r in rows:
                if r.overall >= 81:
                    rpl_stars.append(
                        f"{r.overall} {r.position} {r.name} ({r.verdict})"
                    )

        ovrs = [int(r.overall) for r in rows if int(r.overall or 0) > 0]
        out[canon] = TeamSnapshot(
            team=canon,
            league=lc,
            strength=get_team_strength(canon),
            median_ovr=float(median(ovrs)) if ovrs else 0.0,
            deficits=deficits,
            top_sell=top_sell,
            rpl_stars=rpl_stars,
        )
    return out


def load_draft(path: Path | None = None) -> list[DraftMove]:
    p = path or DEFAULT_DRAFT_PATH
    raw = json.loads(p.read_text(encoding="utf-8"))
    moves = raw.get("moves") or []
    return [
        DraftMove(
            player=m["player"],
            position=m["position"],
            overall=int(m["overall"]),
            from_team=m["from_team"],
            to_team=m["to_team"],
            note=str(m.get("note") or ""),
        )
        for m in moves
    ]


def validate_draft(
    moves: list[DraftMove], teams: list[str] | None = None
) -> tuple[list[str], list[str]]:
    """Проверки черновика: уникальность игрока, 5 IN/OUT, позиции вратарей."""
    errors: list[str] = []
    warnings: list[str] = []
    pool = set(teams or all_league_teams()) - _EXCLUDED_TEAMS

    seen_players: dict[str, DraftMove] = {}
    out_count: dict[str, int] = defaultdict(int)
    in_count: dict[str, int] = defaultdict(int)
    gk_delta: dict[str, int] = defaultdict(int)

    for m in moves:
        if m.from_team not in pool:
            errors.append(f"Неизвестный клуб (from): {m.from_team}")
        if m.to_team not in pool:
            errors.append(f"Неизвестный клуб (to): {m.to_team}")
        if m.from_team == m.to_team:
            errors.append(f"Переход в тот же клуб: {m.player}")

        key = (m.player.strip().lower(), m.position.strip().upper())
        if key in seen_players:
            prev = seen_players[key]
            errors.append(
                f"Игрок {m.player} ({m.position}) уже в черновике: "
                f"{prev.from_team}→{prev.to_team} и {m.from_team}→{m.to_team}"
            )
        seen_players[key] = m

        out_count[m.from_team] += 1
        in_count[m.to_team] += 1
        if m.position == "ВРТ":
            gk_delta[m.from_team] -= 1
            gk_delta[m.to_team] += 1

    for t in sorted(pool, key=str.lower):
        oc, ic = out_count.get(t, 0), in_count.get(t, 0)
        if oc != 5:
            errors.append(f"{t}: OUT {oc}/5")
        if ic != 5:
            errors.append(f"{t}: IN {ic}/5")

    # Минимум 3 ВРТ после окна (по советам transfer_advice).
    for t in pool:
        canon, rows, err = collect_transfer_advice(t)
        if err:
            continue
        slots = get_slots_for_formation_key(resolve_formation_key_for_team(canon))
        gk_now = sum(1 for r in rows if r.position == "ВРТ")
        min_gk = _min_depth_for_position("ВРТ", slots)
        gk_after = gk_now + gk_delta.get(t, 0)
        if gk_after < min_gk:
            warnings.append(
                f"{t}: после окна ВРТ {gk_after} < {min_gk} "
                f"(сейчас {gk_now}, Δ{gk_delta.get(t, 0):+d})"
            )

    # РПЛ 81+ не должны оставаться в РПЛ (кроме вратарей на обмен).
    for m in moves:
        from_lc = national_league_code_for_team(m.from_team)
        to_lc = national_league_code_for_team(m.to_team)
        if (
            from_lc == "rpl"
            and m.overall >= 81
            and to_lc == "rpl"
            and m.position != "ВРТ"
        ):
            errors.append(
                f"РПЛ 81+ остаётся в РПЛ: {m.player} {m.overall} "
                f"{m.from_team}→{m.to_team}"
            )
        if from_lc == "rpl" and m.overall >= 81 and to_lc != "rpl":
            rank = _league_rank(m.to_team, to_lc or "")
            if rank <= _APEX_RANK_IN_LEAGUE:
                errors.append(
                    f"РПЛ 81+ сразу в топ-{ _APEX_RANK_IN_LEAGUE }: "
                    f"{m.player} → {m.to_team} (#{rank})"
                )

    return errors, warnings


def _team_moves_view(moves: list[DraftMove], team: str) -> tuple[list[str], list[str]]:
    outs: list[str] = []
    ins: list[str] = []
    for m in moves:
        tag = f"{m.overall} {m.position} {m.player}"
        if m.note:
            tag += f" — {m.note}"
        if m.from_team == team:
            outs.append(f"{tag} → **{m.to_team}**")
        if m.to_team == team:
            ins.append(f"**{m.from_team}** → {tag}")
    return outs, ins


def render_markdown(
    moves: list[DraftMove],
    snapshots: dict[str, TeamSnapshot] | None = None,
    *,
    title: str = "Черновик трансферного окна",
) -> str:
    snaps = snapshots or analyze_teams()
    lines: list[str] = [
        f"# {title}",
        "",
        "> **Статус:** только рекомендации, переходы в БД **не применяются**.",
        "",
        "## Принципы черновика",
        "",
        "1. **5 OUT + 5 IN** на каждый из 40 клубов, без свободных агентов.",
        "2. **Позиции:** OUT и IN сопоставлены по позиции (ВРТ↔ВРТ обязательно); "
        "после окна у клуба ≥3 вратаря.",
        "3. **РПЛ 81+** уходят в более сильную лигу, но не в топ-3 клуба нации "
        "(середина АПЛ/Ла Лиги/Серии А/Бундеслиги).",
        "4. Опора на `collect_transfer_advice` (СУ/НУ/З+) + ручная оценка "
        "контекста (глубина, сила лиги, возрастная/трофейная логика).",
        "",
        "## Сводка по лигам",
        "",
    ]

    for code in _LEAGUE_ORDER:
        label = _LEAGUE_LABEL[code]
        teams = [s for s in snaps.values() if s.league == code]
        if not teams:
            continue
        gk_holes = sum(1 for s in teams if any(x.startswith("ВРТ") for x in s.deficits))
        stars = sum(len(s.rpl_stars) for s in teams)
        lines.append(
            f"- **{label}** ({len(teams)} клубов): "
            f"средняя сила {median([s.strength for s in teams]):.1f}, "
            f"дефицит ВРТ у {gk_holes} клубов"
            + (f", звёзды 81+ к вывозу: {stars}" if code == "rpl" else "")
        )

    lines.extend(["", "## РПЛ: step-up 81+", ""])
    for s in sorted(snaps.values(), key=lambda x: -x.strength):
        if s.league != "rpl" or not s.rpl_stars:
            continue
        lines.append(f"**{s.team}:** " + "; ".join(s.rpl_stars))
    lines.append("")

    # mobility block from actual draft
    mobility = [
        m
        for m in moves
        if national_league_code_for_team(m.from_team) == "rpl" and m.overall >= 81
    ]
    if mobility:
        lines.extend(["## Ключевые переходы РПЛ → топ-5", ""])
        for m in sorted(mobility, key=lambda x: -x.overall):
            lines.append(
                f"- **{m.player}** {m.overall} {m.position} "
                f"({m.from_team} → {m.to_team})"
                + (f" — {m.note}" if m.note else "")
            )
        lines.append("")

    lines.extend(["## По клубам", ""])

    ordered_teams = sorted(
        {m.from_team for m in moves} | {m.to_team for m in moves},
        key=lambda t: (
            _LEAGUE_ORDER.index(snaps[t].league) if t in snaps else 99,
            -(snaps[t].strength if t in snaps else 0),
        ),
    )

    for team in ordered_teams:
        snap = snaps.get(team)
        lines.append(f"### {team}")
        if snap:
            meta = f"сила {snap.strength:.1f}, медиана {snap.median_ovr:.0f}"
            if snap.deficits:
                meta += f", нужно: {', '.join(snap.deficits[:6])}"
            lines.append(f"*{meta}*")
        lines.append("")
        outs, ins = _team_moves_view(moves, team)
        lines.append("| # | OUT → куда | IN ← откуда |")
        lines.append("|---|------------|-------------|")
        lines.append(
            "| | *строки не обязаны быть зеркальными парами — "
            "смотрите на баланс позиций по клубу* | |"
        )
        for i in range(5):
            o = outs[i] if i < len(outs) else "—"
            inn = ins[i] if i < len(ins) else "—"
            lines.append(f"| {i + 1} | {o} | {inn} |")
        if snap and snap.top_sell:
            lines.append("")
            lines.append(
                "<details><summary>Кандидаты на продажу (авто-советы)</summary>"
            )
            lines.append("")
            for x in snap.top_sell:
                lines.append(f"- {x}")
            lines.append("")
            lines.append("</details>")
        lines.append("")

    return "\n".join(lines)


def save_markdown_report(
    moves: list[DraftMove],
    md_path: Path | None = None,
    json_path: Path | None = None,
) -> tuple[Path, list[str]]:
    json_path = json_path or DEFAULT_DRAFT_PATH
    md_path = md_path or json_path.with_suffix(".md")
    errors, warnings = validate_draft(moves)
    snaps = analyze_teams()
    body = render_markdown(moves, snaps)
    if warnings:
        body += "\n## ⚠️ Вратари (проверить вручную)\n\n"
        for w in warnings:
            body += f"- {w}\n"
    if errors:
        body += "\n## ❌ Ошибки баланса\n\n"
        for e in errors:
            body += f"- {e}\n"
    md_path.write_text(body, encoding="utf-8")
    return md_path, errors, warnings
