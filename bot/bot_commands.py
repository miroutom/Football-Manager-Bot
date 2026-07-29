"""Меню команд Telegram (подсказка при вводе «/» в чате с ботом)."""
from __future__ import annotations

from aiogram import Bot
from aiogram.types import BotCommand


async def setup_bot_commands(bot: Bot) -> None:
    await bot.set_my_commands(
        [
            BotCommand(command="start", description="Начало, нижнее меню и кнопки"),
            BotCommand(command="menu", description="Главное меню"),
            BotCommand(command="help", description="Справка по всем действиям"),
            BotCommand(command="cancel", description="Отменить ввод счёта, статы, трансфера, заявки или награды"),
            BotCommand(command="play_next", description="Записать следующий матч по календарю"),
            BotCommand(command="match", description="Записать матч вручную (клубы и счёт)"),
            BotCommand(command="play_skipped", description="Сыграть из списка отложенных"),
            BotCommand(command="play_schedule", description="Выбрать матч из календаря (mixed_schedule)"),
            BotCommand(command="fix_score", description="Исправить счёт уже записанного матча"),
            BotCommand(command="transfer", description="Трансферный дашборд (окно, квоты, НО/СО/СУ/НУ)"),
            BotCommand(command="squad_status", description="Правка заявки start/bench/reserve по строкам"),
            BotCommand(command="awards", description="Награда сезона (+1: мяч, бутса, перчатка, Golden Boy)"),
            BotCommand(command="stats_match", description="Стата по сыгранному матчу из календаря"),
            BotCommand(command="done", description="Закончить ввод статистики после матча"),
            BotCommand(command="table", description="Таблица (картинка)"),
            BotCommand(command="goals", description="Бомбардиры (картинка)"),
            BotCommand(command="assists", description="Ассисты (картинка)"),
            BotCommand(command="ga", description="Голы + передачи (картинка)"),
            BotCommand(command="bracket", description="Сетка ЛЧ (картинка)"),
            BotCommand(command="cl_draw", description="Жребий 1/16 или 1/8 ЛЧ (когда доступен)"),
            BotCommand(command="status", description="Полный статус сезона (картинка)"),
            BotCommand(command="next", description="Следующий матч по календарю"),
            BotCommand(command="skipped", description="Отложенные матчи (просмотр)"),
            BotCommand(command="journal", description="Журнал сыгранных матчей"),
            BotCommand(command="ovr_debug", description="DEBUG: совет OVR по клубу (без записи)"),
        ],
    )
