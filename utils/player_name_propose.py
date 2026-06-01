# -*- coding: utf-8 -*-
"""Предложение имени/фамилии без привязки к реальному клубу игрока."""
from __future__ import annotations

import json
import os
import time
import urllib.parse
import urllib.request
from typing import Any

from utils.player_names import player_first_name, player_surname
from utils.player_transfer import _cyrillic_to_latin_lc, _norm_cmp, normalize_player_name_for_db

# Национальность в БД → Wikidata QID страны гражданства
NATION_TO_WIKIDATA: dict[str, str] = {
    "англия": "Q21",
    "Англия": "Q21",
    "аргентина": "Q414",
    "Аргентина": "Q414",
    "бельгия": "Q31",
    "Бельгия": "Q31",
    "бразилия": "Q155",
    "Бразилия": "Q155",
    "германия": "Q183",
    "Германия": "Q183",
    "голландия": "Q55",
    "Нидерланды": "Q55",
    "греция": "Q41",
    "Греция": "Q41",
    "гвинея": "Q1006",
    "дания": "Q35",
    "Дания": "Q35",
    "испания": "Q29",
    "Испания": "Q29",
    "италия": "Q38",
    "Италия": "Q38",
    "колумбия": "Q739",
    "Колумбия": "Q739",
    "марокко": "Q1028",
    "Марокко": "Q1028",
    "нигерия": "Q1033",
    "Нигерия": "Q1033",
    "норвегия": "Q20",
    "Норвегия": "Q20",
    "парагвай": "Q733",
    "Парагвай": "Q733",
    "португалия": "Q45",
    "Португалия": "Q45",
    "россия": "Q159",
    "Россия": "Q159",
    "сербия": "Q403",
    "Сербия": "Q403",
    "сша": "Q30",
    "США": "Q30",
    "турция": "Q43",
    "Турция": "Q43",
    "украина": "Q212",
    "Украина": "Q212",
    "уругвай": "Q77",
    "Уругвай": "Q77",
    "франция": "Q142",
    "Франция": "Q142",
    "хорватия": "Q224",
    "Хорватия": "Q224",
    "чехия": "Q213",
    "Чехия": "Q213",
    "швейцария": "Q39",
    "Швейцария": "Q39",
    "швеция": "Q34",
    "Швеция": "Q34",
    "шотландия": "Q22",
    "Шотландия": "Q22",
    "австрия": "Q40",
    "Австрия": "Q40",
    "алжир": "Q262",
    "Алжир": "Q262",
    "буркина-фасо": "Q965",
    "венгрия": "Q28",
    "Венгрия": "Q28",
    "гана": "Q117",
    "Гана": "Q117",
    "габон": "Q750",
    "Габон": "Q750",
    "камерун": "Q1009",
    "Камерун": "Q1009",
    "кот-д'ивуар": "Q1008",
    "Кот-д'Ивуар": "Q1008",
    "польша": "Q36",
    "Польша": "Q36",
    "румыния": "Q218",
    "Румыния": "Q218",
    "сенегал": "Q1041",
    "Сенегал": "Q1041",
    "словация": "Q214",
    "Словакия": "Q214",
    "словения": "Q215",
    "Словения": "Q215",
    "юж. корея": "Q884",
    "Юж. Корея": "Q884",
    "япония": "Q17",
    "Япония": "Q17",
    "эквадор": "Q736",
    "Эквадор": "Q736",
    "эстония": "Q191",
    "Эстония": "Q191",
    "армения": "Q399",
    "Армения": "Q399",
    "австралия": "Q408",
    "Австралия": "Q408",
    "канада": "Q16",
    "Канада": "Q16",
    "мексика": "Q96",
    "Мексика": "Q96",
    "чили": "Q298",
    "Чили": "Q298",
    "перу": "Q419",
    "Перу": "Q419",
    "венесуэла": "Q717",
    "Венесуэла": "Q717",
    "ирландия": "Q27",
    "Ирландия": "Q27",
    "уэльс": "Q25",
    "Уэльс": "Q25",
    "грузия": "Q230",
    "Грузия": "Q230",
    "казахстан": "Q232",
    "Казахстан": "Q232",
    "узбекистан": "Q265",
    "Узбекистан": "Q265",
    "беларусь": "Q184",
    "Беларусь": "Q184",
    "молдова": "Q217",
    "Молдова": "Q217",
    "литва": "Q37",
    "Литва": "Q37",
    "латвия": "Q211",
    "Латвия": "Q211",
    "босния": "Q225",
    "Босния": "Q225",
    "черногория": "Q236",
    "Черногория": "Q236",
    "македония": "Q221",
    "Македония": "Q221",
    "албания": "Q222",
    "Албания": "Q222",
    "косово": "Q1246",
    "Косово": "Q1246",
    "исландия": "Q189",
    "Исландия": "Q189",
    "финляндия": "Q33",
    "Финляндия": "Q33",
    "египет": "Q79",
    "Египет": "Q79",
    "тунис": "Q948",
    "Тунис": "Q948",
    "юар": "Q258",
    "ЮАР": "Q258",
    "замбия": "Q953",
    "Замбия": "Q953",
    "зимбабве": "Q954",
    "Зимбабве": "Q954",
    "ямайка": "Q766",
    "Ямайка": "Q766",
    "куба": "Q241",
    "Куба": "Q241",
    "китай": "Q148",
    "Китай": "Q148",
    "иран": "Q794",
    "Иран": "Q794",
    "ирак": "Q796",
    "Ирак": "Q796",
    "сауд. аравия": "Q851",
    "Сауд. Аравия": "Q851",
    "оаэ": "Q878",
    "ОАЭ": "Q878",
    "катар": "Q846",
    "Катар": "Q846",
}

