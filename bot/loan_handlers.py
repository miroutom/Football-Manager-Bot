# -*- coding: utf-8 -*-
"""Аренды: лига → клуб → строка «имя позиция overall Nм»."""
from __future__ import annotations

import asyncio
import logging
import re

from aiogram import F, Router
from aiogram.fsm.context import FSMContext
from aiogram.types import (
    CallbackQuery,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    Message,
)

from bot.services import LEAGUE_LABELS, teams_ordered_for_goalscorers
from bot.states import LoanEnter

logger = logging.getLogger(__name__)

loan_router = Router()

_TEXT_NOT_CMD = F.text & ~F.text.startswith("/")

_RE_LOAN_LG = re.compile(r"^loan:lg:([a-z0-9_]+)$")
_RE_LOAN_TM = re.compile(r"^loan:tm:([a-z0-9_]+):(\d+)$")


def _league_title(code: str) -> str:
    return dict(LEAGUE_LABELS).get(code, code)


def _club_btn(text: str, max_chars: int = 40) -> str:
    text = (text or "").strip()
    if len(text) <= max_chars:
        return text
    return text[: max_chars - 1] + "…"


def _loan_league_kb() -> InlineKeyboardMarkup:
    row: list[InlineKeyboardButton] = []
    rows: list[list[InlineKeyboardButton]] = []
    for code, label in LEAGUE_LABELS:
        row.append(
            InlineKeyboardButton(text=label, callback_data=f"loan:lg:{code}")
        )
        if len(row) == 3:
            rows.append(row)
            row = []
    if row:
        rows.append(row)
    return InlineKeyboardMarkup(inline_keyboard=rows)


def _loan_teams_kb(league_code: str) -> InlineKeyboardMarkup:
    teams = teams_ordered_for_goalscorers(league_code)
    rows: list[list[InlineKeyboardButton]] = []
    row: list[InlineKeyboardButton] = []
    for idx, team in enumerate(teams):
        row.append(
            InlineKeyboardButton(
                text=_club_btn(team),
                callback_data=f"loan:tm:{league_code}:{idx}",
            )
        )
        if len(row) == 2:
            rows.append(row)
            row = []
    if row:
        rows.append(row)
    return InlineKeyboardMarkup(inline_keyboard=rows)


@loan_router.callback_query(F.data == "menu:loan")
async def cb_menu_loan(callback: CallbackQuery, state: FSMContext) -> None:
    await callback.answer()
    if callback.message is None:
        return
    await state.clear()
    await state.set_state(LoanEnter.pick_lg)
    await callback.message.answer(
        "📅 <b>Аренда</b>\n\n"
        "Выбери лигу и клуб, затем одной строкой:\n"
        "<code>имя позиция overall Nм</code>\n\n"
        "Пример: <code>нубель врт 76 7м</code> — через 7 месяцев календаря (как у травм) "
        "игрок уйдёт в свободные агенты; раньше — как обычный игрок в составе.\n\n"
        "Срок в конце: число + лат. <code>m</code> или кирил. <code>м</code>.\n"
        "/cancel — отмена.",
        parse_mode="HTML",
        reply_markup=_loan_league_kb(),
    )


@loan_router.callback_query(F.data.regexp(_RE_LOAN_LG))
async def cb_loan_league(callback: CallbackQuery, state: FSMContext) -> None:
    m = _RE_LOAN_LG.match(callback.data or "")
    if not m:
        await callback.answer()
        return
    code = m.group(1)
    await callback.answer()
    await state.update_data(loan_lg=code)
    await state.set_state(LoanEnter.pick_team)
    if callback.message:
        await callback.message.answer(
            f"{_league_title(code)} — выбери клуб:",
            reply_markup=_loan_teams_kb(code),
        )


@loan_router.callback_query(F.data.regexp(_RE_LOAN_TM))
async def cb_loan_team(callback: CallbackQuery, state: FSMContext) -> None:
    m = _RE_LOAN_TM.match(callback.data or "")
    if not m:
        await callback.answer()
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
        if callback.message:
            await callback.message.answer(f"Ошибка клуба: {e}")
        return
    await state.update_data(loan_team=team, loan_lg=code)
    await state.set_state(LoanEnter.wait_line)
    if callback.message:
        await callback.message.answer(
            f"<b>{_league_title(code)}</b> · <b>{team}</b>\n\n"
            "Введи строку аренды, например:\n<code>нубель врт 76 7м</code>",
            parse_mode="HTML",
        )


@loan_router.message(LoanEnter.wait_line, _TEXT_NOT_CMD)
async def on_loan_line(message: Message, state: FSMContext) -> None:
    data = await state.get_data()
    team = (data.get("loan_team") or "").strip()
    if not team:
        await state.clear()
        await message.answer("Сессия сброшена. Начни с меню → аренда.")
        return
    from utils.player_loans import register_loan_for_team

    msg, ok = await asyncio.to_thread(
        register_loan_for_team,
        team,
        message.text or "",
        schedule_day=None,
    )
    await state.clear()
    await message.answer(msg, parse_mode="HTML")


@loan_router.message(LoanEnter.pick_lg, _TEXT_NOT_CMD)
@loan_router.message(LoanEnter.pick_team, _TEXT_NOT_CMD)
async def on_loan_stray(message: Message) -> None:
    await message.answer("Сначала выбери лигу и клуб кнопками или /cancel.")
