# -*- coding: utf-8 -*-
"""Меню «История»: чемпионы, награды, клубы, сравнения, менеджеры, обложки."""
from __future__ import annotations

import asyncio
import logging
from typing import Any

from aiogram import F, Router
from aiogram.types import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup

from bot.history_render import (
    render_award_history_png,
    render_cl_history_png,
    render_league_history_png,
    render_special_cups_history_png,
    render_wc_history_png,
)
from bot.history_champion_squad import (
    champion_seasons_cl,
    champion_seasons_league,
    render_champion_squad_pages,
)
from bot.services import LEAGUE_LABELS, teams_ordered_for_goalscorers
from bot.team_history import format_season_tag, list_history_seasons
from bot.team_history_gallery import (
    render_club_career_conceded_pages,
    render_club_career_goals_pages,
    render_club_hall_of_fame_png,
    render_club_player_influence_png,
    render_club_season_matches_png,
    render_compare_clubs_png,
    render_h2h_png,
    render_hall_of_fame_png,
    render_heatmap_png,
    render_managers_png,
    render_nation_career_goals_pages,
    render_prestige_dynamics_png,
    render_pvp_kryptonite_detail_png,
    render_pvp_kryptonite_list_png,
    render_season_cover_png,
)
from bot.team_history_render import (
    render_attack_rating_pages,
    render_club_dossier_png,
    render_defense_rating_pages,
    render_league_titles_chart_png,
    render_nation_power_ranking_pages,
    render_nation_prestige_breakdown_pages,
    render_power_ranking_pages,
    render_prestige_breakdown_pages,
    render_wc_titles_chart_png,
)

logger = logging.getLogger(__name__)

history_router = Router()

# user_id -> {"mode": "cmp"|"h2h", "a": (league, idx)|None}
_pending_two: dict[int, dict[str, Any]] = {}
# user_id -> list[kryptonite row dict] для кнопок детализации
_krypto_cache: dict[int, list[dict[str, Any]]] = {}
_KRYPTO_PAGE_SIZE = 12

_AWARD_CAPTION = {
    "golden_ball": "Золотой мяч",
    "golden_boot": "Золотая бутса",
    "golden_glove": "Золотая перчатка",
    "golden_boy": "Golden Boy",
    "world_cup_best": "Лучший игрок ЧМ",
}


def history_root_kb() -> InlineKeyboardMarkup:
    rows: list[list[InlineKeyboardButton]] = [
        [
            InlineKeyboardButton(text="🏠 Лига", callback_data="hist:pick_league"),
            InlineKeyboardButton(text="⭐ ЛЧ", callback_data="hist:cl"),
        ],
        [
            InlineKeyboardButton(text="🌍 ЧМ", callback_data="hist:wc"),
            InlineKeyboardButton(text="🏆 Особые кубки", callback_data="hist:special_cups"),
        ],
        [
            InlineKeyboardButton(text="⚽ ЗМ", callback_data="hist:a:golden_ball"),
            InlineKeyboardButton(text="👟 Бутса", callback_data="hist:a:golden_boot"),
        ],
        [
            InlineKeyboardButton(text="🧤 Перчатка", callback_data="hist:a:golden_glove"),
            InlineKeyboardButton(text="🌟 Golden Boy", callback_data="hist:a:golden_boy"),
        ],
        [
            InlineKeyboardButton(text="🌍 Лучший ЧМ", callback_data="hist:a:world_cup_best"),
        ],
        [
            InlineKeyboardButton(text="🏟 Клубы", callback_data="hist:teams"),
            InlineKeyboardButton(text="🌍 Сборные", callback_data="hist:nations"),
        ],
        [
            InlineKeyboardButton(text="🎖 Зал славы", callback_data="hist:hof"),
            InlineKeyboardButton(text="⚔ Сравнить", callback_data="hist:cmp"),
        ],
        [
            InlineKeyboardButton(text="🗺 H2H", callback_data="hist:h2h"),
        ],
        [
            InlineKeyboardButton(text="🏆 Победный состав", callback_data="hist:ws"),
            InlineKeyboardButton(text="🪨 PVP-криптониты", callback_data="hist:krypto"),
        ],
        [
            InlineKeyboardButton(text="👔 Менеджеры", callback_data="hist:mgr"),
            InlineKeyboardButton(text="🌡 Теплокарта", callback_data="hist:heat"),
        ],
        [
            InlineKeyboardButton(text="🖼 Обложка сезона", callback_data="hist:cover"),
        ],
    ]
    return InlineKeyboardMarkup(inline_keyboard=rows)


def history_teams_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="💪 Рейтинг силы", callback_data="hist:t:power")],
            [InlineKeyboardButton(text="📊 Из чего престиж", callback_data="hist:t:break")],
            [InlineKeyboardButton(text="🏆 Чемпионства (вес лиг)", callback_data="hist:t:titles")],
            [InlineKeyboardButton(text="⚽ Голы клубов", callback_data="hist:t:goals")],
            [InlineKeyboardButton(text="🛡 Пропущенные", callback_data="hist:t:conceded")],
            [InlineKeyboardButton(text="⚡ Рейтинг нападения", callback_data="hist:t:attack")],
            [InlineKeyboardButton(text="🧱 Рейтинг защиты", callback_data="hist:t:defense")],
            [InlineKeyboardButton(text="🔑 Влияние игрока", callback_data="hist:t:influence")],
            [InlineKeyboardButton(text="📁 Досье клуба", callback_data="hist:t:club")],
            [InlineKeyboardButton(text="« Назад", callback_data="hist:back")],
        ]
    )


def history_nations_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="💪 Рейтинг силы", callback_data="hist:n:power")],
            [InlineKeyboardButton(text="📊 Из чего престиж", callback_data="hist:n:break")],
            [InlineKeyboardButton(text="🏆 Чемпионства ЧМ", callback_data="hist:n:titles")],
            [InlineKeyboardButton(text="⚽ Голы сборных", callback_data="hist:n:goals")],
            [InlineKeyboardButton(text="📁 Досье сборной", callback_data="hist:n:dossier")],
            [InlineKeyboardButton(text="« Назад", callback_data="hist:back")],
        ]
    )


