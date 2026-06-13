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
    VERDICT_NO,
    VERDICT_NU,
    VERDICT_SO,
    VERDICT_SU,
    TransferAdviceRow,
    collect_transfer_advice,
    flat_advice_rows,
    format_player_advice_card_html,
    format_team_advice_html,
    paginate_advice_view,
)
from utils.player_names import player_surname
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
_DASH_ADVICE_PAGE_SIZE = 10
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


def _sell_pick_kb(
    code: str,
    ti: int,
    advice_rows: list[TransferAdviceRow],
    page: int,
) -> InlineKeyboardMarkup:
    ps = _DASH_PAGE_SIZE
    sell_rows = flat_advice_rows(advice_rows, "sell")
    total_pages = max(1, (len(sell_rows) + ps - 1) // ps)
    page = max(0, min(page, total_pages - 1))
    chunk = sell_rows[page * ps : page * ps + ps]
    rows: list[list[InlineKeyboardButton]] = []
    for i, r in enumerate(chunk):
        pi = page * ps + i
        label = f"{r.verdict} {r.compact_line()}"
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
        f"{_ADVICE_LEGEND_HTML}"
    )
    await message.answer(text, parse_mode="HTML", reply_markup=_dash_home_kb())


def _PATH_exists_open_default() -> bool:
    from pathlib import Path

    return Path(__file__).resolve().parent.parent.joinpath(
        "data", "transfer_window.json"
    ).is_file()


_ADVICE_LEGEND_HTML = (
    "<i>П+ перерос · П− не дорос · Т− трофеи · Т× тащит без титулов · "
    "Н новичок · ≈ уровень</i>\n"
)

# view в callback: summary | nu | su | so | no | sell | all
_VIEW_TO_VERDICT = {
    "nu": VERDICT_NU,
    "su": VERDICT_SU,
    "so": VERDICT_SO,
    "no": VERDICT_NO,
}


def _parse_team_view(raw: str | None) -> str:
    v = (raw or "summary").strip().lower()
    if v in ("summary", "nu", "su", "so", "no", "sell", "all"):
        return v
    if v == "sell":
        return "sell"
    return "summary"


def _team_detail_kb(
    code: str,
    ti: int,
    *,
    view: str,
    page: int,
    total_pages: int,
    counts: dict[str, int],
    advice_rows: list[TransferAdviceRow] | None = None,
) -> InlineKeyboardMarkup:
    def _cnt(key: str) -> str:
        verdict = _VIEW_TO_VERDICT.get(key)
        n = counts.get(verdict, 0) if verdict else 0
        if key == "sell":
            n = counts.get(VERDICT_SU, 0) + counts.get(VERDICT_NU, 0)
        return str(n)

    def _vbtn(label: str, vkey: str) -> InlineKeyboardButton:
        mark = "• " if view == vkey else ""
        return InlineKeyboardButton(
            text=f"{mark}{label} {_cnt(vkey)}",
            callback_data=f"xfd:tm:{code}:{ti}:0:{vkey}",
        )

    kb_rows: list[list[InlineKeyboardButton]] = [
        [_vbtn("НУ", "nu"), _vbtn("СУ", "su")],
        [_vbtn("СО", "so"), _vbtn("НО", "no")],
        [
            InlineKeyboardButton(
                text=("• Сводка" if view == "summary" else "Сводка"),
                callback_data=f"xfd:tm:{code}:{ti}:0:summary",
            ),
            InlineKeyboardButton(
                text=("• Все" if view == "all" else "Все"),
                callback_data=f"xfd:tm:{code}:{ti}:0:all",
            ),
        ],
        [
            InlineKeyboardButton(
                text=("• СУ+НУ" if view == "sell" else "СУ+НУ"),
                callback_data=f"xfd:tm:{code}:{ti}:0:sell",
            ),
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
    if view != "summary" and advice_rows:
        chunk, _, _ = paginate_advice_view(
            advice_rows, view, page, _DASH_ADVICE_PAGE_SIZE
        )
        for i, r in enumerate(chunk):
            global_idx = page * _DASH_ADVICE_PAGE_SIZE + i
            sur = (player_surname(r.name) or r.name).strip()
            if len(sur) > 14:
                sur = sur[:12] + "…"
            label = f"{r.verdict} {sur} {r.overall}"
            if len(label) > 42:
                label = label[:39] + "…"
            kb_rows.append(
                [
                    InlineKeyboardButton(
                        text=label,
                        callback_data=f"xfd:pl:{code}:{ti}:{view}:{page}:{global_idx}",
                    )
                ]
            )
    if view != "summary" and total_pages > 1:
        nav: list[InlineKeyboardButton] = []
        if page > 0:
            nav.append(
                InlineKeyboardButton(
                    text="◀",
                    callback_data=f"xfd:tm:{code}:{ti}:{page - 1}:{view}",
                )
            )
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
                    callback_data=f"xfd:tm:{code}:{ti}:{page + 1}:{view}",
                )
            )
        kb_rows.append(nav)
    kb_rows.append(
        [
            InlineKeyboardButton(
                text=f"← {_LEAGUE_TITLE.get(code, code)}",
                callback_data=f"xfd:lg:{code}",
            )
        ]
    )
    return InlineKeyboardMarkup(inline_keyboard=kb_rows)


