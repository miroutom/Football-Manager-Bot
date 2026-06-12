# -*- coding: utf-8 -*-
"""Меню «Игроки по позициям» — текущий сезон, сортировка по рейтингу."""
from __future__ import annotations

import asyncio
import logging

from aiogram import F, Router
from aiogram.types import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup

from utils.players_by_position import format_position_list, positions_with_players
from utils.season_paths import get_active_season

logger = logging.getLogger(__name__)

players_pos_router = Router()

_PAGE_SIZE = 14


def _positions_kb(page: int = 0) -> InlineKeyboardMarkup:
    positions = positions_with_players()
    if not positions:
        return InlineKeyboardMarkup(
            inline_keyboard=[
                [InlineKeyboardButton(text="« Меню", callback_data="menu:players_pos")]
            ]
        )
    start = page * _PAGE_SIZE
    chunk = positions[start : start + _PAGE_SIZE]
    rows: list[list[InlineKeyboardButton]] = []
    row: list[InlineKeyboardButton] = []
    for pos in chunk:
        row.append(InlineKeyboardButton(text=pos, callback_data=f"ppos:pos:{pos}"))
        if len(row) == 2:
            rows.append(row)
            row = []
    if row:
        rows.append(row)
    nav: list[InlineKeyboardButton] = []
    if start > 0:
        nav.append(
            InlineKeyboardButton(text="« Назад", callback_data=f"ppos:page:{page - 1}")
        )
    if start + _PAGE_SIZE < len(positions):
        nav.append(
            InlineKeyboardButton(text="Вперёд »", callback_data=f"ppos:page:{page + 1}")
        )
    if nav:
        rows.append(nav)
    return InlineKeyboardMarkup(inline_keyboard=rows)


@players_pos_router.callback_query(F.data == "menu:players_pos")
async def cb_players_pos_menu(callback: CallbackQuery) -> None:
    await callback.answer()
    if not callback.message:
        return
    n = get_active_season()
    await callback.message.answer(
        f"👤 <b>Игроки по позициям</b> · сезон <b>{n}</b>\n"
        "Лига и ЛЧ вместе, сортировка по рейтингу.\n"
        "Формат: Фамилия Команда Рейтинг Менеджер (roma / lika).\n"
        "Выбери позицию:",
        parse_mode="HTML",
        reply_markup=_positions_kb(0),
    )


@players_pos_router.callback_query(F.data.startswith("ppos:page:"))
async def cb_players_pos_page(callback: CallbackQuery) -> None:
    try:
        page = int(callback.data.split(":")[-1])
    except ValueError:
        await callback.answer("Ошибка страницы.", show_alert=True)
        return
    await callback.answer()
    if not callback.message:
        return
    n = get_active_season()
    await callback.message.answer(
        f"👤 <b>Игроки по позициям</b> · сезон <b>{n}</b>\nВыбери позицию:",
        parse_mode="HTML",
        reply_markup=_positions_kb(max(0, page)),
    )


@players_pos_router.callback_query(F.data.startswith("ppos:pos:"))
async def cb_players_pos_show(callback: CallbackQuery) -> None:
    pos = callback.data.split(":", 2)[-1]
    await callback.answer("Считаю…")
    if not callback.message:
        return
    try:
        from bot.handlers import answer_report_photos

        text = await asyncio.to_thread(format_position_list, pos)
        await answer_report_photos(
            callback.message,
            text,
            f"Игроки · {pos} · сезон {get_active_season()}",
        )
    except Exception as e:
        logger.exception("players_by_position")
        await callback.message.answer(f"Ошибка: {e}")
