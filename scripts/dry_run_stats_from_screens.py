#!/usr/bin/env python3
"""Dry-run: стата из stats_from_screens_m3_m5.txt → проверка имён (без записи)."""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from player_stats import find_player_by_name, get_session
from scripts.stats_screens_load import blocks_with_tournament
from utils.transfer_input import resolve_team_name
from utils.utils import session_league

NAME_MAP: dict[str, str] = {
    "Guruzeta": "Гурузета",
    "Ben Yedder": "Бен-Йеддер",
    "Sancet": "Сансет",
    "Baumgartner": "Баумгартнер",
    "Vivian": "Вивиан",
    "Cassierra": "Касьерра",
    "Adeyemi": "Адейеми",
    "Dybala": "Дибала",
    "Kobel": "Кобель",
    "Kroos": "Кроос",
    "Nkunku": "Нкунку",
    "Nkounkou": "Нкунку",
    "Marmoush": "Мармуш",
    "Gotze": "Гётце",
    "Garcia": "Гарсия",
    "De Bruyne": "Де Брюйне",
    "Foden": "Фоден",
    "Malen": "Мален",
    "Haaland": "Холанд",
    "Gundogan": "Гюндоган",
    "Palazon": "Палазон",
    "Gavi": "Гави",
    "Cancelo": "Канселу",
    "ter Stegen": "Тер Штеген",
    "Arnautovic": "Арнаутович",
    "Calhanoglu": "Чалханоглу",
    "Silas": "Силас",
    "Carrascal": "Карраскаль",
    "O'Riley": "О'райли",
    "Leao": "Леау",
    "Chavez": "Чавез",
    "Ruiz de Galarreta": "Галаррета",
    "Fernandes": "Фернандес",
    "Zaha": "Заха",
    "Sow": "Соу",
    "Alip": "Алип",
    "Du Queiroz": "Ду Кейрош",
    "Wimmer": "Виммер",
    "Lukaku": "Лукаку",
    "Rodrygo": "Родриго",
    "Kuchaev": "Кучаев",
    "Simeone": "Симеоне",
    "Malcom": "Малком",
    "Lopez": "Лопес",
    "Barak": "Барак",
    "Sottil": "Соттиль",
    "Biraghi": "Бираги",
    "Rocha": "Роша",
    "Jota": "Жота",
    "Szoboszlai": "Собослай",
    "Saka": "Сака",
    "Mario Rui": "Оливера",
    "Hernandez": "Люка Эрнандез",
    "Ramos": "Рамос",
    "Olmo": "Ольмо",
    "Carrasco": "Карраско",
    "Bade": "Баде",
    "Sutalo": "Шутало",
    "Alba": "Альба",
    "Kostic": "Костич",
    "Szczesny": "Чесны",
    "Gabriel": "Габриэль",
    "Sane": "Сане",
    "Kim Min Jae": "Мин Дже",
    "Garnacho": "Гарначо",
    "Goretzka": "Горетцка",
    "Martial": "Марсиаль",
    "Joao Mario": "Мариу",
    "Brozovic": "Брозович",
    "Palhinha": "Палинья",
    "Stones": "Стоунз",
    "Vanaken": "Ванакен",
    "Dias": "Диаш",
    "Schick": "Шик",
    "Ikoné": "Иконе",
    "Alderweireld": "Куарта",
    "Lindstrom": "Линдстром",
    "Nmecha": "Нмеча",
    "Kaminski": "Каминский",
    "Rrahmani": "Рахмани",
    "Arnold": "Арнольд",
    "Di Lorenzo": "Ди Лоренцо",
    "Morata": "Мората",
    "Molina": "Молина",
    "Llorente": "Льоренте",
    "Reinildo": "Рейнилдо",
    "Oblak": "Облак",
    "Otavio": "Отавиу",
    "Ruiz": "Руис",
    "Tapsoba": "Тапсоба",
    "Andrich": "Андрих",
    "Lewandowski": "Лева",
    "Raphinha": "Рафинья",
    "Pedri": "Педри",
    "Lukébakio": "Лукебакио",
    "Goncalves": "Гонсалвеш",
    "Benzema": "Бензема",
    "Gonzalez": "Гонзалез",
    "Bennacer": "Беннасер",
    "Milenkovic": "Миленкович",
    "Kjaer": "Кьяер",
    "Bonaventura": "Бонавентура",
    "Kerzhakov": "Кержаков",
    "Havertz": "Хаверц",
    "Rashford": "Рэшфорд",
    "Kolo Muani": "Коло Муани",
    "Fomin": "Фомин",
    "Rice": "Райс",
    "ElShaarawy": "Эль Шарави",
    "Pulisic": "Пулишич",
    "Herrera": "Эррера",
    "Ander Herrera": "Эррера",
    "Isco": "Иско",
    "Promes": "Промес",
    "Bouanga": "Буанга",
    "Pepe": "Пепе",
    "Kone": "Коне",
    "Livakovic": "Ливакович",
    "Klostermann": "Клостерманн",
    "Openda": "Опенда",
    "Can": "Джан",
    "Fred": "Фред",
    "Kokcu": "Кёкчю",
    "Seiwald": "Сейвальд",
    "Pisarskiy": "Писарский",
    "Ricci": "Риччи",
    "Gare": "Гарре",
    "Berardi": "Берарди",
    "Chiesa": "Кьеза",
    "Mkhitaryan": "Мхитарян",
    "Vlasic": "Влашич",
    "Safonov": "Сафонов",
    "Sportiello": "Спортиелло",
    "Martins": "Мартинс",
    "Kashtanov": "Каштанов",
    "Egorychev": "Егорычев",
    "Ngamaleu": "Нгамалу",
    "Miranchuk": "Миранчук",
    "Williams": "Нико",
    "Roberto": "Роберто",
    "Hartman": "Хартман",
    "Raspadori": "Распадори",
    "Immobile": "Иммобиле",
    "Frattesi": "Фраттези",
    "Locatelli": "Локателли",
    "Kin": "Кин",
    "Mane": "Мане",
    "Dumfries": "Думфрис",
    "Maehle": "Маэле",
    "Dovbyk": "Довбык",
    "Kramaric": "Крамарич",
    "Guimaraes": "Гимараеш",
    "Giroud": "Жиру",
    "Icardi": "Икарди",
    "Beier": "Исаксен",
    "Sommer": "Зоммер",
    "Barella": "Барелла",
    "Messi": "Месси",
    "Ortega": "Ортега",
    "Corona": "Корона",
    "Musiala": "Мусиаля",
    "Koksharov": "Кокшаров",
    "Alonso": "Алонсо",
    "Max": "Макс",
    "Ignatov": "Игнатов",
    "Maksimenko": "Максименко",
    "Davies": "Дэвис",
}