def history_winner_squad_root_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="🏠 Лига", callback_data="hist:ws:pick")],
            [InlineKeyboardButton(text="⭐ ЛЧ", callback_data="hist:ws:cl")],
            [InlineKeyboardButton(text="« Назад", callback_data="hist:back")],
        ]
    )


def _fit_team_btn(name: str, limit: int = 22) -> str:
    t = (name or "").strip()
    if len(t) <= limit:
        return t
    return t[: limit - 1] + "…"


def history_winner_squad_season_kb(
    rows: list[tuple[int, str]],
    *,
    prefix: str,
    back: str,
) -> InlineKeyboardMarkup:
    buttons: list[InlineKeyboardButton] = []
    for sn, team in rows:
        lab = f"{format_season_tag(sn)} · {_fit_team_btn(team)}"
        buttons.append(InlineKeyboardButton(text=lab, callback_data=f"{prefix}{sn}"))
    out_rows = [buttons[i : i + 2] for i in range(0, len(buttons), 2)]
    out_rows.append([InlineKeyboardButton(text="« Назад", callback_data=back)])
    return InlineKeyboardMarkup(inline_keyboard=out_rows)


def history_kryptonite_pick_kb(
    items: list[dict[str, Any]], *, page: int = 0, back: str = "hist:back"
) -> InlineKeyboardMarkup:
    n = len(items)
    total_pages = max(1, (n + _KRYPTO_PAGE_SIZE - 1) // _KRYPTO_PAGE_SIZE)
    page = max(0, min(int(page), total_pages - 1))
    start = page * _KRYPTO_PAGE_SIZE
    chunk = items[start : start + _KRYPTO_PAGE_SIZE]

    rows: list[list[InlineKeyboardButton]] = []
    row: list[InlineKeyboardButton] = []
    for i, r in enumerate(chunk):
        idx = start + i
        dom = str(r.get("dominant") or "")
        vic = str(r.get("victim") or "")
        lab = f"{_fit_team_btn(dom, 12)}→{_fit_team_btn(vic, 12)}"
        row.append(InlineKeyboardButton(text=lab, callback_data=f"hist:krypto:d:{idx}"))
        if len(row) == 2:
            rows.append(row)
            row = []
    if row:
        rows.append(row)

    if total_pages > 1:
        nav: list[InlineKeyboardButton] = []
        if page > 0:
            nav.append(InlineKeyboardButton(text="←", callback_data=f"hist:krypto:p:{page - 1}"))
        nav.append(
            InlineKeyboardButton(
                text=f"{page + 1}/{total_pages}",
                callback_data="hist:krypto:noop",
            )
        )
        if page < total_pages - 1:
            nav.append(InlineKeyboardButton(text="→", callback_data=f"hist:krypto:p:{page + 1}"))
        rows.append(nav)

    rows.append([InlineKeyboardButton(text="« Назад", callback_data=back)])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def _kryptonite_pick_caption(items: list[dict[str, Any]], page: int = 0) -> str:
    n = len(items)
    total_pages = max(1, (n + _KRYPTO_PAGE_SIZE - 1) // _KRYPTO_PAGE_SIZE)
    page = max(0, min(int(page), total_pages - 1))
    if total_pages <= 1:
        return f"Выбери пару для полной хронологии ({n}):"
    start = page * _KRYPTO_PAGE_SIZE + 1
    end = min(n, (page + 1) * _KRYPTO_PAGE_SIZE)
    return (
        f"Выбери пару для полной хронологии · "
        f"стр. {page + 1}/{total_pages} · пары {start}–{end} из {n}"
    )


def history_league_choice_kb(
    *,
    prefix: str,
    back: str,
    kind: str = "club",
) -> InlineKeyboardMarkup:
    """
    ``kind``: ``club`` — только нац. лиги; ``nation`` — только ЧМ; ``both`` — лиги + ЧМ.
    """
    buttons: list[InlineKeyboardButton] = []
    allow = (kind or "club").strip().lower()
    for code, label in LEAGUE_LABELS:
        if code == "cl":
            continue
        if code == "wc":
            if allow in ("both", "nation"):
                buttons.append(
                    InlineKeyboardButton(text="🌍 ЧМ · сборные", callback_data=f"{prefix}wc")
                )
            continue
        if allow in ("both", "club"):
            buttons.append(InlineKeyboardButton(text=label, callback_data=f"{prefix}{code}"))
    rows = [buttons[i : i + 2] for i in range(0, len(buttons), 2)]
    rows.append([InlineKeyboardButton(text="« Назад", callback_data=back)])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def history_nation_actions_kb(idx: int) -> InlineKeyboardMarkup:
    base = f"wc:{idx}"
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="📁 Досье", callback_data=f"hist:act:dossier:{base}")],
            [InlineKeyboardButton(text="📈 Динамика престижа", callback_data=f"hist:act:dyn:{base}")],
            [InlineKeyboardButton(text="📅 Матчи сезона", callback_data=f"hist:act:matches:{base}")],
            [InlineKeyboardButton(text="« Сборные", callback_data="hist:n:dossier")],
        ]
    )


def history_club_pick_kb(league_code: str, *, prefix: str, back: str) -> InlineKeyboardMarkup:
    teams = teams_ordered_for_goalscorers(league_code)
    rows: list[list[InlineKeyboardButton]] = []
    row: list[InlineKeyboardButton] = []
    for i, name in enumerate(teams):
        row.append(InlineKeyboardButton(text=name, callback_data=f"{prefix}{league_code}:{i}"))
        if len(row) == 2:
            rows.append(row)
            row = []
    if row:
        rows.append(row)
    rows.append([InlineKeyboardButton(text="« Лиги", callback_data=back)])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def history_club_actions_kb(league_code: str, idx: int) -> InlineKeyboardMarkup:
    base = f"{league_code}:{idx}"
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="📁 Досье", callback_data=f"hist:act:dossier:{base}")],
            [InlineKeyboardButton(text="🎖 Зал славы клуба", callback_data=f"hist:act:hof:{base}")],
            [InlineKeyboardButton(text="📈 Динамика престижа", callback_data=f"hist:act:dyn:{base}")],
            [InlineKeyboardButton(text="🔑 Влияние игрока", callback_data=f"hist:act:infl:{base}")],
            [InlineKeyboardButton(text="📅 Матчи сезона", callback_data=f"hist:act:matches:{base}")],
            [InlineKeyboardButton(text="« Клубы лиги", callback_data=f"hist:tcl:{league_code}")],
        ]
    )


