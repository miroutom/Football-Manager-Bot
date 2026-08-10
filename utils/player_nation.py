# -*- coding: utf-8 -*-
"""
Национальность игрока: нормализация подписи и код flagcdn.

``resolve_player_nation`` подставляет нацию из заявок / других строк БД,
если в текущей записи поле пустое или не мапится на флаг.
"""
from __future__ import annotations

import functools
import re
from typing import Any

from utils.player_transfer import _norm_cmp


def player_name_key(full_name: str) -> str:
    s = (full_name or "").replace("-", " ").replace("\u2011", " ").replace("\u2010", " ")
    return " ".join(s.split()).lower()


# Опечатки / варианты → каноническая русская подпись (Title Case).
_NATION_ALIASES: dict[str, str] = {
    "босния и герцеговина": "Босния",
    "босния и герцеговна": "Босния",
    "д р конго": "ДР Конго",
    "д.р. конго": "ДР Конго",
    "др конго": "ДР Конго",
    "конго": "ДР Конго",
    "коста рика": "Коста-Рика",
    "коста-рика": "Коста-Рика",
    "центральноафриканская республика": "ЦАР",
    "цар": "ЦАР",
    "тринидад и тобаго": "Тринидад и Тобаго",
    "юж корея": "Южная Корея",
    "юж. корея": "Южная Корея",
    "кот-д'ивуар": "Кот-д'Ивуар",
    "кот д'ивуар": "Кот-д'Ивуар",
    "котдивуар": "Кот-д'Ивуар",
    "сша": "США",
    "франци": "Франция",
    "франйция": "Франция",
    "gb eng": "Англия",
    "gb sct": "Шотландия",
    "gb wls": "Уэльс",
    "gb nir": "Северная Ирландия",
}

# Игрок (ключ имени) → нация, если в БД пусто / ошибочно.
_PLAYER_NATION_OVERRIDES: dict[str, str] = {
    "кондогбия": "Франция",
    "дардер": "Испания",
    "кафу": "Бразилия",
    "зидорф": "Нидерланды",
    "фиго": "Португалия",
    "барези": "Италия",
    "гулит": "Нидерланды",
    # легенды / иконки с пустой nation в БД
    "пеле": "Бразилия",
    "роналдиньо": "Бразилия",
    "роберто карлос": "Бразилия",
    "гимараеш": "Бразилия",
    "матеус": "Германия",
    "зидан": "Франция",
    "макелеле": "Франция",
    "десали": "Франция",
    "жиноля": "Франция",
    "верон": "Аргентина",
    "креспо": "Аргентина",
    "гидо родригез": "Аргентина",
    "каннаваро": "Италия",
    "инсинье": "Италия",
    "шевченко": "Украина",
    "кайседо": "Эквадор",
    "эссьен": "Гана",
    "мане": "Сенегал",
    "клюйверт": "Нидерланды",
    "патрик клюйверт": "Нидерланды",
    "уокер": "Англия",
    "коул": "Англия",
    "джо коул": "Англия",
    "овен": "Англия",
    "скоулз": "Англия",
    "рой кин": "Ирландия",
    "торрес": "Испания",
    "перез гуедес": "Португалия",
    "бута": "Португалия",
    "кадыоглу": "Турция",
    "файзуллаев": "Узбекистан",
    "аль-мусрати": "Ливия",
}

