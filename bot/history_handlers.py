# -*- coding: utf-8 -*-
"""Меню «История»: лига → выбор чемпионата, ЛЧ, личные награды — картинка в стиле состава."""
from __future__ import annotations

import asyncio
import logging

from aiogram import F, Router
from aiogram.types import BufferedInputFile, CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup

from bot.history_render import render_award_history_png, render_cl_history_png, render_league_history_png
from bot.services import LEAGUE_LABELS

logger = logging.getLogger(__name__)

history_router = Router()


def history_root_kb() -> InlineKeyboardMarkup:
    rows: list[list[InlineKeyboardButton]] = [
        [
            InlineKeyboardButton(text="🏠 Лига", callback_data="hist:pick_league"),
            InlineKeyboardButton(text="⭐ ЛЧ", callback_data="hist:cl"),
        ],
        [
            InlineKeyboardButton(text="⚽ ЗМ", callback_data="hist:a:golden_ball"),
            InlineKeyboardButton(text="👟 Бутса", callback_data="hist:a:golden_boot"),
        ],
        [
            InlineKeyboardButton(text="🧤 Перчатка", callback_data="hist:a:golden_glove"),
            InlineKeyboardButton(text="🌟 Golden Boy", callback_data="hist:a:golden_boy"),
        ],
    ]
    return InlineKeyboardMarkup(inline_keyboard=rows)


def history_league_choice_kb() -> InlineKeyboardMarkup:
    buttons: list[InlineKeyboardButton] = []
    for code, label in LEAGUE_LABELS:
        if code == "cl":
            continue
        buttons.append(
            InlineKeyboardButton(text=label, callback_data=f"hist:l:{code}")
        )
    rows = [buttons[i : i + 2] for i in range(0, len(buttons), 2)]
    rows.append([InlineKeyboardButton(text="« Назад", callback_data="hist:back")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


@history_router.callback_query(F.data == "menu:history")
async def cb_menu_history(callback: CallbackQuery) -> None:
    await callback.answer()
    if not callback.message:
        return
    await callback.message.answer(
        "<b>История</b>\n\n"
        "Хронология по <b>сезонам</b> (номер сезона — как в <code>db/season_state.json</code>). "
        "Чемпионы лиг и ЛЧ после «Завершить сезон» подставляются из таблиц автоматически. "
        "Личные награды и фото — в <code>data/season_history.json</code> и "
        "<code>assets/history/photos/</code> (см. <code>scripts/fetch_history_assets.py</code>).",
        reply_markup=history_root_kb(),
    )


@history_router.callback_query(F.data == "hist:back")
async def cb_hist_back(callback: CallbackQuery) -> None:
    await callback.answer()
    if not callback.message:
        return
    await callback.message.edit_reply_markup(reply_markup=history_root_kb())


@history_router.callback_query(F.data == "hist:pick_league")
async def cb_hist_pick_league(callback: CallbackQuery) -> None:
    await callback.answer()
    if not callback.message:
        return
    await callback.message.edit_reply_markup(reply_markup=history_league_choice_kb())


@history_router.callback_query(F.data.startswith("hist:l:"))
async def cb_hist_league(callback: CallbackQuery) -> None:
    parts = (callback.data or "").split(":")
    if len(parts) != 3:
        await callback.answer()
        return
    code = parts[2].strip()
    labels = dict(LEAGUE_LABELS)
    title = labels.get(code, code)
    await callback.answer("Готовлю…")
    if not callback.message:
        return
    try:
        png = await asyncio.to_thread(render_league_history_png, code, title)
    except Exception as e:
        logger.exception("render_league_history")
        await callback.message.answer(f"Не удалось нарисовать историю: {e}")
        return
    await callback.message.answer_photo(
        photo=BufferedInputFile(png, filename=f"history_{code}.png"),
        caption=f"<b>{title}</b> — чемпионы по сезонам",
    )


@history_router.callback_query(F.data == "hist:cl")
async def cb_hist_cl(callback: CallbackQuery) -> None:
    await callback.answer("Готовлю…")
    if not callback.message:
        return
    try:
        png = await asyncio.to_thread(render_cl_history_png)
    except Exception as e:
        logger.exception("render_cl_history")
        await callback.message.answer(f"Не удалось нарисовать историю ЛЧ: {e}")
        return
    await callback.message.answer_photo(
        photo=BufferedInputFile(png, filename="history_cl.png"),
        caption="<b>Лига чемпионов</b> — победители по сезонам",
    )


@history_router.callback_query(F.data.startswith("hist:a:"))
async def cb_hist_award(callback: CallbackQuery) -> None:
    parts = (callback.data or "").split(":")
    if len(parts) != 3:
        await callback.answer()
        return
    kind = parts[2].strip()
    await callback.answer("Готовлю…")
    if not callback.message:
        return
    try:
        png = await asyncio.to_thread(render_award_history_png, kind)
    except Exception as e:
        logger.exception("render_award_history")
        await callback.message.answer(f"Не удалось нарисовать награду: {e}")
        return
    cap = {
        "golden_ball": "Золотой мяч",
        "golden_boot": "Золотая бутса",
        "golden_glove": "Золотая перчатка",
        "golden_boy": "Golden Boy",
    }.get(kind, kind)
    await callback.message.answer_photo(
        photo=BufferedInputFile(png, filename=f"history_{kind}.png"),
        caption=f"<b>{cap}</b> — по сезонам",
    )
