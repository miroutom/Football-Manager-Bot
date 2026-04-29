# -*- coding: utf-8 -*-
"""
Смешанное расписание v3: 10 «месяцев» (day 1..10).
Нац. лиги: туры 1–9 в месяцах 1–5, туры 10–18 в 6–10; в первой половине нет пары
и обратной (второй круг только в 6–10).
ЛЧ: 8+8 матчей, без соперников из той же страны; плей-офф не генерируется.
"""
from __future__ import annotations

import json
import random
from pathlib import Path
from typing import Any

from config.leagues_config import rpl, england, spain, italy, germany

from utils.schedule_generator import double_round_robin
from utils.team_country import same_country

_ROOT = Path(__file__).resolve().parent.parent
MIXED_FILE = _ROOT / "mixed_schedule.json"

# Расклад 9 туров на 5 месяцев: по два тура в четырёх, один в пятом
NATIONAL_ROUNDS_FIRST_HALF = 9
NATIONAL_ROUND_MONTHS_1_5 = (2, 2, 2, 2, 1)  # сумма 9
CL_ROUNDS_HALF = 8
CL_ROUNDS_MONTHS_1_5 = (2, 2, 2, 1, 1)  # сумма 8


def _title_team(t: str) -> str:
    s = (t or "").strip()
    return s.title() if s else s


def _line(h: str, a: str, code: str) -> str:
    return f"{h};{a};{code}"


def _one_perfect_round(
    team_names: list[str],
    rng: random.Random,
    used_edges: set[tuple[str, str]],
) -> list[tuple[str, str]] | None:
    """
    Подобрать полноценный тур: 15 пар, без same_country и без рёбер из used_edges.
    Backtracking с эвристикой (сначала вершина с меньшим числом вариантов).
    team_names: 30 уникальных строк Title.
    """
    names = list(team_names)
    if len(names) % 2:
        return None

    def can_pair(a: str, b: str) -> bool:
        if same_country(a, b):
            return False
        e = (a, b) if a < b else (b, a)
        if e in used_edges:
            return False
        return True

    def rec(unfixed: list[str]) -> list[tuple[str, str]] | None:
        if not unfixed:
            return []
        # выбрать u с минимальной степеней среди кандидатов
        best_u: str | None = None
        best_cands: list[str] = []
        best_n = 999
        for u in unfixed:
            cands = [v for v in unfixed if v != u and can_pair(u, v)]
            if not cands:
                return None
            if len(cands) < best_n:
                best_n = len(cands)
                best_u = u
                best_cands = cands
        assert best_u is not None
        rng.shuffle(best_cands)
        u = best_u
        rest0 = [x for x in unfixed if x != u]
        for v in best_cands:
            if v not in rest0:
                continue
            e = (u, v) if u < v else (v, u)
            if e in used_edges:
                continue
            sub = rec([x for x in rest0 if x != v])
            if sub is not None:
                return [(u, v)] + sub
        return None

    return rec(names)


def _build_cl_sixteen_rounds(
    cl_teams: list[str],
    rng: random.Random,
) -> list[list[tuple[str, str]]] | None:
    """
    8 туров (каждая команда 8 соперников) + 8 обратных встреч.
    """
    teams = [_title_team(t) for t in cl_teams]
    if len(teams) != 30:
        return None
    if len(set(teams)) != 30:
        return None

    for _ in range(3000):
        used: set[tuple[str, str]] = set()
        first: list[list[tuple[str, str]]] = []
        ok = True
        for _r in range(CL_ROUNDS_HALF):
            m = _one_perfect_round(teams, rng, used)
            if m is None:
                ok = False
                break
            for a, b in m:
                e = (a, b) if a < b else (b, a)
                used.add(e)
            first.append(m)
        if not ok or len(first) != CL_ROUNDS_HALF:
            continue

        second: list[list[tuple[str, str]]] = []
        for r in first:
            rev = [(a, b) for b, a in r]
            second.append(rev)
        return first + second
    return None


def _national_double_schedule(league_code: str, team_list: list[str]) -> list[list[str]]:
    """18 туров в формате list[str] — строка слота; teams lowercase из конфига."""
    t_title = [_title_team(t) for t in team_list]
    rr = double_round_robin(t_title)
    out: list[list[str]] = []
    for r in rr:
        out.append([_line(h, a, league_code) for h, a in r])
    return out


def _spread_rounds_to_months(
    rounds: list[list[str]],
    start_month: int,
    chunk_pattern: tuple[int, ...],
) -> dict[int, list[str]]:
    """
    Раскладывает туры подряд в месяцы start_month, start_month+1, …
    chunk_pattern — сколько туров в каждом из len(chunk_pattern) месяцев.
    """
    if sum(chunk_pattern) != len(rounds):
        raise ValueError("chunk_pattern does not cover all rounds")
    by_month: dict[int, list[str]] = {}
    i = 0
    for mi, n in enumerate(chunk_pattern):
        m = start_month + mi
        chunk: list[str] = []
        for _ in range(n):
            for line in rounds[i]:
                chunk.append(line)
            i += 1
        by_month[m] = by_month.get(m, []) + chunk
    return by_month


def _cl_rounds_to_lines(
    round_pairs: list[tuple[str, str]],
) -> list[str]:
    return [_line(h, a, "cl") for h, a in round_pairs]


