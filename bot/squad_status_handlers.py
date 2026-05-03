"""Правка заявки start/bench/reserve через Telegram (аналог правки overall)."""
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
from bot.states import SquadStatusEnter
from utils.player_status_lines import apply_player_status_lines_for_team

logger = logging.getLogger(__name__)

squad_status_router = Router()

_TEXT_NOT_CMD = F.text & ~F.text.startswith("/")

_RE_ST_LG = re.compile(r"^st1:lg:([a-z0-9_]+)$")
_RE_ST_TM = re.compile(r"^st1:tm:([a-z0-9_]+):(\d+)$")


def _league_title(code: str) -> str:
    return dict(LEAGUE_LABELS).get(code, code)


def _club_btn_label(text: str, max_chars: int = 40) -> str:
    text = (text or "").strip()
    if len(text) <= max_chars:
        return text
    return text[: max_chars - 1] + "…"


def _squad_league_kb() -> InlineKeyboardMarkup:
    row: list[InlineKeyboardButton] = []
    rows: list[list[InlineKeyboardButton]] = []
    for code, label in LEAGUE_LABELS:
        row.append(
            InlineKeyboardButton(
                text=label,
                callback_data=f"st1:lg:{code}",
            )
        )
        if len(row) == 3:
            rows.append(row)
            row = []
    if row:
        rows.append(row)
    return InlineKeyboardMarkup(inline_keyboard=rows)


def _squad_teams_kb(league_code: str) -> InlineKeyboardMarkup:
    teams = teams_ordered_for_goalscorers(league_code)
    rows: list[list[InlineKeyboardButton]] = []
    row: list[InlineKeyboardButton] = []
    for idx, team in enumerate(teams):
        row.append(
            InlineKeyboardButton(
                text=_club_btn_label(team),
                callback_data=f"st1:tm:{league_code}:{idx}",
            )
        )
        if len(row) == 2:
            rows.append(row)
            row = []
    if row:
        rows.append(row)
    return InlineKeyboardMarkup(inline_keyboard=rows)


@squad_status_router.callback_query(F.data == "menu:squad_status")
async def cb_menu_squad_status(callback: CallbackQuery, state: FSMContext) -> None:
    await callback.answer()
    if callback.message is None:
        return
    await state.clear()
    await callback.message.answer(
        "📋 <b>Заявка: старт / скамейка / резерв</b>\n\n"
        "Только меняет статус у <b>перечисленных</b> игроков. Кого нет в списке — "
        "<b>не трогает</b> (не снимает с состава и не в СА).\n\n"
        "Если нужно «в заявке только эти N человек, остальных в свободные агенты» — "
        "это <b>«Изменить игроков» → «В состав / из состава» → Полная заявка (текстом)»</b>, "
        "там у каждой строки должны быть имя и позиция.\n\n"
        "Здесь: выбери лигу и клуб, затем строки, например:\n"
        "<code>игиль start</code>\n"
        "<code>силас пфа start</code> — если нужна позиция для поиска\n"
        "<code>мартинез bench</code>\n"
        "<code>юг reserve</code>\n"
        "Статусы <code>start</code>, <code>bench</code>, <code>reserve</code> — латиницей. "
        "Нац. лига и ЛЧ при необходимости, затем common и накопительные БД.\n\n"
        "/cancel — отмена.",
        parse_mode="HTML",
        reply_markup=_squad_league_kb(),
    )


@squad_status_router.message(Command("squad_status"))
async def cmd_squad_status(message: Message, state: FSMContext) -> None:
    await state.clear()
    await message.answer(
        "📋 <b>Заявка</b> — выбери лигу (кнопки).\n/cancel — отмена.",
        parse_mode="HTML",
        reply_markup=_squad_league_kb(),
    )


@squad_status_router.callback_query(F.data.startswith("st1:lg:"))
async def cb_squad_league(callback: CallbackQuery, state: FSMContext) -> None:
    m = _RE_ST_LG.match(callback.data or "")
    if not m:
        return
    code = m.group(1)
    await callback.answer()
    if callback.message is None:
        return
    try:
        kb = _squad_teams_kb(code)
    except Exception as e:
        logger.exception("squad_teams_kb")
        await callback.message.answer(f"Ошибка: {e}")
        return
    await state.update_data(sq_lg=code)
    await callback.message.answer(
        f"{_league_title(code)} — выберите клуб:",
        reply_markup=kb,
    )


@squad_status_router.callback_query(F.data.startswith("st1:tm:"))
async def cb_squad_team(callback: CallbackQuery, state: FSMContext) -> None:
    m = _RE_ST_TM.match(callback.data or "")
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
    await state.update_data(sq_lg=code, sq_team=team)
    await state.set_state(SquadStatusEnter.wait_lines)
    await callback.message.answer(
        f"<b>{_league_title(code)}</b> · {team}\n\n"
        "Строки: <code>фамилия start</code>, при необходимости "
        "<code>имя позиция bench</code> (позиция как в БД: ЦП, ПФА, …). "
        "Кого нет в списке — состав не меняется.\n"
        "/cancel — отмена.",
        parse_mode="HTML",
    )


@squad_status_router.message(SquadStatusEnter.wait_lines, _TEXT_NOT_CMD)
async def on_squad_status_lines(message: Message, state: FSMContext) -> None:
    data = await state.get_data()
    team = (data.get("sq_team") or "").strip()
    if not team:
        await state.clear()
        await message.answer("Сброс. Открой снова из меню «Заявка».")
        return
    try:
        r = await asyncio.to_thread(
            apply_player_status_lines_for_team, team, message.text or ""
        )
    except ValueError as e:
        await message.answer(str(e))
        return
    except Exception as e:
        logger.exception("apply_player_status_lines")
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
