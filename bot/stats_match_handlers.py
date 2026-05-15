# -*- coding: utf-8 -*-
"""Двухшаговый ввод статистики матча: кто играл → стата по игроку."""
from __future__ import annotations

import asyncio
import logging
from html import escape as html_escape

from aiogram import F, Router
from aiogram.filters import StateFilter
from aiogram.fsm.context import FSMContext
from aiogram.types import (
    CallbackQuery,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    Message,
)

from bot.states import PostMatch
from utils.match_stats_bot import (
    _PAGE,
    apply_played_appearances,
    apply_player_stat_line,
    deserialize_roster,
    format_player_acc,
    get_player_acc,
    load_match_roster,
    merge_player_acc,
    parse_player_stat_line,
    player_by_idx,
    serialize_roster,
    set_player_acc,
)

logger = logging.getLogger(__name__)

stats_match_router = Router()

_TEXT_NOT_CMD = F.text & ~F.text.startswith("/")


def _played_set(data: dict) -> set[int]:
    return {int(x) for x in (data.get("stats_played_idxs") or [])}


def _roster(data: dict):
    return deserialize_roster(data.get("stats_roster") or [])


def _played_intro_html(data: dict, *, page: int, total_pages: int) -> str:
    home = html_escape(data.get("stats_home") or "")
    away = html_escape(data.get("stats_away") or "")
    hs = data.get("stats_hs")
    aws = data.get("stats_aws")
    sc = f"{hs}:{aws}" if hs is not None and aws is not None else "?"
    played = _played_set(data)
    return (
        f"<b>Шаг 1/2 — кто играл</b>\n"
        f"{home} — {away} (<b>{sc}</b>)\n\n"
        f"Отмечено: <b>{len(played)}</b>. Страница <b>{page + 1}</b>/<b>{total_pages}</b>.\n"
        "Нажимай по игроку. «Далее к стате» — когда все отмечены."
    )


