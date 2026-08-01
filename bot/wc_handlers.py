# -*- coding: utf-8 -*-
"""Меню ЧМ в боте: жеребьёвка, группы, календарь м.11, вызовы."""
from __future__ import annotations

import asyncio
import logging
from html import escape as html_escape

from aiogram import F, Router
from aiogram.filters import Command, StateFilter
from aiogram.fsm.context import FSMContext
from aiogram.types import (
    CallbackQuery,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    Message,
)

from bot.states import WcEnter

logger = logging.getLogger(__name__)

wc_router = Router()

_NATIONS_PAGE = 12
_PLAYERS_PAGE = 10


def _wc_home_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(text="🎲 Жеребьёвка групп", callback_data="wc:draw"),
            ],
            [
                InlineKeyboardButton(text="📋 Группы", callback_data="wc:groups:0"),
                InlineKeyboardButton(text="📅 Месяц 11", callback_data="wc:cal"),
            ],
            [
                InlineKeyboardButton(text="📣 Вызовы", callback_data="wc:call:home"),
                InlineKeyboardButton(text="👤 Менеджеры", callback_data="wc:mgr"),
            ],
            [
                InlineKeyboardButton(text="⚽ Схемы сборных", callback_data="squadlg:wc"),
                InlineKeyboardButton(text="🎨 Логотип", callback_data="wc:logo"),
            ],
            [
                InlineKeyboardButton(text="ℹ️ Формат", callback_data="wc:rules"),
            ],
            [InlineKeyboardButton(text="✖️ Закрыть", callback_data="wc:close")],
        ]
    )


def _logo_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="🎲 Другой хост / стиль", callback_data="wc:logo:reroll"
                )
            ],
            _back_home_row(),
        ]
    )


def _branding_line(season: int) -> str:
    try:
        from utils.wc_branding import ensure_branding

        b = ensure_branding(season)
        host = html_escape(str(b.get("host") or "?"))
        sn = int(b.get("season") or season)
        style = html_escape(str(b.get("style") or ""))
        return f"Хост логотипа: <b>{host}</b> · сезон {sn} · стиль <code>{style}</code>"
    except Exception:
        return ""


async def _send_wc_logo(message, *, season: int, reroll: bool = False) -> None:
    import time

    from aiogram.types import BufferedInputFile

    from bot.wc_logo import render_wc_logo_png_bytes
    from utils.wc_branding import ensure_branding

    brand = await asyncio.to_thread(ensure_branding, season, force=reroll)
    png = await asyncio.to_thread(
        render_wc_logo_png_bytes, season, branding=brand, use_cache=not reroll
    )
    host = brand.get("host") or "?"
    sn = brand.get("season") or season
    style = brand.get("style") or ""
    cap = f"🎨 ЧМ · {host} · сезон {sn} · {style}"
    await message.answer_photo(
        BufferedInputFile(png, filename=f"wc_logo_{season}_{time.time_ns()}.png"),
        caption=cap,
        reply_markup=_logo_kb(),
    )


def _back_home_row() -> list[InlineKeyboardButton]:
    return [InlineKeyboardButton(text="⬅️ ЧМ", callback_data="wc:home")]


async def _edit(cb: CallbackQuery, text: str, kb: InlineKeyboardMarkup) -> None:
    try:
        await cb.message.edit_text(text, reply_markup=kb, parse_mode="HTML")
    except Exception:
        await cb.message.answer(text, reply_markup=kb, parse_mode="HTML")


@wc_router.message(Command("wc"))
async def cmd_wc(message: Message, state: FSMContext) -> None:
    await state.clear()
    from utils.world_cup import is_world_cup_season, next_world_cup_season
    from utils import season_paths

    sn = season_paths.get_active_season()
    if is_world_cup_season(sn):
        head = f"🌍 <b>Чемпионат мира</b> · сезон {sn}"
    else:
        head = (
            f"🌍 <b>ЧМ</b>\n"
            f"Сейчас сезон {sn} — турнир в сезоне <b>{next_world_cup_season(sn)}</b>.\n"
            f"Меню доступно для подготовки (жеребьёвка / вызовы)."
        )
    brand = _branding_line(sn)
    if brand:
        head = head + "\n" + brand
    await message.answer(head + "\n\nВыберите:", reply_markup=_wc_home_kb(), parse_mode="HTML")


