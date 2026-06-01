"""Ввод счёта матча в боте (аналог «n» и «m» в консоли)."""
from __future__ import annotations

import asyncio
import logging
import re
from html import escape as html_escape
from typing import Final
from unicodedata import normalize

from aiogram import F, Router
from aiogram.filters import BaseFilter, Command, StateFilter
from aiogram.fsm.context import FSMContext
from aiogram.types import (
    CallbackQuery,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    Message,
)

from bot.services import (
    LEAGUE_LABELS,
    needs_cl_penalty_shootout,
    run_process_match_bot,
    split_text_chunks,
)
from bot.keyboards import MENU_REPLY_TEXT
from bot.menu_content import deliver_help_screen, deliver_main_menu_refresh
from bot.states import (
    AddOnlyStats,
    ClPenalties,
    MatchEnter,
    MatchPerfRatingEnter,
    PostMatch,
    SkipPlay,
)
from utils.player_discipline import format_discipline_pre_match_notice_html

logger = logging.getLogger(__name__)

match_router = Router()

_SCORE_RE: Final = re.compile(r"^\s*(\d+)\s+(\d+)\s*$")

# Не перехватывать /help и прочие команды как счёт или имя команды
_TEXT_NOT_CMD: Final = F.text & ~F.text.startswith("/")


class MenuReplyFilter(BaseFilter):
    """Текст кнопки «📋 Меню» с учётом разных NFC/NFD у эмодзи."""

    async def __call__(self, message: Message) -> bool:
        raw = message.text
        if raw is None:
            return False
        return normalize("NFC", raw.strip()) == normalize("NFC", MENU_REPLY_TEXT)


def _league_title(code: str) -> str:
    return dict(LEAGUE_LABELS).get(code, code)


async def _finish_match_and_offer_stats(
    message: Message,
    state: FSMContext,
    *,
    ok: bool,
    log: str,
    home: str,
    away: str,
    hs: int,
    aws: int,
    league_code: str,
    schedule_day: int | None = None,
) -> None:
    """После записи матча — опционально предложить статистику (если INPUT_PLAYER_STATS в main)."""
    from main import INPUT_PLAYER_STATS

    log_html = html_escape(log)
    if not ok:
        await state.clear()
        txt = log if log else "Не удалось записать матч."
        await message.answer(f"✗ {txt}")
        return

    await message.answer(f"✓ Записано.\n{log_html}", parse_mode="HTML")

    if not INPUT_PLAYER_STATS:
        await state.clear()
        await _send_post_match_continue_prompt(message)
        return

    await state.clear()
    await state.set_state(PostMatch.offer_stats)
    await state.update_data(
        stats_home=home.strip().title(),
        stats_away=away.strip().title(),
        stats_hs=hs,
        stats_aws=aws,
        stats_tournament="cl" if league_code == "cl" else "league",
        stats_league_code=league_code,
        stats_schedule_day=schedule_day,
    )
    kb = InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="📊 Да, статистика",
                    callback_data="postmatch:stats_y",
                ),
                InlineKeyboardButton(
                    text="⏭ Нет",
                    callback_data="postmatch:stats_n",
                ),
            ]
        ]
    )
    await message.answer(
        "Добавить статистику игроков (голы, передачи, сухие)?",
        reply_markup=kb,
    )


async def _record_match_or_request_penalties(
    message: Message,
    state: FSMContext,
    *,
    home: str,
    away: str,
    hs: int,
    aws: int,
    league_code: str,
    round_num: int | None,
    cl_ph: str | None,
) -> None:
    """Запись матча или запрос серии пенальти (ЛЧ нокаут, ничья по сумме двух матчей)."""
    hn = home.strip().title()
    an = away.strip().title()

    if needs_cl_penalty_shootout(hn, an, hs, aws, league_code, cl_ph):
        await state.set_state(ClPenalties.waiting)
        await state.update_data(
            pen_home=hn,
            pen_away=an,
            pen_hs=hs,
            pen_aws=aws,
            pen_league=league_code,
            pen_round=round_num,
            pen_cl_ph=cl_ph,
        )
        from utils.cl_knockout_schedule import format_first_leg_score_html

        first_leg = format_first_leg_score_html(hn, an)
        await message.answer(
            f"{first_leg}"
            "По сумме двух матчей ничья — нужна серия пенальти после ответного матча.\n"
            f"Введи два числа через пробел: голы в серии <b>{hn}</b> (хозяева ответного) "
            f"и <b>{an}</b> (гости), например: <code>5 4</code>\n"
            "В серии должен быть победитель — числа не должны совпадать.\n/cancel — отмена.",
            parse_mode="HTML",
        )
        return

    ok, log = await asyncio.to_thread(
        run_process_match_bot,
        hn,
        an,
        hs,
        aws,
        league_code,
        round_num=round_num,
        cl_phase=cl_ph,
    )
    await _finish_match_and_offer_stats(
        message,
        state,
        ok=ok,
        log=log,
        home=hn,
        away=an,
        hs=hs,
        aws=aws,
        league_code=league_code,
        schedule_day=round_num,
    )


def _manual_league_kb() -> InlineKeyboardMarkup:
    rows: list[list[InlineKeyboardButton]] = []
    row: list[InlineKeyboardButton] = []
    for code, label in LEAGUE_LABELS:
        row.append(InlineKeyboardButton(text=label, callback_data=f"man:{code}"))
        if len(row) == 3:
            rows.append(row)
            row = []
    if row:
        rows.append(row)
    return InlineKeyboardMarkup(inline_keyboard=rows)


def _cl_phase_kb(prefix: str) -> InlineKeyboardMarkup:
    """prefix: mancl (ручной матч) или asoncl (стата без матч-дня)."""
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="Группа (league)",
                    callback_data=f"{prefix}:league",
                ),
                InlineKeyboardButton(
                    text="Нокаут (knockout)",
                    callback_data=f"{prefix}:knockout",
                ),
            ]
        ]
    )


def _cl_phase_short_label(phase: str) -> str:
    return "группа" if phase == "league" else "нокаут"


_MANUAL_PICK_PAGE = 10


def _sorted_team_names_for_manual(league_code: str) -> list[str]:
    """Имена клубов для кнопок ручного матча (актуальный пул текущего сезона)."""
    from bot.services import teams_ordered_for_goalscorers

    if league_code != "cl":
        return teams_ordered_for_goalscorers(league_code)

    # ЛЧ: берём текущий список участников из pickle.
    import teams as teams_mod

    m = {
        "cl": teams_mod.teams_champ_league,
    }
    teams = m.get(league_code)
    if not teams:
        return []
    return sorted(teams.keys(), key=lambda s: (s or "").casefold())