TEAM_HINT: dict[str, str] = {
    "Guruzeta": "Атлетик",
    "Ben Yedder": "Лейпциг",
    "Sancet": "Атлетик",
    "Baumgartner": "Лейпциг",
    "Vivian": "Атлетик",
    "Cassierra": "Дортмунд",
    "Adeyemi": "Дортмунд",
    "Dybala": "Дортмунд",
    "Kobel": "Дортмунд",
    "Kroos": "Реал",
    "Nkunku": "Реал",
    "Nkounkou": "Франкфурт",
    "Marmoush": "Франкфурт",
    "Gotze": "Франкфурт",
    "Garcia": "Реал",
    "De Bruyne": "Сити",
    "Foden": "Сити",
    "Malen": "Дортмунд",
    "Haaland": "Сити",
    "Gundogan": "Барселона",
    "Palazon": "Барселона",
    "Gavi": "Барселона",
    "Cancelo": "Барселона",
    "ter Stegen": "Барселона",
    "Arnautovic": "Интер",
    "Calhanoglu": "Интер",
    "Silas": "Динамо",
    "Carrascal": "Динамо",
    "O'Riley": "Динамо",
    "Leao": "Атлетик",
    "Chavez": "Динамо",
    "Herrera": "Жирона",
    "Ander Herrera": "Атлетик",
    "Sesko": "Динамо",
    "Ruiz de Galarreta": "Атлетик",
    "Fernandes": "Зенит",
    "Zaha": "Зенит",
    "Sow": "Севилья",
    "Alip": "Зенит",
    "Du Queiroz": "Зенит",
    "Wimmer": "Вольфсбург",
    "Lukaku": "Реал",
    "Rodrygo": "Реал",
    "Kuchaev": "Цска",
    "Simeone": "Цска",
    "Malcom": "Фиорентина",
    "Lopez": "Фиорентина",
    "Barak": "Фиорентина",
    "Sottil": "Фиорентина",
    "Biraghi": "Фиорентина",
    "Rocha": "Цска",
    "Jota": "Ливерпуль",
    "Szoboszlai": "Ливерпуль",
    "Saka": "Наполи",
    "Mario Rui": "Наполи",
    "Hernandez": "Наполи",
    "Ramos": "Севилья",
    "Olmo": "Лейпциг",
    "Carrasco": "Севилья",
    "Bade": "Севилья",
    "Nianzu": "Севилья",
    "Alba": "Ювентус",
    "Kostic": "Ювентус",
    "Szczesny": "Ювентус",
    "Gabriel": "Арсенал",
    "Sutalo": "Зенит",
    "Sane": "Бавария",
    "Kim Min Jae": "Бавария",
    "Garnacho": "Мю",
    "Goretzka": "Бавария",
    "Martial": "Мю",
    "Joao Mario": "Бавария",
    "Brozovic": "Мю",
    "Palhinha": "Сити",
    "Stones": "Сити",
    "Vanaken": "Сити",
    "Dias": "Сити",
    "Schick": "Байер",
    "Ikoné": "Байер",
    "Alderweireld": "Фиорентина",
    "Lindstrom": "Вольфсбург",
    "Nmecha": "Вольфсбург",
    "Kaminski": "Вольфсбург",
    "Rrahmani": "Наполи",
    "Arnold": "Вольфсбург",
    "Di Lorenzo": "Наполи",
    "Morata": "Атлетико",
    "Molina": "Атлетико",
    "Llorente": "Атлетико",
    "Reinildo": "Атлетико",
    "Oblak": "Атлетико",
    "Otavio": "Мю",
    "Ruiz": "Байер",
    "Tapsoba": "Франкфурт",
    "Andrich": "Байер",
    "Lewandowski": "Барселона",
    "Raphinha": "Барселона",
    "Pedri": "Барселона",
    "Lukébakio": "Севилья",
    "Goncalves": "Севилья",
    "Fomin": "Зенит",
    "Benzema": "Милан",
    "Gonzalez": "Фиорентина",
    "Bennacer": "Милан",
    "Milenkovic": "Фиорентина",
    "Kjaer": "Милан",
    "Bonaventura": "Фиорентина",
    "Kerzhakov": "Зенит",
    "Havertz": "Арсенал",
    "Rashford": "Сити",
    "Kolo Muani": "Арсенал",
    "Rice": "Арсенал",
    "ElShaarawy": "Бетис",
    "Pulisic": "Жирона",
    "Isco": "Бетис",
    "Promes": "Спартак",
    "Bouanga": "Краснодар",
    "Pepe": "Спартак",
    "Kone": "Боруссия М",
    "Livakovic": "Боруссия М",
    "Klostermann": "Лейпциг",
    "Openda": "Лейпциг",
    "Can": "Дортмунд",
    "Fred": "Дортмунд",
    "Kokcu": "Лейпциг",
    "Seiwald": "Лейпциг",
    "Pisarskiy": "Крылья Советов",
    "Ricci": "Крылья Советов",
    "Gare": "Крылья Советов",
    "Berardi": "Интер",
    "Chiesa": "Ювентус",
    "Mkhitaryan": "Интер",
    "Vlasic": "Ювентус",
    "Safonov": "Краснодар",
    "Sportiello": "Цска",
    "Martins": "Спартак",
    "Kashtanov": "Урал",
    "Egorychev": "Урал",
    "Ngamaleu": "Зенит",
    "Miranchuk": "Локомотив",
    "Roberto": "Барселона",
    "Hartman": "Атлетик",
    "Immobile": "Лацио",
    "Frattesi": "Лацио",
    "Locatelli": "Ювентус",
    "Kin": "Ювентус",
    "Mane": "Интер",
    "Dumfries": "Интер",
    "Barella": "Интер",
    "Sommer": "Интер",
    "Maehle": "Вольфсбург",
    "Dovbyk": "Хоффенхайм",
    "Kramaric": "Хоффенхайм",
    "Guimaraes": "Дортмунд",
    "Giroud": "Жирона",
    "Icardi": "Атлетико",
    "Beier": "Лацио",
    "Messi": "Сити",
    "Ortega": "Сити",
    "Corona": "Франкфурт",
    "Musiala": "Франкфурт",
    "Koksharov": "Краснодар",
    "Alonso": "Краснодар",
    "Max": "Краснодар",
    "Ignatov": "Спартак",
    "Maksimenko": "Спартак",
    "Davies": "Бавария",
    "Frimpong": "Бавария",
    "Kane": "Бавария",
}


