# -*- coding: utf-8 -*-
"""Меню ЧМ в боте: жеребьёвка, группы, календарь м.11, вызовы."""
from __future__ import annotations

import asyncio
import io
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
_SQUAD_PAGE = 8

_STATUS_ICON = {"start": "🟢", "bench": "🟡", "reserve": "⚪"}
_STATUS_LABEL = {"start": "старт", "bench": "запас", "reserve": "резерв", "remove": "снять"}
_ASSIGN_MODES = ("start", "bench", "reserve", "remove")
_WC_ASSIGN_MODE_KEY = "wc_assign_mode"


def _norm_assign_mode(raw: str | None) -> str:
    m = (raw or "reserve").strip().lower()
    return m if m in _ASSIGN_MODES else "reserve"


def _mode_hint(mode: str) -> str:
    mode = _norm_assign_mode(mode)
    if mode == "remove":
        return "➖ Снять"
    return _STATUS_LABEL.get(mode, mode)


def _player_row_label(
    name: str,
    position: str | None,
    overall: int | str | None,
    *,
    prefix: str = "",
    suffix: str = "",
    nickname: str | None = None,
    max_len: int = 64,
) -> str:
    """Подпись строки игрока: имя · позиция · рейтинг (лимит Telegram — 64)."""
    from utils.player_nicknames import is_complex_player_name

    pos = (position or "—").strip() or "—"
    ovr = overall if overall not in (None, "") else "—"
    tail = f" · {pos} · {ovr}"
    if suffix:
        tail += f" · {suffix}"

    def _with_display(display: str) -> str:
        return f"{prefix}{display}{tail}"

    nick = (nickname or "").strip()
    prefer_nick = bool(nick) and (
        is_complex_player_name(name) or len(_with_display(name)) > max_len
    )
    if prefer_nick:
        nick_label = _with_display(nick)
        if len(nick_label) <= max_len:
            return nick_label

    label = _with_display(name)
    if len(label) <= max_len:
        return label

    if nick:
        nick_label = _with_display(nick)
        if len(nick_label) <= max_len:
            return nick_label

    budget = max_len - len(tail) - len(prefix) - 1
    if budget < 2:
        return f"{prefix}…{tail}"[:max_len]
    short = name if len(name) <= budget else name[: budget - 1] + "…"
    return _with_display(short)


