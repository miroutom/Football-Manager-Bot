# -*- coding: utf-8 -*-
"""Трансферный дашборд: окно, квоты, НО/СО/СУ/НУ, быстрые действия."""
from __future__ import annotations

import logging
from html import escape as html_escape

from aiogram import F, Router
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.types import (
    CallbackQuery,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    Message,
)

from bot.services import LEAGUE_LABELS
from bot.states import TransferEnter
from player_stats import LEAGUE_TEAMS
from utils.transfer_advice import (
    VERDICT_NU,
    VERDICT_SU,
    TransferAdviceRow,
    collect_transfer_advice,
)
from utils.transfer_window import (
    blocks_transfers,
    is_window_open,
    quota_line,
    set_window_open,
    toggle_window,
    window_status_html,
)

logger = logging.getLogger(__name__)

_DASH_PAGE_SIZE = 12
_NATIONAL_LEAGUES = ("rpl", "eng", "esp", "ger", "ita")
_LEAGUE_TITLE = dict(LEAGUE_LABELS)


def _teams_for_league(code: str) -> list[str]:
    from utils.team_registry import teams_in_league

    reg = teams_in_league(code, active_only=True)
    if reg:
        return sorted(t.name for t in reg)
    return sorted(LEAGUE_TEAMS.get(code, []))


def _team_at(code: str, idx: int) -> str | None:
    teams = _teams_for_league(code)
    if idx < 0 or idx >= len(teams):
        return None
    return teams[idx]


def _dash_home_kb() -> InlineKeyboardMarkup:
    toggle_label = "🔴 Закрыть окно" if is_window_open() else "🟢 Открыть окно"
    rows: list[list[InlineKeyboardButton]] = [
        [InlineKeyboardButton(text=toggle_label, callback_data="xfd:toggle")],
    ]
    lg_row: list[InlineKeyboardButton] = []
    for code in _NATIONAL_LEAGUES:
        lg_row.append(
            InlineKeyboardButton(
                text=_LEAGUE_TITLE.get(code, code),
                callback_data=f"xfd:lg:{code}",
            )
        )
    rows.append(lg_row)
    rows.append(
        [
            InlineKeyboardButton(
                text="📦 Пакет (старый мастер)",
                callback_data="xfd:batch",
            ),
            InlineKeyboardButton(
                text="➡ Одиночный FSM",
                callback_data="xfer:legacy:start",
            ),
        ]
    )
    return InlineKeyboardMarkup(inline_keyboard=rows)


