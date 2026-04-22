"""Ввод счёта матча в боте (аналог «n» и «m» в консоли)."""
from __future__ import annotations

import asyncio
import logging
import re
from html import escape as html_escape
from typing import Final

from aiogram import F, Router
from aiogram.filters import Command
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
from bot.states import AddOnlyStats, ClPenalties, MatchEnter, PostMatch, SkipPlay

logger = logging.getLogger(__name__)

match_router = Router()

_SCORE_RE: Final = re.compile(r"^\s*(\d+)\s+(\d+)\s*$")

# Не перехватывать /help и прочие команды как счёт или имя команды
_TEXT_NOT_CMD: Final = F.text & ~F.text.startswith("/")


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
) -> None:
    """После записи матча — опционально предложить статистику (если INPUT_PLAYER_STATS в main)."""
    from main import INPUT_PLAYER_STATS

    log_html = html_escape(log)
    if not ok:
        await state.clear()
        txt = log if log else "Не удалось записать матч."
        await message.answer(f"✗ {txt}")
        return

    await message.answer(f"✓ Записано.\n<pre>{log_html}</pre>", parse_mode="HTML")

    if not INPUT_PLAYER_STATS:
        await state.clear()
        return

    await state.clear()
    await state.set_state(PostMatch.offer_stats)
    await state.update_data(
        stats_home=home.strip().title(),
        stats_away=away.strip().title(),
        stats_hs=hs,
        stats_aws=aws,
        stats_tournament="cl" if league_code == "cl" else "league",
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
        await message.answer(
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


def build_ason_league_kb() -> InlineKeyboardMarkup:
    """Выбор лиги для режима «статистика без записи счёта в матч-дне» (как «a»)."""
    rows: list[list[InlineKeyboardButton]] = []
    row: list[InlineKeyboardButton] = []
    for code, label in LEAGUE_LABELS:
        row.append(InlineKeyboardButton(text=label, callback_data=f"ason:{code}"))
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
    await state.clear()

    extra = ""
    if pj:
        from match_results import add_match_result, is_match_played as _played

        h = pj["home"]
        a = pj["away"]
        lc = pj["lc"]
        hs = pj["hs"]
        aws = pj["aws"]
        cl_ph = "knockout" if lc == "cl" else None
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


async def _send_stats_lines_ui(message: Message, state: FSMContext) -> None:
    """Шпаргалка + инструкции для PostMatch.stats_lines (данные уже в state)."""
    from player_stats import format_roster_cheat_sheet_text

    data = await state.get_data()
    home = data["stats_home"]
    away = data["stats_away"]
    hs = data["stats_hs"]
    aws = data["stats_aws"]
    tournament = data.get("stats_tournament", "league")

    sheet = await asyncio.to_thread(
        format_roster_cheat_sheet_text, home, away, tournament
    )
    body = sheet or "(игроков в БД для этих команд не найдено)"
    for chunk in split_text_chunks(body, 3500):
        await message.answer(
            f"<pre>{html_escape(chunk)}</pre>",
            parse_mode="HTML",
        )

    dry_lines: list[str] = []
    if aws == 0:
        dry_lines.append(f"💪 {home} — сухой матч для гостей (0 голов).")
    if hs == 0:
        dry_lines.append(f"💪 {away} — сухой матч для хозяев (0 голов).")
    dry_txt = "\n".join(dry_lines)

    await state.set_state(PostMatch.stats_lines)
    await state.update_data(stats_current_team=home, stats_mode_new=False)

    done_kb = InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="✓ Готово",
                    callback_data="stats:done",
                ),
            ]
        ]
    )
    instr = (
        "Вводи по одной строке (как в консоли): например <code>Салах 2 1</code>, "
        "<code>ван дейк цз 0 0 cs</code>.\n"
        "<code>1</code> — только из БД, <code>2</code> — новый игрок; "
        "<code>h</code>/<code>х</code> — хозяева, <code>a</code>/<code>г</code> — гости.\n"
        "/done или «Готово» — закончить; /cancel — отмена."
    )
    if dry_txt:
        instr = html_escape(dry_txt) + "\n\n" + instr
    await message.answer(
        instr,
        reply_markup=done_kb,
        parse_mode="HTML",
    )