def history_season_pick_kb(*, prefix: str, back: str) -> InlineKeyboardMarkup:
    seasons = list_history_seasons()
    rows: list[list[InlineKeyboardButton]] = []
    row: list[InlineKeyboardButton] = []
    for sn in seasons:
        row.append(
            InlineKeyboardButton(text=format_season_tag(sn), callback_data=f"{prefix}{sn}")
        )
        if len(row) == 3:
            rows.append(row)
            row = []
    if row:
        rows.append(row)
    rows.append([InlineKeyboardButton(text="« Назад", callback_data=back)])
    return InlineKeyboardMarkup(inline_keyboard=rows)


async def _send_png(
    callback: CallbackQuery,
    *,
    png: bytes | list[bytes],
    filename: str,
    caption: str,
) -> None:
    if not callback.message:
        return
    from bot.handlers import answer_png_pages

    blobs = [png] if isinstance(png, (bytes, bytearray)) else list(png)
    prefix = filename.rsplit(".", 1)[0] if filename else "history"
    await answer_png_pages(
        callback.message,
        blobs,
        caption,
        filename_prefix=prefix,
        parse_mode="HTML",
    )


def _team_by_idx(league_code: str, idx: int) -> str:
    return teams_ordered_for_goalscorers(league_code)[idx]


def _uid(callback: CallbackQuery) -> int:
    return int(callback.from_user.id) if callback.from_user else 0


@history_router.callback_query(F.data == "menu:history")
async def cb_menu_history(callback: CallbackQuery) -> None:
    await callback.answer()
    if not callback.message:
        return
    await callback.message.answer(
        "<b>История</b>\n\n"
        "Чемпионы, награды, клубы, сборные, сравнение, H2H, победный состав, "
        "PVP-криптониты, менеджеры, теплокарта, обложки сезонов.",
        reply_markup=history_root_kb(),
        parse_mode="HTML",
    )


@history_router.callback_query(F.data == "hist:back")
async def cb_hist_back(callback: CallbackQuery) -> None:
    await callback.answer()
    if callback.message:
        await callback.message.edit_reply_markup(reply_markup=history_root_kb())


@history_router.callback_query(F.data == "hist:teams")
async def cb_hist_teams(callback: CallbackQuery) -> None:
    await callback.answer()
    if callback.message:
        await callback.message.edit_reply_markup(reply_markup=history_teams_kb())


@history_router.callback_query(F.data == "hist:nations")
async def cb_hist_nations(callback: CallbackQuery) -> None:
    await callback.answer()
    if callback.message:
        await callback.message.edit_reply_markup(reply_markup=history_nations_kb())


@history_router.callback_query(F.data == "hist:n:power")
async def cb_hist_nation_power(callback: CallbackQuery) -> None:
    await callback.answer("Готовлю…")
    try:
        pages = await asyncio.to_thread(render_nation_power_ranking_pages, page_size=16)
    except Exception as e:
        logger.exception("nation power")
        if callback.message:
            await callback.message.answer(f"Ошибка: {e}")
        return
    n = len(pages)
    cap = (
        "<b>Рейтинг силы сборных</b>"
        if n <= 1
        else f"<b>Рейтинг силы сборных</b> · {n} стр."
    )
    await _send_png(callback, png=pages, filename="history_nation_power.png", caption=cap)


@history_router.callback_query(F.data == "hist:n:break")
async def cb_hist_nation_break(callback: CallbackQuery) -> None:
    await callback.answer("Готовлю…")
    try:
        pages = await asyncio.to_thread(render_nation_prestige_breakdown_pages, page_size=12)
    except Exception as e:
        logger.exception("nation break")
        if callback.message:
            await callback.message.answer(f"Ошибка: {e}")
        return
    n = len(pages)
    cap = (
        "<b>Из чего престиж сборных</b>"
        if n <= 1
        else f"<b>Из чего престиж сборных</b> · {n} стр."
    )
    await _send_png(callback, png=pages, filename="history_nation_break.png", caption=cap)


@history_router.callback_query(F.data == "hist:n:titles")
async def cb_hist_nation_titles(callback: CallbackQuery) -> None:
    await callback.answer("Готовлю…")
    try:
        png = await asyncio.to_thread(render_wc_titles_chart_png)
    except Exception as e:
        logger.exception("nation titles")
        if callback.message:
            await callback.message.answer(f"Ошибка: {e}")
        return
    await _send_png(
        callback, png=png, filename="history_wc_titles.png", caption="<b>Чемпионства мира</b>"
    )


@history_router.callback_query(F.data == "hist:n:goals")
async def cb_hist_nation_goals(callback: CallbackQuery) -> None:
    await callback.answer("Готовлю…")
    try:
        pages = await asyncio.to_thread(render_nation_career_goals_pages, page_size=16)
    except Exception as e:
        logger.exception("nation goals")
        if callback.message:
            await callback.message.answer(f"Ошибка: {e}")
        return
    n = len(pages)
    cap = (
        "<b>Голы сборных · ЧМ</b>"
        if n <= 1
        else f"<b>Голы сборных · ЧМ</b> · {n} стр."
    )
    await _send_png(callback, png=pages, filename="history_nation_goals.png", caption=cap)