@wc_router.callback_query(F.data == "menu:wc")
async def cb_menu_wc(callback: CallbackQuery, state: FSMContext) -> None:
    await callback.answer()
    await state.clear()
    from utils.world_cup import is_world_cup_season, next_world_cup_season
    from utils import season_paths

    sn = season_paths.get_active_season()
    if is_world_cup_season(sn):
        head = f"🌍 <b>Чемпионат мира</b> · сезон {sn}"
    else:
        head = (
            f"🌍 <b>ЧМ</b> (подготовка)\n"
            f"Турнир — сезон <b>{next_world_cup_season(sn)}</b>."
        )
    brand = _branding_line(sn)
    if brand:
        head = head + "\n" + brand
    await _edit(callback, head + "\n\nВыберите:", _wc_home_kb())


@wc_router.callback_query(F.data == "wc:home")
async def cb_wc_home(callback: CallbackQuery, state: FSMContext) -> None:
    await callback.answer()
    await state.clear()
    from utils import season_paths

    sn = season_paths.get_active_season()
    brand = _branding_line(sn)
    text = "🌍 <b>ЧМ</b>"
    if brand:
        text += "\n" + brand
    text += "\n\nВыберите:"
    await _edit(callback, text, _wc_home_kb())


@wc_router.callback_query(F.data == "wc:logo")
async def cb_wc_logo(callback: CallbackQuery) -> None:
    await callback.answer("Рисую логотип…")
    from utils import season_paths

    try:
        await _send_wc_logo(callback.message, season=season_paths.get_active_season())
    except Exception as e:
        logger.exception("wc logo")
        await callback.message.answer(f"Не удалось нарисовать логотип: {e}")


@wc_router.callback_query(F.data == "wc:logo:reroll")
async def cb_wc_logo_reroll(callback: CallbackQuery) -> None:
    await callback.answer("Новый хост…")
    from utils import season_paths

    try:
        await _send_wc_logo(
            callback.message, season=season_paths.get_active_season(), reroll=True
        )
    except Exception as e:
        logger.exception("wc logo reroll")
        await callback.message.answer(f"Не удалось: {e}")


@wc_router.callback_query(F.data == "wc:close")
async def cb_wc_close(callback: CallbackQuery, state: FSMContext) -> None:
    await state.clear()
    await callback.answer()
    try:
        await callback.message.delete()
    except Exception:
        await callback.message.edit_text("ЧМ закрыто.")


@wc_router.callback_query(F.data == "wc:rules")
async def cb_wc_rules(callback: CallbackQuery) -> None:
    await callback.answer()
    from utils.world_cup_format import format_rules_ru

    text = "<b>Формат ЧМ</b>\n\n" + html_escape(format_rules_ru())
    kb = InlineKeyboardMarkup(inline_keyboard=[_back_home_row()])
    await _edit(callback, text, kb)


@wc_router.callback_query(F.data == "wc:mgr")
async def cb_wc_mgr(callback: CallbackQuery) -> None:
    await callback.answer()
    from utils.wc_tournament import managers_html

    text = managers_html()
    if len(text) > 3900:
        text = text[:3900] + "\n…"
    kb = InlineKeyboardMarkup(inline_keyboard=[_back_home_row()])
    await _edit(callback, text, kb)


@wc_router.callback_query(F.data == "wc:draw")
async def cb_wc_draw(callback: CallbackQuery) -> None:
    await callback.answer()
    from utils.wc_tournament import groups_drawn, load_tournament

    if groups_drawn():
        data = load_tournament()
        text = (
            f"<b>Жеребьёвка уже есть</b> (seed={data.get('draw_seed')}).\n"
            f"Можно пережеребить или посмотреть группы."
        )
        kb = InlineKeyboardMarkup(
            inline_keyboard=[
                [
                    InlineKeyboardButton(
                        text="♻️ Пережеребить", callback_data="wc:draw:force"
                    )
                ],
                [
                    InlineKeyboardButton(text="📋 Группы", callback_data="wc:groups:0"),
                ],
                _back_home_row(),
            ]
        )
        await _edit(callback, text, kb)
        return
    kb = InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="✅ Провести жеребьёвку", callback_data="wc:draw:run"
                )
            ],
            _back_home_row(),
        ]
    )
    await _edit(
        callback,
        "<b>Жеребьёвка групп ЧМ</b>\n\n"
        "4 корзины × 12, лимиты конфедераций,\n"
        "в каждой группе <b>2 Roman + 2 Lika</b>.\n"
        "После жеребьёвки матчи группы пишутся в месяц <b>11</b>.",
        kb,
    )