async def _begin_play_next(message: Message, state: FSMContext) -> None:
    from main import find_next_match_in_schedule, load_or_generate_mixed_schedule
    from match_results import cl_phase_from_mixed_schedule_line

    sch = load_or_generate_mixed_schedule()
    tup = find_next_match_in_schedule(sch)
    if tup[0] is None:
        await message.answer(
            "Следующего матча нет (всё сыграно или остались только отложенные)."
        )
        return

    day, match_str, home, away, league_code = tup
    cl_ph = (
        cl_phase_from_mixed_schedule_line(match_str) if league_code == "cl" else None
    )

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

    await message.answer(
        f"Матч-день <b>{day}</b> · {lg}\n"
        f"<b>{home}</b> — <b>{away}</b>\n\n"
        f"Ответь сообщением со счётом через пробел, например: <code>2 1</code>\n"
        f"или нажми «Отложить».",
        reply_markup=kb,
        parse_mode="HTML",
    )


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
            "TransferEnter",
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
    elif str(cur).startswith("TransferEnter"):
        await message.answer("Трансфер отменён.")
    else:
        await message.answer("Ввод счёта отменён.")


@match_router.callback_query(F.data == "play:next")
async def cb_play_next(callback: CallbackQuery, state: FSMContext) -> None:
    await callback.answer()
    await _begin_play_next(callback.message, state)


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
    await callback.message.answer(f"Отложено: {home} — {away} (тур дня {day}).")


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
    await state.update_data(league_code=code)
    await state.set_state(MatchEnter.manual_home)
    await callback.message.answer(
        f"Лига: <b>{_league_title(code)}</b>\n"
        f"Введи название <b>хозяев</b> (как в базе):",
        parse_mode="HTML",
    )


@match_router.message(MatchEnter.manual_home, _TEXT_NOT_CMD)
async def on_manual_home(message: Message, state: FSMContext) -> None:
    await state.update_data(home_raw=message.text.strip())
    await state.set_state(MatchEnter.manual_away)
    await message.answer("Введи название гостей:")


@match_router.message(MatchEnter.manual_away, _TEXT_NOT_CMD)
async def on_manual_away(message: Message, state: FSMContext) -> None:
    await state.update_data(away_raw=message.text.strip())
    await state.set_state(MatchEnter.manual_score)
    await message.answer(
        "Введи счёт два числа через пробел (хозяева гости), например: 2 1"
    )


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
    cl_ph = "knockout" if league_code == "cl" else None

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


def _skipped_pick_kb(matches_slice: list) -> InlineKeyboardMarkup:
    """Кнопки skipm:<индекс в полном упорядоченном списке>."""
    rows: list[list[InlineKeyboardButton]] = []
    for j, m in enumerate(matches_slice):
        i = j
        lg = _league_title(m["tournament"])
        label = f"{i + 1}. т{m['round']} · {m['home']} — {m['away']} ({lg})"
        if len(label) > 64:
            label = label[:61] + "…"
        rows.append([InlineKeyboardButton(text=label, callback_data=f"skipm:{i}")])
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
    lg = _league_title(row["tournament"])
    rnd = row["round"]
    extra = ""
    if row["tournament"] == "cl":
        extra = f"\nФаза ЛЧ: <code>{row.get('cl_phase') or 'knockout'}</code>"

    await state.set_state(SkipPlay.awaiting_score)
    await state.update_data(skip_play_row=dict(row))

    await callback.message.answer(
        f"Отложенный матч · <b>{lg}</b>, тур дня <b>{rnd}</b>{extra}\n"
        f"<b>{row['home']}</b> — <b>{row['away']}</b>\n\n"
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
    )


@match_router.callback_query(F.data == "postmatch:stats_n")
async def cb_postmatch_stats_no(callback: CallbackQuery, state: FSMContext) -> None:
    if await state.get_state() != PostMatch.offer_stats:
        await callback.answer()
        return
    await callback.answer()
    await state.clear()
    await callback.message.answer("Без статистики.")


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
    await _send_stats_lines_ui(callback.message, state)


