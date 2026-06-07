# -*- coding: utf-8 -*-
"""
Плей-офф ЛЧ в ``mixed_schedule.json`` (фаза ``knockout``).

Правила месяцев календаря (day 6–10):
  - 1/16 (round_1) — всегда месяц 6
  - 1/8 (round_2) — месяц 7
  - 1/4 (round_3) — месяц 8
  - 1/2 (semi_finals) — месяц 9
  - финал — месяц 10, последний матч месяца

Новые матчи раунда вставляются **между** матчами лиг (случайно), без двух ``;cl;knockout``
подряд в одном месяце. После завершения всех стыков раунда N в журнале — в календарь
добавляется раунд N+1 (если его строк ещё нет).
"""
from __future__ import annotations

import json
import random
from pathlib import Path
from typing import Any

from champions_league.bracket_html import _load_cl_scores_and_penalties, _winner_two_leg
from champions_league.knockout_bracket import (
    SlotRef,
    default_cl_playoff_24_tree,
    get_default_round1_pairs,
    get_default_round2_seeds,
)
from match_results import find_cl_knockout_first_leg_record
from utils.schedule_by_months import MIXED_FILE

_ROOT = Path(__file__).resolve().parent.parent

# Ключ раунда в дереве → месяц календаря
CL_KNOCKOUT_ROUND_MONTH: dict[str, int] = {
    "round_1": 6,
    "round_2": 7,
    "round_3": 8,
    "semi_finals": 9,
    "final": 10,
}

# Подпись стадии, куда проходит победитель стыка
CL_KNOCKOUT_ADVANCE_STAGE_RU: dict[str, str] = {
    "round_1": "1/8",
    "round_2": "1/4",
    "round_3": "1/2",
    "semi_finals": "финал",
}

CL_KNOCKOUT_ROUND_ORDER: tuple[str, ...] = (
    "round_1",
    "round_2",
    "round_3",
    "semi_finals",
    "final",
)

_NEXT_ROUND: dict[str, str | None] = {
    "round_1": "round_2",
    "round_2": "round_3",
    "round_3": "semi_finals",
    "semi_finals": "final",
    "final": None,
}


def _norm(s: str) -> str:
    return (s or "").strip().title()


def _knockout_line(home: str, away: str) -> str:
    return f"{_norm(home)};{_norm(away)};cl;knockout"


def _two_leg_knockout_lines(home_first: str, away_first: str) -> list[str]:
    hf, af = _norm(home_first), _norm(away_first)
    return [_knockout_line(hf, af), _knockout_line(af, hf)]


def _is_cl_knockout_line(line: str) -> bool:
    parts = [x.strip() for x in (line or "").split(";")]
    return len(parts) >= 4 and parts[2].lower() == "cl" and parts[3].lower() == "knockout"


def _line_key(line: str) -> tuple[str, str]:
    parts = [x.strip() for x in line.split(";")]
    if len(parts) < 2:
        return ("", "")
    return (_norm(parts[0]), _norm(parts[1]))


def _resolve_slot(w: dict[tuple[str, int], str], x: str | SlotRef) -> str:
    if isinstance(x, str):
        return x
    return w[(x.round, x.tie)]


def _build_winners_map() -> dict[tuple[str, int], str]:
    """Победители стыков по журналу (как в HTML-сетке)."""
    scores, pen = _load_cl_scores_and_penalties()
    r1_pairs = list(get_default_round1_pairs())
    seeds = list(get_default_round2_seeds())
    w: dict[tuple[str, int], str] = {}

    for i, (h, a) in enumerate(r1_pairs):
        win = _winner_two_leg(scores, h, a, pen)
        w[("r1", i)] = win or f"победитель R1 #{i}"

    for i in range(8):
        seed = seeds[i]
        opp = w[("r1", i)]
        if opp.startswith("победитель"):
            w[("r2", i)] = f"победитель R2 #{i}"
        else:
            win = _winner_two_leg(scores, seed, opp, pen)
            w[("r2", i)] = win or f"победитель R2 #{i}"

    tree = default_cl_playoff_24_tree()
    for row in tree["round_3"]:
        ha = _resolve_slot(w, row["home_from"])
        hb = _resolve_slot(w, row["away_from"])
        if ha.startswith("победитель") or hb.startswith("победитель"):
            w[("r3", row["tie"])] = f"победитель R3 #{row['tie']}"
        else:
            win = _winner_two_leg(scores, ha, hb, pen)
            w[("r3", row["tie"])] = win or f"победитель R3 #{row['tie']}"

    for row in tree["semi_finals"]:
        ha = _resolve_slot(w, row["home_from"])
        hb = _resolve_slot(w, row["away_from"])
        if ha.startswith("победитель") or hb.startswith("победитель"):
            w[("sf", row["tie"])] = f"победитель ПФ #{row['tie']}"
        else:
            win = _winner_two_leg(scores, ha, hb, pen)
            w[("sf", row["tie"])] = win or f"победитель ПФ #{row['tie']}"

    return w


