"""Тексты главного меню и /help — общие для handlers и match_router."""
from __future__ import annotations

from aiogram.types import Message

from bot.keyboards import send_main_menu_screen

HELP_HTML = (
    "Кнопки меню или команды:\n"
    "<b>Снизу экрана</b> — «📋 Меню» открывает то же главное меню, что и /menu.\n"
    "<b>Запись матча:</b> «Записать следующий» / «Ручной матч» / «Из пропусков»; "
    "команды /play_next, /match, /play_skipped (отложенные из skipped_matches.json).\n"
    "/cancel — отменить ввод счёта, статистики, трансфера или награды.\n"
    "После успешной записи счёта бот может предложить статистику игроков "
    "(если в main.py включён INPUT_PLAYER_STATS).\n"
    "\n"
    "/table — таблица: текущий сезон или архив db/season_n (картинка); "
    "/goals /assists /ga — топы (картинка)\n"
    "/bracket — сетка ЛЧ (картинка)\n"
    "/status — полный статус как в консоли «i» (картинка)\n"
    "/next — информация о следующем матче по календарю\n"
    "/skipped — список отложенных (только просмотр)\n"
    "/journal — хвост журнала сыгранных\n"
    "/stats_match — статистика по матчу без записи через матч-день (как «a»)\n"
    "/transfer — трансфер (5 шагов, в т.ч. start/bench/reserve в новом клубе)\n"
    "/awards — награда сезона (как в меню: мяч, бутса, перчатка, Golden Boy; +1 в БД и common)\n"
    "/menu — главное меню\n"
    "\n"
    "В меню: 📅 Расписание — весь календарь картинками; 📚 Стата сезонов — *_synced.db и архив "
    "db/season_n; топ-100, топы лига+ЛЧ; 👥 голеадоры по клубам — сначала сезон (текущий или архив), "
    "затем лига и клуб.\n"
    "ЛЧ нокаут: при ничьей по сумме двух матчей бот спросит серию пенальти (два числа).\n"
)


async def deliver_help_screen(message: Message) -> None:
    await send_main_menu_screen(
        message,
        intro_text=HELP_HTML,
        inline_title="Выберите действие:",
        intro_parse_mode="HTML",
    )


async def deliver_main_menu_refresh(message: Message) -> None:
    await send_main_menu_screen(message, intro_text=None, inline_title="Главное меню:")
