"""Правка overall пакетно: лига → клуб → строки «имя +2»."""
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
from bot.states import RatingEnter
from utils.player_overall_bumps import apply_overall_bumps_for_team

logger = logging.getLogger(__name__)

rating_router = Router()

_TEXT_NOT_CMD = F.text & ~F.text.startswith("/")

_RE_RT_LG = re.compile(r"^rt1:lg:([a-z0-9_]+)$")
_RE_RT_TM = re.compile(r"^rt1:tm:([a-z0-9_]+):(\d+)$")


def _league_title(code: str) -> str:
    return dict(LEAGUE_LABELS).get(code, code)


def _club_btn_label(text: str, max_chars: int = 40) -> str:
    text = (text or "").strip()
    if len(text) <= max_chars:
        return text
    return text[: max_chars - 1] + "…"


def _rating_league_kb() -> InlineKeyboardMarkup:
    row: list[InlineKeyboardButton] = []
    rows: list[list[InlineKeyboardButton]] = []
    for code, label in LEAGUE_LABELS:
        row.append(
            InlineKeyboardButton(
                text=label,
                callback_data=f"rt1:lg:{code}",
            )
        )
        if len(row) == 3:
            rows.append(row)
            row = []
    if row:
        rows.append(row)
    return InlineKeyboardMarkup(inline_keyboard=rows)


def _rating_teams_kb(league_code: str) -> InlineKeyboardMarkup:
    teams = teams_ordered_for_goalscorers(league_code)
    rows: list[list[InlineKeyboardButton]] = []
    row: list[InlineKeyboardButton] = []
    for idx, team in enumerate(teams):
        row.append(
            InlineKeyboardButton(
                text=_club_btn_label(team),
                callback_data=f"rt1:tm:{league_code}:{idx}",
            )
        )
        if len(row) == 2:
            rows.append(row)
            row = []
    if row:
        rows.append(row)
    return InlineKeyboardMarkup(inline_keyboard=rows)


@rating_router.callback_query(F.data == "menu:rating")
async def cb_menu_rating(callback: CallbackQuery, state: FSMContext) -> None:
    await callback.answer()
    if callback.message is None:
        return
    await state.clear()
    await callback.message.answer(
        "⭐ <b>Изменение рейтинга (overall)</b>\n\n"
        "Выбери лигу и клуб, затем пришли список строк, по одной на строку, например:\n"
        "<code>мартинез +2</code>\n"
        "<code>зоммер +5</code>\n"
        "<code>павар -3</code>\n"
        "В нац. БД и в БД ЛЧ (если игрок там есть) к соответствующим строкам "
        "прибавляется дельта; затем пересчитывается <code>common.db</code>.\n\n"
        "/cancel — отмена.",
        parse_mode="HTML",
        reply_markup=_rating_league_kb(),
    )


@rating_router.message(Command("rating_bump"))
async def cmd_rating_bump(message: Message, state: FSMContext) -> None:
    await state.clear()
    await message.answer(
        "⭐ <b>Изменение рейтинга</b> — выбери лигу (кнопки).\n/cancel — отмена.",
        parse_mode="HTML",
        reply_markup=_rating_league_kb(),
    )


@rating_router.callback_query(F.data.startswith("rt1:lg:"))
async def cb_rating_league(callback: CallbackQuery, state: FSMContext) -> None:
    m = _RE_RT_LG.match(callback.data or "")
    if not m:
        return
    code = m.group(1)
    await callback.answer()
    if callback.message is None:
        return
    try:
        kb = _rating_teams_kb(code)
    except Exception as e:
        logger.exception("rating_teams_kb")
        await callback.message.answer(f"Ошибка: {e}")
        return
    await state.update_data(rt_lg=code)
    await callback.message.answer(
        f"{_league_title(code)} — выберите клуб:",
        reply_markup=kb,
    )


@rating_router.callback_query(F.data.startswith("rt1:tm:"))
async def cb_rating_team(callback: CallbackQuery, state: FSMContext) -> None:
    m = _RE_RT_TM.match(callback.data or "")
    if not m:
        return
    code, idx_s = m.group(1), m.group(2)
    try:
        idx = int(idx_s)
    except ValueError:
        return
    await callback.answer()
    if callback.message is None:
        return
    try:
        teams = teams_ordered_for_goalscorers(code)
        team = teams[idx]
    except (IndexError, Exception) as e:
        await callback.message.answer(f"Клуб: ошибка: {e}")
        return
    await state.update_data(rt_lg=code, rt_team=team)
    await state.set_state(RatingEnter.wait_lines)
    await callback.message.answer(
        f"<b>{_league_title(code)}</b> · {team}\n\n"
        "Введи список (несколько строк), формат: <code>фамилия +2</code> или <code>имя -3</code>.\n"
        "/cancel — отмена.",
        parse_mode="HTML",
    )


@rating_router.message(RatingEnter.wait_lines, _TEXT_NOT_CMD)
async def on_rating_lines(message: Message, state: FSMContext) -> None:
    data = await state.get_data()
    team = (data.get("rt_team") or "").strip()
    if not team:
        await state.clear()
        await message.answer("Сброс. Открой снова из меню «Рейтинг».")
        return
    try:
        r = await asyncio.to_thread(apply_overall_bumps_for_team, team, message.text or "")
    except ValueError as e:
        await message.answer(str(e))
        return
    except Exception as e:
        logger.exception("apply_overall_bumps")
        await message.answer(f"Ошибка: {e}")
        return
    await state.clear()
    lines: list[str] = []
    if r.ok:
        lines.append("✅ Обновлено:")
        lines.extend(f"  · {x}" for x in r.ok)
    if r.errors:
        lines.append("⚠️ Проблемы:")
        lines.extend(f"  · {x}" for x in r.errors)
    if not lines:
        lines.append("Пусто — нечего применить.")
    await message.answer("\n".join(lines))
