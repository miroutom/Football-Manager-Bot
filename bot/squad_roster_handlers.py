"""Добавление / исключение игрока в составе клуба (лига → клуб → …)."""
from __future__ import annotations

import asyncio
import logging
import re
from html import escape as html_escape

from aiogram import F, Router
from aiogram.filters import StateFilter
from aiogram.fsm.context import FSMContext
from aiogram.types import (
    CallbackQuery,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    Message,
)

from bot.services import LEAGUE_LABELS, split_text_chunks, teams_ordered_for_goalscorers
from bot.states import SquadRosterEnter
from bot.roster_utils import ROSTER_PAGE_SIZE as _ROSTER_PAGE_SIZE, league_roster_tuples as _league_roster_tuples
from utils.roster_manual import (
    FREE_AGENT_TEAM,
    add_players_to_team_roster_bulk,
    apply_team_squad_declaration,
    build_squad_declaration_template_from_db,
    parse_roster_add_lines,
    parse_squad_declaration_text,
    remove_players_from_team_roster_bulk,
    rewrite_team_player_identity,
)
from utils.squad_limits import (
    SQUAD_BENCH,
    SQUAD_MAX,
    SQUAD_MIN_FOR_WIZARD,
    SQUAD_START,
    squad_limits_for_total,
)
from utils.transfer_input import normalize_display_name, normalize_position

logger = logging.getLogger(__name__)

squad_roster_router = Router()


async def _ensure_squad_roster_fsm(callback: CallbackQuery, state: FSMContext) -> bool:
    """Есть активная сессия «В состав / из состава» и сообщение для ответа."""
    cur = await state.get_state()
    if cur is None or not str(cur).startswith("SquadRosterEnter"):
        await callback.answer(
            "Сессия сброшена. Снова: «Изменить игроков» → «В состав / из состава».",
            show_alert=True,
        )
        return False
    if callback.message is None:
        await callback.answer("Сообщение недоступно.", show_alert=True)
        return False
    return True

_TEXT_NOT_CMD = F.text & ~F.text.startswith("/")

_RE_SQR_LG = re.compile(r"^sqr:lg:([a-z0-9_]+)$")
_RE_SQR_TM = re.compile(r"^sqr:tm:([a-z0-9_]+):(\d+)$")


def _league_title(code: str) -> str:
    return dict(LEAGUE_LABELS).get(code, code)


def _club_btn_label(text: str, max_chars: int = 40) -> str:
    text = (text or "").strip()
    if len(text) <= max_chars:
        return text
    return text[: max_chars - 1] + "…"


def _sqr_league_kb() -> InlineKeyboardMarkup:
    row: list[InlineKeyboardButton] = []
    rows: list[list[InlineKeyboardButton]] = []
    for code, label in LEAGUE_LABELS:
        row.append(InlineKeyboardButton(text=label, callback_data=f"sqr:lg:{code}"))
        if len(row) == 3:
            rows.append(row)
            row = []
    if row:
        rows.append(row)
    return InlineKeyboardMarkup(inline_keyboard=rows)


def _sqr_teams_kb(league_code: str) -> InlineKeyboardMarkup:
    teams = teams_ordered_for_goalscorers(league_code)
    rows: list[list[InlineKeyboardButton]] = []
    row: list[InlineKeyboardButton] = []
    for idx, team in enumerate(teams):
        row.append(
            InlineKeyboardButton(
                text=_club_btn_label(team),
                callback_data=f"sqr:tm:{league_code}:{idx}",
            )
        )
        if len(row) == 2:
            rows.append(row)
            row = []
    if row:
        rows.append(row)
    return InlineKeyboardMarkup(inline_keyboard=rows)


def _sqr_rm_multi_kb(
    candidates: list[tuple[str, str, int, str]],
    page: int,
    selected: set[int],
) -> InlineKeyboardMarkup:
    """Список игроков с галочками для массового удаления."""
    n = len(candidates)
    ps = _ROSTER_PAGE_SIZE
    total_pages = max(1, (n + ps - 1) // ps)
    page = max(0, min(int(page), total_pages - 1))
    chunk = candidates[page * ps : page * ps + ps]
    base = page * ps
    rows: list[list[InlineKeyboardButton]] = []
    for i, (nm, pos, ov, _dbt) in enumerate(chunk):
        gidx = base + i
        mark = "☑ " if gidx in selected else "☐ "
        label = f"{mark}{nm} · {pos} · {ov}"
        if len(label) > 60:
            label = label[:57] + "…"
        rows.append(
            [InlineKeyboardButton(text=label, callback_data=f"sqr:rm:tg:{gidx}")]
        )
    if total_pages > 1:
        nav: list[InlineKeyboardButton] = []
        if page > 0:
            nav.append(
                InlineKeyboardButton(
                    text=f"« {page + 1}/{total_pages}",
                    callback_data=f"sqr:rm:pg:{page - 1}",
                )
            )
        if page < total_pages - 1:
            nav.append(
                InlineKeyboardButton(
                    text=f"{page + 2}/{total_pages} »",
                    callback_data=f"sqr:rm:pg:{page + 1}",
                )
            )
        if nav:
            rows.append(nav)
    n_sel = len(selected)
    del_label = f"🗑 Удалить выбранных ({n_sel})" if n_sel else "🗑 Удалить выбранных"
    rows.append([InlineKeyboardButton(text=del_label, callback_data="sqr:rm:apply")])
    rows.append([InlineKeyboardButton(text="↩ Назад", callback_data="sqr:rm:back")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def _sqr_rm_multi_caption(team: str, page: int, total_pages: int, selected: set[int]) -> str:
    return (
        f"Клуб <b>{html_escape(team)}</b> — отметь игроков для <b>исключения</b> "
        f"(☑). Выбрано: <b>{len(selected)}</b>.\n"
        f"Стр. <b>{page + 1}</b>/<b>{total_pages}</b>."
    )


def _sqr_roster_kb(
    candidates: list[tuple[str, str, int, str]], page: int
) -> InlineKeyboardMarkup:
    n = len(candidates)
    ps = _ROSTER_PAGE_SIZE
    total_pages = max(1, (n + ps - 1) // ps)
    page = max(0, min(int(page), total_pages - 1))
    chunk = candidates[page * ps : page * ps + ps]
    base = page * ps
    rows: list[list[InlineKeyboardButton]] = []
    for i, (nm, pos, ov, _dbt) in enumerate(chunk):
        gidx = base + i
        label = f"{nm} · {pos} · {ov}"
        if len(label) > 60:
            label = label[:57] + "…"
        rows.append(
            [InlineKeyboardButton(text=label, callback_data=f"sqr:rp:{gidx}")]
        )
    if total_pages > 1:
        nav: list[InlineKeyboardButton] = []
        if page > 0:
            nav.append(
                InlineKeyboardButton(
                    text=f"« {page + 1}/{total_pages}",
                    callback_data=f"sqr:rpg:{page - 1}",
                )
            )
        if page < total_pages - 1:
            nav.append(
                InlineKeyboardButton(
                    text=f"{page + 2}/{total_pages} »",
                    callback_data=f"sqr:rpg:{page + 1}",
                )
            )
        if nav:
            rows.append(nav)
    return InlineKeyboardMarkup(inline_keyboard=rows)


def _sqr_choice_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text=f"🧩 Заявка кнопками (11/7/до {SQUAD_MAX})",
                    callback_data="sqr:do:wizard",
                ),
            ],
            [
                InlineKeyboardButton(
                    text="➕ Один игрок в состав", callback_data="sqr:do:add"
                ),
                InlineKeyboardButton(
                    text="➕ Несколько (строки)", callback_data="sqr:do:add_bulk"
                ),
            ],
            [
                InlineKeyboardButton(
                    text="➖ Исключить (галочки)", callback_data="sqr:do:rm"
                ),
            ],
        ]
    )


