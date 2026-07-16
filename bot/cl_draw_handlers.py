# -*- coding: utf-8 -*-
"""Ручной жребий ЛЧ в боте: 1/16 (места 9–24) и 1/8 (места 1–8 × победители)."""
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

from bot.states import ClDrawEnter

logger = logging.getLogger(__name__)

cl_draw_router = Router()

_PLACEHOLDER = "—"


def _club_btn(text: str, max_chars: int = 28) -> str:
    text = (text or "").strip()
    if len(text) <= max_chars:
        return text
    return text[: max_chars - 1] + "…"


def _r1_status_html(pairs: list[list[str]], pending: str | None, remaining: list[str]) -> str:
    lines = ["🎟 <b>Жребий 1/16 ЛЧ</b>", "", "Пул: места <b>9–24</b> таблицы.", ""]
    if pairs:
        lines.append("<b>Пары:</b>")
        for i, (h, a) in enumerate(pairs, 1):
            lines.append(f"{i}. {h} — {a}")
        lines.append("")
    left = 8 - len(pairs)
    if left > 0:
        if pending:
            lines.append(f"Выбрана: <b>{pending}</b> — нажми соперника.")
        else:
            lines.append(f"Осталось пар: <b>{left}</b>. Два тапа = пара.")
        lines.append(f"В пуле: {len(remaining)}")
    else:
        lines.append("Все 8 пар собраны. Нажми <b>Записать в сетку</b>.")
    lines.append("\n/cancel — отмена.")
    return "\n".join(lines)


def _r1_keyboard(
    remaining: list[str],
    *,
    pending: str | None,
    pairs_n: int,
) -> InlineKeyboardMarkup:
    rows: list[list[InlineKeyboardButton]] = []
    row: list[InlineKeyboardButton] = []
    for idx, team in enumerate(remaining):
        mark = "✓ " if pending and team == pending else ""
        row.append(
            InlineKeyboardButton(
                text=f"{mark}{_club_btn(team)}",
                callback_data=f"cld:r1:t:{idx}",
            )
        )
        if len(row) == 2:
            rows.append(row)
            row = []
    if row:
        rows.append(row)
    nav: list[InlineKeyboardButton] = []
    if pairs_n > 0:
        nav.append(
            InlineKeyboardButton(text="↩ Отменить последнюю", callback_data="cld:r1:undo")
        )
    if pairs_n > 0 or pending:
        nav.append(InlineKeyboardButton(text="Сброс", callback_data="cld:r1:reset"))
    if nav:
        rows.append(nav)
    if pairs_n >= 8:
        rows.append(
            [
                InlineKeyboardButton(
                    text="✅ Записать в сетку", callback_data="cld:r1:save"
                )
            ]
        )
    rows.append(
        [InlineKeyboardButton(text="✖️ Отмена", callback_data="cld:cancel")]
    )
    return InlineKeyboardMarkup(inline_keyboard=rows)


def _r2_status_html(
    winners: list[str],
    seeds: list[str | None],
    seed_pool: list[str],
    active_slot: int | None,
) -> str:
    lines = [
        "🎟 <b>Жребий 1/8 ЛЧ</b>",
        "",
        "Победители 1/16 получают соперника из мест <b>1–8</b>.",
        "",
        "<b>Стыки:</b>",
    ]
    for i, w in enumerate(winners):
        seed = seeds[i] if i < len(seeds) else None
        if seed:
            lines.append(f"{i + 1}. {seed} — {w}")
        else:
            mark = " ←" if active_slot == i else ""
            lines.append(f"{i + 1}. ? — {w}{mark}")
    lines.append("")
    if any(s is None for s in seeds):
        if active_slot is None:
            lines.append("Выбери стык, затем соперника из пула.")
        else:
            lines.append(
                f"Стык {active_slot + 1} ({winners[active_slot]}): выбери соперника."
            )
        lines.append(f"Осталось в пуле: {len(seed_pool)}")
    else:
        lines.append("Все стыки заполнены. Нажми <b>Записать в сетку</b>.")
    lines.append("\n/cancel — отмена.")
    return "\n".join(lines)


