# -*- coding: utf-8 -*-
"""Man Of The Month: месяц → лига → клуб → игрок."""
from __future__ import annotations

import asyncio
import logging
import re

from aiogram import F, Router
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.types import (
    CallbackQuery,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    Message,
)

from bot.services import LEAGUE_LABELS, teams_ordered_for_goalscorers
from bot.states import MonthMotmEnter

logger = logging.getLogger(__name__)

month_motm_router = Router()

_TEXT_NOT_CMD = F.text & ~F.text.startswith("/")

_RE_LG = re.compile(r"^mm:lg:\d+:[a-z0-9_]+$")
_RE_TM = re.compile(r"^mm:tm:\d+:[a-z0-9_]+:\d+$")


def _league_title(code: str) -> str:
    return dict(LEAGUE_LABELS).get(code, code)


def _club_btn_label(text: str, max_chars: int = 40) -> str:
    text = (text or "").strip()
    if len(text) <= max_chars:
        return text
    return text[: max_chars - 1] + "…"


def _months_keyboard(months: list[int]) -> InlineKeyboardMarkup:
    rows: list[list[InlineKeyboardButton]] = []
    row: list[InlineKeyboardButton] = []
    for m in months:
        row.append(
            InlineKeyboardButton(text=f"М{m}", callback_data=f"mm:mo:{m}")
        )
        if len(row) == 4:
            rows.append(row)
            row = []
    if row:
        rows.append(row)
    return InlineKeyboardMarkup(inline_keyboard=rows)


def _league_kb(month: int) -> InlineKeyboardMarkup:
    row: list[InlineKeyboardButton] = []
    rows: list[list[InlineKeyboardButton]] = []
    for code, label in LEAGUE_LABELS:
        row.append(
            InlineKeyboardButton(
                text=label,
                callback_data=f"mm:lg:{month}:{code}",
            )
        )
        if len(row) == 3:
            rows.append(row)
            row = []
    if row:
        rows.append(row)
    return InlineKeyboardMarkup(inline_keyboard=rows)


def _teams_kb(month: int, league_code: str) -> InlineKeyboardMarkup:
    teams = teams_ordered_for_goalscorers(league_code)
    rows: list[list[InlineKeyboardButton]] = []
    row: list[InlineKeyboardButton] = []
    for idx, team in enumerate(teams):
        row.append(
            InlineKeyboardButton(
                text=_club_btn_label(team),
                callback_data=f"mm:tm:{month}:{league_code}:{idx}",
            )
        )
        if len(row) == 2:
            rows.append(row)
            row = []
    if row:
        rows.append(row)
    return InlineKeyboardMarkup(inline_keyboard=rows)


async def _open_month_motm_menu(message: Message) -> None:
    from utils.month_motm_award import completed_calendar_months

    months = await asyncio.to_thread(completed_calendar_months)
    if not months:
        await message.answer(
            "📆 <b>Игрок месяца (MOTM)</b>\n\n"
            "Нет завершённых месяцев — дождись, пока все матчи месяца "
            "будут сыграны или внесены в пропуски.",
            parse_mode="HTML",
        )
        return
    await message.answer(
        "📆 <b>Игрок месяца (MOTM)</b>\n\n"
        "Выбери <b>завершённый</b> месяц календаря, затем лигу, клуб и игрока.\n"
        "В каждой лиге (и в ЛЧ) — свой игрок месяца.\n\n"
        "/cancel — отмена.",
        reply_markup=_months_keyboard(months),
        parse_mode="HTML",
    )


@month_motm_router.callback_query(F.data == "menu:month_motm")
async def cb_menu_month_motm(callback: CallbackQuery, state: FSMContext) -> None:
    await callback.answer()
    await state.clear()
    if callback.message:
        await _open_month_motm_menu(callback.message)


@month_motm_router.message(Command("month_motm"))
async def cmd_month_motm(message: Message, state: FSMContext) -> None:
    await state.clear()
    await _open_month_motm_menu(message)


@month_motm_router.callback_query(F.data.startswith("mm:mo:"))
async def cb_mm_month(callback: CallbackQuery, state: FSMContext) -> None:
    await callback.answer()
    if not callback.message or not callback.data:
        return
    try:
        month = int(callback.data.split(":")[-1])
    except ValueError:
        return
    from utils.month_motm_award import is_calendar_month_complete

    if not await asyncio.to_thread(is_calendar_month_complete, month):
        await callback.message.answer(f"Месяц {month} ещё не завершён.")
        return
    await state.update_data(mm_month=month)
    await callback.message.answer(
        f"📆 <b>MOTM</b> · месяц <b>{month}</b>\nВыбери лигу:",
        reply_markup=_league_kb(month),
        parse_mode="HTML",
    )


