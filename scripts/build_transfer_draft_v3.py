#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Черновик трансферного окна v3: 5 OUT + 5 IN × 40 клубов.

  python3 scripts/build_transfer_draft_v3.py
  python3 scripts/build_transfer_draft_v3.py -o data/transfer_window_draft_v3.md
"""
from __future__ import annotations

import argparse
import sys
from collections import defaultdict
from dataclasses import dataclass
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from config.leagues_config import MANAGER_TEAMS
from player_stats import LEAGUE_NAMES, LEAGUE_TEAMS, national_league_code_for_team
from utils.transfer_advice import collect_transfer_advice, player_surname
from utils.transfer_market_draft import (
    DraftMove,
    _EXCLUDED_TEAMS,
    _league_rank,
    validate_draft,
)

CL_POOL_PATH = _ROOT / "data" / "cl_participants_dynamic.txt"
TARGET = 5
TOP_OVR = 84
MAX_PAIR = 2
MAX_CROSS_TOP_PER_MGR = 3

TOP16 = frozenset({
    "Сити", "Ливерпуль", "Арсенал", "Челси", "Интер", "Наполи", "Милан", "Аталанта",
    "Реал", "Атлетико", "Барселона", "Атлетик", "Бавария", "Вольфсбург", "Дортмунд", "Лейпциг",
})

# Приоритетные топ-переходы (не обязательные — алгоритм пытается в первую очередь)
ELITE_SWAPS: list[tuple[str, str, str, str]] = [
    ("Ковачич", "Сити", "Мю", "топ-полузащитник на ротацию"),
    ("Модрич", "Ливерпуль", "Наполи", "ветеран в топ-клуб"),
    ("Маркиньос", "Реал", "Атлетико", "опытный ЦЗ в оборону"),
    ("Диас", "Ливерпуль", "Ньюкасл", "ЛЧ-класс на фланг"),
    ("Грилиш", "Интер", "Челси", "креатив на фланг"),
    ("Мане", "Интер", "Тоттенхэм", "усиление атаки"),
    ("Беллингем", "Милан", "Арсенал", "усиление полузащиты"),
    ("Депай", "Атлетико", "Барселона", "форвард на ротацию"),
]

# (player, from_team, to_team, note)
MANDATORY: list[tuple[str, str, str, str]] = [
    ("Альварез", "Динамо", "Ньюкасл", "РПЛ 81+ → АПЛ (не топ-3)"),
    ("Давид", "Зенит", "Севилья", "РПЛ 81+ → Ла Лига"),
    ("Ляказет", "Краснодар", "Бетис", "РПЛ 81+ → Ла Лига"),
    ("Трехо", "Зенит", "Ливерпуль", "РПЛ 81+ → АПЛ"),
    ("Митома", "Спартак", "Атлетик", "РПЛ 81+ → Ла Лига"),
    ("Орта", "Спартак", "Лацио", "РПЛ 81+ → Серия А"),
    ("Фуллкруг", "Спартак", "Милан", "РПЛ 81+ → Серия А"),
    ("Бето", "Спартак", "Франкфурт", "РПЛ 81+ → Бундеслига"),
    ("Данк", "Спартак", "Вольфсбург", "РПЛ 81+ → Бундеслига"),
    ("Заха", "Зенит", "Реал Сосьедад", "РПЛ 81+ → Ла Лига"),
    ("Бовен", "Зенит", "Боруссия М", "РПЛ 81+ → Бундеслига"),
    ("Фомин", "Зенит", "Тоттенхэм", "РПЛ 81+ → АПЛ"),
    ("Карраскаль", "Динамо", "Фиорентина", "РПЛ 81+ → Серия А"),
    ("Сангаре", "Динамо", "Аталанта", "РПЛ 81+ → Серия А"),
]

POS_COMPAT: dict[str, set[str]] = {
    "ВРТ": {"ВРТ"},
    "ЦЗ": {"ЦЗ"},
    "ПЗ": {"ПЗ", "ЛЗ"},
    "ЛЗ": {"ЛЗ", "ПЗ"},
    "ЦОП": {"ЦОП", "ЦП", "ЦАП"},
    "ЦП": {"ЦП", "ЦОП", "ЦАП", "ЛП", "ПП"},
    "ЦАП": {"ЦАП", "ЦП", "ЦОП", "ЛП"},
    "ЛП": {"ЛП", "ЛФА", "ЦП", "ЦАП"},
    "ПП": {"ПП", "ПФА", "ЦП"},
    "ЛФА": {"ЛФА", "ЛП", "ПФА", "ФРВ"},
    "ПФА": {"ПФА", "ПП", "ЛФА", "ФРВ"},
    "ФРВ": {"ФРВ", "ПФА", "ЛФА"},
}


@dataclass
class PInfo:
    name: str
    sur: str
    team: str
    pos: str
    ovr: int
    status: str
    verdict: str
    depth: int
    pm: float | None
    sell: float


def _mgr(team: str) -> str:
    t = team.strip().lower()
    for side, clubs in MANAGER_TEAMS.items():
        if t in {c.lower() for c in clubs}:
            return side
    return "?"


def _load_cl() -> set[str]:
    if not CL_POOL_PATH.is_file():
        return set()
    return {
        ln.strip()
        for ln in CL_POOL_PATH.read_text(encoding="utf-8").splitlines()
        if ln.strip() and not ln.startswith("#")
    }


def _teams40() -> list[str]:
    out: list[str] = []
    for code in ("rpl", "eng", "esp", "ita", "ger"):
        out.extend(LEAGUE_TEAMS.get(code, []))
    return [t for t in out if t not in _EXCLUDED_TEAMS]


def _sell_score(row) -> float:
    d = row.detail or {}
    st = (d.get("status") or "").strip().lower()
    dr = int(d.get("depth_rank") or row.depth_rank or 9)
    ovr = int(row.overall)
    pm = d.get("result_pm")
    sc = 0.0
    if st == "reserve":
        sc += 4.0
    elif st == "bench":
        sc += 2.5 if dr >= 3 else 1.5
    if ovr <= 79:
        sc += 2.0
    if ovr >= 84 and row.verdict in ("НО", "СО"):
        sc -= 8.0
    if pm is not None and float(pm) < -8:
        sc += 2.0
    if ovr >= 88 and row.verdict in ("СУ", "НУ"):
        sc += 3.0
    return sc


def _load_players() -> dict[tuple[str, str], PInfo]:
    """key = (surname_lower, position)"""
    pool: dict[tuple[str, str], PInfo] = {}
    for team in _teams40():
        canon, rows, err = collect_transfer_advice(team)
        if err:
            continue
        for r in rows:
            sur = (player_surname(r.name) or r.name).strip()
            pos = r.position.strip().upper()
            d = r.detail or {}
            key = (sur.casefold(), pos)
            pool[key] = PInfo(
                name=sur,
                sur=sur,
                team=canon,
                pos=pos,
                ovr=int(r.overall),
                status=(d.get("status") or "").strip().lower(),
                verdict=r.verdict,
                depth=int(d.get("depth_rank") or r.depth_rank or 9),
                pm=float(d["result_pm"]) if d.get("result_pm") is not None else None,
                sell=_sell_score(r),
            )
    return pool


def _find(pool: dict, name: str, team: str, pos: str | None = None) -> PInfo | None:
    want_t = team.strip().casefold()
    want_n = name.strip().casefold()
    for (n, p), info in pool.items():
        if n != want_n:
            continue
        if info.team.strip().casefold() != want_t:
            continue
        if pos and p != pos.strip().upper():
            continue
        return info
    # fallback: any position
    for (n, _), info in pool.items():
        if n == want_n and info.team.strip().casefold() == want_t:
            return info
    return None


def _pos_ok(need: str, offer: str) -> bool:
    need = need.strip().upper()
    offer = offer.strip().upper()
    if need == offer:
        return True
    return offer in POS_COMPAT.get(need, {need})


def _move(info: PInfo, to: str, note: str) -> DraftMove:
    return DraftMove(
        player=info.sur,
        position=info.pos,
        overall=info.ovr,
        from_team=info.team,
        to_team=to,
        note=note,
    )


def _team_tier(team: str, cl: set[str]) -> int:
    if team in TOP16:
        return 0
    if team in cl:
        return 1
    if national_league_code_for_team(team) == "rpl":
        return 2
    return 3


def _in_note(buyer: str, pinfo: PInfo, cl: set[str]) -> str:
    tier = _team_tier(buyer, cl)
    if pinfo.ovr >= 84:
        return "топ-переход"
    if pinfo.ovr >= 82 and tier <= 1:
        return "усиление бенча / ротация ЛЧ"
    if pinfo.ovr >= 81 and tier <= 1:
        return "ключевое усиление под ЛЧ"
    if pinfo.ovr >= 80 and tier == 0:
        return "ротация топ-клуба"
    if pinfo.ovr >= 78 and tier <= 2:
        return "усиление состава"
    return "глубина / ротация"


def _out_note(seller: str, pinfo: PInfo, buyer: str, cl: set[str]) -> str:
    st = _team_tier(seller, cl)
    bt = _team_tier(buyer, cl)
    if pinfo.ovr >= 84 and st <= 1:
        return "топ-переход"
    if pinfo.ovr >= 82 and st == 0 and bt <= 1:
        return "излишек бенча → клубу ЛЧ"
    if pinfo.ovr >= 80 and st <= 1:
        return "ротация / освобождение места"
    return "глубина / ротация"


def _build_moves(pool: dict, cl: set[str]) -> list[DraftMove]:
    moves: list[DraftMove] = []
    used: set[tuple[str, str]] = set()
    out_c: dict[str, int] = defaultdict(int)
    in_c: dict[str, int] = defaultdict(int)
    pair_c: dict[tuple[str, str], int] = defaultdict(int)
    cross_top: dict[str, int] = defaultdict(int)
    premium_in: dict[str, int] = defaultdict(int)

    mandatory_keys = {(n.casefold(), fr, to) for n, fr, to, _ in MANDATORY}

    def can_add(m: DraftMove, *, mandatory: bool = False) -> bool:
        if out_c[m.from_team] >= TARGET or in_c[m.to_team] >= TARGET:
            return False
        key = (m.player.casefold(), m.position)
        if key in used:
            return False
        if pair_c[(m.from_team, m.to_team)] >= MAX_PAIR:
            return False
        from_lc = national_league_code_for_team(m.from_team)
        to_lc = national_league_code_for_team(m.to_team)
        if (
            not mandatory
            and from_lc == "rpl"
            and m.overall >= 81
            and to_lc
            and to_lc != "rpl"
            and m.position != "ВРТ"
        ):
            if _league_rank(m.to_team, to_lc) <= 3:
                return False
        if m.overall >= TOP_OVR:
            mf, mt = _mgr(m.from_team), _mgr(m.to_team)
            if mf != mt and mf in ("roman", "lika") and mt in ("roman", "lika"):
                if cross_top[mf] >= MAX_CROSS_TOP_PER_MGR or cross_top[mt] >= MAX_CROSS_TOP_PER_MGR:
                    return False
        return True

    def commit(m: DraftMove) -> None:
        moves.append(m)
        key = (m.player.casefold(), m.position)
        used.add(key)
        out_c[m.from_team] += 1
        in_c[m.to_team] += 1
        pair_c[(m.from_team, m.to_team)] += 1
        if m.overall >= TOP_OVR:
            mf, mt = _mgr(m.from_team), _mgr(m.to_team)
            if mf != mt:
                cross_top[mf] += 1
                cross_top[mt] += 1
        tier = _team_tier(m.to_team, cl)
        if m.overall >= 82 and tier == 0:
            premium_in[m.to_team] += 1
        elif m.overall >= 81 and tier == 1:
            premium_in[m.to_team] += 1
        elif m.overall >= 80 and tier == 2:
            premium_in[m.to_team] += 1

    teams = _teams40()
    mandatory_out_names = {name.casefold() for name, fr, _, _ in MANDATORY}

    def need_out(t: str) -> int:
        return TARGET - out_c[t]

    def need_in(t: str) -> int:
        return TARGET - in_c[t]

    def premium_target(team: str) -> int:
        tier = _team_tier(team, cl)
        if tier == 0:
            return 3
        if tier == 1:
            return 2
        if tier == 2:
            return 1
        return 0

    def premium_need(team: str) -> int:
        return max(0, premium_target(team) - premium_in[team])

    def min_in_ovr(team: str, premium: bool) -> int:
        tier = _team_tier(team, cl)
        if premium:
            if tier == 0:
                return 82
            if tier == 1:
                return 81
            if tier == 2:
                return 80
            return 79
        if tier == 0:
            return 80
        if tier == 1:
            return 78
        if tier == 2:
            return 76
        if team in cl:
            return 76
        return 72

    def out_candidates(
        team: str,
        *,
        for_buyer: str | None = None,
        min_ovr: int = 0,
        relax: int = 0,
    ) -> list[PInfo]:
        bt = _team_tier(for_buyer, cl) if for_buyer else 3
        st = _team_tier(team, cl)
        cand: list[PInfo] = []
        for p in pool.values():
            if p.team != team or (p.sur.casefold(), p.pos) in used:
                continue
            if p.sur.casefold() in mandatory_out_names:
                continue
            if p.ovr < min_ovr:
                continue
            if p.ovr >= 84:
                if not (p.status in ("bench", "reserve") and p.sell >= 2.0):
                    if relax < 2 or p.status == "start" or p.sell < 3.5:
                        continue
            if p.ovr >= 82 and p.status == "start":
                if relax < 1:
                    continue
            if p.ovr >= 80 and p.verdict in ("НО", "СО") and p.status == "start":
                if relax < 1:
                    continue
            if p.sell < 1.0 and p.ovr > 79 and st <= 1:
                if relax < 2:
                    continue
            if team in TOP16:
                if p.status == "start" and p.ovr > 79 and relax < 2:
                    continue
                if for_buyer:
                    if bt >= 2 and p.ovr > 81 and relax < 2:
                        continue
                    if bt >= 3 and p.ovr > 79 and relax < 1:
                        continue
                cap = 79 + relax * 2
                if p.ovr > cap and relax < 3 and bt >= 2:
                    continue
            if st <= 1 and bt >= 3 and p.ovr > 80 and relax < 2:
                continue
            cand.append(p)
        cand.sort(key=lambda x: (-x.ovr, -x.sell))
        return cand

    def best_incoming(
        buyer: str,
        *,
        premium: bool,
        relax: int = 0,
    ) -> tuple[PInfo, str] | None:
        want = min_in_ovr(buyer, premium) - relax
        best: tuple[float, PInfo, str] | None = None
        bt = _team_tier(buyer, cl)
        for seller in teams:
            if seller == buyer or need_out(seller) <= 0:
                continue
            if pair_c[(seller, buyer)] >= MAX_PAIR:
                continue
            for p in out_candidates(seller, for_buyer=buyer, min_ovr=want, relax=relax):
                if (p.sur.casefold(), p.pos) in used:
                    continue
                if buyer in cl and p.ovr < want and relax < 2:
                    continue
                score = p.ovr * 3.0 + p.sell
                st = _team_tier(seller, cl)
                if st < bt:
                    score += 4.0
                if premium and p.ovr >= min_in_ovr(buyer, True):
                    score += 6.0
                if best is None or score > best[0]:
                    best = (score, p, seller)
        return (best[1], best[2]) if best else None

    # --- фаза 1: обязательные РПЛ 81+ ---
    for name, fr, to, note in MANDATORY:
        info = _find(pool, name, fr)
        if info is None:
            raise RuntimeError(f"Нет в БД: {name} ({fr})")
        m = _move(info, to, note)
        if not can_add(m, mandatory=True):
            raise RuntimeError(f"Не влезает обязательный: {name} {fr}→{to}")
        commit(m)

    # --- фаза 2: приоритетные топ-переходы ---
    for name, fr, to, note in ELITE_SWAPS:
        if need_in(to) <= 0 or need_out(fr) <= 0:
            continue
        info = _find(pool, name, fr)
        if info is None or (info.sur.casefold(), info.pos) in used:
            continue
        m = _move(info, to, note)
        if can_add(m):
            commit(m)

    # --- фаза 3: премиум-IN для топ-16 и ЛЧ ---
    for relax in range(3):
        buyers = sorted(teams, key=lambda t: (_team_tier(t, cl), -premium_need(t), -need_in(t)))
        progress = False
        for buyer in buyers:
            while premium_need(buyer) > 0 and need_in(buyer) > 0:
                hit = best_incoming(buyer, premium=True, relax=relax)
                if hit is None:
                    break
                pinfo, seller = hit
                m = _move(pinfo, buyer, _in_note(buyer, pinfo, cl))
                if not can_add(m):
                    break
                commit(m)
                progress = True
        if not progress and relax >= 1:
            break

    # --- фаза 4: обычные IN с учётом уровня клуба ---
    for relax in range(4):
        buyers = sorted(teams, key=lambda t: (_team_tier(t, cl), -need_in(t)))
        progress = False
        for buyer in buyers:
            if need_in(buyer) <= 0:
                continue
            premium = premium_need(buyer) > 0
            hit = best_incoming(buyer, premium=premium, relax=relax)
            if hit is None:
                continue
            pinfo, seller = hit
            m = _move(pinfo, buyer, _in_note(buyer, pinfo, cl))
            if not can_add(m):
                continue
            commit(m)
            progress = True
        if not progress:
            break

    # --- фаза 5: закрыть OUT/IN остатки ---
    def try_fill_one(relax: int = 0) -> bool:
        incomplete = [t for t in teams if need_out(t) or need_in(t)]
        if not incomplete:
            return False
        t = max(incomplete, key=lambda x: (_team_tier(x, cl), need_out(x) + need_in(x)))
        if need_out(t) > 0 and need_in(t) > 0:
            for other in sorted(teams, key=lambda x: -(need_out(x) + need_in(x))):
                if other == t:
                    continue
                if need_out(other) <= 0 or need_in(other) <= 0:
                    continue
                if pair_c[(t, other)] >= MAX_PAIR or pair_c[(other, t)] >= MAX_PAIR:
                    continue
                oc = out_candidates(t, for_buyer=other, relax=relax)
                ic = out_candidates(other, for_buyer=t, relax=relax)
                if not oc or not ic:
                    continue
                m1 = _move(oc[0], other, _out_note(t, oc[0], other, cl))
                m2 = _move(ic[0], t, _out_note(other, ic[0], t, cl))
                if can_add(m1) and can_add(m2):
                    commit(m1)
                    commit(m2)
                    return True
        if need_out(t) > 0:
            for other in sorted(teams, key=lambda x: -need_in(x)):
                if other == t or need_in(other) <= 0:
                    continue
                if pair_c[(t, other)] >= MAX_PAIR:
                    continue
                for p in out_candidates(t, for_buyer=other, relax=relax):
                    m = _move(p, other, _out_note(t, p, other, cl))
                    if can_add(m):
                        commit(m)
                        return True
        if need_in(t) > 0:
            hit = best_incoming(t, premium=premium_need(t) > 0, relax=relax)
            if hit:
                pinfo, seller = hit
                m = _move(pinfo, t, _in_note(t, pinfo, cl))
                if can_add(m):
                    commit(m)
                    return True
        return False

    for relax in range(5):
        for _ in range(4000):
            if not any(need_out(t) or need_in(t) for t in teams):
                break
            if not try_fill_one(relax):
                break

    return moves


def _team_blurb(team: str, moves: list[DraftMove], cl: set[str]) -> str:
    outs = [m for m in moves if m.from_team == team]
    ins = [m for m in moves if m.to_team == team]
    mgr = _mgr(team)
    bits: list[str] = []
    if team in cl:
        bits.append("участник ЛЧ — усиление")
    if mgr in ("roman", "lika"):
        bits.append(f"менеджер **{mgr.capitalize()}**")
    rpl_stars_out = [m for m in outs if m.overall >= 81]
    rpl_stars_in = [m for m in ins if m.overall >= 81]
    if rpl_stars_out:
        bits.append("отток звёзд РПЛ" if national_league_code_for_team(team) == "rpl" else "")
    if rpl_stars_in:
        bits.append(f"приход {len(rpl_stars_in)} игрок(ов) 81+")
    top16_in_82 = [m for m in ins if m.overall >= 82]
    if team in TOP16:
        bits.append(f"топ-16: {len(top16_in_82)} приход(ов) 82+")
    elif team in cl and top16_in_82:
        bits.append(f"ЛЧ: приход {len([m for m in ins if m.overall >= 81])} игрок(ов) 81+")
    return "; ".join(x for x in bits if x) or "ротация состава"


def render_md(moves: list[DraftMove], errors: list[str], warnings: list[str]) -> str:
    cl = _load_cl()
    lines: list[str] = [
        "# Трансферное окно — черновик v3",
        "",
        "> Рекомендации по правилам из `teams_rosters_for_glm.md` + уточнения менеджеров Roman/Lika. "
        "**В БД не применять.**",
        "",
        f"**Переходов:** {len(moves)} (цель 200 = 5 OUT + 5 IN × 40).",
        "",
        "### Дополнительные правила (v3)",
        "",
        "- Ровно **5 OUT** и **5 IN** на клуб; **без свободных агентов**.",
        "- **Вратари** могут переходить; третьего ВРТ в окне не добавляем.",
        "- Вердикты НУ/СО/НО/СУ — ориентир, не автомат; приоритет — здравый смысл и контекст.",
        "- **Roman ↔ Lika:** не более **3** обменов игроками **84+** на менеджера за окно.",
        "- Не более **2** игроков с одного клуба на один клуб; без «5↔5» с одной командой.",
        "",
    ]
    if errors:
        lines.append("### ⚠️ Ошибки баланса")
        lines.append("")
        for e in errors:
            lines.append(f"- {e}")
        lines.append("")
    if warnings:
        lines.append("### Предупреждения")
        lines.append("")
        for w in warnings:
            lines.append(f"- {w}")
        lines.append("")

    lines.extend([
        "## Обязательные акценты",
        "",
        "| Игрок | Откуда | Куда | Зачем |",
        "|-------|--------|------|-------|",
    ])
    for name, fr, to, note in MANDATORY:
        lines.append(f"| **{name}** | {fr} | **{to}** | {note} |")
    lines.append("")
    lines.extend([
        "## Приоритетные топ-переходы",
        "",
        "| Игрок | Откуда | Куда | Зачем |",
        "|-------|--------|------|-------|",
    ])
    elite_done = {(m.player.casefold(), m.from_team, m.to_team) for m in moves}
    for name, fr, to, note in ELITE_SWAPS:
        mark = "✓" if (name.casefold(), fr, to) in elite_done else "—"
        lines.append(f"| {mark} **{name}** | {fr} | **{to}** | {note} |")
    lines.append("")

    for code in ("rpl", "eng", "esp", "ita", "ger"):
        lname = LEAGUE_NAMES.get(code, code.upper())
        lines.append(f"## {lname}")
        lines.append("")
        for team in LEAGUE_TEAMS.get(code, []):
            if team in _EXCLUDED_TEAMS:
                continue
            outs = [m for m in moves if m.from_team == team]
            ins = [m for m in moves if m.to_team == team]
            lines.append(f"### {team} [{_mgr(team)}] — OUT {len(outs)}/5 · IN {len(ins)}/5")
            lines.append("")
            lines.append(f"*{_team_blurb(team, moves, cl)}*")
            lines.append("")
            lines.append("| OUT | → Куда | IN | ← Откуда |")
            lines.append("|-----|--------|----|---------| ")
            for i in range(max(len(outs), len(ins), TARGET)):
                out_s = "—"
                in_s = "—"
                if i < len(outs):
                    m = outs[i]
                    out_s = f"**{m.player}** {m.position} {m.overall} — {m.note or '—'}"
                    out_to = f"**{m.to_team}**"
                else:
                    out_to = "—"
                if i < len(ins):
                    m = ins[i]
                    in_s = f"**{m.player}** {m.position} {m.overall} — {m.note or '—'}"
                    in_from = f"**{m.from_team}**"
                else:
                    in_from = "—"
                if i < len(outs):
                    lines.append(f"| {out_s} | {out_to} | {in_s} | {in_from} |")
                else:
                    lines.append(f"| — | — | {in_s} | {in_from} |")
            lines.append("")

    return "\n".join(lines).rstrip() + "\n"


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("-o", "--output", type=Path, default=_ROOT / "data" / "transfer_window_draft_v3.md")
    args = p.parse_args()

    pool = _load_players()
    moves = _build_moves(pool, _load_cl())
    errors, warnings = validate_draft(moves, _teams40())
    text = render_md(moves, errors, warnings)
    args.output.write_text(text, encoding="utf-8")
    print(f"Записано: {args.output}")
    print(f"Переходов: {len(moves)}, ошибок: {len(errors)}, предупреждений: {len(warnings)}")
    if errors:
        for e in errors[:20]:
            print(" ERR:", e)
        if len(errors) > 20:
            print(f" ... ещё {len(errors)-20}")
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