def _r2_keyboard(
    winners: list[str],
    seeds: list[str | None],
    seed_pool: list[str],
    active_slot: int | None,
) -> InlineKeyboardMarkup:
    rows: list[list[InlineKeyboardButton]] = []
    if any(s is None for s in seeds) and active_slot is None:
        for i, w in enumerate(winners):
            if seeds[i] is not None:
                continue
            rows.append(
                [
                    InlineKeyboardButton(
                        text=f"Стык {i + 1}: {_club_btn(w)}",
                        callback_data=f"cld:r2:slot:{i}",
                    )
                ]
            )
    elif active_slot is not None:
        row: list[InlineKeyboardButton] = []
        for idx, team in enumerate(seed_pool):
            row.append(
                InlineKeyboardButton(
                    text=_club_btn(team),
                    callback_data=f"cld:r2:seed:{idx}",
                )
            )
            if len(row) == 2:
                rows.append(row)
                row = []
        if row:
            rows.append(row)
        rows.append(
            [
                InlineKeyboardButton(
                    text="↩ К стыкам", callback_data="cld:r2:back"
                )
            ]
        )
    nav: list[InlineKeyboardButton] = []
    if any(s is not None for s in seeds):
        nav.append(
            InlineKeyboardButton(text="↩ Отменить последнюю", callback_data="cld:r2:undo")
        )
        nav.append(InlineKeyboardButton(text="Сброс", callback_data="cld:r2:reset"))
    if nav:
        rows.append(nav)
    if seeds and all(s is not None for s in seeds):
        rows.append(
            [
                InlineKeyboardButton(
                    text="✅ Записать в сетку", callback_data="cld:r2:save"
                )
            ]
        )
    rows.append(
        [InlineKeyboardButton(text="✖️ Отмена", callback_data="cld:cancel")]
    )
    return InlineKeyboardMarkup(inline_keyboard=rows)


async def _edit_or_answer(
    target: Message,
    text: str,
    kb: InlineKeyboardMarkup,
    *,
    edit: bool,
) -> None:
    if edit:
        try:
            await target.edit_text(text, reply_markup=kb, parse_mode="HTML")
            return
        except Exception:
            pass
    await target.answer(text, reply_markup=kb, parse_mode="HTML")


async def start_cl_draw_flow(message: Message, state: FSMContext) -> None:
    """Открыть нужный жребий по текущему состоянию сетки."""
    from utils.cl_draw import cl_draw_menu_action

    action = await asyncio.to_thread(cl_draw_menu_action)
    await state.clear()
    if action == "r1":
        await _start_r1(message, state, edit=False)
    elif action == "r2":
        await _start_r2(message, state, edit=False)
    else:
        await message.answer(
            "Сейчас жребий ЛЧ не требуется.\n"
            "1/16 — после группы; 1/8 — после всех стыков 1/16."
        )


async def _start_r1(message: Message, state: FSMContext, *, edit: bool) -> None:
    from utils.cl_draw import r1_draw_pool

    pool = await asyncio.to_thread(r1_draw_pool)
    if len(pool) < 16:
        await message.answer(
            f"В пуле 1/16 ожидается 16 команд (места 9–24), сейчас {len(pool)}."
        )
        return
    await state.set_state(ClDrawEnter.r1_picking)
    await state.update_data(r1_pool=pool, r1_pairs=[], r1_pending=None)
    text = _r1_status_html([], None, pool)
    kb = _r1_keyboard(pool, pending=None, pairs_n=0)
    await _edit_or_answer(message, text, kb, edit=edit)


async def _start_r2(message: Message, state: FSMContext, *, edit: bool) -> None:
    from utils.cl_draw import r1_winners_in_bracket_order, r2_seed_pool

    winners = await asyncio.to_thread(r1_winners_in_bracket_order)
    seeds_pool = await asyncio.to_thread(r2_seed_pool)
    if not winners or len(winners) != 8:
        await message.answer(
            "Не удалось получить 8 победителей 1/16 — доиграй все стыки."
        )
        return
    if len(seeds_pool) < 8:
        await message.answer(
            f"В пуле 1/8 ожидается 8 команд (места 1–8), сейчас {len(seeds_pool)}."
        )
        return
    await state.set_state(ClDrawEnter.r2_picking)
    await state.update_data(
        r2_winners=winners,
        r2_seed_pool=list(seeds_pool),
        r2_seeds=[None] * 8,
        r2_active=None,
    )
    text = _r2_status_html(winners, [None] * 8, seeds_pool, None)
    kb = _r2_keyboard(winners, [None] * 8, seeds_pool, None)
    await _edit_or_answer(message, text, kb, edit=edit)


