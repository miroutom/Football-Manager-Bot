# -*- coding: utf-8 -*-
"""Меню «Травмы»: лига → клуб → строка как в статистике матча (без жк/кк)."""
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
from bot.states import InjuryEnter

logger = logging.getLogger(__name__)

injury_router = Router()

_TEXT_NOT_CMD = F.text & ~F.text.startswith("/")

_RE_INJ_LG = re.compile(r"^inj:lg:([a-z0-9_]+)$")
_RE_INJ_TM = re.compile(r"^inj:tm:([a-z0-9_]+):(\d+)$")


def _league_title(code: str) -> str:
    return dict(LEAGUE_LABELS).get(code, code)


def _club_btn(text: str, max_chars: int = 40) -> str:
    text = (text or "").strip()
    if len(text) <= max_chars:
        return text
    return text[: max_chars - 1] + "…"


def _injury_league_kb() -> InlineKeyboardMarkup:
    row: list[InlineKeyboardButton] = []
    rows: list[list[InlineKeyboardButton]] = []
    for code, label in LEAGUE_LABELS:
        row.append(
            InlineKeyboardButton(text=label, callback_data=f"inj:lg:{code}")
        )
        if len(row) == 3:
            rows.append(row)
            row = []
    if row:
        rows.append(row)
    return InlineKeyboardMarkup(inline_keyboard=rows)


def _injury_teams_kb(league_code: str) -> InlineKeyboardMarkup:
    teams = teams_ordered_for_goalscorers(league_code)
    rows: list[list[InlineKeyboardButton]] = []
    row: list[InlineKeyboardButton] = []
    for idx, team in enumerate(teams):
        row.append(
            InlineKeyboardButton(
                text=_club_btn(team),
                callback_data=f"inj:tm:{league_code}:{idx}",
            )
        )
        if len(row) == 2:
            rows.append(row)
            row = []
    if row:
        rows.append(row)
    return InlineKeyboardMarkup(inline_keyboard=rows)


@injury_router.callback_query(F.data == "menu:injury")
async def cb_menu_injury(callback: CallbackQuery, state: FSMContext) -> None:
    await callback.answer()
    if callback.message is None:
        return
    await state.clear()
    await state.set_state(InjuryEnter.pick_lg)
    await callback.message.answer(
        "🏥 <b>Травмы</b>\n\n"
        "Выбери лигу и клуб, затем строку в формате:\n"
        "<code>имя Nм</code> или <code>имя Nм тип</code>\n\n"
        "Примеры: <code>Симонс 4м</code>, <code>Симонс 4м колено</code>\n"
        "(число — месяцы календаря до возвращения; как при записи статистики матча).\n\n"
        "ЖК и КК вводятся в статистике после матча, не здесь.\n"
        "/cancel — отмена.",
        parse_mode="HTML",
        reply_markup=_injury_league_kb(),
    )


@injury_router.callback_query(F.data.regexp(_RE_INJ_LG))
async def cb_injury_league(callback: CallbackQuery, state: FSMContext) -> None:
    m = _RE_INJ_LG.match(callback.data or "")
    if not m:
        await callback.answer()
        return
    code = m.group(1)
    await callback.answer()
    await state.update_data(injury_lg=code)
    await state.set_state(InjuryEnter.pick_team)
    if callback.message:
        await callback.message.answer(
            f"{_league_title(code)} — выбери клуб:",
            reply_markup=_injury_teams_kb(code),
        )


@injury_router.callback_query(F.data.regexp(_RE_INJ_TM))
async def cb_injury_team(callback: CallbackQuery, state: FSMContext) -> None:
    m = _RE_INJ_TM.match(callback.data or "")
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
    tourn = "cl" if code == "cl" else "league"
    await state.update_data(injury_team=team, injury_lg=code, injury_tournament=tourn)
    await state.set_state(InjuryEnter.wait_line)
    if callback.message:
        await callback.message.answer(
            f"<b>{_league_title(code)}</b> · <b>{team}</b>\n\n"
            "Отправь строку травмы, например:\n<code>Симонс 4м</code>\n\n"
            "Можно несколько строк подряд; /cancel — выход.",
            parse_mode="HTML",
        )


@injury_router.message(InjuryEnter.wait_line, _TEXT_NOT_CMD)
async def on_injury_line(message: Message, state: FSMContext) -> None:
    from utils.player_discipline import (
        get_calendar_month,
        is_injury_line,
        try_apply_discipline_line,
    )

    data = await state.get_data()
    team = (data.get("injury_team") or "").strip()
    lc = (data.get("injury_lg") or "").strip()
    tourn = data.get("injury_tournament") or "league"
    if not team or not lc:
        await state.clear()
        await message.answer("Сессия сброшена. Начни с меню → травмы.")
        return

    raw = (message.text or "").strip()
    if not is_injury_line(raw):
        await message.answer(
            "Здесь только травмы: <code>имя Nм</code> или <code>имя Nм тип</code> "
            "(лат. <code>m</code> или кирил. <code>м</code>). "
            "Жёлтые и красные карточки — в статистике матча после счёта.",
            parse_mode="HTML",
        )
        return

    msched = get_calendar_month(None)
    msg, handled = await asyncio.to_thread(
        try_apply_discipline_line,
        raw,
        current_team=team,
        tournament=str(tourn),
        league_code=lc,
        schedule_month=msched,
    )
    if not handled:
        await message.answer(
            "Не удалось применить строку. Проверь имя в базе для этого клуба.",
            parse_mode="HTML",
        )
        return
    await message.answer(msg or "Готово.", parse_mode="HTML")


@injury_router.message(InjuryEnter.pick_lg, _TEXT_NOT_CMD)
@injury_router.message(InjuryEnter.pick_team, _TEXT_NOT_CMD)
async def on_injury_stray(message: Message) -> None:
    await message.answer("Сначала выбери лигу и клуб кнопками или /cancel.")
