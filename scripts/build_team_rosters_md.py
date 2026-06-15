#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Ростеры всех клубов со статой и контекстом за 2 сезона — для подачи в LLM (GLM).

  python3 scripts/build_team_rosters_md.py
  python3 scripts/build_team_rosters_md.py -o data/teams_rosters_for_glm.md
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import Any

_ROOT = Path(__file__).resolve().parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))


def _load_cl_participants() -> set[str]:
    path = _ROOT / "data" / "cl_participants_dynamic.txt"
    if not path.is_file():
        return set()
    out: set[str] = set()
    for line in path.read_text(encoding="utf-8").splitlines():
        t = line.strip()
        if t and not t.startswith("#"):
            out.add(t)
    return out


def _player_line(row) -> str:
    from utils.transfer_advice import player_surname

    d = row.detail or {}
    sur = (player_surname(row.name) or row.name).strip()
    parts = [f"{sur} {row.position} {row.overall}"]
    if row.verdict:
        parts[0] += f" ({row.verdict})"
    stat_bits: list[str] = []
    m = int(d.get("matches") or 0)
    g = int(d.get("goals") or 0)
    a = int(d.get("assists") or 0)
    if m > 0:
        if row.is_goalkeeper:
            cs = int(d.get("clean_sheets") or 0)
            stat_bits.append(f"{m} матчей, {cs} сухих")
        else:
            stat_bits.append(f"{m} матчей, {g} голов, {a} передач")
    ovr_hist = d.get("ovr_history")
    if ovr_hist:
        stat_bits.append(f"рейтинг {ovr_hist}")
    dr = int(d.get("depth_rank") or row.depth_rank or 0)
    if dr > 0:
        stat_bits.append(f"глубина {dr}")
    if stat_bits:
        parts.append(" — " + "; ".join(stat_bits))
    return "".join(parts)


def _squad_status(row) -> str:
    d = row.detail or {}
    st = (d.get("status") or "").strip().lower()
    if st in ("start", "bench", "reserve"):
        return st
    if d.get("in_start"):
        return "start"
    return "reserve"


def _group_rows(rows) -> tuple[list, list, list]:
    starters: list = []
    bench: list = []
    reserve: list = []
    for r in rows:
        st = _squad_status(r)
        if st == "start":
            starters.append(r)
        elif st == "bench":
            bench.append(r)
        else:
            reserve.append(r)
    key = lambda r: (-int(r.overall), r.position, r.name)
    return (
        sorted(starters, key=key),
        sorted(bench, key=key),
        sorted(reserve, key=key),
    )


def _team_situation(team: str, league_code: str | None, seasons: list[int]) -> dict[str, Any]:
    from bot.season_history_store import load_history
    from utils.cl_knockout_results import cl_stage_label_ru, team_cl_knockout_stage
    from utils.transfer_advice import (
        _expected_league_place,
        _team_league_places_during_seasons,
        _cl_strength_rank,
        _league_strength_rank,
    )

    hist = load_history()
    exp_place = _expected_league_place(team)
    places = _team_league_places_during_seasons(team, league_code, seasons)

    league_wins = 0
    if league_code:
        lw_rows = (hist.get("league_winners") or {}).get(league_code) or []
        for row in lw_rows:
            if not row or len(row) < 2:
                continue
            sn, winner = int(row[0]), str(row[1])
            if sn in seasons and winner.strip().casefold() == team.strip().casefold():
                league_wins += 1

    cl_wins = 0
    for row in hist.get("champions_league") or []:
        if not row or len(row) < 2:
            continue
        sn, winner = int(row[0]), str(row[1])
        if sn in seasons and winner.strip().casefold() == team.strip().casefold():
            cl_wins += 1

    cl_stages: list[tuple[int, int]] = []
    for sn in seasons:
        st = team_cl_knockout_stage(team, sn)
        if st > 0:
            cl_stages.append((sn, st))
    max_stage = max((st for _, st in cl_stages), default=0)
    max_stage_label = cl_stage_label_ru(max_stage) if max_stage else "—"

    return {
        "expected_place": exp_place,
        "places": places,
        "league_wins": league_wins,
        "cl_wins": cl_wins,
        "cl_stages": cl_stages,
        "max_cl_stage": max_stage,
        "max_cl_stage_label": max_stage_label,
        "league_rank": _league_strength_rank(team, league_code),
        "cl_rank": _cl_strength_rank(team),
    }