async def _refresh_r1(callback: CallbackQuery, state: FSMContext) -> None:
    data = await state.get_data()
    pairs = data.get("r1_pairs") or []
    pending = data.get("r1_pending")
    pool = data.get("r1_pool") or []
    text = _r1_status_html(pairs, pending, pool)
    kb = _r1_keyboard(pool, pending=pending, pairs_n=len(pairs))
    await _edit_or_answer(callback.message, text, kb, edit=True)


async def _refresh_r2(callback: CallbackQuery, state: FSMContext) -> None:
    data = await state.get_data()
    winners = data.get("r2_winners") or []
    seeds = data.get("r2_seeds") or [None] * 8
    pool = data.get("r2_seed_pool") or []
    active = data.get("r2_active")
    text = _r2_status_html(winners, seeds, pool, active)
    kb = _r2_keyboard(winners, seeds, pool, active)
    await _edit_or_answer(callback.message, text, kb, edit=True)


@cl_draw_router.callback_query(F.data == "menu:cl_draw")
async def cb_menu_cl_draw(callback: CallbackQuery, state: FSMContext) -> None:
    await callback.answer()
    await start_cl_draw_flow(callback.message, state)


@cl_draw_router.message(Command("cl_draw"))
async def cmd_cl_draw(message: Message, state: FSMContext) -> None:
    await start_cl_draw_flow(message, state)


@cl_draw_router.callback_query(F.data == "cld:cancel")
async def cb_cld_cancel(callback: CallbackQuery, state: FSMContext) -> None:
    await state.clear()
    await callback.answer("Отменено")
    try:
        await callback.message.edit_text("Жребий ЛЧ отменён.")
    except Exception:
        await callback.message.answer("Жребий ЛЧ отменён.")


@cl_draw_router.callback_query(ClDrawEnter.r1_picking, F.data.startswith("cld:r1:"))
async def cb_cld_r1(callback: CallbackQuery, state: FSMContext) -> None:
    data = await state.get_data()
    pairs: list[list[str]] = list(data.get("r1_pairs") or [])
    pending: str | None = data.get("r1_pending")
    pool: list[str] = list(data.get("r1_pool") or [])
    action = callback.data.split(":")[-1]

    if callback.data == "cld:r1:undo":
        if pairs:
            h, a = pairs.pop()
            pool.extend([h, a])
            await state.update_data(r1_pairs=pairs, r1_pool=pool, r1_pending=None)
        await callback.answer()
        await _refresh_r1(callback, state)
        return

    if callback.data == "cld:r1:reset":
        from utils.cl_draw import r1_draw_pool

        pool = await asyncio.to_thread(r1_draw_pool)
        await state.update_data(r1_pairs=[], r1_pool=pool, r1_pending=None)
        await callback.answer("Сброс")
        await _refresh_r1(callback, state)
        return

    if callback.data == "cld:r1:save":
        if len(pairs) < 8:
            await callback.answer("Нужно 8 пар", show_alert=True)
            return
        await callback.answer("Сохраняю…")
        ok_msg = await asyncio.to_thread(_persist_r1, pairs)
        await state.clear()
        try:
            await callback.message.edit_text(ok_msg, parse_mode="HTML")
        except Exception:
            await callback.message.answer(ok_msg, parse_mode="HTML")
        return

    if not callback.data.startswith("cld:r1:t:"):
        await callback.answer()
        return

    try:
        idx = int(action)
        team = pool[idx]
    except (ValueError, IndexError):
        await callback.answer("Команда недоступна", show_alert=True)
        return

    if pending is None:
        await state.update_data(r1_pending=team)
        await callback.answer(team)
        await _refresh_r1(callback, state)
        return

    if team == pending:
        await state.update_data(r1_pending=None)
        await callback.answer("Снято")
        await _refresh_r1(callback, state)
        return

    if len(pairs) >= 8:
        await callback.answer("Уже 8 пар", show_alert=True)
        return

    pairs.append([pending, team])
    pool = [t for t in pool if t not in (pending, team)]
    await state.update_data(r1_pairs=pairs, r1_pool=pool, r1_pending=None)
    await callback.answer(f"{pending} — {team}")
    await _refresh_r1(callback, state)


