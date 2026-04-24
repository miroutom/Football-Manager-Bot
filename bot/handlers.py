"""Хендлеры aiogram: доступ по ALLOWED_USER_IDS, отчёты через bot.services."""
from __future__ import annotations

import asyncio
import logging
from functools import partial
from typing import Any, Awaitable, Callable

from aiogram import F, Router
from aiogram.dispatcher.middlewares.base import BaseMiddleware
from aiogram.enums import ParseMode
from aiogram.filters import Command
from aiogram.types import (
    BufferedInputFile,
    CallbackQuery,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    InputMediaPhoto,
    Message,
    TelegramObject,
)

from bot.image_render import render_monospace_png_bytes
from bot.services import (
    LEAGUE_LABELS,
    render_cl_bracket_text,
    render_full_status_text,
    render_journal_report,
    render_next_match_text,
    render_schedule_intrinsic_rounds,
    render_schedule_mixed,
    render_schedule_queue_text,
    render_skipped_matches_text,
    render_standings,
    render_team_goalscorers_league,
    render_team_goalscorers_single,
    render_team_squad_pitch_png_bytes,
    render_top100_all_leagues,
    teams_ordered_for_goalscorers,
    render_top_assists,
    render_top_assists_common,
    render_top_ga,
    render_top_ga_common,
    render_top_scorers,
    render_top_scorers_common,
    split_text_chunks,
    to_pre_html,
)
from bot.keyboards import send_main_menu_screen
from bot.match_handlers import build_ason_league_kb
from bot.settings import get_allowed_user_ids

logger = logging.getLogger(__name__)

router = Router()


def _league_title(code: str) -> str:
    return dict(LEAGUE_LABELS).get(code, code)


async def answer_report_photos(message: Message, body: str, caption: str) -> None:
    """Таблица / топ — одна или несколько PNG (заголовок уже внутри картинки)."""
    blobs = await asyncio.to_thread(
        partial(render_monospace_png_bytes, body, title=caption),
    )
    if not blobs:
        return
    if len(blobs) == 1:
        await message.answer_photo(
            BufferedInputFile(blobs[0], filename="report_0.png"),
        )
        return
    chunk_size = 10
    idx = 0
    while idx < len(blobs):
        chunk = blobs[idx : idx + chunk_size]
        media: list[InputMediaPhoto] = []
        for j, blob in enumerate(chunk):
            bf = BufferedInputFile(blob, filename=f"report_{idx + j}.png")
            media.append(InputMediaPhoto(media=bf))
        await message.answer_media_group(media)
        idx += chunk_size


async def send_cl_bracket(message: Message) -> None:
    """Сетка плей-офф ЛЧ: инфографика PNG; при ошибке — моноширинный текст как раньше."""
    from champions_league.bracket_infographic import render_cl_bracket_infographic_png_bytes

    try:
        png = await asyncio.to_thread(render_cl_bracket_infographic_png_bytes)
        await message.answer_photo(BufferedInputFile(png, filename="cl_bracket.png"))
        return
    except Exception:
        logger.exception("bracket_infographic")

    txt = await asyncio.to_thread(render_cl_bracket_text)
    try:
        await answer_report_photos(message, txt or "(пусто)", "Сетка ЛЧ")
    except Exception as e:
        logger.exception("bracket_png")
        await message.answer(f"Не удалось нарисовать сетку картинкой: {e}")
        if txt:
            for chunk in split_text_chunks(txt, 3800):
                await message.answer(to_pre_html(chunk), parse_mode=ParseMode.HTML)


def _league_keyboard(prefix: str) -> InlineKeyboardMarkup:
    rows: list[list[InlineKeyboardButton]] = []
    row: list[InlineKeyboardButton] = []
    for code, label in LEAGUE_LABELS:
        row.append(InlineKeyboardButton(text=label, callback_data=f"{prefix}:{code}"))
        if len(row) == 3:
            rows.append(row)
            row = []
    if row:
        rows.append(row)
    return InlineKeyboardMarkup(inline_keyboard=rows)


def _club_btn_label(text: str, max_chars: int = 40) -> str:
    """Подпись на кнопке (у Telegram лимит ~64 символа)."""
    text = text.strip()
    if len(text) <= max_chars:
        return text
    return text[: max_chars - 1] + "…"