def _round_ties_home_first(round_key: str, w: dict[tuple[str, int], str]) -> list[tuple[str, str]] | None:
    """Пары (хозяева 1-го матча, гости) для раунда; ``None`` если раунд ещё не собрать."""
    tree = default_cl_playoff_24_tree()
    if round_key == "round_1":
        return list(get_default_round1_pairs())

    if round_key == "round_2":
        seeds = list(get_default_round2_seeds())
        out: list[tuple[str, str]] = []
        for i in range(8):
            opp = w.get(("r1", i), "")
            if not opp or opp.startswith("победитель"):
                return None
            out.append((seeds[i], opp))
        return out

    if round_key == "round_3":
        out = []
        for row in tree["round_3"]:
            ha = _resolve_slot(w, row["home_from"])
            hb = _resolve_slot(w, row["away_from"])
            if ha.startswith("победитель") or hb.startswith("победитель"):
                return None
            out.append((ha, hb))
        return out

    if round_key == "semi_finals":
        out = []
        for row in tree["semi_finals"]:
            ha = _resolve_slot(w, row["home_from"])
            hb = _resolve_slot(w, row["away_from"])
            if ha.startswith("победитель") or hb.startswith("победитель"):
                return None
            out.append((ha, hb))
        return out

    if round_key == "final":
        row = tree["final"]
        fh = _resolve_slot(w, row["home_from"])
        fa = _resolve_slot(w, row["away_from"])
        if fh.startswith("победитель") or fa.startswith("победитель"):
            return None
        return [(fh, fa)]

    return None


def knockout_lines_for_round(round_key: str) -> list[str] | None:
    """Строки ``mixed_schedule`` для раунда, если все пары известны."""
    w = _build_winners_map()
    ties = _round_ties_home_first(round_key, w)
    if ties is None:
        return None
    if round_key == "final":
        h, a = ties[0]
        return [_knockout_line(h, a)]
    lines: list[str] = []
    for h, a in ties:
        lines.extend(_two_leg_knockout_lines(h, a))
    return lines


def is_knockout_round_complete(round_key: str) -> bool:
    scores, pen = _load_cl_scores_and_penalties()
    ties = _round_ties_home_first(round_key, _build_winners_map())
    if ties is None:
        return False
    if round_key == "final":
        h, a = ties[0]
        from champions_league.bracket_html import _single_leg_score

        s = _single_leg_score(scores, h, a)
        return s[0] is not None
    for h, a in ties:
        if _winner_two_leg(scores, h, a, pen) is None:
            return False
    return True


def find_knockout_tie_for_match(home: str, away: str) -> tuple[str, str] | None:
    """
    Для матча нокаута: ``(round_key, home_first)`` или ``None``.
    """
    h, a = _norm(home), _norm(away)
    w = _build_winners_map()
    for round_key in CL_KNOCKOUT_ROUND_ORDER:
        ties = _round_ties_home_first(round_key, w)
        if not ties:
            continue
        for hf, af in ties:
            if (h, a) == (_norm(hf), _norm(af)) or (h, a) == (_norm(af), _norm(hf)):
                return round_key, _norm(hf)
    return None


def format_first_leg_score_html(home: str, away: str) -> str:
    """HTML-блок счёта первого матча стыка (для ответного матча)."""
    first = find_cl_knockout_first_leg_record(home, away)
    if not first:
        return ""
    fh = _norm(first["home"])
    fa = _norm(first["away"])
    hs, aws = int(first["home_score"]), int(first["away_score"])
    return (
        f"Первый матч стыка: <b>{fh}</b> {hs}:{aws} <b>{fa}</b>\n"
        f"(ответный: <b>{_norm(home)}</b> — <b>{_norm(away)}</b>)\n\n"
    )