@history_router.callback_query(F.data == "hist:n:dossier")
async def cb_hist_nation_dossier_pick(callback: CallbackQuery) -> None:
    await callback.answer()
    if callback.message:
        await callback.message.answer(
            "Выбери <b>сборную</b>:",
            reply_markup=history_club_pick_kb(
                "wc", prefix="hist:tn:", back="hist:nations"
            ),
            parse_mode="HTML",
        )


@history_router.callback_query(F.data.startswith("hist:tn:"))
async def cb_hist_nation_actions(callback: CallbackQuery) -> None:
    parts = (callback.data or "").split(":")
    if len(parts) != 4:
        await callback.answer()
        return
    code, idx_s = parts[2], parts[3]
    try:
        idx = int(idx_s)
        team = _team_by_idx(code, idx)
    except Exception:
        await callback.answer("Сборная не найдена", show_alert=True)
        return
    await callback.answer()
    if callback.message:
        await callback.message.answer(
            f"<b>{team}</b> — что показать?",
            reply_markup=history_nation_actions_kb(idx),
            parse_mode="HTML",
        )


@history_router.callback_query(F.data == "hist:pick_league")
async def cb_hist_pick_league(callback: CallbackQuery) -> None:
    await callback.answer()
    if callback.message:
        await callback.message.edit_reply_markup(
            reply_markup=history_league_choice_kb(prefix="hist:l:", back="hist:back")
        )


@history_router.callback_query(F.data.startswith("hist:l:"))
async def cb_hist_league(callback: CallbackQuery) -> None:
    parts = (callback.data or "").split(":")
    if len(parts) != 3:
        await callback.answer()
        return
    code = parts[2].strip()
    title = dict(LEAGUE_LABELS).get(code, code)
    await callback.answer("Готовлю…")
    try:
        png = await asyncio.to_thread(render_league_history_png, code, title)
    except Exception as e:
        logger.exception("render_league_history")
        if callback.message:
            await callback.message.answer(f"Ошибка: {e}")
        return
    await _send_png(
        callback,
        png=png,
        filename=f"history_{code}.png",
        caption=f"<b>{title}</b> — чемпионы",
    )


@history_router.callback_query(F.data == "hist:cl")
async def cb_hist_cl(callback: CallbackQuery) -> None:
    await callback.answer("Готовлю…")
    try:
        png = await asyncio.to_thread(render_cl_history_png)
    except Exception as e:
        logger.exception("render_cl_history")
        if callback.message:
            await callback.message.answer(f"Ошибка: {e}")
        return
    await _send_png(
        callback,
        png=png,
        filename="history_cl.png",
        caption="<b>ЛЧ</b> — победители",
    )


@history_router.callback_query(F.data == "hist:wc")
async def cb_hist_wc(callback: CallbackQuery) -> None:
    await callback.answer("Готовлю…")
    try:
        png = await asyncio.to_thread(render_wc_history_png)
    except Exception as e:
        logger.exception("render_wc_history")
        if callback.message:
            await callback.message.answer(f"Ошибка: {e}")
        return
    await _send_png(
        callback,
        png=png,
        filename="history_wc.png",
        caption="<b>Чемпионат мира</b>",
    )


@history_router.callback_query(F.data == "hist:special_cups")
async def cb_hist_special_cups(callback: CallbackQuery) -> None:
    await callback.answer("Готовлю…")
    try:
        png = await asyncio.to_thread(render_special_cups_history_png)
    except Exception as e:
        logger.exception("render_special_cups_history")
        if callback.message:
            await callback.message.answer(f"Ошибка: {e}")
        return
    await _send_png(
        callback,
        png=png,
        filename="history_special_cups.png",
        caption="<b>Особые кубки</b>",
    )


@history_router.callback_query(F.data.startswith("hist:a:"))
async def cb_hist_award(callback: CallbackQuery) -> None:
    parts = (callback.data or "").split(":")
    if len(parts) != 3:
        await callback.answer()
        return
    kind = parts[2].strip()
    await callback.answer("Готовлю…")
    try:
        png = await asyncio.to_thread(render_award_history_png, kind)
    except Exception as e:
        logger.exception("render_award_history")
        if callback.message:
            await callback.message.answer(f"Ошибка: {e}")
        return
    await _send_png(
        callback,
        png=png,
        filename=f"history_{kind}.png",
        caption=f"<b>{_AWARD_CAPTION.get(kind, kind)}</b>",
    )


@history_router.callback_query(F.data == "hist:t:power")
async def cb_hist_power(callback: CallbackQuery) -> None:
    await callback.answer("Готовлю…")
    try:
        pages = await asyncio.to_thread(render_power_ranking_pages, page_size=20)
    except Exception as e:
        logger.exception("power")
        if callback.message:
            await callback.message.answer(f"Ошибка: {e}")
        return
    n = len(pages)
    cap = "<b>Рейтинг силы</b>" if n <= 1 else f"<b>Рейтинг силы</b> · {n} стр."
    await _send_png(callback, png=pages, filename="history_power.png", caption=cap)


@history_router.callback_query(F.data == "hist:t:break")
async def cb_hist_break(callback: CallbackQuery) -> None:
    await callback.answer("Готовлю…")
    try:
        pages = await asyncio.to_thread(render_prestige_breakdown_pages, page_size=10)
    except Exception as e:
        logger.exception("break")
        if callback.message:
            await callback.message.answer(f"Ошибка: {e}")
        return
    n = len(pages)
    cap = "<b>Из чего престиж</b>" if n <= 1 else f"<b>Из чего престиж</b> · {n} стр."
    await _send_png(callback, png=pages, filename="history_break.png", caption=cap)


@history_router.callback_query(F.data == "hist:t:titles")
async def cb_hist_titles(callback: CallbackQuery) -> None:
    await callback.answer("Готовлю…")
    try:
        png = await asyncio.to_thread(render_league_titles_chart_png)
    except Exception as e:
        logger.exception("titles")
        if callback.message:
            await callback.message.answer(f"Ошибка: {e}")
        return
    await _send_png(callback, png=png, filename="history_titles.png", caption="<b>Чемпионства с весом</b>")