def _squad_club_keyboard(league_code: str) -> InlineKeyboardMarkup:
    teams = teams_ordered_for_goalscorers(league_code)
    rows: list[list[InlineKeyboardButton]] = []
    row: list[InlineKeyboardButton] = []
    for idx, team in enumerate(teams):
        row.append(
            InlineKeyboardButton(
                text=_club_btn_label(team),
                callback_data=f"sqclub:{league_code}:{idx}",
            )
        )
        if len(row) == 2:
            rows.append(row)
            row = []
    if row:
        rows.append(row)
    return InlineKeyboardMarkup(inline_keyboard=rows)


def _tgclub_keyboard(league_code: str) -> InlineKeyboardMarkup:
    teams = teams_ordered_for_goalscorers(league_code)
    rows: list[list[InlineKeyboardButton]] = []
    row: list[InlineKeyboardButton] = []
    for idx, team in enumerate(teams):
        row.append(
            InlineKeyboardButton(
                text=_club_btn_label(team),
                callback_data=f"tgclub:{league_code}:{idx}",
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
                text="📋 Все клубы подряд",
                callback_data=f"tgsall:{league_code}",
            ),
        ]
    )
    return InlineKeyboardMarkup(inline_keyboard=rows)


def _schedule_menu_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(text="Смеш · все", callback_data="sch:mix:a:xx"),
                InlineKeyboardButton(text="Смеш · осталось", callback_data="sch:mix:r:xx"),
            ],
            [
                InlineKeyboardButton(
                    text="Журнал сыгранных",
                    callback_data="sch:mix:p:xx",
                ),
                InlineKeyboardButton(
                    text="Журнал · РПЛ",
                    callback_data="sch:mix:p:rpl",
                ),
            ],
            [
                InlineKeyboardButton(
                    text="Смеш · ЛЧ ост.",
                    callback_data="sch:mix:r:cl",
                ),
                InlineKeyboardButton(
                    text="Туры РПЛ · ост.",
                    callback_data="sch:in:rpl:r",
                ),
            ],
            [
                InlineKeyboardButton(text="Туры АПЛ · ост.", callback_data="sch:in:eng:r"),
                InlineKeyboardButton(text="Туры Ла Лига · ост.", callback_data="sch:in:esp:r"),
            ],
            [
                InlineKeyboardButton(text="Туры Серия А · ост.", callback_data="sch:in:ita:r"),
                InlineKeyboardButton(text="Туры Бундес · ост.", callback_data="sch:in:ger:r"),
            ],
            [
                InlineKeyboardButton(text="Туры ЛЧ · ост.", callback_data="sch:in:cl:r"),
            ],
        ]
    )


def _tops_plus_kb() -> InlineKeyboardMarkup:
    rows: list[list[InlineKeyboardButton]] = []
    for code, label in LEAGUE_LABELS:
        rows.append(
            [
                InlineKeyboardButton(
                    text=f"{label} ⚽",
                    callback_data=f"tcp:g:{code}",
                ),
                InlineKeyboardButton(
                    text=f"{label} 🎯",
                    callback_data=f"tcp:a:{code}",
                ),
                InlineKeyboardButton(
                    text=f"{label} 📈",
                    callback_data=f"tcp:ga:{code}",
                ),
            ]
        )
    return InlineKeyboardMarkup(inline_keyboard=rows)


class AccessMiddleware(BaseMiddleware):
    """Если ALLOWED_USER_IDS задан — только эти пользователи."""

    async def __call__(
        self,
        handler: Callable[[TelegramObject, dict[str, Any]], Awaitable[Any]],
        event: TelegramObject,
        data: dict[str, Any],
    ) -> Any:
        allowed = get_allowed_user_ids()
        if not allowed:
            return await handler(event, data)

        uid = None
        if isinstance(event, Message) and event.from_user:
            uid = event.from_user.id
        elif isinstance(event, CallbackQuery) and event.from_user:
            uid = event.from_user.id

        if uid is None or uid not in allowed:
            if isinstance(event, Message):
                await event.answer("Доступ запрещён.")
            elif isinstance(event, CallbackQuery):
                await event.answer("Нет доступа.", show_alert=True)
            return None

        return await handler(event, data)