def _mode_buttons_row(
    prefix: str,
    nation_idx: int,
    page: int,
    active: str,
) -> list[InlineKeyboardButton]:
    active = _norm_assign_mode(active)
    btns: list[InlineKeyboardButton] = []
    for key, label in (
        ("start", "🟢 Старт"),
        ("bench", "🟡 Запас"),
        ("reserve", "⚪ Резерв"),
    ):
        text = f"▸ {label}" if key == active else label
        btns.append(
            InlineKeyboardButton(
                text=text,
                callback_data=f"{prefix}:m:{nation_idx}:{page}:{key}",
            )
        )
    rm = "▸ ➖ Снять" if active == "remove" else "➖ Снять"
    btns.append(
        InlineKeyboardButton(
            text=rm,
            callback_data=f"{prefix}:m:{nation_idx}:{page}:remove",
        )
    )
    return btns


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
                InlineKeyboardButton(text="📥 Пул игроков", callback_data="wc:pools:export"),
            ],
            [
                InlineKeyboardButton(text="📥 Заявки ЧМ", callback_data="wc:squads:import"),
                InlineKeyboardButton(text="📤 Заявки ЧМ", callback_data="wc:squads:export"),
            ],
            [
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


@wc_router.callback_query(F.data == "wc:pools:export")
async def cb_wc_pools_export(callback: CallbackQuery) -> None:
    await callback.answer("Готовлю сборные…")
    if not callback.message:
        return
    try:
        from aiogram.types import BufferedInputFile
        from utils.transfer_export import export_national_pools_bundle_for_bot

        txt, jtext, meta = await asyncio.to_thread(export_national_pools_bundle_for_bot)
        nations = len(meta.get("nations") or [])
        players = int(meta.get("player_count") or 0)
        season = meta.get("season") or "?"
        cap = (
            f"📥 Сборные · сезон {season}\n"
            f"{nations} наций, {players} игроков (клуб + FA)\n"
            f"Transfer app: «Загрузить сборные» или import national_pools.json"
        )
        await callback.message.answer_document(
            BufferedInputFile(txt.encode("utf-8"), filename="national_pools.txt"),
            caption=cap,
        )
        await callback.message.answer_document(
            BufferedInputFile(jtext.encode("utf-8"), filename="national_pools.json"),
            caption="📋 JSON для transfer app",
        )
    except Exception as e:
        logger.exception("wc national pools export")
        await callback.message.answer(f"✗ {html_escape(str(e))}", parse_mode="HTML")


@wc_router.callback_query(F.data == "wc:squads:export")
async def cb_wc_squads_export(callback: CallbackQuery) -> None:
    await callback.answer("Готовлю заявки…")
    if not callback.message:
        return
    try:
        from aiogram.types import BufferedInputFile
        from utils.transfer_export import export_wc_squads_txt_for_bot

        txt = await asyncio.to_thread(export_wc_squads_txt_for_bot)
        n_blocks = txt.count("\n@") + (1 if txt.startswith("@") else 0)
        cap = (
            f"📤 Заявки ЧМ · {n_blocks} сборных\n"
            f"Transfer app: режим «Сборные ЧМ» → Загрузить заявки"
        )
        await callback.message.answer_document(
            BufferedInputFile(txt.encode("utf-8"), filename="wc_squads_export.txt"),
            caption=cap,
        )
    except Exception as e:
        logger.exception("wc squads export")
        await callback.message.answer(f"✗ {html_escape(str(e))}", parse_mode="HTML")


@wc_router.callback_query(F.data == "wc:squads:import")
async def cb_wc_squads_import_start(callback: CallbackQuery, state: FSMContext) -> None:
    await callback.answer()
    await state.set_state(WcEnter.squad_import)
    if callback.message:
        await callback.message.answer(
            "📥 Отправь <code>wc_squads_export.txt</code> из transfer app "
            "(режим «Сборные ЧМ» → Выгрузить заявки).\n"
            "/cancel — отмена.",
            parse_mode="HTML",
        )


@wc_router.message(StateFilter(WcEnter.squad_import), F.document)
async def on_wc_squads_import_file(message: Message, state: FSMContext) -> None:
    doc = message.document
    if doc is None or not doc.file_name:
        await message.answer("✗ Нужен файл-документ.", parse_mode="HTML")
        return
    fn = doc.file_name.lower()
    if not fn.endswith(".txt"):
        await message.answer("✗ Нужен .txt (<code>wc_squads_export.txt</code>).", parse_mode="HTML")
        return
    buf = io.BytesIO()
    await message.bot.download(doc, destination=buf)
    try:
        text = buf.getvalue().decode("utf-8")
    except UnicodeDecodeError:
        text = buf.getvalue().decode("utf-8-sig")
    if "@" not in text or "==== start ===" not in text.lower():
        await message.answer(
            "✗ Не похоже на wc_squads_export: нужны блоки <code>@Нация</code>, "
            "<code>coach:</code>, <code>formation_id:</code>.",
            parse_mode="HTML",
        )
        return
    try:
        from utils.wc_squad_app import import_wc_squads_export_txt

        stats = await asyncio.to_thread(import_wc_squads_export_txt, text, apply_db=True)
    except Exception as e:
        logger.exception("wc squads import")
        await message.answer(f"✗ {html_escape(str(e))}", parse_mode="HTML")
        return
    await state.clear()
    await message.answer(
        f"✓ Заявки ЧМ применены\n"
        f"• сборных: <b>{stats.get('teams_parsed') or stats.get('nations') or 0}</b>\n"
        f"• игроков в БД: <b>{stats.get('players') or 0}</b>",
        parse_mode="HTML",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[_back_home_row()]),
    )


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