def _manual_team_pick_kb(
    names: list[str],
    page: int,
    *,
    which: str,
) -> InlineKeyboardMarkup:
    """
    which: "h" — хозяева (индекс в полном списке), "a" — гости (индекс в names = away list).
    """
    n = len(names)
    if n == 0:
        return InlineKeyboardMarkup(
            inline_keyboard=[
                [InlineKeyboardButton(text="✏️ Ввести вручную", callback_data="mtp:x:h")],
            ],
        )
    total_pages = max(1, (n + _MANUAL_PICK_PAGE - 1) // _MANUAL_PICK_PAGE)
    page = max(0, min(int(page), total_pages - 1))
    start = page * _MANUAL_PICK_PAGE
    chunk = names[start : start + _MANUAL_PICK_PAGE]

    rows: list[list[InlineKeyboardButton]] = []
    for j, name in enumerate(chunk):
        idx = start + j
        label = name if len(name) <= 50 else name[:47] + "…"
        rows.append(
            [
                InlineKeyboardButton(
                    text=label,
                    callback_data=f"mtp:{which}:{idx}",
                ),
            ],
        )
    nav: list[InlineKeyboardButton] = []
    if page > 0:
        nav.append(
            InlineKeyboardButton(text="←", callback_data=f"mpt:{which}:{page - 1}")
        )
    if page < total_pages - 1:
        nav.append(
            InlineKeyboardButton(text="→", callback_data=f"mpt:{which}:{page + 1}")
        )
    if nav:
        rows.append(nav)
    tag = "h" if which == "h" else "a"
    rows.append(
        [InlineKeyboardButton(text="✏️ Ввести вручную", callback_data=f"mtp:x:{tag}")],
    )
    return InlineKeyboardMarkup(inline_keyboard=rows)


def _manual_banner_home_pick(data: dict) -> str:
    lc = data.get("league_code") or ""
    title = html_escape(_league_title(lc))
    extra = ""
    if lc == "cl" and data.get("cl_ph"):
        extra = f" · {_cl_phase_short_label(str(data.get('cl_ph')))}"
    return (
        f"Лига: <b>{title}{html_escape(extra)}</b>\n"
        "Выбери <b>хозяев</b> (внизу — ввод текста):"
    )


def _manual_banner_away_pick(data: dict, home: str) -> str:
    lc = data.get("league_code") or ""
    title = html_escape(_league_title(lc))
    extra = ""
    if lc == "cl" and data.get("cl_ph"):
        extra = f" · {_cl_phase_short_label(str(data.get('cl_ph')))}"
    return (
        f"Лига: <b>{title}{html_escape(extra)}</b>\n"
        f"Хозяева: <b>{html_escape(home)}</b>\n"
        "Выбери <b>гостей</b>:"
    )


async def _answer_manual_score_prompt(
    message: Message, state: FSMContext, home: str, away: str
) -> None:
    from config.leagues_config import manager_session_label

    mode = manager_session_label(home, away)
    mode_head = f"<b>{html_escape(mode)}</b>\n\n" if mode else ""
    data = await state.get_data()
    cl_ph = data.get("cl_ph") if data.get("league_code") == "cl" else None
    first_leg_block = ""
    if cl_ph == "knockout":
        from utils.cl_knockout_schedule import format_first_leg_score_html

        first_leg_block = format_first_leg_score_html(home, away)
    await state.update_data(away_raw=away)
    await state.set_state(MatchEnter.manual_score)
    await message.answer(
        f"{mode_head}"
        f"{first_leg_block}"
        "Введи счёт два числа через пробел (хозяева гости), например: 2 1",
        parse_mode="HTML",
    )


def build_ason_league_kb() -> InlineKeyboardMarkup:
    """Выбор лиги: сыгранные матчи из календаря (как «Из календаря», но только журнал)."""
    rows: list[list[InlineKeyboardButton]] = [
        [
            InlineKeyboardButton(
                text="Все чемпионаты",
                callback_data="asonf:all",
            ),
        ],
    ]
    row: list[InlineKeyboardButton] = []
    for code, label in LEAGUE_LABELS:
        row.append(InlineKeyboardButton(text=label, callback_data=f"asonf:{code}"))
        if len(row) == 3:
            rows.append(row)
            row = []
    if row:
        rows.append(row)
    return InlineKeyboardMarkup(inline_keyboard=rows)


async def _finalize_stats_session(message: Message, state: FSMContext) -> None:
    """Закрыть ввод строк статистики; при режиме «только стата» — добавить матч в журнал при необходимости."""
    data = await state.get_data()
    pj = data.get("pending_journal")

    h = data.get("stats_home")
    a = data.get("stats_away")
    lc = data.get("stats_league_code")
    tourn = data.get("stats_tournament", "league")
    if h and a:
        if not lc:
            from player_stats import infer_league_code_for_stats

            lc = infer_league_code_for_stats(h, a, tourn)
        cl_ph = None
        if tourn == "cl" or lc == "cl":
            from match_results import find_journal_match_record

            rec = await asyncio.to_thread(
                find_journal_match_record, h, a, lc or "cl", cl_phase=None
            )
            if rec:
                cl_ph = rec.get("cl_phase")
        from matches_stats_tracking import mark_stats_completed

        await asyncio.to_thread(
            mark_stats_completed,
            h,
            a,
            tourn,
            cl_phase=cl_ph,
            day=data.get("stats_schedule_day"),
        )
        from utils.player_discipline import register_match_played_for_discipline

        snap = data.get("stats_susp_snapshot")
        await asyncio.to_thread(
            register_match_played_for_discipline,
            h,
            a,
            lc,
            tourn,
            susp_snapshot_before_stats=snap,
        )
        from utils.player_loans import process_loan_expirations

        loan_logs = await asyncio.to_thread(
            process_loan_expirations, data.get("stats_schedule_day")
        )
        if loan_logs:
            tail = "\n".join(loan_logs[:8])
            more = f"\n…ещё {len(loan_logs) - 8}" if len(loan_logs) > 8 else ""
            await message.answer(f"Аренды:\n{tail}{more}")

    await state.clear()

    extra = ""
    if pj:
        from match_results import add_match_result, is_match_played as _played

        h = pj["home"]
        a = pj["away"]
        lc = pj["lc"]
        hs = pj["hs"]
        aws = pj["aws"]
        if lc == "cl":
            cl_ph = pj.get("cl_phase", "knockout")
        else:
            cl_ph = None
        if not _played(h, a, lc, cl_phase=cl_ph):
            add_match_result(
                h,
                a,
                lc,
                home_score=hs,
                away_score=aws,
                cl_phase=cl_ph,
            )
            extra = "\nМатч добавлен в журнал match_results.json."

    await message.answer(f"Готово. Статистика сохранена в базу.{extra}")
    await _send_post_match_continue_prompt(message)


def _slot_from_schedule_tuple(tup: tuple) -> dict | None:
    day, match_str, home, away, league_code = tup
    if day is None:
        return None
    from match_results import cl_phase_from_mixed_schedule_line

    cl_ph = (
        cl_phase_from_mixed_schedule_line(match_str) if league_code == "cl" else None
    )
    from utils.calendar_slot_labels import home_display_tour
    from utils.player_discipline import find_fixture_round

    slot = {
        "day": day,
        "match_str": match_str,
        "home": home,
        "away": away,
        "league_code": league_code,
        "cl_ph": cl_ph,
        "display_round": home_display_tour(home, league_code),
        "fixture_round": find_fixture_round(
            home, away, league_code, cl_phase=cl_ph
        ),
    }
    return slot


def _skipped_row_to_slot(row: dict) -> dict:
    """Слот отложенного матча: ``round`` в JSON — месяц календаря при отложении."""
    from utils.calendar_slot_labels import home_display_tour
    from utils.player_discipline import find_fixture_round

    lc = str(row.get("tournament") or "")
    cl_ph = row.get("cl_phase") if lc == "cl" else None
    home = row.get("home")
    away = row.get("away")
    return {
        "day": row.get("round"),
        "home": home,
        "away": away,
        "league_code": lc,
        "cl_ph": cl_ph,
        "display_round": home_display_tour(str(home or ""), lc),
        "fixture_round": find_fixture_round(
            str(home or ""),
            str(away or ""),
            lc,
            cl_phase=cl_ph,
        ),
    }


async def _peek_next_schedule_slot(session_kind: str | None) -> dict | None:
    from main import find_next_match_in_schedule, load_or_generate_mixed_schedule

    sch = await asyncio.to_thread(load_or_generate_mixed_schedule)
    tup = await asyncio.to_thread(find_next_match_in_schedule, sch, session_kind)
    return _slot_from_schedule_tuple(tup)


def _calendar_slot_btn_label(slot: dict, *, index: int | None = None) -> str:
    """
    Подпись кнопки: месяц, тур (лига: след. у хозяев), матч, турнир, сим/игра.
    Пример: ``1. м2 т6 · Бавария — Вольфсбург (Бундеслига, сим)``; ЛЧ без ``т``.
    """
    from config.leagues_config import manager_session_label
    from utils.calendar_slot_labels import home_display_tour

    home = str(slot.get("home") or "?").strip()
    away = str(slot.get("away") or "?").strip()
    lc_code = str(slot.get("league_code") or slot.get("tournament") or "")
    lg = _league_title(lc_code)

    month = slot.get("day", "?")
    rnd = slot.get("display_round")
    if rnd is None:
        rnd = home_display_tour(home, lc_code)
    rnd_part = f" т{rnd}" if rnd is not None else ""

    mode = manager_session_label(home, away) or "?"
    mode_short = "игра" if mode == "Игра" else ("сим" if mode == "Симуляция" else "?")

    head = f"{index}. " if index is not None else ""
    meta = f"({lg}, {mode_short})"

    def _pack(h: str, a: str, sep: str = " — ") -> str:
        return f"{head}м{month}{rnd_part} · {h}{sep}{a} {meta}"

    for h, a, sep in (
        (home, away, " — "),
        (home, away, "—"),
    ):
        label = _pack(h, a, sep)
        if len(label) <= 64:
            return label

    budget = 64 - len(f"{head}м{month}{rnd_part} · ") - len(f" {meta}")
    if budget < 10:
        short = f"{head}м{month}{rnd_part} {meta}"
        return short if len(short) <= 64 else short[:61] + "…"
    half = max(4, (budget - 1) // 2)
    h_s = home if len(home) <= half else home[: half - 1].rstrip() + "…"
    rem = budget - len(h_s) - 1
    a_s = away if len(away) <= rem else away[: max(3, rem - 1)].rstrip() + "…"
    label = f"{head}м{month}{rnd_part} · {h_s}—{a_s} {meta}"
    return label if len(label) <= 64 else label[:61] + "…"


def _played_slot_btn_label(slot: dict, *, index: int | None = None) -> str:
    """Как календарь, но со счётом из журнала: ``… · Х 2:1 Г (лига, сим)``."""
    hs = slot.get("home_score")
    aws = slot.get("away_score")
    score_s = f" {hs}:{aws}" if hs is not None and aws is not None else ""
    home = str(slot.get("home") or "?").strip()
    away = str(slot.get("away") or "?").strip()
    lc_code = str(slot.get("league_code") or slot.get("tournament") or "")
    lg = _league_title(lc_code)
    from config.leagues_config import manager_session_label
    from utils.calendar_slot_labels import home_display_tour

    month = slot.get("day", "?")
    rnd = slot.get("display_round")
    if rnd is None:
        rnd = home_display_tour(home, lc_code)
    rnd_part = f" т{rnd}" if rnd is not None else ""
    mode = manager_session_label(home, away) or "?"
    mode_short = "игра" if mode == "Игра" else ("сим" if mode == "Симуляция" else "?")
    head = f"{index}. " if index is not None else ""
    meta = f"({lg}, {mode_short})"
    core = f"{head}м{month}{rnd_part} · {home}{score_s} — {away} {meta}"
    if len(core) <= 64:
        return core
    short_meta = f"({lg})"
    core2 = f"{head}м{month} · {home}{score_s}—{away} {short_meta}"
    return core2 if len(core2) <= 64 else core2[:61] + "…"


def _ason_play_kind_kb(league_key: str) -> InlineKeyboardMarkup:
    lg = league_key
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(text="Все типы", callback_data=f"asonpk:{lg}:all"),
                InlineKeyboardButton(text="Симуляция", callback_data=f"asonpk:{lg}:sim"),
                InlineKeyboardButton(text="Игра", callback_data=f"asonpk:{lg}:game"),
            ],
            [
                InlineKeyboardButton(
                    text="← К выбору месяца",
                    callback_data=f"asonmo:{lg}",
                ),
            ],
        ]
    )


def _ason_play_month_kb(league_key: str, months: list[int]) -> InlineKeyboardMarkup:
    """Месяц календаря: «все» или конкретный ``мN`` (только месяцы с сыгранными матчами)."""
    lg = league_key
    rows: list[list[InlineKeyboardButton]] = [
        [
            InlineKeyboardButton(
                text="Все месяцы",
                callback_data=f"asonm:{lg}:all",
            ),
        ],
    ]
    row: list[InlineKeyboardButton] = []
    for m in months:
        row.append(
            InlineKeyboardButton(text=f"м{m}", callback_data=f"asonm:{lg}:{m}")
        )
        if len(row) == 4:
            rows.append(row)
            row = []
    if row:
        rows.append(row)
    rows.append(
        [
            InlineKeyboardButton(
                text="← К выбору чемпионата",
                callback_data="asonf:back",
            ),
        ]
    )
    return InlineKeyboardMarkup(inline_keyboard=rows)


def _ason_month_filter_label(month_filter: int | None) -> str:
    if month_filter is None:
        return "все месяцы"
    return f"месяц {month_filter}"


def _ason_filter_played_list(ordered: list, data: dict) -> list:
    cph = data.get("ason_pick_cl_ph") or data.get("ason_cl_ph")
    lf = (data.get("ason_pick_lf") or data.get("ason_league") or "").strip().lower()
    if lf == "cl" and cph:
        ordered = [r for r in ordered if (r.get("cl_ph") or "knockout") == cph]
    return ordered


