#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Пакетное изменение overall в БД **сезона 2** (db/season_2/league.db + champions_league.db),
затем пересборка season_2/common.db.

Имена/клубы — как в списке редактора; часть строк заведомо с опечатками — правьте в
константе ``TEAM_BUMPS`` и перезапускайте.

  # из каталога проекта, с **интерпретатором venv** (часто ``python``, не системный ``python3``):
  python scripts/season2_overall_bumps.py --dry-run   # текущий overall → новый по каждой БД, без записи
  python scripts/season2_overall_bumps.py --apply     # season_2 league+cl, common, зеркало в *_synced
  python scripts/season2_overall_bumps.py --apply --no-synced   # без league_synced / cl_synced / common_synced

Если ``ModuleNotFoundError: sqlalchemy`` — в активированном venv:
  ``pip install -r requirements.txt``

Не трогает глобальные сессии ``utils`` (открывает только файлы ``db/season_2/…``).

Что не попало в автоматические строки (добавьте вручную в ``TEAM_BUMPS`` при необходимости):
  • дельта 0 (Нуньес, Диаз, Промес, Эллиот, Родри, Олаза, Сафонов, Эдерсон, Мартинели,
    Фекир, Пулишич, Жиру, Олаза, Акунья, Эррера, Цыганков, Карвахаль, …);
  • ЦСКА: «Цп ничего»;
  • Краснодар: «Кокшаров +» без числа;
  • Фиорентина: «Защита -2 всем» — нужны конкретные фамилии защитников;
  • Милан: строка «Бенссаер» без дельты;
  • Наполи: «Рамоньоли» без дельты; «Сака (0)»;
  • Ювентус: из списка убраны Бастони/Думфрис (это не Юве) — если имелось в виду другое, добавьте;
  • «Робертсон и Арнольд +1» разбито на две строки;
  • Жирона: было два разных Гарсия (74) и Алейш (80) — сейчас упрощено до «Гарсия +3», «Алейш +1»;
  • Вольфсбург: в исходном списке были фамилии с других клубов — оставлено как у вас, проверьте;
  • Реал: «Лукаку +4?» записано как +4.
"""
from __future__ import annotations

import argparse
import os
import re
import sys

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

try:
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker
except ModuleNotFoundError as _e:
    _exe = sys.executable
    _msg = (
        "Не установлен SQLAlchemy (или запуск не из того же Python, что venv).\n"
        "  1) Активируйте venv:  source .venv/bin/activate\n"
        "  2) Если «bad interpreter» в .venv — пересоздайте venv:\n"
        "       rm -rf .venv && python3 -m venv .venv && source .venv/bin/activate\n"
        "  3) Установите зависимости:  pip install -r requirements.txt\n"
        "  4) Запускайте:  python scripts/season2_overall_bumps.py --dry-run\n\n"
        "Сейчас интерпретатор: " + _exe
    )
    print(_msg, file=sys.stderr)
    raise SystemExit(1) from _e

from utils import season_paths
from utils.common_db import rebuild_common_database_for_disk_paths
from utils.player_overall_bumps import apply_overall_bumps_in_sessions
from utils.squad_roster_sync import find_player_row_first_match

SEASON_NUM = 2

# Ключ: ``клуб_нижний|имя_из_строки_нижний`` → дополнительные варианты как в SQLite.
# Реал Сосьедад: в сезоне 1 часто «Лауриент», в заявке может быть «Лориент».
BUMP_ALTERNATES: dict[str, tuple[str, ...]] = {
    "реал сосьедад|лориент": ("Лауриент",),
    "реал сосьедад|лауриент": ("Лориент",),
}


def _bump_alt_key(team: str, name: str) -> str:
    return f"{team.strip().lower()}|{name.strip().lower()}"


def _alternates_for(team: str, name: str) -> tuple[str, ...]:
    return BUMP_ALTERNATES.get(_bump_alt_key(team, name), ())

# Имя команды — как в SQLite / LEAGUE_TEAMS (например «Цска», не «ЦСКА»).
# Значение: строки «имя +N» / «имя -N» (как в боте). Нулевые дельты и пустые — пропускаются.
# Строки с # в начале в тройных кавычках — закомментированы вручную, не парсятся.
TEAM_BUMPS: dict[str, str] = {
    "Ливерпуль": """
