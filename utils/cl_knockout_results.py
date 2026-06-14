# -*- coding: utf-8 -*-
"""
Стадии плей-офф ЛЧ по журналу матчей или ``season_history.json``.

Шкала (чем выше — тем дальше прошли):
  0 — вылет в группе / не в нокауте
  1 — 1/16 (round_1, day 6)
  2 — 1/8 (round_2, day 7)
  3 — 1/4 (round_3, day 8)
  4 — 1/2 (semi_finals, day 9)
  5 — финал (проигравший, day 10)
  6 — победитель
"""
from __future__ import annotations

import os
from typing import Any

from utils import season_paths
from utils.player_transfer import _norm_cmp

CL_STAGE_NONE = 0
CL_STAGE_R16 = 1
CL_STAGE_R8 = 2
CL_STAGE_R4 = 3
CL_STAGE_SF = 4
CL_STAGE_FINAL = 5
CL_STAGE_CHAMP = 6

CL_STAGE_LABEL_RU: dict[int, str] = {
    CL_STAGE_NONE: "группа",
    CL_STAGE_R16: "1/16",
    CL_STAGE_R8: "1/8",
    CL_STAGE_R4: "1/4",
    CL_STAGE_SF: "1/2",
    CL_STAGE_FINAL: "финал",
    CL_STAGE_CHAMP: "победитель",
}

_DAY_TO_STAGE: dict[int, int] = {
    6: CL_STAGE_R16,
    7: CL_STAGE_R8,
    8: CL_STAGE_R4,
    9: CL_STAGE_SF,
    10: CL_STAGE_FINAL,
}


def _norm_team(s: str) -> str:
    t = (s or "").strip()
    if t.casefold() == "цска":
        return "Цска"
    return t.title()


def cl_stage_label_ru(stage: int) -> str:
    return CL_STAGE_LABEL_RU.get(int(stage), "—")


def _knockout_records_from_journal(journal_path: str) -> list[dict[str, Any]]:
    from match_results import _normalize_cl_phase, load_records_and_keys_from_path

    records, _ = load_records_and_keys_from_path(journal_path)
    out: list[dict[str, Any]] = []
    for r in records:
        if str(r.get("league") or "") != "cl":
            continue
        if _normalize_cl_phase(r.get("cl_phase")) != "knockout":
            continue
        out.append(r)
    return out


def _final_winner_from_record(rec: dict[str, Any]) -> str | None:
    hs, aws = rec.get("home_score"), rec.get("away_score")
    if hs is None or aws is None:
        return None
    h = _norm_team(str(rec.get("home") or ""))
    a = _norm_team(str(rec.get("away") or ""))
    if int(hs) > int(aws):
        return h
    if int(aws) > int(hs):
        return a
    pen = rec.get("penalties_by_team")
    if isinstance(pen, dict):
        ph = pen.get(h)
        if ph is None:
            ph = pen.get(h.title())
        pa = pen.get(a)
        if pa is None:
            pa = pen.get(a.title())
        if ph is not None and pa is not None:
            if int(ph) > int(pa):
                return h
            if int(pa) > int(ph):
                return a
    return None


def team_cl_knockout_stage_from_records(
    team: str, records: list[dict[str, Any]]
) -> int:
    """Максимальная стадия по нокаут-матчам журнала (day 6–10 = раунд)."""
    want = _norm_cmp(_norm_team(team))
    if not want or not records:
        return CL_STAGE_NONE

    best = CL_STAGE_NONE
    final_recs: list[dict[str, Any]] = []
    for r in records:
        h = _norm_cmp(_norm_team(str(r.get("home") or "")))
        a = _norm_cmp(_norm_team(str(r.get("away") or "")))
        if want not in (h, a):
            continue
        try:
            day = int(r.get("day") or 0)
        except (TypeError, ValueError):
            day = 0
        stage = _DAY_TO_STAGE.get(day, CL_STAGE_NONE)
        if day == 10:
            final_recs.append(r)
        if stage > 0:
            best = max(best, int(stage))

    if best >= CL_STAGE_FINAL and final_recs:
        for rec in final_recs:
            winner = _final_winner_from_record(rec)
            if winner and _norm_cmp(winner) == want:
                return CL_STAGE_CHAMP
        return CL_STAGE_FINAL
    return int(best)


def team_cl_knockout_stage_from_bracket(team: str, bracket_state: dict[str, Any]) -> int:
    """Совместимость: делегирует в разбор журнала, если передан путь в meta."""
    jp = bracket_state.get("_journal_path")
    if jp:
        return team_cl_knockout_stage_from_records(
            team, _knockout_records_from_journal(str(jp))
        )
    return CL_STAGE_NONE


def _journal_path_for_season(season_num: int) -> str | None:
    active = int(season_paths.get_state().get("active_season") or 1)
    if int(season_num) == active:
        from match_results import MATCH_RESULTS_FILE

        return MATCH_RESULTS_FILE if os.path.isfile(MATCH_RESULTS_FILE) else None
    path = os.path.join(
        season_paths.season_archive_directory(int(season_num)),
        "match_results.json",
    )
    return path if os.path.isfile(path) else None


def all_cl_knockout_stages_from_journal(journal_path: str) -> dict[str, int]:
    """Все команды нокаута сезона → стадия (канонические имена)."""
    records = _knockout_records_from_journal(journal_path)
    teams: set[str] = set()
    for r in records:
        for side in ("home", "away"):
            nm = str(r.get(side) or "").strip()
            if nm:
                teams.add(_norm_team(nm))
    return {
        t: team_cl_knockout_stage_from_records(t, records) for t in sorted(teams)
    }