@router.message(Command("start"))
async def cmd_start(message: Message) -> None:
    await send_main_menu_screen(
        message,
        intro_text=(
            "⚽ Football Manager — журнал, расписание, таблицы, топы.\n"
            "Запись счёта: «✅ Записать следующий», «✏️ Ручной матч», «📌 Из пропусков» или "
            "/play_next, /match, /play_skipped.\n"
            "Трансфер игрока — кнопка «🔄 Трансфер» или /transfer.\n"
            "Расписание, топ-100, топы лига+ЛЧ, голеадоры по клубам, стата без матча — кнопки в меню или /help.\n"
            "Снизу экрана кнопка «📋 Меню» снова открывает главное меню."
        ),
        inline_title="Выберите действие:",
    )


@router.callback_query(F.data == "menu:table")
async def cb_menu_table(callback: CallbackQuery) -> None:
    await callback.answer()
    await callback.message.answer("Лига для таблицы:", reply_markup=_league_keyboard("tbl"))


@router.callback_query(F.data == "menu:goals")
async def cb_menu_goals(callback: CallbackQuery) -> None:
    await callback.answer()
    await callback.message.answer("Лига (бомбардиры):", reply_markup=_league_keyboard("gls"))


@router.callback_query(F.data == "menu:assists")
async def cb_menu_assists(callback: CallbackQuery) -> None:
    await callback.answer()
    await callback.message.answer("Лига (ассисты):", reply_markup=_league_keyboard("ast"))


@router.callback_query(F.data == "menu:ga")
async def cb_menu_ga(callback: CallbackQuery) -> None:
    await callback.answer()
    await callback.message.answer("Лига (гол+пас):", reply_markup=_league_keyboard("gaa"))


@router.callback_query(F.data == "menu:status")
async def cb_menu_status(callback: CallbackQuery) -> None:
    await callback.answer()
    try:
        text = await asyncio.to_thread(render_full_status_text)
        await answer_report_photos(callback.message, text, "Статус матч-дня")
    except Exception as e:
        logger.exception("status")
        await callback.message.answer(f"Ошибка статуса: {e}")


@router.callback_query(F.data == "menu:bracket")
async def cb_menu_bracket(callback: CallbackQuery) -> None:
    await callback.answer("Рисую сетку…")
    try:
        await send_cl_bracket(callback.message)
    except Exception as e:
        logger.exception("bracket")
        await callback.message.answer(f"Ошибка сетки: {e}")


@router.callback_query(F.data.startswith("tbl:"))
async def cb_table(callback: CallbackQuery) -> None:
    await callback.answer()
    code = callback.data.split(":", 1)[1]
    try:
        text = await asyncio.to_thread(render_standings, code)
        await answer_report_photos(
            callback.message,
            text,
            f"Таблица · {_league_title(code)}",
        )
    except Exception as e:
        logger.exception("table")
        await callback.message.answer(f"Ошибка таблицы: {e}")


@router.callback_query(F.data.startswith("gls:"))
async def cb_goals(callback: CallbackQuery) -> None:
    await callback.answer()
    code = callback.data.split(":", 1)[1]
    try:
        text = await asyncio.to_thread(render_top_scorers, code)
        await answer_report_photos(
            callback.message,
            text,
            f"Топ бомбардиров · {_league_title(code)}",
        )
    except Exception as e:
        logger.exception("goals")
        await callback.message.answer(f"Ошибка: {e}")


@router.callback_query(F.data.startswith("ast:"))
async def cb_assists(callback: CallbackQuery) -> None:
    await callback.answer()
    code = callback.data.split(":", 1)[1]
    try:
        text = await asyncio.to_thread(render_top_assists, code)
        await answer_report_photos(
            callback.message,
            text,
            f"Топ ассистентов · {_league_title(code)}",
        )
    except Exception as e:
        logger.exception("assists")
        await callback.message.answer(f"Ошибка: {e}")


@router.callback_query(F.data == "menu:next")
async def cb_menu_next(callback: CallbackQuery) -> None:
    await callback.answer()
    try:
        text = await asyncio.to_thread(render_next_match_text)
        await callback.message.answer(to_pre_html(text), parse_mode=ParseMode.HTML)
    except Exception as e:
        logger.exception("next")
        await callback.message.answer(f"Ошибка: {e}")


@router.callback_query(F.data == "menu:queue")
async def cb_menu_queue(callback: CallbackQuery) -> None:
    await callback.answer()
    try:
        text = await asyncio.to_thread(render_schedule_queue_text, 18)
        await answer_report_photos(callback.message, text, "Очередь календаря")
    except Exception as e:
        logger.exception("queue")
        await callback.message.answer(f"Ошибка: {e}")