Гомес -4
Робертсон +1
Александер-Арнольд +1
Конате +8
ван дейк -9
Алиссон +1
мак Аллистер -5
Тьяго -1
Жота +2
Собослай +2
Диаби -8
Рабьо -2
Гакпо -1
Гравенберх +1
""",
    "Цска": """
Кучаев +2
Заболотный +3
Файзуллаев +1
Роша +1
Дивеев +1
Мойзес +2
Акинфеев -9
Спортиелло +1
Агапов -2
""",
    "Урал": """
Дмитриев +7
Каштанов +9
Юшин +1
Егорычев +5
Газинский +3
Кики +3
Бевеев +6
Мамин +4
Бегич +3
Рейна -3
Помазун -5
""",
    "Спартак": """
Бельтран -2
Медина -2
Пруцев +1
Зобнин +2
Джикия +4
Рябчук -1
Максименко +6
Денисов +2
Игнатов +4
Соболев +2
Бонгонда -3
Зиньковский +2
""",
    "Локомотив": """
Пиняев +2
Глушенков +3
Чалов +1
Миранчук +3
Сулейманов +2
Лантратов -3
""",
    "Крылья Советов": """
Писарский +5
Рахманович +5
Бабкин +7
Гарре +2
Салтыков +4
Ломаев +4
Солдатенков +2
Евгеньев +1
Костанца +1
Горшков +1
Боргес +3
""",
    "Зенит": """
Касьерра +7
Кержаков +6
Фернандес +4
Алип +5
Вендел +3
Трехо +2
Нгамалу +1
Мостовой +2
""",
    "Динамо": """
Смолов +4
Фомин +6
Силас +2
Гиттенс +1
Карраскаль +3
Лаксальт -2
Чавез +2
Шунин +2
Лесовой -2
""",
    "Краснодар": """
Сперцян +5
Батши +3
Черников +3
Олаза +0
Алонсо +3
Кайо +2
Волков +1
Сафонов +0
Кокшаров +5
""",
    "Арсенал": """
Хаверц +3
Жезус +2
Одегаард +1
Мерино +2
Райс +1
Парти -3
Уайт -2
Томиясу +2
Габриэль +4
Салиба +3
Тимбер +4
Рамсдейл +1
""",
    "Ньюкасл": """
Поуп -3
Гордон -1
Исак +3
Тонали +3
Уиллок +4
Жоелинтон +1
Ливраменто +3
Бёрн +1
Шар +1
""",
    "Сити": """
Холанд +1
Де Брюйне +1
Рэшфорд -2
Фоден -1
Палинья +2
Гвардиоль +2
Диаш -2
Уокер +1
Ковачич +1
Доку -1
Эдерсон +0
""",
    "Тоттенхэм": """
Сон +2
Куадрадо +1
Перишич +2
Альварез +1
Мэддисон +1
Джонсон -2
Ришарлисон -1
Удоджи +2
Ван де Вен +4
""",
    "Мю": """
Марсиаль +2
Фернандеш +1
Эриксен +3
Маунт -5
Каземиро -2
Маласия +2
Мартинез +2
Варан -1
ван-биссака +1
Онана +3
Диалло +2
Антони -2
Гарначо +1
""",
    "Челси": """
Стерлинг +3
Фати +2
Мадуэке +1
Энцо +2
Галлагер +2
Маатсен +6
Фофана +4
Сильва +1
Гюсто +3
Санчез +5
""",
    "Атлетик": """
Муниаин +5
Нико +3
Иньяки +3
Сансет +2
Кулушевски +2
Симон +1
де маркос -2
Берчиче -2
Эррера +1
Вивиан +3
Йерай +1
""",
    "Атлетико": """
Корреа +6
Мората +5
Депай +4
Льоренте +2
Лемар +5
Рейнилдо +6
Молина +4
Эрмосо +3
Савич +5
Облак +1
Коке +2
""",
    "Барселона": """
Лева +1
Рафинья +4
Палазон +3
Педри +2
Бальде +2
Араухо +3
Кунде +2
тер штеген +1
Гюндоган -1
Канселу +1
""",
    "Бетис": """
Феликс +2
Черны +3
Иско +1
Карвальо +1
Бартра -1
Бельерин -1
Силва +1
Иглесиас -5
""",
    "Севилья": """
Ундав +3
Лукебакио +3
Окампос +1
Фернандо -4
Ракитич -1
Навас +2
Педроса +2
""",
    "Реал Сосьедад": """
Оярзабаль +1
Тюкавин +1
Кубо -3
Захарян +1
Лориент +1
Мендез +2
ле норманд -2
Ремиро +1
Траоре +4
""",
    "Аталанта": """
