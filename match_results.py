"""
Хранение сыгранных матчей по точной паре (home, away, league).
Эвертон-Сити и Сити-Эвертон — разные матчи, не путаем.

Для ЛЧ ключ журнала включает фазу: одна и та же пара может быть в группе и в плей-оффе
(разные записи: ``cl_phase`` ``league`` vs ``knockout``).

Файл match_results.json:
  v1 (legacy): массив [home, away, league]
  v2: {"version": 2, "matches": [{home, away, league, home_score?, away_score?, day?, ...}, ...]}
  Опционально ``entry_type``: ``play`` (по умолчанию для старых строк) или ``simulation``
  — режим «Ввод оценки» в боте показывает только матчи ``play``.
  Опционально для ЛЧ (league=cl):
  - ``cl_phase``: явный ``"knockout"`` — нокаут (не входит в групповую таблицу в интерфейсе).
    ``"league"`` / ``"group"`` и синонимы — группа. Если поля ``cl_phase`` **нет** (старые записи),
    матч считается **групповым** для расчёта групповой таблицы (см. ``is_cl_group_phase_record``).
  - ``penalties_by_team``: при ничьей в стыке плей-офф — см. bracket_html / документацию.

Фаза для строки ``mixed_schedule`` задаётся опциональным 4-м сегментом (``...;cl;knockout``)
или выводится из групповой сетки ``table.schedule.schedule_cl``.

При «Завершить сезон» живой ``match_results.json`` копируется в
``db/season_N/match_results.json`` и очищается (см. ``utils.season_end``).
"""
import json
import os
import shutil
from typing import Any, Dict, Iterable, Optional

from utils.utils import PROJECT_ROOT

MATCH_RESULTS_FILE = os.path.join(PROJECT_ROOT, 'match_results.json')

LEAGUE_NAMES = {
    'rpl': 'РПЛ',
    'eng': 'АПЛ',
    'esp': 'Ла Лига',
    'ger': 'Бундеслига',
    'ita': 'Серия А',
    'cl': 'ЛЧ',
}


def _norm(s: str) -> str:
    return (s or "").strip().title()


def _key(home, away, tournament):
    return (_norm(home), _norm(away), tournament)


def _normalize_cl_phase(raw) -> str:
    """Для ЛЧ: ``league`` (группа) или ``knockout`` (плей-офф)."""
    if raw is None:
        return "knockout"
    p = str(raw).strip().lower()
    if p in ("league", "group", "лига", "группа", "гр", "groups"):
        return "league"
    return "knockout"


def record_key(
    home,
    away,
    tournament,
    cl_phase=None,
    *,
    _rec: Optional[Dict[str, Any]] = None,
) -> tuple:
    """
    Ключ строки журнала. Для ЛЧ учитывается фаза — группа и плей-офф могут иметь
    одну и ту же пару (дом, гости); для остальных лиг ключ по-прежнему (дом, гости, лига).

    Для записи из JSON (``_rec``): нет/пустой ``cl_phase`` = группа (как
    ``is_cl_group_phase_record``), **не** нокаут. Иначе нельзя ввести тот же
    «по парам» матч в нокауте после группы.
    """
    h, a = _norm(home), _norm(away)
    t = tournament
    if t != "cl":
        return (h, a, t)
    if _rec is not None:
        raw = _rec.get("cl_phase")
        if raw is None or str(raw).strip() == "":
            phase = "league"
        else:
            phase = _normalize_cl_phase(raw)
    else:
        phase = _normalize_cl_phase(cl_phase)
    return (h, a, t, phase)


_CL_GROUP_PAIRS: Optional[frozenset] = None


def _cl_group_phase_pairs() -> frozenset:
    """Пары (дома, гости) из официальной групповой сетки ЛЧ (table.schedule.schedule_cl)."""
    global _CL_GROUP_PAIRS
    if _CL_GROUP_PAIRS is None:
        from table.schedule import schedule_cl

        s = set()
        for matches in schedule_cl.values():
            for line in matches:
                parts = line.split(";")
                if len(parts) >= 2:
                    s.add((_norm(parts[0]), _norm(parts[1])))
        _CL_GROUP_PAIRS = frozenset(s)
    return _CL_GROUP_PAIRS


