"""Ввод трансфера игрока или свободного агента через Telegram (FSM)."""
from __future__ import annotations

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

from bot.states import TransferEnter
from bot.transfer_storage import append_transfer

logger = logging.getLogger(__name__)

transfer_router = Router()

_TEXT_NOT_CMD = F.text & ~F.text.startswith("/")

_RE_OVERALL = re.compile(r"^\s*(\d{1,2})\s*$")


def _kind_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="Из другого клуба", callback_data="xfer:kind:club"
                ),
            ],
            [
                InlineKeyboardButton(
                    text="Свободный агент (новый игрок)", callback_data="xfer:kind:fa"
                ),
            ],
        ]
    )


def _status_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="▶ Старт (11)", callback_data="xfer:st:start"
                ),
                InlineKeyboardButton(
                    text="Скамейка", callback_data="xfer:st:bench"
                ),
            ],
            [
                InlineKeyboardButton(
                    text="Резерв", callback_data="xfer:st:reserve"
                ),
            ],
        ]
    )


@transfer_router.callback_query(F.data == "xfer:start")
async def cb_transfer_start(callback: CallbackQuery, state: FSMContext) -> None:
    await callback.answer()
    await state.set_state(TransferEnter.player_name)
    await state.update_data(tr_kind="")
    await callback.message.answer(
        "🔄 <b>Трансфер / свободный агент</b>\n\n"
        "Сначала выбери тип (кнопки ниже) или введи имя сразу для варианта "
        "<b>из клуба</b> — тогда дальше шаги как раньше.\n"
        "Удобнее: нажми кнопку <b>Из другого клуба</b> или <b>Свободный агент</b>.\n\n"
        "Или <b>Шаг 1</b> — введи <b>имя игрока</b> (как в игре), если уже выбрал тип кнопкой.\n"
        "/cancel — отмена.",
        parse_mode="HTML",
        reply_markup=_kind_keyboard(),
    )


@transfer_router.callback_query(F.data.startswith("xfer:kind:"))
async def cb_transfer_kind(callback: CallbackQuery, state: FSMContext) -> None:
    kind = (callback.data or "").rsplit(":", 1)[-1]
    if kind not in ("club", "fa"):
        return
    await callback.answer()
    if not callback.message:
        return
    await state.set_state(TransferEnter.player_name)
    await state.update_data(tr_kind=kind)
    if kind == "club":
        await callback.message.answer(
            "Тип: <b>трансфер из клуба</b>.\n\n"
            "Шаг 1/5 — <b>имя игрока</b>.\n/cancel — отмена.",
            parse_mode="HTML",
        )
    else:
        await callback.message.answer(
            "Тип: <b>свободный агент</b> (новая строка в БД).\n\n"
            "Шаг 1/5 — <b>имя игрока</b>.\n/cancel — отмена.",
            parse_mode="HTML",
        )


@transfer_router.message(Command("transfer"))
async def cmd_transfer(message: Message, state: FSMContext) -> None:
    await state.set_state(TransferEnter.player_name)
    await state.update_data(tr_kind="")
    await message.answer(
        "🔄 <b>Трансфер / свободный агент</b>\n\n"
        "Выбери тип кнопками или введи имя (режим «из клуба»).\n/cancel — отмена.",
        parse_mode="HTML",
        reply_markup=_kind_keyboard(),
    )