@wc_router.callback_query(F.data.in_({"wc:draw:run", "wc:draw:force"}))
async def cb_wc_draw_run(callback: CallbackQuery) -> None:
    force = callback.data == "wc:draw:force"
    await callback.answer("Жеребьёвка…")
    from utils.wc_tournament import manager_of_map, run_group_draw
    from utils.world_cup_format import groups_manager_balance

    try:
        data = await asyncio.to_thread(run_group_draw, force=force)
    except Exception as e:
        logger.exception("wc draw")
        kb = InlineKeyboardMarkup(inline_keyboard=[_back_home_row()])
        await _edit(callback, f"Ошибка жеребьёвки: {html_escape(str(e))}", kb)
        return
    bal_ok, _ = groups_manager_balance(data.get("groups") or {}, manager_of_map(data))
    bal = "✓ баланс 2+2 Roman/Lika" if bal_ok else "⚠ проверьте баланс менеджеров"
    text = (
        f"✅ <b>Жеребьёвка готова</b>\n"
        f"Сезон {data.get('season')} · seed={data.get('draw_seed')}\n"
        f"{bal}\n\n"
        f"Откройте группы или проверьте месяц 11."
    )
    kb = InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="📋 Группы", callback_data="wc:groups:0")],
            [InlineKeyboardButton(text="📅 Месяц 11", callback_data="wc:cal")],
            _back_home_row(),
        ]
    )
    await _edit(callback, text, kb)


@wc_router.callback_query(F.data.startswith("wc:groups:"))
async def cb_wc_groups(callback: CallbackQuery) -> None:
    await callback.answer()
    from utils.wc_tournament import (
        ensure_manager_balanced_groups,
        groups_drawn,
        groups_html,
        load_tournament,
    )
    from utils.world_cup_format import GROUP_IDS as GIDS

    # если баланс 2+2 нарушен — пережеребить автоматически
    try:
        await asyncio.to_thread(ensure_manager_balanced_groups)
    except Exception:
        logger.exception("wc ensure manager balance")

    suffix = callback.data.split(":")[-1]
    if suffix == "all":
        text = groups_html()
        if len(text) > 3900:
            text = text[:3900] + "\n…"
        kb = InlineKeyboardMarkup(
            inline_keyboard=[
                [InlineKeyboardButton(text="📋 По страницам", callback_data="wc:groups:0")],
                _back_home_row(),
            ]
        )
        await _edit(callback, text, kb)
        return

    try:
        page = int(suffix)
    except ValueError:
        page = 0
    data = load_tournament()
    if not groups_drawn():
        kb = InlineKeyboardMarkup(
            inline_keyboard=[
                [InlineKeyboardButton(text="🎲 Жеребьёвка", callback_data="wc:draw")],
                _back_home_row(),
            ]
        )
        await _edit(callback, "Группы ещё не разыграны.", kb)
        return

    # 3 группы на страницу
    per = 3
    ids = list(GIDS)
    pages = (len(ids) + per - 1) // per
    page = max(0, min(page, pages - 1))
    chunk = ids[page * per : (page + 1) * per]
    lines = [f"<b>ЧМ · группы</b> ({page + 1}/{pages})", ""]
    groups = data.get("groups") or {}
    for gid in chunk:
        teams = groups.get(gid) or []
        lines.append(f"<b>Группа {gid}</b>")
        for t in teams:
            lines.append(f"· {html_escape(str(t))}")
        lines.append("")
    nav: list[InlineKeyboardButton] = []
    if page > 0:
        nav.append(
            InlineKeyboardButton(text="⬅️", callback_data=f"wc:groups:{page - 1}")
        )
    if page < pages - 1:
        nav.append(
            InlineKeyboardButton(text="➡️", callback_data=f"wc:groups:{page + 1}")
        )
    rows: list[list[InlineKeyboardButton]] = []
    if nav:
        rows.append(nav)
    rows.append(
        [InlineKeyboardButton(text="📜 Все текстом", callback_data="wc:groups:all")]
    )
    rows.append(_back_home_row())
    await _edit(callback, "\n".join(lines).rstrip(), InlineKeyboardMarkup(inline_keyboard=rows))


@wc_router.callback_query(F.data == "wc:cal")
async def cb_wc_cal(callback: CallbackQuery) -> None:
    await callback.answer()
    from utils.wc_schedule import ensure_wc_group_stage_in_schedule, month11_wc_summary

    summary = await asyncio.to_thread(month11_wc_summary)
    text = f"<b>Календарь ЧМ</b>\n\n{summary}"
    kb = InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="➕ Дописать группу в м.11", callback_data="wc:cal:sync"
                )
            ],
            [
                InlineKeyboardButton(
                    text="♻️ Перезаписать м.11", callback_data="wc:cal:replace"
                )
            ],
            _back_home_row(),
        ]
    )
    await _edit(callback, text, kb)