@history_router.callback_query(F.data == "hist:t:goals")
async def cb_hist_club_goals(callback: CallbackQuery) -> None:
    await callback.answer("Готовлю…")
    try:
        pages = await asyncio.to_thread(render_club_career_goals_pages, page_size=10)
    except Exception as e:
        logger.exception("club goals")
        if callback.message:
            await callback.message.answer(f"Ошибка: {e}")
        return
    n = len(pages)
    cap = (
        "<b>Голы клубов</b> — лига / ЛЧ / всего · все сезоны"
        if n <= 1
        else f"<b>Голы клубов</b> — лига / ЛЧ / всего · все сезоны · {n} стр."
    )
    await _send_png(
        callback,
        png=pages,
        filename="history_club_goals.png",
        caption=cap,
    )


@history_router.callback_query(F.data == "hist:t:conceded")
async def cb_hist_club_conceded(callback: CallbackQuery) -> None:
    await callback.answer("Готовлю…")
    try:
        pages = await asyncio.to_thread(render_club_career_conceded_pages, page_size=10)
    except Exception as e:
        logger.exception("club conceded")
        if callback.message:
            await callback.message.answer(f"Ошибка: {e}")
        return
    n = len(pages)
    cap = (
        "<b>Пропущенные</b> — меньше лучше · лига / ЛЧ / всего"
        if n <= 1
        else f"<b>Пропущенные</b> — меньше лучше · лига / ЛЧ / всего · {n} стр."
    )
    await _send_png(
        callback,
        png=pages,
        filename="history_club_conceded.png",
        caption=cap,
    )


@history_router.callback_query(F.data == "hist:t:attack")
async def cb_hist_attack(callback: CallbackQuery) -> None:
    await callback.answer("Готовлю…")
    try:
        pages = await asyncio.to_thread(render_attack_rating_pages, page_size=20)
    except Exception as e:
        logger.exception("attack rating")
        if callback.message:
            await callback.message.answer(f"Ошибка: {e}")
        return
    n = len(pages)
    cap = "<b>Рейтинг нападения</b>" if n <= 1 else f"<b>Рейтинг нападения</b> · {n} стр."
    await _send_png(callback, png=pages, filename="history_attack.png", caption=cap)


@history_router.callback_query(F.data == "hist:t:defense")
async def cb_hist_defense(callback: CallbackQuery) -> None:
    await callback.answer("Готовлю…")
    try:
        pages = await asyncio.to_thread(render_defense_rating_pages, page_size=20)
    except Exception as e:
        logger.exception("defense rating")
        if callback.message:
            await callback.message.answer(f"Ошибка: {e}")
        return
    n = len(pages)
    cap = "<b>Рейтинг защиты</b>" if n <= 1 else f"<b>Рейтинг защиты</b> · {n} стр."
    await _send_png(callback, png=pages, filename="history_defense.png", caption=cap)


@history_router.callback_query(F.data == "hist:t:influence")
async def cb_hist_influence_pick(callback: CallbackQuery) -> None:
    await callback.answer()
    if callback.message:
        await callback.message.edit_reply_markup(
            reply_markup=history_league_choice_kb(
                prefix="hist:inflg:", back="hist:teams"
            )
        )


@history_router.callback_query(F.data.startswith("hist:inflg:"))
async def cb_hist_influence_league(callback: CallbackQuery) -> None:
    parts = (callback.data or "").split(":")
    if len(parts) != 3:
        await callback.answer()
        return
    code = parts[2].strip()
    await callback.answer()
    if callback.message:
        await callback.message.edit_reply_markup(
            reply_markup=history_club_pick_kb(
                code, prefix="hist:infc:", back="hist:t:influence"
            )
        )


@history_router.callback_query(F.data.startswith("hist:infc:"))
async def cb_hist_influence_club(callback: CallbackQuery) -> None:
    parts = (callback.data or "").split(":")
    if len(parts) != 4:
        await callback.answer()
        return
    code, idx_s = parts[2], parts[3]
    try:
        idx = int(idx_s)
        team = _team_by_idx(code, idx)
    except Exception as e:
        await callback.answer(str(e), show_alert=True)
        return
    await callback.answer("Готовлю…")
    try:
        png = await asyncio.to_thread(render_club_player_influence_png, team)
    except Exception as e:
        logger.exception("player influence")
        if callback.message:
            await callback.message.answer(f"Ошибка: {e}")
        return
    await _send_png(
        callback,
        png=png,
        filename=f"influence_{code}_{idx}.png",
        caption=f"<b>Влияние игрока</b> · {team}",
    )


@history_router.callback_query(F.data == "hist:t:club")
async def cb_hist_club_pick_league(callback: CallbackQuery) -> None:
    await callback.answer()
    if callback.message:
        await callback.message.edit_reply_markup(
            reply_markup=history_league_choice_kb(prefix="hist:tcl:", back="hist:teams")
        )


@history_router.callback_query(F.data.startswith("hist:tcl:"))
async def cb_hist_club_league(callback: CallbackQuery) -> None:
    parts = (callback.data or "").split(":")
    if len(parts) != 3:
        await callback.answer()
        return
    code = parts[2].strip()
    await callback.answer()
    if callback.message:
        await callback.message.edit_reply_markup(
            reply_markup=history_club_pick_kb(
                code, prefix="hist:tc:", back="hist:t:club"
            )
        )


@history_router.callback_query(F.data.startswith("hist:tc:"))
async def cb_hist_club_actions(callback: CallbackQuery) -> None:
    parts = (callback.data or "").split(":")
    if len(parts) != 4:
        await callback.answer()
        return
    code, idx_s = parts[2], parts[3]
    try:
        idx = int(idx_s)
        team = _team_by_idx(code, idx)
    except Exception:
        await callback.answer("Клуб не найден", show_alert=True)
        return
    await callback.answer()
    if callback.message:
        await callback.message.answer(
            f"<b>{team}</b> — что показать?",
            reply_markup=history_club_actions_kb(code, idx),
            parse_mode="HTML",
        )


