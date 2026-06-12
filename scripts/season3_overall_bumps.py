#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Пакетное изменение overall в БД **сезона 3** (db/season_3/league.db + champions_league.db).

  python3 scripts/season3_overall_bumps.py --dry-run
  python3 scripts/season3_overall_bumps.py --apply
"""
from __future__ import annotations

import argparse
import os
import re
import sys

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from utils import season_paths
from utils.common_db import rebuild_common_database_for_disk_paths
from utils.player_overall_bumps import apply_overall_bumps_in_sessions
from utils.squad_roster_sync import find_player_row_first_match

SEASON_NUM = 3

BUMP_ALTERNATES: dict[str, tuple[str, ...]] = {
    "зенит|фомин": ("Фомин",),
    "краснодар|кокшаров": ("Кокшаров",),
    "динамо|караскаль": ("Карраскаль",),
    "динамо|гитенс": ("Гиттенс",),
    "динамо|орайли": ("О'Райли", "Орайли"),
    "арсенал|диеш": ("Диаш",),
    "арсенал|кай": ("Хаверц",),
    "арсенал|рамсейл": ("Рамсдейл",),
    "ливерпуль|собо": ("Собослай",),
    "ливерпуль|гравен": ("Гравенберх",),
    "ливерпуль|смолинг": ("Смоллинг",),
    "мю|марсьяль": ("Марсиаль",),
    "мю|савич": ("Милинкович-Савич",),
    "мю|биссака": ("Ван-Биссака",),
    "ньюкасл|нури": ("Аит-Нури",),
    "сити|холланд": ("Холанд",),
    "сити|рэш": ("Рэшфорд",),
    "сити|гвардиоль": ("Гвардиоль",),
    "сити|ортега": ("Ортега",),
    "тоттенхэм|мэд": ("Мэддисон",),
    "челси|факир": ("Фекир",),
    "челси|густо": ("Гюсто",),
    "атлетико|альмада": ("Алмада",),
    "атлетик|муниан": ("Муниаин",),
    "жирона|газзанига": ("Газзанига",),
    "жирона|гаццанига": ("Газзанига",),
    "реал|дембеле": ("Дембеле",),
    "реал сосьедад|мендез": ("Мендез",),
    "реал сосьедад|мендес": ("Мендез",),
    "реал сосьедад|ди мария": ("Ди Мария",),
    "аталанта|мариэль": ("Муриэль",),
    "аталанта|щесны": ("Чесны",),
    "аталанта|шчесны": ("Чесны",),
    "аталанта|сильва": ("Антониу Сильва",),
    "интер|баррела": ("Барелла",),
    "интер|чан": ("Чалханоглу",),
    "интер|верман": ("Вирман",),
    "ювентус|эн несри": ("Эн-Несри",),
    "ювентус|эн-несири": ("Эн-Несри",),
    "ювентус|миррети": ("Миретти",),
    "ювентус|инасио": ("Инасиу",),
    "ювентус|черки": ("Черки",),
    "ювентус|бах": ("Бах",),
    "ювентус|проведель": ("Проведель",),
    "бавария|рель": ("Рёль",),
    "бавария|сориа": ("Сориа",),
    "бавария|айду": ("Айду",),
    "байер|гюлер": ("Гюлер",),
    "вольфсбург|линдсторм": ("Линдстром",),
    "вольфсбург|маэле": ("Маэле",),
    "вольфсбург|барнау": ("Борнау",),
    "дортмунд|касьера": ("Касьерра",),
    "дортмунд|шимански": ("Шимански",),
    "дортмунд|шлотер": ("Шлоттербек",),
    "дортмунд|рейрсон": ("Райерсон",),
    "дортмунд|хумельс": ("Хуммельс",),
    "милан|тераччано": ("Терраччано",),
    "наполи|рамоньоли": ("Романьоли",),
    "наполи|квара": ("Квара",),
    "наполи|эрнандес": ("Люка Эрнандез",),
    "франкфурт|кох": ("Кох",),
}

_LINE_RE = re.compile(
    r"^\s*(.+?)\s*([+-]?\d{1,2})\s*$",
    re.IGNORECASE | re.UNICODE,
)

TEAM_BUMPS: dict[str, str] = {
    "Зенит": """
Давид +2
Трехо +2
Фомин +1
Шутало +2
Алип +4
Кержаков +4
""",
    "Краснодар": """
Кокшаров +2
""",
    "Динамо": """
Шешко +4
Карраскаль +4
Силас +3
Чавез +3
Орайли +2
Гиттенс +2
Трубин +2
Бальбуэна +2
Даса +2
Ругани +2
Скопинцев +2
Патрик +2
Маричаль +2
Фернандез +2
Мауро +2
Альварез +2
Хенри +2
""",
    "Астон Вилла": """