@match_router.callback_query(F.data == "stats:done")
async def cb_stats_done(callback: CallbackQuery, state: FSMContext) -> None:
    if await state.get_state() != PostMatch.stats_lines:
        await callback.answer()
        return
    await callback.answer()
    await _finalize_stats_session(callback.message, state)


@match_router.message(PostMatch.stats_lines, Command("done"))
async def cmd_stats_done_cmd(message: Message, state: FSMContext) -> None:
    await _finalize_stats_session(message, state)


@match_router.callback_query(F.data.startswith("ason:"))
async def cb_ason_league(callback: CallbackQuery, state: FSMContext) -> None:
    code = callback.data.split(":", 1)[1]
    await callback.answer()
    await state.clear()
    await state.set_state(AddOnlyStats.home)
    await state.update_data(ason_league=code)
    await callback.message.answer(
        f"Лига: <b>{_league_title(code)}</b>\n"
        f"Введи название <b>хозяев</b> (как в базе):",
        parse_mode="HTML",
    )


@match_router.message(Command("stats_match"))
async def cmd_stats_match(message: Message, state: FSMContext) -> None:
    await state.clear()
    await message.answer(
        "Статистика по уже сыгранному матчу (как «a» в консоли).\n"
        "Выбери лигу — затем хозяева, гости, счёт и строки статистики.\n"
        "/cancel — отмена.",
        reply_markup=build_ason_league_kb(),
    )


@match_router.message(AddOnlyStats.home, _TEXT_NOT_CMD)
async def on_ason_home(message: Message, state: FSMContext) -> None:
    await state.update_data(ason_home=message.text.strip())
    await state.set_state(AddOnlyStats.away)
    await message.answer("Введи название гостей:")


@match_router.message(AddOnlyStats.away, _TEXT_NOT_CMD)
async def on_ason_away(message: Message, state: FSMContext) -> None:
    await state.update_data(ason_away=message.text.strip())
    await state.set_state(AddOnlyStats.score)
    await message.answer(
        "Введи счёт два числа через пробел (хозяева гости), например: 2 1"
    )


@match_router.message(AddOnlyStats.score, _TEXT_NOT_CMD)
async def on_ason_score(message: Message, state: FSMContext) -> None:
    raw = message.text.strip()
    m = _SCORE_RE.match(raw)
    if not m:
        await message.answer("Нужны два числа через пробел, например: 2 1")
        return

    hs, aws = int(m.group(1)), int(m.group(2))
    data = await state.get_data()
    lc = data["ason_league"]
    home = data["ason_home"].strip().title()
    away = data["ason_away"].strip().title()

    await state.update_data(
        stats_home=home,
        stats_away=away,
        stats_hs=hs,
        stats_aws=aws,
        stats_tournament="cl" if lc == "cl" else "league",
        pending_journal={
            "home": home,
            "away": away,
            "lc": lc,
            "hs": hs,
            "aws": aws,
        },
    )
    await _send_stats_lines_ui(message, state)


@match_router.message(PostMatch.stats_lines, _TEXT_NOT_CMD)
async def on_stats_line(message: Message, state: FSMContext) -> None:
    from player_stats import apply_stats_bot_line

    data = await state.get_data()
    home = data.get("stats_home")
    away = data.get("stats_away")
    if not home:
        await state.clear()
        await message.answer("Сессия сброшена.")
        return

    hs = data["stats_hs"]
    aws = data["stats_aws"]
    tournament = data.get("stats_tournament", "league")
    cur_team = data.get("stats_current_team", home)
    mode_new = bool(data.get("stats_mode_new", False))

    def run_line() -> tuple[str, str, bool]:
        return apply_stats_bot_line(
            message.text or "",
            home_team=home,
            away_team=away,
            home_score=hs,
            away_score=aws,
            tournament=tournament,
            current_team=cur_team,
            mode_new=mode_new,
        )

    reply, new_team, new_mode = await asyncio.to_thread(run_line)
    await state.update_data(stats_current_team=new_team, stats_mode_new=new_mode)

    tail = html_escape(reply)
    if len(tail) > 3800:
        tail = tail[:3797] + "…"
    await message.answer(f"<pre>{tail}</pre>", parse_mode="HTML")
