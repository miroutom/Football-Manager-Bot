# -*- coding: utf-8 -*-
"""
Визуальная сетка плей-офф ЛЧ: HTML (колонки, карточки).

Счета из match_results.json (league=cl), **без** записей с ``cl_phase``: ``league``/``group``
(групповая фаза). Для двухматчевого стыка в карточке:
каждая строка — только домашний матч этой команды (хозяева;гости в журнале).

При ничьей по сумме двух матчей можно внести пенальти: на любой из двух матчей стыка
добавьте поле ``penalties_by_team``: {"Интер": 5, "Франкфурт": 4} (см. match_results.py).
"""
from __future__ import annotations

import html as html_module
import os
import webbrowser
from pathlib import Path
from typing import Any

from champions_league.knockout_bracket import (
    DEFAULT_ROUND1_PAIRS,
    DEFAULT_ROUND2_SEEDS,
    SlotRef,
    default_cl_playoff_24_tree,
)
from match_results import load_records_and_keys
from utils.utils import PROJECT_ROOT

OUT_PATH = os.path.join(PROJECT_ROOT, "data", "cl_bracket_view.html")


def _norm(s: str) -> str:
    return (s or "").strip().title()


def _tie_key(a: str, b: str) -> tuple[str, str]:
    x, y = _norm(a), _norm(b)
    return (x, y) if x <= y else (y, x)


def _cl_record_is_group_phase(r: dict) -> bool:
    """Матч группы ЛЧ — не используем для сетки плей-офф."""
    p = str(r.get("cl_phase") or "").strip().lower()
    return p in ("league", "group", "лига", "группа", "groups")


def _load_cl_scores_and_penalties() -> tuple[
    dict[tuple[str, str], tuple[int, int]],
    dict[tuple[str, str], dict[str, int]],
]:
    """scores: (home,away)->(hs,aws). pen: sorted pair -> {team_name_norm: pens}."""
    records, _ = load_records_and_keys()
    scores: dict[tuple[str, str], tuple[int, int]] = {}
    pen: dict[tuple[str, str], dict[str, int]] = {}
    for r in records:
        if r.get("league") != "cl":
            continue
        if _cl_record_is_group_phase(r):
            continue
        hs, aws = r.get("home_score"), r.get("away_score")
        h = _norm(str(r.get("home", "")))
        a = _norm(str(r.get("away", "")))
        if hs is not None and aws is not None:
            scores[(h, a)] = (int(hs), int(aws))
        raw_pen = r.get("penalties_by_team")
        if isinstance(raw_pen, dict) and h and a:
            k = _tie_key(h, a)
            bucket = pen.setdefault(k, {})
            for tk, tv in raw_pen.items():
                if isinstance(tv, int):
                    bucket[_norm(str(tk))] = tv
    return scores, pen


def _two_leg_team_goals(
    scores: dict[tuple[str, str], tuple[int, int]], home_first: str, away_first: str
) -> tuple[tuple[int | None, int | None], tuple[int | None, int | None]]:
    leg1 = scores.get((home_first, away_first))
    leg2 = scores.get((away_first, home_first))
    g1 = (leg1[0], leg1[1]) if leg1 else (None, None)
    if leg2:
        g2 = (leg2[1], leg2[0])
    else:
        g2 = (None, None)
    return g1, g2


def _winner_two_leg(
    scores: dict[tuple[str, str], tuple[int, int]],
    home_first: str,
    away_first: str,
    pen: dict[tuple[str, str], dict[str, int]] | None = None,
) -> str | None:
    (a1, b1), (a2, b2) = _two_leg_team_goals(scores, home_first, away_first)
    if any(x is None for x in (a1, b1, a2, b2)):
        return None
    ta = a1 + a2  # type: ignore[operator]
    tb = b1 + b2  # type: ignore[operator]
    if ta > tb:
        return home_first
    if tb > ta:
        return away_first
    # Ничья по сумме — победитель по серии пенальти (журнал penalties_by_team)
    if pen:
        k = _tie_key(home_first, away_first)
        bucket = pen.get(k) or {}
        nh, na = _norm(home_first), _norm(away_first)
        ph = bucket.get(nh)
        pa = bucket.get(na)
        if ph is not None and pa is not None:
            if ph > pa:
                return home_first
            if pa > ph:
                return away_first
    return None