def _ason_pick_kb(
    ordered: list,
    *,
    page: int,
    league_filter: str = "all",
    session_kind: str = "all",
) -> InlineKeyboardMarkup:
    n = len(ordered)
    if not ordered:
        raise ValueError("ason pick keyboard requires non-empty list")
    lf = (league_filter or "all").strip().lower() or "all"
    sk = (session_kind or "all").strip().lower() or "all"
    total_pages = max(1, (n + _SCHED_PAGE_SIZE - 1) // _SCHED_PAGE_SIZE)
    page = max(0, min(int(page), total_pages - 1))
    start = page * _SCHED_PAGE_SIZE
    chunk = ordered[start : start + _SCHED_PAGE_SIZE]

    rows: list[list[InlineKeyboardButton]] = []
    for j, row in enumerate(chunk):
        idx = start + j
        label = _played_slot_btn_label(row, index=idx + 1)
        rows.append(
            [
                InlineKeyboardButton(
                    text=label,
                    callback_data=f"asonpick:{idx}:{lf}:{sk}",
                ),
            ]
        )

    nav: list[InlineKeyboardButton] = []
    if page > 0:
        nav.append(
            InlineKeyboardButton(
                text=f"« {page}",
                callback_data=f"asonpage:{page - 1}:{lf}:{sk}",
            )
        )
    nav.append(
        InlineKeyboardButton(
            text=f"{page + 1}/{total_pages}",
            callback_data="ason:noop",
        )
    )
    if page < total_pages - 1:
        nav.append(
            InlineKeyboardButton(
                text=f"{page + 2} »",
                callback_data=f"asonpage:{page + 1}:{lf}:{sk}",
            )
        )
    rows.append(nav)
    rows.append(
        [
            InlineKeyboardButton(
                text="← Фильтры (месяц / тип)",
                callback_data=f"asonmo:{lf}",
            ),
        ]
    )
    return InlineKeyboardMarkup(inline_keyboard=rows)


def _ason_pick_intro_html(
    page: int,
    total_pages: int,
    *,
    league_filter: str = "all",
    session_kind: str = "all",
    month_filter: int | None = None,
) -> str:
    note = (
        f"\nСтраница <b>{page + 1}</b> из <b>{total_pages}</b> "
        f"(по {_SCHED_PAGE_SIZE} матчей; порядок как в mixed_schedule)."
    )
    cap = _schedule_play_filter_caption(league_filter, session_kind)
    mo = html_escape(_ason_month_filter_label(month_filter))
    return (
        f"{cap} · <b>{mo}</b>\n\n"
        "<b>Очередь «без статы»</b> — только матчи, где после счёта нажали «Нет» "
        "(см. <code>data/matches_stats_pending.json</code>). Выбери матч → ввод статы.\n"
        f"{note}"
    )


async def _ordered_played_filtered(
    league_filter: str,
    session_kind: str,
    *,
    month_filter: int | None = None,
) -> list:
    from main import list_played_schedule_matches, load_or_generate_mixed_schedule

    lf = (league_filter or "all").strip().lower() or "all"
    sk = (session_kind or "all").strip().lower() or "all"
    sch = await asyncio.to_thread(load_or_generate_mixed_schedule)
    return await asyncio.to_thread(
        list_played_schedule_matches,
        sch,
        league_filter=None if lf == "all" else lf,
        session_kind=None if sk == "all" else sk,
        month_filter=month_filter,
        only_without_stats=True,
    )


async def _ason_played_months_for_league(league_key: str, data: dict) -> list[int]:
    """Номера месяцев календаря, в которых есть сыгранные матчи (по лиге / фазе ЛЧ)."""
    ordered = await _ordered_played_filtered(league_key, "all", month_filter=None)
    ordered = _ason_filter_played_list(ordered, data)
    return sorted({int(r["day"]) for r in ordered if r.get("day") is not None})


async def _send_ason_month_step(
    message: Message,
    state: FSMContext,
    league_key: str,
    *,
    edit: bool = False,
) -> None:
    data = await state.get_data()
    months = await _ason_played_months_for_league(league_key, data)
    lg_title = html_escape(_league_title(league_key) if league_key != "all" else "все чемпионаты")
    phase = data.get("ason_cl_ph")
    phase_s = ""
    if league_key == "cl" and phase:
        phase_s = f" · {_cl_phase_short_label(phase)}"
    if not months:
        text = (
            f"Чемпионат: <b>{lg_title}</b>{phase_s}\n"
            "Нет матчей без статистики по этому фильтру — выбери другой чемпионат."
        )
        kb = build_ason_league_kb()
    else:
        text = (
            f"Чемпионат: <b>{lg_title}</b>{phase_s}\n"
            "Выбери <b>месяц</b> календаря или «Все месяцы», затем тип матча."
        )
        kb = _ason_play_month_kb(league_key, months)
    if edit:
        try:
            await message.edit_text(text, reply_markup=kb, parse_mode="HTML")
            return
        except Exception:
            pass
    await message.answer(text, reply_markup=kb, parse_mode="HTML")


async def _show_ason_pick_list(
    message: Message,
    state: FSMContext,
    *,
    league_key: str,
    session_kind: str,
    page: int = 0,
    edit: bool = True,
) -> None:
    data = await state.get_data()
    month = data.get("ason_month")
    if month is not None:
        month = int(month)
    ordered = await _ordered_played_filtered(
        league_key, session_kind, month_filter=month
    )
    ordered = _ason_filter_played_list(ordered, data)
    if not ordered:
        text = (
            "По фильтру нет матчей без статистики. "
            "Попробуй другой месяц, тип или чемпионат."
        )
        kb = _ason_play_kind_kb(league_key)
        if edit:
            try:
                await message.edit_text(text, reply_markup=kb, parse_mode="HTML")
                return
            except Exception:
                pass
        await message.answer(text, reply_markup=kb, parse_mode="HTML")
        return

    total_pages = max(1, (len(ordered) + _SCHED_PAGE_SIZE - 1) // _SCHED_PAGE_SIZE)
    page = max(0, min(page, total_pages - 1))
    kb = _ason_pick_kb(
        ordered,
        page=page,
        league_filter=league_key,
        session_kind=session_kind,
    )
    text = _ason_pick_intro_html(
        page,
        total_pages,
        league_filter=league_key,
        session_kind=session_kind,
        month_filter=month,
    )
    await state.update_data(
        ason_pick_lf=league_key,
        ason_pick_sk=session_kind,
        ason_pick_cl_ph=data.get("ason_cl_ph"),
    )
    if edit:
        try:
            await message.edit_text(text, reply_markup=kb, parse_mode="HTML")
            return
        except Exception:
            pass
    await message.answer(text, reply_markup=kb, parse_mode="HTML")


async def _send_ason_stats_intro(message: Message, state: FSMContext) -> None:
    await state.clear()
    await state.set_state(AddOnlyStats.browsing)
    await message.answer(
        "📊 <b>Стата без матча</b> — чемпионат → месяц (или все) → тип (сим / игра / всё). "
        "Только матчи из очереди: после счёта нажал «Нет» на стате — попадёт в "
        "<code>matches_stats_pending.json</code> и отобразится здесь.\n"
        "/cancel — отмена.",
        reply_markup=build_ason_league_kb(),
        parse_mode="HTML",
    )


async def _begin_stats_for_played_slot(
    message: Message,
    state: FSMContext,
    slot: dict,
) -> None:
    from match_results import find_journal_match_record

    home = str(slot["home"]).strip().title()
    away = str(slot["away"]).strip().title()
    hs = int(slot["home_score"])
    aws = int(slot["away_score"])
    lc = str(slot["league_code"])
    cl_ph = slot.get("cl_ph")
    rec = await asyncio.to_thread(
        find_journal_match_record, home, away, lc, cl_phase=cl_ph
    )
    if rec and lc == "cl":
        cl_ph = rec.get("cl_phase") or cl_ph

    await state.clear()
    await state.update_data(
        stats_home=home,
        stats_away=away,
        stats_hs=hs,
        stats_aws=aws,
        stats_tournament="cl" if lc == "cl" else "league",
        stats_league_code=lc,
        stats_schedule_day=slot.get("day"),
    )
    hn = html_escape(home)
    an = html_escape(away)
    await message.answer(
        f"Матч: <b>{hn}</b> <code>{hs}:{aws}</code> <b>{an}</b> — счёт из журнала.",
        parse_mode="HTML",
    )
    await _start_stats_team_flow(message, state)


def _post_match_continue_kb(
    sim_slot: dict | None, game_slot: dict | None
) -> InlineKeyboardMarkup:
    rows: list[list[InlineKeyboardButton]] = []
    if sim_slot:
        rows.append(
            [
                InlineKeyboardButton(
                    text=_calendar_slot_btn_label(sim_slot, index=1),
                    callback_data="play:next:sim",
                )
            ]
        )
    else:
        rows.append(
            [
                InlineKeyboardButton(
                    text="— нет сим-матча в очереди",
                    callback_data="play:post:noop:sim",
                )
            ]
        )
    if game_slot:
        rows.append(
            [
                InlineKeyboardButton(
                    text=_calendar_slot_btn_label(
                        game_slot, index=2 if sim_slot else 1
                    ),
                    callback_data="play:next:game",
                )
            ]
        )
    else:
        rows.append(
            [
                InlineKeyboardButton(
                    text="— нет игрового матча в очереди",
                    callback_data="play:post:noop:game",
                )
            ]
        )
    rows.append(
        [InlineKeyboardButton(text="📋 Меню", callback_data="play:post:menu")]
    )
    return InlineKeyboardMarkup(inline_keyboard=rows)


async def _send_post_match_continue_prompt(message: Message) -> None:
    sim_slot, game_slot = await asyncio.gather(
        _peek_next_schedule_slot("sim"),
        _peek_next_schedule_slot("game"),
    )
    if not sim_slot and not game_slot:
        await message.answer(
            "В календаре не осталось несыгранных матчей (или только отложенные).",
            reply_markup=_post_match_continue_kb(None, None),
        )
        return

    await message.answer(
        "<b>Что дальше?</b> Выбери матч кнопкой (как в «Из календаря»).",
        reply_markup=_post_match_continue_kb(sim_slot, game_slot),
        parse_mode="HTML",
    )


def _stats_flow_team(data: dict) -> str:
    side = (data.get("stats_flow_side") or "home").strip().lower()
    return data["stats_home"] if side == "home" else data["stats_away"]


def _stats_lines_done_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="✓ Готово (команда)", callback_data="stats:done")],
        ]
    )


async def _start_stats_team_flow(message: Message, state: FSMContext) -> None:
    """Сначала список «кто сыграл» хозяева → стата → гости → стата."""
    data = await state.get_data()
    home = data["stats_home"]
    away = data["stats_away"]
    hs = data["stats_hs"]
    aws = data["stats_aws"]
    lc = data.get("stats_league_code") or ""
    tourn = data.get("stats_tournament", "league")
    from utils.player_discipline import snapshot_suspensions_for_fixture

    snap = await asyncio.to_thread(
        snapshot_suspensions_for_fixture, home, away, lc, tourn
    )
    await state.update_data(
        stats_played_keys=[],
        stats_session_match_keys=[],
        stats_session_acc={},
        stats_roster_buffer=[],
        stats_flow_side="home",
        stats_mode_new=False,
        stats_susp_snapshot=snap,
        stats_pending_confirm=None,
    )
    dry_lines: list[str] = []
    if int(aws) == 0:
        dry_lines.append(f"💪 {home} — сухой матч для гостей (0 голов).")
    if int(hs) == 0:
        dry_lines.append(f"💪 {away} — сухой матч для хозяев (0 голов).")
    if dry_lines:
        await message.answer(html_escape("\n".join(dry_lines)), parse_mode="HTML")
    hn = html_escape(home)
    an = html_escape(away)
    await message.answer(
        f"Матч <b>{hn}</b> <code>{hs}:{aws}</code> <b>{an}</b>\n"
        "По очереди: <b>кто сыграл</b> (списком) → <b>стата</b> для этой команды → вторая команда.",
        parse_mode="HTML",
    )
    await _send_stats_roster_prompt(message, state)