def _sqr_continue_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="➡ Выбрать следующий клуб",
                    callback_data="sqr:flow:next_team",
                )
            ],
            [
                InlineKeyboardButton(
                    text="🏆 Сменить лигу",
                    callback_data="sqr:flow:pick_lg",
                )
            ],
            [
                InlineKeyboardButton(
                    text="✅ Завершить",
                    callback_data="sqr:flow:finish",
                )
            ],
        ]
    )


def _sqr_status_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="▶ Старт (11)", callback_data="sqr:st:start"
                ),
                InlineKeyboardButton(text="Скамейка", callback_data="sqr:st:bench"),
            ],
            [
                InlineKeyboardButton(text="Резерв", callback_data="sqr:st:reserve"),
            ],
        ]
    )


_SQR_WZ_PAGE = 10
_SQR_WZ_LIMITS_DEFAULT: dict[str, int] = squad_limits_for_total(SQUAD_MAX)
_SQR_WZ_TITLES: dict[str, str] = {
    "start": "Стартовый состав",
    "bench": "Скамейка",
    "reserve": "Резерв",
}


def _team_roster_records(team: str) -> list[dict[str, object]]:
    """Текущий состав клуба в нац. БД с nation/status."""
    from utils.player_transfer import _filter_team
    from utils.utils import session_league

    out: list[dict[str, object]] = []
    for Cls in (
        __import__("data.forward", fromlist=["Forward"]).Forward,
        __import__("data.midfielder", fromlist=["Midfielder"]).Midfielder,
        __import__("data.defender", fromlist=["Defender"]).Defender,
        __import__("data.goalkeeper", fromlist=["Goalkeeper"]).Goalkeeper,
    ):
        for r in session_league.query(Cls).filter(_filter_team(Cls, team)).all():
            nm = (getattr(r, "name", None) or "").strip()
            pos = (getattr(r, "position", None) or "").strip().upper()
            if not nm or not pos:
                continue
            out.append(
                {
                    "name": nm,
                    "position": pos,
                    "overall": int(getattr(r, "overall", 0) or 0),
                    "nation": (getattr(r, "nation", None) or "").strip() or None,
                    "status": (getattr(r, "status", None) or "bench").strip().lower(),
                }
            )
    out.sort(key=lambda x: str(x["name"]).casefold())
    return out


def _wz_sets_from_state(data: dict) -> tuple[set[int], set[int], set[int]]:
    st = {int(x) for x in (data.get("sqr_wz_start") or [])}
    bn = {int(x) for x in (data.get("sqr_wz_bench") or [])}
    rs = {int(x) for x in (data.get("sqr_wz_reserve") or [])}
    return st, bn, rs


def _wz_prefill_from_status(
    players: list[dict[str, object]], limits: dict[str, int]
) -> tuple[list[int], list[int], list[int]]:
    """Предзаполнить wizard текущими status из БД."""
    need_start = int(limits.get("start", 11))
    need_bench = int(limits.get("bench", 7))
    need_reserve = int(limits.get("reserve", 5))

    start_idx: list[int] = []
    bench_idx: list[int] = []
    reserve_idx: list[int] = []
    for i, p in enumerate(players):
        st = str(p.get("status") or "").strip().lower()
        if st == "start":
            start_idx.append(i)
        elif st == "reserve":
            reserve_idx.append(i)
        else:
            # bench + любые невалидные статусы трактуем как скамейку
            bench_idx.append(i)

    sel_start = start_idx[:need_start]
    used = set(sel_start)
    sel_bench = [i for i in bench_idx if i not in used][:need_bench]
    used.update(sel_bench)
    sel_reserve = [i for i in reserve_idx if i not in used][:need_reserve]
    return sel_start, sel_bench, sel_reserve


def _wz_render_text(data: dict, *, phase: str, page: int, total_pages: int) -> str:
    title = _SQR_WZ_TITLES.get(phase, phase)
    limits = dict(data.get("sqr_wz_limits") or _SQR_WZ_LIMITS_DEFAULT)
    limit = int(limits.get(phase, 0))
    st, bn, rs = _wz_sets_from_state(data)
    cur_n = len({"start": st, "bench": bn, "reserve": rs}[phase])
    team = html_escape((data.get("sqr_team") or "").strip())
    total_players = int(data.get("sqr_wz_total_players") or 0)
    return (
        f"<b>{team}</b>\n"
        f"В составе: <b>{total_players}</b> игроков.\n"
        f"Шаг 1: старт {limits.get('start', 11)} → "
        f"шаг 2: скамейка {limits.get('bench', 7)} → "
        f"шаг 3: резерв {limits.get('reserve', 5)}.\n\n"
        f"<b>{title}</b>: выбрано <b>{cur_n}/{limit}</b>.\n"
        f"Страница <b>{page + 1}</b>/<b>{total_pages}</b>.\n"
        "✅ в текущем шаге · 🟦 старт · 🟨 скамейка · 🟥 резерв.\n"
        "Нажимай по игроку, чтобы добавить/убрать; затем «Готово»."
    )


