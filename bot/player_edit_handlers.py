"""Правка одного поля у игрока: лига → клуб (кнопки) → игрок → поле → значение."""
from __future__ import annotations

import asyncio
import logging
import re
from html import escape as html_escape

from aiogram import F, Router
from aiogram.fsm.context import FSMContext
from aiogram.types import (
    CallbackQuery,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    Message,
)

from bot.services import LEAGUE_LABELS, teams_ordered_for_goalscorers
from bot.states import PlayerFieldEnter
from bot.transfer_handlers import _ROSTER_PAGE_SIZE
from utils.player_field_edit import (
    apply_player_field_update,
    format_merge_preview_message,
    list_editable_fields_for_player,
    preview_field_update_merge,
)
from utils.player_names import player_display_name, player_surname
from utils.player_transfer import _filter_team, _norm_cmp
from utils.transfer_input import resolve_team_name

logger = logging.getLogger(__name__)

player_edit_router = Router()

_TEXT_NOT_CMD = F.text & ~F.text.startswith("/")


async def _ensure_player_field_fsm(callback: CallbackQuery, state: FSMContext) -> bool:
    cur = await state.get_state()
    if cur is None or not str(cur).startswith("PlayerFieldEnter"):
        await callback.answer(
            "Сессия сброшена. Снова: «Изменить игроков» → «Изменить игрока (любое поле)».",
            show_alert=True,
        )
        return False
    if callback.message is None:
        await callback.answer("Сообщение недоступно.", show_alert=True)
        return False
    return True

_RE_PFP_LG = re.compile(r"^pfp:lg:([a-z0-9_]+)$")
_RE_PFP_TM = re.compile(r"^pfp:tm:([a-z0-9_]+):(\d+)$")


def _league_title(code: str) -> str:
    return dict(LEAGUE_LABELS).get(code, code)


def _pfp_roster_caption_html(data: dict, page: int, total_pages: int) -> str:
    code = data.get("pfp_lg") or ""
    team = html_escape((data.get("pfp_team") or "").strip())
    return (
        f"<b>{html_escape(_league_title(code))}</b> · {team}\n\n"
        f"Выбери игрока (стр. <b>{page + 1}</b>/<b>{total_pages}</b>).\n/cancel — отмена."
    )


def _club_btn_label(text: str, max_chars: int = 40) -> str:
    text = (text or "").strip()
    if len(text) <= max_chars:
        return text
    return text[: max_chars - 1] + "…"


def _pfp_league_kb() -> InlineKeyboardMarkup:
    row: list[InlineKeyboardButton] = []
    rows: list[list[InlineKeyboardButton]] = []
    for code, label in LEAGUE_LABELS:
        row.append(
            InlineKeyboardButton(
                text=label,
                callback_data=f"pfp:lg:{code}",
            )
        )
        if len(row) == 3:
            rows.append(row)
            row = []
    if row:
        rows.append(row)
    return InlineKeyboardMarkup(inline_keyboard=rows)


def _pfp_teams_kb(league_code: str) -> InlineKeyboardMarkup:
    teams = teams_ordered_for_goalscorers(league_code)
    rows: list[list[InlineKeyboardButton]] = []
    row: list[InlineKeyboardButton] = []
    for idx, team in enumerate(teams):
        row.append(
            InlineKeyboardButton(
                text=_club_btn_label(team),
                callback_data=f"pfp:tm:{league_code}:{idx}",
            )
        )
        if len(row) == 2:
            rows.append(row)
            row = []
    if row:
        rows.append(row)
    return InlineKeyboardMarkup(inline_keyboard=rows)


def _pfp_roster_entries(team: str) -> list[tuple[str, str, int, str, str, int]]:
    """Ростер с id строки: имя, поз, ovr, клуб, таблица, id (одна строка на имя)."""
    from data.defender import Defender
    from data.forward import Forward
    from data.goalkeeper import Goalkeeper
    from data.midfielder import Midfielder
    from utils.utils import session_league

    resolved = resolve_team_name(team, session_league)
    t = resolved if resolved else team.strip().title()
    best: dict[str, tuple[str, str, int, str, str, int]] = {}
    for Cls in (Forward, Midfielder, Defender, Goalkeeper):
        tbl = Cls.__tablename__
        for r in session_league.query(Cls).filter(_filter_team(Cls, t)).all():
            disp = player_display_name(r)
            if not disp:
                continue
            pos = (r.position or "").strip()
            db_team = (r.team or "").strip()
            ovr = int(r.overall or 0)
            rid = int(r.id or 0)
            nk = _norm_cmp(player_surname(r))
            row = (disp, pos, ovr, db_team, tbl, rid)
            prev = best.get(nk)
            if prev is None or (ovr, rid) > (prev[2], prev[5]):
                best[nk] = row
    return sorted(best.values(), key=lambda x: (-x[2], x[0].lower()))