def _parse_line(line: str) -> tuple[str, int, int, bool, str | None]:
    low = line.lower().strip()
    if "кк" in low.split():
        name = line.replace("кк", "").strip()
        return name, 0, 0, False, "кк"
    if "жк" in low.split():
        name = line.replace("жк", "").strip()
        return name, 0, 0, False, "жк"
    if low.endswith(" cs") or " cs" in low:
        return line.replace("cs", "").strip(), 0, 0, True, None
    parts = line.split()
    if len(parts) >= 3:
        return " ".join(parts[:-2]), int(parts[-2]), int(parts[-1]), False, None
    if len(parts) == 2:
        return parts[0], int(parts[1]), 0, False, None
    return line, 0, 0, False, None


def main() -> None:
    ok, fail, skip = 0, 0, 0
    lines_out: list[str] = [
        "# Превью: стата со скринов FIFA\n\n",
        "Матчи **уже в журнале**. Запись не выполнялась.\n\n",
    ]
    for label, home, away, hs, aws, month, tournament, stat_lines in blocks_with_tournament():
        if not stat_lines:
            rh = resolve_team_name(home, session_league) or home
            ra = resolve_team_name(away, session_league) or away
            lines_out.append(
                f"## {label} · {rh} {hs}:{aws} {ra} → {tournament.upper()}, day={month}\n\n"
            )
            lines_out.append("- _(нет строк статы — допиши в txt)_\n\n")
            skip += 1
            continue
        sess = get_session(tournament)
        rh = resolve_team_name(home, session_league) or home
        ra = resolve_team_name(away, session_league) or away
        lines_out.append(
            f"## {label} · {rh} {hs}:{aws} {ra} → {tournament}, day={month}\n\n"
        )
        for raw in stat_lines:
            fifa_name, g, a, cs, disc = _parse_line(raw)
            db_name = NAME_MAP.get(fifa_name, fifa_name)
            team = TEAM_HINT.get(fifa_name, rh)
            rt = resolve_team_name(team, session_league) or team
            pl, _ = find_player_by_name(sess, db_name, rt)
            if pl:
                if disc:
                    bot_line = f"{fifa_name} {disc}"
                elif cs:
                    bot_line = f"{fifa_name} cs"
                elif g or a:
                    bot_line = f"{fifa_name} {g} {a}"
                else:
                    bot_line = fifa_name
                lines_out.append(f"- `{bot_line}` → `{pl.name}` ({pl.team})\n")
                ok += 1
            else:
                lines_out.append(
                    f"- **НЕ НАЙДЕН** `{db_name}` @ `{rt}` ← `{raw}`\n"
                )
                fail += 1
        lines_out.append("\n")
    lines_out.append(
        f"---\n**{ok} строк OK**, **{fail} не найдено**, **{skip} матчей без строк**.\n"
    )
    text = "".join(lines_out)
    out = ROOT / "scripts" / "STATS_FROM_SCREENS_PREVIEW.md"
    out.write_text(text, encoding="utf-8")
    print(text)
    print(f"(written {out})")


if __name__ == "__main__":
    main()