def _wz_pick_kb(data: dict, *, phase: str, page: int) -> tuple[InlineKeyboardMarkup, int]:
    players: list[dict] = list(data.get("sqr_wz_players") or [])
    st, bn, rs = _wz_sets_from_state(data)
    current = {"start": st, "bench": bn, "reserve": rs}[phase]
    all_selected = st | bn | rs
    n = len(players)
    total_pages = max(1, (n + _SQR_WZ_PAGE - 1) // _SQR_WZ_PAGE)
    page = max(0, min(int(page), total_pages - 1))
    chunk = list(range(len(players)))[page * _SQR_WZ_PAGE : page * _SQR_WZ_PAGE + _SQR_WZ_PAGE]

    rows: list[list[InlineKeyboardButton]] = []
    for gi in chunk:
        p = players[gi]
        if gi in current:
            mark = "✅ "
        elif gi in st:
            mark = "🟦 "
        elif gi in bn:
            mark = "🟨 "
        elif gi in rs:
            mark = "🟥 "
        else:
            mark = ""
        label = f"{mark}{p['name']} · {p['position']} · {p['overall']}"
        if len(label) > 60:
            label = label[:57] + "…"
        rows.append([InlineKeyboardButton(text=label, callback_data=f"sqr:wz:tg:{gi}")])

    nav: list[InlineKeyboardButton] = []
    if page > 0:
        nav.append(InlineKeyboardButton(text="←", callback_data=f"sqr:wz:pg:{page - 1}"))
    if page < total_pages - 1:
        nav.append(InlineKeyboardButton(text="→", callback_data=f"sqr:wz:pg:{page + 1}"))
    if nav:
        rows.append(nav)
    limits = dict(data.get("sqr_wz_limits") or _SQR_WZ_LIMITS_DEFAULT)
    if phase == "reserve" and int(limits.get("reserve", 0)) > 0:
        rows.append(
            [
                InlineKeyboardButton(
                    text="⚡ Автозаполнить резерв",
                    callback_data="sqr:wz:auto_res",
                )
            ]
        )
    rows.append([InlineKeyboardButton(text="✅ Готово", callback_data="sqr:wz:done")])
    return InlineKeyboardMarkup(inline_keyboard=rows), total_pages


def _wz_edit_kb(data: dict, *, page: int) -> tuple[InlineKeyboardMarkup, int]:
    selected: list[dict] = list(data.get("sqr_wz_selected") or [])
    n = len(selected)
    total_pages = max(1, (n + _SQR_WZ_PAGE - 1) // _SQR_WZ_PAGE)
    page = max(0, min(int(page), total_pages - 1))
    chunk = selected[page * _SQR_WZ_PAGE : page * _SQR_WZ_PAGE + _SQR_WZ_PAGE]
    base = page * _SQR_WZ_PAGE
    rows: list[list[InlineKeyboardButton]] = []
    for i, p in enumerate(chunk):
        gi = base + i
        label = f"{p['name']} · {p['position']} · {p['overall']} · {p['status']}"
        if len(label) > 60:
            label = label[:57] + "…"
        rows.append([InlineKeyboardButton(text=label, callback_data=f"sqr:wz:ep:{gi}")])
    nav: list[InlineKeyboardButton] = []
    if page > 0:
        nav.append(InlineKeyboardButton(text="←", callback_data=f"sqr:wz:epg:{page - 1}"))
    if page < total_pages - 1:
        nav.append(InlineKeyboardButton(text="→", callback_data=f"sqr:wz:epg:{page + 1}"))
    if nav:
        rows.append(nav)
    rows.append([InlineKeyboardButton(text="💾 Сохранить", callback_data="sqr:wz:save")])
    return InlineKeyboardMarkup(inline_keyboard=rows), total_pages


def _wz_edit_intro_html(data: dict, *, page: int, total_pages: int) -> str:
    team = html_escape((data.get("sqr_team") or "").strip())
    return (
        f"<b>{team}</b>\n"
        "Заявка применена. Можно точечно править игроков.\n"
        "Нажми на игрока, я пришлю строку-шаблон: <code>Имя ПОЗ OVR Нация</code>.\n"
        f"Страница <b>{page + 1}</b>/<b>{total_pages}</b>.\n"
        "Кнопка «Сохранить» доступна всегда."
    )


def _parse_player_line_for_edit(
    line: str,
) -> tuple[tuple[str, str, int | None, str | None] | None, str | None]:
    text = (line or "").strip()
    if not text:
        return None, "Пустая строка."
    entries, errs = parse_squad_declaration_text("==== start ===\n" + text)
    if errs:
        return None, errs[0]
    if not entries:
        return None, "Не удалось разобрать строку."
    nm, pos, _st, ovr, nat = entries[0]
    return (nm, pos, ovr, nat), None


async def _wz_apply_and_open_edit(
    callback: CallbackQuery,
    state: FSMContext,
    *,
    team: str,
    players: list[dict],
    st: set[int],
    bn: set[int],
    rs: set[int],
) -> None:
    entries: list[tuple[str, str, str, int | None, str | None]] = []
    selected: list[dict[str, object]] = []
    for idx in sorted(st):
        p = players[idx]
        entries.append((str(p["name"]), str(p["position"]), "start", int(p["overall"]), p.get("nation")))
        selected.append({**p, "status": "start"})
    for idx in sorted(bn):
        p = players[idx]
        entries.append((str(p["name"]), str(p["position"]), "bench", int(p["overall"]), p.get("nation")))
        selected.append({**p, "status": "bench"})
    for idx in sorted(rs):
        p = players[idx]
        entries.append((str(p["name"]), str(p["position"]), "reserve", int(p["overall"]), p.get("nation")))
        selected.append({**p, "status": "reserve"})

    await callback.answer("Применяю заявку...")
    try:
        r = await asyncio.to_thread(apply_team_squad_declaration, team, entries)
    except Exception as e:
        logger.exception("wizard apply_team_squad_declaration")
        if callback.message:
            await callback.message.answer(f"Ошибка применения заявки: {e}")
        return
    await state.update_data(sqr_wz_selected=selected, sqr_wz_edit_page=0)
    await state.set_state(SquadRosterEnter.wz_edit_pick)
    data3 = await state.get_data()
    kb, total_pages = _wz_edit_kb(data3, page=0)
    det = r.get("released", 0)
    if callback.message:
        await callback.message.edit_text(
            _wz_edit_intro_html(data3, page=0, total_pages=total_pages)
            + f"\n\nСнято в СА: <b>{det}</b>.",
            parse_mode="HTML",
            reply_markup=kb,
        )

@squad_roster_router.callback_query(F.data == "menu:squad_roster")
async def cb_menu_squad_roster(callback: CallbackQuery, state: FSMContext) -> None:
    await callback.answer()
    if callback.message is None:
        return
    await state.clear()
    await state.set_state(SquadRosterEnter.pick_lg)
    await callback.message.answer(
        "👥 <b>В состав / из состава</b>\n\n"
        "Выбери лигу и клуб.\n"
        f"<b>Заявка кнопками:</b> 11 старт + 7 скамейка + резерв (до <b>{SQUAD_MAX}</b> в клубе), "
        "затем точечная правка.\n"
        "<b>Добавление:</b> один игрок или <b>несколько строк</b> "
        "(<code>имя позиция [overall] [нация]</code> — в нац. БД и ЛЧ, если клуб в пуле).\n"
        "<b>Исключение:</b> галочками, затем «Удалить выбранных».\n"
        f"При статистике клуб в БД станет «{FREE_AGENT_TEAM}».\n"
        "/cancel — отмена.",
        parse_mode="HTML",
        reply_markup=_sqr_league_kb(),
    )


@squad_roster_router.callback_query(F.data.regexp(_RE_SQR_LG))
async def cb_sqr_league(callback: CallbackQuery, state: FSMContext) -> None:
    m = _RE_SQR_LG.match(callback.data or "")
    if not m:
        await callback.answer()
        return
    if not await _ensure_squad_roster_fsm(callback, state):
        return
    code = m.group(1)
    await callback.answer()
    await state.update_data(sqr_lg=code)
    await state.set_state(SquadRosterEnter.pick_team)
    await callback.message.answer(
        f"{_league_title(code)} — выберите клуб:",
        reply_markup=_sqr_teams_kb(code),
    )


@squad_roster_router.callback_query(F.data.regexp(_RE_SQR_TM))
async def cb_sqr_team(callback: CallbackQuery, state: FSMContext) -> None:
    m = _RE_SQR_TM.match(callback.data or "")
    if not m:
        await callback.answer()
        return
    if not await _ensure_squad_roster_fsm(callback, state):
        return
    code, idx_s = m.group(1), m.group(2)
    try:
        idx = int(idx_s)
    except ValueError:
        await callback.answer()
        return
    await callback.answer()
    try:
        teams = teams_ordered_for_goalscorers(code)
        team = teams[idx]
    except (IndexError, Exception) as e:
        await callback.message.answer(f"Клуб: ошибка: {e}")
        return
    rows = _league_roster_tuples(team)
    canonical = (rows[0][3] or team) if rows else team
    n_players = len(rows)
    await state.update_data(sqr_team=canonical, sqr_lg=code)
    await state.set_state(SquadRosterEnter.pick_choice)
    await callback.message.answer(
        f"<b>{_league_title(code)}</b> · <b>{canonical}</b>\n"
        f"Игроков в составе: <b>{n_players}</b>\n\nЧто сделать?",
        parse_mode="HTML",
        reply_markup=_sqr_choice_kb(),
    )


@squad_roster_router.callback_query(F.data == "sqr:flow:next_team")
async def cb_sqr_flow_next_team(callback: CallbackQuery, state: FSMContext) -> None:
    if not await _ensure_squad_roster_fsm(callback, state):
        return
    await callback.answer()
    data = await state.get_data()
    code = str(data.get("sqr_lg") or "").strip()
    if not code:
        await state.set_state(SquadRosterEnter.pick_lg)
        await callback.message.answer(
            "Лига не выбрана. Выбери лигу:",
            reply_markup=_sqr_league_kb(),
        )
        return
    await state.set_state(SquadRosterEnter.pick_team)
    await callback.message.answer(
        f"{_league_title(code)} — выберите клуб:",
        reply_markup=_sqr_teams_kb(code),
    )


@squad_roster_router.callback_query(F.data == "sqr:flow:pick_lg")
async def cb_sqr_flow_pick_lg(callback: CallbackQuery, state: FSMContext) -> None:
    if not await _ensure_squad_roster_fsm(callback, state):
        return
    await callback.answer()
    await state.set_state(SquadRosterEnter.pick_lg)
    await callback.message.answer("Выбери лигу:", reply_markup=_sqr_league_kb())


@squad_roster_router.callback_query(F.data == "sqr:flow:finish")
async def cb_sqr_flow_finish(callback: CallbackQuery, state: FSMContext) -> None:
    await callback.answer()
    await state.clear()
    if callback.message:
        await callback.message.answer("Сессия завершена.")


@squad_roster_router.callback_query(SquadRosterEnter.pick_choice, F.data == "sqr:do:wizard")
async def cb_sqr_wizard_start(callback: CallbackQuery, state: FSMContext) -> None:
    await callback.answer()
    if not callback.message:
        return
    data = await state.get_data()
    team = (data.get("sqr_team") or "").strip()
    if not team:
        await callback.message.answer("Нет клуба в сессии. Начни с меню.")
        return
    players = _team_roster_records(team)
    total_players = len(players)
    if total_players < SQUAD_MIN_FOR_WIZARD:
        await callback.message.answer(
            f"В составе {total_players} игроков, а нужно минимум {SQUAD_MIN_FOR_WIZARD} "
            f"({SQUAD_START} старт + {SQUAD_BENCH} скамейка). Добавь игроков и повтори."
        )
        return
    if total_players > SQUAD_MAX:
        await callback.message.answer(
            f"В составе {total_players} игроков — максимум заявки <b>{SQUAD_MAX}</b>.",
            parse_mode="HTML",
        )
        return
    limits = squad_limits_for_total(total_players)
    serial = [dict(p) for p in players]
    wz_start, wz_bench, wz_reserve = _wz_prefill_from_status(serial, limits)
    await state.update_data(
        sqr_wz_players=serial,
        sqr_wz_total_players=total_players,
        sqr_wz_limits=limits,
        sqr_wz_start=wz_start,
        sqr_wz_bench=wz_bench,
        sqr_wz_reserve=wz_reserve,
        sqr_wz_page=0,
    )
    await state.set_state(SquadRosterEnter.wz_pick_start)
    data2 = await state.get_data()
    kb, total_pages = _wz_pick_kb(data2, phase="start", page=0)
    await callback.message.answer(
        _wz_render_text(data2, phase="start", page=0, total_pages=total_pages),
        parse_mode="HTML",
        reply_markup=kb,
    )


@squad_roster_router.callback_query(
    StateFilter(
        SquadRosterEnter.wz_pick_start,
        SquadRosterEnter.wz_pick_bench,
        SquadRosterEnter.wz_pick_reserve,
    ),
    F.data.startswith("sqr:wz:pg:"),
)
async def cb_sqr_wizard_page(callback: CallbackQuery, state: FSMContext) -> None:
    if not callback.message or not callback.data:
        await callback.answer()
        return
    try:
        page = int((callback.data or "").rsplit(":", 1)[-1])
    except ValueError:
        await callback.answer()
        return
    cur = await state.get_state()
    phase = "start"
    if cur == SquadRosterEnter.wz_pick_bench.state:
        phase = "bench"
    elif cur == SquadRosterEnter.wz_pick_reserve.state:
        phase = "reserve"
    await state.update_data(sqr_wz_page=page)
    data = await state.get_data()
    kb, total_pages = _wz_pick_kb(data, phase=phase, page=page)
    text = _wz_render_text(
        data,
        phase=phase,
        page=max(0, min(page, total_pages - 1)),
        total_pages=total_pages,
    )
    try:
        await callback.message.edit_text(text, parse_mode="HTML", reply_markup=kb)
    except Exception:
        await callback.message.edit_reply_markup(reply_markup=kb)
    await callback.answer()


@squad_roster_router.callback_query(
    SquadRosterEnter.wz_pick_reserve, F.data == "sqr:wz:auto_res"
)
async def cb_sqr_wizard_auto_reserve(callback: CallbackQuery, state: FSMContext) -> None:
    if not callback.message:
        await callback.answer()
        return
    data = await state.get_data()
    players: list[dict] = list(data.get("sqr_wz_players") or [])
    st, bn, rs = _wz_sets_from_state(data)
    limits = dict(data.get("sqr_wz_limits") or _SQR_WZ_LIMITS_DEFAULT)
    need_reserve = int(limits.get("reserve", 0))
    current_all = st | bn
    remaining = [i for i in range(len(players)) if i not in current_all]
    if len(remaining) < need_reserve:
        await callback.answer(
            f"Недостаточно игроков для резерва: нужно {need_reserve}, осталось {len(remaining)}.",
            show_alert=True,
        )
        return
    rs_new = set(remaining[:need_reserve])
    await state.update_data(sqr_wz_reserve=sorted(rs_new))
    data2 = await state.get_data()
    kb, total_pages = _wz_pick_kb(data2, phase="reserve", page=0)
    text = _wz_render_text(data2, phase="reserve", page=0, total_pages=total_pages)
    await callback.message.edit_text(text, parse_mode="HTML", reply_markup=kb)
    await callback.answer("Резерв заполнен автоматически.")


@squad_roster_router.callback_query(
    StateFilter(
        SquadRosterEnter.wz_pick_start,
        SquadRosterEnter.wz_pick_bench,
        SquadRosterEnter.wz_pick_reserve,
    ),
    F.data.startswith("sqr:wz:tg:"),
)
async def cb_sqr_wizard_toggle(callback: CallbackQuery, state: FSMContext) -> None:
    if not callback.message or not callback.data:
        await callback.answer()
        return
    try:
        idx = int((callback.data or "").rsplit(":", 1)[-1])
    except ValueError:
        await callback.answer()
        return
    cur = await state.get_state()
    phase = "start"
    if cur == SquadRosterEnter.wz_pick_bench.state:
        phase = "bench"
    elif cur == SquadRosterEnter.wz_pick_reserve.state:
        phase = "reserve"

    data = await state.get_data()
    players: list[dict] = list(data.get("sqr_wz_players") or [])
    if idx < 0 or idx >= len(players):
        await callback.answer("Неверный игрок.", show_alert=True)
        return
    st, bn, rs = _wz_sets_from_state(data)
    limits = dict(data.get("sqr_wz_limits") or _SQR_WZ_LIMITS_DEFAULT)
    current = {"start": st, "bench": bn, "reserve": rs}[phase]
    if idx in current:
        current.remove(idx)
    else:
        limit = int(limits.get(phase, 0))
        if len(current) >= limit:
            await callback.answer(f"Лимит: {limit}.", show_alert=True)
            return
        st.discard(idx)
        bn.discard(idx)
        rs.discard(idx)
        current.add(idx)
    await state.update_data(
        sqr_wz_start=sorted(st),
        sqr_wz_bench=sorted(bn),
        sqr_wz_reserve=sorted(rs),
    )
    page = int(data.get("sqr_wz_page") or 0)
    data2 = await state.get_data()
    kb, total_pages = _wz_pick_kb(data2, phase=phase, page=page)
    text = _wz_render_text(
        data2,
        phase=phase,
        page=max(0, min(page, total_pages - 1)),
        total_pages=total_pages,
    )
    try:
        await callback.message.edit_text(text, parse_mode="HTML", reply_markup=kb)
    except Exception:
        await callback.message.edit_reply_markup(reply_markup=kb)
    await callback.answer()


@squad_roster_router.callback_query(
    StateFilter(
        SquadRosterEnter.wz_pick_start,
        SquadRosterEnter.wz_pick_bench,
        SquadRosterEnter.wz_pick_reserve,
    ),
    F.data == "sqr:wz:done",
)
async def cb_sqr_wizard_done(callback: CallbackQuery, state: FSMContext) -> None:
    if not callback.message:
        await callback.answer()
        return
    data = await state.get_data()
    players: list[dict] = list(data.get("sqr_wz_players") or [])
    st, bn, rs = _wz_sets_from_state(data)
    limits = dict(data.get("sqr_wz_limits") or _SQR_WZ_LIMITS_DEFAULT)
    need_start = int(limits.get("start", 11))
    need_bench = int(limits.get("bench", 7))
    need_reserve = int(limits.get("reserve", 5))
    cur = await state.get_state()
    if cur == SquadRosterEnter.wz_pick_start.state:
        if len(st) != need_start:
            await callback.answer(
                f"Нужно выбрать ровно {need_start} игроков в старт.", show_alert=True
            )
            return
        await state.set_state(SquadRosterEnter.wz_pick_bench)
        await state.update_data(sqr_wz_page=0)
        data2 = await state.get_data()
        kb, total_pages = _wz_pick_kb(data2, phase="bench", page=0)
        await callback.message.edit_text(
            _wz_render_text(data2, phase="bench", page=0, total_pages=total_pages),
            parse_mode="HTML",
            reply_markup=kb,
        )
        await callback.answer()
        return
    if cur == SquadRosterEnter.wz_pick_bench.state:
        if len(bn) != need_bench:
            await callback.answer(
                f"Нужно выбрать ровно {need_bench} игроков на скамейку.",
                show_alert=True,
            )
            return
        if need_reserve <= 0:
            team = (data.get("sqr_team") or "").strip()
            await _wz_apply_and_open_edit(
                callback,
                state,
                team=team,
                players=players,
                st=st,
                bn=bn,
                rs=set(),
            )
            return
        await state.set_state(SquadRosterEnter.wz_pick_reserve)
        await state.update_data(sqr_wz_page=0)
        data2 = await state.get_data()
        kb, total_pages = _wz_pick_kb(data2, phase="reserve", page=0)
        await callback.message.edit_text(
            _wz_render_text(data2, phase="reserve", page=0, total_pages=total_pages),
            parse_mode="HTML",
            reply_markup=kb,
        )
        await callback.answer()
        return
    if len(rs) != need_reserve:
        await callback.answer(
            f"Нужно выбрать ровно {need_reserve} игроков в резерв.", show_alert=True
        )
        return
    team = (data.get("sqr_team") or "").strip()
    await _wz_apply_and_open_edit(
        callback,
        state,
        team=team,
        players=players,
        st=st,
        bn=bn,
        rs=rs,
    )


@squad_roster_router.callback_query(SquadRosterEnter.wz_edit_pick, F.data.startswith("sqr:wz:epg:"))
async def cb_sqr_wizard_edit_page(callback: CallbackQuery, state: FSMContext) -> None:
    if not callback.message or not callback.data:
        await callback.answer()
        return
    try:
        page = int((callback.data or "").rsplit(":", 1)[-1])
    except ValueError:
        await callback.answer()
        return
    await state.update_data(sqr_wz_edit_page=page)
    data = await state.get_data()
    kb, total_pages = _wz_edit_kb(data, page=page)
    text = _wz_edit_intro_html(
        data, page=max(0, min(page, total_pages - 1)), total_pages=total_pages
    )
    try:
        await callback.message.edit_text(text, parse_mode="HTML", reply_markup=kb)
    except Exception:
        await callback.message.edit_reply_markup(reply_markup=kb)
    await callback.answer()


@squad_roster_router.callback_query(SquadRosterEnter.wz_edit_pick, F.data.startswith("sqr:wz:ep:"))
async def cb_sqr_wizard_edit_pick(callback: CallbackQuery, state: FSMContext) -> None:
    if not callback.message or not callback.data:
        await callback.answer()
        return
    try:
        idx = int((callback.data or "").rsplit(":", 1)[-1])
    except ValueError:
        await callback.answer()
        return
    data = await state.get_data()
    selected: list[dict] = list(data.get("sqr_wz_selected") or [])
    if idx < 0 or idx >= len(selected):
        await callback.answer("Неверный выбор.", show_alert=True)
        return
    p = selected[idx]
    nat = str(p.get("nation") or "—")
    tpl = f"{p['name']} {p['position']} {p['overall']} {nat}"
    await state.update_data(sqr_wz_edit_idx=idx)
    await state.set_state(SquadRosterEnter.wz_edit_wait_line)
    kb = InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="↩ К списку", callback_data="sqr:wz:eback")],
            [InlineKeyboardButton(text="💾 Сохранить", callback_data="sqr:wz:save")],
        ]
    )
    await callback.message.edit_text(
        "Отправь строку в формате:\n"
        "<code>Имя ПОЗ OVR Нация</code>\n\n"
        "Шаблон:\n"
        f"<pre>{html_escape(tpl)}</pre>",
        parse_mode="HTML",
        reply_markup=kb,
    )
    await callback.answer()


