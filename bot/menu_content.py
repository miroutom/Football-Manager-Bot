"""Тексты главного меню и /help — общие для handlers и match_router."""
from __future__ import annotations

from aiogram.types import Message

from bot.keyboards import send_main_menu_screen

HELP_HTML = (
    "Кнопки меню или команды:\n"
    "<b>Снизу экрана</b> — «📋 Меню» открывает то же главное меню, что и /menu.\n"
    "<b>Запись матча:</b> «Ручной матч» / «Из пропусков» / «Из календаря»; "
    "«Из календаря» — любой несыгранный слот из mixed_schedule (не отложенный); "
    "команды /match, /play_schedule, /play_skipped.\n"
    "/cancel — отменить ввод счёта, статистики, трансфера или награды.\n"
    "После успешной записи счёта бот может предложить статистику игроков "
    "(если в main.py включён INPUT_PLAYER_STATS).\n"
    "\n"
    "/table — таблица: текущий сезон или архив db/season_n (картинка)\n"
    "/bracket — сетка ЛЧ (картинка)\n"
    "/status — полный статус как в консоли «i» (картинка)\n"
    "/next и /skipped — доступны как команды (в главном меню кнопок нет)\n"
    "/journal — хвост журнала сыгранных\n"
    "/stats_match — стата по сыгранному матчу без статистики (счёт уже в журнале)\n"
    "«🏥 Травмы · жк/кк» — ввод травмы и сводка: травмы, дисквалы (остаток матчей в турнире), жк к 4-й "
    "(лига → клуб → строка <code>имя Nм</code>).\n"
    "/squad_status — пакетно start/bench/reserve по строкам.\n"
    "Полная заявка в БД — «✏️ Изменить игроков» → «В состав / из состава».\n"
    "/transfer — трансферный дашборд: окно, квоты in/out, НО/СО/СУ/НУ, покупка/продажа\n"
    "/transfer_advice — рекомендации по составу клуба (НО/СО/СУ/НУ; стата и трофеи в этом клубе)\n"
    "/awards — награда сезона (как в меню: мяч, бутса, перчатка, Golden Boy; +1 в БД и common)\n"
    "/menu — главное меню\n"
    "\n"
    "В меню: 📅 Расписание — календарь по чемпионату (все/ЛЧ/…) и срезу сим/игра; 📚 Стата сезонов — *_synced.db и архив "
    "db/season_n; топ-100; 👥 голеадоры по клубам — сначала сезон (текущий или архив), "
    "затем лига и клуб.\n"
    "ЛЧ нокаут: при ничьей в финале или по сумме двух матчей бот спросит серию пенальти (два числа).\n"
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
