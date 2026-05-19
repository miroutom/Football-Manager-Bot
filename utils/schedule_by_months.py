# -*- coding: utf-8 -*-
"""
Смешанное расписание v3: 10 «месяцев» (day 1..10).
Нац. лиги: два круга (``2*(N-1)`` туров при ``N`` командах); первая половина туров в месяцах 1–5,
вторая — в 6–10. Расклад по месяцам подстраивается под число туров (8 команд → 7+7).
ЛЧ: только лиговая фаза — 8 матчей на команду в месяцах 1–5 (без дерби по стране);
   месяцы 6–10 без матчей ЛЧ (плей-офф задаётся позже).

После генерации ``build_and_write_mixed_v3`` по умолчанию из расписания выбрасываются строки,
для которых в ``match_results.json`` уже есть сыгранный матч (со счётом, не simulation).
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

# Расклад первой половины нац. туров на 5 месяцев (сумма паттерна = числу туров в половине).
# При 10 командах: 9+9 туров, паттерн (2,2,2,2,1). При 8: 7+7 — см. ``_national_chunk_pattern``.
NATIONAL_ROUNDS_FIRST_HALF = 9  # legacy константа; фактически считается от числа команд
NATIONAL_ROUND_MONTHS_1_5 = (2, 2, 2, 2, 1)  # сумма 9 — только для 10 команд; иначе динамика


def _national_chunk_pattern(n_rounds_in_half: int) -> tuple[int, int, int, int, int]:
    """Раскидать ``n_rounds_in_half`` туров по 5 «месяцам» (целые неотрицательные, сумма = n)."""
    n = int(n_rounds_in_half)
    if n < 0:
        raise ValueError(n)
    base, rem = divmod(n, 5)
    return tuple(base + (1 if i < rem else 0) for i in range(5))
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


def _build_cl_league_phase_eight_rounds(
    cl_teams: list[str],
    rng: random.Random,
) -> list[list[tuple[str, str]]] | None:
    """
    8 туров ЛЧ (30 команд, 15 матчей в туре): без соперников из одной страны,
    каждая команда — 8 разных соперников. Обратные матчи не входят (плей-офф позже).
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
        if ok and len(first) == CL_ROUNDS_HALF:
            return first
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
        c = _build_cl_league_phase_eight_rounds(cl_teams, rng)
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
        n_tot = len(full)
        n_first = n_tot // 2
        chunk1 = _national_chunk_pattern(n_first)
        chunk2 = _national_chunk_pattern(n_tot - n_first)
        first_half = full[:n_first]
        second_half = full[n_first:]
        m1 = _spread_rounds_to_months(first_half, 1, chunk1)
        m2 = _spread_rounds_to_months(second_half, 6, chunk2)
        for m, lines in {**m1, **m2}.items():
            months[m].extend(lines)

    # --- ЛЧ: только месяцы 1–5 (8 туров), месяцы 6–10 без ЛЧ
    cidx = 0
    for i, n in enumerate(CL_ROUNDS_MONTHS_1_5):
        m = 1 + i
        for _ in range(n):
            months[m].extend(_cl_rounds_to_lines(cl_rounds[cidx]))
            cidx += 1
    assert cidx == CL_ROUNDS_HALF, cidx

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


def _norm_schedule_name(s: str) -> str:
    return (s or "").strip().title()


def _normalize_cl_phase_journal(raw) -> str:
    """Как ``match_results._normalize_cl_phase`` для ключа журнала."""
    if raw is None:
        return "knockout"
    p = str(raw).strip().lower()
    if p in ("league", "group", "лига", "группа", "гр", "groups"):
        return "league"
    return "knockout"


def _journal_record_key_tuple(rec: dict) -> tuple | None:
    """Ключ как в ``match_results.record_key`` (в т.ч. ЛЧ с фазой)."""
    if not isinstance(rec, dict):
        return None
    lg = rec.get("league")
    if not lg:
        return None
    h = _norm_schedule_name(str(rec.get("home") or ""))
    a = _norm_schedule_name(str(rec.get("away") or ""))
    if lg != "cl":
        return (h, a, str(lg).strip())
    raw = rec.get("cl_phase")
    if raw is None or str(raw).strip() == "":
        phase = "league"
    else:
        phase = _normalize_cl_phase_journal(raw)
    return (h, a, "cl", phase)


def _journal_played_keys_for_strip() -> set[tuple]:
    """
    Ключи записей журнала со счётом (реальная игра), для вычёркивания из расписания.

    Читает ``match_results.json`` напрямую — без импорта ``match_results`` (нет цепочки SQLAlchemy).
    """
    path = _ROOT / "match_results.json"
    if not path.is_file():
        return set()
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return set()
    matches = raw.get("matches") if isinstance(raw, dict) else raw
    if not isinstance(matches, list):
        return set()
    out: set[tuple] = set()
    for rec in matches:
        if not isinstance(rec, dict):
            continue
        et = (rec.get("entry_type") or "play").strip().lower()
        if et == "simulation":
            continue
        hs, aws = rec.get("home_score"), rec.get("away_score")
        if hs is None or aws is None:
            continue
        try:
            int(hs)
            int(aws)
        except (TypeError, ValueError):
            continue
        k = _journal_record_key_tuple(rec)
        if k:
            out.add(k)
    return out


def _mixed_schedule_line_played(match_str: str, played_keys: set[tuple]) -> bool:
    """Строка календаря совпадает с сыгранным матчем (учёт обеих фаз ЛЧ в журнале)."""
    parts = [x.strip() for x in match_str.split(";")]
    if len(parts) < 3:
        return False
    home, away, lg = parts[0], parts[1], parts[2]
    h = _norm_schedule_name(home)
    a = _norm_schedule_name(away)
    if lg != "cl":
        return (h, a, lg) in played_keys
    # ЛЧ: в журнале одно направление пары, в новом календаре после перегенерации —
    # то же столкновение может быть в обратном порядке (одна встреча на пару за фазу).
    for phase in ("league", "knockout"):
        if (h, a, "cl", phase) in played_keys or (a, h, "cl", phase) in played_keys:
            return True
    return False


def strip_played_matches_from_v3_document(doc: dict[str, Any]) -> dict[str, Any]:
    """
    Удалить из документа v3 все строки матчей, которые уже есть в журнале со счётом.

    Возвращает новый dict (копия с отфильтрованными ``matches`` по месяцам).
    """
    played_keys = _journal_played_keys_for_strip()
    if not played_keys:
        return doc
    rounds = doc.get("rounds")
    if not isinstance(rounds, list):
        return doc
    new_rounds: list[dict[str, Any]] = []
    for block in rounds:
        if not isinstance(block, dict):
            new_rounds.append(block)
            continue
        matches = block.get("matches") or []
        if not isinstance(matches, list):
            new_rounds.append(block)
            continue
        kept: list[str] = []
        for ln in matches:
            if not isinstance(ln, str):
                kept.append(ln)
                continue
            if _mixed_schedule_line_played(ln, played_keys):
                continue
            kept.append(ln)
        nb = dict(block)
        nb["matches"] = kept
        new_rounds.append(nb)
    out = dict(doc)
    out["rounds"] = new_rounds
    return out


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
    *,
    strip_played: bool = True,
) -> str:
    p = Path(path) if path else MIXED_FILE
    doc = generate_mixed_schedule_v3(cl_teams=cl_teams, seed=seed)
    if strip_played:
        doc = strip_played_matches_from_v3_document(doc)
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
    """Подпись периода в UI (в календаре v3 и в боте — всегда «месяц»)."""
    return "Месяц"


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