def _dash_league_kb(code: str, page: int = 0) -> InlineKeyboardMarkup:
    teams = _teams_for_league(code)
    ps = _DASH_PAGE_SIZE
    total_pages = max(1, (len(teams) + ps - 1) // ps)
    page = max(0, min(page, total_pages - 1))
    chunk = teams[page * ps : page * ps + ps]
    rows: list[list[InlineKeyboardButton]] = []
    for i, t in enumerate(chunk):
        ti = page * ps + i
        ql = quota_line(t)
        label = f"{t}  {ql}"
        if len(label) > 58:
            label = label[:55] + "…"
        rows.append(
            [
                InlineKeyboardButton(
                    text=label,
                    callback_data=f"xfd:tm:{code}:{ti}",
                )
            ]
        )
    nav: list[InlineKeyboardButton] = []
    if page > 0:
        nav.append(
            InlineKeyboardButton(
                text="◀", callback_data=f"xfd:lg:{code}:{page - 1}"
            )
        )
    if total_pages > 1:
        nav.append(
            InlineKeyboardButton(
                text=f"{page + 1}/{total_pages}",
                callback_data="xfd:noop",
            )
        )
    if page < total_pages - 1:
        nav.append(
            InlineKeyboardButton(
                text="▶", callback_data=f"xfd:lg:{code}:{page + 1}"
            )
        )
    if nav:
        rows.append(nav)
    rows.append(
        [InlineKeyboardButton(text="← Дашборд", callback_data="xfd:home")]
    )
    return InlineKeyboardMarkup(inline_keyboard=rows)


def _team_detail_kb(
    code: str, ti: int, *, sell_only: bool, page: int, total_pages: int
) -> InlineKeyboardMarkup:
    filt_btn = (
        "📋 Все игроки"
        if sell_only
        else "📉 Только СУ+НУ"
    )
    filt_data = (
        f"xfd:tm:{code}:{ti}:{page}:all"
        if sell_only
        else f"xfd:tm:{code}:{ti}:{page}:sell"
    )
    rows: list[list[InlineKeyboardButton]] = [
        [
            InlineKeyboardButton(text=filt_btn, callback_data=filt_data),
        ],
        [
            InlineKeyboardButton(
                text="➡ Продать (выбор)",
                callback_data=f"xfd:pick:{code}:{ti}:sell",
            ),
        ],
        [
            InlineKeyboardButton(
                text="➕ Купить из клуба",
                callback_data=f"xfd:buy:{code}:{ti}",
            ),
            InlineKeyboardButton(
                text="➕ Св. агент",
                callback_data=f"xfd:fa:{code}:{ti}",
            ),
        ],
        [
            InlineKeyboardButton(
                text="📦 Пакет в клуб",
                callback_data=f"xfd:bt:{code}:{ti}",
            ),
        ],
    ]
    nav: list[InlineKeyboardButton] = []
    if page > 0:
        nav.append(
            InlineKeyboardButton(
                text="◀", callback_data=f"xfd:tm:{code}:{ti}:{page - 1}:{'sell' if sell_only else 'all'}"
            )
        )
    if total_pages > 1:
        nav.append(
            InlineKeyboardButton(
                text=f"{page + 1}/{total_pages}",
                callback_data="xfd:noop",
            )
        )
    if page < total_pages - 1:
        nav.append(
            InlineKeyboardButton(
                text="▶",
                callback_data=f"xfd:tm:{code}:{ti}:{page + 1}:{'sell' if sell_only else 'all'}",
            )
        )
    if nav:
        rows.append(nav)
    rows.append(
        [
            InlineKeyboardButton(
                text=f"← {_LEAGUE_TITLE.get(code, code)}",
                callback_data=f"xfd:lg:{code}",
            )
        ]
    )
    return InlineKeyboardMarkup(inline_keyboard=rows)


def _sell_pick_kb(
    code: str,
    ti: int,
    advice_rows: list[TransferAdviceRow],
    page: int,
) -> InlineKeyboardMarkup:
    ps = _DASH_PAGE_SIZE
    sell_rows = [r for r in advice_rows if r.verdict in (VERDICT_SU, VERDICT_NU)]
    total_pages = max(1, (len(sell_rows) + ps - 1) // ps)
    page = max(0, min(page, total_pages - 1))
    chunk = sell_rows[page * ps : page * ps + ps]
    rows: list[list[InlineKeyboardButton]] = []
    for i, r in enumerate(chunk):
        pi = page * ps + i
        label = r.line_text()
        if len(label) > 60:
            label = label[:57] + "…"
        rows.append(
            [
                InlineKeyboardButton(
                    text=label,
                    callback_data=f"xfd:sl:{code}:{ti}:{pi}",
                )
            ]
        )
    nav: list[InlineKeyboardButton] = []
    if page > 0:
        nav.append(
            InlineKeyboardButton(
                text="◀", callback_data=f"xfd:pick:{code}:{ti}:sell:{page - 1}"
            )
        )
    if page < total_pages - 1:
        nav.append(
            InlineKeyboardButton(
                text="▶", callback_data=f"xfd:pick:{code}:{ti}:sell:{page + 1}"
            )
        )
    if nav:
        rows.append(nav)
    rows.append(
        [
            InlineKeyboardButton(
                text="← Клуб",
                callback_data=f"xfd:tm:{code}:{ti}",
            )
        ]
    )
    return InlineKeyboardMarkup(inline_keyboard=rows)


async def send_dashboard_home(message: Message) -> None:
    if not _PATH_exists_open_default():
        set_window_open()
    text = (
        "🔄 <b>Трансферы</b>\n\n"
        f"{window_status_html()}\n\n"
        "Выбери лигу — увидишь квоты <code>in/out</code> и рекомендации "
        "<b>НО СО СУ НУ</b> по каждому клубу.\n\n"
        "<i>НО СО СУ НУ · Т− П↓ З+ С×</i>"
    )
    await message.answer(text, parse_mode="HTML", reply_markup=_dash_home_kb())


def _PATH_exists_open_default() -> bool:
    from pathlib import Path

    return Path(__file__).resolve().parent.parent.joinpath(
        "data", "transfer_window.json"
    ).is_file()


_ADVICE_LEGEND_HTML = (
    "<i>НО надо остаться · СО стоит остаться · СУ стоит уходить · НУ надо уходить\n"
    "Т− трофеи · П↓ продуктивность · З+ избыток · С× не в схему</i>\n"
)


def _format_team_detail(
    team: str,
    rows: list[TransferAdviceRow],
    *,
    sell_only: bool,
    page: int,
) -> tuple[str, int]:
    q = quota_line(team)
    body_rows = rows
    if sell_only:
        body_rows = [r for r in rows if r.verdict in (VERDICT_SU, VERDICT_NU)]
    ps = _DASH_PAGE_SIZE
    total_pages = max(1, (len(body_rows) + ps - 1) // ps)
    page = max(0, min(page, total_pages - 1))
    chunk = body_rows[page * ps : page * ps + ps]

    counts = {v: sum(1 for r in rows if r.verdict == v) for v in ("НО", "СО", "СУ", "НУ")}
    header = (
        f"<b>{html_escape(team)}</b>  ·  <code>{html_escape(q)}</code>\n"
        f"{_ADVICE_LEGEND_HTML}"
        f"НО {counts['НО']} · СО {counts['СО']} · СУ {counts['СУ']} · НУ {counts['НУ']}\n"
    )
    if sell_only:
        header += "<i>Фильтр: только СУ и НУ</i>\n"
    if not chunk:
        header += "\nНет игроков в этом фильтре."
        return header, total_pages

    lines = [html_escape(r.line_text()) for r in chunk]
    if len(body_rows) > ps:
        lines.append(
            f"<i>стр. {page + 1}/{total_pages}</i>"
        )
    return header + "\n".join(lines), total_pages


def register_transfer_dashboard(router: Router) -> None:
    """Подключить обработчики дашборда к ``transfer_router``."""

    @router.callback_query(F.data == "xfd:noop")
    async def cb_dash_noop(callback: CallbackQuery) -> None:
        await callback.answer()

    @router.callback_query(F.data == "xfd:home")
    @router.callback_query(F.data == "xfer:start")
    async def cb_dash_home(callback: CallbackQuery, state: FSMContext) -> None:
        await state.clear()
        await callback.answer()
        if callback.message:
            await send_dashboard_home(callback.message)

    @router.callback_query(F.data == "xfd:toggle")
    async def cb_dash_toggle(callback: CallbackQuery) -> None:
        now_open = toggle_window()
        await callback.answer("Окно открыто" if now_open else "Окно закрыто")
        if callback.message:
            await send_dashboard_home(callback.message)

    @router.callback_query(F.data == "xfd:batch")
    async def cb_dash_batch(callback: CallbackQuery, state: FSMContext) -> None:
        from bot.transfer_handlers import _legacy_entry_keyboard

        await state.clear()
        await state.set_state(TransferEnter.batch_to_count)
        await callback.answer()
        if callback.message:
            await callback.message.answer(
                "📦 <b>Пакет трансферов</b> (классический мастер)\n\n"
                "Строка: <code>Клуб 3</code> — куда и сколько (1–5).\n/cancel — отмена.",
                parse_mode="HTML",
                reply_markup=_legacy_entry_keyboard(),
            )

    @router.callback_query(F.data.regexp(r"^xfd:lg:([a-z]+)(?::(\d+))?$"))
    async def cb_dash_league(callback: CallbackQuery) -> None:
        import re

        m = re.match(r"^xfd:lg:([a-z]+)(?::(\d+))?$", callback.data or "")
        if not m:
            await callback.answer()
            return
        code, page_s = m.group(1), m.group(2)
        page = int(page_s) if page_s else 0
        teams = _teams_for_league(code)
        if not teams:
            await callback.answer("Лига не найдена", show_alert=True)
            return
        title = _LEAGUE_TITLE.get(code, code)
        await callback.answer()
        if callback.message:
            await callback.message.edit_text(
                f"<b>{html_escape(title)}</b> — выбери клуб\n"
                f"<code>in X/5  out Y/5</code> за текущее окно",
                parse_mode="HTML",
                reply_markup=_dash_league_kb(code, page),
            )

    @router.callback_query(
        F.data.regexp(r"^xfd:tm:([a-z]+):(\d+)(?::(\d+))?(?::(sell|all))?$")
    )
    async def cb_dash_team(callback: CallbackQuery) -> None:
        import re

        m = re.match(
            r"^xfd:tm:([a-z]+):(\d+)(?::(\d+))?(?::(sell|all))?$",
            callback.data or "",
        )
        if not m:
            await callback.answer()
            return
        code = m.group(1)
        ti = int(m.group(2))
        page = int(m.group(3)) if m.group(3) else 0
        sell_only = m.group(4) == "sell"
        team = _team_at(code, ti)
        if not team:
            await callback.answer("Клуб не найден", show_alert=True)
            return
        canon, rows, err = collect_transfer_advice(team)
        if err:
            await callback.answer(err, show_alert=True)
            return
        text, total_pages = _format_team_detail(
            canon, rows, sell_only=sell_only, page=page
        )
        await callback.answer()
        if callback.message:
            try:
                await callback.message.edit_text(
                    text,
                    parse_mode="HTML",
                    reply_markup=_team_detail_kb(
                        code, ti, sell_only=sell_only, page=page, total_pages=total_pages
                    ),
                )
            except Exception:
                await callback.message.answer(
                    text,
                    parse_mode="HTML",
                    reply_markup=_team_detail_kb(
                        code, ti, sell_only=sell_only, page=page, total_pages=total_pages
                    ),
                )

    @router.callback_query(F.data.regexp(r"^xfd:pick:([a-z]+):(\d+):sell(?::(\d+))?$"))
    async def cb_dash_pick_sell(callback: CallbackQuery, state: FSMContext) -> None:
        import re

        m = re.match(r"^xfd:pick:([a-z]+):(\d+):sell(?::(\d+))?$", callback.data or "")
        if not m:
            await callback.answer()
            return
        code, ti_s, page_s = m.group(1), m.group(2), m.group(3)
        ti = int(ti_s)
        page = int(page_s) if page_s else 0
        team = _team_at(code, ti)
        if not team:
            await callback.answer("Клуб не найден", show_alert=True)
            return
        _, rows, err = collect_transfer_advice(team)
        if err:
            await callback.answer(err, show_alert=True)
            return
        sell_rows = [r for r in rows if r.verdict in (VERDICT_SU, VERDICT_NU)]
        if not sell_rows:
            await callback.answer("Нет СУ/НУ в составе", show_alert=True)
            return
        await callback.answer()
        if callback.message:
            await callback.message.edit_text(
                f"<b>{html_escape(team)}</b> — кого продать?\n"
                f"СУ+НУ: <b>{len(sell_rows)}</b>",
                parse_mode="HTML",
                reply_markup=_sell_pick_kb(code, ti, rows, page),
            )

    @router.callback_query(F.data.regexp(r"^xfd:sl:([a-z]+):(\d+):(\d+)$"))
    async def cb_dash_sell_player(callback: CallbackQuery, state: FSMContext) -> None:
        import re

        if blocks_transfers():
            await callback.answer("Трансферное окно закрыто", show_alert=True)
            return
        m = re.match(r"^xfd:sl:([a-z]+):(\d+):(\d+)$", callback.data or "")
        if not m:
            await callback.answer()
            return
        code, ti_s, pi_s = m.group(1), m.group(2), m.group(3)
        ti, pi = int(ti_s), int(pi_s)
        team = _team_at(code, ti)
        if not team:
            await callback.answer("Клуб не найден", show_alert=True)
            return
        canon, rows, err = collect_transfer_advice(team)
        if err:
            await callback.answer(err, show_alert=True)
            return
        sell_rows = [r for r in rows if r.verdict in (VERDICT_SU, VERDICT_NU)]
        if pi < 0 or pi >= len(sell_rows):
            await callback.answer("Игрок не найден", show_alert=True)
            return
        row = sell_rows[pi]
        await state.update_data(
            tr_kind="club",
            tr_from=canon,
            tr_player=row.name,
            tr_pos=row.position,
            tr_to="",
            tr_meta_patch={},
            tr_dash_lg=code,
            tr_dash_ti=ti,
            tr_roster_ui=False,
        )
        await state.set_state(TransferEnter.to_team)
        await callback.answer()
        if callback.message:
            await callback.message.answer(
                f"Продажа: <b>{html_escape(row.name)}</b> ({row.position}) "
                f"из <b>{html_escape(canon)}</b>\n"
                f"{html_escape(row.label_short())}\n\n"
                "Введи клуб <b>куда</b> уходит игрок.\n/cancel — отмена.",
                parse_mode="HTML",
            )

    @router.callback_query(F.data.regexp(r"^xfd:buy:([a-z]+):(\d+)$"))
    async def cb_dash_buy(callback: CallbackQuery, state: FSMContext) -> None:
        import re

        if blocks_transfers():
            await callback.answer("Трансферное окно закрыто", show_alert=True)
            return
        m = re.match(r"^xfd:buy:([a-z]+):(\d+)$", callback.data or "")
        if not m:
            await callback.answer()
            return
        code, ti = m.group(1), int(m.group(2))
        team = _team_at(code, ti)
        if not team:
            await callback.answer("Клуб не найден", show_alert=True)
            return
        from utils.transfer_input import resolve_team_name
        from utils.utils import session_league

        resolved = resolve_team_name(team, session_league) or team
        await state.update_data(
            tr_to=resolved,
            tr_dash_lg=code,
            tr_dash_ti=ti,
            tr_meta_patch={},
        )
        await state.set_state(TransferEnter.from_club)
        await callback.answer()
        if callback.message:
            await callback.message.answer(
                f"Покупка в <b>{html_escape(resolved)}</b>\n"
                f"Квота: <code>{html_escape(quota_line(resolved))}</code>\n\n"
                "Введи клуб <b>откуда</b> забираем игрока.\n/cancel — отмена.",
                parse_mode="HTML",
            )

    @router.callback_query(F.data.regexp(r"^xfd:fa:([a-z]+):(\d+)$"))
    async def cb_dash_fa(callback: CallbackQuery, state: FSMContext) -> None:
        import re

        if blocks_transfers():
            await callback.answer("Трансферное окно закрыто", show_alert=True)
            return
        m = re.match(r"^xfd:fa:([a-z]+):(\d+)$", callback.data or "")
        if not m:
            await callback.answer()
            return
        code, ti = m.group(1), int(m.group(2))
        team = _team_at(code, ti)
        if not team:
            await callback.answer("Клуб не найден", show_alert=True)
            return
        from utils.transfer_input import resolve_team_name
        from utils.utils import session_league

        resolved = resolve_team_name(team, session_league) or team
        await state.update_data(
            tr_kind="fa",
            tr_to=resolved,
            tr_dash_lg=code,
            tr_dash_ti=ti,
        )
        await callback.answer()
        if callback.message:
            from bot.transfer_handlers import _begin_new_player_signing

            await _begin_new_player_signing(
                callback.message,
                state,
                f"Св. агент → <b>{html_escape(resolved)}</b>\n"
                f"Квота: <code>{html_escape(quota_line(resolved))}</code>\n\n"
                "Шаг 1/5 — <b>имя</b>.\n/cancel — отмена.",
            )

    @router.callback_query(F.data.regexp(r"^xfd:bt:([a-z]+):(\d+)$"))
    async def cb_dash_batch_team(callback: CallbackQuery, state: FSMContext) -> None:
        import re

        if blocks_transfers():
            await callback.answer("Трансферное окно закрыто", show_alert=True)
            return
        m = re.match(r"^xfd:bt:([a-z]+):(\d+)$", callback.data or "")
        if not m:
            await callback.answer()
            return
        code, ti = m.group(1), int(m.group(2))
        team = _team_at(code, ti)
        if not team:
            await callback.answer("Клуб не найден", show_alert=True)
            return
        from bot.transfer_handlers import begin_batch_for_team

        await callback.answer()
        if callback.message:
            await begin_batch_for_team(
                callback.message, state, team, dash_lg=code, dash_ti=ti
            )

    @router.message(Command("transfer"))
    async def cmd_transfer_dashboard(message: Message, state: FSMContext) -> None:
        await state.clear()
        await send_dashboard_home(message)