_FLAG_RU: dict[str, str] = {
    "РОССИЯ": "ru",
    "РФ": "ru",
    "ИСПАНИЯ": "es",
    "ИТАЛИЯ": "it",
    "ФРАНЦИЯ": "fr",
    "ГЕРМАНИЯ": "de",
    "АНГЛИЯ": "gb-eng",
    "ШОТЛАНДИЯ": "gb-sct",
    "УЭЛЬС": "gb-wls",
    "СЕВЕРНАЯ ИРЛАНДИЯ": "gb-nir",
    "ОЛСТЕР": "gb-nir",
    "ВЕЛИКОБРИТАНИЯ": "gb",
    "БРИТАНИЯ": "gb",
    "ИРЛАНДИЯ": "ie",
    "БРАЗИЛИЯ": "br",
    "АРГЕНТИНА": "ar",
    "ПОРТУГАЛИЯ": "pt",
    "ПОЛЬША": "pl",
    "УКРАИНА": "ua",
    "ХОРВАТИЯ": "hr",
    "СЕРБИЯ": "rs",
    "БЕЛЬГИЯ": "be",
    "НИДЕРЛАНДЫ": "nl",
    "ГОЛЛАНДИЯ": "nl",
    "АВСТРИЯ": "at",
    "ШВЕЙЦАРИЯ": "ch",
    "ШВЕЦИЯ": "se",
    "НОРВЕГИЯ": "no",
    "ДАНИЯ": "dk",
    "ФИНЛЯНДИЯ": "fi",
    "ТУРЦИЯ": "tr",
    "ГРЕЦИЯ": "gr",
    "ЧЕХИЯ": "cz",
    "СЛОВАКИЯ": "sk",
    "ВЕНГРИЯ": "hu",
    "РУМЫНИЯ": "ro",
    "БОЛГАРИЯ": "bg",
    "ЯПОНИЯ": "jp",
    "КОРЕЯ": "kr",
    "ЮЖНАЯ КОРЕЯ": "kr",
    "КНР": "cn",
    "США": "us",
    "МЕКСИКА": "mx",
    "КАНАДА": "ca",
    "АВСТРАЛИЯ": "au",
    "НИГЕРИЯ": "ng",
    "ГАНА": "gh",
    "СЕНЕГАЛ": "sn",
    "МАРОККО": "ma",
    "АЛЖИР": "dz",
    "ЕГИПЕТ": "eg",
    "УРУГВАЙ": "uy",
    "КОЛУМБИЯ": "co",
    "ЧИЛИ": "cl",
    "ЭКВАДОР": "ec",
    "КАМЕРУН": "cm",
    "ГАБОН": "ga",
    "ЯМАЙКА": "jm",
    "ТОГО": "tg",
    "БУРКИНА-ФАСО": "bf",
    "БУРКИНАФАСО": "bf",
    "КОТ-Д'ИВУАР": "ci",
    "КОТ Д'ИВУАР": "ci",
    "КОТДИВУАР": "ci",
    "ИРАН": "ir",
    "САУДОВСКАЯ АРАВИЯ": "sa",
    "ИСЛАНДИЯ": "is",
    "ПАРАГВАЙ": "py",
    "АНГОЛА": "ao",
    "АЛБАНИЯ": "al",
    "ЧЕРНОГОРИЯ": "me",
    "КОСОВО": "xk",
    "СЕВЕРНАЯ МАКЕДОНИЯ": "mk",
    "МАКЕДОНИЯ": "mk",
    "ЭКВАТОРИАЛЬНАЯ ГВИНЕЯ": "gq",
    "СЛОВЕНИЯ": "si",
    "БОСНИЯ": "ba",
    "ИЗРАИЛЬ": "il",
    "ИСРАИЛЬ": "il",
    "ГРУЗИЯ": "ge",
    "АРМЕНИЯ": "am",
    "АЗЕРБАЙДЖАН": "az",
    "КАЗАХСТАН": "kz",
    "УЗБЕКИСТАН": "uz",
    "БОЛИВИЯ": "bo",
    "ВЕНЕСУЭЛА": "ve",
    "МОЗАМБИК": "mz",
    "КАБО-ВЕРДЕ": "cv",
    "ДОМИНИКАНСКАЯ РЕСПУБЛИКА": "do",
    "ЛИТВА": "lt",
    "ЛЮКСЕМБУРГ": "lu",
    "ГВИНЕЯ": "gn",
    "ДР КОНГО": "cd",
    "КОНГО": "cg",
    "МОЛДАВИЯ": "md",
    "МАЛИ": "ml",
    "ПЕРУ": "pe",
    "ГАМБИЯ": "gm",
    "МАЛЬТА": "mt",
    "ЗИМБАБВЕ": "zw",
    "ЛИВИЯ": "ly",
    "ЛИБЕРИЯ": "lr",
    "КОСТА-РИКА": "cr",
    "ТРИНИДАД И ТОБАГО": "tt",
    "ЦАР": "cf",
}