@history_router.callback_query(F.data.startswith("hist:act:"))
async def cb_hist_club_act(callback: CallbackQuery) -> None:
    parts = (callback.data or "").split(":")
    # hist:act:dossier:ita:0
    if len(parts) != 5:
        await callback.answer()
        return
    action, code, idx_s = parts[2], parts[3], parts[4]
    try:
        idx = int(idx_s)
        team = _team_by_idx(code, idx)
    except Exception:
        await callback.answer("Клуб не найден", show_alert=True)
        return

    if action == "matches":
        await callback.answer()
        if callback.message:
            await callback.message.answer(
                f"Сезон для матчей <b>{team}</b>:",
                reply_markup=history_season_pick_kb(
                    prefix=f"hist:cms:{code}:{idx}:",
                    back=f"hist:tc:{code}:{idx}",
                ),
                parse_mode="HTML",
            )
        return

    await callback.answer("Готовлю…")
    try:
        if action == "dossier":
            png = await asyncio.to_thread(render_club_dossier_png, team)
            cap = f"<b>{team}</b> — досье"
            fn = "dossier.png"
        elif action == "hof":
            png = await asyncio.to_thread(render_club_hall_of_fame_png, team)
            cap = f"<b>{team}</b> — зал славы"
            fn = "club_hof.png"
        elif action == "dyn":
            png = await asyncio.to_thread(render_prestige_dynamics_png, team)
            cap = f"<b>{team}</b> — динамика престижа"
            fn = "dyn.png"
        elif action == "infl":
            png = await asyncio.to_thread(render_club_player_influence_png, team)
            cap = f"<b>{team}</b> — влияние (основа: эвристика; скамья/резерв: матчи БД)"
            fn = "influence.png"
        else:
            await callback.answer("Неизвестно", show_alert=True)
            return
    except Exception as e:
        logger.exception("club act %s", action)
        if callback.message:
            await callback.message.answer(f"Ошибка: {e}")
        return
    await _send_png(callback, png=png, filename=fn, caption=cap)


@history_router.callback_query(F.data.startswith("hist:cms:"))
async def cb_hist_club_matches_season(callback: CallbackQuery) -> None:
    parts = (callback.data or "").split(":")
    # hist:cms:ita:0:2
    if len(parts) != 5:
        await callback.answer()
        return
    code, idx_s, sn_s = parts[2], parts[3], parts[4]
    try:
        team = _team_by_idx(code, int(idx_s))
        sn = int(sn_s)
    except Exception:
        await callback.answer("Ошибка", show_alert=True)
        return
    await callback.answer("Готовлю…")
    try:
        png = await asyncio.to_thread(render_club_season_matches_png, team, sn)
    except Exception as e:
        logger.exception("club matches")
        if callback.message:
            await callback.message.answer(f"Ошибка: {e}")
        return
    await _send_png(
        callback,
        png=png,
        filename=f"matches_{sn}.png",
        caption=f"<b>{team}</b> — матчи · {format_season_tag(sn)}",
    )


@history_router.callback_query(F.data == "hist:hof")
async def cb_hist_hof(callback: CallbackQuery) -> None:
    await callback.answer("Готовлю…")
    try:
        png = await asyncio.to_thread(render_hall_of_fame_png, limit=20)
    except Exception as e:
        logger.exception("hof")
        if callback.message:
            await callback.message.answer(f"Ошибка: {e}")
        return
    await _send_png(callback, png=png, filename="hof.png", caption="<b>Зал славы</b> — топ игроков карьеры")


@history_router.callback_query(F.data == "hist:mgr")
async def cb_hist_mgr(callback: CallbackQuery) -> None:
    await callback.answer("Готовлю…")
    try:
        png = await asyncio.to_thread(render_managers_png)
    except Exception as e:
        logger.exception("mgr")
        if callback.message:
            await callback.message.answer(f"Ошибка: {e}")
        return
    await _send_png(callback, png=png, filename="managers.png", caption="<b>Roman vs Lika</b>")


@history_router.callback_query(F.data == "hist:heat")
async def cb_hist_heat(callback: CallbackQuery) -> None:
    await callback.answer("Готовлю…")
    try:
        png = await asyncio.to_thread(render_heatmap_png)
    except Exception as e:
        logger.exception("heat")
        if callback.message:
            await callback.message.answer(f"Ошибка: {e}")
        return
    await _send_png(callback, png=png, filename="heatmap.png", caption="<b>Теплокарта чемпионов</b>")


@history_router.callback_query(F.data == "hist:cover")
async def cb_hist_cover(callback: CallbackQuery) -> None:
    await callback.answer()
    if callback.message:
        await callback.message.answer(
            "Выбери сезон для обложки:",
            reply_markup=history_season_pick_kb(prefix="hist:cov:", back="hist:back"),
        )


@history_router.callback_query(F.data.startswith("hist:cov:"))
async def cb_hist_cover_season(callback: CallbackQuery) -> None:
    parts = (callback.data or "").split(":")
    if len(parts) != 3:
        await callback.answer()
        return
    try:
        sn = int(parts[2])
    except ValueError:
        await callback.answer()
        return
    await callback.answer("Готовлю обложку…")
    try:
        png = await asyncio.to_thread(render_season_cover_png, sn)
    except Exception as e:
        logger.exception("cover")
        if callback.message:
            await callback.message.answer(f"Ошибка: {e}")
        return
    await _send_png(
        callback,
        png=png,
        filename=f"cover_{sn}.png",
        caption=f"<b>Обложка · {format_season_tag(sn)}</b>",
    )


def _start_two_pick(callback: CallbackQuery, mode: str) -> None:
    _pending_two[_uid(callback)] = {"mode": mode, "a": None}


def _side_kind(league_code: str) -> str:
    return "nation" if (league_code or "").strip().lower() in ("wc", "world_cup") else "club"