@squad_roster_router.callback_query(
    StateFilter(SquadRosterEnter.wz_edit_pick, SquadRosterEnter.wz_edit_wait_line),
    F.data == "sqr:wz:save",
)
async def cb_sqr_wizard_save(callback: CallbackQuery, state: FSMContext) -> None:
    await callback.answer()
    await state.set_state(SquadRosterEnter.pick_team)
    if callback.message:
        await callback.message.answer(
            "✅ Состав сохранён.\nВыбери, что дальше:",
            reply_markup=_sqr_continue_kb(),
        )


@squad_roster_router.callback_query(SquadRosterEnter.wz_edit_wait_line, F.data == "sqr:wz:eback")
async def cb_sqr_wizard_edit_back(callback: CallbackQuery, state: FSMContext) -> None:
    await callback.answer()
    if not callback.message:
        return
    await state.set_state(SquadRosterEnter.wz_edit_pick)
    data = await state.get_data()
    page = int(data.get("sqr_wz_edit_page") or 0)
    kb, total_pages = _wz_edit_kb(data, page=page)
    await callback.message.edit_text(
        _wz_edit_intro_html(
            data, page=max(0, min(page, total_pages - 1)), total_pages=total_pages
        ),
        parse_mode="HTML",
        reply_markup=kb,
    )