Сперцян +2
Ровелла +2
Виртц -5
""",
    "Арсенал": """
Муани +2
Кай +3
Акунья -2
Диаш -5
Салиба +3
Тимбер +2
Рамсдейл -2
Канте -2
Плеа -3
Мерино +1
""",
    "Ливерпуль": """
Жота +3
Собослай +2
Гравенберх +2
Смолинг +2
Конате -2
""",
    "Мю": """
Марсьяль +2
Гарначо +2
Савич +1
Маласия +2
Биссака +2
Онана -2
Брозович +1
""",
    "Ньюкасл": """
Исак +3
Рафа +1
Тюрам +3
Нури +2
""",
    "Сити": """
Холанд -2
Рэшфорд +3
Палинья +2
Ковачич +2
Гвардиоль +2
Уокер +1
Ортега +3
Месси +2
Стоунз -1
""",
    "Тоттенхэм": """
Мэддисон +2
Сон +1
""",
    "Челси": """
Марез +2
Факир +1
Сильва +2
Густо +2
Фофана +1
""",
    "Атлетико": """
Обамеянг +1
Депай -2
Лемар +1
Льоренте -1
Альмада +2
Джикия +4
""",
    "Атлетик": """
Леау +3
Сансет +2
Кулушевски +1
Нико +2
Иньяки +2
Муниан +2
Вивиан +2
""",
    "Барселона": """
Педри +1
Рафинья +1
Гави +1
""",
    "Бетис": """
Феликс +1
Иско +2
""",
    "Жирона": """
Гаццанига +3
""",
    "Реал": """
Лукаку -2
Браим +2
Дембеле -3
Начо +2
Маркиньос -2
Гарсия +2
""",
    "Реал Сосьедад": """
Оярзабаль +1
Мендес +2
Ди Мария +2
Фернандес +4
Ремиро +3
""",
    "Севилья": """
Гонсалвеш +4
Лукебакио +2
Карраско +2
Рамос +1
Педроса +1
Навас +1
""",
    "Аталанта": """
Миранчук +5
Муриэль +3
Симонс +3
Пашалич +1
Илич +1
Сильва +2
Орбан +2
Чесны +1
""",
    "Интер": """
Мартинез +3
Арнаутович +2
Берарди +2
Барелла +3
Чалханоглу +1
Бастони -2
Вирман +2
""",
    "Милан": """
Терраччано +2
""",
    "Наполи": """
Осимен +1
Квара +2
Лоботка +2
Невеш -2
Рахмани +2
Романьоли +3
Люка Эрнандез +1
Мерет +1
""",
    "Ювентус": """
Влашич +5
Костич +1
Кьеза +1
Эн-Несри +2
Миретти +3
Фаджиоли +1
Альба +1
Инасиу +2
Рейс +2
Черки +2
Бах +1
Проведель +1
""",
    "Бавария": """
Коман +3
Рёль +4
Сане -3
Горетцка +3
Банза +1
Киммих +1
Дэвис +2
Фримпонг +1
Нойер +2
Сориа +2
Айду +2
""",
    "Байер": """
Иконе +2
Гюлер +4
Синго +2
Градецки +2
""",
    "Боруссия М": """
Кванкара +2
""",
    "Вольфсбург": """
Линдстром +3
Майер +4
Нмеча +1
Виммер +1
Сванберг +2
Маэле +2
Лакруа +2
Борнау +2
Фишер +3
Саму Гарсия +2
""",
    "Дортмунд": """
Фред +4
Дибала +2
Касьерра +3
Мален +1
Шимански +2
Шлоттербек +3
Райерсон +2
Хуммельс -1
""",
    "Хоффенхайм": """
Довбык +2
""",
    "Лейпциг": """
Ольмо +2
Опенда +1
Вернер +1
Клаудиньо +1
""",
    "Франкфурт": """