def _played_pick_kb(data: dict, *, page: int) -> tuple[InlineKeyboardMarkup, int]:
    players = _roster(data)
    played = _played_set(data)
    side_filter = data.get("stats_side_filter")  # None | "home" | "away"
    home_c = (data.get("stats_home_canon") or data.get("stats_home") or "").strip()
    away_c = (data.get("stats_away_canon") or data.get("stats_away") or "").strip()

    filtered: list[int] = []
    for p in players:
        if side_filter == "home" and p.team.casefold() != home_c.casefold():
            continue
        if side_filter == "away" and p.team.casefold() != away_c.casefold():
            continue
        filtered.append(p.idx)

    n = len(filtered)
    total_pages = max(1, (n + _PAGE - 1) // _PAGE)
    page = max(0, min(int(page), total_pages - 1))
    chunk = filtered[page * _PAGE : page * _PAGE + _PAGE]

    rows: list[list[InlineKeyboardButton]] = []
    for gi in chunk:
        p = next(x for x in players if x.idx == gi)
        mark = "✅ " if gi in played else ""
        label = f"{mark}{p.side_label} · {p.name} · {p.position}"
        if len(label) > 60:
            label = label[:57] + "…"
        rows.append(
            [InlineKeyboardButton(text=label, callback_data=f"stpw:tp:{gi}")]
        )

    nav: list[InlineKeyboardButton] = []
    if page > 0:
        nav.append(InlineKeyboardButton(text="←", callback_data=f"stpw:pp:{page - 1}"))
    if page < total_pages - 1:
        nav.append(InlineKeyboardButton(text="→", callback_data=f"stpw:pp:{page + 1}"))
    if nav:
        rows.append(nav)

    rows.append(
        [
            InlineKeyboardButton(text="Все", callback_data="stpw:sf:all"),
            InlineKeyboardButton(text="Хозяева", callback_data="stpw:sf:home"),
            InlineKeyboardButton(text="Гости", callback_data="stpw:sf:away"),
        ]
    )
    rows.append(
        [InlineKeyboardButton(text="➡ Далее к стате", callback_data="stpw:played_done")]
    )
    return InlineKeyboardMarkup(inline_keyboard=rows), total_pages


def _stat_intro_html(data: dict, *, page: int, total_pages: int) -> str:
    home = html_escape(data.get("stats_home") or "")
    away = html_escape(data.get("stats_away") or "")
    cur = data.get("stats_cur_player_idx")
    cur_name = ""
    if cur is not None:
        p = player_by_idx(_roster(data), int(cur))
        if p:
            acc_s = format_player_acc(get_player_acc(data, int(cur)))
            acc_line = f" · <code>{html_escape(acc_s)}</code>" if acc_s else ""
            cur_name = (
                f"\nСейчас: <b>{html_escape(p.name)}</b>{acc_line}\n"
            )
    return (
        f"<b>Шаг 2/2 — стата</b>\n{home} — {away}{cur_name}\n"
        f"Выбери игрока (✅ на шаге 1). "
        f"Стр. <b>{page + 1}</b>/<b>{total_pages}</b>.\n\n"
        "Строка — любые фрагменты: <code>1 0</code>, <code>жк</code>, <code>3м</code>, "
        "<code>cs</code>, <code>-1 1</code> (убавить гол, если в матче уже есть)…\n"
        "Повторный выбор — дополняет (было <code>1+0 жк</code>, вводишь <code>0 1 жк</code> "
        "→ <code>1+1 2жк</code>).\n"
        "Не выбрал на шаге 2 — только +1 матч. «Готово» — завершить."
    )


def _stat_pick_kb(data: dict, *, page: int) -> tuple[InlineKeyboardMarkup, int]:
    players = _roster(data)
    played = _played_set(data)
    plist = [p for p in players if p.idx in played]
    n = len(plist)
    total_pages = max(1, (n + _PAGE - 1) // _PAGE)
    page = max(0, min(int(page), total_pages - 1))
    chunk = plist[page * _PAGE : page * _PAGE + _PAGE]

    acc_bag = data.get("stats_player_acc") or {}
    rows: list[list[InlineKeyboardButton]] = []
    for p in chunk:
        acc_s = format_player_acc(acc_bag.get(str(p.idx)))
        label = f"{p.name} · {p.position}"
        if acc_s:
            label = f"{label} · {acc_s}"
        if len(label) > 60:
            label = label[:57] + "…"
        rows.append(
            [InlineKeyboardButton(text=label, callback_data=f"stpw:sp:{p.idx}")]
        )

    nav: list[InlineKeyboardButton] = []
    if page > 0:
        nav.append(InlineKeyboardButton(text="←", callback_data=f"stpw:spg:{page - 1}"))
    if page < total_pages - 1:
        nav.append(InlineKeyboardButton(text="→", callback_data=f"stpw:spg:{page + 1}"))
    if nav:
        rows.append(nav)

    rows.append(
        [
            InlineKeyboardButton(
                text="← Кто играл",
                callback_data="stpw:back_played",
            ),
            InlineKeyboardButton(text="✓ Готово", callback_data="stats:done"),
        ]
    )
    return InlineKeyboardMarkup(inline_keyboard=rows), total_pages


async def start_stats_match_wizard(message: Message, state: FSMContext) -> None:
    """Точка входа после записи счёта (вместо текстового ввода строк)."""
    from utils.player_discipline import snapshot_suspensions_for_fixture

    data = await state.get_data()
    home = data["stats_home"]
    away = data["stats_away"]
    tournament = data.get("stats_tournament", "league")
    lc = data.get("stats_league_code") or ""

    players = await asyncio.to_thread(load_match_roster, home, away, tournament)
    from utils.match_ratings import build_roster_template

    _, _, canon_home = await asyncio.to_thread(
        build_roster_template, home, tournament
    )
    _, _, canon_away = await asyncio.to_thread(
        build_roster_template, away, tournament
    )
    susp_snap = await asyncio.to_thread(
        snapshot_suspensions_for_fixture,
        home,
        away,
        lc,
        tournament,
    )

    await state.update_data(
        stats_roster=serialize_roster(players),
        stats_home_canon=canon_home,
        stats_away_canon=canon_away,
        stats_played_idxs=[],
        stats_played_page=0,
        stats_stat_page=0,
        stats_side_filter=None,
        stats_susp_snapshot=susp_snap,
        stats_cur_player_idx=None,
        stats_player_acc={},
    )
    await state.set_state(PostMatch.stats_pick_played)

    kb, total_pages = _played_pick_kb(await state.get_data(), page=0)
    data2 = await state.get_data()
    await message.answer(
        _played_intro_html(data2, page=0, total_pages=total_pages),
        parse_mode="HTML",
        reply_markup=kb,
    )


async def _edit_played_ui(callback: CallbackQuery, state: FSMContext, page: int) -> None:
    if not callback.message:
        return
    await state.update_data(stats_played_page=page)
    data = await state.get_data()
    kb, total_pages = _played_pick_kb(data, page=page)
    text = _played_intro_html(data, page=page, total_pages=total_pages)
    try:
        await callback.message.edit_text(text, parse_mode="HTML", reply_markup=kb)
    except Exception:
        await callback.message.edit_reply_markup(reply_markup=kb)


async def _edit_stat_ui(callback: CallbackQuery, state: FSMContext, page: int) -> None:
    if not callback.message:
        return
    await state.update_data(stats_stat_page=page)
    data = await state.get_data()
    kb, total_pages = _stat_pick_kb(data, page=page)
    text = _stat_intro_html(data, page=page, total_pages=total_pages)
    try:
        await callback.message.edit_text(text, parse_mode="HTML", reply_markup=kb)
    except Exception:
        await callback.message.edit_reply_markup(reply_markup=kb)


@stats_match_router.callback_query(
    PostMatch.stats_pick_played,
    F.data.startswith("stpw:pp:"),
)
async def cb_stpw_played_page(callback: CallbackQuery, state: FSMContext) -> None:
    try:
        page = int((callback.data or "").rsplit(":", 1)[-1])
    except ValueError:
        await callback.answer()
        return
    await callback.answer()
    await _edit_played_ui(callback, state, page)


@stats_match_router.callback_query(
    PostMatch.stats_pick_played,
    F.data.startswith("stpw:sf:"),
)
async def cb_stpw_side_filter(callback: CallbackQuery, state: FSMContext) -> None:
    side = (callback.data or "").rsplit(":", 1)[-1]
    filt = None if side == "all" else side
    await callback.answer()
    await state.update_data(stats_side_filter=filt, stats_played_page=0)
    await _edit_played_ui(callback, state, 0)


@stats_match_router.callback_query(
    PostMatch.stats_pick_played,
    F.data.startswith("stpw:tp:"),
)
async def cb_stpw_toggle_played(callback: CallbackQuery, state: FSMContext) -> None:
    try:
        idx = int((callback.data or "").rsplit(":", 1)[-1])
    except ValueError:
        await callback.answer()
        return
    data = await state.get_data()
    played = _played_set(data)
    if idx in played:
        played.remove(idx)
    else:
        played.add(idx)
    await state.update_data(stats_played_idxs=sorted(played))
    page = int(data.get("stats_played_page") or 0)
    await callback.answer()
    await _edit_played_ui(callback, state, page)


@stats_match_router.callback_query(
    PostMatch.stats_pick_played,
    F.data == "stpw:played_done",
)
async def cb_stpw_played_done(callback: CallbackQuery, state: FSMContext) -> None:
    data = await state.get_data()
    played = _played_set(data)
    if not played:
        await callback.answer("Отметь хотя бы одного игрока.", show_alert=True)
        return
    await callback.answer("Записываю матчи…")

    players = _roster(data)
    tournament = data.get("stats_tournament", "league")
    logs = await asyncio.to_thread(
        apply_played_appearances,
        players,
        played,
        tournament=tournament,
    )
    tail = "\n".join(logs[:12])
    more = f"\n…ещё {len(logs) - 12}" if len(logs) > 12 else ""

    await state.set_state(PostMatch.stats_pick_player)
    await state.update_data(stats_stat_page=0, stats_cur_player_idx=None)
    if callback.message:
        kb, tp = _stat_pick_kb(await state.get_data(), page=0)
        await callback.message.answer(
            f"Матчи в БД: <b>{len(logs)}</b> игроков.\n<pre>{html_escape(tail)}{html_escape(more)}</pre>",
            parse_mode="HTML",
        )
        await callback.message.answer(
            _stat_intro_html(await state.get_data(), page=0, total_pages=tp),
            parse_mode="HTML",
            reply_markup=kb,
        )


@stats_match_router.callback_query(
    StateFilter(PostMatch.stats_pick_player, PostMatch.stats_wait_player_line),
    F.data.startswith("stpw:spg:"),
)
async def cb_stpw_stat_page(callback: CallbackQuery, state: FSMContext) -> None:
    try:
        page = int((callback.data or "").rsplit(":", 1)[-1])
    except ValueError:
        await callback.answer()
        return
    await callback.answer()
    await state.set_state(PostMatch.stats_pick_player)
    await _edit_stat_ui(callback, state, page)


@stats_match_router.callback_query(
    StateFilter(PostMatch.stats_pick_player, PostMatch.stats_wait_player_line),
    F.data.startswith("stpw:sp:"),
)
async def cb_stpw_pick_player(callback: CallbackQuery, state: FSMContext) -> None:
    try:
        idx = int((callback.data or "").rsplit(":", 1)[-1])
    except ValueError:
        await callback.answer()
        return
    data = await state.get_data()
    p = player_by_idx(_roster(data), idx)
    if not p or idx not in _played_set(data):
        await callback.answer("Игрок не в списке сыгравших.", show_alert=True)
        return
    await callback.answer()
    await state.update_data(stats_cur_player_idx=idx)
    await state.set_state(PostMatch.stats_wait_player_line)
    if callback.message:
        acc_s = format_player_acc(get_player_acc(data, idx))
        if acc_s:
            cur_block = (
                f"Текущий итог: <code>{html_escape(acc_s)}</code>\n"
                "Дополни строкой, например: <code>0 1 жк</code>\n"
            )
        else:
            cur_block = (
                "Отправь строку — любые фрагменты:\n"
                "<code>1 0</code> · <code>-1 1</code> · <code>жк</code> · "
                "<code>cs</code> · <code>1 0 жк</code>\n"
            )
        kb = InlineKeyboardMarkup(
            inline_keyboard=[
                [
                    InlineKeyboardButton(
                        text="← К списку",
                        callback_data="stpw:back_stat",
                    )
                ]
            ]
        )
        await callback.message.edit_text(
            f"<b>{html_escape(p.name)}</b> · {html_escape(p.position)} · "
            f"{html_escape(p.team)}\n\n{cur_block}",
            parse_mode="HTML",
            reply_markup=kb,
        )


@stats_match_router.callback_query(
    PostMatch.stats_wait_player_line,
    F.data == "stpw:back_stat",
)
async def cb_stpw_back_stat(callback: CallbackQuery, state: FSMContext) -> None:
    await callback.answer()
    await state.set_state(PostMatch.stats_pick_player)
    page = int((await state.get_data()).get("stats_stat_page") or 0)
    await _edit_stat_ui(callback, state, page)


@stats_match_router.callback_query(
    StateFilter(PostMatch.stats_pick_player, PostMatch.stats_wait_player_line),
    F.data == "stpw:back_played",
)
async def cb_stpw_back_played(callback: CallbackQuery, state: FSMContext) -> None:
    await callback.answer()
    await state.set_state(PostMatch.stats_pick_played)
    page = int((await state.get_data()).get("stats_played_page") or 0)
    await _edit_played_ui(callback, state, page)


@stats_match_router.message(PostMatch.stats_wait_player_line, _TEXT_NOT_CMD)
async def on_stpw_player_line(message: Message, state: FSMContext) -> None:
    data = await state.get_data()
    idx = data.get("stats_cur_player_idx")
    if idx is None:
        await message.answer("Сначала выбери игрока кнопкой.")
        return
    p = player_by_idx(_roster(data), int(idx))
    if not p:
        await message.answer("Игрок не найден в сессии.")
        return

    parsed = parse_player_stat_line(message.text or "")
    if parsed.parse_errors:
        await message.answer("\n".join(parsed.parse_errors))
        return

    acc = get_player_acc(data, int(idx))
    logs = await asyncio.to_thread(
        apply_player_stat_line,
        p,
        parsed,
        session_acc=acc,
        home_team=data["stats_home"],
        away_team=data["stats_away"],
        home_score=int(data["stats_hs"]),
        away_score=int(data["stats_aws"]),
        tournament=data.get("stats_tournament", "league"),
        league_code=data.get("stats_league_code"),
        schedule_day=data.get("stats_schedule_day"),
    )

    if logs and any(
        s.startswith("Голов в матче") or s.startswith("Передач в матче") for s in logs
    ):
        await message.answer("\n".join(logs))
        return
    if logs and any("✗" in s for s in logs):
        await message.answer("\n".join(logs))
        return

    merge_player_acc(acc, parsed)
    acc_bag = set_player_acc(data, int(idx), acc)
    await state.update_data(stats_player_acc=acc_bag)

    await state.set_state(PostMatch.stats_pick_player)
    acc_after = format_player_acc(acc)
    tail_lines = list(logs)
    if acc_after:
        tail_lines.append(f"Итог: {acc_after}")
    tail = html_escape("\n".join(tail_lines))
    page = int(data.get("stats_stat_page") or 0)
    kb, tp = _stat_pick_kb(await state.get_data(), page=page)
    await message.answer(f"<pre>{tail}</pre>", parse_mode="HTML")
    await message.answer(
        _stat_intro_html(await state.get_data(), page=page, total_pages=tp),
        parse_mode="HTML",
        reply_markup=kb,
    )


@stats_match_router.message(PostMatch.stats_pick_played, _TEXT_NOT_CMD)
async def on_stpw_stray_played(message: Message) -> None:
    await message.answer("Отмечай игроков кнопками, затем «Далее к стате».")


@stats_match_router.message(PostMatch.stats_pick_player, _TEXT_NOT_CMD)
async def on_stpw_stray_pick(message: Message) -> None:
    await message.answer("Выбери игрока кнопкой или «Готово».")
