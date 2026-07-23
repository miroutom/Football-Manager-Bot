# -*- coding: utf-8 -*-
"""Меню «История»: лига → выбор чемпионата, ЛЧ, личные награды, клубы — картинки."""
from __future__ import annotations

import asyncio
import logging

from aiogram import F, Router
from aiogram.types import BufferedInputFile, CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup

from bot.history_render import render_award_history_png, render_cl_history_png, render_league_history_png
from bot.services import LEAGUE_LABELS, teams_ordered_for_goalscorers
from bot.team_history_render import (
    render_club_dossier_png,
    render_league_titles_chart_png,
    render_power_ranking_png,
    render_prestige_breakdown_png,
)

logger = logging.getLogger(__name__)

history_router = Router()

_AWARD_CAPTION = {
    "golden_ball": "Золотой мяч",
    "golden_boot": "Золотая бутса",
    "golden_glove": "Золотая перчатка",
    "golden_boy": "Golden Boy",
}


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
        [
            InlineKeyboardButton(text="🏟 Клубы", callback_data="hist:teams"),
        ],
    ]
    return InlineKeyboardMarkup(inline_keyboard=rows)


def history_teams_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="💪 Рейтинг силы", callback_data="hist:t:power"
                ),
            ],
            [
                InlineKeyboardButton(
                    text="📊 Из чего престиж", callback_data="hist:t:break"
                ),
            ],
            [
                InlineKeyboardButton(
                    text="🏆 Чемпионства (вес лиг)", callback_data="hist:t:titles"
                ),
            ],
            [
                InlineKeyboardButton(
                    text="📁 Досье клуба", callback_data="hist:t:club"
                ),
            ],
            [InlineKeyboardButton(text="« Назад", callback_data="hist:back")],
        ]
    )


def history_league_choice_kb(*, for_club: bool = False) -> InlineKeyboardMarkup:
    prefix = "hist:tcl:" if for_club else "hist:l:"
    back = "hist:teams" if for_club else "hist:back"
    buttons: list[InlineKeyboardButton] = []
    for code, label in LEAGUE_LABELS:
        if code == "cl":
            continue
        buttons.append(InlineKeyboardButton(text=label, callback_data=f"{prefix}{code}"))
    rows = [buttons[i : i + 2] for i in range(0, len(buttons), 2)]
    rows.append([InlineKeyboardButton(text="« Назад", callback_data=back)])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def history_club_pick_kb(league_code: str) -> InlineKeyboardMarkup:
    teams = teams_ordered_for_goalscorers(league_code)
    rows: list[list[InlineKeyboardButton]] = []
    row: list[InlineKeyboardButton] = []
    for i, name in enumerate(teams):
        # callback length limit — short index
        row.append(
            InlineKeyboardButton(
                text=name, callback_data=f"hist:tc:{league_code}:{i}"
            )
        )
        if len(row) == 2:
            rows.append(row)
            row = []
    if row:
        rows.append(row)
    rows.append(
        [InlineKeyboardButton(text="« Лиги", callback_data="hist:t:club")]
    )
    return InlineKeyboardMarkup(inline_keyboard=rows)


async def _send_png(
    callback: CallbackQuery,
    *,
    png: bytes,
    filename: str,
    caption: str,
) -> None:
    if not callback.message:
        return
    await callback.message.answer_photo(
        photo=BufferedInputFile(png, filename=filename),
        caption=caption,
        parse_mode="HTML",
    )


@history_router.callback_query(F.data == "menu:history")
async def cb_menu_history(callback: CallbackQuery) -> None:
    await callback.answer()
    if not callback.message:
        return
    await callback.message.answer(
        "<b>История</b>\n\n"
        "Хронология по <b>сезонам</b> (номер сезона — как в <code>db/season_state.json</code>). "
        "Чемпионы лиг и ЛЧ после «Завершить сезон» подставляются из таблиц автоматически. "
        "Личные награды и фото — в <code>data/season_history.json</code>.\n\n"
        "Раздел <b>Клубы</b> — рейтинг силы (с весом лиг и ЛЧ), графики и досье с легендами.",
        reply_markup=history_root_kb(),
        parse_mode="HTML",
    )


@history_router.callback_query(F.data == "hist:back")
async def cb_hist_back(callback: CallbackQuery) -> None:
    await callback.answer()
    if not callback.message:
        return
    await callback.message.edit_reply_markup(reply_markup=history_root_kb())