@router.callback_query(F.data == "menu:skipped")
async def cb_menu_skipped(callback: CallbackQuery) -> None:
    await callback.answer()
    try:
        text = await asyncio.to_thread(render_skipped_matches_text)
        await answer_report_photos(callback.message, text, "Пропущенные матчи")
    except Exception as e:
        logger.exception("skipped")
        await callback.message.answer(f"Ошибка: {e}")


@router.callback_query(F.data == "menu:journal")
async def cb_menu_journal(callback: CallbackQuery) -> None:
    await callback.answer()
    try:
        text = await asyncio.to_thread(render_journal_report, 120)
        await answer_report_photos(callback.message, text, "Журнал сыгранных (хвост)")
    except Exception as e:
        logger.exception("journal")
        await callback.message.answer(f"Ошибка: {e}")


@router.callback_query(F.data.startswith("gaa:"))
async def cb_ga(callback: CallbackQuery) -> None:
    await callback.answer()
    code = callback.data.split(":", 1)[1]
    try:
        text = await asyncio.to_thread(render_top_ga, code)
        await answer_report_photos(
            callback.message,
            text,
            f"Топ гол+пас · {_league_title(code)}",
        )
    except Exception as e:
        logger.exception("ga")
        await callback.message.answer(f"Ошибка: {e}")


@router.message(Command("table"))
async def cmd_table(message: Message) -> None:
    await message.answer("Лига для таблицы:", reply_markup=_league_keyboard("tbl"))


@router.message(Command("goals"))
async def cmd_goals(message: Message) -> None:
    await message.answer("Лига:", reply_markup=_league_keyboard("gls"))


@router.message(Command("assists"))
async def cmd_assists(message: Message) -> None:
    await message.answer("Лига:", reply_markup=_league_keyboard("ast"))


@router.message(Command("ga"))
async def cmd_ga(message: Message) -> None:
    await message.answer("Лига:", reply_markup=_league_keyboard("gaa"))


@router.message(Command("bracket"))
async def cmd_bracket(message: Message) -> None:
    try:
        await send_cl_bracket(message)
    except Exception as e:
        logger.exception("bracket")
        await message.answer(f"Ошибка сетки: {e}")


@router.message(Command("status"))
async def cmd_status(message: Message) -> None:
    try:
        text = await asyncio.to_thread(render_full_status_text)
        await answer_report_photos(message, text, "Статус матч-дня")
    except Exception as e:
        logger.exception("status")
        await message.answer(f"Ошибка: {e}")


@router.message(Command("next"))
async def cmd_next(message: Message) -> None:
    text = await asyncio.to_thread(render_next_match_text)
    await message.answer(to_pre_html(text), parse_mode=ParseMode.HTML)


@router.message(Command("queue"))
async def cmd_queue(message: Message) -> None:
    try:
        text = await asyncio.to_thread(render_schedule_queue_text, 18)
        await answer_report_photos(message, text, "Очередь календаря")
    except Exception as e:
        logger.exception("queue")
        await message.answer(f"Ошибка: {e}")


@router.message(Command("skipped"))
async def cmd_skipped(message: Message) -> None:
    try:
        text = await asyncio.to_thread(render_skipped_matches_text)
        await answer_report_photos(message, text, "Пропущенные матчи")
    except Exception as e:
        logger.exception("skipped")
        await message.answer(f"Ошибка: {e}")


@router.message(Command("journal"))
async def cmd_journal(message: Message) -> None:
    try:
        text = await asyncio.to_thread(render_journal_report, 120)
        await answer_report_photos(message, text, "Журнал сыгранных (хвост)")
    except Exception as e:
        logger.exception("journal")
        await message.answer(f"Ошибка: {e}")


@router.callback_query(F.data == "menu:schedule")
async def cb_menu_schedule(callback: CallbackQuery) -> None:
    await callback.answer()
    await callback.message.answer(
        "Расписание (как «v» в main, без поиска по названию команды).\n"
        "Смеш — матч-дни; Туры — календарь лиги; Журнал — match_results.",
        reply_markup=_schedule_menu_kb(),
    )