def cl_phase_from_mixed_schedule_line(match_str: str) -> Optional[str]:
    """
    Какую фазу ЛЧ ожидать для строки ``mixed_schedule``.

    - Не ЛЧ → ``None``.
    - 4-й сегмент (``league`` / ``knockout`` и синонимы) — явно.
    - Иначе: пара есть в групповой сетке ``schedule_cl`` → ``league``, иначе ``knockout``.

    Если одна и та же пара в группе и в плей-оффе совпадает по направлению, в JSON
    расписания укажите 4-й сегмент (например ``...;cl;knockout``).
    """
    parts = [x.strip() for x in match_str.split(";")]
    if len(parts) < 3 or parts[2] != "cl":
        return None
    if len(parts) >= 4:
        return _normalize_cl_phase(parts[3])
    h, a = _norm(parts[0]), _norm(parts[1])
    if (h, a) in _cl_group_phase_pairs():
        return "league"
    return "knockout"


def is_cl_group_phase_record(rec: Dict[str, Any]) -> bool:
    """
    Матч участвует в групповой таблице ЛЧ.

    Явный ``cl_phase``, нормализующийся в ``knockout``, — нет (только нокаут исключаем).

    Поле отсутствует или пустое — да (устаревшие строки только ``league=cl``: считаем группой).
    """
    if str(rec.get("league") or "") != "cl":
        return False
    raw = rec.get("cl_phase")
    if raw is None or str(raw).strip() == "":
        return True
    return _normalize_cl_phase(raw) == "league"


def load_records_and_keys_from_path(path: str) -> tuple[list[dict[str, Any]], set]:
    """
    Прочитать журнал сыгранных из произвольного JSON (архив сезона).
    Не перезаписывает основной ``match_results.json`` при v1.
    """
    if not os.path.isfile(path):
        return [], set()
    try:
        with open(path, encoding="utf-8") as f:
            raw = json.load(f)
    except Exception:
        return [], set()

    if isinstance(raw, list):
        records: list[dict[str, Any]] = []
        keys: set = set()
        for item in raw:
            if not isinstance(item, (list, tuple)) or len(item) < 3:
                continue
            h, a, t = _norm(item[0]), _norm(item[1]), item[2]
            row = {
                "home": h,
                "away": a,
                "league": t,
                "home_score": None,
                "away_score": None,
                "day": None,
            }
            records.append(row)
            keys.add(record_key(h, a, t, _rec=row))
        return records, keys

    if isinstance(raw, dict) and raw.get("version") == 2:
        matches = raw.get("matches", [])
        records = []
        keys = set()
        for m in matches:
            if not isinstance(m, dict):
                continue
            h = _norm(m.get("home", ""))
            a = _norm(m.get("away", ""))
            t = m.get("league")
            if not t:
                continue
            rec: dict[str, Any] = {
                "home": h,
                "away": a,
                "league": t,
                "home_score": m.get("home_score"),
                "away_score": m.get("away_score"),
                "day": m.get("day"),
            }
            if "cl_phase" in m:
                rec["cl_phase"] = m.get("cl_phase")
            if "penalties_by_team" in m:
                rec["penalties_by_team"] = m.get("penalties_by_team")
            if m.get("entry_type"):
                rec["entry_type"] = str(m.get("entry_type")).strip().lower()
            records.append(rec)
            keys.add(record_key(h, a, t, _rec=rec))
        return records, keys

    return [], set()


def compute_cl_group_standings_from_journal(
    team_names: Iterable[str],
    *,
    journal_path: Optional[str] = None,
) -> Dict[str, Any]:
    """
    Построить таблицу группового этапа ЛЧ только из журнала match_results.json.

    ``journal_path`` — альтернативный файл (архив сезона); иначе живой журнал проекта.
    Не использует pickle: нокаут в эту таблицу не попадает.
    """
    from table.team import Team

    names = [_norm(n) for n in team_names]
    teams = {n: Team(n) for n in names}
    if journal_path:
        records, _ = load_records_and_keys_from_path(journal_path)
    else:
        records, _ = load_records_and_keys()
    for r in records:
        if not is_cl_group_phase_record(r):
            continue
        hs, aws = r.get("home_score"), r.get("away_score")
        if hs is None or aws is None:
            continue
        h = _norm(str(r.get("home", "")))
        a = _norm(str(r.get("away", "")))
        if h not in teams or a not in teams:
            continue
        hi, ai = int(hs), int(aws)
        teams[h].update_stats(hi, ai, a)
        teams[a].update_stats(ai, hi, h)
    return teams