def _format_situation(
    sit: dict[str, Any], seasons: list[int], in_cl: bool
) -> list[str]:
    from utils.cl_knockout_results import cl_stage_label_ru

    lines: list[str] = []
    exp = sit["expected_place"]
    places = sit["places"]
    if places:
        place_parts = []
        for i, sn in enumerate(seasons[: len(places)]):
            place_parts.append(f"сезон {sn} — {places[i]}-е")
        fact = ", ".join(place_parts)
        lines.append(
            f"- При ожидаемом ~{exp:g}-м месте: {fact}"
        )
    else:
        lines.append(f"- Ожидаемое место в лиге: ~{exp:g}")

    lines.append(f"- Чемпионат лиги за {len(seasons)} сез.: {sit['league_wins']} раз")
    lines.append(f"- Победы в ЛЧ: {sit['cl_wins']} раз")
    if sit["cl_stages"]:
        stage_parts = [
            f"сезон {sn} — {cl_stage_label_ru(st)}"
            for sn, st in sit["cl_stages"]
        ]
        lines.append(f"- Стадии ЛЧ: {', '.join(stage_parts)}")
    lines.append(f"- Макс. стадия ЛЧ: {sit['max_cl_stage_label']}")
    lines.append(f"- Участник ЛЧ (текущий пул): {'да' if in_cl else 'нет'}")
    lr = sit.get("cl_rank")
    if lr is not None:
        lines.append(
            f"- Рейтинг силы: лига #{sit['league_rank']}, ЛЧ #{lr}"
        )
    return lines


def _formation_label(fkey: str | None) -> str | None:
    if not fkey:
        return None
    from formation_catalog import FORMATION_ID_LABELS

    if fkey.startswith("fid_"):
        try:
            fid = int(fkey.split("_", 1)[1])
            return FORMATION_ID_LABELS.get(fid, fkey)
        except ValueError:
            pass
    return fkey


def _contribution_sort_key(row) -> tuple:
    d = row.detail or {}
    pm = d.get("result_pm")
    matches = int(d.get("matches") or 0)
    ga = int(d.get("goals") or 0) + int(d.get("assists") or 0)
    if pm is not None and matches > 0:
        return (float(pm), ga, int(row.overall))
    prod = float(d.get("prod_ratio") or 0)
    return (-999.0, prod, int(row.overall))


def _best_player(rows) -> Any:
    outfield = [r for r in rows if not r.is_goalkeeper]
    pool = outfield or rows
    with_matches = [r for r in pool if int((r.detail or {}).get("matches") or 0) >= 3]
    pick_pool = with_matches or pool
    return max(pick_pool, key=_contribution_sort_key)


def _best_player_head(row) -> str:
    from utils.transfer_advice import _format_result_pm, player_surname

    d = row.detail or {}
    sur = (player_surname(row.name) or row.name).strip()
    head = f"{sur} {row.position} {row.overall}"
    if row.verdict:
        head += f" ({row.verdict})"
    stat_bits: list[str] = []
    pm = d.get("result_pm")
    if pm is not None and int(d.get("matches") or 0) > 0:
        pm_label = d.get("result_pm_label") or ""
        pm_s = _format_result_pm(float(pm))
        stat_bits.append(f"вклад {pm_s}" + (f", {pm_label}" if pm_label else ""))
    m = int(d.get("matches") or 0)
    g = int(d.get("goals") or 0)
    a = int(d.get("assists") or 0)
    if m > 0:
        if row.is_goalkeeper:
            cs = int(d.get("clean_sheets") or 0)
            stat_bits.append(f"{m} матчей, {cs} сухих")
        else:
            stat_bits.append(f"{m} матчей, {g} голов, {a} передач")
    ovr_hist = d.get("ovr_history")
    if ovr_hist:
        stat_bits.append(f"рейтинг {ovr_hist}")
    if stat_bits:
        return head + " — " + "; ".join(stat_bits)
    return head


def _format_team_block(
    team: str,
    rows: list,
    sit: dict[str, Any],
    seasons: list[int],
    in_cl: bool,
    formation: str | None,
) -> str:
    best = _best_player(rows)
    best_head = _best_player_head(best)

    starters, bench, reserve = _group_rows(rows)

    out: list[str] = [f"### {team}", ""]
    flabel = _formation_label(formation)
    if flabel:
        out.append(f"**Схема:** {flabel}")
        out.append("")
    out.append(f"**Лучший игрок:** {best_head}")
    out.append("")

    def _list_block(title: str, group: list) -> None:
        out.append(f"**{title}** ({len(group)}):")
        if not group:
            out.append("- —")
        else:
            for r in group:
                out.append(f"- {_player_line(r)}")
        out.append("")

    _list_block("Стартовый состав", starters)
    _list_block("Банка", bench)
    _list_block("Резерв", reserve)

    out.append("**Ситуация за 2 года:**")
    out.extend(_format_situation(sit, seasons, in_cl))
    out.append("")
    return "\n".join(out)


