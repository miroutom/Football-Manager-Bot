# -*- coding: utf-8 -*-
"""
DEBUG: предложение overall по клубу (не применяет в БД).

Сигналы (каждый даёт небольшой вклад в Δ, итог зажат в ±3):
- форма текущего сезона (G+A / сухие vs ожидание для позиции и OVR);
- карьерная продуктивность в клубе;
- травмы (месяцы / периоды);
- win% клуба «когда игрок в старте» vs средний win% клуба;
- траектория OVR по сезонам (пик → сейчас).
"""
from __future__ import annotations

import os
import sqlite3
from dataclasses import dataclass, field
from typing import Any

from utils import season_paths


def _norm(s: str) -> str:
    return (s or "").strip().casefold()


_GK = frozenset({"ВРТ", "ВР", "GK"})
_DEF = frozenset({"ЦЗ", "ЛЦЗ", "ПЦЗ", "ЛЗ", "ПЗ", "ЛФЗ", "ПФЗ"})
_FWD = frozenset({"ФРВ", "ЛФА", "ПФА", "ЦФД", "ЛФД", "ПФД", "СТ"})


@dataclass
class OvrAdviceRow:
    name: str
    position: str
    status: str
    current: int
    suggested: int
    peak: int
    history: list[tuple[int, int]]  # (season, ovr)
    reasons: list[str] = field(default_factory=list)
    signals: dict[str, float] = field(default_factory=dict)
    # context
    season_matches: int = 0
    season_goals: int = 0
    season_assists: int = 0
    season_cs: int = 0
    career_matches: int = 0
    career_ga: int = 0
    career_cs: int = 0
    injury_periods: int = 0
    injury_months: int = 0
    infl_played: int = 0
    infl_win_pct: float = 0.0
    infl_miss: int = 0

    @property
    def delta(self) -> int:
        return int(self.suggested) - int(self.current)


def _expected_ga_per_match(pos: str, ovr: int) -> float:
    """Грубая норма G+A/матч для позиции при данном OVR."""
    pos_u = (pos or "").upper()
    # база для ~85
    if pos_u in _FWD:
        base = 0.85
    elif pos_u in ("ЦАП", "ПП", "CAM"):
        base = 0.70
    elif pos_u in ("ЦП", "ЦОП", "CM", "CDM"):
        base = 0.35
    elif pos_u in _DEF:
        base = 0.12
    else:
        base = 0.40
    # ±0.04 за пункт OVR от 85
    return max(0.05, base + 0.04 * (int(ovr) - 85))


def _expected_cs_rate(ovr: int) -> float:
    return max(0.15, min(0.55, 0.28 + 0.015 * (int(ovr) - 80)))


def _scan_club_players(team: str) -> list[dict[str, Any]]:
    """Текущий сезон: игроки клуба из league+cl (берём max ovr / sum stats)."""
    want = _norm(team)
    active = int(season_paths.get_active_season())
    by: dict[str, dict[str, Any]] = {}
    base = os.path.join(season_paths.PROJECT_ROOT, "db", f"season_{active}")
    for dbn in ("league.db", "champions_league.db"):
        path = os.path.join(base, dbn)
        if not os.path.isfile(path):
            continue
        conn = sqlite3.connect(path)
        try:
            for tbl in ("forwards", "midfielders", "defenders", "goalkeepers"):
                try:
                    if tbl == "goalkeepers":
                        cur = conn.execute(
                            "SELECT name, team, position, COALESCE(overall,0), "
                            "COALESCE(status,''), COALESCE(matches,0), "
                            "0, 0, COALESCE(clean_sheets,0), COALESCE(missed_goals,0) "
                            f"FROM {tbl}"
                        )
                    elif tbl == "defenders":
                        cur = conn.execute(
                            "SELECT name, team, position, COALESCE(overall,0), "
                            "COALESCE(status,''), COALESCE(matches,0), "
                            "COALESCE(goals,0), COALESCE(assists,0), "
                            "COALESCE(clean_sheets,0), 0 "
                            f"FROM {tbl}"
                        )
                    else:
                        cur = conn.execute(
                            "SELECT name, team, position, COALESCE(overall,0), "
                            "COALESCE(status,''), COALESCE(matches,0), "
                            "COALESCE(goals,0), COALESCE(assists,0), 0, 0 "
                            f"FROM {tbl}"
                        )
                except sqlite3.OperationalError:
                    continue
                for name, tm, pos, ovr, st, m, g, a, cs, mg in cur:
                    if _norm(str(tm or "")) != want:
                        continue
                    nm = (name or "").strip()
                    if not nm:
                        continue
                    key = nm.casefold()
                    slot = by.setdefault(
                        key,
                        {
                            "name": nm,
                            "position": (pos or "").strip().upper(),
                            "overall": 0,
                            "status": (st or "").strip().lower(),
                            "matches": 0,
                            "goals": 0,
                            "assists": 0,
                            "clean_sheets": 0,
                            "missed_goals": 0,
                        },
                    )
                    slot["matches"] += int(m or 0)
                    slot["goals"] += int(g or 0)
                    slot["assists"] += int(a or 0)
                    slot["clean_sheets"] += int(cs or 0)
                    slot["missed_goals"] += int(mg or 0)
                    ovri = int(ovr or 0)
                    if ovri >= int(slot["overall"]):
                        slot["overall"] = ovri
                    if st and (not slot["status"] or st == "start"):
                        slot["status"] = (st or "").strip().lower()
                    if pos and not slot["position"]:
                        slot["position"] = (pos or "").strip().upper()
        finally:
            conn.close()
    return list(by.values())