@history_router.callback_query(F.data == "hist:teams")
async def cb_hist_teams(callback: CallbackQuery) -> None:
    await callback.answer()
    if not callback.message:
        return
    await callback.message.edit_reply_markup(reply_markup=history_teams_kb())


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
    await _send_png(
        callback,
        png=png,
        filename=f"history_{code}.png",
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
    await _send_png(
        callback,
        png=png,
        filename="history_cl.png",
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
    cap = _AWARD_CAPTION.get(kind, kind)
    await _send_png(
        callback,
        png=png,
        filename=f"history_{kind}.png",
        caption=f"<b>{cap}</b> — по сезонам",
    )


@history_router.callback_query(F.data == "hist:t:power")
async def cb_hist_power(callback: CallbackQuery) -> None:
    await callback.answer("Готовлю рейтинг…")
    if not callback.message:
        return
    try:
        png = await asyncio.to_thread(render_power_ranking_png, limit=15)
    except Exception as e:
        logger.exception("render_power_ranking")
        await callback.message.answer(f"Не удалось нарисовать рейтинг: {e}")
        return
    await _send_png(
        callback,
        png=png,
        filename="history_power.png",
        caption=(
            "<b>Рейтинг силы клубов</b>\n"
            "Учитывает вес лиги, титулы/путь в ЛЧ, состав и личные награды."
        ),
    )


@history_router.callback_query(F.data == "hist:t:break")
async def cb_hist_break(callback: CallbackQuery) -> None:
    await callback.answer("Готовлю график…")
    if not callback.message:
        return
    try:
        png = await asyncio.to_thread(render_prestige_breakdown_png, limit=10)
    except Exception as e:
        logger.exception("render_prestige_breakdown")
        await callback.message.answer(f"Не удалось нарисовать разрез: {e}")
        return
    await _send_png(
        callback,
        png=png,
        filename="history_prestige_break.png",
        caption="<b>Из чего складывается престиж</b> — стек-бар топ клубов",
    )


@history_router.callback_query(F.data == "hist:t:titles")
async def cb_hist_titles(callback: CallbackQuery) -> None:
    await callback.answer("Готовлю…")
    if not callback.message:
        return
    try:
        png = await asyncio.to_thread(render_league_titles_chart_png)
    except Exception as e:
        logger.exception("render_league_titles_chart")
        await callback.message.answer(f"Не удалось нарисовать чемпионства: {e}")
        return
    await _send_png(
        callback,
        png=png,
        filename="history_titles_weighted.png",
        caption="<b>Чемпионства лиг</b> — с весом (РПЛ дешевле топ-лиг)",
    )


@history_router.callback_query(F.data == "hist:t:club")
async def cb_hist_club_pick_league(callback: CallbackQuery) -> None:
    await callback.answer()
    if not callback.message:
        return
    await callback.message.edit_reply_markup(
        reply_markup=history_league_choice_kb(for_club=True)
    )


@history_router.callback_query(F.data.startswith("hist:tcl:"))
async def cb_hist_club_league(callback: CallbackQuery) -> None:
    parts = (callback.data or "").split(":")
    if len(parts) != 3:
        await callback.answer()
        return
    code = parts[2].strip()
    await callback.answer()
    if not callback.message:
        return
    try:
        kb = history_club_pick_kb(code)
    except Exception as e:
        await callback.message.answer(f"Не удалось список клубов: {e}")
        return
    await callback.message.edit_reply_markup(reply_markup=kb)


@history_router.callback_query(F.data.startswith("hist:tc:"))
async def cb_hist_club_dossier(callback: CallbackQuery) -> None:
    parts = (callback.data or "").split(":")
    if len(parts) != 4:
        await callback.answer()
        return
    code = parts[2].strip()
    try:
        idx = int(parts[3])
    except ValueError:
        await callback.answer()
        return
    try:
        teams = teams_ordered_for_goalscorers(code)
        team = teams[idx]
    except Exception:
        await callback.answer("Клуб не найден", show_alert=True)
        return
    await callback.answer(f"Досье: {team}…")
    if not callback.message:
        return
    try:
        png = await asyncio.to_thread(render_club_dossier_png, team)
    except Exception as e:
        logger.exception("render_club_dossier")
        await callback.message.answer(f"Не удалось нарисовать досье: {e}")
        return
    await _send_png(
        callback,
        png=png,
        filename=f"history_club_{code}_{idx}.png",
        caption=f"<b>{team}</b> — досье: трофеи, ЛЧ, легенды",
    )