_FOOTBALL_OCCUPATION_QIDS = frozenset(
    {
        "Q937857",  # association football player
        "Q61672138",  # professional association football player
        "Q19204627",  # association football midfielder (instance misuse sometimes)
    }
)
_FOOTBALL_INSTANCE_QIDS = frozenset({"Q5"})  # human


def nation_wikidata_qid(nation: str) -> str | None:
    n = (nation or "").strip()
    if not n:
        return None
    if n in NATION_TO_WIKIDATA:
        return NATION_TO_WIKIDATA[n]
    key = n.title()
    return NATION_TO_WIKIDATA.get(key) or NATION_TO_WIKIDATA.get(n.lower())


def is_already_split(row: Any) -> bool:
    fn = (getattr(row, "name", None) or "").strip()
    sn = (getattr(row, "surname", None) or "").strip()
    if not fn or not sn:
        return False
    if _norm_cmp(fn) == _norm_cmp(sn):
        return False
    if len(fn.split()) >= 2:
        return False
    if sn.lower().endswith(fn.lower()) and len(sn.split()) > 1:
        return False
    return True


def propose_split_from_fields(row: Any) -> tuple[str, str] | None:
    """
    Разобрать уже записанное полное имя: «Алейш Гарсия» + surname «Гарсия» → Алейш / Гарсия.

    Не режет «Смит Роу» / «Коло Муани», если имя и фамилия в БД совпадают целиком.
    """
    raw_name = normalize_player_name_for_db(getattr(row, "name", None) or "")
    raw_sn = normalize_player_name_for_db(getattr(row, "surname", None) or "")

    if raw_name and raw_sn and _norm_cmp(raw_name) == _norm_cmp(raw_sn):
        return None

    if len(raw_name.split()) < 2:
        return None

    parts = raw_name.split()
    sn_last = parts[-1]
    first = " ".join(parts[:-1])
    if not first:
        return None

    if raw_sn and _norm_cmp(raw_sn) == _norm_cmp(sn_last):
        return first.title(), sn_last.title()
    if not raw_sn:
        return first.title(), sn_last.title()
    return None


def current_listing_label(row: Any) -> str:
    """Как в примере: «Хаверц» или «Коло Муани» (без имени, если его нет)."""
    fn = player_first_name(row)
    sn = player_surname(row)
    if is_already_split(row):
        return sn
    if fn and _norm_cmp(fn) != _norm_cmp(sn):
        if len(fn.split()) >= 2:
            return fn
        return sn or fn
    return sn or fn


def format_player_line(row: Any) -> str:
    pos = (getattr(row, "position", None) or "").strip()
    ovr = int(getattr(row, "overall", 0) or 0)
    nat = (getattr(row, "nation", None) or "").strip().title()
    return f"{current_listing_label(row)} {pos} {ovr} {nat}".strip()


def format_proposed_full(first: str, surname: str) -> str:
    return f"{first.strip().title()} {surname.strip().title()}".strip()