def generate_mixed_schedule_v3(
    *,
    cl_teams: list[str] | None = None,
    seed: int | None = None,
) -> dict[str, Any]:
    from champions_league.cl_format import get_cl_participants

    rng = random.Random(seed)
    if cl_teams is None:
        cl_teams = get_cl_participants()

    cl_rounds: list[list[tuple[str, str]]] | None = None
    for attempt in range(5000):
        c = _build_cl_sixteen_rounds(cl_teams, rng)
        if c is not None:
            cl_rounds = c
            break
    if cl_rounds is None:
        raise RuntimeError("Не удалось сгенерировать 8 туров ЛЧ без дерби по стране")

    months: dict[int, list[str]] = {i: [] for i in range(1, 11)}

    # --- национальные: половины и расклад по месяцам
    for teams, code in [
        (rpl, "rpl"),
        (england, "eng"),
        (spain, "esp"),
        (italy, "ita"),
        (germany, "ger"),
    ]:
        full = _national_double_schedule(code, list(teams))
        first9 = full[:NATIONAL_ROUNDS_FIRST_HALF]
        second9 = full[NATIONAL_ROUNDS_FIRST_HALF :]
        m1 = _spread_rounds_to_months(first9, 1, NATIONAL_ROUND_MONTHS_1_5)
        m2 = _spread_rounds_to_months(second9, 6, NATIONAL_ROUND_MONTHS_1_5)
        for m, lines in {**m1, **m2}.items():
            months[m].extend(lines)

    # --- ЛЧ: 8 + 8
    cl_first8 = cl_rounds[:CL_ROUNDS_HALF]
    cl_sec8 = cl_rounds[CL_ROUNDS_HALF:]
    cidx = 0
    for i, n in enumerate(CL_ROUNDS_MONTHS_1_5):
        m = 1 + i
        for _ in range(n):
            months[m].extend(_cl_rounds_to_lines(cl_first8[cidx]))
            cidx += 1
    assert cidx == 8, cidx

    cidx = 0
    for i, n in enumerate(CL_ROUNDS_MONTHS_1_5):
        m = 6 + i
        for _ in range(n):
            months[m].extend(_cl_rounds_to_lines(cl_sec8[cidx]))
            cidx += 1
    assert cidx == 8, cidx

    # перемешивать внутри месяца, чтобы не было жёсткого пор лиг
    for m in months:
        rng.shuffle(months[m])

    out_list: list[dict[str, Any]] = []
    for day in range(1, 11):
        out_list.append({"day": day, "matches": months[day]})

    return {
        "version": 3,
        "kind": "months",
        "label": "month",  # UI: «месяц», не «матч-день»
        "rounds": out_list,
    }


def _legacy_list_from_v3(doc: dict[str, Any]) -> list[dict[str, Any]]:
    """Список как у старого json: [{day, matches}, …] + метаданные в первом элементе нет — несём version отдельно в load."""
    rounds = doc.get("rounds")
    if isinstance(rounds, list):
        return list(rounds)
    return []


def build_and_write_mixed_v3(
    cl_teams: list[str] | None = None,
    path: Path | str | None = None,
    seed: int | None = None,
) -> str:
    p = Path(path) if path else MIXED_FILE
    doc = generate_mixed_schedule_v3(cl_teams=cl_teams, seed=seed)
    p.parent.mkdir(parents=True, exist_ok=True)
    with open(p, "w", encoding="utf-8") as f:
        json.dump(doc, f, ensure_ascii=False, indent=2)
    return str(p)


def v3_to_flat_schedule(doc: dict[str, Any] | list) -> list[dict[str, Any]]:
    """Превратить документ (или плоский список) в list[{day, matches}] для main/bot."""
    if isinstance(doc, list):
        return doc
    if not isinstance(doc, dict):
        return []
    v = int(doc.get("version") or 0)
    if v >= 3 and "rounds" in doc:
        r = _legacy_list_from_v3(doc)
        if r:
            return r
    r2 = doc.get("months")
    if isinstance(r2, list):
        return r2
    return []


def is_schedule_v3(data: list[dict] | dict) -> bool:
    if isinstance(data, dict) and int(data.get("version") or 0) >= 3:
        return True
    return False


def mixed_slot_label_from_raw(raw: Any) -> str:
    """Подпись для UI: «Месяц» (v3) или «Матч-день» (старый список)."""
    if isinstance(raw, dict) and int(raw.get("version") or 0) >= 3:
        return "Месяц"
    return "Матч-день"


def read_mixed_slot_label(path: Path | str | None = None) -> str:
    """Короткая подпись периода для печати (без чтения всего v3-дерева)."""
    p = Path(path) if path else MIXED_FILE
    if not p.is_file():
        return "Месяц"
    with open(p, encoding="utf-8") as f:
        raw: Any = json.load(f)
    return mixed_slot_label_from_raw(raw)


def load_parsed_mixed(path: Path | str | None = None) -> tuple[list[dict[str, Any]], str]:
    """
    Загрузить ``mixed_schedule.json`` как плоский список ``[{day, matches}, …]``.
    Если файла нет — сгенерировать v3 (10 месяцев) и записать.
    """
    p = Path(path) if path else MIXED_FILE
    if not p.is_file():
        build_and_write_mixed_v3(path=p)
    with open(p, encoding="utf-8") as f:
        raw: Any = json.load(f)
    label = mixed_slot_label_from_raw(raw)
    if isinstance(raw, list):
        return raw, label
    if isinstance(raw, dict) and int(raw.get("version") or 0) >= 3:
        flat = v3_to_flat_schedule(raw)
        return (flat, label) if flat else ([], label)
    return [], label
