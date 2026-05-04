"""
Оценки игроков за матчи (игровые метки ☠🥶❤️…) и синхронизация счётчика матчей в БД.

Данные хранятся в ``match_performance_ratings.json`` у корня проекта.
Журнал — только матчи не из симуляций (``match_results.entry_type``).
"""
from __future__ import annotations

import json
import re
from typing import Any

from match_results import list_journal_records_for_ratings, record_key
from utils.player_transfer import _norm_cmp
from utils.utils import PROJECT_ROOT

_RATINGS_FILE = f"{PROJECT_ROOT}/match_performance_ratings.json"

_SECTION_ORDER = ("reserve", "bench", "start")
_SECTION_HEADER = {
    "reserve": "===== reserve =====",
    "bench": "===== bench =====",
    "start": "==== start ====",
}

EMOJI_TO_CODE: dict[str, str] = {
    "☠": "skull",
    "🥶": "cold",
    "❤": "heart",
    "❤️": "heart",
    "👍": "thumbs",
    "🫥": "ghost",
    "😐": "meh",
    "👎": "bad",
}

CODE_TO_EMOJI: dict[str, str] = {
    "skull": "☠",
    "cold": "🥶",
    "heart": "❤️",
    "thumbs": "👍",
    "ghost": "🫥",
    "meh": "😐",
    "bad": "👎",
}

CODE_LEGEND = (
    "☠ — выдающеся: ЛЧ плей-офф / дерби / топ-матч\n"
    "🥶 — выдающеся в обычном туре лиги\n"
    "❤️ — отлично · 👍 — выше среднего · 🫥 — средне · "
    "😐 — ниже среднего · 👎 — очень слабо\n"
    "Без смайлика — в этом матче не играл."
)


def rating_match_key(rec: dict[str, Any]) -> str:
    h = (rec.get("home") or "").strip()
    a = (rec.get("away") or "").strip()
    lg = (rec.get("league") or "").strip()
    t = record_key(h, a, lg, _rec=rec)
    return json.dumps(list(t), ensure_ascii=False)


def find_journal_record_by_rating_key(mk: str) -> dict[str, Any] | None:
    for r in list_journal_records_for_ratings():
        if rating_match_key(r) == mk:
            return dict(r)
    return None


def _load_store() -> dict[str, Any]:
    import os

    if not os.path.isfile(_RATINGS_FILE):
        return {"version": 1, "by_match": {}}
    try:
        with open(_RATINGS_FILE, encoding="utf-8") as f:
            raw = json.load(f)
    except Exception:
        return {"version": 1, "by_match": {}}
    if not isinstance(raw, dict):
        return {"version": 1, "by_match": {}}
    raw.setdefault("version", 1)
    raw.setdefault("by_match", {})
    if not isinstance(raw["by_match"], dict):
        raw["by_match"] = {}
    return raw


def _save_store(data: dict[str, Any]) -> None:
    import os

    tmp = _RATINGS_FILE + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    os.replace(tmp, _RATINGS_FILE)


def get_side_ratings(match_key: str, side: str) -> dict[str, str]:
    st = _load_store()
    ent = st.get("by_match", {}).get(match_key) or {}
    side_d = ent.get(side) or {}
    if not isinstance(side_d, dict):
        return {}
    out: dict[str, str] = {}
    for k, v in side_d.items():
        out[str(k)] = str(v) if v else ""
    return out


def set_side_ratings(match_key: str, side: str, ratings: dict[str, str]) -> None:
    st = _load_store()
    bm = st.setdefault("by_match", {})
    ent = bm.setdefault(match_key, {})
    clean = {str(k): str(v) if v else "" for k, v in ratings.items()}
    ent[side] = clean
    _save_store(st)


def player_row_key(name: str, pos: str) -> str:
    return f"{_norm_cmp(name)}|{_norm_cmp(pos)}"


def _as_in_db_team(t: str) -> str:
    if (t or "").strip().casefold() == "цска":
        return "Цска"
    return (t or "").strip()


def _resolve_team_name_for_session(user_team: str, sess) -> str:
    """
    Имя клуба в этой БД (лига или ЛЧ): как в ``resolve_team_name``,
    плюс нечёткое совпадение по подстроке, если в журнале и в SQLite строки
    расходятся (пробелы, сокращения).
    """
    from utils.transfer_input import distinct_teams_from_league, resolve_team_name

    direct = resolve_team_name(user_team, sess)
    if direct:
        return direct
    raw = _as_in_db_team(user_team)
    if len(raw) < 2:
        return raw
    want = _norm_cmp(raw)
    teams = distinct_teams_from_league(sess)
    for tm in teams:
        if _norm_cmp(tm) == want:
            return tm
    subs: list[str] = []
    for tm in teams:
        tw = _norm_cmp(tm)
        if len(want) >= 3 and (want in tw or tw in want):
            subs.append(tm)
    if len(subs) == 1:
        return subs[0]
    if len(subs) > 1:
        subs.sort(key=lambda x: (abs(len(x) - len(raw)), x.lower()))
        return subs[0]
    return raw