def _aggregate_tied(
    scores: dict[tuple[str, str], tuple[int, int]], home_first: str, away_first: str
) -> bool:
    (a1, b1), (a2, b2) = _two_leg_team_goals(scores, home_first, away_first)
    if any(x is None for x in (a1, b1, a2, b2)):
        return False
    return (a1 + a2) == (b1 + b2)  # type: ignore[operator]


def _single_leg_score(
    scores: dict[tuple[str, str], tuple[int, int]], home: str, away: str
) -> tuple[int | None, int | None]:
    t = scores.get((home, away))
    if not t:
        return None, None
    return t[0], t[1]


def _slot_resolve(w: dict[tuple[str, int], str], x: str | SlotRef) -> str:
    if isinstance(x, str):
        return x
    if isinstance(x, SlotRef):
        return w[(x.round, x.tie)]
    return str(x)


def build_cl_bracket_state(
    scores: dict[tuple[str, str], tuple[int, int]] | None = None,
    pen: dict[tuple[str, str], dict[str, int]] | None = None,
) -> dict[str, Any]:
    if scores is None or pen is None:
        s2, p2 = _load_cl_scores_and_penalties()
        if scores is None:
            scores = s2
        if pen is None:
            pen = p2
    r1_pairs = list(DEFAULT_ROUND1_PAIRS)
    seeds = list(DEFAULT_ROUND2_SEEDS)

    w: dict[tuple[str, int], str] = {}

    r1_matches = []
    for i, (h, a) in enumerate(r1_pairs):
        win = _winner_two_leg(scores, h, a, pen)
        w[("r1", i)] = win or f"победитель R1 #{i}"
        r1_matches.append({"tie": i, "home": h, "away": a})

    r2_matches = []
    for i in range(8):
        seed = seeds[i]
        opp = w[("r1", i)]
        if opp.startswith("победитель"):
            win = None
        else:
            win = _winner_two_leg(scores, seed, opp, pen)
        w[("r2", i)] = win or f"победитель R2 #{i}"
        r2_matches.append({"tie": i, "home": seed, "away": opp})

    tree = default_cl_playoff_24_tree()
    r3_matches = []
    for row in tree["round_3"]:
        ha = _slot_resolve(w, row["home_from"])
        hb = _slot_resolve(w, row["away_from"])
        if ha.startswith("победитель") or hb.startswith("победитель"):
            win = None
        else:
            win = _winner_two_leg(scores, ha, hb, pen)
        t = row["tie"]
        w[("r3", t)] = win or f"победитель R3 #{t}"
        r3_matches.append({"tie": t, "home": ha, "away": hb})

    sf_matches = []
    for row in tree["semi_finals"]:
        ha = _slot_resolve(w, row["home_from"])
        hb = _slot_resolve(w, row["away_from"])
        if ha.startswith("победитель") or hb.startswith("победитель"):
            win = None
        else:
            win = _winner_two_leg(scores, ha, hb, pen)
        t = row["tie"]
        w[("sf", t)] = win or f"победитель ПФ #{t}"
        sf_matches.append({"tie": t, "home": ha, "away": hb})

    fh = _slot_resolve(w, tree["final"]["home_from"])
    fa = _slot_resolve(w, tree["final"]["away_from"])
    if fh.startswith("победитель") or fa.startswith("победитель"):
        fs = (None, None)
    else:
        fs = _single_leg_score(scores, fh, fa)

    return {
        "round_1": r1_matches,
        "round_2": r2_matches,
        "round_3": r3_matches,
        "semi_finals": sf_matches,
        "final": {"home": fh, "away": fa, "score": fs},
    }


def _esc(s: str) -> str:
    return html_module.escape(s, quote=True)


