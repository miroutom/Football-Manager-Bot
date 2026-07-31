"""Награды сезона: +1 в одной БД (сезонная награда не в двойном экземпляре), common — max(лига, лч). FSM: вид → лига → клуб → имя."""
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

from bot.award_apply import apply_trophy
from bot.services import LEAGUE_LABELS, teams_ordered_for_goalscorers
from bot.states import AwardEnter

logger = logging.getLogger(__name__)

awards_router = Router()

_TEXT_NOT_CMD = F.text & ~F.text.startswith("/")

_KIND_LABELS = {
    "ball": "🌕 Золотой мяч",
    "boot": "👢 Золотая бутса",
    "glove": "🧤 Золотая перчатка (ВР)",
    "boy": "🌟 Golden Boy",
}

_RE_LG = re.compile(r"^aw:lg:(ball|boot|glove|boy):[a-z0-9_]+$")
_RE_TM = re.compile(r"^aw:tm:(ball|boot|glove|boy):[a-z0-9_]+:\d+$")


def _league_title(code: str) -> str:
    return dict(LEAGUE_LABELS).get(code, code)


def _kinds_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="🌕 Мяч", callback_data="aw:k:ball"
                ),
                InlineKeyboardButton(
                    text="👢 Бутса", callback_data="aw:k:boot"
                ),
            ],
            [
                InlineKeyboardButton(
                    text="🧤 Перчатка", callback_data="aw:k:glove"
                ),
                InlineKeyboardButton(
                    text="🌟 G. Boy", callback_data="aw:k:boy"
                ),
            ],
        ]
    )


def _league_for_award_kb(kind: str) -> InlineKeyboardMarkup:
    row: list[InlineKeyboardButton] = []
    rows: list[list[InlineKeyboardButton]] = []
    for code, label in LEAGUE_LABELS:
        row.append(
            InlineKeyboardButton(
                text=label,
                callback_data=f"aw:lg:{kind}:{code}",
            )
        )
        if len(row) == 3:
            rows.append(row)
            row = []
    if row:
        rows.append(row)
    return InlineKeyboardMarkup(inline_keyboard=rows)


def _club_btn_label(text: str, max_chars: int = 40) -> str:
    text = (text or "").strip()
    if len(text) <= max_chars:
        return text
    return text[: max_chars - 1] + "…"


def _teams_kb(kind: str, league_code: str) -> InlineKeyboardMarkup:
    teams = teams_ordered_for_goalscorers(league_code)
    rows: list[list[InlineKeyboardButton]] = []
    row: list[InlineKeyboardButton] = []
    for idx, team in enumerate(teams):
        row.append(
            InlineKeyboardButton(
                text=_club_btn_label(team),
                callback_data=f"aw:tm:{kind}:{league_code}:{idx}",
            )
        )
        if len(row) == 2:
            rows.append(row)
            row = []
    if row:
        rows.append(row)
    return InlineKeyboardMarkup(inline_keyboard=rows)


async def _open_award_menu_msg(message: Message) -> None:
    wc_note = ""
    try:
        from utils.world_cup import is_world_cup_season

        if is_world_cup_season():
            wc_note = (
                "\n\n🌍 <b>Сезон ЧМ:</b> ЗМ / бутса / перчатка / Golden Boy вручаем "
                "<b>после</b> чемпионата мира (месяц 11). "
                "Отдельная награда — лучший игрок ЧМ (история → Лучший ЧМ)."
            )
    except Exception:
        pass
    await message.answer(
        "🏅 <b>Награда сезона</b>\n\n"
        "Выбери награду, лигу и клуб, затем введи <b>имя игрока</b> как в базе.\n"
        "Одна награда этого вида на сезон: +1 пишется в <b>одну</b> БД (сначала ищем в нац. лиге, "
        "если нет строки — в БД ЛЧ). В <code>common.db</code> для сводки дубли не суммируются."
        f"{wc_note}\n\n"
        "/cancel — отмена.",
        reply_markup=_kinds_keyboard(),
        parse_mode="HTML",
    )


@awards_router.callback_query(F.data == "menu:awards")
async def cb_menu_awards(callback: CallbackQuery, state: FSMContext) -> None:
    await callback.answer()
    if callback.message is None:
        return
    await state.clear()
    await _open_award_menu_msg(callback.message)


@awards_router.message(Command("awards"))
async def cmd_awards(message: Message, state: FSMContext) -> None:
    await state.clear()
    await _open_award_menu_msg(message)