def _players_kb(
    nation_idx: int,
    page: int,
    players: list[dict],
    status_by_name: dict[str, str],
    assign_mode: str,
) -> InlineKeyboardMarkup:
    pages = max(1, (len(players) + _PLAYERS_PAGE - 1) // _PLAYERS_PAGE)
    page = max(0, min(page, pages - 1))
    chunk = players[page * _PLAYERS_PAGE : (page + 1) * _PLAYERS_PAGE]
    rows: list[list[InlineKeyboardButton]] = []
    for i, p in enumerate(chunk):
        nk = p["name"].casefold()
        st = status_by_name.get(nk)
        if st:
            mark = _STATUS_ICON.get(st, "✅") + " "
        else:
            mark = "➕ "
        label = _player_row_label(
            p["name"],
            p.get("position"),
            p.get("overall"),
            prefix=mark,
            nickname=p.get("nickname"),
        )
        rows.append(
            [
                InlineKeyboardButton(
                    text=label,
                    callback_data=f"wc:call:a:{nation_idx}:{page}:{i}",
                )
            ]
        )
    rows.append(_mode_buttons_row("wc:call", nation_idx, page, assign_mode))
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
                text="📋 Заявка 26", callback_data=f"wc:sq:n:{nation_idx}"
            ),
            InlineKeyboardButton(
                text="📄 Заявка текстом", callback_data=f"wc:call:sq:{nation_idx}"
            ),
        ]
    )
    rows.append(
        [
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
    assign_mode: str | None = None,
) -> None:
    nations = _nations_sorted()
    if nation_idx < 0 or nation_idx >= len(nations):
        await callback.answer("Нет такой сборной", show_alert=True)
        return
    nation = nations[nation_idx]
    from utils.wc_callups import club_players_for_nation, squad_for_nation
    from utils.wc_squad_quota import evaluate_wc_squad, format_wc_quota_summary_html

    data = await state.get_data()
    if assign_mode is None:
        assign_mode = _norm_assign_mode(data.get(_WC_ASSIGN_MODE_KEY))
    else:
        assign_mode = _norm_assign_mode(assign_mode)
        await state.update_data(**{_WC_ASSIGN_MODE_KEY: assign_mode})

    players = await asyncio.to_thread(club_players_for_nation, nation)
    roster = squad_for_nation(nation)
    from utils.wc_callups import squad_status_map

    status_map = squad_status_map(nation)
    ev = evaluate_wc_squad(roster)
    await state.set_state(WcEnter.callup_players)
    await state.update_data(wc_nation_idx=nation_idx, wc_players=players)
    text = (
        f"<b>{html_escape(nation)}</b>\n"
        f"В клубах найдено: <b>{len(players)}</b>\n"
        f"{format_wc_quota_summary_html(ev)}\n"
        f"Режим: <b>{html_escape(_mode_hint(assign_mode))}</b> — тап по игроку.\n"
        f"Повторный тап (тот же режим) — снять · FA — «Вне клубов»."
    )
    await _edit(
        callback,
        text,
        _players_kb(nation_idx, page, players, status_map, assign_mode),
    )


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


@wc_router.callback_query(F.data.startswith("wc:call:m:"))
async def cb_call_mode(callback: CallbackQuery, state: FSMContext) -> None:
    parts = callback.data.split(":")
    try:
        nation_idx = int(parts[3])
        page = int(parts[4])
        mode = parts[5]
    except (IndexError, ValueError):
        await callback.answer()
        return
    await callback.answer(_mode_hint(mode))
    await _show_nation_players(callback, state, nation_idx, page, assign_mode=mode)


@wc_router.callback_query(F.data.startswith("wc:call:a:"))
async def cb_call_assign(callback: CallbackQuery, state: FSMContext) -> None:
    parts = callback.data.split(":")
    try:
        nation_idx = int(parts[3])
        page = int(parts[4])
        local_idx = int(parts[5])
    except (IndexError, ValueError):
        await callback.answer()
        return
    await _apply_call_assign(callback, state, nation_idx, page, local_idx)


async def _apply_call_assign(
    callback: CallbackQuery,
    state: FSMContext,
    nation_idx: int,
    page: int,
    local_idx: int,
) -> None:
    nations = _nations_sorted()
    if nation_idx < 0 or nation_idx >= len(nations):
        await callback.answer()
        return
    nation = nations[nation_idx]
    from utils.wc_callups import club_players_for_nation

    players = await asyncio.to_thread(club_players_for_nation, nation)
    abs_idx = page * _PLAYERS_PAGE + local_idx
    if abs_idx < 0 or abs_idx >= len(players):
        await callback.answer("Обновляю список…")
        await _show_nation_players(callback, state, nation_idx, page)
        return
    p = players[abs_idx]
    data = await state.get_data()
    mode = _norm_assign_mode(data.get(_WC_ASSIGN_MODE_KEY))
    from utils.wc_callups import remove_from_squad, toggle_assign_player_to_squad

    try:
        if mode == "remove":
            ok = await asyncio.to_thread(remove_from_squad, nation, p["name"])
            if not ok:
                await callback.answer("Не в заявке", show_alert=True)
                return
            await callback.answer("Снят")
        else:
            action, _ = await asyncio.to_thread(
                toggle_assign_player_to_squad,
                nation,
                name=p["name"],
                club=p.get("club") or "",
                position=p.get("position") or "",
                overall=int(p.get("overall") or 0),
                status=mode,
            )
            if action == "removed":
                await callback.answer("Снят")
            else:
                await callback.answer(_STATUS_LABEL.get(mode, mode))
    except Exception as e:
        await callback.answer(str(e)[:180], show_alert=True)
        return
    await _show_nation_players(callback, state, nation_idx, page)


@wc_router.callback_query(F.data.startswith("wc:call:t:"))
async def cb_call_toggle_legacy(callback: CallbackQuery, state: FSMContext) -> None:
    parts = callback.data.split(":")
    try:
        nation_idx = int(parts[3])
        page = int(parts[4])
        local_idx = int(parts[5])
    except (IndexError, ValueError):
        await callback.answer()
        return
    await _apply_call_assign(callback, state, nation_idx, page, local_idx)


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
    from utils.wc_callups import club_players_for_nation, squad_for_nation, squad_status_map
    from utils.wc_squad_quota import evaluate_wc_squad, format_wc_quota_summary_html

    players = await asyncio.to_thread(club_players_for_nation, nation)
    roster = squad_for_nation(nation)
    status_map = squad_status_map(nation)
    ev = evaluate_wc_squad(roster)
    assign_mode = _norm_assign_mode(data.get(_WC_ASSIGN_MODE_KEY))
    await state.update_data(wc_players=players)
    text = (
        f"<b>{html_escape(nation)}</b>\n"
        f"В клубах/FA: <b>{len(players)}</b>\n"
        f"{format_wc_quota_summary_html(ev)}\n"
        f"Режим: <b>{html_escape(_mode_hint(assign_mode))}</b> — тап по игроку."
    )
    await message.answer(
        text,
        reply_markup=_players_kb(nation_idx, page, players, status_map, assign_mode),
        parse_mode="HTML",
    )


def _sorted_roster(roster: list[dict]) -> list[dict]:
    order = {"start": 0, "bench": 1, "reserve": 2, "": 3}

    def key(p: dict) -> tuple:
        st = str(p.get("status") or "").strip().lower()
        if st not in order:
            st = ""
        return (
            order[st],
            -int(p.get("overall") or 0),
            str(p.get("name") or "").casefold(),
        )

    return sorted(roster, key=key)


def _squad_roster_kb(
    nation_idx: int,
    page: int,
    roster: list[dict],
    assign_mode: str,
) -> InlineKeyboardMarkup:
    from utils.player_nicknames import get_nickname_for_player

    sorted_r = _sorted_roster(roster)
    pages = max(1, (len(sorted_r) + _SQUAD_PAGE - 1) // _SQUAD_PAGE)
    page = max(0, min(page, pages - 1))
    chunk = sorted_r[page * _SQUAD_PAGE : (page + 1) * _SQUAD_PAGE]
    rows: list[list[InlineKeyboardButton]] = []
    for i, p in enumerate(chunk):
        st = str(p.get("status") or "reserve").strip().lower()
        if st not in _STATUS_ICON:
            st = "reserve"
        icon = _STATUS_ICON[st]
        lab = _STATUS_LABEL.get(st, st)
        name = str(p.get("name") or "")
        nick = p.get("nickname") or get_nickname_for_player(
            name=name,
            team=p.get("club"),
            person_id=p.get("person_id"),
        )
        label = _player_row_label(
            name,
            p.get("position"),
            p.get("overall"),
            prefix=f"{icon} ",
            suffix=lab,
            nickname=nick,
        )
        rows.append(
            [
                InlineKeyboardButton(
                    text=label,
                    callback_data=f"wc:sq:a:{nation_idx}:{page}:{i}",
                )
            ]
        )
    rows.append(_mode_buttons_row("wc:sq", nation_idx, page, assign_mode))
    nav: list[InlineKeyboardButton] = []
    if page > 0:
        nav.append(
            InlineKeyboardButton(text="⬅️", callback_data=f"wc:sq:pg:{nation_idx}:{page - 1}")
        )
    if page < pages - 1:
        nav.append(
            InlineKeyboardButton(text="➡️", callback_data=f"wc:sq:pg:{nation_idx}:{page + 1}")
        )
    if nav:
        rows.append(nav)
    rows.append(
        [
            InlineKeyboardButton(
                text="✅ Подтвердить заявку", callback_data=f"wc:sq:done:{nation_idx}"
            )
        ]
    )
    rows.append(
        [
            InlineKeyboardButton(
                text="🖼 Схема", callback_data=f"wc:sq:png:{nation_idx}"
            ),
            InlineKeyboardButton(
                text="✏️ Строками", callback_data=f"wc:sq:edit:{nation_idx}"
            ),
        ]
    )
    rows.append(
        [
            InlineKeyboardButton(
                text="⬅️ К игрокам", callback_data=f"wc:call:np:{nation_idx}:0"
            )
        ]
    )
    rows.append(_back_home_row())
    return InlineKeyboardMarkup(inline_keyboard=rows)


async def _show_squad_roster(
    callback: CallbackQuery,
    state: FSMContext,
    nation_idx: int,
    page: int = 0,
    assign_mode: str | None = None,
) -> None:
    nations = _nations_sorted()
    if nation_idx < 0 or nation_idx >= len(nations):
        await callback.answer("Нет такой сборной", show_alert=True)
        return
    nation = nations[nation_idx]
    from utils.wc_callups import squad_for_nation
    from utils.wc_squad_quota import evaluate_wc_squad, format_wc_quota_summary_html

    data = await state.get_data()
    if assign_mode is None:
        assign_mode = _norm_assign_mode(data.get(_WC_ASSIGN_MODE_KEY))
    else:
        assign_mode = _norm_assign_mode(assign_mode)
        await state.update_data(**{_WC_ASSIGN_MODE_KEY: assign_mode})

    roster = squad_for_nation(nation)
    ev = evaluate_wc_squad(roster)
    n = len(roster)
    text = (
        f"<b>{html_escape(nation)}</b> · заявка 26\n"
        f"{format_wc_quota_summary_html(ev)}\n\n"
        f"Игроков в заявке: <b>{n}</b>\n"
        f"Режим: <b>{html_escape(_mode_hint(assign_mode))}</b> — тап по игроку.\n"
        f"Повторный тап (тот же режим) — снять с заявки."
    )
    await _edit(
        callback,
        text,
        _squad_roster_kb(nation_idx, page, roster, assign_mode),
    )


def _squad_manage_kb(nation_idx: int) -> InlineKeyboardMarkup:
    """Клавиатура под PNG (возврат в редактор заявки)."""
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="📋 Заявка 26", callback_data=f"wc:sq:n:{nation_idx}"
                ),
            ],
            _back_home_row(),
        ]
    )


