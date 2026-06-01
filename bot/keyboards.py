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
# Первое сообщение только с reply-клавиатурой «Меню» — короткий видимый текст (Telegram не любит «пустые»).
_MENU_REPLY_ONLY_BODY = "·"


def edit_players_submenu_kb() -> InlineKeyboardMarkup:
    """Подменю из пункта «Изменить игроков» главного меню."""
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="⭐ Рейтинг (±overall)",
                    callback_data="menu:rating",
                ),
            ],
            [
                InlineKeyboardButton(
                    text="✏️ Изменить игрока (любое поле)",
                    callback_data="menu:player_field",
                ),
            ],
            [
                InlineKeyboardButton(
                    text="👥 В состав / из состава",
                    callback_data="menu:squad_roster",
                ),
            ],
            [
                InlineKeyboardButton(
                    text="📅 Аренда",
                    callback_data="menu:loan",
                ),
            ],
        ]
    )


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
                text="✏️ Ручной матч",
                callback_data="play:manual",
            ),
            InlineKeyboardButton(
                text="📌 Из пропусков",
                callback_data="skip:list",
            ),
        ],
        [
            InlineKeyboardButton(
                text="📋 Из календаря",
                callback_data="play:schedule",
            ),
            InlineKeyboardButton(text="📊 Таблица", callback_data="menu:table"),
        ],
        [
            InlineKeyboardButton(text="📜 История", callback_data="menu:history"),
        ],
        [
            InlineKeyboardButton(text="🏟 Сетка ЛЧ", callback_data="menu:bracket"),
            InlineKeyboardButton(text="📌 Статус", callback_data="menu:status"),
        ],
        [
            InlineKeyboardButton(text="📅 Расписание", callback_data="menu:schedule"),
            InlineKeyboardButton(text="📜 Журнал", callback_data="menu:journal"),
        ],
        [
            InlineKeyboardButton(
                text="🏥 Травмы · жк/кк",
                callback_data="menu:injury",
            ),
        ],
        [
            InlineKeyboardButton(text="📊 Стата без матча", callback_data="menu:stats_match"),
            InlineKeyboardButton(text="📚 Стата сезонов", callback_data="menu:stats_history"),
        ],
        [
            InlineKeyboardButton(text="🔢 Топ-100 всего", callback_data="menu:top100"),
            InlineKeyboardButton(text="👥 Голеадоры по клубам", callback_data="menu:tgs_league"),
        ],
        [
            InlineKeyboardButton(
                text="⚽ Схема",
                callback_data="menu:squad_league",
            ),
        ],
        [
            InlineKeyboardButton(
                text="👤 Сменить тренера",
                callback_data="menu:coach_team",
            ),
            InlineKeyboardButton(
                text="📐 Схема (активная)",
                callback_data="menu:formation_pick",
            ),
        ],
        [
            InlineKeyboardButton(text="🔄 Трансфер", callback_data="xfer:start"),
            InlineKeyboardButton(text="🏅 Награды", callback_data="menu:awards"),
            InlineKeyboardButton(
                text="✏️ Изменить игроков",
                callback_data="menu:edit_players",
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

    body = intro_text if intro_text is not None else _MENU_REPLY_ONLY_BODY
    await message.answer(
        body,
        reply_markup=reply_keyboard_menu_button(),
        parse_mode=intro_parse_mode,
    )
    end_ok = can_finish_season()
    await message.answer(
        inline_title, reply_markup=main_menu_inline_kb(show_end_season=end_ok)
    )