Миранчук +6
Лукман +2
Пашалич +4
Муриэль +3
Симонс +2
Илич +3
Хатебур +2
Скальвини -4
Толои -2
Карнесекки -9
Эдерсон -2
""",
    "Интер": """
Мартинез +6
Арнаутович +5
Берарди +3
Мхитарян +4
Барелла +3
Чалханоглу +2
Уоткинс -3
Димарко +2
Павар -5
Зоммер +6
Аугусто -2
""",
    "Ювентус": """
Влахович -8
Данило -7
Гатти -6
Маккенни -6
Локателли -1
Костич +3
Кьеза +2
Влашич +5
Миретти +2
Фаджиоли +4
Бремер +4
Коуто +2
""",
    "Боруссия М": """
Кванкара +6
Плеа +5
Беренгер -5
Хонорат +3
Траоре +1
Коне +2
Нетц +3
Итакура +5
Скалли +1
Омлин -5
Нгуму -2
""",
    "Дортмунд": """
Адейеми +4
Мален +2
Ройс -3
Брандт -3
Джан +1
Гимараеш -3
Нмеча -1
Вульф -10
Бенсебаини -5
Шлоттербек +2
Зюле -2
Кобель +2
Мукоко -2
""",
    "Лейпциг": """
Клаудиньо +6
Вернер +5
Опенда +4
Ольмо +3
Сейвальд +5
Баумгартнер +1
Шлагер -2
Раум +2
Симакан +3
Клостерманн +2
Лукеба +3
Гулашчи -2
""",
    "Хоффенхайм": """
Бебу +2
Крамарич -2
Жустван -2
Бериша -2
Сков +4
Бултер +1
Довбык +1
Бауманн +2
Салай +1
Акпогума +1
Кадерабек +1
""",
    "Реал": """
Нкунку +1
Родриго +1
Браим +6
Кроос +1
Модрич -3
Гарсия +4
Карвахаль +0
Кепа +2
Алаба +1
Начо +1
Вини -1
Вальверде -1
Рюдигер -3
Милитао -4
Куртуа -5
Хоселу +1
Менди -2
Лукаку +4
""",
    "Лацио": """
Тель +3
Дзаканьи -2
Андерсон -2
Камада +2
Альберто -4
Гендузи +4
Марушич +1
Лаззари +1
Патрик -2
Касале -2
Проведель +5
Иммобиле -5
""",
    "Милан": """
Окафор +2
Барнс +1
Чуквуезе +1
Беллингем -2
Рейндерс +5
Лофтус-Чик +1
Эрнандез -3
Кьяер +1
Томори -3
Калабрия -3
Маньян -5
Калулу -1
Муса +1
""",
    "Наполи": """
Осимен +3
Квара +2
Зелински -1
Руи -2
Рахмани +1
ди лоренцо +1
Мерет +3
""",
    "Рома": """
Абрахам -2
Азмун +5
Пеллегрини +2
эль шарави +2
Залевски +1
Кристанте +1
Спиназолла +1
Ндика -2
Смоллинг +4
Карсдорп +2
Патрисио +2
""",
    "Фиорентина": """
Гонзалез +2
Нзола +3
Соттиль +2
Бонавентура +2
Лопес +3
Барак +1
Терраччано +7
Бираги -2
Додо -2
Миленкович -2
Куарта -2
""",
    "Бавария": """
Кейн +1
Коман +1
Сане +1
Мюллер -3
Лаймер -5
Горетцка -2
Дэвис +3
мин дже +4
Упамекано +6
Нойер +2
Салах -9
Гнабри +1
Мактоминей -2
""",
    "Байер": """
Шик +1
Хофманн +1
Андрих +2
Паласиос -2
Иконе +2
Хинкапи -2
Тапсоба -2
Фримпонг +1
Градецки +1
""",
    "Вольфсбург": """
Нмеча +2
Линдстром +2
Виммер +2
Сванберг +2
Арнольд +3
Маэле +2
Фишер +4
Лакруа +4
Борнау +1
Кастилс +1
""",
    "Франкфурт": """
Мармуш +8
дина эбимбе +5
Науфф +2
Кох +4
Гётце +3
Нкунку +7
Баку +5
Тута +5
Пачо +8
""",
    "Жирона": """
Савио +4
Саму Гарсия +3
Алейш Гарсия +1
Фергюсон +2
Блинд +2
Газзанига +3
""",
    "Фрайбург": """
