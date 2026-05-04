"""Меню «Ввод оценки»: все оценки по клубу и пошаговый ввод за матч."""
from __future__ import annotations

import asyncio
import logging
import re
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
from aiogram.enums import ParseMode

from bot.services import LEAGUE_LABELS, split_text_chunks, teams_ordered_for_goalscorers
from bot.states import MatchPerfRatingEnter
from match_results import list_journal_records_for_ratings

logger = logging.getLogger(__name__)

match_rating_router = Router()

_TEXT_NOT_CMD = F.text & ~F.text.startswith("/")

_MATCH_PAGE = 6

_RE_ALL_TM = re.compile(r"^mrate:alltm:([a-z0-9_]+):(\d+)$")


def _league_title(code: str) -> str:
    return dict(LEAGUE_LABELS).get(code, code)


def _club_btn_label(text: str, max_chars: int = 36) -> str:
    text = (text or "").strip()
    if len(text) <= max_chars:
        return text
    return text[: max_chars - 1] + "…"


def _root_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="Все оценки",
                    callback_data="mrate:root:all",
                ),
                InlineKeyboardButton(
                    text="Оценки за матч",
                    callback_data="mrate:root:match",
                ),
            ],
        ]
    )


def _league_kb() -> InlineKeyboardMarkup:
    row: list[InlineKeyboardButton] = []
    rows: list[list[InlineKeyboardButton]] = []
    for code, label in LEAGUE_LABELS:
        row.append(
            InlineKeyboardButton(
                text=label,
                callback_data=f"mrate:alllg:{code}",
            )
        )
        if len(row) == 3:
            rows.append(row)
            row = []
    if row:
        rows.append(row)
    return InlineKeyboardMarkup(inline_keyboard=rows)


def _teams_kb(league_code: str) -> InlineKeyboardMarkup:
    teams = teams_ordered_for_goalscorers(league_code)
    rows: list[list[InlineKeyboardButton]] = []
    row: list[InlineKeyboardButton] = []
    for idx, team in enumerate(teams):
        row.append(
            InlineKeyboardButton(
                text=_club_btn_label(team),
                callback_data=f"mrate:alltm:{league_code}:{idx}",
            )
        )
        if len(row) == 2:
            rows.append(row)
            row = []
    if row:
        rows.append(row)
    return InlineKeyboardMarkup(inline_keyboard=rows)


def _short_rec_label(rec: dict, idx: int) -> str:
    h = (rec.get("home") or "?")[:14]
    a = (rec.get("away") or "?")[:14]
    hs, aws = rec.get("home_score"), rec.get("away_score")
    sc = ""
    if hs is not None and aws is not None:
        sc = f" {hs}:{aws}"
    return f"{idx + 1}. {h}—{a}{sc}"[:58]


def _match_list_kb(page: int) -> InlineKeyboardMarkup:
    recs = list_journal_records_for_ratings()
    n = len(recs)
    if n == 0:
        return InlineKeyboardMarkup(
            inline_keyboard=[
                [
                    InlineKeyboardButton(
                        text="« Назад",
                        callback_data="mrate:backroot",
                    ),
                ],
            ]
        )
    total_pages = max(1, (n + _MATCH_PAGE - 1) // _MATCH_PAGE)
    page = max(0, min(page, total_pages - 1))
    start = page * _MATCH_PAGE
    chunk = recs[start : start + _MATCH_PAGE]

    rows: list[list[InlineKeyboardButton]] = []
    for i, rec in enumerate(chunk):
        gidx = start + i
        rows.append(
            [
                InlineKeyboardButton(
                    text=_short_rec_label(rec, gidx),
                    callback_data=f"mrate:ms:{gidx}",
                ),
            ]
        )

    nav: list[InlineKeyboardButton] = []
    if page > 0:
        nav.append(
            InlineKeyboardButton(text=f"« {page}", callback_data=f"mrate:mlp:{page - 1}")
        )
    if page < total_pages - 1:
        nav.append(
            InlineKeyboardButton(
                text=f"{page + 2} »", callback_data=f"mrate:mlp:{page + 1}"
            )
        )
    if nav:
        rows.append(nav)

    rows.append(
        [
            InlineKeyboardButton(text="« В режимы", callback_data="mrate:backroot"),
        ]
    )
    return InlineKeyboardMarkup(inline_keyboard=rows)


def _match_side_kb(home_team: str, away_team: str) -> InlineKeyboardMarkup:
    """Подписи кнопок — названия клубов (до ~28 симв., лимит Telegram 64)."""
    hb = _club_btn_label(home_team or "Хозяева", max_chars=28)
    ab = _club_btn_label(away_team or "Гости", max_chars=28)
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(text=hb, callback_data="mrate:side:home"),
                InlineKeyboardButton(text=ab, callback_data="mrate:side:away"),
            ],
            [
                InlineKeyboardButton(text="✓ Готово", callback_data="mrate:mdone"),
            ],
            [
                InlineKeyboardButton(text="« К списку матчей", callback_data="mrate:backml"),
            ],
        ]
    )