@router.callback_query(F.data == "menu:stats_match")
async def cb_menu_stats_match(callback: CallbackQuery) -> None:
    await callback.answer()
    await callback.message.answer(
        "Статистика по матчу без прохождения матч-дня (как «a»): "
        "лига → хозяева → гости → счёт → строки статы.\n"
        "/cancel — отмена.",
        reply_markup=build_ason_league_kb(),
    )


@router.callback_query(F.data.startswith("sch:mix:"))
async def cb_sch_mixed(callback: CallbackQuery) -> None:
    parts = callback.data.split(":")
    if len(parts) != 4:
        await callback.answer("Ошибка кнопки.", show_alert=True)
        return
    fk = parts[2]
    lg = parts[3]
    mf_map = {"a": "all", "r": "remaining", "p": "played"}
    if fk not in mf_map:
        await callback.answer("Ошибка.", show_alert=True)
        return
    mf_code = mf_map[fk]
    lc = None if lg == "xx" else lg
    await callback.answer("Генерация…")
    try:
        text = await asyncio.to_thread(render_schedule_mixed, lc, mf_code)
        await answer_report_photos(callback.message, text, "Расписание (смешанное)")
    except Exception as e:
        logger.exception("sch:mix")
        await callback.message.answer(f"Ошибка: {e}")


@router.callback_query(F.data.startswith("sch:in:"))
async def cb_sch_intrinsic(callback: CallbackQuery) -> None:
    parts = callback.data.split(":")
    if len(parts) != 4:
        await callback.answer("Ошибка кнопки.", show_alert=True)
        return
    lg_code = parts[2]
    fk = parts[3]
    mf_map = {"a": "all", "r": "remaining", "p": "played"}
    if fk not in mf_map:
        await callback.answer("Ошибка.", show_alert=True)
        return
    await callback.answer("Генерация…")
    try:
        text = await asyncio.to_thread(
            render_schedule_intrinsic_rounds, lg_code, mf_map[fk]
        )
        await answer_report_photos(
            callback.message,
            text,
            f"Туры · {_league_title(lg_code)}",
        )
    except Exception as e:
        logger.exception("sch:in")
        await callback.message.answer(f"Ошибка: {e}")


@router.callback_query(F.data == "menu:top100")
async def cb_menu_top100(callback: CallbackQuery) -> None:
    kb = InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(text="По голам", callback_data="top100:1"),
                InlineKeyboardButton(text="По передачам", callback_data="top100:2"),
                InlineKeyboardButton(text="По Г+А", callback_data="top100:3"),
            ]
        ]
    )
    await callback.answer()
    await callback.message.answer(
        "Топ-100 (лига + ЛЧ, все лиги), только игроки с голом или передачей:",
        reply_markup=kb,
    )


@router.callback_query(F.data.startswith("top100:"))
async def cb_top100_sort(callback: CallbackQuery) -> None:
    try:
        sk = int(callback.data.split(":")[1])
    except (IndexError, ValueError):
        await callback.answer()
        return
    await callback.answer("Считаю…")
    try:
        text = await asyncio.to_thread(render_top100_all_leagues, sk, 100)
        await answer_report_photos(callback.message, text, f"Топ-100 (сортировка {sk})")
    except Exception as e:
        logger.exception("top100")
        await callback.message.answer(f"Ошибка: {e}")


@router.callback_query(F.data == "menu:tops_plus")
async def cb_menu_tops_plus(callback: CallbackQuery) -> None:
    await callback.answer()
    await callback.message.answer(
        "Топы лига + ЛЧ (common.db), как пункт «b» с «+» в консоли. "
        "⚽ бомбардиры · 🎯 ассисты · 📈 гол+пас:",
        reply_markup=_tops_plus_kb(),
    )


@router.callback_query(F.data.startswith("tcp:"))
async def cb_tcp_tops(callback: CallbackQuery) -> None:
    parts = callback.data.split(":", 2)
    if len(parts) < 3:
        await callback.answer()
        return
    _, kind, code = parts
    await callback.answer()
    try:
        if kind == "g":
            text = await asyncio.to_thread(render_top_scorers_common, code)
            title = f"Бомбардиры · {_league_title(code)} · лига+ЛЧ"
        elif kind == "a":
            text = await asyncio.to_thread(render_top_assists_common, code)
            title = f"Ассисты · {_league_title(code)} · лига+ЛЧ"
        elif kind == "ga":
            text = await asyncio.to_thread(render_top_ga_common, code)
            title = f"Г+А · {_league_title(code)} · лига+ЛЧ"
        else:
            await callback.message.answer("Неизвестный тип топа.")
            return
        await answer_report_photos(callback.message, text, title)
    except Exception as e:
        logger.exception("tcp")
        await callback.message.answer(f"Ошибка: {e}")