@history_router.callback_query(F.data == "hist:cmp")
async def cb_hist_cmp(callback: CallbackQuery) -> None:
    _start_two_pick(callback, "cmp")
    await callback.answer()
    if callback.message:
        await callback.message.answer(
            "Сравнение: выбери <b>первую</b> сторону (клуб или сборную).\n"
            "<i>Смешивать клуб и сборную нельзя.</i>",
            reply_markup=history_league_choice_kb(
                prefix="hist:2l:", back="hist:back", kind="both"
            ),
            parse_mode="HTML",
        )


@history_router.callback_query(F.data == "hist:h2h")
async def cb_hist_h2h(callback: CallbackQuery) -> None:
    _start_two_pick(callback, "h2h")
    await callback.answer()
    if callback.message:
        await callback.message.answer(
            "Противостояние: выбери <b>первую</b> сторону (клуб или сборную).\n"
            "<i>Смешивать клуб и сборную нельзя.</i>",
            reply_markup=history_league_choice_kb(
                prefix="hist:2l:", back="hist:back", kind="both"
            ),
            parse_mode="HTML",
        )


@history_router.callback_query(F.data.startswith("hist:2l:"))
async def cb_hist_two_league(callback: CallbackQuery) -> None:
    parts = (callback.data or "").split(":")
    if len(parts) != 3:
        await callback.answer()
        return
    code = parts[2]
    st = _pending_two.get(_uid(callback))
    if not st:
        await callback.answer("Сначала выбери Сравнить или H2H", show_alert=True)
        return
    # второй выбор — только тот же тип (клуб/сборная)
    if st.get("a") is not None:
        want = st.get("kind") or _side_kind(str(st["a"][0]))
        got = _side_kind(code)
        if want != got:
            await callback.answer(
                "Нужна та же категория: клуб–клуб или сборная–сборная",
                show_alert=True,
            )
            return
    await callback.answer()
    which = "первую" if st.get("a") is None else "вторую"
    label = "сборную" if _side_kind(code) == "nation" else "клуб"
    if callback.message:
        await callback.message.answer(
            f"Выбери <b>{which}</b> {label}:",
            reply_markup=history_club_pick_kb(
                code, prefix="hist:2t:", back="hist:cmp" if st["mode"] == "cmp" else "hist:h2h"
            ),
            parse_mode="HTML",
        )


@history_router.callback_query(F.data.startswith("hist:2t:"))
async def cb_hist_two_team(callback: CallbackQuery) -> None:
    parts = (callback.data or "").split(":")
    if len(parts) != 4:
        await callback.answer()
        return
    code, idx_s = parts[2], parts[3]
    uid = _uid(callback)
    st = _pending_two.get(uid)
    if not st:
        await callback.answer("Сессия устарела — начни снова", show_alert=True)
        return
    try:
        idx = int(idx_s)
        team = _team_by_idx(code, idx)
    except Exception:
        await callback.answer("Команда не найдена", show_alert=True)
        return

    kind = _side_kind(code)
    if st.get("a") is None:
        st["a"] = (code, idx, team)
        st["kind"] = kind
        await callback.answer()
        if callback.message:
            lab = "сборная" if kind == "nation" else "клуб"
            await callback.message.answer(
                f"Первая сторона ({lab}): <b>{team}</b>\n"
                f"Теперь <b>вторая</b> — только {'сборная' if kind == 'nation' else 'клуб'}:",
                reply_markup=history_league_choice_kb(
                    prefix="hist:2l:", back="hist:back", kind=kind
                ),
                parse_mode="HTML",
            )
        return

    a = st["a"]
    if (st.get("kind") or _side_kind(str(a[0]))) != kind:
        await callback.answer(
            "Нельзя сравнивать клуб и сборную — выбери ту же категорию",
            show_alert=True,
        )
        return
    team_a = a[2]
    team_b = team
    mode = st["mode"]
    _pending_two.pop(uid, None)
    await callback.answer("Готовлю…")
    try:
        if mode == "cmp":
            png = await asyncio.to_thread(render_compare_clubs_png, team_a, team_b)
            cap = f"<b>Сравнение</b>: {team_a} vs {team_b}"
            fn = "compare.png"
        else:
            png = await asyncio.to_thread(render_h2h_png, team_a, team_b)
            cap = f"<b>H2H</b>: {team_a} — {team_b}"
            fn = "h2h.png"
    except Exception as e:
        logger.exception("two side")
        if callback.message:
            await callback.message.answer(f"Ошибка: {e}")
        return
    await _send_png(callback, png=png, filename=fn, caption=cap)


@history_router.callback_query(F.data == "hist:ws")
async def cb_hist_winner_squad_root(callback: CallbackQuery) -> None:
    await callback.answer()
    if callback.message:
        await callback.message.answer(
            "<b>Победный состав</b>\n\n"
            "Схема и вклад игроков (Г, А, Г+А) чемпионов лиги или ЛЧ по сезонам.",
            reply_markup=history_winner_squad_root_kb(),
            parse_mode="HTML",
        )


@history_router.callback_query(F.data == "hist:ws:pick")
async def cb_hist_winner_squad_pick_league(callback: CallbackQuery) -> None:
    await callback.answer()
    if callback.message:
        await callback.message.edit_reply_markup(
            reply_markup=history_league_choice_kb(
                prefix="hist:ws:l:", back="hist:ws", kind="club"
            )
        )


@history_router.callback_query(F.data == "hist:ws:cl")
async def cb_hist_winner_squad_cl_seasons(callback: CallbackQuery) -> None:
    rows = champion_seasons_cl()
    await callback.answer()
    if not callback.message:
        return
    if not rows:
        await callback.message.answer("В истории ЛЧ пока нет зафиксированных чемпионов.")
        return
    await callback.message.answer(
        "<b>ЛЧ</b> — выбери сезон:",
        reply_markup=history_winner_squad_season_kb(
            rows, prefix="hist:ws:go:cl:", back="hist:ws"
        ),
        parse_mode="HTML",
    )