def names_need_update(row: Any, first: str, surname: str) -> bool:
    cur_fn = (getattr(row, "name", None) or "").strip().title()
    cur_sn = (getattr(row, "surname", None) or "").strip().title()
    return _norm_cmp(cur_fn) != _norm_cmp(first) or _norm_cmp(cur_sn) != _norm_cmp(surname)


def extract_first_from_label(label: str, surname: str) -> str:
    label = (label or "").strip()
    surname = (surname or "").strip()
    if not label or not surname:
        return ""

    def _strip_suffix(lbl: str, suf: str) -> str:
        if not suf:
            return ""
        li, si = lbl.lower(), suf.lower()
        if li.endswith(si):
            return lbl[: len(lbl) - len(suf)].strip().rstrip("-").strip().title()
        lp = lbl.split()
        sp = suf.split()
        if len(lp) > len(sp) and [p.lower() for p in lp[-len(sp) :]] == [
            p.lower() for p in sp
        ]:
            return " ".join(lp[: -len(sp)]).title()
        return ""

    first = _strip_suffix(label, surname)
    if first:
        return first

    lat_sn = _cyrillic_to_latin_lc(surname)
    if lat_sn:
        first = _strip_suffix(label, lat_sn)
        if first:
            return first

    lp = label.split()
    if len(lp) >= 2:
        return " ".join(lp[:-1]).title()
    return ""


class WikidataNameLookup:
    """Поиск футболиста по фамилии + стране (без клуба)."""

    def __init__(self, cache_path: str, *, delay_s: float = 0.35) -> None:
        self.cache_path = cache_path
        self.delay_s = delay_s
        self._cache: dict[str, dict] = {}
        self._load_cache()

    def _load_cache(self) -> None:
        if os.path.isfile(self.cache_path):
            try:
                with open(self.cache_path, encoding="utf-8") as f:
                    self._cache = json.load(f)
            except (json.JSONDecodeError, OSError):
                self._cache = {}

    def save_cache(self) -> None:
        os.makedirs(os.path.dirname(self.cache_path) or ".", exist_ok=True)
        with open(self.cache_path, "w", encoding="utf-8") as f:
            json.dump(self._cache, f, ensure_ascii=False, indent=2)

    def _cache_key(self, surname: str, nation: str) -> str:
        return f"{_norm_cmp(surname)}|{_norm_cmp(nation)}"

    def _http_json(self, url: str) -> dict:
        req = urllib.request.Request(
            url,
            headers={"User-Agent": "FootballManagerBot/1.0 (player name suggest)"},
        )
        with urllib.request.urlopen(req, timeout=25) as resp:
            return json.loads(resp.read().decode("utf-8"))

    def _search_queries(self, surname: str) -> list[str]:
        s = surname.strip()
        lat = _cyrillic_to_latin_lc(s)
        out: list[str] = []
        if lat:
            out.append(lat.title())
            out.append(lat)
        if s and _norm_cmp(s) not in {_norm_cmp(x) for x in out}:
            out.append(s)
        return out

    def _entity_claim_qids(self, entity: dict, prop: str) -> set[str]:
        claims = (entity.get("claims") or {}).get(prop) or []
        ids: set[str] = set()
        for c in claims:
            try:
                val = c["mainsnak"]["datavalue"]["value"]
                if isinstance(val, dict) and val.get("id"):
                    ids.add(val["id"])
            except (KeyError, TypeError):
                continue
        return ids

    def _entity_labels(self, entity: dict) -> dict[str, str]:
        labels = entity.get("labels") or {}
        out: dict[str, str] = {}
        for lang in ("ru", "en"):
            if lang in labels:
                out[lang] = (labels[lang].get("value") or "").strip()
        return out

    def _is_footballer_entity(self, entity: dict) -> bool:
        occ = self._entity_claim_qids(entity, "P106")
        if occ & _FOOTBALL_OCCUPATION_QIDS:
            return True
        inst = self._entity_claim_qids(entity, "P31")
        desc = (entity.get("descriptions") or {}).get("en", {}).get("value", "").lower()
        if "football" in desc or "soccer" in desc or "футбол" in desc:
            return True
        return bool(inst & _FOOTBALL_INSTANCE_QIDS and occ)

    def _fetch_entity(self, qid: str) -> dict | None:
        url = f"https://www.wikidata.org/wiki/Special:EntityData/{qid}.json"
        try:
            data = self._http_json(url)
            ent = data.get("entities", {}).get(qid)
            return ent if isinstance(ent, dict) else None
        except Exception:
            return None

    def lookup(
        self, surname: str, nation: str
    ) -> tuple[str, str] | None | list[tuple[str, str]]:
        """
        None — не найдено; tuple — однозначно; list — несколько кандидатов.
        """
        key = self._cache_key(surname, nation)
        if key in self._cache:
            hit = self._cache[key]
            if hit.get("status") == "ok":
                return hit["first"], hit["surname"]
            if hit.get("status") == "multi":
                return [(c["first"], c["surname"]) for c in hit.get("candidates", [])]
            return None

        nat_q = nation_wikidata_qid(nation)
        if not nat_q:
            self._cache[key] = {"status": "no_nation"}
            return None

        candidates: list[tuple[str, str, str]] = []
        seen_q: set[str] = set()

        for lang in ("en", "ru"):
            for q in self._search_queries(surname):
                enc = urllib.parse.quote(q)
                url = (
                    "https://www.wikidata.org/w/api.php?"
                    f"action=wbsearchentities&search={enc}&language={lang}&format=json&limit=12"
                )
                self._collect_candidates(
                    url, nat_q, surname, candidates, seen_q
                )
                time.sleep(self.delay_s)

        uniq: dict[str, tuple[str, str]] = {}
        for first, sn, _qid in candidates:
            uniq[_norm_cmp(first) + "|" + _norm_cmp(sn)] = (first, sn)

        if len(uniq) == 1:
            first, sn = next(iter(uniq.values()))
            self._cache[key] = {"status": "ok", "first": first, "surname": sn}
            return first, sn
        if len(uniq) > 1:
            cands = list(uniq.values())
            self._cache[key] = {
                "status": "multi",
                "candidates": [{"first": a, "surname": b} for a, b in cands],
            }
            return cands
        self._cache[key] = {"status": "miss"}
        return None

    def _collect_candidates(
        self,
        url: str,
        nat_q: str,
        surname: str,
        candidates: list[tuple[str, str, str]],
        seen_q: set[str],
    ) -> None:
        try:
            data = self._http_json(url)
        except Exception:
            return

        for item in data.get("search") or []:
            qid = item.get("id")
            if not qid or qid in seen_q:
                continue
            seen_q.add(qid)
            ent = self._fetch_entity(qid)
            if not ent or not self._is_footballer_entity(ent):
                continue
            countries = self._entity_claim_qids(ent, "P27")
            if nat_q not in countries:
                continue
            labels = self._entity_labels(ent)
            label = labels.get("ru") or labels.get("en") or (item.get("label") or "")
            first = extract_first_from_label(label, surname)
            if not first:
                p735 = self._entity_claim_qids(ent, "P735")
                if p735:
                    g_ent = self._fetch_entity(next(iter(p735)))
                    if g_ent:
                        gl = self._entity_labels(g_ent)
                        first = (gl.get("ru") or gl.get("en") or "").title()
            sn_out = surname.strip().title()
            if first and _norm_cmp(first) != _norm_cmp(sn_out):
                candidates.append((first.title(), sn_out, qid))
        time.sleep(self.delay_s)