@wc_router.callback_query(F.data.in_({"wc:cal:sync", "wc:cal:replace"}))
async def cb_wc_cal_sync(callback: CallbackQuery) -> None:
    replace = callback.data == "wc:cal:replace"
    await callback.answer("Пишем календарь…")
    from utils.wc_schedule import ensure_wc_group_stage_in_schedule, month11_wc_summary

    ok, msg = await asyncio.to_thread(
        ensure_wc_group_stage_in_schedule, replace_existing=replace
    )
    summary = await asyncio.to_thread(month11_wc_summary)
    text = f"{'✅' if ok else 'ℹ️'} {msg}\n\n{summary}"
    kb = InlineKeyboardMarkup(inline_keyboard=[_back_home_row()])
    await _edit(callback, text, kb)


# --- вызовы ---


def _nations_sorted() -> list[str]:
    from utils.world_cup import load_wc_config

    return list(load_wc_config().get("nations") or [])


def _call_nations_kb(page: int) -> InlineKeyboardMarkup:
    nations = _nations_sorted()
    pages = max(1, (len(nations) + _NATIONS_PAGE - 1) // _NATIONS_PAGE)
    page = max(0, min(page, pages - 1))
    chunk = nations[page * _NATIONS_PAGE : (page + 1) * _NATIONS_PAGE]
    rows: list[list[InlineKeyboardButton]] = []
    row: list[InlineKeyboardButton] = []
    for i, name in enumerate(chunk):
        idx = page * _NATIONS_PAGE + i
        label = name if len(name) <= 18 else name[:17] + "…"
        row.append(InlineKeyboardButton(text=label, callback_data=f"wc:call:n:{idx}"))
        if len(row) == 2:
            rows.append(row)
            row = []
    if row:
        rows.append(row)
    nav: list[InlineKeyboardButton] = []
    if page > 0:
        nav.append(InlineKeyboardButton(text="⬅️", callback_data=f"wc:call:p:{page - 1}"))
    if page < pages - 1:
        nav.append(InlineKeyboardButton(text="➡️", callback_data=f"wc:call:p:{page + 1}"))
    if nav:
        rows.append(nav)
    rows.append(
        [InlineKeyboardButton(text="📊 Сводка заявок", callback_data="wc:call:sum")]
    )
    rows.append(_back_home_row())
    return InlineKeyboardMarkup(inline_keyboard=rows)


@wc_router.callback_query(F.data == "wc:call:home")
async def cb_call_home(callback: CallbackQuery, state: FSMContext) -> None:
    await callback.answer()
    await state.set_state(WcEnter.callup_nation)
    from utils.wc_callups import squad_summary_html

    text = squad_summary_html() + "\n\nВыберите сборную:"
    await _edit(callback, text, _call_nations_kb(0))


@wc_router.callback_query(F.data.startswith("wc:call:p:"))
async def cb_call_page(callback: CallbackQuery, state: FSMContext) -> None:
    await callback.answer()
    await state.set_state(WcEnter.callup_nation)
    try:
        page = int(callback.data.split(":")[-1])
    except ValueError:
        page = 0
    from utils.wc_callups import squad_summary_html

    await _edit(
        callback,
        squad_summary_html() + "\n\nВыберите сборную:",
        _call_nations_kb(page),
    )


@wc_router.callback_query(F.data == "wc:call:sum")
async def cb_call_sum(callback: CallbackQuery) -> None:
    await callback.answer()
    from utils.wc_callups import squad_summary_html
    from utils.world_cup import load_wc_squads

    data = load_wc_squads()
    teams = data.get("teams") or {}
    lines = [squad_summary_html(), ""]
    for name in sorted(teams.keys(), key=lambda x: x.casefold()):
        n = len(teams[name] or [])
        if n:
            lines.append(f"· {html_escape(name)} — {n}")
    kb = InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="📣 К сборным", callback_data="wc:call:home")],
            _back_home_row(),
        ]
    )
    text = "\n".join(lines)
    if len(text) > 3900:
        text = text[:3900] + "\n…"
    await _edit(callback, text, kb)