def _save_v2(records: list) -> None:
    with open(MATCH_RESULTS_FILE, 'w', encoding='utf-8') as f:
        json.dump(
            {'version': 2, 'matches': records},
            f,
            ensure_ascii=False,
            indent=2,
        )


def load_records_and_keys():
    """
    Загрузить список записей и множество ключей (home, away, league).
    Legacy v1 при первом чтении пересохраняется как v2.
    """
    if not os.path.exists(MATCH_RESULTS_FILE):
        return [], set()

    try:
        with open(MATCH_RESULTS_FILE, 'r', encoding='utf-8') as f:
            raw = json.load(f)
    except Exception:
        return [], set()

    if isinstance(raw, list):
        records = []
        keys = set()
        for item in raw:
            if not isinstance(item, (list, tuple)) or len(item) < 3:
                continue
            h, a, t = _norm(item[0]), _norm(item[1]), item[2]
            row = {
                'home': h,
                'away': a,
                'league': t,
                'home_score': None,
                'away_score': None,
                'day': None,
            }
            if t == 'cl':
                # v1: в источнике нет фазы; как legacy без cl_phase = группа (is_cl_group_phase_record).
                pass
            records.append(row)
            keys.add(record_key(h, a, t, _rec=row))
        if records:
            _save_v2(records)
        return records, keys

    if isinstance(raw, dict) and raw.get('version') == 2:
        matches = raw.get('matches', [])
        records = []
        keys = set()
        for m in matches:
            if not isinstance(m, dict):
                continue
            h = _norm(m.get('home', ''))
            a = _norm(m.get('away', ''))
            t = m.get('league')
            if not t:
                continue
            rec = {
                'home': h,
                'away': a,
                'league': t,
                'home_score': m.get('home_score'),
                'away_score': m.get('away_score'),
                'day': m.get('day'),
            }
            if 'cl_phase' in m:
                rec['cl_phase'] = m.get('cl_phase')
            if 'penalties_by_team' in m:
                rec['penalties_by_team'] = m.get('penalties_by_team')
            if m.get("entry_type"):
                rec["entry_type"] = str(m.get("entry_type")).strip().lower()
            records.append(rec)
            keys.add(record_key(h, a, t, _rec=rec))
        return records, keys

    return [], set()


def load_match_results():
    """Множество сыгранных матчей {(home, away, tournament), ...} — для совместимости."""
    _, keys = load_records_and_keys()
    return keys


def save_match_results(results):
    """Совместимость: сохранить только множество ключей (без счёта)."""
    records = []
    for home, away, league in sorted(results, key=lambda x: (x[2], x[0], x[1])):
        records.append({
            'home': _norm(home),
            'away': _norm(away),
            'league': league,
            'home_score': None,
            'away_score': None,
            'day': None,
        })
    _save_v2(records)


def archive_match_results_json_to_dir(dest_path: str) -> str:
    """
    Скопировать текущий ``match_results.json`` в ``dest_path`` (например
    ``db/season_N/match_results.json``).

    Возвращает ``no_source`` (файла не было), ``ok`` (скопировано), ``copy_failed``.
    """
    if not os.path.isfile(MATCH_RESULTS_FILE):
        return "no_source"
    parent = os.path.dirname(os.path.abspath(dest_path))
    try:
        if parent:
            os.makedirs(parent, exist_ok=True)
        shutil.copy2(MATCH_RESULTS_FILE, dest_path)
        return "ok"
    except OSError:
        return "copy_failed"


def clear_match_results_journal() -> None:
    """Полностью очистить живой журнал (новый сезон): ``{version:2, matches: []}``."""
    _save_v2([])


def remove_cl_knockout_matches_from_journal() -> int:
    """
    Удалить из ``match_results.json`` все матчи ЛЧ **плей-офф** (нокаут).

    Групповой этап ЛЧ (``cl_phase`` группа / legacy без фазы) и остальные лиги
    не трогаются. Нужно при новом сезоне: сетка HTML/PNG читает нокаут из журнала
    (см. ``champions_league/bracket_html.py``).

    Возвращает число удалённых записей.
    """
    records, _ = load_records_and_keys()
    kept: list[dict[str, Any]] = []
    removed = 0
    for r in records:
        if str(r.get("league") or "") == "cl" and not is_cl_group_phase_record(r):
            removed += 1
        else:
            kept.append(r)
    if removed:
        _save_v2(kept)
    return removed