@squad_roster_router.message(SquadRosterEnter.wz_edit_wait_line, _TEXT_NOT_CMD)
async def on_sqr_wizard_edit_line(message: Message, state: FSMContext) -> None:
    data = await state.get_data()
    team = (data.get("sqr_team") or "").strip()
    raw_idx = data.get("sqr_wz_edit_idx")
    try:
        idx = int(raw_idx) if raw_idx is not None else -1
    except (TypeError, ValueError):
        idx = -1
    selected: list[dict] = list(data.get("sqr_wz_selected") or [])
    if idx < 0 or idx >= len(selected) or not team:
        await state.clear()
        await message.answer("Сессия сброшена. Начни заново из меню.")
        return
    parsed, err = _parse_player_line_for_edit(message.text or "")
    if err:
        await message.answer(f"Ошибка строки: {err}")
        return
    assert parsed is not None
    nm_new, pos_new, ovr_new, nat_new = parsed
    p = selected[idx]
    old_nm = str(p["name"])
    old_pos = str(p["position"])
    st = str(p.get("status") or "bench")
    try:
        r = await asyncio.to_thread(
            rewrite_team_player_identity,
            team,
            old_nm,
            old_pos,
            new_name=nm_new,
            new_position=pos_new,
            overall=ovr_new,
            nation=nat_new,
            status=st,
        )
    except Exception as e:
        logger.exception("rewrite_team_player_identity")
        await message.answer(f"Не удалось обновить игрока: {e}")
        return
    selected[idx] = {
        "name": r["new"][0],
        "position": r["new"][1],
        "overall": r["overall"],
        "nation": r.get("nation"),
        "status": r["status"],
    }
    await state.update_data(sqr_wz_selected=selected)
    await state.set_state(SquadRosterEnter.wz_edit_pick)
    data2 = await state.get_data()
    page = int(data2.get("sqr_wz_edit_page") or 0)
    kb, total_pages = _wz_edit_kb(data2, page=page)
    await message.answer(
        "✅ Игрок обновлён.\n"
        + _wz_edit_intro_html(
            data2, page=max(0, min(page, total_pages - 1)), total_pages=total_pages
        ),
        parse_mode="HTML",
        reply_markup=kb,
    )