Рёль +15
""",
    "Фулхэм": """
Перейра +3
Виллиан +2
Фуллкруг +1
Бейси +4
Диоп +2
Лекуе +1
Лено +1
""",
    "Рубин": """
Ранделович +5
Палмер +1
Дюпин +4
""",
    "Брайтон": """
Адингра +2
Гроб +1
Эступинан +1
Лампти +3
Игорь +1
""",
    "Райо Вальекано": """
Шешко +1
""",
    "Сассуоло": """
Байер +2
Садик +2
Кастильехо +2
""",
    "Вильярреал": """
Гризманн -8
""",
    "Торино": """
Риччи +1
Бонджорно +1
""",
    "Штутгарт": """
Ито +3
""",
}

_LINE_RE = re.compile(
    r"^\s*(.+?)\s*([+-]?\d{1,2})\s*$",
    re.IGNORECASE | re.UNICODE,
)


def _normalize_bump_block(text: str) -> str:
    """Убираем пустые строки, комментарии #..., строки без цифры дельты или с дельтой 0."""
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


def _preview_bumps_for_team(
    team: str, text: str, sleague, scl
) -> tuple[list[str], list[str]]:
    """
    Только чтение: для каждой строки «имя ±N» — текущий и новый overall по нац. и/или ЛЧ.
    Возвращает (строки для печати, ошибки).
    """
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
        ds = m.group(2).strip()
        try:
            delta = int(ds)
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
            new = _clamp_ov(cur + delta)
            dbn = (row_l.name or "").strip()
            hint = f" [как в БД: {db_l}]" if db_l.lower() != name.strip().lower() else ""
            bits.append(f"нац. {cur}→{new} ({dbn}){hint}")
        if row_c is not None:
            cur = int(getattr(row_c, "overall", 0) or 0)
            new = _clamp_ov(cur + delta)
            dbn = (row_c.name or "").strip()
            hint = f" [как в БД: {db_c}]" if db_c.lower() != name.strip().lower() else ""
            bits.append(f"ЛЧ {cur}→{new} ({dbn}){hint}")
        out.append(f"  {name} {delta:+d}   {' | '.join(bits)}")
    return out, err


def main() -> None:
    ap = argparse.ArgumentParser(description="Overall bumps для db/season_2/")
    ap.add_argument(
        "--dry-run",
        action="store_true",
        help="Все найденные игроки: текущий overall → новый (после дельты), без записи в БД",
    )
    ap.add_argument(
        "--apply",
        action="store_true",
        help="Записать изменения, пересобрать season_2/common.db и (по умолчанию) *_synced",
    )
    ap.add_argument(
        "--no-synced",
        action="store_true",
        help="При --apply не трогать league_synced / champions_league_synced / common_synced",
    )
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
                print(f"[{team}] нет строк после нормализации — пропуск")
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
                n_ok, n_err = len(res.ok), len(res.errors)
                total_ok += n_ok
                total_err += n_err
                for s in res.ok:
                    print("  OK ", s)
                for s in res.errors:
                    print("  ERR", s)

        print(f"\nИтого строк (успех): {total_ok}, ошибок: {total_err}")

        if args.dry_run:
            sl.rollback()
            scl.rollback()
            print(
                "\n(dry-run: БД не менялась; показаны потенциальные рейтинги "
                "после clamp 1…99, как при --apply)",
            )
            return

        if total_err and not total_ok:
            sl.rollback()
            scl.rollback()
            print("\nНи одной успешной правки — откат.")
            sys.exit(1)

        sl.commit()
        scl.commit()
        print("\nCommit league + cl:", p_l)
    finally:
        sl.close()
        scl.close()
        el.dispose()
        ec.dispose()

    if args.apply:
        rebuild_common_database_for_disk_paths(p_l, p_c, p_o)
        print("Пересобран season_2 common:", p_o)
        if not args.no_synced:
            from utils import cumulative_mirror

            for team, block in TEAM_BUMPS.items():
                tnorm = _normalize_bump_block(block)
                if not tnorm.strip():
                    continue
                cumulative_mirror.mirror_overall_bumps_for_team(
                    team, tnorm, alternate_names=BUMP_ALTERNATES
                )
            print(
                "Зеркало overall в накопительные БД (если не legacy и есть "
                "league_synced / champions_league_synced): пересобран common_synced.",
            )
    print("Готово.")


if __name__ == "__main__":
    main()
