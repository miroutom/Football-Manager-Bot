#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Слияние двух match_results.json (v2) по тому же ключу, что и в match_results.record_key.

Сценарий: на сервере сделали git stash с локальными играми из бота, затем git pull
подтянул репозиторий — рабочий файл с Git, застешенные матчи в stash.

  git show 'stash@{0}:match_results.json' > /tmp/mr_stash.json
  python3 scripts/merge_match_results_json.py match_results.json /tmp/mr_stash.json -o match_results.merged.json

Правила: сначала все записи из base (порядок сохраняем), затем из incoming только
новые ключи; при совпадении ключа — лучше запись с полным счётом, иначе --prefer
(first|second) при двух вариантах с полным счётом.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from copy import deepcopy
from typing import Any

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

from match_results import _norm, record_key  # noqa: E402


def _parse_v2_file(path: str) -> list[dict[str, Any]]:
    with open(path, encoding="utf-8") as f:
        raw = json.load(f)
    if not isinstance(raw, dict) or raw.get("version") != 2:
        raise SystemExit(f"Нужен match_results v2, получено: {path!r}")
    matches = raw.get("matches", [])
    out: list[dict[str, Any]] = []
    for m in matches:
        if not isinstance(m, dict):
            continue
        h = _norm(m.get("home", ""))
        a = _norm(m.get("away", ""))
        t = m.get("league")
        if not t or not h or not a:
            continue
        rec: dict[str, Any] = {
            "home": h,
            "away": a,
            "league": t,
            "home_score": m.get("home_score"),
            "away_score": m.get("away_score"),
            "day": m.get("day"),
        }
        if "cl_phase" in m and m.get("cl_phase") is not None:
            rec["cl_phase"] = m.get("cl_phase")
        if "penalties_by_team" in m and isinstance(m.get("penalties_by_team"), dict):
            rec["penalties_by_team"] = m.get("penalties_by_team")
        out.append(rec)
    return out


def _key(rec: dict[str, Any]) -> tuple:
    return record_key(
        rec["home"],
        rec["away"],
        str(rec["league"]),
        _rec=rec,
    )


def _is_scored(rec: dict[str, Any]) -> bool:
    hs, aws = rec.get("home_score"), rec.get("away_score")
    return hs is not None and aws is not None


def _merge_one(ra: dict[str, Any], rb: dict[str, Any], *, prefer: str) -> dict[str, Any]:
    if _is_scored(rb) and not _is_scored(ra):
        return deepcopy(rb)
    if _is_scored(ra) and not _is_scored(rb):
        return deepcopy(ra)
    if _is_scored(ra) and _is_scored(rb):
        return deepcopy(rb) if prefer == "second" else deepcopy(ra)
    return deepcopy(rb) if prefer == "second" else deepcopy(ra)


def merge_records(
    first: list[dict[str, Any]],
    second: list[dict[str, Any]],
    *,
    prefer: str = "second",
) -> list[dict[str, Any]]:
    m: dict[tuple, dict[str, Any]] = {}
    order: list[tuple] = []
    for r in first:
        k = _key(r)
        m[k] = deepcopy(r)
        order.append(k)
    for r in second:
        k = _key(r)
        if k not in m:
            m[k] = deepcopy(r)
            order.append(k)
        else:
            m[k] = _merge_one(m[k], r, prefer=prefer)
    return [m[k] for k in order]


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("base", help="после git pull (актуальная ветка)")
    ap.add_argument("incoming", help="копия из stash — обычно важнее по счетам (second)")
    ap.add_argument("-o", "--output", required=True)
    ap.add_argument(
        "--prefer",
        choices=("first", "second"),
        default="second",
        help="при двух полных счетах: чей оставить (второй = копия с бота с сервера)",
    )
    args = ap.parse_args()

    a = _parse_v2_file(args.base)
    b = _parse_v2_file(args.incoming)
    out = merge_records(a, b, prefer=args.prefer)
    with open(args.output, "w", encoding="utf-8") as f:
        json.dump(
            {"version": 2, "matches": out},
            f,
            ensure_ascii=False,
            indent=2,
        )
    print(f"OK: {len(out)} матчей → {args.output}")


if __name__ == "__main__":
    main()