def _players_kb(nation_idx: int, page: int, players: list[dict], called: set[str]) -> InlineKeyboardMarkup:
    pages = max(1, (len(players) + _PLAYERS_PAGE - 1) // _PLAYERS_PAGE)
    page = max(0, min(page, pages - 1))
    chunk = players[page * _PLAYERS_PAGE : (page + 1) * _PLAYERS_PAGE]
    rows: list[list[InlineKeyboardButton]] = []
    for i, p in enumerate(chunk):
        idx = page * _PLAYERS_PAGE + i
        mark = "✅ " if p["name"].casefold() in called else ""
        label = f"{mark}{p['name']} · {p.get('overall') or '—'}"
        if len(label) > 36:
            label = label[:35] + "…"
        rows.append(
            [
                InlineKeyboardButton(
                    text=label,
                    callback_data=f"wc:call:t:{nation_idx}:{page}:{idx}",
                )
            ]
        )
    nav: list[InlineKeyboardButton] = []
    if page > 0:
        nav.append(
            InlineKeyboardButton(
                text="⬅️", callback_data=f"wc:call:np:{nation_idx}:{page - 1}"
            )
        )
    if page < pages - 1:
        nav.append(
            InlineKeyboardButton(
                text="➡️", callback_data=f"wc:call:np:{nation_idx}:{page + 1}"
            )
        )
    if nav:
        rows.append(nav)
    rows.append(
        [
            InlineKeyboardButton(
                text="📄 Заявка текстом", callback_data=f"wc:call:sq:{nation_idx}"
            ),
            InlineKeyboardButton(
                text="➕ Вне клубов", callback_data=f"wc:call:fa:{nation_idx}:{page}"
            ),
        ]
    )
    rows.append(
        [InlineKeyboardButton(text="⬅️ Сборные", callback_data="wc:call:home")]
    )
    rows.append(_back_home_row())
    return InlineKeyboardMarkup(inline_keyboard=rows)


async def _show_nation_players(
    callback: CallbackQuery,
    state: FSMContext,
    nation_idx: int,
    page: int = 0,
) -> None:
    nations = _nations_sorted()
    if nation_idx < 0 or nation_idx >= len(nations):
        await callback.answer("Нет такой сборной", show_alert=True)
        return
    nation = nations[nation_idx]
    from utils.wc_callups import club_players_for_nation, squad_for_nation

    players = await asyncio.to_thread(club_players_for_nation, nation)
    called = {str(p.get("name") or "").casefold() for p in squad_for_nation(nation)}
    await state.set_state(WcEnter.callup_players)
    await state.update_data(wc_nation_idx=nation_idx, wc_players=players)
    n_called = len(called)
    text = (
        f"<b>{html_escape(nation)}</b>\n"
        f"В клубах найдено: <b>{len(players)}</b> · в заявке: <b>{n_called}</b>\n"
        f"Тап = вызов / снять. FA без клуба — кнопка «Вне клубов»."
    )
    await _edit(callback, text, _players_kb(nation_idx, page, players, called))


@wc_router.callback_query(F.data.startswith("wc:call:n:"))
async def cb_call_nation(callback: CallbackQuery, state: FSMContext) -> None:
    await callback.answer()
    try:
        idx = int(callback.data.split(":")[-1])
    except ValueError:
        return
    await _show_nation_players(callback, state, idx, 0)


@wc_router.callback_query(F.data.startswith("wc:call:np:"))
async def cb_call_nation_page(callback: CallbackQuery, state: FSMContext) -> None:
    await callback.answer()
    parts = callback.data.split(":")
    try:
        nation_idx = int(parts[3])
        page = int(parts[4])
    except (IndexError, ValueError):
        return
    await _show_nation_players(callback, state, nation_idx, page)


@wc_router.callback_query(F.data.startswith("wc:call:t:"))
async def cb_call_toggle(callback: CallbackQuery, state: FSMContext) -> None:
    parts = callback.data.split(":")
    try:
        nation_idx = int(parts[3])
        page = int(parts[4])
        local_idx = int(parts[5])
    except (IndexError, ValueError):
        await callback.answer()
        return
    data = await state.get_data()
    players = data.get("wc_players") or []
    abs_idx = page * _PLAYERS_PAGE + local_idx
    if abs_idx < 0 or abs_idx >= len(players):
        # перезагрузить список
        await callback.answer()
        await _show_nation_players(callback, state, nation_idx, page)
        return
    p = players[abs_idx]
    nations = _nations_sorted()
    nation = nations[nation_idx]
    from utils.wc_callups import toggle_callup

    try:
        added, _ = await asyncio.to_thread(
            toggle_callup,
            nation,
            name=p["name"],
            club=p.get("club") or "",
            position=p.get("position") or "",
            overall=int(p.get("overall") or 0),
        )
    except Exception as e:
        await callback.answer(str(e)[:180], show_alert=True)
        return
    await callback.answer("Вызван" if added else "Снят")
    await _show_nation_players(callback, state, nation_idx, page)


@wc_router.callback_query(F.data.startswith("wc:call:sq:"))
async def cb_call_squad_text(callback: CallbackQuery) -> None:
    await callback.answer()
    try:
        nation_idx = int(callback.data.split(":")[-1])
    except ValueError:
        return
    nations = _nations_sorted()
    if nation_idx < 0 or nation_idx >= len(nations):
        return
    from utils.wc_callups import squad_summary_html

    text = squad_summary_html(nations[nation_idx])
    if len(text) > 3900:
        text = text[:3900] + "\n…"
    kb = InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="⬅️ К игрокам",
                    callback_data=f"wc:call:np:{nation_idx}:0",
                )
            ],
            _back_home_row(),
        ]
    )
    await _edit(callback, text, kb)