@awards_router.callback_query(
    (F.data == "aw:k:ball")
    | (F.data == "aw:k:boot")
    | (F.data == "aw:k:glove")
    | (F.data == "aw:k:boy")
)
async def cb_award_kind(callback: CallbackQuery, state: FSMContext) -> None:
    await callback.answer()
    if callback.message is None or not callback.data:
        return
    kind = callback.data.rsplit(":", 1)[-1]
    await state.update_data(aw_kind=kind)
    label = _KIND_LABELS.get(kind, kind)
    await callback.message.answer(
        f"{label} — выберите лигу:",
        reply_markup=_league_for_award_kb(kind),
    )


@awards_router.callback_query(
    (F.data.startswith("aw:lg:ball:"))
    | (F.data.startswith("aw:lg:boot:"))
    | (F.data.startswith("aw:lg:glove:"))
    | (F.data.startswith("aw:lg:boy:"))
)
async def cb_award_league(callback: CallbackQuery, state: FSMContext) -> None:
    d = callback.data
    if not d or not _RE_LG.match(d):
        return
    await callback.answer()
    if callback.message is None or not callback.data:
        return
    parts = callback.data.split(":")
    if len(parts) < 4:
        return
    kind, code = parts[2], parts[3]
    await state.update_data(aw_kind=kind, aw_lg=code)
    try:
        kb = _teams_kb(kind, code)
    except Exception as e:
        logger.exception("aw_teams_kb")
        await callback.message.answer(f"Ошибка: {e}")
        return
    label = _KIND_LABELS.get(kind, kind)
    await callback.message.answer(
        f"{label} · {_league_title(code)} — выберите клуб:",
        reply_markup=kb,
    )


@awards_router.callback_query(
    (F.data.startswith("aw:tm:ball:"))
    | (F.data.startswith("aw:tm:boot:"))
    | (F.data.startswith("aw:tm:glove:"))
    | (F.data.startswith("aw:tm:boy:"))
)
async def cb_award_team(callback: CallbackQuery, state: FSMContext) -> None:
    d = callback.data
    if not d or not _RE_TM.match(d):
        return
    if callback.message is None or not callback.data:
        return
    await callback.answer()
    parts = callback.data.split(":")
    if len(parts) < 5:
        return
    kind, code, idx_s = parts[2], parts[3], parts[4]
    try:
        idx = int(idx_s)
    except ValueError:
        return
    try:
        teams = teams_ordered_for_goalscorers(code)
        team = teams[idx]
    except (IndexError, Exception) as e:
        await callback.message.answer(f"Клуб: ошибка: {e}")
        return
    label = _KIND_LABELS.get(kind, kind)
    await state.update_data(aw_kind=kind, aw_lg=code, aw_team=team, aw_lbl=label)
    await state.set_state(AwardEnter.wait_name)
    await callback.message.answer(
        f"{label}\n"
        f"<b>{_league_title(code)}</b> · {team}\n\n"
        "Введи <b>фамилию/имя игрока</b> как в БД (одна строка).\n"
        "/cancel — отмена.",
        parse_mode="HTML",
    )


@awards_router.message(AwardEnter.wait_name, _TEXT_NOT_CMD)
async def on_award_name(message: Message, state: FSMContext) -> None:
    name = (message.text or "").strip()
    if len(name) < 2:
        await message.answer("Слишком коротко. Введи имя ещё раз.")
        return
    data = await state.get_data()
    kind = data.get("aw_kind", "")
    team = data.get("aw_team", "")
    lbl = data.get("aw_lbl", "Награда")
    if not team:
        await state.clear()
        await message.answer("Сброс. Начни с меню «Награды».")
        return
    try:
        r = await asyncio.to_thread(apply_trophy, str(kind), name, str(team))
    except ValueError as e:
        await message.answer(str(e))
        return
    except Exception as e:
        logger.exception("apply_trophy")
        await message.answer(f"Ошибка: {e}")
        return
    await state.clear()
    src = "нац. лига" if r.league else "ЛЧ"
    disp_name = r.player_name or name
    disp_team = r.team or team
    await message.answer(
        f"✅ {lbl}\n"
        f"<b>{disp_name}</b> · {disp_team}\n"
        f"+1 в одной БД ({src}) — в сезоне одна награда этого вида; "
        f"класс: {r.player_class}\n"
        f"<code>common.db</code> пересобран; "
        f"<code>season_history.json</code> обновлён.",
        parse_mode="HTML",
    )