def _persist_r1(pairs: list[list[str]]) -> str:
    from champions_league.knockout_bracket import (
        get_default_round2_seeds,
        save_cl_playoff_bracket,
    )
    from utils.cl_knockout_schedule import apply_cl_draw_to_schedule

    seeds = get_default_round2_seeds()
    # Пока 1/8 не разыгран — посевы остаются плейсхолдерами
    if not all(s and s != _PLACEHOLDER for s in seeds):
        seeds = [_PLACEHOLDER] * 8
    save_cl_playoff_bracket(pairs, seeds)
    added, msg = apply_cl_draw_to_schedule("round_1")
    lines = ["✅ <b>1/16 записана</b> в сетку."]
    for i, (h, a) in enumerate(pairs, 1):
        lines.append(f"{i}. {h} — {a}")
    lines.append("")
    lines.append(msg if added else (msg or "Матчи уже были в календаре."))
    lines.append("Места 1–8 ждут жребия 1/8 после стыков.")
    return "\n".join(lines)


@cl_draw_router.callback_query(ClDrawEnter.r2_picking, F.data.startswith("cld:r2:"))
async def cb_cld_r2(callback: CallbackQuery, state: FSMContext) -> None:
    data = await state.get_data()
    winners: list[str] = list(data.get("r2_winners") or [])
    seeds: list[str | None] = list(data.get("r2_seeds") or [None] * 8)
    pool: list[str] = list(data.get("r2_seed_pool") or [])
    active = data.get("r2_active")

    if callback.data == "cld:r2:undo":
        for i in range(7, -1, -1):
            if seeds[i] is not None:
                pool.append(seeds[i])  # type: ignore[arg-type]
                seeds[i] = None
                break
        await state.update_data(r2_seeds=seeds, r2_seed_pool=pool, r2_active=None)
        await callback.answer()
        await _refresh_r2(callback, state)
        return

    if callback.data == "cld:r2:reset":
        from utils.cl_draw import r2_seed_pool

        pool = await asyncio.to_thread(r2_seed_pool)
        await state.update_data(
            r2_seeds=[None] * 8, r2_seed_pool=pool, r2_active=None
        )
        await callback.answer("Сброс")
        await _refresh_r2(callback, state)
        return

    if callback.data == "cld:r2:back":
        await state.update_data(r2_active=None)
        await callback.answer()
        await _refresh_r2(callback, state)
        return

    if callback.data == "cld:r2:save":
        if any(s is None for s in seeds) or len(seeds) < 8:
            await callback.answer("Заполни все 8 стыков", show_alert=True)
            return
        await callback.answer("Сохраняю…")
        ok_msg = await asyncio.to_thread(_persist_r2, seeds, winners)
        await state.clear()
        try:
            await callback.message.edit_text(ok_msg, parse_mode="HTML")
        except Exception:
            await callback.message.answer(ok_msg, parse_mode="HTML")
        return

    if callback.data.startswith("cld:r2:slot:"):
        try:
            slot = int(callback.data.rsplit(":", 1)[-1])
        except ValueError:
            await callback.answer()
            return
        if slot < 0 or slot >= 8 or seeds[slot] is not None:
            await callback.answer("Слот недоступен", show_alert=True)
            return
        await state.update_data(r2_active=slot)
        await callback.answer(f"Стык {slot + 1}")
        await _refresh_r2(callback, state)
        return

    if callback.data.startswith("cld:r2:seed:"):
        if active is None:
            await callback.answer("Сначала выбери стык", show_alert=True)
            return
        try:
            idx = int(callback.data.rsplit(":", 1)[-1])
            team = pool[idx]
        except (ValueError, IndexError):
            await callback.answer("Команда недоступна", show_alert=True)
            return
        seeds[int(active)] = team
        pool = [t for t in pool if t != team]
        await state.update_data(
            r2_seeds=seeds, r2_seed_pool=pool, r2_active=None
        )
        await callback.answer(f"{team} — {winners[int(active)]}")
        await _refresh_r2(callback, state)
        return

    await callback.answer()


def _persist_r2(seeds: list[str | None], winners: list[str]) -> str:
    from champions_league.knockout_bracket import (
        get_default_round1_pairs,
        save_cl_playoff_bracket,
    )
    from utils.cl_knockout_schedule import apply_cl_draw_to_schedule

    pairs = get_default_round1_pairs()
    seed_names = [str(s) for s in seeds]
    save_cl_playoff_bracket(pairs, seed_names)
    added, msg = apply_cl_draw_to_schedule("round_2")
    lines = ["✅ <b>1/8 записана</b> в сетку."]
    for i, (seed, w) in enumerate(zip(seed_names, winners), 1):
        lines.append(f"{i}. {seed} — {w}")
    lines.append("")
    lines.append(msg if added else (msg or "Матчи уже были в календаре."))
    lines.append("Дальше 1/4 и далее добавятся сами после стыков.")
    return "\n".join(lines)
