# -*- coding: utf-8 -*-
"""Меню «Травмы»: ввод травмы и сводка травм + дисквалы + накопление жк."""
from __future__ import annotations

import asyncio
import logging
import re
from functools import partial

from aiogram import F, Router
from aiogram.fsm.context import FSMContext
from aiogram.types import (
    CallbackQuery,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    Message,
)

from bot.image_render import render_monospace_png_bytes
from bot.services import LEAGUE_LABELS, teams_ordered_for_goalscorers
from bot.states import InjuryEnter

logger = logging.getLogger(__name__)

injury_router = Router()

_TEXT_NOT_CMD = F.text & ~F.text.startswith("/")

_RE_INJ_LG = re.compile(r"^inj:lg:([a-z0-9_]+)$")
_RE_INJ_TM = re.compile(r"^inj:tm:([a-z0-9_]+):(\d+)$")
_RE_INJ_VIEW_S = re.compile(r"^inj:view:s:(\d+)$")


def _league_title(code: str) -> str:
    return dict(LEAGUE_LABELS).get(code, code)


def _club_btn(text: str, max_chars: int = 40) -> str:
    text = (text or "").strip()
    if len(text) <= max_chars:
        return text
    return text[: max_chars - 1] + "…"


def _injury_root_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="✏️ Ввод травмы",
                    callback_data="inj:root:enter",
                ),
            ],
            [
                InlineKeyboardButton(
                    text="👁 Всё · травмы · дисквалы · жк",
                    callback_data="inj:root:view",
                ),
            ],
            [
                InlineKeyboardButton(
                    text="📅 Травмы по сезону",
                    callback_data="inj:view:seasons",
                ),
            ],
            [
                InlineKeyboardButton(
                    text="📊 Чаще всего травмировались",
                    callback_data="inj:view:freq",
                ),
            ],
            [
                InlineKeyboardButton(
                    text="🛡 Ни разу не травмировались",
                    callback_data="inj:view:never",
                ),
            ],
        ]
    )


def _injury_season_kb(seasons: list[int]) -> InlineKeyboardMarkup:
    rows: list[list[InlineKeyboardButton]] = [
        [
            InlineKeyboardButton(
                text="← К травмам",
                callback_data="inj:back:root",
            )
        ]
    ]
    row: list[InlineKeyboardButton] = []
    for sn in seasons:
        row.append(
            InlineKeyboardButton(
                text=f"Сезон {sn}",
                callback_data=f"inj:view:s:{sn}",
            )
        )
        if len(row) == 3:
            rows.append(row)
            row = []
    if row:
        rows.append(row)
    return InlineKeyboardMarkup(inline_keyboard=rows)


def _injury_league_kb() -> InlineKeyboardMarkup:
    row: list[InlineKeyboardButton] = []
    rows: list[list[InlineKeyboardButton]] = [
        [
            InlineKeyboardButton(
                text="← К травмам",
                callback_data="inj:back:root",
            )
        ]
    ]
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
    rows: list[list[InlineKeyboardButton]] = [
        [
            InlineKeyboardButton(
                text="← К лигам",
                callback_data="inj:back:lg",
            )
        ]
    ]
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


async def _send_injury_root(message: Message, state: FSMContext) -> None:
    from utils.player_discipline import _MAX_INJURY_DURATION_MONTHS

    await state.clear()
    await message.answer(
        "🏥 <b>Травмы и дисциплина</b>\n\n"
        "«Ввод травмы» — лига и клуб, затем строка:\n"
        "<code>имя Nм</code> / <code>имя Nм тип</code> — с текущего месяца календаря;\n"
        "<code>имя с3 4м</code> — с 3-го месяца на 4 месяца.\n"
        f"Срок N — от 1 до <b>{_MAX_INJURY_DURATION_MONTHS}</b> мес. "
        "(если больше 10 — остаток переносится на следующий сезон).\n\n"
        "«Всё» — полная сводка; «по сезону» — только травмы выбранного сезона; "
        "«чаще всего» / «ни разу» — за все сезоны (с OVR).\n\n"
        "Начисление жк и кк — в статистике матча после счёта.",
        parse_mode="HTML",
        reply_markup=_injury_root_kb(),
    )


async def _send_png_report(
    message: Message,
    *,
    body: str,
    title: str,
    caption: str,
    filename_prefix: str,
) -> None:
    blobs = await asyncio.to_thread(
        partial(render_monospace_png_bytes, body, title=title),
    )
    if not blobs:
        await message.answer("Отчёт пуст.")
        return
    from bot.handlers import answer_png_pages

    await answer_png_pages(
        message,
        blobs,
        caption,
        filename_prefix=filename_prefix,
        parse_mode="HTML",
    )


@injury_router.callback_query(F.data == "menu:injury")
async def cb_menu_injury(callback: CallbackQuery, state: FSMContext) -> None:
    await callback.answer()
    if callback.message is None:
        return
    await _send_injury_root(callback.message, state)


@injury_router.callback_query(F.data == "inj:back:root")
async def cb_injury_back_root(callback: CallbackQuery, state: FSMContext) -> None:
    await callback.answer()
    if callback.message is None:
        return
    await _send_injury_root(callback.message, state)