_SQUAD_LINES_HELP = (
    "Отправь строки (можно несколько):\n"
    "<code>Имя start [LW]</code>\n"
    "<code>Имя bench</code>\n"
    "<code>Имя reserve</code>\n\n"
    "Слоты старта 4-3-3 ат: <code>LW ST RW LCM CAM RCM LB LCB RCB RB GK</code>\n"
    "На слот можно поставить любого — позиция в БД не важна.\n\n"
    "26 игроков: 11 старт + 7 запас + 8 резерв · 2 ВРТ (1 в старте, 1 в запасе/резерве).\n"
    "/cancel — отмена."
)


@wc_router.callback_query(F.data.startswith("wc:sq:n:"))
async def cb_squad_manage(callback: CallbackQuery, state: FSMContext) -> None:
    await callback.answer()
    try:
        nation_idx = int(callback.data.split(":")[-1])
    except ValueError:
        return
    await _show_squad_roster(callback, state, nation_idx, 0)


@wc_router.callback_query(F.data.startswith("wc:sq:pg:"))
async def cb_squad_page(callback: CallbackQuery, state: FSMContext) -> None:
    await callback.answer()
    parts = callback.data.split(":")
    try:
        nation_idx = int(parts[3])
        page = int(parts[4])
    except (IndexError, ValueError):
        return
    await _show_squad_roster(callback, state, nation_idx, page)