def _ovr_history(team: str, name: str) -> list[tuple[int, int]]:
    want_t, want_n = _norm(team), _norm(name)
    from utils.cumulative_db import list_season_archives_with_db

    seasons = set(list_season_archives_with_db())
    seasons.add(int(season_paths.get_active_season()))
    hist: list[tuple[int, int]] = []
    for sn in sorted(seasons):
        best = 0
        base = os.path.join(season_paths.PROJECT_ROOT, "db", f"season_{int(sn)}")
        for dbn in ("league.db", "champions_league.db"):
            path = os.path.join(base, dbn)
            if not os.path.isfile(path):
                continue
            conn = sqlite3.connect(path)
            try:
                for tbl in ("forwards", "midfielders", "defenders", "goalkeepers"):
                    try:
                        cur = conn.execute(
                            f"SELECT name, team, COALESCE(overall,0) FROM {tbl}"
                        )
                    except sqlite3.OperationalError:
                        continue
                    for nm, tm, ovr in cur:
                        if _norm(str(nm or "")) != want_n:
                            continue
                        if _norm(str(tm or "")) != want_t:
                            continue
                        best = max(best, int(ovr or 0))
            finally:
                conn.close()
        if best > 0:
            hist.append((int(sn), best))
    return hist


def _career_club_stats(team: str, name: str) -> dict[str, int]:
    want_t, want_n = _norm(team), _norm(name)
    from utils.cumulative_db import list_season_archives_with_db

    seasons = set(list_season_archives_with_db())
    seasons.add(int(season_paths.get_active_season()))
    out = {"matches": 0, "goals": 0, "assists": 0, "clean_sheets": 0, "missed_goals": 0}
    for sn in seasons:
        base = os.path.join(season_paths.PROJECT_ROOT, "db", f"season_{int(sn)}")
        for dbn in ("league.db", "champions_league.db"):
            path = os.path.join(base, dbn)
            if not os.path.isfile(path):
                continue
            conn = sqlite3.connect(path)
            try:
                for tbl in ("forwards", "midfielders", "defenders", "goalkeepers"):
                    try:
                        if tbl == "goalkeepers":
                            cur = conn.execute(
                                "SELECT name, team, COALESCE(matches,0), 0, 0, "
                                "COALESCE(clean_sheets,0), COALESCE(missed_goals,0) "
                                f"FROM {tbl}"
                            )
                        elif tbl == "defenders":
                            cur = conn.execute(
                                "SELECT name, team, COALESCE(matches,0), "
                                "COALESCE(goals,0), COALESCE(assists,0), "
                                "COALESCE(clean_sheets,0), 0 FROM {tbl}".format(tbl=tbl)
                            )
                        else:
                            cur = conn.execute(
                                "SELECT name, team, COALESCE(matches,0), "
                                "COALESCE(goals,0), COALESCE(assists,0), 0, 0 "
                                f"FROM {tbl}"
                            )
                    except sqlite3.OperationalError:
                        continue
                    for nm, tm, m, g, a, cs, mg in cur:
                        if _norm(str(nm or "")) != want_n:
                            continue
                        if _norm(str(tm or "")) != want_t:
                            continue
                        out["matches"] += int(m or 0)
                        out["goals"] += int(g or 0)
                        out["assists"] += int(a or 0)
                        out["clean_sheets"] += int(cs or 0)
                        out["missed_goals"] += int(mg or 0)
            finally:
                conn.close()
    return out