async def _send_stats_roster_prompt(message: Message, state: FSMContext) -> None:
    from bot.services import split_text_chunks
    from player_stats import format_single_team_roster_text

    data = await state.get_data()
    team = _stats_flow_team(data)
    tourn = data.get("stats_tournament", "league")
    side = data.get("stats_flow_side", "home")
    side_lab = "хозяева" if side == "home" else "гости"
    await state.update_data(stats_roster_buffer=[])
    await state.set_state(PostMatch.stats_roster_list)

    cheat = await asyncio.to_thread(format_single_team_roster_text, team, tourn)
    if cheat:
        for chunk in split_text_chunks(html_escape(cheat)):
            await message.answer(
                f"<pre>Состав · {html_escape(team)}\n{chunk}</pre>",
                parse_mode="HTML",
            )
    await message.answer(
        f"<b>Кто сыграл у {html_escape(team)}</b> ({side_lab})?\n\n"
        "Пиши <b>по одному игроку в строке</b> — можно сразу несколько строк в одном сообщении "
        "(фамилия или имя как в БД).\n"
        "Когда список готов — <code>/done</code>. /cancel — отмена.",
        parse_mode="HTML",
    )


async def _finish_stats_roster_for_team(message: Message, state: FSMContext) -> None:
    from utils.match_stats_bot import apply_roster_names_for_team

    data = await state.get_data()
    names = list(data.get("stats_roster_buffer") or [])
    if not names:
        await message.answer(
            "Список пуст. Напиши игроков (по строке) или /cancel."
        )
        return
    team = _stats_flow_team(data)
    tourn = str(data.get("stats_tournament", "league"))
    keys, ok_lines, err_lines = await asyncio.to_thread(
        apply_roster_names_for_team, names, team, tournament=tourn
    )
    played = sorted(set(data.get("stats_played_keys") or []) | set(keys))
    await state.update_data(
        stats_played_keys=played,
        stats_session_match_keys=sorted(set(data.get("stats_session_match_keys") or []) | set(keys)),
        stats_roster_buffer=[],
    )
    parts: list[str] = [f"✓ <b>{html_escape(team)}</b> — матчи (+1): <b>{len(ok_lines)}</b>"]
    if ok_lines:
        preview = "\n".join(html_escape(x) for x in ok_lines[:10])
        more = f"\n…ещё {len(ok_lines) - 10}" if len(ok_lines) > 10 else ""
        parts.append(preview + more)
    if err_lines:
        parts.append(
            "\n⚠ Не засчитано:\n"
            + "\n".join(html_escape(x) for x in err_lines[:12])
        )
    await message.answer("\n".join(parts), parse_mode="HTML")
    await _send_stats_lines_ui(message, state)


async def _advance_after_team_stats_lines(message: Message, state: FSMContext) -> None:
    data = await state.get_data()
    if data.get("stats_pending_confirm"):
        await message.answer(
            "Сначала ответь «Да, играл» или «Нет» на вопрос выше."
        )
        return
    side = (data.get("stats_flow_side") or "home").strip().lower()
    if side == "home":
        await state.update_data(stats_flow_side="away", stats_pending_confirm=None)
        away = data["stats_away"]
        await message.answer(
            f"Стата хозяев записана. Дальше — <b>{html_escape(away)}</b>.",
            parse_mode="HTML",
        )
        await _send_stats_roster_prompt(message, state)
        return
    await _finalize_stats_session(message, state)


async def _send_stats_lines_ui(message: Message, state: FSMContext) -> None:
    """Построчная стата для текущей команды (после списка «кто сыграл»)."""
    data = await state.get_data()
    team = _stats_flow_team(data)
    home = data["stats_home"]
    away = data["stats_away"]
    hs = data["stats_hs"]
    aws = data["stats_aws"]
    side = data.get("stats_flow_side", "home")
    side_lab = "хозяева" if side == "home" else "гости"

    await state.update_data(
        stats_current_team=team,
        stats_mode_new=False,
        stats_pending_confirm=None,
    )
    if "stats_session_acc" not in data:
        await state.update_data(stats_session_acc={})
    await state.set_state(PostMatch.stats_wait_lines)

    hn = html_escape(home)
    an = html_escape(away)
    tn = html_escape(team)
    await message.answer(
        f"<b>Стата · {tn}</b> ({side_lab}) · матч {hn} <code>{hs}:{aws}</code> {an}\n\n"
        "Строки: <code>имя голы передачи</code> (например <code>Санчес 1 0</code>, "
        "<code>имя -1 0</code>). Несколько строк на игрока слаживаются.\n"
        "Матчи уже +1 у списка «сыгравших»; здесь только голы/пасы/жк/cs. "
        "Если игрок не из списка — спросим подтверждение.\n"
        "Дисциплина: <code>фамилия жк</code>, <code>… 8м</code>. "
        "Режим <code>2</code> — новый игрок с позицией в строке.\n"
        "Закончить стату этой команды — <code>/done</code> или кнопка ниже. /cancel — отмена.",
        reply_markup=_stats_lines_done_kb(),
        parse_mode="HTML",
    )


async def _prompt_score_for_scheduled_slot(
    message: Message,
    state: FSMContext,
    slot: dict,
) -> None:
    """Счёт для слота из mixed_schedule (следующий или выбранный из календаря)."""
    from config.leagues_config import manager_session_label
    from main import MIXED_SCHEDULE_FILE
    from utils.schedule_by_months import read_mixed_slot_label

    day = slot["day"]
    match_str = slot["match_str"]
    home = slot["home"]
    away = slot["away"]
    league_code = slot["league_code"]
    cl_ph = slot.get("cl_ph")

    slot_label = read_mixed_slot_label(MIXED_SCHEDULE_FILE)

    await state.set_state(MatchEnter.next_score)
    await state.update_data(
        day=day,
        match_str=match_str,
        home=home,
        away=away,
        league_code=league_code,
        cl_ph=cl_ph,
    )

    lg = _league_title(league_code)
    kb = InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="⏭ Отложить (skipped)", callback_data="play:skip"
                ),
            ]
        ]
    )

    mode = manager_session_label(home, away)
    mode_line = f"<b>{mode}</b>\n\n" if mode else ""

    disc_html = format_discipline_pre_match_notice_html(
        home,
        away,
        league_code=league_code,
        schedule_day=day,
        cl_phase=cl_ph,
    )
    disc_block = f"{disc_html}\n\n" if disc_html else ""

    first_leg_block = ""
    if league_code == "cl" and (cl_ph or "knockout") == "knockout":
        from utils.cl_knockout_schedule import format_first_leg_score_html

        first_leg_block = format_first_leg_score_html(home, away)

    await message.answer(
        f"{mode_line}"
        f"{slot_label} <b>{day}</b> · {lg}\n"
        f"<b>{home}</b> — <b>{away}</b>\n\n"
        f"{first_leg_block}"
        f"{disc_block}"
        f"Ответь сообщением со счётом через пробел, например: <code>2 1</code>\n"
        f"или нажми «Отложить».",
        reply_markup=kb,
        parse_mode="HTML",
    )


async def _begin_play_next(
    message: Message,
    state: FSMContext,
    *,
    session_kind: str | None = None,
) -> None:
    from main import find_next_match_in_schedule, load_or_generate_mixed_schedule

    sch = await asyncio.to_thread(load_or_generate_mixed_schedule)
    tup = await asyncio.to_thread(find_next_match_in_schedule, sch, session_kind)
    slot = _slot_from_schedule_tuple(tup)
    if slot is None:
        kind = {"sim": "симуляции", "game": "игры"}.get(session_kind or "", "")
        extra = f" ({kind})" if kind else ""
        await message.answer(
            f"Следующего матча{extra} нет (всё сыграно или только отложенные)."
        )
        return

    await _prompt_score_for_scheduled_slot(message, state, slot)


@match_router.message(Command("menu"))
async def cmd_menu_match(message: Message, state: FSMContext) -> None:
    await state.clear()
    await deliver_main_menu_refresh(message)


@match_router.message(Command("help"))
async def cmd_help_match(message: Message, state: FSMContext) -> None:
    await state.clear()
    await deliver_help_screen(message)


@match_router.message(MenuReplyFilter())
async def on_reply_menu_button(message: Message, state: FSMContext) -> None:
    await state.clear()
    await deliver_main_menu_refresh(message)


@match_router.message(Command("cancel"))
async def cmd_cancel_match_fsm(message: Message, state: FSMContext) -> None:
    cur = await state.get_state()
    if cur is None:
        await message.answer("Нечего отменять.")
        return
    if not str(cur).startswith(
        (
            "MatchEnter",
            "SkipPlay",
            "PostMatch",
            "AddOnlyStats",
            "ClPenalties",
            "AwardEnter",
            "RatingEnter",
            "SquadStatusEnter",
            "PlayerFieldEnter",
            "SquadRosterEnter",
            "MatchPerfRatingEnter",
            "LoanEnter",
            "InjuryEnter",
        ),
    ):
        return
    await state.clear()
    if str(cur).startswith("PostMatch"):
        await message.answer("Ввод статистики отменён.")
    elif str(cur).startswith("AddOnlyStats"):
        await message.answer("Ввод для статистики без матча отменён.")
    elif str(cur).startswith("ClPenalties"):
        await message.answer("Ввод пенальти отменён.")
    elif str(cur).startswith("AwardEnter"):
        await message.answer("Ввод награды отменён.")
    elif str(cur).startswith("RatingEnter"):
        await message.answer("Правка рейтинга отменена.")
    elif str(cur).startswith("PlayerFieldEnter"):
        await message.answer("Правка поля игрока отменена.")
    elif str(cur).startswith("SquadRosterEnter"):
        await message.answer("Добавление/удаление из состава отменено.")
    elif str(cur).startswith("SquadStatusEnter"):
        await message.answer("Правка заявки отменена.")
    elif str(cur).startswith("MatchPerfRatingEnter"):
        await message.answer("Ввод оценок отменён.")
    elif str(cur).startswith("LoanEnter"):
        await message.answer("Аренда отменена.")
    elif str(cur).startswith("InjuryEnter"):
        await message.answer("Ввод травм отменён.")
    else:
        await message.answer("Ввод счёта отменён.")


@match_router.callback_query(F.data == "play:next")
async def cb_play_next(callback: CallbackQuery, state: FSMContext) -> None:
    await callback.answer()
    await _begin_play_next(callback.message, state)


@match_router.callback_query(F.data == "play:next:sim")
async def cb_play_next_sim(callback: CallbackQuery, state: FSMContext) -> None:
    await callback.answer()
    await state.clear()
    if callback.message:
        await _begin_play_next(callback.message, state, session_kind="sim")


@match_router.callback_query(F.data == "play:next:game")
async def cb_play_next_game(callback: CallbackQuery, state: FSMContext) -> None:
    await callback.answer()
    await state.clear()
    if callback.message:
        await _begin_play_next(callback.message, state, session_kind="game")