def _transfer_rules_markdown() -> str:
    cl_teams = sorted(_load_cl_participants())
    cl_list = ", ".join(cl_teams) if cl_teams else "—"
    top16 = sorted(
        {
            "Сити",
            "Ливерпуль",
            "Арсенал",
            "Челси",
            "Интер",
            "Наполи",
            "Милан",
            "Аталанта",
            "Реал",
            "Атлетико",
            "Барселона",
            "Атлетик",
            "Бавария",
            "Вольфсбург",
            "Дортмунд",
            "Лейпциг",
        }
    )
    top16_s = ", ".join(top16)
    rpl_81 = (
        "Альварез 85 (Динамо), Давид 83 (Зенит), Ляказет 83 (Краснодар), "
        "Трехо 82 (Зенит), Митома 82 (Спартак), Орта 82 (Спартак), "
        "Фуллкруг 81 (Спартак), Бето 81 (Спартак), Данк 81 (Спартак), "
        "Заха 81 (Зенит), Бовен 81 (Зенит), Фомин 81 (Зенит), "
        "Карраскаль 81 (Динамо), Сангаре 81 (Динамо)"
    )
    return "\n".join(
        [
            "---",
            "",
            "## Правила летнего трансферного окна",
            "",
            "> Только **рекомендации** для LLM. В БД **не применять** без ручной проверки. "
            "Имена игроков — **только из ростеров выше** (актуальная БД).",
            "",
            "### Формат ответа",
            "",
            "- Для **каждого из 40 клубов**: таблица **5 OUT + 5 IN** (можно меньше, если логично, но цель — полное окно).",
            "- Только обмены **между клубами** (без свободных агентов в этом черновике).",
            "- **OUT и IN по позиции**: ВРТ↔ВРТ обязательно; полевые — та же позиция или близкая по схеме.",
            "- После окна у клуба **≥ 3 вратаря** (третьего ВРТ добавляем отдельно, см. ниже).",
            "",
            "### Кого не трогаем",
            "",
            "1. **Вратарей в окне не трогаем** — ни OUT, ни IN. Третий ВРТ — вне трансферного окна.",
            "2. **Ядро не продаём**: игроки **84+** с вердиктом **НО/СО** и реальным вкладом в команду.",
            "3. **НО на глубине 1–2** не уводим — это стартовый костяк.",
            "",
            "### Топ-16 (усиление, не распродажа)",
            "",
            f"Клубы: **{top16_s}**.",
            "",
            "- Стратегия: **усилиться**, не разбирать состав.",
            "- **OUT**: ротация и глубина **≤ 79**, плюс исключения — высокий рейтинг, но провал по делу "
            "(вердикт **СУ/НУ**, слабый вклад): **Хаверц 88** (Арсенал → уходит), **Стерлинг 86** (Челси).",
            "- **IN**: 1–2 усиления в старт + замена ушедшей глубины; брать из оттока элиты и **РПЛ 81+**.",
            "- Цель: **не просесть по глубине** и добавить 1–2 игрока в основу.",
            "",
            "### РПЛ 81+ → элита",
            "",
            "РПЛ — лига развития. Все полевые **81+** уезжают в топ-5, **не остаются в РПЛ**:",
            "",
            f"{rpl_81}.",
            "",
            "- Первый шаг — **не в топ-3** клуба нации (середина АПЛ / Ла Лиги / Серии А / Бундеслиги).",
            "- После продажи звёзд РПЛ-клубы (особенно **6 участников ЛЧ**) компенсируют состав "
            "**европейской глубиной 76–80**, не «дном» 68–71.",
            "",
            "### Участники ЛЧ (30 клубов)",
            "",
            f"Текущий пул: **{cl_list}**.",
            "",
            "- Все участники ЛЧ **усиливаются**, не только топ-16.",
            "- **IN от 76**, лучше **78–82**; минимум **2–3** таких входа у клубов вне топ-16.",
            "- **Запрещены «затычки» 68–71** в ЛЧ-клубы — это не уровень турнира.",
            "- У **6 российских** участников ЛЧ после оттока 81+ — приоритет на **готовую европейскую глубину**.",
            "",
            "### Как выбирать OUT",
            "",
            "- Опираться на вердикты `collect_transfer_advice`: **СУ, НУ** — в первую очередь.",
            "- Метки: **З+** (избыток на позиции), **П↓** (продуктивность ниже ожиданий), **С×** (не в схему), **Т−** (нет трофеев при амбициях клуба).",
            "- **Лучший игрок клуба** — по **вкладу в результаты** (`result_pm`), не по рейтингу.",
            "- Учитывать **ситуацию за 2 года**: недобор трофеев / провал в ЛЧ → больше мотивации на смену состава.",
            "",
            "### Как выбирать IN",
            "",
            "- Закрывать дыры в **старт / банка / резерв** с учётом схемы тренера.",
            "- Брать игроков, которых отдают другие клубы по правилам выше.",
            "- Не дублировать одного игрока у нескольких покупателей.",
            "- Не более **2 игроков с одного клуба-источника** на одного покупателя.",
            "",
            "### Чего не делать",
            "",
            "- Не придумывать игроков, которых **нет в ростерах** (никаких Лукаку/Тюрама в Интер и т.п.).",
            "- Не продавать ядро топ-клубов ради «баланса рынка».",
            "- Не гонять РПЛ 81+ между середняками — только **step-up в элиту**.",
            "- Не набивать ЛЧ-клубы случайным флотом 68–71.",
            "- Не строить переходы механическим автобалансом — **осмысленные пары** по позиции и контексту клуба.",
            "",
            "### Вне игры (со 2-го сезона)",
            "",
            "Не участвуют в лиге и в окне: **Фрайбург, Штутгарт, Торино, Сассуоло, "
            "Райо Вальекано, Вильярреал, Рубин, Ростов, Брайтон, Фулхэм**.",
            "",
            "### Обязательные акценты (v2)",
            "",
            "- **Хаверц** уходит из **Арсенала** (88, СУ, слабый вклад при высоком рейтинге).",
            "- **14 игроков РПЛ 81+** — в топ-16 / элиту (см. список выше).",
            "- Топ-16 **набирают**, середняки и РПЛ **не обнищают** после оттока.",
            "",
        ]
    )


