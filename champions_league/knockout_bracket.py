# -*- coding: utf-8 -*-
"""
Сетка плей-офф ЛЧ: 24 команды, как на турнирной сетке (single elimination).

  Round 1 — 8 стыков (посевы #9–#24), двухматчевые стыки → 8 победителей.
  Round 2 — 8 стыков: посевы #1–#8 (дом в 1-м матче) против победителя
            соответствующего стыка Round 1 (стык R1 #i → игра с посевом R2 #i).
  Round 3 — 4 стыка: победители (0,1), (2,3), (4,5), (6,7) из Round 2.
  Полуфинал — 2 стыка: победители (0,1) и (2,3) из Round 3.
  Финал — один матч (по умолчанию).

Строки матчей: ``хозяева;гости;cl`` (двухраундовые стыки — по две строки).

На сетке «Бильбао» = Athletic Club; в данных проекта используется имя «Атлетик».

Пары стыков и посевы для **картинки/HTML** задаются в ``data/cl_playoff_bracket.json``.
Если файла нет или он битый — используются плейсхолдеры «—». При «Завершить сезон»
вызывается ``reset_cl_playoff_bracket_json_to_placeholders()`` (см. ``utils.season_end``).
"""
from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable, Sequence

_PLACEHOLDER_R1: list[tuple[str, str]] = [("—", "—")] * 8
_PLACEHOLDER_SEEDS: list[str] = ["—"] * 8


def _bracket_json_path() -> Path:
    from utils.utils import PROJECT_ROOT

    return Path(PROJECT_ROOT) / "data" / "cl_playoff_bracket.json"


def load_cl_playoff_bracket_from_disk() -> tuple[list[tuple[str, str]], list[str]]:
    """Прочитать ``data/cl_playoff_bracket.json``; при ошибке — плейсхолдеры."""
    p = _bracket_json_path()
    if not p.is_file():
        return [tuple(p) for p in _PLACEHOLDER_R1], list(_PLACEHOLDER_SEEDS)
    try:
        raw = json.loads(p.read_text(encoding="utf-8"))
        pairs_raw = raw.get("round1_pairs") or []
        seeds_raw = raw.get("round2_seeds") or []
        pairs: list[tuple[str, str]] = []
        for item in pairs_raw[:8]:
            if not isinstance(item, (list, tuple)) or len(item) != 2:
                return [tuple(x) for x in _PLACEHOLDER_R1], list(_PLACEHOLDER_SEEDS)
            a, b = str(item[0]).strip(), str(item[1]).strip()
            pairs.append((a, b))
        while len(pairs) < 8:
            pairs.append(("—", "—"))
        seeds = [str(x).strip() if x is not None else "—" for x in seeds_raw[:8]]
        while len(seeds) < 8:
            seeds.append("—")
        return pairs, seeds
    except Exception:
        return [tuple(x) for x in _PLACEHOLDER_R1], list(_PLACEHOLDER_SEEDS)


def reset_cl_playoff_bracket_json_to_placeholders() -> None:
    """
    Записать ``data/cl_playoff_bracket.json`` плейсхолдерами (новый сезон / сетка без жребия).
    """
    p = _bracket_json_path()
    p.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "version": 1,
        "round1_pairs": [["—", "—"] for _ in range(8)],
        "round2_seeds": ["—"] * 8,
    }
    p.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )


def get_default_round1_pairs() -> list[tuple[str, str]]:
    p, _ = load_cl_playoff_bracket_from_disk()
    return p


def get_default_round2_seeds() -> list[str]:
    _, s = load_cl_playoff_bracket_from_disk()
    return s


def two_leg_match_strings(home_first_leg: str, away_first_leg: str) -> tuple[str, str]:
    """Первый матч дома у home_first_leg, ответный — дома у away_first_leg."""
    return (
        f"{home_first_leg};{away_first_leg};cl",
        f"{away_first_leg};{home_first_leg};cl",
    )


def round1_knockout_lines(r1_pairs: Sequence[tuple[str, str]]) -> list[str]:
    """16 строк ЛЧ для стыков Round 1 (по 2 на пару)."""
    if len(r1_pairs) != 8:
        raise ValueError(f"Ожидается 8 пар Round 1, получено {len(r1_pairs)}")
    out: list[str] = []
    for h, a in r1_pairs:
        out.extend(two_leg_match_strings(h, a))
    return out


def round_of_16_lines(r16_pairs: Sequence[tuple[str, str]]) -> list[str]:
    """Алиас: старый термин «1/8» здесь = Round 1 сетки из 24 команд."""
    return round1_knockout_lines(r16_pairs)


@dataclass(frozen=True)
class SlotRef:
    """Победитель стыка: round r1|r2|r3|sf, индекс стыка в этом раунде."""

    round: str
    tie: int

    def __str__(self) -> str:
        return f"W_{self.round.upper()}_{self.tie}"