def _tournament_from_record(rec: dict) -> str:
    return "cl" if (rec.get("league") or "") == "cl" else "league"


@match_rating_router.callback_query(F.data == "menu:match_rating")
async def cb_menu_match_rating(callback: CallbackQuery, state: FSMContext) -> None:
    await callback.answer()
    if callback.message is None:
        return
    await state.clear()
    from utils.match_ratings import CODE_LEGEND

    await callback.message.answer(
        "📝 <b>Ввод оценки</b>\n\n"
        "«Все оценки» — история по клубу в выбранной лиге (ЛЧ — отдельная кнопка лига).\n"
        "«Оценки за матч» — журнал только матчей «игра» (записи с "
        "<code>entry_type: simulation</code> не показываются).\n\n"
        f"<i>{html_escape(CODE_LEGEND)}</i>",
        parse_mode=ParseMode.HTML,
        reply_markup=_root_kb(),
    )


@match_rating_router.callback_query(F.data == "mrate:backroot")
async def cb_mrate_back_root(callback: CallbackQuery, state: FSMContext) -> None:
    await callback.answer()
    await state.clear()
    if callback.message:
        await callback.message.answer(
            "📝 <b>Ввод оценки</b>",
            parse_mode=ParseMode.HTML,
            reply_markup=_root_kb(),
        )


@match_rating_router.callback_query(F.data == "mrate:root:all")
async def cb_mrate_root_all(callback: CallbackQuery, state: FSMContext) -> None:
    await callback.answer()
    await state.clear()
    if callback.message:
        await callback.message.answer(
            "Выбери лигу:",
            reply_markup=_league_kb(),
        )


@match_rating_router.callback_query(F.data.startswith("mrate:alllg:"))
async def cb_mrate_all_league(callback: CallbackQuery, state: FSMContext) -> None:
    parts = (callback.data or "").split(":", 2)
    if len(parts) < 3:
        await callback.answer()
        return
    code = parts[2]
    await callback.answer()
    if callback.message is None:
        return
    try:
        kb = _teams_kb(code)
    except Exception as e:
        logger.exception("mrate teams kb")
        await callback.message.answer(f"Ошибка: {e}")
        return
    await callback.message.answer(
        f"{_league_title(code)} — выберите клуб:",
        reply_markup=kb,
    )


@match_rating_router.callback_query(F.data.startswith("mrate:alltm:"))
async def cb_mrate_all_team(callback: CallbackQuery, state: FSMContext) -> None:
    m = _RE_ALL_TM.match(callback.data or "")
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
    if callback.message is None:
        return
    try:
        teams = teams_ordered_for_goalscorers(code)
        team = teams[idx]
    except (IndexError, Exception) as e:
        await callback.message.answer(f"Ошибка клуба: {e}")
        return

    from utils.match_ratings import CODE_LEGEND, format_team_ratings_history

    body = await asyncio.to_thread(format_team_ratings_history, code, team)
    chunks = split_text_chunks(body, 3500)
    header = (
        f"📋 <b>Все оценки</b> · {_league_title(code)} · <b>{html_escape(team)}</b>\n\n"
        f"<i>{html_escape(CODE_LEGEND)}</i>\n\n"
    )
    for i, chunk in enumerate(chunks):
        pre = f"<pre>{html_escape(chunk)}</pre>"
        if i == 0:
            text = header + pre
        else:
            text = f"<i>…продолжение {i + 1}/{len(chunks)}</i>\n" + pre
        await callback.message.answer(text, parse_mode=ParseMode.HTML)


@match_rating_router.callback_query(F.data == "mrate:root:match")
async def cb_mrate_root_match(callback: CallbackQuery, state: FSMContext) -> None:
    await callback.answer()
    await state.set_state(MatchPerfRatingEnter.session)
    if callback.message:
        n = len(list_journal_records_for_ratings())
        if n == 0:
            await callback.message.answer(
                "В журнале нет подходящих матчей (все с "
                "<code>entry_type: simulation</code> или журнал пуст).",
                parse_mode=ParseMode.HTML,
                reply_markup=_root_kb(),
            )
            await state.clear()
            return
        await callback.message.answer(
            "Матчи журнала (только «игра», без симуляций). Выбери матч:",
            reply_markup=_match_list_kb(0),
        )