def _roster_buckets_for_canonical(
    sess, canon_team: str
) -> dict[str, list[tuple[str, str, int]]]:
    from data.defender import Defender
    from data.forward import Forward
    from data.goalkeeper import Goalkeeper
    from data.midfielder import Midfielder
    from utils.player_transfer import _filter_team

    t = canon_team
    buckets: dict[str, list[tuple[str, str, int]]] = {
        "start": [],
        "bench": [],
        "reserve": [],
    }
    for Cls in (Forward, Midfielder, Defender, Goalkeeper):
        for r in sess.query(Cls).filter(_filter_team(Cls, t)).all():
            nm = (r.name or "").strip()
            pos = (r.position or "").strip()
            if not nm:
                continue
            ovr = int(r.overall or 0)
            st = (getattr(r, "status", None) or "bench").strip().lower()
            if st not in buckets:
                st = "bench"
            buckets[st].append((nm, pos, ovr))
    for k in buckets:
        buckets[k].sort(key=lambda x: (-x[2], x[0].lower()))
    return buckets


def _roster_buckets_by_status(
    team: str,
    tournament: str = "league",
    *,
    roster_from: str | None = None,
) -> dict[str, list[tuple[str, str, int]]]:
    from utils.utils import get_session

    t_read = roster_from if roster_from is not None else tournament
    sess = get_session(t_read)
    canon = _resolve_team_name_for_session(team, sess)
    return _roster_buckets_for_canonical(sess, canon)


def build_roster_template(
    team: str,
    tournament: str = "league",
    *,
    roster_from: str | None = None,
) -> tuple[str, dict[str, tuple[str, str, int]], str]:
    """
    Возвращает шаблон, карту строк и каноническое имя клуба в БД (для matches/stats).

    ``roster_from`` — из какой БД читать start/bench/reserve (по умолчанию = ``tournament``).
    Для ввода оценок за ЛЧ-матч укажи ``roster_from="league"``, чтобы шаблон совпадал
    с полной заявкой в национальной БД.
    """
    from utils.utils import get_session

    t_read = roster_from if roster_from is not None else tournament
    sess = get_session(t_read)
    canon = _resolve_team_name_for_session(team, sess)
    buckets = _roster_buckets_for_canonical(sess, canon)
    lines: list[str] = []
    key_map: dict[str, tuple[str, str, int]] = {}
    for sec in _SECTION_ORDER:
        lines.append(_SECTION_HEADER[sec])
        for nm, pos, ovr in buckets.get(sec, []):
            pk = player_row_key(nm, pos)
            lines.append(f"{nm} {pos}")
            key_map[pk] = (nm, pos, ovr)
    return "\n".join(lines), key_map, canon


def _strip_first_emoji(line: str) -> tuple[str | None, str]:
    s = line.lstrip()
    if not s:
        return None, ""
    for em in sorted(EMOJI_TO_CODE.keys(), key=len, reverse=True):
        if s.startswith(em):
            rest = s[len(em) :].lstrip()
            return EMOJI_TO_CODE[em], rest
    ch = s[0]
    if ch in EMOJI_TO_CODE:
        return EMOJI_TO_CODE[ch], s[1:].lstrip()
    return None, s


_RE_SPLIT_LINE = re.compile(r"\s*·\s*")


def _extract_code_and_core(line: str) -> tuple[str | None, str]:
    """
    Смайлик оценки — в начале и/или в конце строки (через пробел в конце удобнее).
    Если указаны оба, берётся конечный.
    """
    s = line.strip()
    if not s:
        return None, ""
    code_tail: str | None = None
    rest = s
    for em in sorted(EMOJI_TO_CODE.keys(), key=len, reverse=True):
        if rest.endswith(em):
            code_tail = EMOJI_TO_CODE[em]
            rest = rest[: -len(em)].rstrip()
            break
    code_head, rest = _strip_first_emoji(rest)
    code = code_tail or code_head
    return code, rest.strip()


def _warn_pair(name: str, pos: str) -> str:
    return f"{name.strip()} {pos.strip()}"