@match_router.callback_query(F.data.startswith("play:post:noop"))
async def cb_play_post_noop(callback: CallbackQuery) -> None:
    tag = (callback.data or "").split(":")[-1]
    lab = "симуляции" if tag == "sim" else "игры" if tag == "game" else "этого типа"
    await callback.answer(f"Нет несыгранных матчей ({lab}).", show_alert=True)


@match_router.callback_query(F.data == "play:post:menu")
async def cb_play_post_menu(callback: CallbackQuery, state: FSMContext) -> None:
    await callback.answer()
    await state.clear()
    if callback.message:
        await deliver_main_menu_refresh(callback.message)


@match_router.message(Command("play_next"))
async def cmd_play_next(message: Message, state: FSMContext) -> None:
    await _begin_play_next(message, state)


@match_router.callback_query(F.data == "play:skip")
async def cb_play_skip(callback: CallbackQuery, state: FSMContext) -> None:
    data = await state.get_data()
    if await state.get_state() != MatchEnter.next_score or data.get("day") is None:
        await callback.answer("Сначала начни запись следующего матча.", show_alert=True)
        return
    await callback.answer()
    from skipped_matches import add_skipped_match

    home = data["home"]
    away = data["away"]
    lg = data["league_code"]
    day = data["day"]
    cl_ph = data.get("cl_ph")

    add_skipped_match(home, away, lg, day, cl_phase=cl_ph if lg == "cl" else None)
    await state.clear()
    await callback.message.answer(f"Отложено: {home} — {away} (месяц {day}).")


@match_router.message(MatchEnter.next_score, _TEXT_NOT_CMD)
async def on_next_score(message: Message, state: FSMContext) -> None:
    data = await state.get_data()
    raw = message.text.strip()
    m = _SCORE_RE.match(raw)
    if not m:
        await message.answer("Нужны два числа через пробел, например: 2 1")
        return

    hs, aws = int(m.group(1)), int(m.group(2))
    home = data["home"]
    away = data["away"]
    league_code = data["league_code"]
    day = data["day"]
    cl_ph = data.get("cl_ph")

    await _record_match_or_request_penalties(
        message,
        state,
        home=home,
        away=away,
        hs=hs,
        aws=aws,
        league_code=league_code,
        round_num=day,
        cl_ph=cl_ph,
    )


@match_router.callback_query(F.data == "play:manual")
async def cb_manual_start(callback: CallbackQuery, state: FSMContext) -> None:
    await callback.answer()
    await state.clear()
    await callback.message.answer(
        "Ручной ввод матча.\nВыбери лигу:",
        reply_markup=_manual_league_kb(),
    )


@match_router.message(Command("match"))
async def cmd_manual(message: Message, state: FSMContext) -> None:
    await state.clear()
    await message.answer(
        "Ручной ввод матча.\nВыбери лигу:",
        reply_markup=_manual_league_kb(),
    )


@match_router.callback_query(F.data.startswith("man:"))
async def cb_manual_league(callback: CallbackQuery, state: FSMContext) -> None:
    code = callback.data.split(":", 1)[1]
    await callback.answer()
    if code == "cl":
        await state.update_data(league_code=code)
        await state.set_state(MatchEnter.manual_cl_phase)
        await callback.message.answer(
            "Лига: <b>ЛЧ</b>\n"
            "Выбери фазу (для группы и нокаута разные записи в журнале):",
            reply_markup=_cl_phase_kb("mancl"),
            parse_mode="HTML",
        )
        return
    teams = _sorted_team_names_for_manual(code)
    if not teams:
        await callback.message.answer(
            "Не удалось загрузить список команд для этой лиги. Дальше — ввод текстом."
        )
        await state.update_data(league_code=code, cl_ph=None)
        await state.set_state(MatchEnter.manual_home)
        await callback.message.answer(
            f"Лига: <b>{_league_title(code)}</b>\n"
            "Введи название <b>хозяев</b> (как в базе):",
            parse_mode="HTML",
        )
        return
    await state.update_data(
        league_code=code, cl_ph=None, manual_all_teams=teams, manual_away_list=None
    )
    await state.set_state(MatchEnter.manual_home_pick)
    data = await state.get_data()
    await callback.message.answer(
        _manual_banner_home_pick(data),
        reply_markup=_manual_team_pick_kb(teams, 0, which="h"),
        parse_mode="HTML",
    )


@match_router.callback_query(F.data.startswith("mancl:"))
async def cb_manual_cl_phase(callback: CallbackQuery, state: FSMContext) -> None:
    if await state.get_state() != MatchEnter.manual_cl_phase:
        await callback.answer("Сначала начни ручной ввод и выбери ЛЧ.", show_alert=True)
        return
    phase = callback.data.split(":", 1)[1]
    if phase not in ("league", "knockout"):
        await callback.answer("Неверная фаза.", show_alert=True)
        return
    await callback.answer()
    teams = _sorted_team_names_for_manual("cl")
    if not teams:
        await state.update_data(cl_ph=phase)
        await state.set_state(MatchEnter.manual_home)
        await callback.message.answer(
            f"Лига: <b>ЛЧ</b> · фаза: <b>{_cl_phase_short_label(phase)}</b>\n"
            "Введи название <b>хозяев</b> (как в базе):",
            parse_mode="HTML",
        )
        return
    await state.update_data(
        league_code="cl",
        cl_ph=phase,
        manual_all_teams=teams,
        manual_away_list=None,
    )
    await state.set_state(MatchEnter.manual_home_pick)
    data = await state.get_data()
    await callback.message.answer(
        _manual_banner_home_pick(data),
        reply_markup=_manual_team_pick_kb(teams, 0, which="h"),
        parse_mode="HTML",
    )


@match_router.callback_query(F.data.startswith("mpt:"))
async def cb_manual_pick_page(callback: CallbackQuery, state: FSMContext) -> None:
    parts = callback.data.split(":")
    if len(parts) != 3:
        await callback.answer()
        return
    _, which, page_s = parts
    try:
        page = int(page_s)
    except ValueError:
        await callback.answer()
        return
    cur = await state.get_state()
    data = await state.get_data()
    if which == "h":
        if cur != MatchEnter.manual_home_pick.state:
            await callback.answer("Начни снова: /match", show_alert=True)
            return
        names = data.get("manual_all_teams") or []
        banner = _manual_banner_home_pick(data)
        wkey = "h"
    elif which == "a":
        if cur != MatchEnter.manual_away_pick.state:
            await callback.answer("Начни снова: /match", show_alert=True)
            return
        names = data.get("manual_away_list") or []
        home = (data.get("home_raw") or "").strip()
        banner = _manual_banner_away_pick(data, home)
        wkey = "a"
    else:
        await callback.answer()
        return
    await callback.message.edit_text(
        banner,
        reply_markup=_manual_team_pick_kb(names, page, which=wkey),
        parse_mode="HTML",
    )
    await callback.answer()


@match_router.callback_query(F.data.startswith("mtp:"))
async def cb_manual_team_pick(callback: CallbackQuery, state: FSMContext) -> None:
    parts = callback.data.split(":")
    if len(parts) != 3:
        await callback.answer()
        return
    _, kind, spec = parts
    data = await state.get_data()
    if kind == "x":
        await callback.answer()
        if spec == "h":
            await state.set_state(MatchEnter.manual_home)
            await callback.message.answer("Введи название хозяев (как в базе):")
            return
        if spec == "a":
            await state.set_state(MatchEnter.manual_away)
            await callback.message.answer("Введи название гостей:")
        return
    if kind not in ("h", "a"):
        await callback.answer()
        return
    try:
        idx = int(spec)
    except ValueError:
        await callback.answer()
        return
    if kind == "h":
        if await state.get_state() != MatchEnter.manual_home_pick.state:
            await callback.answer("Начни снова: /match", show_alert=True)
            return
        all_teams = data.get("manual_all_teams") or []
        if idx < 0 or idx >= len(all_teams):
            await callback.answer("Неверный выбор.", show_alert=True)
            return
        home = all_teams[idx]
        away_list = [t for t in all_teams if t != home]
        await state.update_data(home_raw=home, manual_away_list=away_list)
        await state.set_state(MatchEnter.manual_away_pick)
        data2 = await state.get_data()
        await callback.message.edit_text(
            _manual_banner_away_pick(data2, home),
            reply_markup=_manual_team_pick_kb(away_list, 0, which="a"),
            parse_mode="HTML",
        )
        await callback.answer()
        return
    if await state.get_state() != MatchEnter.manual_away_pick.state:
        await callback.answer("Начни снова: /match", show_alert=True)
        return
    away_list = data.get("manual_away_list") or []
    if idx < 0 or idx >= len(away_list):
        await callback.answer("Неверный выбор.", show_alert=True)
        return
    away = away_list[idx]
    home = (data.get("home_raw") or "").strip()
    await callback.answer()
    await _answer_manual_score_prompt(callback.message, state, home, away)


@match_router.message(MatchEnter.manual_home, _TEXT_NOT_CMD)
async def on_manual_home(message: Message, state: FSMContext) -> None:
    await state.update_data(home_raw=message.text.strip())
    await state.set_state(MatchEnter.manual_away)
    await message.answer("Введи название гостей:")


@match_router.message(MatchEnter.manual_away, _TEXT_NOT_CMD)
async def on_manual_away(message: Message, state: FSMContext) -> None:
    away = (message.text or "").strip()
    data = await state.get_data()
    home = (data.get("home_raw") or "").strip()
    await _answer_manual_score_prompt(message, state, home, away)


@match_router.message(MatchEnter.manual_score, _TEXT_NOT_CMD)
async def on_manual_score(message: Message, state: FSMContext) -> None:
    data = await state.get_data()
    raw = message.text.strip()
    m = _SCORE_RE.match(raw)
    if not m:
        await message.answer("Нужны два числа через пробел, например: 2 1")
        return

    hs, aws = int(m.group(1)), int(m.group(2))
    league_code = data["league_code"]
    home = data["home_raw"]
    away = data["away_raw"]
    cl_ph = data.get("cl_ph") if league_code == "cl" else None
    if league_code == "cl" and not cl_ph:
        await message.answer("Не выбрана фаза ЛЧ. Начни снова: /match")
        await state.clear()
        return

    await _record_match_or_request_penalties(
        message,
        state,
        home=home,
        away=away,
        hs=hs,
        aws=aws,
        league_code=league_code,
        round_num=None,
        cl_ph=cl_ph,
    )


_MAX_SKIP_BUTTONS = 50

_SCHED_PAGE_SIZE = 10


