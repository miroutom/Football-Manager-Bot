# -*- coding: utf-8 -*-
"""Меню «Стата по позициям» — нап / полузащ / защ / вратари."""
from __future__ import annotations

import asyncio
import logging

from aiogram import F, Router
from aiogram.types import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup

from utils.stats_by_position import GROUP_META, format_group_stats

logger = logging.getLogger(__name__)

stats_pos_router = Router()


def _scope_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="📍 Текущий сезон",
                    callback_data="stats_pos:scope:cur",
                ),
                InlineKeyboardButton(
                    text="📚 За все время",
                    callback_data="stats_pos:scope:life",
                ),
            ],
            [
                InlineKeyboardButton(text="« Меню", callback_data="menu:stats_pos"),
            ],
        ]
    )


def _group_keyboard(scope: str) -> InlineKeyboardMarkup:
    rows: list[list[InlineKeyboardButton]] = [
        [
            InlineKeyboardButton(
                text="⚽ Нападающие",
                callback_data=f"stats_pos:run:{scope}:fwd",
            ),
            InlineKeyboardButton(
                text="🧩 Полузащитники",
                callback_data=f"stats_pos:run:{scope}:mid",
            ),
        ],
        [
            InlineKeyboardButton(
                text="🛡 Защитники",
                callback_data=f"stats_pos:run:{scope}:def",
            ),
            InlineKeyboardButton(
                text="🧤 Вратари",
                callback_data=f"stats_pos:run:{scope}:gk",
            ),
        ],
        [
            InlineKeyboardButton(
                text="◀️ Период",
                callback_data="menu:stats_pos",
            ),
        ],
    ]
    return InlineKeyboardMarkup(inline_keyboard=rows)


def _scope_title(scope: str) -> str:
    return "за все время" if scope == "life" else "текущий сезон"


@stats_pos_router.callback_query(F.data == "menu:stats_pos")
async def cb_stats_pos_menu(callback: CallbackQuery) -> None:
    await callback.answer()
    if not callback.message:
        return
    await callback.message.answer(
        "📊 <b>Стата по позициям</b>\n"
        "Лига и ЛЧ вместе. Сначала выбери период, затем группу позиций.",
        parse_mode="HTML",
        reply_markup=_scope_keyboard(),
    )


@stats_pos_router.callback_query(F.data.startswith("stats_pos:scope:"))
async def cb_stats_pos_scope(callback: CallbackQuery) -> None:
    scope = callback.data.split(":")[-1]
    if scope not in ("cur", "life"):
        await callback.answer()
        return
    await callback.answer()
    if not callback.message:
        return
    await callback.message.answer(
        f"📊 <b>Стата по позициям</b> · {_scope_title(scope)}\n"
        "Выбери группу:",
        parse_mode="HTML",
        reply_markup=_group_keyboard(scope),
    )


@stats_pos_router.callback_query(F.data.startswith("stats_pos:run:"))
async def cb_stats_pos_run(callback: CallbackQuery) -> None:
    parts = callback.data.split(":")
    if len(parts) != 4:
        await callback.answer()
        return
    scope, group = parts[2], parts[3]
    if scope not in ("cur", "life") or group not in GROUP_META:
        await callback.answer("Неверный выбор.", show_alert=True)
        return
    await callback.answer("Считаю…")
    if not callback.message:
        return
    try:
        from bot.handlers import answer_report_photos

        text = await asyncio.to_thread(format_group_stats, scope, group)
        meta = GROUP_META[group]
        await answer_report_photos(
            callback.message,
            text,
            f"Стата · {meta['title']} · {_scope_title(scope)}",
        )
    except Exception as e:
        logger.exception("stats_by_position")
        await callback.message.answer(f"Ошибка: {e}")
