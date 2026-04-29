"""Клавиатуры Telegram: inline-меню и постоянная reply-кнопка «Меню»."""
from __future__ import annotations

from aiogram.types import (
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    KeyboardButton,
    Message,
    ReplyKeyboardMarkup,
)

# Текст должен совпадать с обработчиком в match_handlers (до FSM).
MENU_REPLY_TEXT = "📋 Меню"
# Якорь для первого сообщения (reply-клавиатура): невидимый текст иногда режет Telegram API.
_MENU_ROW_ANCHOR = "·"


def reply_keyboard_menu_button() -> ReplyKeyboardMarkup:
    """Нижняя клавиатура — всегда под рукой, без ответа /menu."""
    return ReplyKeyboardMarkup(
        keyboard=[[KeyboardButton(text=MENU_REPLY_TEXT)]],
        resize_keyboard=True,
    )


def main_menu_inline_kb(*, show_end_season: bool = False) -> InlineKeyboardMarkup:
    """Главное меню (inline). «Завершить сезон» — только когда в календаре не осталось матчей."""
    rows: list[list[InlineKeyboardButton]] = [
        [
            InlineKeyboardButton(
                text="✅ Записать следующий",
                callback_data="play:next",
            ),
            InlineKeyboardButton(
                text="✏️ Ручной матч",
                callback_data="play:manual",
            ),
            InlineKeyboardButton(
                text="📌 Из пропусков",
                callback_data="skip:list",
            ),
        ],
        [
            InlineKeyboardButton(text="📊 Таблица", callback_data="menu:table"),
            InlineKeyboardButton(text="⚽ Бомбардиры", callback_data="menu:goals"),
        ],
        [
            InlineKeyboardButton(text="🎯 Ассисты", callback_data="menu:assists"),
            InlineKeyboardButton(text="📈 Г+А", callback_data="menu:ga"),
        ],
        [
            InlineKeyboardButton(text="🏟 Сетка ЛЧ", callback_data="menu:bracket"),
            InlineKeyboardButton(text="📌 Статус", callback_data="menu:status"),
        ],
        [
            InlineKeyboardButton(text="⏭ След. матч", callback_data="menu:next"),
            InlineKeyboardButton(text="⏸ Пропуски", callback_data="menu:skipped"),
        ],
        [
            InlineKeyboardButton(text="📅 Расписание", callback_data="menu:schedule"),
            InlineKeyboardButton(text="📜 Журнал", callback_data="menu:journal"),
        ],
        [
            InlineKeyboardButton(text="📊 Стата без матча", callback_data="menu:stats_match"),
            InlineKeyboardButton(text="📚 Стата сезонов", callback_data="menu:stats_history"),
        ],
        [
            InlineKeyboardButton(text="🔢 Топ-100 всего", callback_data="menu:top100"),
            InlineKeyboardButton(text="📈 Ещё топы (+ЛЧ)", callback_data="menu:tops_plus"),
            InlineKeyboardButton(text="👥 Голеадоры по клубам", callback_data="menu:tgs_league"),
        ],
        [
            InlineKeyboardButton(
                text="⚽ Состав клуба (схема)",
                callback_data="menu:squad_league",
            ),
        ],
        [
            InlineKeyboardButton(text="🔄 Трансфер", callback_data="xfer:start"),
            InlineKeyboardButton(text="🏅 Награды", callback_data="menu:awards"),
            InlineKeyboardButton(
                text="⭐ Рейтинг (±overall)", callback_data="menu:rating"
            ),
        ],
    ]
    if show_end_season:
        rows.append(
            [
                InlineKeyboardButton(
                    text="⏹ Завершить сезон", callback_data="menu:end_season"
                ),
            ]
        )
    return InlineKeyboardMarkup(inline_keyboard=rows)


async def send_main_menu_screen(
    message: Message,
    *,
    intro_text: str | None = None,
    inline_title: str = "Выберите действие:",
    intro_parse_mode: str | None = None,
) -> None:
    """Два сообщения: нижняя reply-клавиатура и inline-меню (один reply_markup на сообщение)."""
    from bot.season_tools import can_finish_season

    body = intro_text if intro_text is not None else _MENU_ROW_ANCHOR
    await message.answer(
        body,
        reply_markup=reply_keyboard_menu_button(),
        parse_mode=intro_parse_mode,
    )
    end_ok = can_finish_season()
    await message.answer(
        inline_title, reply_markup=main_menu_inline_kb(show_end_season=end_ok)
    )