@match_rating_router.callback_query(F.data.startswith("mrate:mlp:"))
async def cb_mrate_match_page(callback: CallbackQuery, state: FSMContext) -> None:
    parts = (callback.data or "").split(":")
    try:
        page = int(parts[2])
    except (IndexError, ValueError):
        await callback.answer()
        return
    await callback.answer()
    if callback.message:
        await callback.message.answer(
            "Страница матчей:",
            reply_markup=_match_list_kb(page),
        )


@match_rating_router.callback_query(F.data.startswith("mrate:ms:"))
async def cb_mrate_match_select(callback: CallbackQuery, state: FSMContext) -> None:
    parts = (callback.data or "").split(":")
    try:
        gidx = int(parts[2])
    except (IndexError, ValueError):
        await callback.answer()
        return
    recs = list_journal_records_for_ratings()
    if gidx < 0 or gidx >= len(recs):
        await callback.answer("Нет такого матча.", show_alert=True)
        return
    rec = recs[gidx]
    from utils.match_ratings import rating_match_key

    mk = rating_match_key(rec)
    await callback.answer()
    await state.set_state(MatchPerfRatingEnter.session)
    h, a = rec.get("home"), rec.get("away")
    hs, aws = rec.get("home_score"), rec.get("away_score")
    sc = ""
    if hs is not None and aws is not None:
        sc = f"{hs}:{aws}"
    lg = _league_title((rec.get("league") or "")[:8])
    await state.update_data(
        mrate_mk=mk,
        mrate_rec_idx=gidx,
        mrate_home_name=str(h or ""),
        mrate_away_name=str(a or ""),
    )
    if callback.message:
        await callback.message.answer(
            f"Матч: <b>{html_escape(str(h))}</b> — <b>{html_escape(str(a))}</b>"
            f"{f' ({html_escape(sc)})' if sc else ''} · {html_escape(lg)}\n\n"
            "Выбери клуб кнопкой ниже — пришлю состав для копирования (reserve / bench / start). "
            "Верни тот же список, добавив в начале строки один смайлик "
            "(см. легенду в начале режима). Отправь <b>весь</b> блок целиком.\n"
            "Можно заполнить только одну сторону; затем «Готово».",
            parse_mode=ParseMode.HTML,
            reply_markup=_match_side_kb(str(h or ""), str(a or "")),
        )


@match_rating_router.callback_query(
    StateFilter(MatchPerfRatingEnter.session, MatchPerfRatingEnter.wait_paste),
    F.data.startswith("mrate:side:"),
)
async def cb_mrate_side(callback: CallbackQuery, state: FSMContext) -> None:
    side = (callback.data or "").split(":")[2]
    if side not in ("home", "away"):
        await callback.answer()
        return
    data = await state.get_data()
    mk = data.get("mrate_mk")
    if not mk:
        await callback.answer("Сессия устарела.", show_alert=True)
        return
    from utils.match_ratings import (
        CODE_LEGEND,
        find_journal_record_by_rating_key,
        build_roster_template,
    )

    rec = find_journal_record_by_rating_key(mk)
    if not rec:
        await callback.answer("Матч не найден в журнале.", show_alert=True)
        return
    team_journal = (rec.get("home") if side == "home" else rec.get("away")) or ""
    tour = _tournament_from_record(rec)
    try:
        tpl, key_map, canon_team = await asyncio.to_thread(
            build_roster_template,
            team_journal,
            tour,
            roster_from="league",
        )
    except Exception:
        logger.exception(
            "build_roster_template failed for %s (%s)", team_journal, tour
        )
        await callback.answer(
            "Не удалось собрать состав из БД. Проверь название клуба.",
            show_alert=True,
        )
        return

    await state.update_data(
        mrate_side=side,
        mrate_team=canon_team,
        mrate_team_journal=team_journal,
        mrate_tournament=tour,
        mrate_roster_from="league",
        mrate_key_map={k: [v[0], v[1], v[2]] for k, v in key_map.items()},
    )
    await state.set_state(MatchPerfRatingEnter.wait_paste)
    await callback.answer()

    legend = html_escape(CODE_LEGEND)
    tail = (
        f"\n\nСтрока ответа: имя и позиция, как в шаблоне, затем смайлик через пробел "
        f"(или смайлик в начале строки). Рейтинг из БД в текст вводить не нужно. "
        f"Текущие оценки можно перезаписать. Уже учтённые матчи в БД синхронизируются "
        f"по строкам со смайликом.\n{legend}"
    )
    empty_hint = ""
    if not key_map:
        empty_hint = (
            "\n\n<i>В нац. БД нет игроков этого клуба — проверь состав "
            "(шаблон берётся из league DB, как полная заявка).</i>"
        )

    if not callback.message:
        return

    # Запас под HTML-обёртку и подпись (лимит Telegram ~4096)
    chunks = split_text_chunks(tpl, 2800) if tpl else [""]
    for i, chunk in enumerate(chunks):
        pre = f"<pre>{html_escape(chunk)}</pre>" if chunk.strip() else "<i>(пусто)</i>"
        if i == 0:
            disp = team_journal
            if (canon_team or "").strip().casefold() != (
                team_journal or ""
            ).strip().casefold():
                disp = f"{team_journal} → {canon_team}"
            text = (
                f"<b>{html_escape(disp)}</b> — шаблон состава "
                f"(секции как в <b>полной заявке</b> в нац. БД; матчи ЛЧ тоже):\n\n"
                f"{pre}{tail}{empty_hint}"
            )
        else:
            text = f"<i>…продолжение {i + 1}/{len(chunks)}</i>\n{pre}"
        await callback.message.answer(text, parse_mode=ParseMode.HTML)