def _cl_stages_history_rows() -> list[Any]:
    from bot.season_history_store import load_history

    rows = load_history().get("cl_knockout_stages") or []
    return rows if isinstance(rows, list) else []


def _cl_stages_map_for_season(season_num: int) -> dict[str, int] | None:
    sn = int(season_num)
    for row in _cl_stages_history_rows():
        if not row or len(row) < 2:
            continue
        try:
            if int(row[0]) != sn:
                continue
        except (TypeError, ValueError):
            continue
        block = row[1]
        if not isinstance(block, dict):
            continue
        out: dict[str, int] = {}
        for k, v in block.items():
            try:
                out[_norm_team(str(k))] = int(v)
            except (TypeError, ValueError):
                continue
        return out
    return None


def team_cl_knockout_stage(team: str, season_num: int) -> int:
    """Стадия ЛЧ команды в сезоне: история → архив журнала → 0."""
    team_n = _norm_team(team)
    hist = _cl_stages_map_for_season(int(season_num))
    if hist is not None:
        for k, stage in hist.items():
            if _norm_cmp(k) == _norm_cmp(team_n):
                return int(stage)

    jp = _journal_path_for_season(int(season_num))
    if jp:
        return team_cl_knockout_stage_from_records(
            team_n, _knockout_records_from_journal(jp)
        )
    return CL_STAGE_NONE


def _league_cl_scale(league_code: str | None) -> float:
    from utils.team_registry import get_league

    lg = get_league((league_code or "").strip().lower())
    if lg is None:
        return 0.65
    return float(lg.cl_scale)


def expected_cl_knockout_stage(
    team: str,
    *,
    league_code: str | None,
    league_rank: int,
    cl_rank: int | None,
    prev_stage: int | None = None,
) -> float:
    """
    Ожидаемая глубина в ЛЧ для клуба (0..6).
    Топ-клубы: ожидаем минимум 1/8; вылет в группе/1/16 — провал.
    """
    if cl_rank is None:
        return 0.0

    rk = int(cl_rank)
    if rk <= 3:
        base = 4.2
    elif rk <= 8:
        base = 3.2
    elif rk <= 15:
        base = 2.0
    elif rk <= 20:
        base = 1.2
    else:
        base = 0.8

    from utils.team_registry import get_team

    tm = get_team(team)
    tier = max(1, min(5, int(tm.trophy_tier))) if tm else 3
    base += max(0, tier - 3) * 0.35

    if int(league_rank) <= 2 and tier >= 4:
        base += 0.25

    prev = int(prev_stage) if prev_stage is not None else None
    if prev is not None:
        if prev >= CL_STAGE_CHAMP:
            base = max(base, 5.0)
        elif prev >= CL_STAGE_FINAL:
            base = max(base, 4.5)
        elif prev >= CL_STAGE_SF:
            base = max(base, 3.8)

    cl_scale = _league_cl_scale(league_code)
    if cl_scale < 0.25 and rk > 12:
        base = min(base, 1.4)

    return max(0.5, min(6.0, float(base)))


def team_cl_stage_performance(
    team: str,
    season_nums: list[int],
    *,
    league_code: str | None,
    league_rank: int,
    cl_rank: int | None,
) -> tuple[float, float, list[tuple[int, int, float]]]:
    """
    Сводка по стадиям ЛЧ за сезоны игрока в клубе.

    Возвращает (взвешенная дельта, тренд последнего сезона, детали по сезонам).
    """
    seasons = sorted({int(s) for s in (season_nums or []) if int(s) > 0})
    if not seasons or cl_rank is None:
        return 0.0, 0.0, []

    active = int(season_paths.get_state().get("active_season") or 1)

    details: list[tuple[int, int, float]] = []
    prev_stage: int | None = None
    weighted = 0.0
    weight_sum = 0.0
    per_deltas: list[float] = []

    for i, sn in enumerate(seasons):
        if sn >= active and not _season_cl_knockout_complete(sn):
            continue
        actual = team_cl_knockout_stage(team, sn)
        expected = expected_cl_knockout_stage(
            team,
            league_code=league_code,
            league_rank=league_rank,
            cl_rank=cl_rank,
            prev_stage=prev_stage,
        )
        if actual <= CL_STAGE_NONE and expected < 1.0:
            prev_stage = actual
            continue
        delta = float(actual) - float(expected)
        details.append((sn, actual, round(expected, 2)))
        w = 1.0 + 0.35 * len(details) - 1
        weighted += delta * w
        weight_sum += w
        per_deltas.append(delta)
        prev_stage = actual

    if weight_sum <= 0.0:
        return 0.0, 0.0, details

    cl_delta = weighted / weight_sum
    trend = per_deltas[-1] - per_deltas[-2] if len(per_deltas) >= 2 else per_deltas[-1]
    return round(cl_delta, 2), round(trend, 2), details


def _season_cl_knockout_complete(season_num: int) -> bool:
    """Нокаут сезона завершён (есть финал в журнале или архивная запись)."""
    hist = _cl_stages_map_for_season(int(season_num))
    if hist is not None:
        return any(int(v) >= CL_STAGE_FINAL for v in hist.values())
    jp = _journal_path_for_season(int(season_num))
    if not jp:
        return False
    stages = all_cl_knockout_stages_from_journal(jp)
    return any(int(v) >= CL_STAGE_FINAL for v in stages.values())