@wc_router.callback_query(F.data.startswith("wc:call:fa:"))
async def cb_call_add_fa_start(callback: CallbackQuery, state: FSMContext) -> None:
    await callback.answer()
    parts = callback.data.split(":")
    try:
        nation_idx = int(parts[3])
        page = int(parts[4])
    except (IndexError, ValueError):
        return
    nations = _nations_sorted()
    if nation_idx < 0 or nation_idx >= len(nations):
        return
    await state.set_state(WcEnter.callup_manual_fa)
    await state.update_data(wc_nation_idx=nation_idx, wc_page=page)
    if callback.message:
        await callback.message.answer(
            f"<b>{html_escape(nations[nation_idx])}</b> — игрок <b>без клуба</b>\n\n"
            "Отправь одной строкой:\n"
            "<code>Имя Позиция Рейтинг</code>\n"
            "Пример: <code>Иванов ST 75</code>\n\n"
            "/cancel — отмена.",
            parse_mode="HTML",
        )


@wc_router.message(StateFilter(WcEnter.callup_manual_fa))
async def on_call_manual_fa_line(message: Message, state: FSMContext) -> None:
    if (message.text or "").strip().casefold() in ("/cancel", "отмена"):
        await state.set_state(WcEnter.callup_players)
        await message.answer("Отменено.")
        return
    data = await state.get_data()
    nation_idx = int(data.get("wc_nation_idx") or 0)
    page = int(data.get("wc_page") or 0)
    nations = _nations_sorted()
    if nation_idx < 0 or nation_idx >= len(nations):
        await state.clear()
        await message.answer("Сессия сброшена. /wc")
        return
    nation = nations[nation_idx]
    parts = (message.text or "").strip().split()
    if len(parts) < 3 or not parts[-1].isdigit():
        await message.answer(
            "Нужен формат: <code>Имя Позиция Рейтинг</code>",
            parse_mode="HTML",
        )
        return
    ovr = int(parts[-1])
    pos = parts[-2]
    name = " ".join(parts[:-2])
    from utils.wc_callups import add_fa_player_for_nation_callup

    try:
        entry = await asyncio.to_thread(
            add_fa_player_for_nation_callup,
            nation,
            name=name,
            position=pos,
            overall=ovr,
        )
    except Exception as e:
        await message.answer(f"✗ {html_escape(str(e))}", parse_mode="HTML")
        return
    await state.set_state(WcEnter.callup_players)
    await message.answer(
        f"✓ Добавлен в FA и заявку: <b>{html_escape(entry.get('name') or name)}</b> "
        f"· {html_escape(str(entry.get('position') or pos))} · {ovr}",
        parse_mode="HTML",
    )
    from utils.wc_callups import club_players_for_nation, squad_for_nation

    players = await asyncio.to_thread(club_players_for_nation, nation)
    called = {str(p.get("name") or "").casefold() for p in squad_for_nation(nation)}
    await state.update_data(wc_players=players)
    n_called = len(called)
    text = (
        f"<b>{html_escape(nation)}</b>\n"
        f"В клубах/FA: <b>{len(players)}</b> · в заявке: <b>{n_called}</b>\n"
        f"Тап = вызов / снять вызов."
    )
    await message.answer(
        text, reply_markup=_players_kb(nation_idx, page, players, called), parse_mode="HTML"
    )