@match_rating_router.message(MatchPerfRatingEnter.wait_paste, _TEXT_NOT_CMD)
async def on_mrate_paste(message: Message, state: FSMContext) -> None:
    from utils.match_ratings import (
        format_rated_roster,
        parse_user_rated_lines,
        get_side_ratings,
        set_side_ratings,
        sync_match_appearances_for_side,
    )

    data = await state.get_data()
    mk = data.get("mrate_mk")
    side = data.get("mrate_side")
    team = data.get("mrate_team")
    tour = data.get("mrate_tournament") or "league"
    roster_from = data.get("mrate_roster_from")
    raw_km = data.get("mrate_key_map") or {}
    key_map: dict[str, tuple[str, str, int]] = {
        k: (v[0], v[1], v[2]) for k, v in raw_km.items()
    }
    if not mk or not side or not team or not key_map:
        await state.clear()
        await message.answer("Сессия устарела. Начни с меню.")
        return

    ratings_new, warnings = parse_user_rated_lines(message.text or "", key_map)

    def _merge_and_sync() -> tuple[list[str], dict[str, str]]:
        old_from_file = get_side_ratings(mk, side)
        old_eff = {pk: old_from_file.get(pk, "") for pk in key_map}
        logs_l = sync_match_appearances_for_side(
            team, tour, key_map, old_eff, ratings_new
        )
        final_ratings = dict(ratings_new)
        for k, v in old_from_file.items():
            if k not in key_map:
                final_ratings[k] = v
        set_side_ratings(mk, side, final_ratings)
        return logs_l, final_ratings

    logs, _final = await asyncio.to_thread(_merge_and_sync)

    reply_body = await asyncio.to_thread(
        format_rated_roster,
        team,
        ratings_new,
        tour,
        roster_from=roster_from if roster_from else None,
    )
    warn_txt = ""
    if warnings:
        warn_txt = "\n\n⚠ " + "\n".join(warnings[:12])
        if len(warnings) > 12:
            warn_txt += f"\n…ещё {len(warnings) - 12}"

    log_txt = ""
    if logs:
        log_txt = "\n\n" + "\n".join(logs[:20])

    await message.answer(
        f"<pre>{html_escape(reply_body)}</pre>{warn_txt}{log_txt}",
        parse_mode=ParseMode.HTML,
    )
    await state.set_state(MatchPerfRatingEnter.session)
    hn = data.get("mrate_home_name") or ""
    an = data.get("mrate_away_name") or ""
    await message.answer(
        "Сторона сохранена. Другая сторона или «Готово».",
        reply_markup=_match_side_kb(str(hn), str(an)),
    )


@match_rating_router.callback_query(F.data == "mrate:mdone")
async def cb_mrate_match_done(callback: CallbackQuery, state: FSMContext) -> None:
    await callback.answer()
    await state.clear()
    if callback.message:
        await callback.message.answer("Готово. Оценки в match_performance_ratings.json")


@match_rating_router.callback_query(F.data == "mrate:backml")
async def cb_mrate_back_match_list(callback: CallbackQuery, state: FSMContext) -> None:
    await callback.answer()
    await state.set_state(MatchPerfRatingEnter.session)
    if callback.message:
        await callback.message.answer(
            "Матчи журнала:",
            reply_markup=_match_list_kb(0),
        )


@match_rating_router.message(MatchPerfRatingEnter.session, _TEXT_NOT_CMD)
async def on_mrate_session_stray(message: Message) -> None:
    await message.answer(
        "Выбери матч или сторону кнопками ниже или открой меню «Ввод оценки» заново."
    )