def default_cl_playoff_24_tree() -> dict[str, Any]:
    """
    Связи раундов (как на сетке).

    Round 3: (победитель R2 стыков 0 и 1), (2 и 3), (4 и 5), (6 и 7).
    Полуфиналы: победители стыков R3 (0,1) и (2,3).
    Финал: победители двух полуфиналов.
    """
    r1 = [{"tie": i, "pair_index": i} for i in range(8)]

    seeds = get_default_round2_seeds()
    r2 = [
        {
            "tie": i,
            "seed": seeds[i],
            "plays_winner_of": SlotRef("r1", i),
        }
        for i in range(8)
    ]

    r3 = [
        {"tie": 0, "home_from": SlotRef("r2", 0), "away_from": SlotRef("r2", 1)},
        {"tie": 1, "home_from": SlotRef("r2", 2), "away_from": SlotRef("r2", 3)},
        {"tie": 2, "home_from": SlotRef("r2", 4), "away_from": SlotRef("r2", 5)},
        {"tie": 3, "home_from": SlotRef("r2", 6), "away_from": SlotRef("r2", 7)},
    ]

    sf = [
        {"tie": 0, "home_from": SlotRef("r3", 0), "away_from": SlotRef("r3", 1)},
        {"tie": 1, "home_from": SlotRef("r3", 2), "away_from": SlotRef("r3", 3)},
    ]

    final = {"home_from": SlotRef("sf", 0), "away_from": SlotRef("sf", 1)}
    return {
        "round_1": r1,
        "round_2": r2,
        "round_3": r3,
        "semi_finals": sf,
        "final": final,
    }


def bracket_cl_playoff_24(
    r1_pairs: Sequence[tuple[str, str]] | None = None,
    r2_seeds: Sequence[str] | None = None,
) -> dict[str, Any]:
    """Полное дерево с конкретными парами R1 и посевами R2."""
    pairs = list(r1_pairs) if r1_pairs is not None else get_default_round1_pairs()
    seeds = list(r2_seeds) if r2_seeds is not None else get_default_round2_seeds()
    if len(pairs) != 8 or len(seeds) != 8:
        raise ValueError("Нужно 8 пар R1 и 8 посевов R2")

    tree = default_cl_playoff_24_tree()
    ties_r1 = []
    for i, (h, a) in enumerate(pairs):
        leg1, leg2 = two_leg_match_strings(h, a)
        ties_r1.append(
            {
                "tie": i,
                "home_first_leg": h,
                "away_first_leg": a,
                "leg1": leg1,
                "leg2": leg2,
            }
        )
    tree["round_1"] = ties_r1
    tree["round_2"] = [
        {
            "tie": i,
            "seed": seeds[i],
            "plays_winner_of": SlotRef("r1", i),
            "note": f"посев играет с победителем стыка Round 1 #{i}",
        }
        for i in range(8)
    ]
    return tree


def bracket_with_team_pairs(r16_pairs: Sequence[tuple[str, str]]) -> dict[str, Any]:
    """Совместимость: дерево 24 команд с заданными парами Round 1 (посевы R2 по умолчанию)."""
    return bracket_cl_playoff_24(r1_pairs=r16_pairs, r2_seeds=None)


def _wmap(*rounds: tuple[str, Sequence[str]]) -> dict[tuple[str, int], str]:
    m: dict[tuple[str, int], str] = {}
    for rname, names in rounds:
        for i, n in enumerate(names):
            m[(rname, i)] = n
    return m


def _materialize_row(row: dict[str, Any], w: dict[tuple[str, int], str]) -> tuple[str, str]:
    hf = row["home_from"]
    af = row["away_from"]

    def one(x: str | SlotRef) -> str:
        if isinstance(x, str):
            return x
        return w[(x.round, x.tie)]

    return one(hf), one(af)