Кох +2
""",
}


def _bump_alt_key(team: str, name: str) -> str:
    return f"{team.strip().lower()}|{name.strip().lower()}"


def _alternates_for(team: str, name: str) -> tuple[str, ...]:
    return BUMP_ALTERNATES.get(_bump_alt_key(team, name), ())


def _normalize_bump_block(text: str) -> str:
    out_lines: list[str] = []
    for raw in (text or "").splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        m = _LINE_RE.match(line)
        if not m:
            continue
        name, ds = m.group(1).strip(), m.group(2).strip()
        if not name:
            continue
        if ds in ("", "+", "-"):
            continue
        try:
            d = int(ds)
        except ValueError:
            continue
        if d == 0:
            continue
        sign = "+" if d > 0 else ""
        out_lines.append(f"{name} {sign}{d}")
    return "\n".join(out_lines) + ("\n" if out_lines else "")


def _session_pair(league_path: str, cl_path: str):
    el = create_engine(f"sqlite:///{league_path}")
    ec = create_engine(f"sqlite:///{cl_path}")
    Sl = sessionmaker(bind=el)
    Scl = sessionmaker(bind=ec)
    return Sl(), Scl(), el, ec


def _clamp_ov(v: int) -> int:
    return max(1, min(99, int(v)))


def _preview_bumps_for_team(team: str, text: str, sleague, scl) -> tuple[list[str], list[str]]:
    team = (team or "").strip()
    out: list[str] = []
    err: list[str] = []
    for line in (text or "").splitlines():
        line = line.strip()
        if not line:
            continue
        m = _LINE_RE.match(line)
        if not m:
            err.append(f"не разобрать: {line!r}")
            continue
        name = m.group(1).strip()
        try:
            delta = int(m.group(2).strip())
        except ValueError:
            err.append(f"не разобрать: {line!r}")
            continue
        if not name:
            continue
        ex = _alternates_for(team, name)
        row_l, _, db_l = find_player_row_first_match(sleague, name, team, *ex)
        row_c, _, db_c = find_player_row_first_match(scl, name, team, *ex)
        if row_l is None and row_c is None:
            err.append(f"не найден: {name}")
            continue
        bits: list[str] = []
        if row_l is not None:
            cur = int(getattr(row_l, "overall", 0) or 0)
            bits.append(f"нац. {cur}→{_clamp_ov(cur + delta)} ({row_l.name})")
        if row_c is not None:
            cur = int(getattr(row_c, "overall", 0) or 0)
            bits.append(f"ЛЧ {cur}→{_clamp_ov(cur + delta)} ({row_c.name})")
        out.append(f"  {name} {delta:+d}   {' | '.join(bits)}")
    return out, err


def main() -> None:
    ap = argparse.ArgumentParser(description=f"Overall bumps для db/season_{SEASON_NUM}/")
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--apply", action="store_true")
    ap.add_argument("--no-synced", action="store_true")
    args = ap.parse_args()
    if args.dry_run == args.apply:
        print("Укажите ровно один флаг: --dry-run или --apply")
        sys.exit(2)

    base = os.path.join(season_paths.PROJECT_ROOT, "db", f"season_{SEASON_NUM}")
    p_l = os.path.join(base, season_paths.SEASON_LEAGUE_NAME)
    p_c = os.path.join(base, season_paths.SEASON_CL_NAME)
    p_o = os.path.join(base, season_paths.SEASON_COMMON_NAME)

    if not os.path.isfile(p_l) or not os.path.isfile(p_c):
        print("Нет файлов сезона:", p_l, p_c)
        sys.exit(1)

    sl, scl, el, ec = _session_pair(p_l, p_c)
    try:
        total_ok = 0
        total_err = 0
        for team, block in TEAM_BUMPS.items():
            text = _normalize_bump_block(block)
            if not text.strip():
                print(f"[{team}] нет строк — пропуск")
                continue
            print(f"\n=== {team} ===")
            if args.dry_run:
                previews, p_err = _preview_bumps_for_team(team, text, sl, scl)
                for s in previews:
                    print(s)
                for s in p_err:
                    print("  ERR", s)
                total_ok += len(previews)
                total_err += len(p_err)
            else:
                res = apply_overall_bumps_in_sessions(
                    team, text, sl, scl, alternate_names=BUMP_ALTERNATES
                )
                total_ok += len(res.ok)
                total_err += len(res.errors)
                for s in res.ok:
                    print("  OK ", s)
                for s in res.errors:
                    print("  ERR", s)

        print(f"\nИтого строк (успех): {total_ok}, ошибок: {total_err}")

        if args.dry_run:
            sl.rollback()
            scl.rollback()
            return

        if total_err and not total_ok:
            sl.rollback()
            scl.rollback()
            sys.exit(1)

        sl.commit()
        scl.commit()
        print("\nCommit league + cl")
    finally:
        sl.close()
        scl.close()
        el.dispose()
        ec.dispose()

    if args.apply:
        rebuild_common_database_for_disk_paths(p_l, p_c, p_o)
        if not args.no_synced:
            from utils import cumulative_mirror

            for team, block in TEAM_BUMPS.items():
                tnorm = _normalize_bump_block(block)
                if tnorm.strip():
                    cumulative_mirror.mirror_overall_bumps_for_team(
                        team, tnorm, alternate_names=BUMP_ALTERNATES
                    )
    print("Готово.")


if __name__ == "__main__":
    main()
