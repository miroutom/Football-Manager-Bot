"""Ввод трансфера игрока через Telegram (FSM)."""
from __future__ import annotations

import logging

from aiogram import F, Router
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message

from bot.states import TransferEnter
from bot.transfer_storage import append_transfer

logger = logging.getLogger(__name__)

transfer_router = Router()

_TEXT_NOT_CMD = F.text & ~F.text.startswith("/")


@transfer_router.callback_query(F.data == "xfer:start")
async def cb_transfer_start(callback: CallbackQuery, state: FSMContext) -> None:
    await callback.answer()
    await state.set_state(TransferEnter.player_name)
    await callback.message.answer(
        "🔄 <b>Трансфер</b>\n\n"
        "Шаг 1/4 — введи <b>имя игрока</b> (как в игре).\n"
        "/cancel — отмена.",
        parse_mode="HTML",
    )


@transfer_router.message(Command("transfer"))
async def cmd_transfer(message: Message, state: FSMContext) -> None:
    await state.set_state(TransferEnter.player_name)
    await message.answer(
        "🔄 <b>Трансфер</b>\n\n"
        "Шаг 1/4 — введи <b>имя игрока</b>.\n"
        "/cancel — отмена.",
        parse_mode="HTML",
    )


@transfer_router.message(TransferEnter.player_name, _TEXT_NOT_CMD)
async def on_transfer_player(message: Message, state: FSMContext) -> None:
    name = (message.text or "").strip()
    if len(name) < 2:
        await message.answer("Слишком коротко. Введи имя игрока.")
        return
    await state.update_data(tr_player=name)
    await state.set_state(TransferEnter.from_team)
    await message.answer(
        f"Шаг 2/4 — команда, <b>откуда</b> уходит игрок (был):\n"
        f"«{name}»\n\n/cancel — отмена.",
        parse_mode="HTML",
    )


@transfer_router.message(TransferEnter.from_team, _TEXT_NOT_CMD)
async def on_transfer_from(message: Message, state: FSMContext) -> None:
    team = (message.text or "").strip()
    if len(team) < 2:
        await message.answer("Введи название клуба.")
        return
    await state.update_data(tr_from=team)
    await state.set_state(TransferEnter.position)
    await message.answer(
        "Шаг 3/4 — <b>позиция</b> игрока (например ЦН, ЦП, ЦЗ, ВР…).\n/cancel — отмена.",
        parse_mode="HTML",
    )


@transfer_router.message(TransferEnter.position, _TEXT_NOT_CMD)
async def on_transfer_position(message: Message, state: FSMContext) -> None:
    pos = (message.text or "").strip()
    if len(pos) < 1:
        await message.answer("Введи позицию.")
        return
    await state.update_data(tr_pos=pos)
    await state.set_state(TransferEnter.to_team)
    await message.answer(
        "Шаг 4/4 — команда, <b>куда</b> переходит игрок.\n/cancel — отмена.",
        parse_mode="HTML",
    )


@transfer_router.message(TransferEnter.to_team, _TEXT_NOT_CMD)
async def on_transfer_to(message: Message, state: FSMContext) -> None:
    to_t = (message.text or "").strip()
    if len(to_t) < 2:
        await message.answer("Введи название клуба.")
        return
    data = await state.get_data()
    player = data.get("tr_player", "")
    from_t = data.get("tr_from", "")
    pos = data.get("tr_pos", "")
    uid = message.from_user.id if message.from_user else None
    try:
        from utils.player_transfer import apply_transfer

        counts = apply_transfer(
            player=player,
            from_team=from_t,
            position=pos,
            to_team=to_t,
        )
    except Exception as e:
        logger.exception("transfer_apply")
        await message.answer(f"Не удалось обновить базы: {e}")
        return
    try:
        append_transfer(
            user_id=uid,
            player=player,
            from_team=from_t,
            position=pos,
            to_team=to_t,
        )
    except Exception as e:
        logger.exception("transfer_save")
        await message.answer(
            f"Базы обновлены, но журнал transfers.json не записан: {e}",
            parse_mode="HTML",
        )
        await state.clear()
        return

    await state.clear()
    n_db = counts.get("league", 0) + counts.get("cl", 0)
    warn = ""
    if n_db == 0:
        warn = (
            "⚠️ В <code>league.db</code> и ЛЧ строк не найдено "
            "(проверь имя, клуб «откуда» и позицию как в базе).\n\n"
        )
    lines = [
        warn,
        f"✓ БД: национальные лиги — <b>{counts['league']}</b>, ЛЧ — <b>{counts['cl']}</b>. "
        "<code>common.db</code> пересобран.",
        "",
        "Журнал: <code>data/transfers.json</code>",
        "",
        f"<b>{player}</b> ({pos})",
        f"{from_t} → {to_t}",
    ]
    await message.answer("\n".join(lines), parse_mode="HTML")