def find_cl_knockout_first_leg_record(second_home: str, second_away: str):
    """
    Для ответного матча стыка найти запись **первого** матча в журнале
    (первый: дома был тот, кто сейчас в гостях; в гостях — кто сейчас дома).
    Только ``cl`` + ``knockout``. Если это первый матч стыка — ``None``.
    """
    sh, sa = _norm(second_home), _norm(second_away)
    records, _ = load_records_and_keys()
    for r in records:
        if r.get("league") != "cl":
            continue
        if _normalize_cl_phase(r.get("cl_phase")) != "knockout":
            continue
        rh, ra = _norm(r.get("home", "")), _norm(r.get("away", ""))
        if rh == sa and ra == sh:
            hs, aws = r.get("home_score"), r.get("away_score")
            if hs is None or aws is None:
                continue
            return r
    return None


def cl_knockout_two_leg_totals(first_leg: dict, second_home: str, second_away: str, hs2: int, as2: int):
    """
    Сумма голов по двум матчам. Первый матч — ``first_leg`` (дом/гость и счёт из журнала),
    второй — ``second_home`` vs ``second_away`` со счётом ``hs2:as2``.
    Возвращает ``(голы_команды_дома_в_1-м, голы_команды_гостей_в_1-м)``.
    """
    fh = _norm(first_leg["home"])
    fa = _norm(first_leg["away"])
    if _norm(second_home) != fa or _norm(second_away) != fh:
        return None
    s1h = int(first_leg["home_score"])
    s1a = int(first_leg["away_score"])
    tot_first_home = s1h + as2
    tot_first_away = s1a + hs2
    return tot_first_home, tot_first_away


def add_match_result(
    home,
    away,
    tournament,
    home_score=None,
    away_score=None,
    day=None,
    cl_phase=None,
    penalties_by_team=None,
    *,
    entry_type: str | None = None,
):
    """Добавить матч в сыгранные. Счёт и день тура — опционально.

    Для ЛЧ: ``cl_phase="league"`` — группа (сетка игнорирует); ``"knockout"`` — плей-офф.
    ``penalties_by_team``: при ничьей по сумме двух матчей — голы в серии по командам
    (ключи — названия как в журнале), см. ``bracket_html``.
    ``entry_type``: ``"play"`` (по умолчанию) или ``"simulation"`` — для режима оценок
    в журнал попадают только матчи с игрой «вручную», не симуляции.
    """
    records, keys = load_records_and_keys()
    h, a = _norm(home), _norm(away)
    if tournament == 'cl':
        phase = _normalize_cl_phase(cl_phase)
        k = record_key(h, a, tournament, phase)
    else:
        phase = None
        k = record_key(h, a, tournament)
    if k in keys:
        return False
    row = {
        'home': h,
        'away': a,
        'league': tournament,
        'home_score': home_score,
        'away_score': away_score,
        'day': day,
    }
    if tournament == 'cl':
        row['cl_phase'] = phase
    if penalties_by_team:
        row['penalties_by_team'] = penalties_by_team
    et = (entry_type or "play").strip().lower()
    if et in ("play", "simulation"):
        row["entry_type"] = et
    records.append(row)
    _save_v2(records)
    return True


def list_journal_records_for_ratings() -> list[dict[str, Any]]:
    """
    Записи ``match_results`` в порядке журнала, только «реальные» матчи
    (``entry_type`` не ``simulation``; у старых записей без поля — считаем ``play``).
    """
    records, _ = load_records_and_keys()
    out: list[dict[str, Any]] = []
    for r in records:
        et = (r.get("entry_type") or "play").strip().lower()
        if et == "simulation":
            continue
        out.append(dict(r))
    return out


