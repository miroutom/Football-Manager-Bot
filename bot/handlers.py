"""Хендлеры aiogram: доступ по ALLOWED_USER_IDS, отчёты через bot.services."""
from __future__ import annotations

import asyncio
import logging
import time
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
    render_archived_season_stat,
    render_cl_bracket_text,
    render_cumulative_top_assists,
    render_cumulative_top_ga,
    render_cumulative_top_scorers,
    render_full_status_text,
    render_journal_report,
    render_next_match_text,
    render_schedule_intrinsic_rounds,
    render_schedule_mixed,
    render_skipped_matches_text,
    render_standings,
    render_archived_season_team_goalscorers_league,
    render_archived_season_team_goalscorers_single,
    render_team_goalscorers_league,
    render_team_goalscorers_single,
    render_team_squad_pitch_png_bytes,
    render_top100_all_leagues,
    teams_ordered_for_goalscorers,
    teams_ordered_for_goalscorers_season_archive,
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


def _league_keyboard_tgs_season(season_num: int) -> InlineKeyboardMarkup:
    """Выбор лиги для голеадоров — архив ``season_num`` (после ``tgsroot``)."""
    rows: list[list[InlineKeyboardButton]] = []
    row: list[InlineKeyboardButton] = []
    for code, label in LEAGUE_LABELS:
        row.append(
            InlineKeyboardButton(
                text=label,
                callback_data=f"tgssn:{season_num}:{code}",
            )
        )
        if len(row) == 3:
            rows.append(row)
            row = []
    if row:
        rows.append(row)
    return InlineKeyboardMarkup(inline_keyboard=rows)


def _tgs_season_root_keyboard() -> InlineKeyboardMarkup:
    """Главное меню → голеадоры: сначала текущий сезон или архив db/season_n."""
    nums = _season_numbers_for_stats_picker()
    rows: list[list[InlineKeyboardButton]] = [
        [
            InlineKeyboardButton(
                text="📍 Текущий сезон",
                callback_data="tgsroot:cur",
            ),
        ],
    ]
    row: list[InlineKeyboardButton] = []
    for n in nums:
        row.append(
            InlineKeyboardButton(
                text=f"Сезон {n}",
                callback_data=f"tgsroot:{n}",
            )
        )
        if len(row) >= 4:
            rows.append(row)
            row = []
    if row:
        rows.append(row)
    return InlineKeyboardMarkup(inline_keyboard=rows)


def _tgclub_keyboard_season(season_num: int, league_code: str) -> InlineKeyboardMarkup:
    teams = teams_ordered_for_goalscorers_season_archive(season_num, league_code)
    rows: list[list[InlineKeyboardButton]] = []
    row: list[InlineKeyboardButton] = []
    for idx, team in enumerate(teams):
        row.append(
            InlineKeyboardButton(
                text=_club_btn_label(team),
                callback_data=f"tgclubsn:{season_num}:{league_code}:{idx}",
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
                callback_data=f"tgsallsn:{season_num}:{league_code}",
            ),
        ]
    )
    return InlineKeyboardMarkup(inline_keyboard=rows)


def _season_numbers_for_stats_picker() -> list[int]:
    from utils import season_paths
    from utils.cumulative_db import list_season_archives_with_db

    nums = set(list_season_archives_with_db())
    try:
        nums.add(int(season_paths.get_active_season()))
    except (TypeError, ValueError):
        pass
    return sorted(n for n in nums if n >= 1)


def _table_season_kb() -> InlineKeyboardMarkup:
    """Сначала выбор сезона, затем лига (callback tbls:… → tbl:…:rpl)."""
    nums = _season_numbers_for_stats_picker()
    rows: list[list[InlineKeyboardButton]] = [
        [
            InlineKeyboardButton(
                text="📍 Текущий сезон",
                callback_data="tbls:cur",
            ),
        ],
    ]
    row: list[InlineKeyboardButton] = []
    for n in nums:
        row.append(
            InlineKeyboardButton(
                text=f"Сезон {n}",
                callback_data=f"tbls:{n}",
            )
        )
        if len(row) >= 4:
            rows.append(row)
            row = []
    if row:
        rows.append(row)
    return InlineKeyboardMarkup(inline_keyboard=rows)