@injury_router.callback_query(F.data == "inj:root:enter")
async def cb_injury_root_enter(callback: CallbackQuery, state: FSMContext) -> None:
    from utils.player_discipline import _MAX_INJURY_DURATION_MONTHS

    await callback.answer()
    if callback.message is None:
        return
    await state.clear()
    await state.set_state(InjuryEnter.pick_lg)
    await callback.message.answer(
        "✏️ <b>Ввод травмы</b>\n\n"
        "Выбери лигу и клуб, затем строку:\n"
        "<code>имя Nм</code> — с текущего месяца календаря на N месяцев;\n"
        "<code>имя сM Nм</code> — с месяца M на N месяцев.\n\n"
        f"N = 1…{_MAX_INJURY_DURATION_MONTHS}. Пример остатка длинной травмы: "
        "<code>Эдерсон 14м</code>.\n\n"
        "Новая травма — сразу к рейтингу: 1–2 мес. без изменений; 3–6 мес. −2; "
        "7 мес. −4; 8+ мес. −7.\n\n"
        "Примеры: <code>Брозович с3 1м</code>, <code>Симонс 4м колено</code>\n"
        "/cancel — отмена.",
        parse_mode="HTML",
        reply_markup=_injury_league_kb(),
    )


@injury_router.callback_query(F.data == "inj:back:lg")
async def cb_injury_back_lg(callback: CallbackQuery, state: FSMContext) -> None:
    await callback.answer()
    if callback.message is None:
        return
    await state.set_state(InjuryEnter.pick_lg)
    await callback.message.answer(
        "Выбери лигу:",
        reply_markup=_injury_league_kb(),
    )


@injury_router.callback_query(F.data == "inj:root:view")
async def cb_injury_root_view(callback: CallbackQuery, state: FSMContext) -> None:
    from utils.player_discipline import format_active_injuries_report_text

    await callback.answer("Готовлю…")
    if callback.message is None:
        return
    await state.clear()
    try:
        body = await asyncio.to_thread(format_active_injuries_report_text)
        await _send_png_report(
            callback.message,
            body=body,
            title="Травмы и дисциплина",
            caption="<b>Травмы и дисциплина</b>",
            filename_prefix="injuries",
        )
    except Exception as e:
        logger.exception("injury view report")
        await callback.message.answer(f"Не удалось собрать отчёт: {e}")


@injury_router.callback_query(F.data == "inj:view:seasons")
async def cb_injury_view_seasons(callback: CallbackQuery, state: FSMContext) -> None:
    from utils.player_discipline import list_injury_seasons

    await callback.answer()
    if callback.message is None:
        return
    await state.clear()
    seasons = await asyncio.to_thread(list_injury_seasons)
    if not seasons:
        await callback.message.answer(
            "В журнале травм пока нет сезонов.",
            reply_markup=_injury_root_kb(),
        )
        return
    await callback.message.answer(
        "📅 Выбери сезон — покажу только травмы, начавшиеся в нём:",
        reply_markup=_injury_season_kb(seasons),
    )


@injury_router.callback_query(F.data.regexp(_RE_INJ_VIEW_S))
async def cb_injury_view_season(callback: CallbackQuery, state: FSMContext) -> None:
    from utils.player_discipline import format_injuries_season_report_text

    m = _RE_INJ_VIEW_S.match(callback.data or "")
    if not m:
        await callback.answer()
        return
    sn = int(m.group(1))
    await callback.answer("Готовлю…")
    if callback.message is None:
        return
    await state.clear()
    try:
        body = await asyncio.to_thread(format_injuries_season_report_text, sn)
        await _send_png_report(
            callback.message,
            body=body,
            title=f"Травмы · сезон {sn}",
            caption=f"<b>Травмы · сезон {sn}</b>",
            filename_prefix=f"injuries_s{sn}",
        )
    except Exception as e:
        logger.exception("injury season report")
        await callback.message.answer(f"Не удалось собрать отчёт: {e}")


@injury_router.callback_query(F.data == "inj:view:freq")
async def cb_injury_view_freq(callback: CallbackQuery, state: FSMContext) -> None:
    from utils.player_discipline import format_injury_frequency_report_text

    await callback.answer("Готовлю…")
    if callback.message is None:
        return
    await state.clear()
    try:
        body = await asyncio.to_thread(format_injury_frequency_report_text)
        await _send_png_report(
            callback.message,
            body=body,
            title="Чаще всего травмировались",
            caption="<b>Чаще всего травмировались</b> · все сезоны",
            filename_prefix="injuries_freq",
        )
    except Exception as e:
        logger.exception("injury frequency report")
        await callback.message.answer(f"Не удалось собрать отчёт: {e}")


@injury_router.callback_query(F.data == "inj:view:never")
async def cb_injury_view_never(callback: CallbackQuery, state: FSMContext) -> None:
    from utils.player_discipline import format_never_injured_report_text

    await callback.answer("Готовлю…")
    if callback.message is None:
        return
    await state.clear()
    try:
        body = await asyncio.to_thread(format_never_injured_report_text)
        await _send_png_report(
            callback.message,
            body=body,
            title="Ни разу не травмировались",
            caption="<b>Ни разу не травмировались</b> · все сезоны · топ по матчам",
            filename_prefix="injuries_never",
        )
    except Exception as e:
        logger.exception("never injured report")
        await callback.message.answer(f"Не удалось собрать отчёт: {e}")


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
            "Отправь строку травмы, например:\n"
            "<code>Брозович с3 1м</code>, <code>Симонс 4м</code> "
            "или <code>Эдерсон 14м</code>\n\n"
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
            "Здесь только травмы: <code>имя Nм</code>, <code>имя сM Nм</code> или с типом. "
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