@wc_router.callback_query(F.data.startswith("wc:sq:m:"))
async def cb_squad_mode(callback: CallbackQuery, state: FSMContext) -> None:
    parts = callback.data.split(":")
    try:
        nation_idx = int(parts[3])
        page = int(parts[4])
        mode = parts[5]
    except (IndexError, ValueError):
        await callback.answer()
        return
    await callback.answer(_mode_hint(mode))
    await _show_squad_roster(callback, state, nation_idx, page, assign_mode=mode)


@wc_router.callback_query(F.data.startswith("wc:sq:a:"))
async def cb_squad_assign(callback: CallbackQuery, state: FSMContext) -> None:
    parts = callback.data.split(":")
    try:
        nation_idx = int(parts[3])
        page = int(parts[4])
        local_idx = int(parts[5])
    except (IndexError, ValueError):
        await callback.answer()
        return
    await _apply_squad_assign(callback, state, nation_idx, page, local_idx)


@wc_router.callback_query(F.data.startswith("wc:sq:cyc:"))
async def cb_squad_cycle_status(callback: CallbackQuery, state: FSMContext) -> None:
    parts = callback.data.split(":")
    try:
        nation_idx = int(parts[3])
        page = int(parts[4])
        local_idx = int(parts[5])
    except (IndexError, ValueError):
        await callback.answer()
        return
    await _apply_squad_assign(callback, state, nation_idx, page, local_idx)