def _pfp_roster_keyboard(
    candidates: list[tuple[str, str, int, str, str, int]], page: int
) -> InlineKeyboardMarkup:
    n = len(candidates)
    ps = _ROSTER_PAGE_SIZE
    total_pages = max(1, (n + ps - 1) // ps)
    page = max(0, min(int(page), total_pages - 1))
    chunk = candidates[page * ps : page * ps + ps]
    base = page * ps
    rows: list[list[InlineKeyboardButton]] = []
    for i, (nm, pos, ov, _dbt, _tbl, _rid) in enumerate(chunk):
        gidx = base + i
        label = f"{nm} · {pos} · {ov}"
        if len(label) > 60:
            label = label[:57] + "…"
        rows.append(
            [InlineKeyboardButton(text=label, callback_data=f"pfp:pk:{gidx}")]
        )
    if total_pages > 1:
        nav: list[InlineKeyboardButton] = []
        if page > 0:
            nav.append(
                InlineKeyboardButton(
                    text=f"« {page + 1}/{total_pages}",
                    callback_data=f"pfp:pg:{page - 1}",
                )
            )
        if page < total_pages - 1:
            nav.append(
                InlineKeyboardButton(
                    text=f"{page + 2}/{total_pages} »",
                    callback_data=f"pfp:pg:{page + 1}",
                )
            )
        if nav:
            rows.append(nav)
    return InlineKeyboardMarkup(inline_keyboard=rows)


def _pfp_fields_keyboard(fields: list[str]) -> InlineKeyboardMarkup:
    rows: list[list[InlineKeyboardButton]] = []
    row: list[InlineKeyboardButton] = []
    for i, fname in enumerate(fields):
        lab = fname if len(fname) <= 28 else fname[:25] + "…"
        row.append(
            InlineKeyboardButton(text=lab, callback_data=f"pfp:fd:{i}")
        )
        if len(row) == 2:
            rows.append(row)
            row = []
    if row:
        rows.append(row)
    rows.append([
        InlineKeyboardButton(text="◀ К игрокам клуба", callback_data="pfp:nav:roster"),
        InlineKeyboardButton(text="◀ К клубам лиги", callback_data="pfp:nav:teams"),
    ])
    rows.append([
        InlineKeyboardButton(text="✅ Завершить", callback_data="pfp:nav:done"),
    ])
    return InlineKeyboardMarkup(inline_keyboard=rows)


@player_edit_router.callback_query(F.data == "menu:player_field")
async def cb_menu_player_field(callback: CallbackQuery, state: FSMContext) -> None:
    await callback.answer()
    if callback.message is None:
        return
    await state.clear()
    await state.set_state(PlayerFieldEnter.pick_lg)
    await callback.message.answer(
        "✏️ <b>Поле игрока</b>\n\n"
        "Выбери лигу (список клубов — как в бомбардирах), затем клуб и игрока кнопками, "
        "потом поле и новое значение текстом.\n"
        "/cancel — отмена.",
        parse_mode="HTML",
        reply_markup=_pfp_league_kb(),
    )


@player_edit_router.callback_query(F.data.regexp(_RE_PFP_LG))
async def cb_pfp_league(callback: CallbackQuery, state: FSMContext) -> None:
    m = _RE_PFP_LG.match(callback.data or "")
    if not m:
        await callback.answer()
        return
    if not await _ensure_player_field_fsm(callback, state):
        return
    code = m.group(1)
    await callback.answer()
    await state.update_data(pfp_lg=code)
    await state.set_state(PlayerFieldEnter.pick_team)
    kb = _pfp_teams_kb(code)
    await callback.message.answer(
        f"{_league_title(code)} — выберите клуб:",
        reply_markup=kb,
    )


@player_edit_router.callback_query(F.data.regexp(_RE_PFP_TM))
async def cb_pfp_team(callback: CallbackQuery, state: FSMContext) -> None:
    m = _RE_PFP_TM.match(callback.data or "")
    if not m:
        await callback.answer()
        return
    if not await _ensure_player_field_fsm(callback, state):
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
    rows = _pfp_roster_entries(team)
    if not rows:
        await callback.message.answer(
            f"В <b>текущей нац. БД</b> нет состава для «{team}». "
            "Проверь активный сезон/лигу или написание.\n/cancel — отмена.",
            parse_mode="HTML",
        )
        return
    canonical = rows[0][3] if rows else team
    serial = [list(x) for x in rows]
    await state.update_data(
        pfp_lg=code,
        pfp_team=canonical,
        pfp_candidates=serial,
        pfp_roster_page=0,
    )
    await state.set_state(PlayerFieldEnter.pick_player)
    cands = [tuple(x) for x in serial]
    await callback.message.answer(
        f"<b>{_league_title(code)}</b> · {canonical}\n\n"
        "Выбери игрока (при длинном списке — листание).\n/cancel — отмена.",
        parse_mode="HTML",
        reply_markup=_pfp_roster_keyboard(cands, 0),
    )


@player_edit_router.callback_query(PlayerFieldEnter.pick_player, F.data.startswith("pfp:pg:"))
async def cb_pfp_roster_page(callback: CallbackQuery, state: FSMContext) -> None:
    if not callback.message or not callback.data:
        await callback.answer()
        return
    try:
        page = int((callback.data or "").rsplit(":", 1)[-1])
    except ValueError:
        await callback.answer()
        return
    data = await state.get_data()
    raw = data.get("pfp_candidates") or []
    cands = [tuple(x) for x in raw]
    if not cands:
        await callback.answer("Сессия устарела. Открой снова из меню.", show_alert=True)
        return
    await state.update_data(pfp_roster_page=page)
    ps = _ROSTER_PAGE_SIZE
    total_pages = max(1, (len(cands) + ps - 1) // ps)
    page = max(0, min(page, total_pages - 1))
    kb = _pfp_roster_keyboard(cands, page)
    caption = _pfp_roster_caption_html(data, page, total_pages)
    try:
        await callback.message.edit_text(
            caption,
            parse_mode="HTML",
            reply_markup=kb,
        )
    except Exception:
        try:
            await callback.message.edit_reply_markup(reply_markup=kb)
        except Exception:
            await callback.message.answer(
                f"Стр. {page + 1}/{total_pages}:",
                reply_markup=kb,
            )
    await callback.answer()


@player_edit_router.callback_query(PlayerFieldEnter.pick_player, F.data.startswith("pfp:pk:"))
async def cb_pfp_pick_player(callback: CallbackQuery, state: FSMContext) -> None:
    if not callback.message or not callback.data:
        await callback.answer()
        return
    try:
        idx = int((callback.data or "").rsplit(":", 1)[-1])
    except ValueError:
        await callback.answer()
        return
    data = await state.get_data()
    raw = data.get("pfp_candidates") or []
    cands = [tuple(x) for x in raw]
    team = (data.get("pfp_team") or "").strip()
    if not cands or idx < 0 or idx >= len(cands) or not team:
        await callback.answer("Неверный выбор.", show_alert=True)
        return
    name, pos, _ov, _dbt, tbl, rid = cands[idx]
    fields = list_editable_fields_for_player(
        team, name, pos, row_id=rid, table=tbl
    )
    if not fields:
        await callback.answer("Нет полей.", show_alert=True)
        return
    await callback.answer()
    await state.update_data(
        pfp_name=name,
        pfp_pos=pos,
        pfp_fields=fields,
        pfp_row_id=rid,
        pfp_table=tbl,
    )
    await state.set_state(PlayerFieldEnter.pick_field)
    try:
        await callback.message.edit_text(
            f"<b>{name}</b> ({pos}) · {team}\n\nВыбери поле:",
            parse_mode="HTML",
            reply_markup=_pfp_fields_keyboard(fields),
        )
    except Exception:
        await callback.message.answer(
            f"<b>{name}</b> ({pos}) · {team}\n\nВыбери поле:",
            parse_mode="HTML",
            reply_markup=_pfp_fields_keyboard(fields),
        )


@player_edit_router.callback_query(PlayerFieldEnter.pick_field, F.data.startswith("pfp:fd:"))
async def cb_pfp_pick_field(callback: CallbackQuery, state: FSMContext) -> None:
    if not callback.message or not callback.data:
        await callback.answer()
        return
    try:
        fi = int((callback.data or "").rsplit(":", 1)[-1])
    except ValueError:
        await callback.answer()
        return
    data = await state.get_data()
    fields: list[str] = list(data.get("pfp_fields") or [])
    if fi < 0 or fi >= len(fields):
        await callback.answer("Неверное поле.", show_alert=True)
        return
    fname = fields[fi]
    await callback.answer()
    await state.update_data(pfp_field=fname)
    await state.set_state(PlayerFieldEnter.wait_value)
    await callback.message.answer(
        f"Поле: <code>{fname}</code>\n\n"
        "Введи новое значение одной строкой.\n"
        "Для пустой нации / сброса статуса: <code>-</code> или пусто (если поле допускает NULL).\n"
        "/cancel — отмена.",
        parse_mode="HTML",
    )


def _pfp_merge_keyboard(preview: dict) -> InlineKeyboardMarkup:
    rows = list(preview.get("rows") or [])
    buttons: list[list[InlineKeyboardButton]] = []
    for i, row in enumerate(rows):
        st = row.get("stats") or {}
        g = int(st.get("goals", 0) or 0)
        a = int(st.get("assists", 0) or 0)
        m = int(st.get("matches", 0) or 0)
        label = f"{row.get('name')} ({row.get('position')}) {m}м {g}+{a}"
        if len(label) > 60:
            label = label[:57] + "…"
        buttons.append(
            [InlineKeyboardButton(text=label, callback_data=f"pfp:mrg:i:{i}")]
        )
    buttons.append(
        [InlineKeyboardButton(text="Сумма всех строк", callback_data="pfp:mrg:sum")]
    )
    buttons.append(
        [
            InlineKeyboardButton(
                text="Только редактируемая строка",
                callback_data="pfp:mrg:pri",
            )
        ]
    )
    return InlineKeyboardMarkup(inline_keyboard=buttons)


async def _pfp_apply_and_reply(
    message: Message,
    state: FSMContext,
    *,
    raw: str,
    merge_mode: str = "sum",
) -> None:
    data = await state.get_data()
    team = (data.get("pfp_team") or "").strip()
    name = (data.get("pfp_name") or "").strip()
    pos = (data.get("pfp_pos") or "").strip()
    field = (data.get("pfp_field") or "").strip()
    row_id = data.get("pfp_row_id")
    table = data.get("pfp_table")
    if not (team and name and pos and field):
        await state.clear()
        await message.answer("Сессия сброшена. Открой снова из меню.")
        return
    try:
        r = await asyncio.to_thread(
            apply_player_field_update,
            team,
            name,
            pos,
            field,
            raw,
            row_id=int(row_id) if row_id is not None else None,
            table=str(table) if table else None,
            merge_mode=merge_mode,
        )
    except ValueError as e:
        await message.answer(str(e))
        return
    except Exception as e:
        logger.exception("apply_player_field_update")
        await message.answer(f"Ошибка: {e}")
        return
    disp_name = str(r.get("display_name") or name)
    disp_pos = str(r.get("display_pos") or pos)
    fields: list[str] = list_editable_fields_for_player(
        team, disp_name, disp_pos, row_id=row_id, table=table
    )
    merged_note = ""
    if int(r.get("merged_rows") or 0) > 0:
        mode_lbl = str(r.get("merge_mode") or merge_mode)
        merged_note = (
            f"\nСлито дублей: <b>{r['merged_rows']}</b> (режим: <code>{html_escape(mode_lbl)}</code>)."
        )
    await state.update_data(
        pfp_name=disp_name,
        pfp_pos=disp_pos,
        pfp_fields=fields,
        pfp_field=None,
        pfp_pending_raw=None,
        pfp_merge_preview=None,
    )
    await state.set_state(PlayerFieldEnter.pick_field)
    cl_note = f", ЛЧ строк: <b>{r['cl_updated']}</b>" if r.get("cl_updated") else ""
    await message.answer(
        "✅ Обновлено (та же строка в БД).\n"
        f"Таблица: <code>{r['league_table']}</code>, поле <code>{r['field']}</code>.\n"
        f"Было: <code>{r['before']!r}</code> → стало: <code>{r['after']!r}</code>{cl_note}{merged_note}\n"
        "<code>common.db</code> пересобран.\n\n"
        f"<b>{html_escape(disp_name)}</b> ({html_escape(disp_pos)}) · {html_escape(team)} — "
        "выбери ещё поле или завершить:",
        parse_mode="HTML",
        reply_markup=_pfp_fields_keyboard(fields),
    )


@player_edit_router.message(PlayerFieldEnter.wait_value, _TEXT_NOT_CMD)
async def on_pfp_value(message: Message, state: FSMContext) -> None:
    data = await state.get_data()
    team = (data.get("pfp_team") or "").strip()
    name = (data.get("pfp_name") or "").strip()
    pos = (data.get("pfp_pos") or "").strip()
    field = (data.get("pfp_field") or "").strip()
    row_id = data.get("pfp_row_id")
    table = data.get("pfp_table")
    if not (team and name and pos and field):
        await state.clear()
        await message.answer("Сессия сброшена. Открой снова из меню.")
        return
    raw = message.text or ""
    try:
        preview = await asyncio.to_thread(
            preview_field_update_merge,
            team,
            name,
            pos,
            field,
            raw,
            row_id=int(row_id) if row_id is not None else None,
            table=str(table) if table else None,
        )
    except Exception as e:
        logger.exception("preview_field_update_merge")
        await message.answer(f"Ошибка проверки слияния: {e}")
        return
    if preview:
        await state.update_data(pfp_pending_raw=raw, pfp_merge_preview=preview)
        await state.set_state(PlayerFieldEnter.confirm_merge)
        await message.answer(
            format_merge_preview_message(preview),
            parse_mode="HTML",
            reply_markup=_pfp_merge_keyboard(preview),
        )
        return
    await _pfp_apply_and_reply(message, state, raw=raw)


@player_edit_router.callback_query(
    PlayerFieldEnter.confirm_merge,
    F.data.startswith("pfp:mrg:"),
)
async def cb_pfp_confirm_merge(callback: CallbackQuery, state: FSMContext) -> None:
    if not await _ensure_player_field_fsm(callback, state):
        return
    if callback.message is None or not callback.data:
        await callback.answer()
        return
    data = await state.get_data()
    preview = data.get("pfp_merge_preview")
    raw = data.get("pfp_pending_raw")
    if not preview or raw is None:
        await callback.answer("Сессия устарела.", show_alert=True)
        await state.set_state(PlayerFieldEnter.pick_field)
        return
    cd = callback.data or ""
    merge_mode = "sum"
    if cd == "pfp:mrg:sum":
        merge_mode = "sum"
    elif cd == "pfp:mrg:pri":
        merge_mode = "keep_primary"
    elif cd.startswith("pfp:mrg:i:"):
        try:
            idx = int(cd.rsplit(":", 1)[-1])
        except ValueError:
            await callback.answer("Неверный выбор.", show_alert=True)
            return
        rows = list(preview.get("rows") or [])
        if idx < 0 or idx >= len(rows):
            await callback.answer("Неверный выбор.", show_alert=True)
            return
        row = rows[idx]
        merge_mode = f"keep:{row.get('table')}:{row.get('id')}"
    else:
        await callback.answer()
        return
    await callback.answer()
    await _pfp_apply_and_reply(
        callback.message,
        state,
        raw=str(raw),
        merge_mode=merge_mode,
    )


@player_edit_router.callback_query(F.data == "pfp:nav:done")
async def cb_pfp_nav_done(callback: CallbackQuery, state: FSMContext) -> None:
    await callback.answer()
    await state.clear()
    if callback.message is not None:
        await callback.message.answer("Готово. Сессия редактирования завершена.")


@player_edit_router.callback_query(F.data == "pfp:nav:roster")
async def cb_pfp_nav_roster(callback: CallbackQuery, state: FSMContext) -> None:
    if callback.message is None:
        await callback.answer()
        return
    data = await state.get_data()
    code = (data.get("pfp_lg") or "").strip()
    team = (data.get("pfp_team") or "").strip()
    raw = data.get("pfp_candidates") or []
    cands = [tuple(x) for x in raw]
    if not (code and team and cands):
        await callback.answer("Сессия устарела. Открой снова из меню.", show_alert=True)
        await state.clear()
        return
    await callback.answer()
    await state.update_data(pfp_name=None, pfp_pos=None, pfp_field=None, pfp_fields=None)
    await state.set_state(PlayerFieldEnter.pick_player)
    page = int(data.get("pfp_roster_page") or 0)
    ps = _ROSTER_PAGE_SIZE
    total_pages = max(1, (len(cands) + ps - 1) // ps)
    page = max(0, min(page, total_pages - 1))
    await callback.message.answer(
        _pfp_roster_caption_html(data, page, total_pages),
        parse_mode="HTML",
        reply_markup=_pfp_roster_keyboard(cands, page),
    )


@player_edit_router.callback_query(F.data == "pfp:nav:teams")
async def cb_pfp_nav_teams(callback: CallbackQuery, state: FSMContext) -> None:
    if callback.message is None:
        await callback.answer()
        return
    data = await state.get_data()
    code = (data.get("pfp_lg") or "").strip()
    if not code:
        await callback.answer("Сессия устарела. Открой снова из меню.", show_alert=True)
        await state.clear()
        return
    await callback.answer()
    await state.update_data(
        pfp_team=None,
        pfp_candidates=None,
        pfp_roster_page=0,
        pfp_name=None,
        pfp_pos=None,
        pfp_field=None,
        pfp_fields=None,
    )
    await state.set_state(PlayerFieldEnter.pick_team)
    await callback.message.answer(
        f"{_league_title(code)} — выберите клуб:",
        reply_markup=_pfp_teams_kb(code),
    )