def build_md(*, out_path: Path) -> str:
    from coach_squad_state import resolve_formation_key_for_team
    from player_stats import LEAGUE_NAMES, LEAGUE_TEAMS
    from utils import season_paths
    from utils.transfer_advice import all_league_teams, collect_transfer_advice

    active = int(season_paths.get_state().get("active_season") or 1)
    seasons = [sn for sn in range(1, active + 1) if sn <= 2]
    if not seasons:
        seasons = [1]

    cl_pool = _load_cl_participants()
    blocks: list[str] = [
        "# Ростеры клубов для трансферного окна",
        "",
        f"Сгенерировано из БД. Сезоны: {', '.join(str(s) for s in seasons)} "
        f"(активный сезон {active}).",
        "",
        "Формат: имя, позиция, рейтинг, вердикт (НО/СО/СУ/НУ), стата в клубе.",
        "",
    ]

    teams_by_league: dict[str, list[str]] = {}
    for code, names in LEAGUE_TEAMS.items():
        teams_by_league[code] = list(names)

    for code in ("rpl", "eng", "esp", "ita", "ger"):
        lname = LEAGUE_NAMES.get(code, code.upper())
        blocks.append(f"## {lname}")
        blocks.append("")
        for team in teams_by_league.get(code, []):
            canon, rows, err = collect_transfer_advice(team)
            if err or not rows:
                blocks.append(f"### {team}")
                blocks.append(f"*Ошибка: {err or 'пустой состав'}*")
                blocks.append("")
                continue
            from player_stats import national_league_code_for_team

            league_code = national_league_code_for_team(canon)
            sit = _team_situation(canon, league_code, seasons)
            fkey = resolve_formation_key_for_team(canon)
            blocks.append(
                _format_team_block(
                    canon,
                    rows,
                    sit,
                    seasons,
                    canon in cl_pool,
                    fkey,
                )
            )

    blocks.append(_transfer_rules_markdown())
    text = "\n".join(blocks).rstrip() + "\n"
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(text, encoding="utf-8")
    return text


def main() -> int:
    p = argparse.ArgumentParser(description="MD-ростеры всех клубов для GLM.")
    p.add_argument(
        "-o",
        "--output",
        type=Path,
        default=_ROOT / "data" / "teams_rosters_for_glm.md",
        help="Путь к выходному файлу",
    )
    args = p.parse_args()
    build_md(out_path=args.output.resolve())
    print(f"Записано: {args.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