@router.callback_query(F.data == "menu:tgs_league")
async def cb_menu_tgs_league(callback: CallbackQuery) -> None:
    await callback.answer()
    await callback.message.answer(
        "Голеадоры по клубу: выберите лигу, затем клуб "
        "(или «Все клубы подряд», как раньше «b»→4):",
        reply_markup=_league_keyboard("tgs"),
    )


@router.callback_query(F.data.startswith("tgs:"))
async def cb_tgs_pick_league(callback: CallbackQuery) -> None:
    code = callback.data.split(":", 1)[1]
    await callback.answer()
    try:
        kb = _tgclub_keyboard(code)
    except Exception as e:
        logger.exception("tgs_league_kb")
        await callback.message.answer(f"Ошибка: {e}")
        return
    await callback.message.answer(
        f"{_league_title(code)} — выберите клуб:",
        reply_markup=kb,
    )


@router.callback_query(F.data == "menu:squad_league")
async def cb_menu_squad_league(callback: CallbackQuery) -> None:
    await callback.answer()
    await callback.message.answer(
        "Состав клуба на поле (условная 4-3-3): фамилия и число "
        "(overall из БД; если нет — средний рейтинг за матчи). "
        "Выберите лигу, затем клуб:",
        reply_markup=_league_keyboard("squadlg"),
    )


@router.callback_query(F.data.startswith("squadlg:"))
async def cb_squad_pick_league(callback: CallbackQuery) -> None:
    code = callback.data.split(":", 1)[1]
    await callback.answer()
    try:
        kb = _squad_club_keyboard(code)
    except Exception as e:
        logger.exception("squad_league_kb")
        await callback.message.answer(f"Ошибка: {e}")
        return
    await callback.message.answer(
        f"{_league_title(code)} — выберите клуб:",
        reply_markup=kb,
    )


@router.callback_query(F.data.startswith("sqclub:"))
async def cb_sqclub_team(callback: CallbackQuery) -> None:
    parts = callback.data.split(":")
    if len(parts) != 3:
        await callback.answer()
        return
    _, code, idx_s = parts
    try:
        idx = int(idx_s)
    except ValueError:
        await callback.answer()
        return
    await callback.answer("Рисую…")
    try:
        png = await asyncio.to_thread(render_team_squad_pitch_png_bytes, code, idx)
        teams = await asyncio.to_thread(teams_ordered_for_goalscorers, code)
        team_name = teams[idx]
        cap = f"Состав · {_league_title(code)} · {team_name}"
        await callback.message.answer_photo(
            BufferedInputFile(png, filename="squad_pitch.png"),
            caption=cap,
        )
    except Exception as e:
        logger.exception("sqclub")
        await callback.message.answer(f"Ошибка: {e}")


@router.callback_query(F.data.startswith("tgclub:"))
async def cb_tgclub_team(callback: CallbackQuery) -> None:
    parts = callback.data.split(":")
    if len(parts) != 3:
        await callback.answer()
        return
    _, code, idx_s = parts
    try:
        idx = int(idx_s)
    except ValueError:
        await callback.answer()
        return
    await callback.answer("Считаю…")
    try:
        text = await asyncio.to_thread(render_team_goalscorers_single, code, idx)
        teams = await asyncio.to_thread(teams_ordered_for_goalscorers, code)
        team_name = teams[idx]
        title = f"Голеадоры · {_league_title(code)} · {team_name}"
        await answer_report_photos(callback.message, text, title)
    except Exception as e:
        logger.exception("tgclub")
        await callback.message.answer(f"Ошибка: {e}")


@router.callback_query(F.data.startswith("tgsall:"))
async def cb_tgs_all_clubs(callback: CallbackQuery) -> None:
    code = callback.data.split(":", 1)[1]
    await callback.answer("Считаю…")
    try:
        text = await asyncio.to_thread(render_team_goalscorers_league, code)
        await answer_report_photos(
            callback.message,
            text,
            f"Голеадоры по клубам · {_league_title(code)} · все клубы",
        )
    except Exception as e:
        logger.exception("tgsall")
        await callback.message.answer(f"Ошибка: {e}")