def _format_team_detail(
    team: str,
    rows: list[TransferAdviceRow],
    *,
    view: str,
    page: int,
) -> tuple[str, int, dict[str, int]]:
    counts = {v: sum(1 for r in rows if r.verdict == v) for v in ("НО", "СО", "СУ", "НУ")}
    advice_view = _VIEW_TO_VERDICT.get(view, view)
    text, total_pages = format_team_advice_html(
        team,
        rows,
        view=advice_view if view in _VIEW_TO_VERDICT else view,
        page=page,
        page_size=_DASH_ADVICE_PAGE_SIZE,
        quota=quota_line(team),
    )
    return text, total_pages, counts


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
        F.data.regexp(
            r"^xfd:tm:([a-z]+):(\d+)(?::(\d+))?(?::(summary|nu|su|so|no|sell|all))?$"
        )
    )
    async def cb_dash_team(callback: CallbackQuery) -> None:
        import re

        m = re.match(
            r"^xfd:tm:([a-z]+):(\d+)(?::(\d+))?(?::(summary|nu|su|so|no|sell|all))?$",
            callback.data or "",
        )
        if not m:
            await callback.answer()
            return
        code = m.group(1)
        ti = int(m.group(2))
        page = int(m.group(3)) if m.group(3) else 0
        view = _parse_team_view(m.group(4))
        team = _team_at(code, ti)
        if not team:
            await callback.answer("Клуб не найден", show_alert=True)
            return
        canon, rows, err = collect_transfer_advice(team)
        if err:
            await callback.answer(err, show_alert=True)
            return
        text, total_pages, counts = _format_team_detail(
            canon, rows, view=view, page=page
        )
        await callback.answer()
        if callback.message:
            try:
                await callback.message.edit_text(
                    text,
                    parse_mode="HTML",
                    reply_markup=_team_detail_kb(
                        code,
                        ti,
                        view=view,
                        page=page,
                        total_pages=total_pages,
                        counts=counts,
                        advice_rows=rows,
                    ),
                )
            except Exception:
                await callback.message.answer(
                    text,
                    parse_mode="HTML",
                    reply_markup=_team_detail_kb(
                        code,
                        ti,
                        view=view,
                        page=page,
                        total_pages=total_pages,
                        counts=counts,
                        advice_rows=rows,
                    ),
                )

    @router.callback_query(
        F.data.regexp(
            r"^xfd:pl:([a-z]+):(\d+):(summary|nu|su|so|no|sell|all):(\d+):(\d+)$"
        )
    )
    async def cb_dash_player_card(callback: CallbackQuery) -> None:
        import re

        m = re.match(
            r"^xfd:pl:([a-z]+):(\d+):(summary|nu|su|so|no|sell|all):(\d+):(\d+)$",
            callback.data or "",
        )
        if not m:
            await callback.answer()
            return
        code, ti_s, view, page_s, idx_s = (
            m.group(1),
            m.group(2),
            m.group(3),
            m.group(4),
            m.group(5),
        )
        ti, page, idx = int(ti_s), int(page_s), int(idx_s)
        team = _team_at(code, ti)
        if not team:
            await callback.answer("Клуб не найден", show_alert=True)
            return
        canon, rows, err = collect_transfer_advice(team)
        if err:
            await callback.answer(err, show_alert=True)
            return
        flat = flat_advice_rows(rows, view)
        if idx < 0 or idx >= len(flat):
            await callback.answer("Игрок не найден", show_alert=True)
            return
        row = flat[idx]
        card = format_player_advice_card_html(canon, row)
        back_cb = f"xfd:tm:{code}:{ti}:{page}:{view}"
        kb = InlineKeyboardMarkup(
            inline_keyboard=[
                [
                    InlineKeyboardButton(
                        text="← К составу",
                        callback_data=back_cb,
                    )
                ]
            ]
        )
        await callback.answer()
        if callback.message:
            await callback.message.edit_text(
                card, parse_mode="HTML", reply_markup=kb
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
        sell_rows = flat_advice_rows(rows, "sell")
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
        sell_rows = flat_advice_rows(rows, "sell")
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