def find_journal_match_record(
    home: str,
    away: str,
    tournament: str,
    *,
    cl_phase: str | None = None,
) -> dict[str, Any] | None:
    """Запись матча из журнала (со счётом и метаданными) или ``None``."""
    records, _ = load_records_and_keys()
    h, a = _norm(home), _norm(away)
    lc = (tournament or "").strip().lower()
    if lc != "cl":
        for r in records:
            if str(r.get("league") or "").strip().lower() != lc:
                continue
            if _norm(r.get("home", "")) == h and _norm(r.get("away", "")) == a:
                return dict(r)
        return None
    phases = [_normalize_cl_phase(cl_phase)]
    alt = "knockout" if phases[0] == "league" else "league"
    if alt not in phases:
        phases.append(alt)
    for ph in phases:
        for r in records:
            if str(r.get("league") or "").strip().lower() != "cl":
                continue
            if _normalize_cl_phase(r.get("cl_phase")) != ph:
                continue
            if _norm(r.get("home", "")) == h and _norm(r.get("away", "")) == a:
                return dict(r)
    return None


def is_match_played(home, away, tournament, cl_phase=None):
    """Проверить, сыгран ли конкретный матч.

    Для ЛЧ передайте ``cl_phase`` (``league`` / ``knockout``); если ``None`` для ЛЧ,
    считается ``knockout`` (как матчи из главного меню матч-дня).

    Для ЛЧ также проверяется «альтернативная» фаза: строка ``mixed_schedule`` может
    относить пару к группе, а в журнале оказалась ``knockout`` (или наоборот) —
    иначе слот оставался в «остатке» расписания.
    """
    _, keys = load_records_and_keys()
    if tournament != "cl":
        k = record_key(home, away, tournament)
        return k in keys
    ph = _normalize_cl_phase(cl_phase)
    if record_key(home, away, tournament, ph) in keys:
        return True
    alt = "knockout" if ph == "league" else "league"
    return record_key(home, away, tournament, alt) in keys


def migrate_from_teams(mixed_schedule, get_teams_by_league):
    """
    Миграция: заполнить match_results из pickle (head_to_head).
    Для каждого матча в расписании: если команды уже играли (есть в head_to_head),
    добавляем этот матч в match_results.
    """
    records, keys = load_records_and_keys()
    if keys:
        return 0

    added = 0
    for day_data in mixed_schedule:
        for match_str in day_data.get('matches', []):
            parts = match_str.split(';')
            if len(parts) < 3:
                continue
            home, away, league_code = parts[0], parts[1], parts[2]
            teams = get_teams_by_league(league_code)
            if not teams:
                continue
            home, away = _norm(home), _norm(away)
            if home not in teams or away not in teams:
                continue
            team_home = teams[home]
            if away not in team_home.head_to_head:
                continue
            row = {
                'home': home,
                'away': away,
                'league': league_code,
                'home_score': None,
                'away_score': None,
                'day': None,
            }
            if league_code == 'cl':
                row['cl_phase'] = 'knockout'
            k = record_key(home, away, league_code, _rec=row)
            if k in keys:
                continue
            records.append(row)
            keys.add(k)
            added += 1

    if added > 0:
        _save_v2(records)
    return added


def count_recorded_matches() -> int:
    records, _ = load_records_and_keys()
    return len(records)


def format_played_matches_report(limit: int = 100, league_code: str = None) -> str:
    """Текстовый отчёт по журналу сыгранных матчей."""
    records, _ = load_records_and_keys()
    if league_code:
        records = [r for r in records if r.get('league') == league_code]
    lines = []
    lines.append(f"Файл: {MATCH_RESULTS_FILE}")
    lines.append(f"Всего записей: {len(records)}")
    if league_code:
        lines.append(f"Фильтр лига: {league_code}")
    lines.append("-" * 60)
    tail = records[-limit:] if limit else records
    for r in tail:
        lg = r.get('league', '')
        lg_name = LEAGUE_NAMES.get(lg, lg)
        hs, aws = r.get('home_score'), r.get('away_score')
        if hs is not None and aws is not None:
            score = f" {hs}:{aws}"
        else:
            score = ""
        day = r.get('day')
        day_s = f" | матч-день {day}" if day is not None else ""
        phase_s = ""
        if lg == "cl" and r.get("cl_phase"):
            phase_s = f" | фаза {r.get('cl_phase')}"
        lines.append(
            f"  [{lg_name}] {r.get('home', '')} — {r.get('away', '')}{score}{day_s}{phase_s}"
        )
    if len(records) > len(tail):
        lines.append(f"  ... показаны последние {len(tail)} из {len(records)}")
    return "\n".join(lines)


def get_match_results_path() -> str:
    return MATCH_RESULTS_FILE