def tie_score_pair_strings(
    home_first: str,
    away_first: str,
    scores: dict[tuple[str, str], tuple[int, int]],
    pen_by_tie: dict[tuple[str, str], dict[str, int]],
) -> tuple[tuple[str, str], tuple[str, str]]:
    """
    Две строки карточки как в журнале: ((команда, счёт), …).
    Счёт — «—:—», «2:1» или «2:1 (4)» при серии пенальти после ничьей по сумме.
    Используется HTML-сеткой и PNG (один источник правды).
    """
    ph = _norm(home_first)
    pa = _norm(away_first)
    leg1 = scores.get((ph, pa))
    leg2 = scores.get((pa, ph))

    def plain(rec: tuple[int, int] | None, pen_val: int | None) -> str:
        if not rec:
            return "—:—"
        s = f"{rec[0]}:{rec[1]}"
        if pen_val is not None:
            s += f" ({pen_val})"
        return s

    if ph.startswith("Победитель") or pa.startswith("Победитель"):
        return (
            (home_first, plain(leg1, None)),
            (away_first, plain(leg2, None)),
        )

    agg_tie = (
        leg1 is not None
        and leg2 is not None
        and _aggregate_tied(scores, ph, pa)
    )
    pens_map = pen_by_tie.get(_tie_key(ph, pa), {}) if agg_tie else {}
    p_home = pens_map.get(ph) if agg_tie else None
    p_away = pens_map.get(pa) if agg_tie else None

    if agg_tie and p_home is not None and p_away is not None:
        return (
            (home_first, plain(leg1, p_home)),
            (away_first, plain(leg2, p_away)),
        )
    return (
        (home_first, plain(leg1, None)),
        (away_first, plain(leg2, None)),
    )


def _score_string_to_html_span(score_plain: str) -> str:
    """Счёт как в tie_score_pair_strings → HTML со span dash/pen."""
    if score_plain == "—:—":
        return '<span class="dash">—</span>:<span class="dash">—</span>'
    if " (" in score_plain and score_plain.endswith(")"):
        left, pen = score_plain.rsplit(" (", 1)
        return f"{left} <span class=\"pen\">({pen[:-1]})</span>"
    return score_plain


def _fmt_tie_card(
    home_first: str,
    away_first: str,
    scores: dict[tuple[str, str], tuple[int, int]],
    pen_by_tie: dict[tuple[str, str], dict[str, int]],
) -> str:
    """
    Две строки: у каждой команды только её домашний матч в стыке (первый ходит home_first).
    При ничьей по сумме — суффикс (N) из penalties_by_team, если есть в журнале.
    """
    r1, r2 = tie_score_pair_strings(home_first, away_first, scores, pen_by_tie)
    rows: list[str] = []
    for name, score_plain in (r1, r2):
        score = _score_string_to_html_span(score_plain)
        rows.append(
            f'<div class="tie-line"><span class="tname">{_esc(name)}</span>'
            f'<span class="sc">{score}</span></div>'
        )
    return "".join(rows)


def _fmt_final(h: str, a: str, sc: tuple[int | None, int | None]) -> str:
    sh, sa = sc
    if sh is None or sa is None:
        score = '<span class="dash">—</span> : <span class="dash">—</span>'
    else:
        score = f"{sh} : {sa}"
    return (
        '<div class="final-card">'
        f'<div class="fname">{_esc(h)}</div>'
        f'<div class="fscore">{score}</div>'
        f'<div class="fname">{_esc(a)}</div>'
        "</div>"
    )


def _column(title: str, cards_html: list[str]) -> str:
    inner = "".join(f'<div class="card">{c}</div>' for c in cards_html)
    return f'<div class="col"><h2>{_esc(title)}</h2><div class="cards">{inner}</div></div>'