def _injury_burden(name: str, team: str | None = None) -> tuple[int, int]:
    from utils.player_discipline import _load, _injury_total_months, _norm as dnorm

    want = dnorm(name)
    want_t = dnorm(team) if team else ""
    n = months = 0
    for inj in (_load().get("injuries") or []):
        if dnorm(str(inj.get("name") or "")) != want:
            continue
        if want_t and dnorm(str(inj.get("team") or "")) not in ("", want_t):
            # считаем все травмы игрока, даже в другом клубе — влияют на OVR
            pass
        n += 1
        months += _injury_total_months(inj)
    return n, months


def advise_club_ovr(
    team: str,
    *,
    min_overall: int = 78,
    starters_first: bool = True,
    limit: int = 20,
) -> list[OvrAdviceRow]:
    """DEBUG-советы по OVR для клуба (без записи в БД)."""
    from bot.team_history import club_player_win_influence, iter_all_match_records, match_result_for_team

    display = (team or "").strip()
    # нормализуем МЮ → Мю
    players = _scan_club_players(display)
    if not players:
        # попробовать Title
        players = _scan_club_players(display.title())
        display = display.title()

    # средний win% клуба
    tw = td = tl = 0
    for m in iter_all_match_records():
        if _norm(m.get("home") or "") != _norm(display) and _norm(
            m.get("away") or ""
        ) != _norm(display):
            continue
        res, *_ = match_result_for_team(m, display)
        if res == "W":
            tw += 1
        elif res == "D":
            td += 1
        else:
            tl += 1
    club_n = tw + td + tl
    club_wr = (tw / club_n) if club_n else 0.5

    infl_map = {
        r.player.casefold(): r
        for r in club_player_win_influence(
            display, min_played=1, limit=80, starters_only=False
        )
    }

    rows: list[OvrAdviceRow] = []
    for p in players:
        cur = int(p.get("overall") or 0)
        if cur < int(min_overall):
            continue
        name = str(p["name"])
        pos = str(p.get("position") or "")
        hist = _ovr_history(display, name)
        peak = max((o for _, o in hist), default=cur)
        career = _career_club_stats(display, name)
        inj_n, inj_m = _injury_burden(name, display)
        infl = infl_map.get(name.casefold())

        sm = int(p.get("matches") or 0)
        sg = int(p.get("goals") or 0)
        sa = int(p.get("assists") or 0)
        scs = int(p.get("clean_sheets") or 0)
        reasons: list[str] = []
        score = 0.0  # вклад в Δ до округления
        signals: dict[str, float] = {}

        # 1) форма текущего сезона
        if sm >= 3:
            if pos in _GK:
                rate = scs / sm
                exp = _expected_cs_rate(cur)
                form = (rate - exp) / max(0.15, exp)
                signals["form_cs"] = round(rate, 3)
                if form > 0.25:
                    score += 0.9
                    reasons.append(
                        f"+ сухие сейчас {scs}/{sm} ({rate:.0%}) выше нормы ~{exp:.0%} для OVR {cur}"
                    )
                elif form < -0.25:
                    score -= 0.9
                    reasons.append(
                        f"− сухие сейчас {scs}/{sm} ({rate:.0%}) ниже нормы ~{exp:.0%} для OVR {cur}"
                    )
                else:
                    reasons.append(f"· сухие {scs}/{sm} около нормы для OVR {cur}")
            else:
                ga = sg + sa
                rate = ga / sm
                exp = _expected_ga_per_match(pos, cur)
                form = (rate - exp) / max(0.15, exp)
                signals["form_ga"] = round(rate, 3)
                if form > 0.35:
                    score += 1.1
                    reasons.append(
                        f"+ форма сезона {sg}+{sa} в {sm} матч. "
                        f"({rate:.2f} G+A/м vs ожид. ~{exp:.2f} для {pos} {cur})"
                    )
                elif form > 0.10:
                    score += 0.5
                    reasons.append(
                        f"+ чуть выше нормы: {sg}+{sa} / {sm} (= {rate:.2f}, ожид. ~{exp:.2f})"
                    )
                elif form < -0.35:
                    score -= 1.0
                    reasons.append(
                        f"− слабая форма: {sg}+{sa} / {sm} (= {rate:.2f}, ожид. ~{exp:.2f})"
                    )
                elif form < -0.10:
                    score -= 0.4
                    reasons.append(
                        f"− чуть ниже нормы: {sg}+{sa} / {sm} (= {rate:.2f})"
                    )
                else:
                    reasons.append(
                        f"· форма ок: {sg}+{sa} в {sm} матч. (= {rate:.2f} ≈ {exp:.2f})"
                    )
        else:
            reasons.append(f"· мало матчей в текущем сезоне ({sm}) — форма почти не влияет")

        # 2) карьера в клубе
        cm = int(career.get("matches") or 0)
        if cm >= 15 and pos not in _GK:
            cga = int(career["goals"]) + int(career["assists"])
            crate = cga / cm
            exp_c = _expected_ga_per_match(pos, cur)
            if crate > exp_c * 1.25:
                score += 0.6
                reasons.append(
                    f"+ карьера в клубе сильная: {cga} G+A / {cm} (= {crate:.2f})"
                )
            elif crate < exp_c * 0.7:
                score -= 0.5
                reasons.append(
                    f"− карьера скромнее нормы: {cga} G+A / {cm} (= {crate:.2f})"
                )
            signals["career_ga_rate"] = round(crate, 3)
        elif cm >= 15 and pos in _GK:
            crate = int(career["clean_sheets"]) / cm
            exp_c = _expected_cs_rate(cur)
            if crate > exp_c * 1.15:
                score += 0.5
                reasons.append(f"+ карьера сухих {career['clean_sheets']}/{cm}")
            elif crate < exp_c * 0.75:
                score -= 0.5
                reasons.append(f"− карьера сухих слабая {career['clean_sheets']}/{cm}")

        # 3) травмы
        signals["injury_months"] = float(inj_m)
        if inj_m >= 8:
            score -= 1.2
            reasons.append(f"− много травм: {inj_n} период(ов), {inj_m} мес. суммарно")
        elif inj_m >= 4:
            score -= 0.7
            reasons.append(f"− травмы: {inj_n}×, {inj_m} мес. (давление на OVR)")
        elif inj_m >= 1:
            score -= 0.25
            reasons.append(f"· были травмы: {inj_n}× / {inj_m} мес.")
        else:
            reasons.append("· травм в JSON нет")

        # 4) результаты клуба при нём
        if infl and infl.played >= 20:
            wr = infl.win_pct / 100.0
            signals["infl_wr"] = round(wr, 3)
            diff = wr - club_wr
            if diff > 0.08:
                score += 0.7
                reasons.append(
                    f"+ при нём клуб чаще побеждает: {infl.win_pct:.0f}% "
                    f"(клуб в среднем {club_wr*100:.0f}%), n={infl.played}"
                )
            elif diff < -0.08:
                score -= 0.7
                reasons.append(
                    f"− при нём win% ниже клуба: {infl.win_pct:.0f}% "
                    f"vs {club_wr*100:.0f}% (n={infl.played}, травма-проп. {infl.missed_injury})"
                )
            else:
                reasons.append(
                    f"· win% при нём ≈ клуб: {infl.win_pct:.0f}% (n={infl.played})"
                )
            if infl.missed_injury >= 12:
                score -= 0.4
                reasons.append(
                    f"− много матчей клуба без него из‑за травм ({infl.missed_injury})"
                )

        # 5) траектория
        if peak >= cur + 3:
            # уже сильно упал — осторожный отскок только если форма плюс
            if score > 0.4:
                score += 0.4
                reasons.append(
                    f"· был пик {peak}, сейчас {cur}: при хорошей форме возможен +1 отскок"
                )
            else:
                score -= 0.3
                reasons.append(
                    f"− OVR уже просел с пика {peak}→{cur}; без формы вверх не тянем"
                )
        elif peak > cur:
            reasons.append(f"· история OVR: пик {peak}, сейчас {cur}")
        if hist:
            chain = " → ".join(str(o) for _, o in hist)
            reasons.append(f"· по сезонам: {chain}")

        # итог
        raw_delta = max(-3.0, min(3.0, score))
        # пороги: не дёргать на 0.3
        if raw_delta >= 0.85:
            delta = 1 if raw_delta < 1.7 else (2 if raw_delta < 2.5 else 3)
        elif raw_delta <= -0.85:
            delta = -1 if raw_delta > -1.7 else (-2 if raw_delta > -2.5 else -3)
        else:
            delta = 0
            if abs(raw_delta) < 0.85 and not any(
                r.startswith(("+", "−")) for r in reasons if r
            ):
                reasons.insert(0, "· сигналов мало / они слабые → оставляем OVR")
            elif delta == 0:
                reasons.insert(0, "· плюсы и минусы уравновешены → оставляем OVR")

        suggested = max(60, min(99, cur + delta))
        signals["score_raw"] = round(score, 2)
        signals["delta"] = float(delta)

        rows.append(
            OvrAdviceRow(
                name=name,
                position=pos,
                status=str(p.get("status") or ""),
                current=cur,
                suggested=suggested,
                peak=peak,
                history=hist,
                reasons=reasons,
                signals=signals,
                season_matches=sm,
                season_goals=sg,
                season_assists=sa,
                season_cs=scs,
                career_matches=cm,
                career_ga=int(career["goals"]) + int(career["assists"]),
                career_cs=int(career["clean_sheets"]),
                injury_periods=inj_n,
                injury_months=inj_m,
                infl_played=int(infl.played) if infl else 0,
                infl_win_pct=float(infl.win_pct) if infl else 0.0,
                infl_miss=int(infl.missed_injury) if infl else 0,
            )
        )

    def sort_key(r: OvrAdviceRow) -> tuple:
        st_rank = 0 if r.status == "start" else (1 if r.status == "bench" else 2)
        if not starters_first:
            st_rank = 0
        return (st_rank, -abs(r.delta), -r.current, r.name.casefold())

    rows.sort(key=sort_key)
    return rows[: max(1, int(limit))]