@squad_roster_router.callback_query(
    SquadRosterEnter.pick_choice, F.data == "sqr:do:set_squad"
)
async def cb_sqr_set_squad(callback: CallbackQuery, state: FSMContext) -> None:
    await callback.answer()
    if not callback.message:
        return
    data = await state.get_data()
    team = (data.get("sqr_team") or "").strip()
    if not team:
        await callback.message.answer("Нет клуба в сессии. Начни с меню.")
        return
    try:
        template_blob = await asyncio.to_thread(
            build_squad_declaration_template_from_db, team
        )
    except Exception as e:
        logger.exception("build_squad_declaration_template_from_db")
        await callback.message.answer(f"Не удалось собрать состав из БД: {e}")
        return

    await state.set_state(SquadRosterEnter.wait_paste_squad)
    more_parts = ""
    chunks = split_text_chunks(template_blob, 3500)
    if len(chunks) > 1:
        more_parts = (
            f"Заявка на <b>{len(chunks)}</b> сообщений — скопируй все части подряд "
            "в редактор, поправь и пришли <b>одним</b> сообщением.\n\n"
        )
    await callback.message.answer(
        "Ниже — <b>черновик заявки</b> из нац. БД (секции "
        "<code>==== start ===</code>, <code>=== bench ===</code>, "
        "<code>=== reserve ===</code>). После отправки одним сообщением заявка "
        "применится и к нац. базе, и к ЛЧ (если клуб в актуальном пуле участников).\n"
        "Формат строки: <code>имя позиция overall нация</code> "
        "(нацию/overall можно опустить для игроков из common).\n\n"
        + more_parts
        + "Кого <b>нет</b> в тексте при отправке — уйдут в свободные агенты.\n\n"
        "<b>По-прежнему можно</b> без секций: последнее слово "
        "<code>start</code>/<code>bench</code>/<code>reserve</code>, "
        "или строки через <code>|</code>.\n"
        "/cancel — отмена.",
        parse_mode="HTML",
    )
    for j, chunk in enumerate(chunks):
        prefix = f"📋 {j + 1}/{len(chunks)}\n" if len(chunks) > 1 else ""
        await callback.message.answer(
            f"<pre>{html_escape(prefix + chunk)}</pre>",
            parse_mode="HTML",
        )


@squad_roster_router.message(SquadRosterEnter.wait_paste_squad, _TEXT_NOT_CMD)
async def on_sqr_paste_squad(message: Message, state: FSMContext) -> None:
    data = await state.get_data()
    team = (data.get("sqr_team") or "").strip()
    if not team:
        await state.clear()
        await message.answer("Сессия сброшена. Начни с меню.")
        return
    entries, p_errors = parse_squad_declaration_text(message.text or "")
    if p_errors:
        await message.answer(
            "Ошибки разбора:\n" + "\n".join(p_errors[:30])
            + ("\n…" if len(p_errors) > 30 else ""),
            parse_mode="HTML",
        )
        return
    if not entries:
        await message.answer("Нет ни одной строки заявки (пусто или только комментарии).")
        return
    try:
        r = await asyncio.to_thread(apply_team_squad_declaration, team, entries)
    except Exception as e:
        logger.exception("apply_team_squad_declaration")
        await message.answer(f"Ошибка применения: {e}")
        return
    await state.set_state(SquadRosterEnter.pick_team)
    det = r.get("released_detail") or []
    det_tail = "\n".join(det[:15]) if det else ""
    more = f"\n… ещё {len(det) - 15}" if len(det) > 15 else ""
    cl_note = ""
    if r.get("cl_pool"):
        cl_note = "\nЛЧ: заявка синхронизирована (<code>champions_league_new.db</code>)."
    await message.answer(
        f"✅ Клуб <b>{r['team']}</b>\n"
        f"В заявке: <b>{r['declared']}</b> игроков.\n"
        f"Снято в СА: <b>{r['released']}</b>.\n"
        + cl_note
        + (f"<pre>{det_tail}{more}</pre>" if det_tail else "")
        + "\n<code>common.db</code> / накопительные БД обновлены по режиму сезона.",
        parse_mode="HTML",
        reply_markup=_sqr_continue_kb(),
    )


def _sqr_rm_selected_set(data: dict) -> set[int]:
    return {int(x) for x in (data.get("sqr_rm_selected") or [])}