async def _apply_squad_assign(
    callback: CallbackQuery,
    state: FSMContext,
    nation_idx: int,
    page: int,
    local_idx: int,
) -> None:
    nations = _nations_sorted()
    if nation_idx < 0 or nation_idx >= len(nations):
        await callback.answer()
        return
    nation = nations[nation_idx]
    from utils.wc_callups import remove_from_squad, squad_for_nation, toggle_squad_player_status

    roster = _sorted_roster(squad_for_nation(nation))
    abs_idx = page * _SQUAD_PAGE + local_idx
    if abs_idx < 0 or abs_idx >= len(roster):
        await callback.answer("Обновляю…")
        await _show_squad_roster(callback, state, nation_idx, page)
        return
    name = str(roster[abs_idx].get("name") or "")
    data = await state.get_data()
    mode = _norm_assign_mode(data.get(_WC_ASSIGN_MODE_KEY))
    try:
        if mode == "remove":
            ok = await asyncio.to_thread(remove_from_squad, nation, name)
            if not ok:
                await callback.answer("Не в заявке", show_alert=True)
                return
            await callback.answer("Снят")
        else:
            action, _ = await asyncio.to_thread(
                toggle_squad_player_status, nation, name, mode
            )
            if action == "removed":
                await callback.answer("Снят")
            else:
                await callback.answer(_STATUS_LABEL.get(mode, mode))
    except Exception as e:
        await callback.answer(str(e)[:180], show_alert=True)
        return
    await _show_squad_roster(callback, state, nation_idx, page)


@wc_router.callback_query(F.data.startswith("wc:sq:done:"))
async def cb_squad_confirm(callback: CallbackQuery, state: FSMContext) -> None:
    try:
        nation_idx = int(callback.data.split(":")[-1])
    except ValueError:
        await callback.answer()
        return
    nations = _nations_sorted()
    if nation_idx < 0 or nation_idx >= len(nations):
        await callback.answer()
        return
    nation = nations[nation_idx]
    from utils.wc_callups import squad_for_nation
    from utils.wc_squad_quota import evaluate_wc_squad, format_wc_quota_hint

    ev = evaluate_wc_squad(squad_for_nation(nation))
    if ev.get("complete"):
        await callback.answer("✅ Заявка полная: 26/26", show_alert=True)
    else:
        hint = format_wc_quota_hint(ev)
        await callback.answer(f"⚠️ {hint}"[:200], show_alert=True)
    await _show_squad_roster(callback, state, nation_idx, 0)