def _league_keyboard_for_table(season_key: str) -> InlineKeyboardMarkup:
    """Таблица: tbl:<season_key>:<league_code> (season_key = cur или номер)."""
    rows: list[list[InlineKeyboardButton]] = []
    row: list[InlineKeyboardButton] = []
    for code, label in LEAGUE_LABELS:
        row.append(
            InlineKeyboardButton(
                text=label,
                callback_data=f"tbl:{season_key}:{code}",
            )
        )
        if len(row) == 3:
            rows.append(row)
            row = []
    if row:
        rows.append(row)
    return InlineKeyboardMarkup(inline_keyboard=rows)


def _stats_history_root_kb() -> InlineKeyboardMarkup:
    rows: list[list[InlineKeyboardButton]] = [
        [
            InlineKeyboardButton(
                text="⚽ Всё время · голы",
                callback_data="stats:hist:life:g:a",
            ),
            InlineKeyboardButton(
                text="🎯 Всё время · асс",
                callback_data="stats:hist:life:as:a",
            ),
            InlineKeyboardButton(
                text="📈 Всё время · Г+А",
                callback_data="stats:hist:life:ga:a",
            ),
        ],
        [
            InlineKeyboardButton(text="⚽ РПЛ", callback_data="stats:hist:life:g:rpl"),
            InlineKeyboardButton(text="⚽ АПЛ", callback_data="stats:hist:life:g:eng"),
            InlineKeyboardButton(text="⚽ Ла Лига", callback_data="stats:hist:life:g:esp"),
        ],
        [
            InlineKeyboardButton(text="⚽ Серия А", callback_data="stats:hist:life:g:ita"),
            InlineKeyboardButton(text="⚽ Бундес", callback_data="stats:hist:life:g:ger"),
            InlineKeyboardButton(text="⚽ ЛЧ", callback_data="stats:hist:life:g:cl"),
        ],
        [
            InlineKeyboardButton(
                text="📅 Сезон (любой)",
                callback_data="stats:hist:seasons",
            ),
        ],
    ]
    return InlineKeyboardMarkup(inline_keyboard=rows)


def _stats_history_seasons_kb() -> InlineKeyboardMarkup:
    nums = _season_numbers_for_stats_picker()
    rows: list[list[InlineKeyboardButton]] = []
    row: list[InlineKeyboardButton] = []
    for n in nums:
        row.append(
            InlineKeyboardButton(
                text=f"Сезон {n}",
                callback_data=f"stats:hist:sn:{n}",
            )
        )
        if len(row) >= 4:
            rows.append(row)
            row = []
    if row:
        rows.append(row)
    rows.append(
        [
            InlineKeyboardButton(
                text="« Всё время",
                callback_data="stats:hist:backroot",
            ),
        ]
    )
    return InlineKeyboardMarkup(inline_keyboard=rows)


