#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Обновление overall и снятие игроков из xlsx «рейтинги».

Формат (две колонки: «Травмы» / «Не травмы»):
  - число — новый absolute overall;
  - ``тж`` / ``tj`` — рейтинг не менять;
  - ``убираем`` — снять с заявки → free_agents.db.

  python3 scripts/apply_ratings_xlsx.py /path/to/рейтинги.xlsx --dry-run
  python3 scripts/apply_ratings_xlsx.py /path/to/рейтинги.xlsx --apply

По умолчанию — активный сезон (``db/season_N/``). Сначала всегда ``--dry-run``.
"""
from __future__ import annotations

import argparse
import os
import sys
from dataclasses import dataclass, field
from typing import Any, Literal

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from utils.common_db import rebuild_common_database
from utils.free_agents_db import is_free_agent_team, release_club_player_to_fa
from utils.player_names import player_display_name, player_matches_query
from utils.player_transfer import _norm_cmp
from utils.squad_roster_sync import _ALL_PLAYER
from utils.utils import session_cl, session_league

ActionKind = Literal["tj", "remove", "set"]

# Сокращения из xlsx → подсказка для однозначного матча (team + фрагмент имени в БД)
DEFAULT_ALIASES: dict[str, dict[str, str]] = {
    "Гравен": {"team": "Ливерпуль", "contains": "Гравенберх"},
    "Обла": {"team": "Атлетико", "contains": "Облак"},
    "Калверт": {"team": "Реал", "contains": "Калверт"},
    "Авоний": {"team": "Реал Сосьедад", "contains": "Авоний"},
    "Лофтус": {"team": "Милан", "contains": "Лофтус"},
    "Спина": {"team": "Рома", "contains": "Спиназолла"},
    "Прауз": {"team": "Фиорентина", "contains": "Прауз"},
    "Алдер": {"team": "Фиорентина", "contains": "Алдер"},
    "Заир": {"team": "Ювентус", "contains": "Заир"},
    "Гиббс": {"team": "Хоффенхайм", "contains": "Гиббс"},
    "Сент": {"team": "Франкфурт", "contains": "Сент"},
    "Ришарлсон": {"team": "Байер", "contains": "Ришарлисон"},
    "Трент": {"team": "Ливерпуль", "contains": "Александер"},
    "Террачиано": {"team": "Милан", "contains": "Террач"},
    "Кастеланос": {"team": "Лацио", "contains": "Кастелланос"},
    "Бонжорно": {"team": "Хоффенхайм", "contains": "Бонджорно"},
    "Барренеча": {"team": "Реал Сосьедад", "contains": "Барренеч"},
    "Шкири": {"team": "Франкфурт", "contains": "кхири"},
    # «не найдено» — опечатки/прозвища в xlsx vs БД
    "Галлардо": {"team": "Дортмунд", "contains": "Галлар"},
    "Гертруда": {"team": "Боруссия М", "contains": "Гертру"},
    "Кин": {"team": "Ювентус", "contains": "Кеан"},
    "Ларсон": {"team": "Франкфурт", "contains": "Ларссон"},
    "Парадес": {"team": "Рома", "contains": "Паредес"},
    "Рояль": {"team": "Тоттенхэм", "contains": "Роял"},
    "Сенжу": {"team": "Фиорентина", "contains": "Сёюндж"},
    "Сергей": {"team": "Мю", "contains": "Милинкович"},
    "Соланке": {"team": "Арсенал", "contains": "Солан"},
    "Сотиль": {"team": "Фиорентина", "contains": "Соттил"},
    "Терш": {"team": "Барселона", "contains": "Штеген"},
}


def _load_aliases(path: str | None) -> dict[str, dict[str, str]]:
    import json

    out = dict(DEFAULT_ALIASES)
    if not path:
        return out
    with open(path, encoding="utf-8") as f:
        raw = json.load(f)
    if isinstance(raw, dict):
        for k, v in raw.items():
            if isinstance(v, dict):
                out[str(k).strip()] = {str(a): str(b) for a, b in v.items()}
    return out


def _filter_by_alias(hits: list[DbHit], alias: dict[str, str] | None) -> list[DbHit]:
    if not alias or not hits:
        return hits
    team_hint = _norm_cmp(alias.get("team") or "")
    contains = (alias.get("contains") or "").casefold()
    out: list[DbHit] = []
    for h in hits:
        r = h.row
        if team_hint and _norm_cmp(getattr(r, "team", "") or "") != team_hint:
            continue
        if contains and contains not in (getattr(r, "name", "") or "").casefold():
            continue
        out.append(h)
    return out


@dataclass
class XlsxEntry:
    xlsx_name: str
    side: str
    kind: ActionKind
    new_overall: int | None = None


@dataclass
class DbHit:
    row: Any
    table: str
    db: str  # league | cl


@dataclass
class ResolvedPlayer:
    xlsx_name: str
    side: str
    kind: ActionKind
    new_overall: int | None
    league_hits: list[DbHit] = field(default_factory=list)
    cl_hits: list[DbHit] = field(default_factory=list)
    error: str = ""


def _clamp(v: int) -> int:
    return max(1, min(99, int(v)))


def _norm_rating(raw: Any) -> tuple[ActionKind, int | None]:
    if raw is None:
        return "tj", None
    if isinstance(raw, (int, float)) and not isinstance(raw, bool):
        return "set", _clamp(int(raw))
    s = str(raw).strip().casefold().replace("ё", "е")
    if s in ("тж", "tj", "т.ж.", "тж.", "same", "—", "-"):
        return "tj", None
    if s in ("убираем", "убрать", "fa", "free agent", "снять"):
        return "remove", None
    if s.isdigit():
        return "set", _clamp(int(s))
    raise ValueError(f"непонятный рейтинг: {raw!r}")


def load_ratings_xlsx(path: str) -> list[XlsxEntry]:
    import openpyxl

    wb = openpyxl.load_workbook(path, read_only=True, data_only=True)
    ws = wb.active
    out: list[XlsxEntry] = []
    seen: set[tuple[str, str, ActionKind, int | None]] = set()
    for row in ws.iter_rows(min_row=3, values_only=True):
        pairs = (
            ("injured", row[0] if len(row) > 0 else None, row[1] if len(row) > 1 else None),
            ("ok", row[3] if len(row) > 3 else None, row[4] if len(row) > 4 else None),
        )
        for side, name_raw, rating_raw in pairs:
            name = str(name_raw or "").strip()
            if not name:
                continue
            kind, ovr = _norm_rating(rating_raw)
            key = (name.casefold(), side, kind, ovr)
            if key in seen:
                continue
            seen.add(key)
            out.append(XlsxEntry(xlsx_name=name, side=side, kind=kind, new_overall=ovr))
    return out


@dataclass
class PlayerIndex:
    db: str
    by_surname: dict[str, list[DbHit]] = field(default_factory=dict)
    by_first: dict[str, list[DbHit]] = field(default_factory=dict)
    by_full: dict[str, list[DbHit]] = field(default_factory=dict)
    all_hits: list[DbHit] = field(default_factory=list)


def _row_tokens(row: Any) -> tuple[str, str, str]:
    from utils.player_names import _name_parts

    raw = (getattr(row, "name", None) or "").strip()
    fn, sn = _name_parts(raw)
    return raw.casefold(), fn.casefold(), sn.casefold()


def _build_index(session, *, db_label: str) -> PlayerIndex:
    idx = PlayerIndex(db=db_label)
    for Cls in _ALL_PLAYER:
        q = session.query(Cls)
        if hasattr(Cls, "left_team"):
            q = q.filter((Cls.left_team.is_(False)) | (Cls.left_team.is_(None)))
        for r in q.all():
            team = (getattr(r, "team", None) or "").strip()
            if not team or is_free_agent_team(team):
                continue
            hit = DbHit(row=r, table=Cls.__tablename__, db=db_label)
            full, fn, sn = _row_tokens(r)
            if full:
                idx.by_full.setdefault(full, []).append(hit)
            if sn:
                idx.by_surname.setdefault(sn, []).append(hit)
            if fn:
                idx.by_first.setdefault(fn, []).append(hit)
            idx.all_hits.append(hit)
    return idx


def _find_hits(index: PlayerIndex, query: str, alias: dict[str, str] | None = None) -> list[DbHit]:
    if alias and alias.get("contains"):
        frag = alias["contains"].casefold()
        team_hint = _norm_cmp(alias.get("team") or "")
        out: list[DbHit] = []
        seen: set[tuple[str, int]] = set()
        for h in index.all_hits:
            r = h.row
            if team_hint and _norm_cmp(getattr(r, "team", "") or "") != team_hint:
                continue
            if frag not in (getattr(r, "name", "") or "").casefold():
                continue
            key = (h.table, int(getattr(r, "id", 0) or 0))
            if key in seen:
                continue
            seen.add(key)
            out.append(h)
        return out

    q = (query or "").strip()
    if not q:
        return []
    qcf = q.casefold()
    seen: set[tuple[str, int]] = set()
    candidates: list[DbHit] = []

    def _add(h: DbHit) -> None:
        key = (h.table, int(getattr(h.row, "id", 0) or 0))
        if key in seen:
            return
        seen.add(key)
        candidates.append(h)

    for h in index.by_full.get(qcf, []):
        _add(h)
    if " " not in q and "." not in q:
        for h in index.by_surname.get(qcf, []):
            _add(h)
        for h in index.by_first.get(qcf, []):
            _add(h)
    else:
        # подстрока по полному имени
        for full, hits in index.by_full.items():
            if qcf in full:
                for h in hits:
                    _add(h)

    return [h for h in candidates if player_matches_query(h.row, q)]


def _collapse_hits(hits: list[DbHit]) -> list[DbHit]:
    """Один hit на (команда, полное имя, позиция) — с max matches."""
    best: dict[tuple[str, str, str], DbHit] = {}
    for h in hits:
        r = h.row
        key = (
            _norm_cmp(getattr(r, "team", "") or ""),
            _norm_cmp(getattr(r, "name", "") or ""),
            _norm_cmp(getattr(r, "position", "") or ""),
        )
        cur = best.get(key)
        if cur is None:
            best[key] = h
            continue
        if int(getattr(r, "matches", 0) or 0) > int(getattr(cur.row, "matches", 0) or 0):
            best[key] = h
    return list(best.values())


def _person_key(row: Any) -> tuple[str, str, str]:
    pid = getattr(row, "person_id", None)
    if pid:
        return ("pid", str(int(pid)), _norm_cmp(getattr(row, "position", "") or ""))
    return (
        "name",
        _norm_cmp(getattr(row, "name", "") or ""),
        _norm_cmp(getattr(row, "position", "") or ""),
    )


def resolve_entry(
    entry: XlsxEntry,
    idx_l: PlayerIndex,
    idx_c: PlayerIndex,
    aliases: dict[str, dict[str, str]],
) -> ResolvedPlayer:
    rp = ResolvedPlayer(
        xlsx_name=entry.xlsx_name,
        side=entry.side,
        kind=entry.kind,
        new_overall=entry.new_overall,
    )
    alias = aliases.get(entry.xlsx_name)
    league_hits = _collapse_hits(_find_hits(idx_l, entry.xlsx_name, alias))
    cl_hits = _collapse_hits(_find_hits(idx_c, entry.xlsx_name, alias))
    if alias and alias.get("team"):
        league_hits = _collapse_hits(_filter_by_alias(league_hits, alias))
        cl_hits = _collapse_hits(_filter_by_alias(cl_hits, alias))

    # Сопоставляем league ↔ cl по person_id или (имя, позиция, клуб через cl pool)
    if not league_hits and not cl_hits:
        rp.error = "не найден"
        return rp

    # Для remove/set нужна однозначная league-строка (команда+позиция)
    if entry.kind in ("remove", "set", "tj"):
        if len(league_hits) > 1:
            teams = sorted({(h.row.team or "").strip() for h in league_hits})
            labels = [
                f"{h.row.team} · {player_display_name(h.row)} · {h.row.position} ovr={h.row.overall}"
                for h in league_hits
            ]
            rp.error = f"неоднозначно ({len(league_hits)}): " + "; ".join(labels)
            rp.league_hits = league_hits
            rp.cl_hits = cl_hits
            return rp
        if len(league_hits) == 0 and cl_hits:
            if entry.kind == "remove":
                labels = [
                    f"{h.row.team} · {player_display_name(h.row)} · {h.row.position} ovr={h.row.overall}"
                    for h in cl_hits
                ]
                rp.error = "только в ЛЧ, нет строки в лиге (remove невозможен): " + "; ".join(labels)
                rp.cl_hits = cl_hits
                return rp
            if len(cl_hits) == 1 and entry.kind in ("set", "tj"):
                rp.cl_hits = cl_hits
                return rp
            labels = [
                f"{h.row.team} · {player_display_name(h.row)} · {h.row.position} ovr={h.row.overall}"
                for h in cl_hits
            ]
            rp.error = "только в ЛЧ: " + "; ".join(labels)
            rp.cl_hits = cl_hits
            return rp

    rp.league_hits = league_hits
    rp.cl_hits = cl_hits
    return rp


def _format_hit(h: DbHit) -> str:
    r = h.row
    return f"{h.db}:{r.team} · {player_display_name(r)} · {r.position} · ovr={r.overall}"


def _preview_line(rp: ResolvedPlayer) -> str:
    if rp.error:
        return f"ERR  [{rp.side}] {rp.xlsx_name} — {rp.error}"
    bits: list[str] = []
    if rp.league_hits:
        h = rp.league_hits[0]
        r = h.row
        cur = int(getattr(r, "overall", 0) or 0)
        if rp.kind == "tj":
            bits.append(f"лига {r.team} · {player_display_name(r)} · {r.position} · ovr={cur} (тж)")
        elif rp.kind == "remove":
            bits.append(f"→ FA {r.team} · {player_display_name(r)} · {r.position} · ovr={cur}")
        else:
            bits.append(
                f"лига {r.team} · {player_display_name(r)} · {r.position} · {cur}→{rp.new_overall}"
            )
    elif rp.cl_hits and rp.kind in ("set", "tj"):
        h = rp.cl_hits[0]
        r = h.row
        cur = int(getattr(r, "overall", 0) or 0)
        if rp.kind == "tj":
            bits.append(f"ЛЧ-only {r.team} · ovr={cur} (тж)")
        else:
            bits.append(f"ЛЧ-only {r.team} · {cur}→{rp.new_overall}")
    for h in rp.cl_hits:
        r = h.row
        cur = int(getattr(r, "overall", 0) or 0)
        if rp.kind == "tj":
            bits.append(f"ЛЧ {r.team} · ovr={cur} (тж)")
        elif rp.kind == "set" and rp.new_overall is not None:
            bits.append(f"ЛЧ {r.team} · {cur}→{rp.new_overall}")
        elif rp.kind == "remove":
            bits.append(f"ЛЧ {r.team} · left")
    return f"OK   [{rp.side}] {rp.xlsx_name}: " + " | ".join(bits)


def _set_overall_on_row(row: Any, new_ovr: int) -> bool:
    cur = int(getattr(row, "overall", 0) or 0)
    if cur == new_ovr:
        return False
    row.overall = _clamp(new_ovr)
    return True


def _apply_set(rp: ResolvedPlayer) -> tuple[list[str], list[str]]:
    ok: list[str] = []
    err: list[str] = []
    new_ovr = rp.new_overall
    assert new_ovr is not None

    if rp.league_hits:
        h = rp.league_hits[0]
        r = h.row
        team = (r.team or "").strip()
        nm = (r.name or "").strip()
        pos = (r.position or "").strip()
        if _set_overall_on_row(r, new_ovr):
            ok.append(f"лига {team} · {nm} · {pos} → {new_ovr}")

        from utils.common_db import resolve_team_name_for_cl_pool
        from utils.player_field_edit import find_player_row as find_player_row_exact

        cl_team = resolve_team_name_for_cl_pool(team)
        if cl_team:
            _Cls, row_c = find_player_row_exact(session_cl, cl_team, nm, pos)
            if row_c is not None and not bool(getattr(row_c, "left_team", False)):
                if _set_overall_on_row(row_c, new_ovr):
                    ok.append(f"ЛЧ {cl_team} · {nm} · {pos} → {new_ovr}")
        return ok, err

    if len(rp.cl_hits) == 1:
        r = rp.cl_hits[0].row
        if _set_overall_on_row(r, new_ovr):
            ok.append(
                f"ЛЧ-only {r.team} · {r.name} · {r.position} → {new_ovr}"
            )
        return ok, err

    err.append(f"{rp.xlsx_name}: нет league-строки")
    return ok, err


def _apply_remove(rp: ResolvedPlayer) -> tuple[list[str], list[str]]:
    ok: list[str] = []
    err: list[str] = []
    if not rp.league_hits:
        err.append(f"{rp.xlsx_name}: нет league-строки")
        return ok, err
    h = rp.league_hits[0]
    r = h.row
    try:
        info = release_club_player_to_fa(
            str(r.name or ""),
            str(r.position or ""),
            str(r.team or ""),
        )
        ok.append(
            f"→ FA {info['from_team']} · {info['name']} · {info['position']}"
        )
    except Exception as e:
        err.append(f"{rp.xlsx_name}: {e}")
    return ok, err


def _action_label(rp: ResolvedPlayer) -> str:
    if rp.kind == "set":
        return str(rp.new_overall)
    if rp.kind == "remove":
        return "убираем"
    return "тж"


def _error_detail(rp: ResolvedPlayer) -> str:
    return f"[{rp.side}] {rp.xlsx_name} ({_action_label(rp)}): {rp.error}"


def _dedupe_errors(items: list[ResolvedPlayer]) -> list[ResolvedPlayer]:
    seen: set[tuple[str, str]] = set()
    out: list[ResolvedPlayer] = []
    for rp in items:
        key = (rp.xlsx_name.casefold(), rp.error)
        if key in seen:
            continue
        seen.add(key)
        out.append(rp)
    return out


def _print_error_sections(
    ambiguous: list[ResolvedPlayer],
    not_found: list[ResolvedPlayer],
) -> None:
    not_found_u = _dedupe_errors(not_found)
    ambiguous_u = _dedupe_errors(ambiguous)

    if not_found_u:
        print(f"\n{'=' * 60}")
        print(f"НЕ НАЙДЕНО ({len(not_found_u)})")
        print("=" * 60)
        for rp in sorted(not_found_u, key=lambda x: (x.xlsx_name.casefold(), x.side)):
            print(f"  · {_error_detail(rp)}")

    if ambiguous_u:
        print(f"\n{'=' * 60}")
        print(f"НЕОДНОЗНАЧНО / НЕПОНЯТНО ({len(ambiguous_u)})")
        print("=" * 60)
        for rp in sorted(ambiguous_u, key=lambda x: (x.xlsx_name.casefold(), x.side)):
            print(f"  · {_error_detail(rp)}")
            if rp.league_hits or rp.cl_hits:
                for h in (rp.league_hits or rp.cl_hits)[:6]:
                    r = h.row
                    print(
                        f"      ? {r.team} · {player_display_name(r)} · "
                        f"{r.position} · ovr={r.overall}"
                    )
                extra = len(rp.league_hits or rp.cl_hits) - 6
                if extra > 0:
                    print(f"      … ещё {extra}")


def main() -> None:
    ap = argparse.ArgumentParser(description="Overall / FA из xlsx рейтинги")
    ap.add_argument("xlsx", help="Путь к рейтинги.xlsx")
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--apply", action="store_true")
    ap.add_argument("--aliases", help="JSON: {\"Торрес\": {\"team\": \"Аталанта\"}, ...}")
    ap.add_argument("--errors-only", action="store_true", help="Только проблемные строки + сводка")
    ap.add_argument("--report", help="Записать проблемные строки в .txt")
    ap.add_argument("--ignore-errors", action="store_true", help="При --apply пропустить ERR строки")
    args = ap.parse_args()
    if args.dry_run == args.apply:
        print("Укажите ровно один флаг: --dry-run или --apply")
        sys.exit(2)

    path = os.path.expanduser(args.xlsx)
    if not os.path.isfile(path):
        print(f"Нет файла: {path}")
        sys.exit(1)

    entries = load_ratings_xlsx(path)
    if not entries:
        print("В xlsx нет строк игроков.")
        sys.exit(1)

    from utils import season_paths

    sn = season_paths.get_active_season()
    print(f"Сезон {sn} · строк в xlsx: {len(entries)}")
    print(f"Файл: {path}\n")

    sleague = session_league
    scl = session_cl
    aliases = _load_aliases(args.aliases)
    idx_l = _build_index(sleague, db_label="league")
    idx_c = _build_index(scl, db_label="cl")
    resolved = [resolve_entry(e, idx_l, idx_c, aliases) for e in entries]

    n_ok = n_err = n_tj = n_set = n_rm = 0
    ambiguous: list[ResolvedPlayer] = []
    not_found: list[ResolvedPlayer] = []

    for rp in resolved:
        if rp.kind == "tj":
            n_tj += 1
        elif rp.kind == "set":
            n_set += 1
        elif rp.kind == "remove":
            n_rm += 1

        line = _preview_line(rp)
        if not args.errors_only:
            print(line)
        if rp.error:
            n_err += 1
            if rp.error.startswith("не найден"):
                not_found.append(rp)
            else:
                ambiguous.append(rp)
        else:
            n_ok += 1

    print(
        f"\nИтого: ok={n_ok}, err={n_err} "
        f"(set={n_set}, remove={n_rm}, тж={n_tj})"
    )
    _print_error_sections(ambiguous, not_found)

    if args.report:
        rep_path = os.path.expanduser(args.report)
        lines: list[str] = []
        nf = _dedupe_errors(not_found)
        amb = _dedupe_errors(ambiguous)
        if nf:
            lines.append(f"НЕ НАЙДЕНО ({len(nf)})")
            lines.extend(f"  · {_error_detail(rp)}" for rp in sorted(nf, key=lambda x: x.xlsx_name))
            lines.append("")
        if amb:
            lines.append(f"НЕОДНОЗНАЧНО ({len(amb)})")
            lines.extend(f"  · {_error_detail(rp)}" for rp in sorted(amb, key=lambda x: x.xlsx_name))
        with open(rep_path, "w", encoding="utf-8") as f:
            f.write("\n".join(lines) + "\n")
        print(f"\nОтчёт: {rep_path}")

    if ambiguous:
        print(f"\n⚠ Неоднозначно: {len(_dedupe_errors(ambiguous))} уникальных")
    if not_found:
        print(f"⚠ Не найдено: {len(_dedupe_errors(not_found))} уникальных")

    if args.dry_run:
        if ambiguous or not_found:
            print("\n(dry-run) Исправьте совпадения в xlsx или добавьте алиасы, затем --apply")
        else:
            print("\n(dry-run) Всё однозначно — можно --apply")
        return

    if args.apply and ambiguous and not args.ignore_errors:
        print("\nОтмена: есть неоднозначные строки. Сначала dry-run и правки.")
        print("  Либо --aliases file.json, либо --apply --ignore-errors")
        sys.exit(1)

    applied_ok: list[str] = []
    applied_err: list[str] = []
    for rp in resolved:
        if rp.error:
            if rp.kind == "tj":
                continue
            applied_err.append(f"{rp.xlsx_name}: {rp.error}")
            continue
        if rp.kind == "tj":
            continue
        if rp.kind == "set":
            ok, err = _apply_set(rp)
        else:
            ok, err = _apply_remove(rp)
        applied_ok.extend(ok)
        applied_err.extend(err)

    if applied_ok:
        try:
            sleague.commit()
            scl.commit()
        except Exception:
            sleague.rollback()
            scl.rollback()
            raise
        rebuild_common_database()
        print(f"\nCommit + common.db пересобран. Изменений: {len(applied_ok)}")
        for s in applied_ok[:40]:
            print(" ", s)
        if len(applied_ok) > 40:
            print(f"  … и ещё {len(applied_ok) - 40}")
    else:
        sleague.rollback()
        scl.rollback()

    if applied_err:
        print(f"\nОшибки apply ({len(applied_err)}):")
        for s in applied_err:
            print(" ", s)
        sys.exit(1)

    print("Готово.")


if __name__ == "__main__":
    main()