def build_cl_bracket_html_document() -> str:
    scores, pen_by_tie = _load_cl_scores_and_penalties()
    st = build_cl_bracket_state(scores, pen_by_tie)

    def cards_from_matches(matches: list[dict[str, Any]]) -> list[str]:
        out = []
        for m in matches:
            body = _fmt_tie_card(m["home"], m["away"], scores, pen_by_tie)
            out.append(body + '<div class="card-foot">—</div>')
        return out

    col1 = _column("1/16 (R1)", cards_from_matches(st["round_1"]))
    col2 = _column("1/8 (R2)", cards_from_matches(st["round_2"]))
    col3 = _column("1/4 финала", cards_from_matches(st["round_3"]))
    col4 = _column("1/2 финала", cards_from_matches(st["semi_finals"]))
    f = st["final"]
    col5 = _column("Финал", [_fmt_final(f["home"], f["away"], f["score"]) + '<div class="card-foot">—</div>'])

    css = """
    * { box-sizing: border-box; }
    body {
      margin: 0;
      font-family: system-ui, -apple-system, "Segoe UI", Roboto, sans-serif;
      background: linear-gradient(165deg, #0a1628 0%, #152a45 40%, #0d1830 100%);
      color: #e8eef5;
      min-height: 100vh;
      padding: 24px 16px 48px;
    }
    h1 {
      text-align: center;
      font-weight: 600;
      font-size: 1.35rem;
      margin-bottom: 8px;
      letter-spacing: 0.02em;
    }
    .sub {
      text-align: center;
      font-size: 0.85rem;
      opacity: 0.75;
      margin-bottom: 28px;
      max-width: 760px;
      margin-left: auto;
      margin-right: auto;
      line-height: 1.45;
    }
    .bracket {
      display: flex;
      flex-wrap: nowrap;
      gap: 14px;
      justify-content: center;
      align-items: flex-start;
      overflow-x: auto;
      padding-bottom: 16px;
    }
    .col {
      flex: 0 0 auto;
      min-width: 176px;
      max-width: 220px;
    }
    .col h2 {
      font-size: 0.72rem;
      text-transform: uppercase;
      letter-spacing: 0.06em;
      text-align: center;
      margin: 0 0 12px;
      opacity: 0.9;
      font-weight: 600;
    }
    .cards {
      display: flex;
      flex-direction: column;
      gap: 10px;
    }
    .card {
      background: #fff;
      color: #0a1628;
      border-radius: 10px;
      padding: 10px 12px 8px;
      box-shadow: 0 4px 14px rgba(0,0,0,0.25);
    }
    .tie-line {
      display: flex;
      justify-content: space-between;
      align-items: baseline;
      gap: 10px;
      font-size: 0.82rem;
      padding: 5px 0;
    }
    .tie-line .tname {
      font-weight: 600;
      flex: 1;
      min-width: 0;
    }
    .tie-line .sc {
      font-weight: 700;
      font-variant-numeric: tabular-nums;
      white-space: nowrap;
      text-align: right;
    }
    .tie-line .pen {
      font-weight: 700;
      color: #143a5c;
    }
    .dash { opacity: 0.45; font-weight: 600; }
    .card-foot {
      text-align: center;
      color: #9aa8b8;
      font-size: 0.95rem;
      margin-top: 4px;
      padding-top: 8px;
      border-top: 1px solid #e0e6ec;
      letter-spacing: 0.12em;
    }
    .final-card { text-align: center; padding: 4px 0; }
    .final-card .fname { font-weight: 600; font-size: 0.82rem; margin: 4px 0; }
    .final-card .fscore {
      font-size: 1.05rem;
      font-weight: 700;
      font-variant-numeric: tabular-nums;
      margin: 6px 0;
      color: #143a5c;
    }
    footer {
      text-align: center;
      margin-top: 32px;
      font-size: 0.75rem;
      opacity: 0.55;
      max-width: 720px;
      margin-left: auto;
      margin-right: auto;
      line-height: 1.4;
    }
    """

    body = f"""
    <h1>Лига чемпионов — сетка плей-офф (проект)</h1>
    <p class="sub">В каждой строке — только домашний матч команды в стыке (как в журнале: хозяева первыми).
    У каждой команды — её домашний матч в стыке; ответный может быть ещё не сыгран (тогда прочерк).
    Группа ЛЧ: <code>cl_phase: &quot;league&quot;</code> в JSON — сетка такие матчи пропускает.
    Из главного меня матч-дня ЛЧ пишется как <code>knockout</code>. Старые записи без поля
    учитываются; групповые допишите <code>league</code> вручную, если мешают.
    Ничья в стыке: <code>penalties_by_team</code> — см. <code>match_results.py</code>.</p>
    <div class="bracket">
      {col1}{col2}{col3}{col4}{col5}
    </div>
    <footer>Файл перезаписывается при открытии сетки из меню (k).</footer>
    """

    return f"""<!DOCTYPE html>
<html lang="ru">
<head>
  <meta charset="utf-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1" />
  <title>Сетка ЛЧ</title>
  <style>{css}</style>
</head>
<body>
{body}
</body>
</html>
"""


def write_cl_bracket_html(path: str | None = None) -> str:
    """Записать HTML и вернуть абсолютный путь."""
    out = path or OUT_PATH
    parent = os.path.dirname(out)
    if parent:
        os.makedirs(parent, exist_ok=True)
    text = build_cl_bracket_html_document()
    with open(out, "w", encoding="utf-8") as f:
        f.write(text)
    return os.path.abspath(out)


def open_cl_bracket_in_browser(path: str | None = None) -> str:
    """Сохранить HTML и открыть в браузере по умолчанию."""
    p = write_cl_bracket_html(path)
    try:
        webbrowser.open(Path(p).as_uri())
    except Exception:
        pass
    return p