def format_ovr_advice_report(team: str, rows: list[OvrAdviceRow] | None = None) -> str:
    rows = rows if rows is not None else advise_club_ovr(team)
    chunks = [
        f"── DEBUG OVR · {team} ──",
        "Только тест: в БД ничего не пишем. Δ зажата ±3.",
        "Сигналы: форма сезона · карьера · травмы · win% при игроке · траектория OVR.",
        "",
    ]
    if not rows:
        chunks.append("Нет игроков для разбора.")
        return "\n".join(chunks)

    for r in rows:
        arrow = f"{r.current} → {r.suggested}"
        if r.delta > 0:
            tag = f"ПОДНЯТЬ +{r.delta}"
        elif r.delta < 0:
            tag = f"СНИЗИТЬ {r.delta}"
        else:
            tag = "ОСТАВИТЬ"
        st = r.status or "—"
        chunks.append(
            f"■ {r.name} · {r.position} · {st} · сейчас {r.current}  [{tag}]  {arrow}"
        )
        chunks.append(
            f"  сезон: {r.season_matches} матч, {r.season_goals}+{r.season_assists}"
            + (f", CS {r.season_cs}" if r.position in _GK else "")
            + f" · карьера: {r.career_matches} матч, G+A {r.career_ga}"
            + (f", CS {r.career_cs}" if r.position in _GK or r.career_cs else "")
        )
        chunks.append(
            f"  травмы: {r.injury_periods}× / {r.injury_months} мес · "
            f"влияние: n={r.infl_played}, win {r.infl_win_pct:.0f}%, проп.травм {r.infl_miss}"
        )
        for reason in r.reasons:
            chunks.append(f"  {reason}")
        chunks.append("")
    return "\n".join(chunks).rstrip() + "\n"