def cl_knockout_second_leg_advance_message(
    home: str,
    away: str,
    *,
    penalties_by_team: dict[str, int] | None = None,
) -> str | None:
    """Сообщение «команда прошла в …» после ответного матча (оба матча в журнале)."""
    first = find_cl_knockout_first_leg_record(home, away)
    if not first:
        return None
    tie = find_knockout_tie_for_match(home, away)
    if not tie:
        return None
    round_key, home_first = tie
    scores, pen = _load_cl_scores_and_penalties()
    if penalties_by_team:
        x, y = _norm(home), _norm(away)
        k = (x, y) if x <= y else (y, x)
        pen = dict(pen)
        pen[k] = {_norm(t): int(v) for t, v in penalties_by_team.items()}
    away_first = _norm(first["away"]) if _norm(first["home"]) == home_first else _norm(first["home"])
    winner = _winner_two_leg(scores, home_first, away_first, pen)
    if not winner:
        return None
    stage = CL_KNOCKOUT_ADVANCE_STAGE_RU.get(round_key)
    if not stage:
        return f"<b>{winner}</b> — победитель Лиги чемпионов."
    return f"<b>{winner}</b> прошли в <b>{stage}</b> ЛЧ."


def _interleave_knockout_into_month(
    existing: list[str],
    new_lines: list[str],
    *,
    final_last: bool = False,
    seed: int | None = None,
) -> list[str]:
    rng = random.Random(seed)
    pool = list(existing)
    finals = []
    batch = list(new_lines)
    if final_last and batch:
        finals = [batch[-1]]
        batch = batch[:-1]

    for line in batch:
        candidates = [
            i
            for i in range(len(pool) + 1)
            if not (i > 0 and _is_cl_knockout_line(pool[i - 1]))
            and not (i < len(pool) and _is_cl_knockout_line(pool[i]))
        ]
        if not candidates:
            candidates = [len(pool)]
        pool.insert(rng.choice(candidates), line)

    pool.extend(finals)
    return pool


def _load_mixed_v3(path: Path) -> dict[str, Any]:
    with open(path, encoding="utf-8") as f:
        raw = json.load(f)
    if not isinstance(raw, dict) or int(raw.get("version") or 0) < 3:
        raise ValueError("Ожидается mixed_schedule v3")
    return raw


def _save_mixed_v3(doc: dict[str, Any], path: Path) -> None:
    with open(path, "w", encoding="utf-8") as f:
        json.dump(doc, f, ensure_ascii=False, indent=2)


def _knockout_schedule_line_keys(doc: dict[str, Any]) -> set[tuple[str, str]]:
    """Ключи только ``;cl;knockout`` — не путать с лигой ЛЧ или нац. календарём."""
    keys: set[tuple[str, str]] = set()
    for block in doc.get("rounds") or []:
        for ln in block.get("matches") or []:
            if isinstance(ln, str) and _is_cl_knockout_line(ln):
                k = _line_key(ln)
                keys.add(k)
                keys.add((k[1], k[0]))
    return keys


def _round_lines_in_schedule(doc: dict[str, Any], round_key: str) -> bool:
    lines = knockout_lines_for_round(round_key)
    if not lines:
        return False
    keys = _knockout_schedule_line_keys(doc)
    for ln in lines:
        k = _line_key(ln)
        if k not in keys and (k[1], k[0]) not in keys:
            return False
    return True