def _stats_history_season_metric_kb(season_num: int) -> InlineKeyboardMarkup:
    p = f"stats:hist:sn:{season_num}"
    codes = [
        ("rpl", "РПЛ"),
        ("eng", "АПЛ"),
        ("esp", "Исп"),
        ("ita", "Ит"),
        ("ger", "Гер"),
        ("cl", "ЛЧ"),
    ]
    rows: list[list[InlineKeyboardButton]] = [
        [
            InlineKeyboardButton(text="⚽ Все лиги", callback_data=f"{p}:g:a"),
            InlineKeyboardButton(text="🎯 Все лиги", callback_data=f"{p}:as:a"),
            InlineKeyboardButton(text="📈 Все лиги", callback_data=f"{p}:ga:a"),
        ],
    ]
    for metric, em in (("g", "⚽"), ("as", "🎯"), ("ga", "📈")):
        for i in range(0, 6, 3):
            chunk = codes[i : i + 3]
            rows.append(
                [
                    InlineKeyboardButton(
                        text=f"{em} {lab}",
                        callback_data=f"{p}:{metric}:{c}",
                    )
                    for c, lab in chunk
                ]
            )
    rows.append(
        [
            InlineKeyboardButton(
                text="« Сезоны",
                callback_data="stats:hist:seasons",
            ),
            InlineKeyboardButton(
                text="« Всё время",
                callback_data="stats:hist:backroot",
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
            "📅 Расписание — весь календарь картинками; 📚 Стата сезонов — всё время и архив. "
            "Топ-100, топы лига+ЛЧ, голеадоры, стата без матча — в меню или /help.\n"
            "Снизу экрана кнопка «📋 Меню» снова открывает главное меню."
        ),
        inline_title="Выберите действие:",
    )


@router.callback_query(F.data == "menu:table")
async def cb_menu_table(callback: CallbackQuery) -> None:
    await callback.answer()
    await callback.message.answer(
        "Таблица: сначала выберите сезон (текущий — живой pickle и журнал; "
        "архив — снимок <code>db/season_n</code>, для ЛЧ при наличии — "
        "<code>match_results.json</code> из архива):",
        parse_mode=ParseMode.HTML,
        reply_markup=_table_season_kb(),
    )


@router.callback_query(F.data.startswith("tbls:"))
async def cb_table_season_pick(callback: CallbackQuery) -> None:
    parts = (callback.data or "").split(":")
    if len(parts) != 2:
        await callback.answer()
        return
    season_key = parts[1].strip()
    if not season_key:
        await callback.answer()
        return
    await callback.answer()
    label = "текущий сезон" if season_key == "cur" else f"сезон {season_key}"
    await callback.message.answer(
        f"Лига для таблицы ({label}):",
        reply_markup=_league_keyboard_for_table(season_key),
    )


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
    parts = (callback.data or "").split(":")
    if len(parts) == 3:
        _, season_key, code = parts
        if season_key == "cur":
            season_num = None
        else:
            try:
                season_num = int(season_key)
            except ValueError:
                await callback.message.answer("Некорректный номер сезона.")
                return
    elif len(parts) == 2:
        _, code = parts
        season_num = None
    else:
        await callback.message.answer("Некорректная кнопка таблицы.")
        return
    try:
        text = await asyncio.to_thread(render_standings, code, season_num)
        suf = " · текущий" if season_num is None else f" · сезон {season_num}"
        await answer_report_photos(
            callback.message,
            text,
            f"Таблица · {_league_title(code)}{suf}",
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


@router.callback_query(F.data == "menu:stats_history")
async def cb_menu_stats_history(callback: CallbackQuery) -> None:
    await callback.answer()
    await callback.message.answer(
        "<b>Стата сезонов</b>\n"
        "• <b>Всё время</b> — <code>league_synced.db</code>, <code>champions_league_synced.db</code>, "
        "<code>common_synced.db</code>.\n"
        "• <b>Сезон</b> — снимок из <code>db/season_N/</code> (любой номер из списка).\n"
        "Текущий игровой сезон — также «Бомбардиры», «Ещё топы»; архивные голеадоры по клубам — "
        "кнопка «👥 Голеадоры по клубам» (выбор сезона там же).\n",
        parse_mode="HTML",
        reply_markup=_stats_history_root_kb(),
    )


def _stats_hist_caption_life(metric: str, league_code: str | None) -> str:
    m = metric.lower()
    if m == "g":
        base = "Топ бомбардиров · всё время"
    elif m in ("as", "a"):
        base = "Топ ассистов · всё время"
    else:
        base = "Топ Г+А · всё время"
    if league_code:
        return f"{base} · {_league_title(league_code)}"
    return base


def _stats_hist_caption_season(sn: int, metric: str, league_code: str | None) -> str:
    m = metric.lower()
    if m == "g":
        base = f"Сезон {sn} · бомбардиры"
    elif m in ("as", "a"):
        base = f"Сезон {sn} · ассисты"
    else:
        base = f"Сезон {sn} · Г+А"
    if league_code:
        return f"{base} · {_league_title(league_code)}"
    return base


@router.callback_query(F.data.startswith("stats:hist:"))
async def cb_stats_history_run(callback: CallbackQuery) -> None:
    parts = callback.data.split(":")
    if len(parts) < 3:
        await callback.answer("Ошибка кнопки.", show_alert=True)
        return

    if parts[2] == "backroot":
        await callback.answer()
        await callback.message.answer(
            "Всё время и сезоны:",
            reply_markup=_stats_history_root_kb(),
        )
        return

    if parts[2] == "seasons":
        await callback.answer()
        nums = _season_numbers_for_stats_picker()
        if not nums:
            await callback.message.answer(
                "Пока нет папок сезонов с league.db в db/. "
                "После игры и завершения сезона появятся архивы."
            )
            return
        await callback.message.answer(
            "Выберите номер сезона:",
            reply_markup=_stats_history_seasons_kb(),
        )
        return

    if parts[2] == "sn":
        if len(parts) == 4:
            await callback.answer()
            sn = int(parts[3])
            await callback.message.answer(
                f"Сезон {sn} — метрика и лига:",
                reply_markup=_stats_history_season_metric_kb(sn),
            )
            return
        if len(parts) == 6:
            sn = int(parts[3])
            metric, lg = parts[4], parts[5]
            lc = None if lg == "a" else lg
            await callback.answer("Считаю…")
            try:
                text = await asyncio.to_thread(
                    render_archived_season_stat, sn, lc, metric, 30
                )
                cap = _stats_hist_caption_season(sn, metric, lc)
                await answer_report_photos(callback.message, text, cap)
            except Exception as e:
                logger.exception("stats:hist sn")
                await callback.message.answer(f"Ошибка: {e}")
            return

    if parts[2] != "life":
        await callback.answer("Неизвестная команда.", show_alert=True)
        return

    if len(parts) != 5:
        await callback.answer("Ошибка кнопки.", show_alert=True)
        return

    metric, code = parts[3], parts[4]
    lc = None if code == "a" else code
    await callback.answer("Считаю…")
    try:
        m = metric.lower()
        if m == "g":
            text = await asyncio.to_thread(render_cumulative_top_scorers, lc, 30)
        elif m in ("as", "a"):
            text = await asyncio.to_thread(render_cumulative_top_assists, lc, 30)
        elif m in ("ga",):
            text = await asyncio.to_thread(render_cumulative_top_ga, lc, 30)
        else:
            await callback.message.answer(f"Неизвестная метрика: {metric}")
            return
        cap = _stats_hist_caption_life(metric, lc)
        await answer_report_photos(callback.message, text, cap)
    except Exception as e:
        logger.exception("stats:hist life")
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
    await message.answer(
        "Таблица: выберите сезон.",
        reply_markup=_table_season_kb(),
    )


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
    """Сразу весь mixed_schedule.json (все слоты), как «Смеш · все»; подменю — для других срезов."""
    await callback.answer("Генерация…")
    try:
        text = await asyncio.to_thread(render_schedule_mixed, None, "all")
        await answer_report_photos(
            callback.message,
            text,
            "Смешанное расписание — все матчи",
        )
        await callback.message.answer(
            "Другие срезы: остаток по лигам, туры лиг, сыгранное из журнала.",
            reply_markup=_schedule_menu_kb(),
        )
    except Exception as e:
        logger.exception("menu:schedule")
        await callback.message.answer(f"Ошибка: {e}")


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
        "Топы лига + ЛЧ из <code>common_synced.db</code> (все сезоны), как «b» с «+» в консоли. "
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
        "Голеадоры по клубу: сначала выберите <b>сезон</b> "
        "(текущие рабочие БД или архив <code>db/season_N</code>), затем лигу и клуб "
        "(или «Все клубы подряд»):",
        parse_mode=ParseMode.HTML,
        reply_markup=_tgs_season_root_keyboard(),
    )


@router.callback_query(F.data.startswith("tgsroot:"))
async def cb_tgsroot_season(callback: CallbackQuery) -> None:
    """После выбора сезона — клавиатура лиг (текущий или архив)."""
    parts = callback.data.split(":")
    if len(parts) != 2:
        await callback.answer()
        return
    key = parts[1]
    await callback.answer()
    if key == "cur":
        await callback.message.answer(
            "Текущий сезон — выберите лигу, затем клуб (или «Все клубы подряд»):",
            reply_markup=_league_keyboard("tgs"),
        )
        return
    try:
        sn = int(key)
    except ValueError:
        await callback.message.answer("Неверный выбор сезона.")
        return
    await callback.message.answer(
        f"Сезон {sn} (архив) — выберите лигу, затем клуб (или «Все клубы подряд»):",
        reply_markup=_league_keyboard_tgs_season(sn),
    )


@router.callback_query(F.data.startswith("tgssn:"))
async def cb_tgssn_pick_league_archived(callback: CallbackQuery) -> None:
    """Архив: лига выбрана — список клубов."""
    parts = callback.data.split(":")
    if len(parts) != 3:
        await callback.answer()
        return
    try:
        sn = int(parts[1])
    except ValueError:
        await callback.answer()
        return
    code = parts[2]
    await callback.answer()
    try:
        kb = _tgclub_keyboard_season(sn, code)
    except Exception as e:
        logger.exception("tgssn_kb")
        await callback.message.answer(f"Ошибка: {e}")
        return
    await callback.message.answer(
        f"Сезон {sn} · {_league_title(code)} — выберите клуб:",
        reply_markup=kb,
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
            BufferedInputFile(
                png,
                filename=f"squad_{code}_{idx}_{time.time_ns()}.png",
            ),
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


@router.callback_query(F.data.startswith("tgclubsn:"))
async def cb_tgclubsn_archived_team(callback: CallbackQuery) -> None:
    parts = callback.data.split(":")
    if len(parts) != 4:
        await callback.answer()
        return
    try:
        sn = int(parts[1])
        idx = int(parts[3])
    except ValueError:
        await callback.answer()
        return
    code = parts[2]
    await callback.answer("Считаю…")
    try:
        text = await asyncio.to_thread(
            render_archived_season_team_goalscorers_single, sn, code, idx
        )
        teams = await asyncio.to_thread(
            teams_ordered_for_goalscorers_season_archive, sn, code
        )
        team_name = teams[idx]
        title = f"Голеадоры · сезон {sn} · {_league_title(code)} · {team_name}"
        await answer_report_photos(callback.message, text, title)
    except Exception as e:
        logger.exception("tgclubsn")
        await callback.message.answer(f"Ошибка: {e}")


@router.callback_query(F.data.startswith("tgsallsn:"))
async def cb_tgsallsn_archived_all(callback: CallbackQuery) -> None:
    parts = callback.data.split(":")
    if len(parts) != 3:
        await callback.answer()
        return
    try:
        sn = int(parts[1])
    except ValueError:
        await callback.answer()
        return
    code = parts[2]
    await callback.answer("Считаю…")
    try:
        text = await asyncio.to_thread(
            render_archived_season_team_goalscorers_league, sn, code
        )
        await answer_report_photos(
            callback.message,
            text,
            f"Голеадоры по клубам · сезон {sn} · {_league_title(code)} · все клубы",
        )
    except Exception as e:
        logger.exception("tgsallsn")
        await callback.message.answer(f"Ошибка: {e}")