def format_ovr_advice_summary_all_clubs(
    *,
    limit_per_club: int = 14,
    changes_only: bool = True,
) -> str:
    """Краткий обзор DEBUG OVR по всем клубам пула (только просмотр)."""
    from utils.transfer_advice import all_league_teams

    chunks = [
        "── DEBUG OVR · все клубы ──",
        "Только тест: в БД ничего не пишем. Ниже игроки с предлагаемым Δ≠0."
        if changes_only
        else "Только тест: в БД ничего не пишем.",
        "",
    ]
    n_clubs = 0
    n_chg = 0
    for team in all_league_teams():
        try:
            rows = advise_club_ovr(team, limit=limit_per_club)
        except Exception as e:
            chunks.append(f"── {team} ── ошибка: {e}")
            chunks.append("")
            continue
        show = [r for r in rows if (not changes_only) or r.delta != 0]
        if not show:
            continue
        n_clubs += 1
        chunks.append(f"── {team} ──")
        for r in show:
            n_chg += 1
            if r.delta > 0:
                tag = f"+{r.delta}"
            elif r.delta < 0:
                tag = str(r.delta)
            else:
                tag = "="
            chunks.append(
                f"  {r.name} · {r.position} · {r.status or '—'} · "
                f"{r.current}→{r.suggested} [{tag}]"
            )
        chunks.append("")
    chunks.append(f"Итого: клубов с правками {n_clubs}, строк {n_chg}.")
    return "\n".join(chunks).rstrip() + "\n"