@history_router.callback_query(F.data.startswith("hist:ws:l:"))
async def cb_hist_winner_squad_league_seasons(callback: CallbackQuery) -> None:
    parts = (callback.data or "").split(":")
    if len(parts) != 4:
        await callback.answer()
        return
    code = parts[3].strip()
    title = dict(LEAGUE_LABELS).get(code, code)
    rows = champion_seasons_league(code)
    await callback.answer()
    if not callback.message:
        return
    if not rows:
        await callback.message.answer(f"В {title} пока нет зафиксированных чемпионов.")
        return
    await callback.message.answer(
        f"<b>{title}</b> — выбери сезон:",
        reply_markup=history_winner_squad_season_kb(
            rows, prefix=f"hist:ws:go:l:{code}:", back="hist:ws"
        ),
        parse_mode="HTML",
    )


@history_router.callback_query(F.data.startswith("hist:ws:go:cl:"))
async def cb_hist_winner_squad_cl_go(callback: CallbackQuery) -> None:
    parts = (callback.data or "").split(":")
    if len(parts) != 5:
        await callback.answer()
        return
    try:
        sn = int(parts[4])
    except ValueError:
        await callback.answer()
        return
    by_season = dict(champion_seasons_cl())
    team = by_season.get(sn)
    if not team:
        await callback.answer("Чемпион сезона не найден", show_alert=True)
        return
    await callback.answer("Готовлю…")
    try:
        pngs = await asyncio.to_thread(
            render_champion_squad_pages, team, season_num=sn, cl=True
        )
    except Exception as e:
        logger.exception("winner_squad_cl")
        if callback.message:
            await callback.message.answer(f"Oшибка: {e}")
        return
    await _send_png(
        callback,
        png=pngs,
        filename="winner_squad_cl.png",
        caption=f"<b>Победный состав</b> · {format_season_tag(sn)} · ЛЧ · {team}",
    )


@history_router.callback_query(F.data.startswith("hist:ws:go:l:"))
async def cb_hist_winner_squad_league_go(callback: CallbackQuery) -> None:
    parts = (callback.data or "").split(":")
    # hist:ws:go:l:ger:3
    if len(parts) != 6:
        await callback.answer()
        return
    code, sn_s = parts[4], parts[5]
    try:
        sn = int(sn_s)
    except ValueError:
        await callback.answer()
        return
    title = dict(LEAGUE_LABELS).get(code, code)
    by_season = dict(champion_seasons_league(code))
    team = by_season.get(sn)
    if not team:
        await callback.answer("Чемпион сезона не найден", show_alert=True)
        return
    await callback.answer("Готовлю…")
    try:
        pngs = await asyncio.to_thread(
            render_champion_squad_pages,
            team,
            season_num=sn,
            cl=False,
            league_title=title,
        )
    except Exception as e:
        logger.exception("winner_squad_league")
        if callback.message:
            await callback.message.answer(f"Ошибка: {e}")
        return
    await _send_png(
        callback,
        png=pngs,
        filename=f"winner_squad_{code}.png",
        caption=f"<b>Победный состав</b> · {format_season_tag(sn)} · {title} · {team}",
    )


@history_router.callback_query(F.data == "hist:krypto")
async def cb_hist_kryptonite_list(callback: CallbackQuery) -> None:
    await callback.answer("Готовлю…")
    uid = _uid(callback)
    try:
        from bot.team_history import find_pvp_kryptonites

        png = await asyncio.to_thread(render_pvp_kryptonite_list_png)
        items = find_pvp_kryptonites()
    except Exception as e:
        logger.exception("kryptonite_list")
        if callback.message:
            await callback.message.answer(f"Ошибка: {e}")
        return
    _krypto_cache[uid] = items
    if callback.message:
        await _send_png(
            callback,
            png=png,
            filename="kryptonite_list.png",
            caption="<b>PVP-криптониты</b> — клубы, которые не проигрывали сопернику 3+ матчей",
        )
        if items:
            await callback.message.answer(
                _kryptonite_pick_caption(items),
                reply_markup=history_kryptonite_pick_kb(items, page=0),
            )


@history_router.callback_query(F.data == "hist:krypto:noop")
async def cb_hist_kryptonite_noop(callback: CallbackQuery) -> None:
    await callback.answer()


@history_router.callback_query(F.data.startswith("hist:krypto:p:"))
async def cb_hist_kryptonite_page(callback: CallbackQuery) -> None:
    parts = (callback.data or "").split(":")
    if len(parts) != 4:
        await callback.answer()
        return
    try:
        page = int(parts[3])
    except ValueError:
        await callback.answer()
        return
    uid = _uid(callback)
    items = _krypto_cache.get(uid) or []
    if not items:
        await callback.answer("Список устарел — открой PVP-криптониты снова", show_alert=True)
        return
    await callback.answer()
    if callback.message:
        await callback.message.edit_text(
            _kryptonite_pick_caption(items, page=page),
            reply_markup=history_kryptonite_pick_kb(items, page=page),
        )


@history_router.callback_query(F.data.startswith("hist:krypto:d:"))
async def cb_hist_kryptonite_detail(callback: CallbackQuery) -> None:
    parts = (callback.data or "").split(":")
    if len(parts) != 4:
        await callback.answer()
        return
    try:
        idx = int(parts[3])
    except ValueError:
        await callback.answer()
        return
    uid = _uid(callback)
    items = _krypto_cache.get(uid) or []
    if idx < 0 or idx >= len(items):
        await callback.answer("Список устарел — открой PVP-криптониты снова", show_alert=True)
        return
    row = items[idx]
    dom = str(row.get("dominant") or "")
    vic = str(row.get("victim") or "")
    await callback.answer("Готовлю…")
    try:
        png = await asyncio.to_thread(render_pvp_kryptonite_detail_png, dom, vic)
    except Exception as e:
        logger.exception("kryptonite_detail")
        if callback.message:
            await callback.message.answer(f"Ошибка: {e}")
        return
    await _send_png(
        callback,
        png=png,
        filename="kryptonite_detail.png",
        caption=f"<b>PVP-криптонит</b> · {dom} → {vic}",
    )
