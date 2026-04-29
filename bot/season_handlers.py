"""Кнопка «Завершить сезон»: трофеи, архив БД, новый сезон в db/season_m/."""
from __future__ import annotations

import asyncio
import json
import logging

from aiogram import F, Router
from aiogram.types import (
    CallbackQuery,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    Message,
)

logger = logging.getLogger(__name__)

season_router = Router()


def _confirm_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="✅ Да, завершить сезон",
                    callback_data="season:finalize:yes",
                ),
                InlineKeyboardButton(
                    text="Отмена",
                    callback_data="season:finalize:no",
                ),
            ],
        ]
    )


@season_router.callback_query(F.data == "menu:end_season")
async def cb_season_menu(callback: CallbackQuery) -> None:
    from bot.season_tools import can_finish_season

    if not can_finish_season():
        await callback.answer(
            "Сезон можно завершить только когда в календаре не осталось несыгранных матчей.",
            show_alert=True,
        )
        return
    await callback.answer()
    if not callback.message:
        return
    n = 1
    try:
        from utils.season_paths import get_state

        n = int(get_state().get("active_season") or 1)
    except Exception:
        pass
    await callback.message.answer(
        "⏹ <b>Завершение сезона</b>\n\n"
        f"Сейчас учитывается сезон <b>{n}</b> (см. <code>db/season_state.json</code> в режиме per_season).\n"
        "Будет:\n"
        "• <b>Трофеи</b> по 1-му месту в каждой нац. лиге и в группе ЛЧ: +1 к <code>trophies</code> в соответствующей БД;\n"
        "• <b>common</b> — сумма (общая) пересчитается;\n"
        "• текущие БД и pickle уйдут в <code>db/season_…/archive</code> (копия), новый сезон — в следующую папку с чистой статой.\n\n"
        "<b>Операция длинная и необратимая (бэкап сделай вручную при необходимости).</b>\n"
        "Продолжить?",
        parse_mode="HTML",
        reply_markup=_confirm_kb(),
    )


@season_router.callback_query(F.data == "season:finalize:no")
async def cb_season_no(callback: CallbackQuery) -> None:
    await callback.answer("Отменено")
    if callback.message:
        await callback.message.answer("Завершение сезона отменено.")


@season_router.callback_query(F.data == "season:finalize:yes")
async def cb_season_yes(callback: CallbackQuery) -> None:
    from bot.season_tools import can_finish_season

    if not can_finish_season():
        await callback.answer(
            "Календарь ещё не закрыт — завершение отменено.", show_alert=True
        )
        return
    await callback.answer("Считаю…")
    if not callback.message:
        return
    from utils.season_end import finalize_season

    try:
        log = await asyncio.to_thread(finalize_season)
    except Exception as e:
        logger.exception("finalize_season")
        await callback.message.answer(f"Ошибка: {e}")
        return
    try:
        txt = json.dumps(log, ensure_ascii=False, indent=2)[:3500]
    except Exception:
        txt = str(log)[:3500]
    await callback.message.answer(
        f"✅ <b>Сезон завершён</b>.\n\n<pre>{txt}</pre>", parse_mode="HTML"
    )