@wc_router.callback_query(F.data.startswith("wc:sq:png:"))
async def cb_squad_png(callback: CallbackQuery) -> None:
    await callback.answer("Рисую схему…")
    try:
        nation_idx = int(callback.data.split(":")[-1])
    except ValueError:
        return
    nations = _nations_sorted()
    if nation_idx < 0 or nation_idx >= len(nations):
        return
    nation = nations[nation_idx]
    from bot.squad_pitch import render_squad_pitch_png_bytes

    try:
        png = await asyncio.to_thread(render_squad_pitch_png_bytes, nation, "wc")
    except Exception as e:
        logger.exception("wc squad png")
        await callback.answer(str(e)[:180], show_alert=True)
        return
    if callback.message:
        from aiogram.types import BufferedInputFile

        await callback.message.answer_photo(
            BufferedInputFile(png, filename="wc_squad.png"),
            caption=f"{nation} · 4-3-3 ат",
            reply_markup=_squad_manage_kb(nation_idx),
        )


@wc_router.callback_query(F.data.startswith("wc:sq:edit:"))
async def cb_squad_edit_start(callback: CallbackQuery, state: FSMContext) -> None:
    await callback.answer()
    try:
        nation_idx = int(callback.data.split(":")[-1])
    except ValueError:
        return
    nations = _nations_sorted()
    if nation_idx < 0 or nation_idx >= len(nations):
        return
    await state.set_state(WcEnter.squad_lines)
    await state.update_data(wc_nation_idx=nation_idx)
    if callback.message:
        await callback.message.answer(
            f"<b>{html_escape(nations[nation_idx])}</b> — расстановка заявки\n\n{_SQUAD_LINES_HELP}",
            parse_mode="HTML",
        )


@wc_router.message(StateFilter(WcEnter.squad_lines))
async def on_squad_lines(message: Message, state: FSMContext) -> None:
    if (message.text or "").strip().casefold() in ("/cancel", "отмена"):
        await state.set_state(WcEnter.callup_players)
        await message.answer("Отменено.")
        return
    data = await state.get_data()
    nation_idx = int(data.get("wc_nation_idx") or 0)
    nations = _nations_sorted()
    if nation_idx < 0 or nation_idx >= len(nations):
        await state.clear()
        await message.answer("Сессия сброшена. /wc")
        return
    nation = nations[nation_idx]
    from utils.wc_squad_lines import apply_wc_squad_status_lines
    from utils.wc_squad_quota import evaluate_wc_squad, format_wc_quota_hint

    try:
        res = await asyncio.to_thread(apply_wc_squad_status_lines, nation, message.text or "")
    except Exception as e:
        await message.answer(f"✗ {html_escape(str(e))}", parse_mode="HTML")
        return
    lines: list[str] = []
    if res.ok:
        lines.append(f"✓ Обновлено: <b>{len(res.ok)}</b>")
        for row in res.ok[:12]:
            lines.append(f"· {html_escape(row)}")
        if len(res.ok) > 12:
            lines.append(f"… ещё {len(res.ok) - 12}")
    if res.errors:
        lines.append(f"\n✗ Ошибки: <b>{len(res.errors)}</b>")
        for err in res.errors[:8]:
            lines.append(f"· {html_escape(err)}")
    if not res.ok and not res.errors:
        await message.answer("Пустой ввод.")
        return
    from utils.wc_callups import squad_for_nation

    ev = evaluate_wc_squad(squad_for_nation(nation))
    hint = format_wc_quota_hint(ev)
    if hint != "OK":
        lines.append(f"\n⚠️ {html_escape(hint)}")
    elif ev.get("complete"):
        lines.append("\n✅ Заявка полная (26/26)")
    await state.set_state(WcEnter.callup_players)
    await message.answer("\n".join(lines), parse_mode="HTML")
    await message.answer(
        "Меню заявки:",
        reply_markup=InlineKeyboardMarkup(
            inline_keyboard=[
                [
                    InlineKeyboardButton(
                        text="📋 Заявка 26", callback_data=f"wc:sq:n:{nation_idx}"
                    )
                ]
            ]
        ),
    )