_FLAG_EN: dict[str, str] = {
    "ENGLAND": "gb-eng",
    "SCOTLAND": "gb-sct",
    "WALES": "gb-wls",
    "NORTHERN IRELAND": "gb-nir",
    "UNITED KINGDOM": "gb",
    "GREAT BRITAIN": "gb",
    "UK": "gb",
    "IRELAND": "ie",
    "REPUBLIC OF IRELAND": "ie",
    "RUSSIA": "ru",
    "SPAIN": "es",
    "ITALY": "it",
    "FRANCE": "fr",
    "GERMANY": "de",
    "BRAZIL": "br",
    "ARGENTINA": "ar",
    "PORTUGAL": "pt",
    "POLAND": "pl",
    "UKRAINE": "ua",
    "CROATIA": "hr",
    "SERBIA": "rs",
    "BELGIUM": "be",
    "NETHERLANDS": "nl",
    "AUSTRIA": "at",
    "SWITZERLAND": "ch",
    "SWEDEN": "se",
    "NORWAY": "no",
    "DENMARK": "dk",
    "FINLAND": "fi",
    "TURKEY": "tr",
    "GREECE": "gr",
    "CZECHIA": "cz",
    "CZECH REPUBLIC": "cz",
    "SLOVAKIA": "sk",
    "ROMANIA": "ro",
    "BULGARIA": "bg",
    "JAPAN": "jp",
    "SOUTH KOREA": "kr",
    "CHINA": "cn",
    "USA": "us",
    "MEXICO": "mx",
    "CANADA": "ca",
    "AUSTRALIA": "au",
    "NIGERIA": "ng",
    "GHANA": "gh",
    "SENEGAL": "sn",
    "MOROCCO": "ma",
    "ALGERIA": "dz",
    "EGYPT": "eg",
    "URUGUAY": "uy",
    "COLOMBIA": "co",
    "CHILE": "cl",
    "ECUADOR": "ec",
    "CAMEROON": "cm",
    "GABON": "ga",
    "JAMAICA": "jm",
    "TOGO": "tg",
    "BURKINA FASO": "bf",
    "IVORY COAST": "ci",
    "COTE D'IVOIRE": "ci",
    "CÔTE D'IVOIRE": "ci",
    "IRAN": "ir",
    "SAUDI ARABIA": "sa",
    "ICELAND": "is",
    "PARAGUAY": "py",
    "ANGOLA": "ao",
    "ALBANIA": "al",
    "MONTENEGRO": "me",
    "KOSOVO": "xk",
    "NORTH MACEDONIA": "mk",
    "MACEDONIA": "mk",
    "EQUATORIAL GUINEA": "gq",
    "SLOVENIA": "si",
    "BOSNIA": "ba",
    "ISRAEL": "il",
    "GEORGIA": "ge",
    "ARMENIA": "am",
    "AZERBAIJAN": "az",
    "KAZAKHSTAN": "kz",
    "UZBEKISTAN": "uz",
    "BOLIVIA": "bo",
    "VENEZUELA": "ve",
    "MOZAMBIQUE": "mz",
    "CAPE VERDE": "cv",
    "CABO VERDE": "cv",
    "DOMINICAN REPUBLIC": "do",
    "LITHUANIA": "lt",
    "LUXEMBOURG": "lu",
    "GUINEA": "gn",
    "DR CONGO": "cd",
    "DRC": "cd",
    "CONGO DR": "cd",
    "MOLDOVA": "md",
    "MALI": "ml",
    "PERU": "pe",
    "GAMBIA": "gm",
    "MALTA": "mt",
    "ZIMBABWE": "zw",
    "LIBYA": "ly",
    "LIBERIA": "lr",
    "COSTA RICA": "cr",
    "TRINIDAD AND TOBAGO": "tt",
    "CENTRAL AFRICAN REPUBLIC": "cf",
    "CAR": "cf",
}


def _alias_key(raw: str) -> str:
    s = (raw or "").strip().casefold().replace("ё", "е")
    for ch in ("\u2019", "\u2018", "`", "\u00b4", "\u02bc", "\u02bb"):
        s = s.replace(ch, "'")
    s = re.sub(r"[.\u00b7]", " ", s)
    s = " ".join(s.split())
    return _NATION_ALIASES.get(s, s)


def normalize_nation_label(raw: str | None) -> str | None:
    """Каноническая подпись нации или ``None``."""
    if raw is None:
        return None
    s = str(raw).strip()
    if not s or s in ("—", "-", "?"):
        return None
    if len(s) == 2 and s.isalpha():
        return s.upper()
    key = _alias_key(s)
    if key != s.casefold():
        return key
    if s.isupper() and len(s) > 2:
        parts = s.title().split()
        return "-".join(p.capitalize() if "-" not in p else p for p in " ".join(parts).split("-"))
    return s


def normalize_player_nation_for_db(raw: str) -> str | None:
    """Нация для записи в БД: алиасы, регистр, имя сборной ЧМ если есть."""
    from utils.wc_callups import resolve_nation_name

    norm = normalize_nation_label(raw)
    if not norm:
        return None
    return resolve_nation_name(norm) or norm


def nation_to_flagcdn_code(raw: str | None) -> str | None:
    """Код для flagcdn: ISO2 (``de``) или UK-подрегион ``gb-eng`` …"""
    norm = normalize_nation_label(raw)
    if not norm:
        return None
    if len(norm) == 2 and norm.isalpha():
        return norm.lower()
    s = norm.replace("\u2019", "'").replace("\u2018", "'").upper()
    if not s:
        return None
    if len(s) == 2 and s.isalpha():
        return s.lower()
    return _FLAG_RU.get(s) or _FLAG_EN.get(s)


