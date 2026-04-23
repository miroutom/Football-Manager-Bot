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


def reply_keyboard_menu_button() -> ReplyKeyboardMarkup:
    """Нижняя клавиатура — всегда под рукой, без ответа /menu."""
    return ReplyKeyboardMarkup(
        keyboard=[[KeyboardButton(text=MENU_REPLY_TEXT)]],
        resize_keyboard=True,
    )


def main_menu_inline_kb() -> InlineKeyboardMarkup:
    """Главное меню (inline), как раньше в handlers._main_menu_kb."""
    return InlineKeyboardMarkup(
        inline_keyboard=[
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
                InlineKeyboardButton(text="🏟 Сетка ЛЧ (HTML)", callback_data="menu:bracket"),
                InlineKeyboardButton(text="📌 Статус", callback_data="menu:status"),
            ],
            [
                InlineKeyboardButton(text="⏭ След. матч", callback_data="menu:next"),
                InlineKeyboardButton(text="📋 Очередь", callback_data="menu:queue"),
            ],
            [
                InlineKeyboardButton(text="⏸ Пропуски", callback_data="menu:skipped"),
                InlineKeyboardButton(text="📜 Журнал", callback_data="menu:journal"),
            ],
            [
                InlineKeyboardButton(text="📅 Расписание", callback_data="menu:schedule"),
                InlineKeyboardButton(text="📊 Стата без матча", callback_data="menu:stats_match"),
            ],
            [
                InlineKeyboardButton(text="🔢 Топ-100 всего", callback_data="menu:top100"),
                InlineKeyboardButton(text="📈 Ещё топы (+ЛЧ)", callback_data="menu:tops_plus"),
            ],
            [
                InlineKeyboardButton(text="👥 Голеадоры по клубам", callback_data="menu:tgs_league"),
            ],
            [
                InlineKeyboardButton(text="🔄 Трансфер", callback_data="xfer:start"),
            ],
        ]
    )


async def send_main_menu_screen(
    message: Message,
    *,
    intro_text: str | None = None,
    inline_title: str = "Выберите действие:",
    intro_parse_mode: str | None = None,
) -> None:
    """Два сообщения: нижняя reply-клавиатура и inline-меню (один reply_markup на сообщение)."""
    body = intro_text if intro_text is not None else "\u200b"
    await message.answer(
        body,
        reply_markup=reply_keyboard_menu_button(),
        parse_mode=intro_parse_mode,
    )
    await message.answer(inline_title, reply_markup=main_menu_inline_kb())
