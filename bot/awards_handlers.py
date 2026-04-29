# -*- coding: utf-8 -*-
"""Награды сезона: ЗМ, золотая перчатка, бутса, Golden Boy."""
from __future__ import annotations

import asyncio
import logging

from aiogram import F, Router
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.types import (
    CallbackQuery,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    Message,
)

from bot.award_apply import KIND_TITLES, apply_trophy, save_trophy_and_rebuild_common
from bot.services import LEAGUE_LABELS, teams_ordered_for_goalscorers, tournament_db_for_league
from bot.states import AwardEnter
from utils.utils import get_session

logger = logging.getLogger(__name__)

awards_router = Router()
_TEXT_NOT_CMD = F.text & ~F.text.startswith("/")


def _league_row_kb() -> InlineKeyboardMarkup:
    rows: list[list[InlineKeyboardButton]] = []
    row: list[InlineKeyboardButton] = []
    for code, label in LEAGUE_LABELS:
        row.append(InlineKeyboardButton(text=label, callback_data=f"aw:lg:{code}"))
        if len(row) == 3:
            rows.append(row)
            row = []
    if row:
        rows.append(row)
    return InlineKeyboardMarkup(inline_keyboard=rows)


def _kind_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="🌟 Золотой мяч (ЗМ)",
                    callback_data="aw:k:ball",
                ),
            ],
            [
                InlineKeyboardButton(
                    text="🧤 Золотая перчатка",
                    callback_data="aw:k:glove",
                ),
            ],
            [
                InlineKeyboardButton(
                    text="👟 Золотая бутса",
                    callback_data="aw:k:boot",
                ),
            ],
            [
                InlineKeyboardButton(
                    text="⭐ Golden Boy",
                    callback_data="aw:k:boy",
                ),
            ],
        ]
    )


def _team_kb(league_code: str) -> InlineKeyboardMarkup:
    teams = teams_ordered_for_goalscorers(league_code)
    rows: list[list[InlineKeyboardButton]] = []
    for i, tname in enumerate(teams):
        label = tname if len(tname) <= 30 else tname[:27] + "…"
        rows.append(
            [InlineKeyboardButton(text=label, callback_data=f"aw:tm:{league_code}:{i}")]
        )
    return InlineKeyboardMarkup(inline_keyboard=rows)


@awards_router.callback_query(F.data == "menu:awards")
async def cb_menu_awards(callback: CallbackQuery, state: FSMContext) -> None:
    await callback.answer()
    await state.clear()
    await callback.message.answer(
        "🏆 <b>Награды сезона</b>\n\n"
        "Выбери вид награды — далее лигу, клуб, затем введи "
        "имя игрока (как в базе, без позиции).\n"
        "/cancel — отмена.",
        reply_markup=_kind_kb(),
        parse_mode="HTML",
    )


@awards_router.callback_query(F.data.startswith("aw:k:"))
async def cb_award_kind(callback: CallbackQuery, state: FSMContext) -> None:
    k = (callback.data or "").split(":", 2)[2]
    if k not in KIND_TITLES:
        await callback.answer("Неверный вид", show_alert=True)
        return
    await callback.answer()
    await state.update_data(aw_kind=k, aw_lg=None, aw_team=None)
    await callback.message.answer(
        f"Награда: <b>{KIND_TITLES[k]}</b>\n\n"
        f"Теперь выбери <b>лигу</b>:",
        reply_markup=_league_row_kb(),
        parse_mode="HTML",
    )


@awards_router.callback_query(F.data.startswith("aw:lg:"))
async def cb_award_league(callback: CallbackQuery, state: FSMContext) -> None:
    parts = (callback.data or "").split(":")
    if len(parts) < 3:
        await callback.answer()
        return
    code = parts[2]
    title = dict(LEAGUE_LABELS).get(code, code)
    await callback.answer()
    await state.update_data(aw_lg=code)
    n_teams = len(teams_ordered_for_goalscorers(code))
    if n_teams == 0:
        await callback.message.answer(f"В лиге «{title}» нет списка клубов.")
        return
    await callback.message.answer(
        f"Лига: <b>{title}</b>\n\n"
        f"Выбери <b>клуб</b> игрока:",
        reply_markup=_team_kb(code),
        parse_mode="HTML",
    )


@awards_router.callback_query(F.data.startswith("aw:tm:"))
async def cb_award_team(callback: CallbackQuery, state: FSMContext) -> None:
    parts = (callback.data or "").split(":")
    if len(parts) < 4:
        await callback.answer()
        return
    code = parts[2]
    try:
        idx = int(parts[3])
    except ValueError:
        await callback.answer("Ошибка кнопки", show_alert=True)
        return
    teams = teams_ordered_for_goalscorers(code)
    if idx < 0 or idx >= len(teams):
        await callback.answer("Клуба нет в списке", show_alert=True)
        return
    team = teams[idx]
    data = await state.get_data()
    if not data.get("aw_kind"):
        await callback.answer("Сначала выбери награду.", show_alert=True)
        return
    await callback.answer()
    await state.update_data(aw_team=team, aw_lg=code)
    t_kind = KIND_TITLES.get(data["aw_kind"], data["aw_kind"])
    await state.set_state(AwardEnter.wait_name)
    lg = dict(LEAGUE_LABELS).get(code, code)
    await callback.message.answer(
        f"Награда: <b>{t_kind}</b>\n"
        f"Лига: <b>{lg}</b>\n"
        f"Клуб: <b>{team}</b>\n\n"
        f"Введи <b>имя</b> игрока (как в БД, например «Смолов» или «Де Брюйне»):\n"
        f"/cancel — отмена.",
        parse_mode="HTML",
    )


@awards_router.message(AwardEnter.wait_name, _TEXT_NOT_CMD)
async def on_award_name(message: Message, state: FSMContext) -> None:
    raw = (message.text or "").strip()
    if len(raw) < 2:
        await message.answer("Слишком коротко. Введи имя или /cancel")
        return
    data = await state.get_data()
    kind = data.get("aw_kind")
    team = data.get("aw_team")
    lg = data.get("aw_lg")
    if not kind or not team or not lg:
        await state.clear()
        await message.answer("Сессия сброшена. Начни с кнопки «Награды».")
        return
    tdb = tournament_db_for_league(lg)
    session = get_session(tdb)

    def run() -> tuple[bool, str]:
        ok, msg = apply_trophy(session, team, raw, kind)
        if ok:
            try:
                save_trophy_and_rebuild_common()
            except Exception as e:
                logger.exception("rebuild common after award")
                return (
                    True,
                    msg
                    + f"\n\n⚠️ <code>common</code> не пересобран: {e!s}",
                )
        return ok, msg

    ok, msg = await asyncio.to_thread(run)
    await state.clear()
    await message.answer(msg, parse_mode="HTML")


@awards_router.message(Command("awards"))
async def cmd_awards(message: Message, state: FSMContext) -> None:
    await state.clear()
    await message.answer(
        "🏆 <b>Награды сезона</b>\n\n"
        "Выбери вид награды (кнопки ниже)…\n"
        "/cancel — отмена.",
        reply_markup=_kind_kb(),
        parse_mode="HTML",
    )