def _append_missing_knockout_lines(
    round_key: str,
    doc: dict[str, Any],
    *,
    seed: int | None = None,
) -> tuple[int, str]:
    """Дописать в ``doc`` недостающие строки раунда; вернуть (число добавленных, label)."""
    lines = knockout_lines_for_round(round_key)
    if not lines:
        raise ValueError(f"Раунд {round_key}: пары ещё не определены.")

    month = CL_KNOCKOUT_ROUND_MONTH[round_key]
    rounds = doc.get("rounds")
    if not isinstance(rounds, list):
        raise ValueError("Некорректный mixed_schedule.")

    block = None
    for b in rounds:
        if isinstance(b, dict) and int(b.get("day") or 0) == month:
            block = b
            break
    if block is None:
        block = {"day": month, "matches": []}
        rounds.append(block)
        rounds.sort(key=lambda x: int(x.get("day") or 0))

    existing = list(block.get("matches") or [])
    keys = _knockout_schedule_line_keys(doc)
    missing = [ln for ln in lines if _line_key(ln) not in keys]
    if not missing:
        return 0, round_key

    block["matches"] = _interleave_knockout_into_month(
        existing,
        missing,
        final_last=(round_key == "final"),
        seed=seed,
    )
    label = {
        "round_1": "1/16",
        "round_2": "1/8",
        "round_3": "1/4",
        "semi_finals": "1/2",
        "final": "финал",
    }.get(round_key, round_key)
    return len(missing), label


def ensure_knockout_round_in_schedule(
    round_key: str,
    *,
    path: Path | str | None = None,
    seed: int | None = None,
) -> tuple[bool, str]:
    """
    Идемпотентно добавить недостающие матчи раунда (только ``cl;knockout``).
    """
    p = Path(path) if path else MIXED_FILE
    lines = knockout_lines_for_round(round_key)
    if not lines:
        return False, f"Раунд {round_key}: пары ещё не определены."
    doc = _load_mixed_v3(p)
    try:
        n, label = _append_missing_knockout_lines(round_key, doc, seed=seed)
    except ValueError as e:
        return False, str(e)
    if n == 0:
        return False, f"Раунд {round_key}: все матчи уже в месяце {CL_KNOCKOUT_ROUND_MONTH[round_key]}."
    _save_mixed_v3(doc, p)
    return True, f"В календарь (месяц {CL_KNOCKOUT_ROUND_MONTH[round_key]}) добавлены матчи <b>{label}</b>: {n} шт."


def append_knockout_round_to_mixed_schedule(
    round_key: str,
    *,
    path: Path | str | None = None,
    seed: int | None = None,
) -> tuple[bool, str]:
    """
    Добавить в календарь все матчи раунда ``round_key`` (месяц по CL_KNOCKOUT_ROUND_MONTH).
    Возвращает (добавлено, сообщение).
    """
    return ensure_knockout_round_in_schedule(round_key, path=path, seed=seed)


def try_schedule_next_cl_knockout_rounds(
    *,
    path: Path | str | None = None,
    seed: int | None = None,
) -> list[str]:
    """
    После сыгранного стыка: если раунд N полностью завершён — добавить раунд N+1 в календарь.
    """
    msgs: list[str] = []
    for i, round_key in enumerate(CL_KNOCKOUT_ROUND_ORDER):
        nxt = _NEXT_ROUND.get(round_key)
        if not nxt:
            continue
        if not is_knockout_round_complete(round_key):
            continue
        added, msg = ensure_knockout_round_in_schedule(nxt, path=path, seed=seed)
        if added:
            msgs.append(msg)
    return msgs


def sync_cl_knockout_schedule_gaps(
    *,
    path: Path | str | None = None,
    seed: int | None = None,
) -> list[str]:
    """Дописать пропущенные нокаут-матчи для всех раундов, чьи пары уже известны."""
    msgs: list[str] = []
    for round_key in CL_KNOCKOUT_ROUND_ORDER:
        added, msg = ensure_knockout_round_in_schedule(round_key, path=path, seed=seed)
        if added:
            msgs.append(msg)
    return msgs


def cl_knockout_post_match_messages(
    home: str,
    away: str,
    league_code: str,
    cl_phase: str | None,
    *,
    penalties_by_team: dict[str, int] | None = None,
    schedule_path: Path | str | None = None,
) -> list[str]:
    """Сообщения после записи матча ЛЧ-нокаут (HTML)."""
    if (league_code or "").strip().lower() != "cl":
        return []
    ph = (cl_phase or "knockout").strip().lower()
    if ph != "knockout":
        return []
    out: list[str] = []
    adv = cl_knockout_second_leg_advance_message(
        home, away, penalties_by_team=penalties_by_team
    )
    if adv:
        out.append(adv)
    out.extend(try_schedule_next_cl_knockout_rounds(path=schedule_path))
    return out