@squad_roster_router.callback_query(SquadRosterEnter.pick_choice, F.data == "sqr:do:rm")
async def cb_sqr_choice_remove(callback: CallbackQuery, state: FSMContext) -> None:
    await callback.answer()
    if not callback.message:
        return
    data = await state.get_data()
    team = (data.get("sqr_team") or "").strip()
    rows = _league_roster_tuples(team)
    if not rows:
        await callback.message.answer("Состав пуст.")
        return
    serial = [list(x) for x in rows]
    await state.update_data(sqr_rm_candidates=serial, sqr_rm_page=0, sqr_rm_selected=[])
    await state.set_state(SquadRosterEnter.pick_rm)
    cands = [tuple(x) for x in serial]
    ps = _ROSTER_PAGE_SIZE
    total_pages = max(1, (len(cands) + ps - 1) // ps)
    await callback.message.answer(
        _sqr_rm_multi_caption(team, 0, total_pages, set()),
        parse_mode="HTML",
        reply_markup=_sqr_rm_multi_kb(cands, 0, set()),
    )


@squad_roster_router.callback_query(SquadRosterEnter.pick_rm, F.data == "sqr:rm:back")
async def cb_sqr_rm_back(callback: CallbackQuery, state: FSMContext) -> None:
    await callback.answer()
    if not callback.message:
        return
    data = await state.get_data()
    team = (data.get("sqr_team") or "").strip()
    n_players = len(_team_roster_records(team)) if team else 0
    await state.set_state(SquadRosterEnter.pick_choice)
    await callback.message.answer(
        f"Клуб <b>{html_escape(team)}</b> · игроков: <b>{n_players}</b>.\nЧто сделать?",
        parse_mode="HTML",
        reply_markup=_sqr_choice_kb(),
    )


@squad_roster_router.callback_query(SquadRosterEnter.pick_rm, F.data.startswith("sqr:rm:pg:"))
async def cb_sqr_rm_page(callback: CallbackQuery, state: FSMContext) -> None:
    if not callback.message or not callback.data:
        await callback.answer()
        return
    try:
        page = int((callback.data or "").rsplit(":", 1)[-1])
    except ValueError:
        await callback.answer()
        return
    data = await state.get_data()
    raw = data.get("sqr_rm_candidates") or []
    cands = [tuple(x) for x in raw]
    if not cands:
        await callback.answer("Сессия устарела.", show_alert=True)
        return
    selected = _sqr_rm_selected_set(data)
    ps = _ROSTER_PAGE_SIZE
    total_pages = max(1, (len(cands) + ps - 1) // ps)
    page = max(0, min(page, total_pages - 1))
    team = (data.get("sqr_team") or "").strip()
    await state.update_data(sqr_rm_page=page)
    kb = _sqr_rm_multi_kb(cands, page, selected)
    caption = _sqr_rm_multi_caption(team, page, total_pages, selected)
    try:
        await callback.message.edit_text(caption, parse_mode="HTML", reply_markup=kb)
    except Exception:
        try:
            await callback.message.edit_reply_markup(reply_markup=kb)
        except Exception:
            await callback.message.answer(caption, parse_mode="HTML", reply_markup=kb)
    await callback.answer()


@squad_roster_router.callback_query(SquadRosterEnter.pick_rm, F.data.startswith("sqr:rm:tg:"))
async def cb_sqr_rm_toggle(callback: CallbackQuery, state: FSMContext) -> None:
    if not callback.message or not callback.data:
        await callback.answer()
        return
    try:
        idx = int((callback.data or "").rsplit(":", 1)[-1])
    except ValueError:
        await callback.answer()
        return
    data = await state.get_data()
    raw = data.get("sqr_rm_candidates") or []
    cands = [tuple(x) for x in raw]
    if not cands or idx < 0 or idx >= len(cands):
        await callback.answer("Неверный выбор.", show_alert=True)
        return
    selected = _sqr_rm_selected_set(data)
    if idx in selected:
        selected.remove(idx)
    else:
        selected.add(idx)
    await state.update_data(sqr_rm_selected=sorted(selected))
    page = int(data.get("sqr_rm_page") or 0)
    team = (data.get("sqr_team") or "").strip()
    ps = _ROSTER_PAGE_SIZE
    total_pages = max(1, (len(cands) + ps - 1) // ps)
    page = max(0, min(page, total_pages - 1))
    kb = _sqr_rm_multi_kb(cands, page, selected)
    caption = _sqr_rm_multi_caption(team, page, total_pages, selected)
    try:
        await callback.message.edit_text(caption, parse_mode="HTML", reply_markup=kb)
    except Exception:
        await callback.message.edit_reply_markup(reply_markup=kb)
    await callback.answer()


@squad_roster_router.callback_query(SquadRosterEnter.pick_rm, F.data == "sqr:rm:apply")
async def cb_sqr_rm_apply(callback: CallbackQuery, state: FSMContext) -> None:
    if not callback.message:
        await callback.answer()
        return
    data = await state.get_data()
    team = (data.get("sqr_team") or "").strip()
    raw = data.get("sqr_rm_candidates") or []
    cands = [tuple(x) for x in raw]
    selected = _sqr_rm_selected_set(data)
    if not selected:
        await callback.answer("Никого не выбрано.", show_alert=True)
        return
    to_remove = [(str(cands[i][0]), str(cands[i][1])) for i in sorted(selected) if 0 <= i < len(cands)]
    await callback.answer("Удаляю…")
    try:
        r = await asyncio.to_thread(remove_players_from_team_roster_bulk, team, to_remove)
    except Exception as e:
        logger.exception("remove_players_from_team_roster_bulk")
        await callback.message.answer(f"Ошибка: {e}")
        return
    await state.set_state(SquadRosterEnter.pick_choice)
    lines = [f"✅ Исключено: <b>{len(r.get('removed') or [])}</b>."]
    if r.get("errors"):
        lines.append("⚠️ Ошибки:")
        lines.extend(f"  · {html_escape(x)}" for x in r["errors"][:20])
    if r.get("removed"):
        lines.append("Сняты:")
        lines.extend(f"  · {html_escape(x)}" for x in r["removed"][:25])
        if len(r["removed"]) > 25:
            lines.append(f"  … ещё {len(r['removed']) - 25}")
    lines.append("Накопительные БД обновлены по режиму сезона.")
    await callback.message.answer(
        "\n".join(lines),
        parse_mode="HTML",
        reply_markup=_sqr_continue_kb(),
    )


@squad_roster_router.callback_query(SquadRosterEnter.pick_choice, F.data == "sqr:do:add_bulk")
async def cb_sqr_choice_add_bulk(callback: CallbackQuery, state: FSMContext) -> None:
    await callback.answer()
    if not callback.message:
        return
    data = await state.get_data()
    team = (data.get("sqr_team") or "").strip()
    cur = len(_team_roster_records(team)) if team else 0
    await state.set_state(SquadRosterEnter.wait_bulk_add)
    await callback.message.answer(
        f"Клуб <b>{html_escape(team)}</b> · сейчас в составе: <b>{cur}</b> "
        f"(макс. <b>{SQUAD_MAX}</b>).\n\n"
        "Отправь <b>несколько строк</b> — по одному игроку на строку:\n"
        "<code>имя позиция [overall] [нация]</code>\n\n"
        "Примеры:\n"
        "<code>Нубель ВРТ 76</code>\n"
        "<code>Игрок ЦП 72 Германия</code>\n\n"
        "Если игрок есть в <code>common_synced</code> — overall и нацию можно не писать.\n"
        "Добавление в <b>нац. БД</b> и <b>ЛЧ</b> (если клуб в пуле).\n"
        "Статус новых — <b>скамейка</b> (заявку start/bench/reserve — через кнопки).\n"
        "/cancel — отмена.",
        parse_mode="HTML",
    )


@squad_roster_router.message(SquadRosterEnter.wait_bulk_add, _TEXT_NOT_CMD)
async def on_sqr_bulk_add_lines(message: Message, state: FSMContext) -> None:
    data = await state.get_data()
    team = (data.get("sqr_team") or "").strip()
    if not team:
        await state.clear()
        await message.answer("Сессия сброшена. Начни с меню.")
        return
    rows, p_errors = parse_roster_add_lines(message.text or "")
    if p_errors:
        await message.answer(
            "Ошибки разбора:\n" + "\n".join(p_errors[:25])
            + ("\n…" if len(p_errors) > 25 else ""),
            parse_mode="HTML",
        )
        return
    if not rows:
        await message.answer("Нет ни одной строки. Формат: имя позиция [overall] [нация].")
        return
    cur = len(_team_roster_records(team))
    if cur + len(rows) > SQUAD_MAX:
        await message.answer(
            f"Сейчас в клубе <b>{cur}</b> игроков, добавляешь <b>{len(rows)}</b> — "
            f"лимит заявки <b>{SQUAD_MAX}</b>. Убери лишние строки.",
            parse_mode="HTML",
        )
        return
    try:
        r = await asyncio.to_thread(add_players_to_team_roster_bulk, team, rows)
    except Exception as e:
        logger.exception("add_players_to_team_roster_bulk")
        await message.answer(f"Ошибка: {e}")
        return
    await state.set_state(SquadRosterEnter.pick_choice)
    lines = [f"✅ Добавлено: <b>{len(r.get('added') or [])}</b>."]
    if r.get("errors"):
        lines.append("⚠️ Не добавлены:")
        lines.extend(f"  · {html_escape(x)}" for x in r["errors"][:20])
    if r.get("added"):
        lines.extend(f"  · {html_escape(x)}" for x in r["added"][:25])
        if len(r["added"]) > 25:
            lines.append(f"  … ещё {len(r['added']) - 25}")
    lines.append(
        f"В клубе теперь <b>{len(_team_roster_records(team))}</b> игроков "
        f"(макс. {SQUAD_MAX})."
    )
    await message.answer(
        "\n".join(lines),
        parse_mode="HTML",
        reply_markup=_sqr_continue_kb(),
    )


@squad_roster_router.callback_query(SquadRosterEnter.pick_choice, F.data == "sqr:do:add")
async def cb_sqr_choice_add(callback: CallbackQuery, state: FSMContext) -> None:
    await callback.answer()
    if not callback.message:
        return
    await state.set_state(SquadRosterEnter.add_name)
    await callback.message.answer(
        "Введи <b>имя игрока</b> (как в заявке / common).\n/cancel — отмена.",
        parse_mode="HTML",
    )


@squad_roster_router.message(SquadRosterEnter.add_name, _TEXT_NOT_CMD)
async def on_sqr_add_name(message: Message, state: FSMContext) -> None:
    name = normalize_display_name(message.text or "")
    if len(name) < 2:
        await message.answer("Слишком коротко.")
        return
    await state.update_data(sqr_add_name=name)
    await state.set_state(SquadRosterEnter.add_pos)
    await message.answer(
        "Введи <b>позицию</b> (ЦП, ЦЗ, ФРВ, ВРТ…).\n/cancel — отмена.",
        parse_mode="HTML",
    )


@squad_roster_router.message(SquadRosterEnter.add_pos, _TEXT_NOT_CMD)
async def on_sqr_add_pos(message: Message, state: FSMContext) -> None:
    pos = normalize_position(message.text or "")
    if not pos:
        await message.answer("Нужна позиция.")
        return
    await state.update_data(sqr_add_pos=pos)
    await state.set_state(SquadRosterEnter.add_ovr)
    await message.answer(
        "Введи <b>overall</b> (1–99), если игрока <b>нет</b> в common_synced.\n"
        "Если он там есть — отправь <code>-</code>.\n/cancel — отмена.",
        parse_mode="HTML",
    )


@squad_roster_router.message(SquadRosterEnter.add_ovr, _TEXT_NOT_CMD)
async def on_sqr_add_ovr(message: Message, state: FSMContext) -> None:
    raw = (message.text or "").strip()
    ovr: int | None = None
    if raw not in ("", "-", "—"):
        if not raw.isdigit():
            await message.answer("Число 1–99 или «-».")
            return
        ovr = int(raw)
        if ovr < 1 or ovr > 99:
            await message.answer("Диапазон 1–99.")
            return
    await state.update_data(sqr_add_ovr=ovr)
    await state.set_state(SquadRosterEnter.add_nat)
    await message.answer(
        "Введи <b>нацию</b> (как в игре) или <code>-</code>, если игрок уже в common "
        "и нацию не меняем / пусто.\n/cancel — отмена.",
        parse_mode="HTML",
    )


@squad_roster_router.message(SquadRosterEnter.add_nat, _TEXT_NOT_CMD)
async def on_sqr_add_nat(message: Message, state: FSMContext) -> None:
    raw = (message.text or "").strip()
    nat = None if raw in ("", "-", "—") else raw
    await state.update_data(sqr_add_nat=nat)
    await state.set_state(SquadRosterEnter.wait_status_add)
    await message.answer(
        "Выбери <b>заявку</b> в клубе для добавляемого игрока.\n/cancel — отмена.",
        parse_mode="HTML",
        reply_markup=_sqr_status_kb(),
    )


@squad_roster_router.callback_query(
    SquadRosterEnter.wait_status_add, F.data.startswith("sqr:st:")
)
async def on_sqr_add_status(callback: CallbackQuery, state: FSMContext) -> None:
    st = (callback.data or "").rsplit(":", 1)[-1]
    if st not in ("start", "bench", "reserve"):
        return
    await callback.answer()
    if not callback.message:
        return
    data = await state.get_data()
    team = (data.get("sqr_team") or "").strip()
    name = (data.get("sqr_add_name") or "").strip()
    pos = (data.get("sqr_add_pos") or "").strip()
    ovr = data.get("sqr_add_ovr")
    nat = data.get("sqr_add_nat")
    if not (team and name and pos):
        await state.clear()
        await callback.message.answer("Сессия сброшена.")
        return
    cur = len(_team_roster_records(team))
    if cur >= SQUAD_MAX:
        await callback.message.answer(
            f"В клубе уже <b>{SQUAD_MAX}</b> игроков — сначала кого-то исключи.",
            parse_mode="HTML",
        )
        return
    try:
        r = await asyncio.to_thread(
            __import__("utils.roster_manual", fromlist=["add_player_to_team_roster"]).add_player_to_team_roster,
            team,
            name,
            pos,
            overall=ovr,
            nation=nat,
            status=st,
        )
    except Exception as e:
        logger.exception("add_player_to_team_roster")
        await callback.message.answer(f"Ошибка: {e}")
        return
    await state.set_state(SquadRosterEnter.pick_choice)
    await callback.message.answer(
        f"✅ Игрок <b>{r['player']}</b> ({r['position']}) добавлен в <b>{r['team']}</b>, "
        f"overall <b>{r['overall']}</b>.\n"
        "Накопительные *_synced обновлены (если не legacy).",
        parse_mode="HTML",
        reply_markup=_sqr_continue_kb(),
    )