def _schedule_play_league_kb() -> InlineKeyboardMarkup:
    """Шаг «из календаря»: выбор чемпионата (scpf:<код>)."""
    rows: list[list[InlineKeyboardButton]] = [
        [
            InlineKeyboardButton(
                text="Все чемпионаты",
                callback_data="scpf:all",
            ),
        ],
    ]
    row: list[InlineKeyboardButton] = []
    for code, label in LEAGUE_LABELS:
        row.append(InlineKeyboardButton(text=label, callback_data=f"scpf:{code}"))
        if len(row) == 3:
            rows.append(row)
            row = []
    if row:
        rows.append(row)
    return InlineKeyboardMarkup(inline_keyboard=rows)


def _schedule_play_kind_kb(league_key: str) -> InlineKeyboardMarkup:
    """Шаг 2: все / только сим / только игра (scpk:<lg>:<all|sim|game>)."""
    lg = league_key
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(text="Все типы", callback_data=f"scpk:{lg}:all"),
                InlineKeyboardButton(text="Симуляция", callback_data=f"scpk:{lg}:sim"),
                InlineKeyboardButton(text="Игра", callback_data=f"scpk:{lg}:game"),
            ],
            [
                InlineKeyboardButton(
                    text="← К выбору чемпионата",
                    callback_data="scpf:back",
                ),
            ],
        ]
    )


def _schedule_play_filter_caption(league_key: str, session_kind: str) -> str:
    lg = (league_key or "all").strip().lower() or "all"
    sk = (session_kind or "all").strip().lower() or "all"
    lg_txt = "все чемпионаты" if lg == "all" else _league_title(lg)
    sk_txt = {"all": "все типы", "sim": "только симуляции", "game": "только игры"}.get(
        sk, sk
    )
    return f"Фильтр: <b>{html_escape(lg_txt)}</b> · <b>{html_escape(sk_txt)}</b>"


async def _send_schedule_play_league_step(message: Message) -> None:
    await message.answer(
        "📋 <b>Из календаря</b> — сначала выбери чемпионат, затем тип матча "
        "(сим / игра / всё). Потом откроется список несыгранных слотов.\n/cancel — отмена.",
        reply_markup=_schedule_play_league_kb(),
        parse_mode="HTML",
    )