def parse_user_rated_lines(
    text: str, expected_keys: dict[str, tuple[str, str, int]]
) -> tuple[dict[str, str], list[str]]:
    ratings: dict[str, str] = {}
    warnings: list[str] = []
    used: set[str] = set()

    for raw_line in (text or "").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("="):
            continue
        code, rest = _extract_code_and_core(line)
        rest = rest.strip()
        if not rest:
            continue

        # Старый формат: Имя · Поз · OVR (из шаблона с рейтингом)
        if "·" in rest:
            parts = _RE_SPLIT_LINE.split(rest)
            if len(parts) < 3:
                warnings.append(f"Пропуск: {rest[:80]}")
                continue
            name, pos = parts[0].strip(), parts[1].strip()
            try:
                ovr = int(parts[2].strip())
            except ValueError:
                warnings.append(_warn_pair(name, pos))
                continue
            pk = player_row_key(name, pos)
            if pk not in expected_keys:
                warnings.append(f"Нет в шаблоне: {_warn_pair(name, pos)}")
                continue
            exp = expected_keys[pk]
            if exp[2] != ovr:
                warnings.append(_warn_pair(name, pos))
            if pk in used:
                warnings.append(f"Дубликат: {_warn_pair(name, pos)}")
            used.add(pk)
            ratings[pk] = code if code else ""
            continue

        # Новый формат: «Имя … позиция» + смайлик; OVR только из БД (key_map)
        tokens = rest.split()
        if len(tokens) < 2:
            warnings.append(f"Пропуск: {raw_line[:80]}")
            continue
        pos = tokens[-1]
        name = " ".join(tokens[:-1])
        pk = player_row_key(name, pos)
        if pk not in expected_keys:
            warnings.append(f"Нет в шаблоне: {_warn_pair(name, pos)}")
            continue
        if pk in used:
            warnings.append(f"Дубликат: {_warn_pair(name, pos)}")
        used.add(pk)
        ratings[pk] = code if code else ""

    for pk in expected_keys:
        if pk not in ratings:
            ratings[pk] = ""
    return ratings, warnings


def format_rated_roster(
    team: str,
    ratings: dict[str, str],
    tournament: str = "league",
    *,
    roster_from: str | None = None,
) -> str:
    buckets = _roster_buckets_by_status(team, tournament, roster_from=roster_from)
    lines: list[str] = []
    for sec in _SECTION_ORDER:
        lines.append(_SECTION_HEADER[sec])
        for nm, pos, ovr in buckets.get(sec, []):
            pk = player_row_key(nm, pos)
            code = (ratings.get(pk) or "").strip()
            em = CODE_TO_EMOJI.get(code, "") if code else ""
            prefix = (em + " ") if em else ""
            lines.append(f"{prefix}{nm} {pos} {ovr}")
    return "\n".join(lines)


def sync_match_appearances_for_side(
    team: str,
    tournament: str,
    key_map: dict[str, tuple[str, str, int]],
    old: dict[str, str],
    new: dict[str, str],
) -> list[str]:
    """Синхронизировать поле ``matches`` при смене набора «сыграл»."""
    import contextlib
    import io

    from player_stats import add_player_stats, revert_player_stats

    old_played = {k for k, v in old.items() if v}
    new_played = {k for k, v in new.items() if v}
    to_drop = old_played - new_played
    to_add = new_played - old_played
    log: list[str] = []

    for pk in to_drop:
        if pk not in key_map:
            log.append(f"⚠ откат: нет ключа {pk}")
            continue
        nm, pos, _ = key_map[pk]
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            ok = revert_player_stats(nm, pos, team, 0, 0, False, tournament)
        line = buf.getvalue().strip()
        if ok:
            log.append(line or f"↩ {nm}")
        else:
            log.append(f"✗ откат {nm}")

    for pk in to_add:
        if pk not in key_map:
            log.append(f"⚠ зачёт: нет ключа {pk}")
            continue
        nm, pos, _ = key_map[pk]
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            ok = add_player_stats(
                nm,
                pos,
                team,
                0,
                0,
                clean_sheet=False,
                tournament=tournament,
                auto_find=True,
                match_for_cs=None,
                skip_discipline_check=True,
                increment_matches=True,
            )
        line = buf.getvalue().strip()
        if ok:
            log.append(line or f"✓ {nm} +матч")
        else:
            log.append(f"✗ зачёт матча {nm}")

    return log


def format_team_ratings_history(league_code: str, team: str) -> str:
    """Сводка по всем матчам из JSON для клуба в этой лиге (+ ЛЧ отдельно по коду cl)."""
    st = _load_store()
    bm = st.get("by_match") or {}
    team_l = _norm_cmp(team)
    lines_out: list[str] = []

    for rec in list_journal_records_for_ratings():
        if (rec.get("league") or "").strip() != league_code.strip():
            continue
        h = (rec.get("home") or "").strip()
        a = (rec.get("away") or "").strip()
        if _norm_cmp(h) != team_l and _norm_cmp(a) != team_l:
            continue
        mk = rating_match_key(rec)
        ent = bm.get(mk) or {}
        side = "home" if _norm_cmp(h) == team_l else "away"
        rdict = ent.get(side) or {}
        if not rdict:
            continue
        hs = rec.get("home_score")
        aws = rec.get("away_score")
        score_s = ""
        if hs is not None and aws is not None:
            score_s = f" {hs}:{aws}"
        title = f"{h} — {a}{score_s}"
        lines_out.append(f"── {title} ──")
        for pk, code in sorted(rdict.items(), key=lambda x: x[0].lower()):
            if not code:
                continue
            em = CODE_TO_EMOJI.get(code, code)
            pretty = pk.replace("|", " ")
            lines_out.append(f"  {em} {pretty}")
        lines_out.append("")

    if not lines_out:
        return "Нет сохранённых оценок для этого клуба в выбранной лиге."
    return "\n".join(lines_out).strip()