@functools.lru_cache(maxsize=1)
def _squad_nation_by_team_name() -> dict[tuple[str, str], str]:
    from utils.merged_national_squads import merged_national_squads

    out: dict[tuple[str, str], str] = {}
    for team, rows in merged_national_squads().items():
        for r in rows:
            nat = normalize_nation_label(r[3] if len(r) > 3 else None)
            if nat:
                out[(player_name_key(str(r[0])), team.strip())] = nat
    return out


@functools.lru_cache(maxsize=1)
def _squad_nation_by_name() -> dict[str, str]:
    from utils.merged_national_squads import merged_national_squads

    counts: dict[str, set[str]] = {}
    for _team, rows in merged_national_squads().items():
        for r in rows:
            nat = normalize_nation_label(r[3] if len(r) > 3 else None)
            if not nat:
                continue
            nk = player_name_key(str(r[0]))
            counts.setdefault(nk, set()).add(nat)
    return {k: next(iter(v)) for k, v in counts.items() if len(v) == 1}


def _name_search_variants(name: str) -> list[str]:
    nm = (name or "").strip()
    if not nm:
        return []
    parts = nm.split()
    out = [nm]
    if len(parts) > 1:
        out.append(parts[-1])
        out.append(parts[0])
    seen: set[str] = set()
    uniq: list[str] = []
    for s in out:
        k = s.casefold()
        if k not in seen:
            seen.add(k)
            uniq.append(s)
    return uniq


def _lookup_nation_in_session(session: Any, name: str, team: str | None = None) -> str | None:
    from data.defender import Defender
    from data.forward import Forward
    from data.goalkeeper import Goalkeeper
    from data.midfielder import Midfielder
    from utils.player_transfer import _filter_team

    team_db = (team or "").strip()
    found: list[str] = []
    for Cls in (Forward, Midfielder, Defender, Goalkeeper):
        q = session.query(Cls)
        if team_db:
            q = q.filter(_filter_team(Cls, team_db))
        for row in q.all():
            row_name = (getattr(row, "name", None) or "").strip()
            if not row_name:
                continue
            row_keys = {_norm_cmp(v) for v in _name_search_variants(row_name)}
            for cand in _name_search_variants(name):
                if _norm_cmp(cand) in row_keys:
                    nat = normalize_nation_label(getattr(row, "nation", None))
                    if nat and nation_to_flagcdn_code(nat):
                        found.append(nat)
                    break
    if not found:
        return None
    uniq = set(found)
    if len(uniq) == 1:
        return found[0]
    return None


def resolve_player_nation(
    name: str,
    team: str | None,
    db_nation: str | None,
    session: Any | None = None,
) -> str | None:
    """
    Нация для отображения флага: БД → заявка → другие строки БД → override.
    """
    nk = player_name_key(name)
    if nk in _PLAYER_NATION_OVERRIDES:
        return _PLAYER_NATION_OVERRIDES[nk]

    nat = normalize_nation_label(db_nation)
    if nat and nation_to_flagcdn_code(nat):
        return nat

    team_db = (team or "").strip()
    by_team = _squad_nation_by_team_name()
    hit = by_team.get((nk, team_db))
    if hit:
        return hit

    by_name = _squad_nation_by_name()
    if nk in by_name:
        return by_name[nk]

    if session is not None:
        from_team = _lookup_nation_in_session(session, name, team_db or None)
        if from_team:
            return from_team
        any_team = _lookup_nation_in_session(session, name, None)
        if any_team:
            return any_team

    return nat


def backfill_nation_for_row(name: str, team: str | None, db_nation: str | None, session: Any) -> str | None:
    """Новое значение ``nation`` для записи БД или ``None`` если менять не нужно."""
    resolved = resolve_player_nation(name, team, db_nation, session)
    if not resolved:
        return None
    cur = normalize_nation_label(db_nation)
    if cur == resolved and nation_to_flagcdn_code(cur):
        return None
    if cur and nation_to_flagcdn_code(cur) and cur != resolved:
        # не перезаписываем валидную нацию, кроме явных override (уже выше)
        if player_name_key(name) not in _PLAYER_NATION_OVERRIDES:
            return None
    return resolved


def effective_player_nation(
    name: str,
    team: str | None,
    db_nation: str | None,
    session: Any | None = None,
) -> str | None:
    """Каноническая нация для пулов сборных и автовызовов."""
    from utils.wc_callups import resolve_nation_name

    raw = resolve_player_nation(name, team, db_nation, session)
    if not raw:
        return None
    return resolve_nation_name(raw) or raw