def _schedule_pick_kb(
    ordered: list,
    *,
    page: int,
    league_filter: str = "all",
    session_kind: str = "all",
) -> InlineKeyboardMarkup:
    """Кнопки sched:pick:<idx>:<lg>:<sk>; навигация sched:page:<n>:<lg>:<sk>."""
    n = len(ordered)
    if not ordered:
        raise ValueError("schedule pick keyboard requires non-empty list")
    lf = (league_filter or "all").strip().lower() or "all"
    sk = (session_kind or "all").strip().lower() or "all"
    total_pages = max(1, (n + _SCHED_PAGE_SIZE - 1) // _SCHED_PAGE_SIZE)
    page = max(0, min(int(page), total_pages - 1))
    start = page * _SCHED_PAGE_SIZE
    chunk = ordered[start : start + _SCHED_PAGE_SIZE]

    rows: list[list[InlineKeyboardButton]] = []
    for j, row in enumerate(chunk):
        idx = start + j
        label = _calendar_slot_btn_label(row, index=idx + 1)
        rows.append(
            [
                InlineKeyboardButton(
                    text=label,
                    callback_data=f"sched:pick:{idx}:{lf}:{sk}",
                ),
            ]
        )

    nav: list[InlineKeyboardButton] = []
    if page > 0:
        nav.append(
            InlineKeyboardButton(
                text=f"« {page}",
                callback_data=f"sched:page:{page - 1}:{lf}:{sk}",
            )
        )
    nav.append(
        InlineKeyboardButton(
            text=f"{page + 1}/{total_pages}",
            callback_data="sched:noop",
        )
    )
    if page < total_pages - 1:
        nav.append(
            InlineKeyboardButton(
                text=f"{page + 2} »",
                callback_data=f"sched:page:{page + 1}:{lf}:{sk}",
            )
        )
    rows.append(nav)
    rows.append(
        [
            InlineKeyboardButton(
                text="← Фильтры (лига / тип)",
                callback_data="scpf:back",
            ),
        ]
    )
    return InlineKeyboardMarkup(inline_keyboard=rows)


def _schedule_pick_intro_html(
    page: int,
    total_pages: int,
    *,
    league_filter: str = "all",
    session_kind: str = "all",
) -> str:
    note = (
        f"\nСтраница <b>{page + 1}</b> из <b>{total_pages}</b> "
        f"(по {_SCHED_PAGE_SIZE} матчей; порядок как в mixed_schedule)."
    )
    cap = _schedule_play_filter_caption(league_filter, session_kind)
    return (
        f"{cap}\n\n"
        "Выбери матч из календаря — затем отправь счёт двумя числами через пробел "
        f"(например <code>2 1</code>). Можно отложить матч кнопкой «Отложить», как при записи "
        f"«следующего». Отложенные и уже сыгранные здесь не показываются.{note}\n"
        "/cancel — отмена."
    )


async def _ordered_remaining_filtered(league_filter: str, session_kind: str) -> list:
    from main import list_remaining_schedule_matches, load_or_generate_mixed_schedule

    lf = (league_filter or "all").strip().lower() or "all"
    sk = (session_kind or "all").strip().lower() or "all"
    sch = await asyncio.to_thread(load_or_generate_mixed_schedule)
    return await asyncio.to_thread(
        list_remaining_schedule_matches,
        sch,
        league_filter=None if lf == "all" else lf,
        session_kind=None if sk == "all" else sk,
    )


@match_router.callback_query(F.data == "play:schedule")
async def cb_play_schedule(callback: CallbackQuery, state: FSMContext) -> None:
    await callback.answer()
    await state.clear()
    if callback.message:
        await _send_schedule_play_league_step(callback.message)


@match_router.callback_query(F.data == "sched:noop")
async def cb_sched_noop(callback: CallbackQuery) -> None:
    await callback.answer()


@match_router.callback_query(F.data.startswith("scpf:"))
async def cb_sched_play_filter_league(callback: CallbackQuery, state: FSMContext) -> None:
    await state.clear()
    raw = (callback.data or "").split(":", 2)
    if len(raw) < 2:
        await callback.answer()
        return
    tag = raw[1].strip().lower()
    if tag == "back":
        await callback.answer()
        if callback.message:
            try:
                await callback.message.edit_text(
                    "📋 <b>Из календаря</b> — выбери чемпионат, затем тип матча.\n/cancel — отмена.",
                    reply_markup=_schedule_play_league_kb(),
                    parse_mode="HTML",
                )
            except Exception:
                await _send_schedule_play_league_step(callback.message)
        return
    await callback.answer()
    if callback.message:
        try:
            await callback.message.edit_text(
                f"Чемпионат: <b>{html_escape(_league_title(tag) if tag != 'all' else 'все')}</b>.\n"
                "Теперь выбери тип слотов:",
                reply_markup=_schedule_play_kind_kb(tag),
                parse_mode="HTML",
            )
        except Exception:
            await callback.message.answer(
                f"Чемпионат: <b>{html_escape(_league_title(tag) if tag != 'all' else 'все')}</b>.\n"
                "Теперь выбери тип слотов:",
                reply_markup=_schedule_play_kind_kb(tag),
                parse_mode="HTML",
            )


@match_router.callback_query(F.data.startswith("scpk:"))
async def cb_sched_play_filter_kind(callback: CallbackQuery, state: FSMContext) -> None:
    await state.clear()
    parts = (callback.data or "").split(":")
    if len(parts) < 3:
        await callback.answer("Ошибка кнопки.", show_alert=True)
        return
    league_key = parts[1].strip().lower() or "all"
    sk = parts[2].strip().lower() or "all"
    if sk not in ("all", "sim", "game"):
        await callback.answer("Неизвестный тип.", show_alert=True)
        return
    await callback.answer()
    if not callback.message:
        return
    ordered = await _ordered_remaining_filtered(league_key, sk)
    if not ordered:
        try:
            await callback.message.edit_text(
                "По выбранному фильтру нет доступных матчей. Попробуй другой чемпионат или тип.",
                reply_markup=_schedule_play_kind_kb(league_key),
                parse_mode="HTML",
            )
        except Exception:
            await callback.message.answer(
                "По выбранному фильтру нет доступных матчей. Попробуй другой чемпионат или тип.",
                reply_markup=_schedule_play_kind_kb(league_key),
                parse_mode="HTML",
            )
        return

    total_pages = max(1, (len(ordered) + _SCHED_PAGE_SIZE - 1) // _SCHED_PAGE_SIZE)
    page = 0
    kb = _schedule_pick_kb(
        ordered,
        page=page,
        league_filter=league_key,
        session_kind=sk,
    )
    text = _schedule_pick_intro_html(
        page,
        total_pages,
        league_filter=league_key,
        session_kind=sk,
    )
    try:
        await callback.message.edit_text(
            text,
            reply_markup=kb,
            parse_mode="HTML",
        )
    except Exception:
        await callback.message.answer(
            text,
            reply_markup=kb,
            parse_mode="HTML",
        )


@match_router.callback_query(F.data.startswith("sched:page:"))
async def cb_sched_page(callback: CallbackQuery, state: FSMContext) -> None:
    parts = (callback.data or "").split(":")
    lf, sk = "all", "all"
    try:
        page = int(parts[2])
    except (IndexError, ValueError):
        await callback.answer()
        return
    if len(parts) >= 5:
        lf = (parts[3] or "all").strip().lower() or "all"
        sk = (parts[4] or "all").strip().lower() or "all"
    await callback.answer()
    ordered = await _ordered_remaining_filtered(lf, sk)
    if not ordered:
        if callback.message:
            try:
                await callback.message.edit_text(
                    "Нет доступных матчей по этому фильтру.",
                    parse_mode="HTML",
                )
            except Exception:
                await callback.message.answer(
                    "Нет доступных матчей по этому фильтру.",
                    parse_mode="HTML",
                )
        return
    total_pages = max(1, (len(ordered) + _SCHED_PAGE_SIZE - 1) // _SCHED_PAGE_SIZE)
    page = max(0, min(page, total_pages - 1))
    kb = _schedule_pick_kb(
        ordered,
        page=page,
        league_filter=lf,
        session_kind=sk,
    )
    text = _schedule_pick_intro_html(
        page,
        total_pages,
        league_filter=lf,
        session_kind=sk,
    )
    if callback.message:
        try:
            await callback.message.edit_text(
                text,
                reply_markup=kb,
                parse_mode="HTML",
            )
        except Exception:
            await callback.message.answer(
                text,
                reply_markup=kb,
                parse_mode="HTML",
            )


@match_router.callback_query(F.data.startswith("sched:pick:"))
async def cb_sched_pick(callback: CallbackQuery, state: FSMContext) -> None:
    parts = (callback.data or "").split(":")
    lf, sk = "all", "all"
    try:
        idx = int(parts[2])
    except (IndexError, ValueError):
        await callback.answer("Ошибка кнопки.", show_alert=True)
        return
    if len(parts) >= 5:
        lf = (parts[3] or "all").strip().lower() or "all"
        sk = (parts[4] or "all").strip().lower() or "all"

    ordered = await _ordered_remaining_filtered(lf, sk)
    if idx < 0 or idx >= len(ordered):
        await callback.answer("Матча нет в списке. Обнови список.", show_alert=True)
        return
    slot = ordered[idx]
    await callback.answer()
    await state.clear()
    if callback.message:
        await _prompt_score_for_scheduled_slot(callback.message, state, slot)


@match_router.message(Command("play_schedule"))
async def cmd_play_schedule(message: Message, state: FSMContext) -> None:
    await state.clear()
    await _send_schedule_play_league_step(message)


def _skipped_pick_kb(matches_slice: list) -> InlineKeyboardMarkup:
    """Кнопки skipm:<индекс в полном упорядоченном списке>."""
    rows: list[list[InlineKeyboardButton]] = []
    for j, m in enumerate(matches_slice):
        label = _calendar_slot_btn_label(_skipped_row_to_slot(m), index=j + 1)
        rows.append([InlineKeyboardButton(text=label, callback_data=f"skipm:{j}")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


async def _send_skipped_pick_list(message: Message) -> None:
    from skipped_matches import list_skipped_matches_ordered

    ordered = list_skipped_matches_ordered()
    if not ordered:
        await message.answer(
            "Отложенных матчей нет (skipped_matches.json пуст).\n"
            "Чтобы отложить матч — при «Записать следующий» нажми «Отложить (skipped)»."
        )
        return

    note = ""
    if len(ordered) > _MAX_SKIP_BUTTONS:
        note = (
            f"\n⚠ Показаны первые {_MAX_SKIP_BUTTONS} из {len(ordered)}. "
            "Остальные можно записать через консольный main или уменьшить список вручную."
        )

    slice_len = min(len(ordered), _MAX_SKIP_BUTTONS)
    kb = _skipped_pick_kb(ordered[:slice_len])

    await message.answer(
        "Выбери отложенный матч кнопкой ниже — затем отправь счёт двумя числами через пробел "
        f'(например <code>2 1</code>).{note}\n/cancel — отмена.',
        reply_markup=kb,
        parse_mode="HTML",
    )


@match_router.callback_query(F.data == "skip:list")
async def cb_skip_list(callback: CallbackQuery, state: FSMContext) -> None:
    await callback.answer()
    await state.clear()
    await _send_skipped_pick_list(callback.message)


@match_router.message(Command("play_skipped"))
async def cmd_play_skipped(message: Message, state: FSMContext) -> None:
    await state.clear()
    await _send_skipped_pick_list(message)


@match_router.callback_query(F.data.startswith("skipm:"))
async def cb_skip_pick(callback: CallbackQuery, state: FSMContext) -> None:
    from skipped_matches import list_skipped_matches_ordered

    try:
        idx = int(callback.data.split(":", 1)[1])
    except (IndexError, ValueError):
        await callback.answer("Ошибка кнопки.", show_alert=True)
        return
    ordered = list_skipped_matches_ordered()
    if idx < 0 or idx >= len(ordered):
        await callback.answer("Матча нет в списке. Открой меню снова.", show_alert=True)
        return
    row = ordered[idx]
    await callback.answer()
    from config.leagues_config import manager_session_label

    lg = _league_title(row["tournament"])
    month = row["round"]
    extra = ""
    if row["tournament"] == "cl":
        extra = f"\nФаза ЛЧ: <code>{row.get('cl_phase') or 'knockout'}</code>"
    mode = manager_session_label(row["home"], row["away"])
    mode_line = f"<b>{mode}</b>\n\n" if mode else ""

    slot = _skipped_row_to_slot(row)
    fixture_rnd = slot.get("fixture_round")
    if fixture_rnd is None:
        from utils.player_discipline import find_fixture_round

        fixture_rnd = find_fixture_round(
            row["home"],
            row["away"],
            row["tournament"],
            cl_phase=row.get("cl_phase") if row["tournament"] == "cl" else None,
        )
    tour_line = f", тур <b>{fixture_rnd}</b>" if fixture_rnd is not None else ""

    disc_html = format_discipline_pre_match_notice_html(
        row["home"],
        row["away"],
        league_code=row["tournament"],
        schedule_day=row.get("round"),
        cl_phase=row.get("cl_phase") if row["tournament"] == "cl" else None,
        fixture_round=fixture_rnd,
    )
    disc_block = f"{disc_html}\n\n" if disc_html else ""

    await state.set_state(SkipPlay.awaiting_score)
    await state.update_data(skip_play_row=dict(row))

    await callback.message.answer(
        f"{mode_line}"
        f"Отложенный матч · <b>{lg}</b>, месяц <b>{month}</b>{tour_line}{extra}\n"
        f"<b>{row['home']}</b> — <b>{row['away']}</b>\n\n"
        f"{disc_block}"
        f"Отправь счёт через пробел (хозяева гости), например: <code>2 1</code>\n"
        f"/cancel — отмена.",
        parse_mode="HTML",
    )


@match_router.message(SkipPlay.awaiting_score, _TEXT_NOT_CMD)
async def on_skip_play_score(message: Message, state: FSMContext) -> None:
    data = await state.get_data()
    row = data.get("skip_play_row")
    if not row:
        await state.clear()
        await message.answer("Сессия сброшена. Начни снова: /play_skipped")
        return

    raw = message.text.strip()
    m = _SCORE_RE.match(raw)
    if not m:
        await message.answer("Нужны два числа через пробел, например: 2 1")
        return

    hs, aws = int(m.group(1)), int(m.group(2))
    lg_code = row["tournament"]
    cl_ph = row.get("cl_phase") if lg_code == "cl" else None

    await _record_match_or_request_penalties(
        message,
        state,
        home=row["home"],
        away=row["away"],
        hs=hs,
        aws=aws,
        league_code=lg_code,
        round_num=row["round"],
        cl_ph=cl_ph,
    )


@match_router.message(ClPenalties.waiting, _TEXT_NOT_CMD)
async def on_cl_penalties_series(message: Message, state: FSMContext) -> None:
    raw = message.text.strip()
    m = _SCORE_RE.match(raw)
    if not m:
        await message.answer("Два целых числа через пробел, например: 5 4")
        return
    ph, pa = int(m.group(1)), int(m.group(2))
    if ph == pa:
        await message.answer("В серии пенальти должен быть победитель — числа не совпадают.")
        return

    data = await state.get_data()
    home = data.get("pen_home")
    if not home:
        await state.clear()
        await message.answer("Сессия сброшена. Запиши матч заново.")
        return

    pens = {data["pen_home"]: ph, data["pen_away"]: pa}
    ok, log = await asyncio.to_thread(
        run_process_match_bot,
        data["pen_home"],
        data["pen_away"],
        data["pen_hs"],
        data["pen_aws"],
        data["pen_league"],
        round_num=data["pen_round"],
        cl_phase=data["pen_cl_ph"],
        penalties_override=pens,
    )
    await _finish_match_and_offer_stats(
        message,
        state,
        ok=ok,
        log=log,
        home=data["pen_home"],
        away=data["pen_away"],
        hs=data["pen_hs"],
        aws=data["pen_aws"],
        league_code=data["pen_league"],
        schedule_day=data.get("pen_round"),
    )


@match_router.callback_query(F.data == "postmatch:stats_n")
async def cb_postmatch_stats_no(callback: CallbackQuery, state: FSMContext) -> None:
    if await state.get_state() != PostMatch.offer_stats:
        await callback.answer()
        return
    data = await state.get_data()
    home = data.get("stats_home")
    away = data.get("stats_away")
    tourn = data.get("stats_tournament", "league")
    lc = data.get("stats_league_code")
    cl_ph = None
    if home and away and (tourn == "cl" or lc == "cl"):
        from match_results import find_journal_match_record

        rec = await asyncio.to_thread(
            find_journal_match_record,
            home,
            away,
            lc or "cl",
            cl_phase=None,
        )
        if rec:
            cl_ph = rec.get("cl_phase")
    if home and away:
        from matches_stats_tracking import mark_stats_pending

        await asyncio.to_thread(
            mark_stats_pending,
            home,
            away,
            tourn,
            cl_phase=cl_ph,
            day=data.get("stats_schedule_day"),
        )
    await callback.answer()
    await state.clear()
    await callback.message.answer(
        "Без статистики. Матч в очереди «Стата без матча» — можно внести позже из меню."
    )
    await _send_post_match_continue_prompt(callback.message)


@match_router.callback_query(F.data == "postmatch:stats_y")
async def cb_postmatch_stats_yes(callback: CallbackQuery, state: FSMContext) -> None:
    if await state.get_state() != PostMatch.offer_stats:
        await callback.answer("Сначала запиши матч со счётом.", show_alert=True)
        return
    data = await state.get_data()
    home = data.get("stats_home")
    away = data.get("stats_away")
    hs = data.get("stats_hs")
    aws = data.get("stats_aws")
    if home is None or away is None or hs is None or aws is None:
        await callback.answer("Сессия устарела.", show_alert=True)
        await state.clear()
        return

    await callback.answer()
    await _start_stats_team_flow(callback.message, state)


@match_router.message(StateFilter(PostMatch.stats_roster_list), Command("done"))
async def cmd_stats_roster_done(message: Message, state: FSMContext) -> None:
    await _finish_stats_roster_for_team(message, state)


@match_router.message(StateFilter(PostMatch.stats_roster_list), _TEXT_NOT_CMD)
async def on_stats_roster_lines(message: Message, state: FSMContext) -> None:
    from utils.match_stats_bot import parse_roster_name_lines

    lines = parse_roster_name_lines(message.text or "")
    if not lines:
        await message.answer("Пустое сообщение. Имя игрока — с новой строки.")
        return
    data = await state.get_data()
    buf = list(data.get("stats_roster_buffer") or [])
    buf.extend(lines)
    await state.update_data(stats_roster_buffer=buf)
    team = html_escape(_stats_flow_team(data))
    await message.answer(
        f"+{len(lines)} в списке для <b>{team}</b> (всего <b>{len(buf)}</b>). "
        "Ещё игроков или <code>/done</code>.",
        parse_mode="HTML",
    )


@match_router.callback_query(StateFilter(PostMatch.stats_wait_lines), F.data == "stats:done")
async def cb_stats_done(callback: CallbackQuery, state: FSMContext) -> None:
    await callback.answer()
    if callback.message:
        await _advance_after_team_stats_lines(callback.message, state)


@match_router.message(StateFilter(PostMatch.stats_wait_lines), Command("done"))
async def cmd_stats_done_cmd(message: Message, state: FSMContext) -> None:
    await _advance_after_team_stats_lines(message, state)


def _stats_confirm_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="Да, играл",
                    callback_data="stats:cfm:y",
                ),
                InlineKeyboardButton(
                    text="Нет",
                    callback_data="stats:cfm:n",
                ),
            ]
        ]
    )


async def _apply_stats_line_from_message(
    message: Message,
    state: FSMContext,
    line: str,
    *,
    confirm_unlisted_apply: bool = False,
) -> None:
    from player_stats import apply_stats_bot_line

    data = await state.get_data()
    home = data.get("stats_home")
    away = data.get("stats_away")
    hs = data.get("stats_hs")
    aws = data.get("stats_aws")
    if home is None or away is None or hs is None or aws is None:
        await message.answer("Сессия устарела. Начни снова с записи счёта.")
        await state.clear()
        return
    cur_team = data.get("stats_current_team") or home
    mode_new = bool(data.get("stats_mode_new"))
    session_seen = set(data.get("stats_session_match_keys") or [])
    session_acc: dict[str, dict] = dict(data.get("stats_session_acc") or {})
    played_keys_raw = data.get("stats_played_keys")
    played_keys = (
        set(played_keys_raw) if played_keys_raw is not None else None
    )
    reply, new_team, new_mode, confirm = await asyncio.to_thread(
        apply_stats_bot_line,
        line,
        home_team=str(home),
        away_team=str(away),
        home_score=int(hs),
        away_score=int(aws),
        tournament=str(data.get("stats_tournament", "league")),
        current_team=str(cur_team),
        mode_new=mode_new,
        league_code=data.get("stats_league_code"),
        schedule_day=data.get("stats_schedule_day"),
        increment_matches=True,
        session_match_players=session_seen,
        session_acc=session_acc,
        stats_played_keys=played_keys,
        confirm_unlisted_apply=confirm_unlisted_apply,
    )
    await state.update_data(
        stats_current_team=new_team,
        stats_mode_new=new_mode,
        stats_session_match_keys=sorted(session_seen),
        stats_session_acc=session_acc,
        stats_played_keys=sorted(played_keys) if played_keys is not None else None,
    )
    if confirm:
        await state.update_data(stats_pending_confirm=confirm)
        nm = html_escape(str(confirm.get("name") or ""))
        await message.answer(
            f"Точно ли <b>{nm}</b> играл этот матч?",
            reply_markup=_stats_confirm_kb(),
            parse_mode="HTML",
        )
        return
    if reply:
        await message.answer(html_escape(reply), parse_mode="HTML")


@match_router.message(StateFilter(PostMatch.stats_wait_lines), _TEXT_NOT_CMD)
async def on_postmatch_stats_line(message: Message, state: FSMContext) -> None:
    data = await state.get_data()
    if data.get("stats_pending_confirm"):
        await message.answer(
            "Сначала ответь «Да, играл» или «Нет» на вопрос выше."
        )
        return
    await _apply_stats_line_from_message(message, state, message.text or "")


@match_router.callback_query(
    StateFilter(PostMatch.stats_wait_lines), F.data.startswith("stats:cfm:")
)
async def cb_stats_confirm_played(callback: CallbackQuery, state: FSMContext) -> None:
    tag = (callback.data or "").rsplit(":", 1)[-1]
    data = await state.get_data()
    confirm = data.get("stats_pending_confirm")
    if not confirm:
        await callback.answer("Нет ожидающего подтверждения.", show_alert=True)
        return
    await callback.answer()
    await state.update_data(stats_pending_confirm=None)
    if tag == "n":
        nm = html_escape(str(confirm.get("name") or "игрок"))
        if callback.message:
            await callback.message.answer(
                f"Строка не записана — <b>{nm}</b> не отмечен как сыгравший.",
                parse_mode="HTML",
            )
        return
    if tag == "y" and callback.message:
        await _apply_stats_line_from_message(
            callback.message,
            state,
            str(confirm.get("line") or ""),
            confirm_unlisted_apply=True,
        )


@match_router.callback_query(F.data == "ason:noop")
async def cb_ason_noop(callback: CallbackQuery) -> None:
    await callback.answer()


@match_router.callback_query(F.data.startswith("asonf:"))
async def cb_ason_filter_league(callback: CallbackQuery, state: FSMContext) -> None:
    raw = (callback.data or "").split(":", 2)
    if len(raw) < 2:
        await callback.answer()
        return
    tag = raw[1].strip().lower()
    if tag == "back":
        await callback.answer()
        await state.set_state(AddOnlyStats.browsing)
        if callback.message:
            try:
                await callback.message.edit_text(
                    "📊 <b>Стата без матча</b> — чемпионат → месяц → тип матча.\n/cancel — отмена.",
                    reply_markup=build_ason_league_kb(),
                    parse_mode="HTML",
                )
            except Exception:
                await _send_ason_stats_intro(callback.message, state)
        return
    await callback.answer()
    await state.set_state(AddOnlyStats.browsing)
    await state.update_data(
        ason_league=tag,
        ason_cl_ph=None,
        ason_month=None,
        ason_month_chosen=False,
    )
    if tag == "cl":
        await state.set_state(AddOnlyStats.cl_phase)
        if callback.message:
            await callback.message.answer(
                "Лига: <b>ЛЧ</b>\n"
                "Выбери фазу (группа / нокаут — как в журнале):",
                reply_markup=_cl_phase_kb("asoncl"),
                parse_mode="HTML",
            )
        return
    if callback.message:
        await _send_ason_month_step(callback.message, state, tag, edit=True)


@match_router.callback_query(F.data.startswith("asoncl:"))
async def cb_ason_cl_phase(callback: CallbackQuery, state: FSMContext) -> None:
    if await state.get_state() != AddOnlyStats.cl_phase:
        await callback.answer("Сначала выбери «Стата без матча» и ЛЧ.", show_alert=True)
        return
    phase = callback.data.split(":", 1)[1]
    if phase not in ("league", "knockout"):
        await callback.answer("Неверная фаза.", show_alert=True)
        return
    await callback.answer()
    await state.update_data(
        ason_league="cl",
        ason_cl_ph=phase,
        ason_month=None,
        ason_month_chosen=False,
    )
    await state.set_state(AddOnlyStats.browsing)
    if callback.message:
        await _send_ason_month_step(callback.message, state, "cl", edit=False)


@match_router.callback_query(F.data.startswith("asonmo:"))
async def cb_ason_month_reopen(callback: CallbackQuery, state: FSMContext) -> None:
    parts = (callback.data or "").split(":")
    if len(parts) < 2:
        await callback.answer()
        return
    league_key = parts[1].strip().lower() or "all"
    await callback.answer()
    if callback.message:
        await _send_ason_month_step(callback.message, state, league_key, edit=True)


@match_router.callback_query(F.data.startswith("asonm:"))
async def cb_ason_month_pick(callback: CallbackQuery, state: FSMContext) -> None:
    parts = (callback.data or "").split(":")
    if len(parts) < 3:
        await callback.answer("Ошибка кнопки.", show_alert=True)
        return
    league_key = parts[1].strip().lower() or "all"
    mo_raw = parts[2].strip().lower()
    if mo_raw == "all":
        month_val = None
    else:
        try:
            month_val = int(mo_raw)
        except ValueError:
            await callback.answer("Неверный месяц.", show_alert=True)
            return
    await callback.answer()
    await state.update_data(
        ason_month=month_val,
        ason_month_chosen=True,
        ason_pick_lf=league_key,
    )
    if not callback.message:
        return
    mo_label = html_escape(_ason_month_filter_label(month_val))
    lg_title = html_escape(
        _league_title(league_key) if league_key != "all" else "все чемпионаты"
    )
    try:
        await callback.message.edit_text(
            f"Чемпионат: <b>{lg_title}</b> · <b>{mo_label}</b>\n"
            "Теперь выбери тип слотов:",
            reply_markup=_ason_play_kind_kb(league_key),
            parse_mode="HTML",
        )
    except Exception:
        await callback.message.answer(
            f"Чемпионат: <b>{lg_title}</b> · <b>{mo_label}</b>\n"
            "Теперь выбери тип слотов:",
            reply_markup=_ason_play_kind_kb(league_key),
            parse_mode="HTML",
        )


@match_router.callback_query(F.data.startswith("asonpk:"))
async def cb_ason_filter_kind(callback: CallbackQuery, state: FSMContext) -> None:
    parts = (callback.data or "").split(":")
    if len(parts) < 3:
        await callback.answer("Ошибка кнопки.", show_alert=True)
        return
    league_key = parts[1].strip().lower() or "all"
    sk = parts[2].strip().lower() or "all"
    if sk not in ("all", "sim", "game"):
        await callback.answer("Неизвестный тип.", show_alert=True)
        return
    if not callback.message:
        await callback.answer()
        return
    data = await state.get_data()
    ason_lg = (data.get("ason_league") or league_key).strip().lower()
    if ason_lg == "cl" and league_key == "cl":
        cl_ph = data.get("ason_cl_ph")
        if not cl_ph:
            await callback.answer("Сначала выбери фазу ЛЧ.", show_alert=True)
            return
    if not data.get("ason_month_chosen"):
        await callback.answer("Сначала выбери месяц.", show_alert=True)
        return
    await callback.answer()
    if callback.message:
        await _show_ason_pick_list(
            callback.message,
            state,
            league_key=league_key,
            session_kind=sk,
            page=0,
            edit=True,
        )


@match_router.callback_query(F.data.startswith("asonpage:"))
async def cb_ason_page(callback: CallbackQuery, state: FSMContext) -> None:
    parts = (callback.data or "").split(":")
    lf, sk = "all", "all"
    try:
        page = int(parts[1])
    except (IndexError, ValueError):
        await callback.answer()
        return
    if len(parts) >= 4:
        lf = (parts[2] or "all").strip().lower() or "all"
        sk = (parts[3] or "all").strip().lower() or "all"
    await callback.answer()
    if callback.message:
        await _show_ason_pick_list(
            callback.message,
            state,
            league_key=lf,
            session_kind=sk,
            page=page,
            edit=True,
        )


@match_router.callback_query(F.data.startswith("asonpick:"))
async def cb_ason_pick(callback: CallbackQuery, state: FSMContext) -> None:
    parts = (callback.data or "").split(":")
    lf, sk = "all", "all"
    try:
        idx = int(parts[1])
    except (IndexError, ValueError):
        await callback.answer("Ошибка кнопки.", show_alert=True)
        return
    if len(parts) >= 4:
        lf = (parts[2] or "all").strip().lower() or "all"
        sk = (parts[3] or "all").strip().lower() or "all"
    data = await state.get_data()
    month = data.get("ason_month")
    if month is not None:
        month = int(month)
    ordered = await _ordered_played_filtered(lf, sk, month_filter=month)
    ordered = _ason_filter_played_list(ordered, data)
    if idx < 0 or idx >= len(ordered):
        await callback.answer("Матча нет в списке. Обнови список.", show_alert=True)
        return
    slot = ordered[idx]
    await callback.answer()
    if callback.message:
        await _begin_stats_for_played_slot(callback.message, state, slot)


@match_router.message(Command("stats_match"))
async def cmd_stats_match(message: Message, state: FSMContext) -> None:
    await _send_ason_stats_intro(message, state)