def load_manual_hints(path: str) -> dict[str, str]:
    """
    JSON: ``{"Коло Муани|Франция": "Рандал", "forwards:707": "Кай"}``
    Ключ ``table:id`` — только имя; фамилия из строки.
    """
    if not os.path.isfile(path):
        return {}
    with open(path, encoding="utf-8") as f:
        raw = json.load(f)
    if not isinstance(raw, dict):
        return {}
    out: dict[str, str] = {}
    for k, v in raw.items():
        if str(k).startswith("_") or not v:
            continue
        key = str(k).strip()
        val = str(v).strip()
        if "|" in key:
            a, b = key.split("|", 1)
            out[f"{_norm_cmp(a)}|{_norm_cmp(b)}"] = val
        elif ":" in key:
            tbl, rid = key.split(":", 1)
            out[f"{tbl.strip().lower()}:{rid.strip()}"] = val
        else:
            out[_norm_cmp(key)] = val
    return out


def manual_hint_first(
    hints: dict[str, str], row: Any, table: str, surname: str, nation: str
) -> str | None:
    rid = int(getattr(row, "id", 0) or 0)
    for key in (
        f"{table.lower()}:{rid}",
        f"{_norm_cmp(surname)}|{_norm_cmp(nation)}",
        _norm_cmp(surname),
    ):
        if key in hints and hints[key]:
            return hints[key].title()
    return None