def full_cl_playoff_24_schedule(
    r1_pairs: Sequence[tuple[str, str]],
    winners_r1: Sequence[str],
    winners_r2: Sequence[str],
    winners_r3: Sequence[str],
    winners_sf: Sequence[str],
    *,
    r2_seeds: Sequence[str] | None = None,
    single_leg_final: bool = True,
) -> dict[str, list[str]]:
    """
    Все строки матчей, если известны победители каждого раунда (по индексам стыков).

    winners_r1..winners_sf: длины 8, 8, 4, 2.
    """
    if len(winners_r1) != 8 or len(winners_r2) != 8 or len(winners_r3) != 4 or len(winners_sf) != 2:
        raise ValueError("Нужно 8+8+4+2 победителей (r1, r2, r3, sf)")

    lines: dict[str, list[str]] = {
        "round_1": round1_knockout_lines(r1_pairs),
        "round_2": [],
        "round_3": [],
        "semi_finals": [],
        "final": [],
    }

    w = _wmap(
        ("r1", winners_r1),
        ("r2", winners_r2),
        ("r3", winners_r3),
        ("sf", winners_sf),
    )

    seeds = list(r2_seeds) if r2_seeds is not None else get_default_round2_seeds()
    for i in range(8):
        lines["round_2"].extend(two_leg_match_strings(seeds[i], w[("r1", i)]))

    tree = default_cl_playoff_24_tree()
    for row in tree["round_3"]:
        h, a = _materialize_row(row, w)
        lines["round_3"].extend(two_leg_match_strings(h, a))

    for row in tree["semi_finals"]:
        h, a = _materialize_row(row, w)
        lines["semi_finals"].extend(two_leg_match_strings(h, a))

    fh, fa = _materialize_row(
        {"home_from": tree["final"]["home_from"], "away_from": tree["final"]["away_from"]},
        w,
    )
    if single_leg_final:
        lines["final"].append(f"{fh};{fa};cl")
    else:
        lines["final"].extend(two_leg_match_strings(fh, fa))

    return lines


def flatten_schedule(
    lines_by_round: dict[str, list[str]],
    order: Iterable[str] | None = None,
) -> list[str]:
    order = order or ("round_1", "round_2", "round_3", "semi_finals", "final")
    out: list[str] = []
    for key in order:
        out.extend(lines_by_round.get(key, []))
    return out


def example_chalk_winners_24(r1_pairs: Sequence[tuple[str, str]]) -> tuple[list[str], list[str], list[str], list[str]]:
    """Победитель каждого стыка — первый в паре / посев (для тестового полного календаря)."""
    w1 = [p[0] for p in r1_pairs]
    seeds = list(get_default_round2_seeds())
    w2 = [seeds[i] for i in range(8)]
    r3_pairs = [(w2[0], w2[1]), (w2[2], w2[3]), (w2[4], w2[5]), (w2[6], w2[7])]
    w3 = [p[0] for p in r3_pairs]
    sf_pairs = [(w3[0], w3[1]), (w3[2], w3[3])]
    wsf = [p[0] for p in sf_pairs]
    return w1, w2, w3, wsf


def _slot_ru(x: str | SlotRef) -> str:
    """Подпись узла дерева для человекочитаемого вывода."""
    if isinstance(x, str):
        return x
    labels = {"r1": "1/16 (R1)", "r2": "1/8 (R2)", "r3": "четвертьфинал", "sf": "полуфинал"}
    return f"победитель стыка {labels.get(x.round, x.round)} #{x.tie}"


def format_cl_knockout_bracket_text(
    r1_pairs: Sequence[tuple[str, str]] | None = None,
    r2_seeds: Sequence[str] | None = None,
) -> str:
    """
    Текстовая сетка плей-офф ЛЧ для консоли (main.py и скрипты).

    Пары R1 и посевы R2 по умолчанию — из ``data/cl_playoff_bracket.json``; при необходимости
    передай свои ``r1_pairs`` / ``r2_seeds``.
    """
    tree = bracket_cl_playoff_24(r1_pairs=r1_pairs, r2_seeds=r2_seeds)
    out: list[str] = []
    out.append("Сетка плей-офф ЛЧ (24 команды)")
    out.append("Round 1 — восемь стыков, два матча; у первой команды в паре — дом в 1-м матче.")
    out.append("Round 2 — посевы играют с победителями соответствующих стыков R1.")
    out.append("")
    for t in tree["round_1"]:
        i = t["tie"]
        h, a = t["home_first_leg"], t["away_first_leg"]
        out.append(f"  R1 #{i}:  {h}  —  {a}")
    out.append("")
    out.append("Round 2 (двухматчевые; посев — дом в 1-м матче)")
    for t in tree["round_2"]:
        i = t["tie"]
        seed = t["seed"]
        out.append(f"  R2 #{i}:  {seed}  vs  победитель R1 #{i}")
    out.append("")
    out.append("Четвертьфиналы (R3)")
    for t in tree["round_3"]:
        h = _slot_ru(t["home_from"])
        a = _slot_ru(t["away_from"])
        out.append(f"  R3 #{t['tie']}:  {h}  —  {a}")
    out.append("")
    out.append("Полуфиналы")
    for t in tree["semi_finals"]:
        h = _slot_ru(t["home_from"])
        a = _slot_ru(t["away_from"])
        out.append(f"  ПФ #{t['tie']}:  {h}  —  {a}")
    out.append("")
    fh = _slot_ru(tree["final"]["home_from"])
    fa = _slot_ru(tree["final"]["away_from"])
    out.append(f"Финал:  {fh}  —  {fa}")
    out.append("")
    out.append(
        "(Пары R1 и посевы R2 — файл data/cl_playoff_bracket.json; сброс при завершении сезона.)"
    )
    return "\n".join(out)