@transfer_router.message(TransferEnter.player_name, _TEXT_NOT_CMD)
async def on_transfer_player(message: Message, state: FSMContext) -> None:
    name = (message.text or "").strip()
    if len(name) < 2:
        await message.answer("Слишком коротко. Введи имя игрока.")
        return
    data = await state.get_data()
    kind = (data.get("tr_kind") or "").strip()
    if not kind:
        # по умолчанию — трансфер из клуба
        kind = "club"
        await state.update_data(tr_kind="club")
    await state.update_data(tr_player=name)
    if kind == "fa":
        await state.set_state(TransferEnter.position)
        await message.answer(
            f"Шаг 2/5 — <b>позиция</b> (ЦН, ЦП, ЦЗ, ВР…).\n"
            f"Игрок: «{name}»\n/cancel — отмена.",
            parse_mode="HTML",
        )
        return
    await state.set_state(TransferEnter.from_team)
    await message.answer(
        f"Шаг 2/5 — команда, <b>откуда</b> уходит игрок:\n"
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
        "Шаг 3/5 — <b>позиция</b> (например ЦН, ЦП, ЦЗ, ВР…).\n/cancel — отмена.",
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
    data = await state.get_data()
    kind = data.get("tr_kind")
    n = "4/5" if kind == "fa" else "4/5"
    await message.answer(
        f"Шаг {n} — команда, <b>куда</b> переходит игрок.\n/cancel — отмена.",
        parse_mode="HTML",
    )


@transfer_router.message(TransferEnter.to_team, _TEXT_NOT_CMD)
async def on_transfer_to(message: Message, state: FSMContext) -> None:
    to_t = (message.text or "").strip()
    if len(to_t) < 2:
        await message.answer("Введи название клуба.")
        return
    await state.update_data(tr_to=to_t)
    data = await state.get_data()
    if data.get("tr_kind") == "fa":
        await state.set_state(TransferEnter.fa_overall)
        await message.answer(
            "Шаг 5/6 — <b>стартовый overall</b> (число 1–99, например <code>72</code>).\n"
            "/cancel — отмена.",
            parse_mode="HTML",
        )
        return
    await state.set_state(TransferEnter.new_status)
    await message.answer(
        "Шаг 5/5 — <b>заявка</b> в новом клубе (старт / скамейка / резерв). "
        "Правила: <b>старт</b> — прежний старт с этой позиции → скамейка, худший на скамейке → резерв; "
        "<b>скамейка</b> — худший на скамейке (если больше одного) → резерв; "
        "<b>резерв</b> — только в резерв.\n"
        "/cancel — отмена.",
        parse_mode="HTML",
        reply_markup=_status_keyboard(),
    )


@transfer_router.message(TransferEnter.fa_overall, _TEXT_NOT_CMD)
async def on_fa_overall(message: Message, state: FSMContext) -> None:
    raw = (message.text or "").strip()
    m = _RE_OVERALL.match(raw)
    if not m:
        await message.answer("Введи одно число 1–99, например 72.")
        return
    o = int(m.group(1))
    if o < 1 or o > 99:
        await message.answer("Диапазон 1–99.")
        return
    await state.update_data(tr_overall=o)
    await state.set_state(TransferEnter.new_status)
    await message.answer(
        "Шаг 6/6 — <b>заявка</b> (старт / скамейка / резерв) — как у обычного трансфера.\n"
        "/cancel — отмена.",
        parse_mode="HTML",
        reply_markup=_status_keyboard(),
    )


@transfer_router.callback_query(TransferEnter.new_status, F.data.startswith("xfer:st:"))
async def on_transfer_status(
    callback: CallbackQuery, state: FSMContext
) -> None:
    st = (callback.data or "").rsplit(":", 1)[-1]
    if st not in ("start", "bench", "reserve"):
        return
    await callback.answer()
    if not callback.message:
        return
    data = await state.get_data()
    player = data.get("tr_player", "")
    pos = data.get("tr_pos", "")
    to_t = data.get("tr_to", "")
    kind = data.get("tr_kind")
    uid = callback.from_user.id if callback.from_user else None

    if kind == "fa":
        ovr = int(data.get("tr_overall") or 72)
        try:
            from utils.player_transfer import add_free_agent

            counts = add_free_agent(
                player=player,
                position=pos,
                to_team=to_t,
                new_status=st,
                overall=ovr,
            )
        except Exception as e:
            logger.exception("add_free_agent")
            await callback.message.answer(f"Не удалось обновить базы: {e}")
            return
        try:
            append_transfer(
                user_id=uid,
                player=player,
                from_team="(свободный агент)",
                position=pos,
                to_team=to_t,
                new_status=st,
                free_agent=True,
            )
        except Exception as e:
            logger.exception("transfer_save")
            await callback.message.answer(
                f"Базы обновлены, но журнал не записан: {e}",
            )
            await state.clear()
            return
        await state.clear()
        lines = [
            "✓ <b>Свободный агент</b> добавлен.",
            f"БД: нац. — <b>{counts['league']}</b>, ЛЧ — <b>{counts['cl']}</b>.",
            f"Overall: <b>{ovr}</b>, заявка: <b>{st}</b>.",
            "",
            f"<b>{player}</b> ({pos}) → {to_t}",
            "Журнал: <code>data/transfers.json</code>",
        ]
        await callback.message.answer("\n".join(lines), parse_mode="HTML")
        return

    from_t = data.get("tr_from", "")
    try:
        from utils.player_transfer import apply_transfer_with_status

        counts = apply_transfer_with_status(
            player=player,
            from_team=from_t,
            position=pos,
            to_team=to_t,
            new_status=st,
        )
    except Exception as e:
        logger.exception("transfer_apply")
        await callback.message.answer(f"Не удалось обновить базы: {e}")
        return
    try:
        append_transfer(
            user_id=uid,
            player=player,
            from_team=from_t,
            position=pos,
            to_team=to_t,
            new_status=st,
            free_agent=False,
        )
    except Exception as e:
        logger.exception("transfer_save")
        await callback.message.answer(
            f"Базы обновлены, но журнал transfers.json не записан: {e}",
        )
        await state.clear()
        return

    await state.clear()
    n_db = counts.get("league", 0) + counts.get("cl", 0)
    warn = ""
    if n_db == 0:
        warn = (
            "⚠️ В нац. БД и ЛЧ строк не найдено "
            "(проверь имя, клуб «откуда» и позицию как в базе).\n\n"
        )
    lines = [
        warn,
        f"✓ БД: нац. — <b>{counts['league']}</b>, ЛЧ — <b>{counts['cl']}</b>. "
        "<code>common.db</code> пересобран.",
        "",
        f"Заявка: <b>{st}</b>",
        "Журнал: <code>data/transfers.json</code>",
        "",
        f"<b>{player}</b> ({pos})",
        f"{from_t} → {to_t}",
    ]
    await callback.message.answer("\n".join(lines), parse_mode="HTML")