@month_motm_router.callback_query(F.data.startswith("mm:lg:"))
async def cb_mm_league(callback: CallbackQuery, state: FSMContext) -> None:
    d = callback.data
    if not d or not _RE_LG.match(d):
        return
    await callback.answer()
    if not callback.message:
        return
    parts = d.split(":")
    if len(parts) < 4:
        return
    try:
        month = int(parts[2])
    except ValueError:
        return
    code = parts[3]
    from utils.month_motm_award import month_league_already_awarded

    if await asyncio.to_thread(month_league_already_awarded, month, code):
        from utils.month_motm_award import get_month_award

        prev = await asyncio.to_thread(get_month_award, month, code) or {}
        await callback.message.answer(
            f"За месяц {month} в {_league_title(code)} уже выбран "
            f"<b>{prev.get('player')}</b> ({prev.get('team')}).",
            parse_mode="HTML",
        )
        return
    try:
        kb = _teams_kb(month, code)
    except Exception as e:
        logger.exception("mm_teams_kb")
        await callback.message.answer(f"Ошибка: {e}")
        return
    await state.update_data(mm_month=month, mm_lg=code)
    await callback.message.answer(
        f"📆 MOTM · м{month} · <b>{_league_title(code)}</b>\nВыбери клуб:",
        reply_markup=kb,
        parse_mode="HTML",
    )


@month_motm_router.callback_query(F.data.startswith("mm:tm:"))
async def cb_mm_team(callback: CallbackQuery, state: FSMContext) -> None:
    d = callback.data
    if not d or not _RE_TM.match(d):
        return
    if not callback.message:
        return
    await callback.answer()
    parts = d.split(":")
    if len(parts) < 5:
        return
    try:
        month = int(parts[2])
        idx = int(parts[4])
    except ValueError:
        return
    code = parts[3]
    try:
        teams = teams_ordered_for_goalscorers(code)
        team = teams[idx]
    except (IndexError, Exception) as e:
        await callback.message.answer(f"Клуб: ошибка: {e}")
        return
    await state.update_data(mm_month=month, mm_lg=code, mm_team=team)
    await state.set_state(MonthMotmEnter.wait_name)
    await callback.message.answer(
        f"📆 <b>MOTM</b> · м{month} · {_league_title(code)} · {team}\n\n"
        "Введи <b>имя игрока</b> как в базе.\n/cancel — отмена.",
        parse_mode="HTML",
    )


@month_motm_router.message(MonthMotmEnter.wait_name, _TEXT_NOT_CMD)
async def on_mm_player_name(message: Message, state: FSMContext) -> None:
    name = (message.text or "").strip()
    if len(name) < 2:
        await message.answer("Слишком коротко. Введи имя ещё раз.")
        return
    data = await state.get_data()
    month = data.get("mm_month")
    lg = data.get("mm_lg", "")
    team = data.get("mm_team", "")
    if not month or not lg or not team:
        await state.clear()
        await message.answer("Сброс. Начни с меню «Игрок месяца».")
        return
    from utils.month_motm_award import apply_month_motm_award
    from utils.player_names import resolve_player_query_in_team
    from utils.utils import get_session
    from bot.services import tournament_db_for_league

    sess = get_session(tournament_db_for_league(str(lg)))
    player, err = resolve_player_query_in_team(sess, str(team), name, position=None)
    if err or not player:
        await message.answer(err or "Игрок не найден. Проверь имя.")
        return
    ok, msg = await asyncio.to_thread(
        apply_month_motm_award,
        int(month),
        str(lg),
        player.name,
        player.team,
        position=str(player.position or ""),
    )
    await state.clear()
    if not ok:
        await message.answer(msg)
        return
    await message.answer(
        f"✅ <b>Игрок месяца (MOTM)</b>\n"
        f"Месяц {month} · {_league_title(str(lg))}\n"
        f"<b>{player.name}</b> · {player.team}\n"
        f"+1 MOTM в БД.",
        parse_mode="HTML",
    )
