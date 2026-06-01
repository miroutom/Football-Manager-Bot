"""Запуск Telegram-бота (long polling). Из корня проекта: python -m bot"""
from __future__ import annotations

import asyncio
import logging

from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.fsm.storage.memory import MemoryStorage

import bot  # noqa: F401 — ensure_project_paths при импорте пакета

from bot.season_handlers import season_router
from bot.bot_commands import setup_bot_commands
from bot.handlers import AccessMiddleware, router
from bot.match_handlers import match_router
from bot.transfer_handlers import transfer_router
from bot.awards_handlers import awards_router
from bot.rating_handlers import rating_router
from bot.player_edit_handlers import player_edit_router
from bot.squad_roster_handlers import squad_roster_router
from bot.squad_status_handlers import squad_status_router
from bot.history_handlers import history_router
from bot.loan_handlers import loan_router
from bot.injury_handlers import injury_router
from bot.settings import get_bot_token
from utils.migrate_player_discipline import migrate_all_player_discipline_columns
from utils.migrate_player_awards import migrate_player_awards_columns
from utils.migrate_player_status import migrate_all_player_status_columns
from utils.migrate_player_left_team import migrate_all_player_left_team_columns
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
)


async def main() -> None:
    try:
        await asyncio.to_thread(migrate_all_player_status_columns)
    except Exception:
        logging.getLogger(__name__).exception(
            "Не удалось применить миграции SQLite (колонка status и др.)"
        )
        raise
    try:
        await asyncio.to_thread(migrate_all_player_left_team_columns)
    except Exception:
        logging.getLogger(__name__).exception(
            "Не удалось применить миграции SQLite (колонка left_team)"
        )
        raise
    try:
        await asyncio.to_thread(migrate_all_player_discipline_columns)
    except Exception:
        logging.getLogger(__name__).exception(
            "Не удалось применить миграции дисциплины (жк/кк)"
        )
        raise
    try:
        await asyncio.to_thread(migrate_player_awards_columns)
    except Exception:
        logging.getLogger(__name__).exception(
            "Не удалось применить миграции наград (golden_boots, golden_boys, …)"
        )
        raise
    token = get_bot_token()
    dp = Dispatcher(storage=MemoryStorage())
    match_router.message.middleware(AccessMiddleware())
    match_router.callback_query.middleware(AccessMiddleware())
    transfer_router.message.middleware(AccessMiddleware())
    transfer_router.callback_query.middleware(AccessMiddleware())
    awards_router.message.middleware(AccessMiddleware())
    awards_router.callback_query.middleware(AccessMiddleware())
    rating_router.message.middleware(AccessMiddleware())
    rating_router.callback_query.middleware(AccessMiddleware())
    player_edit_router.message.middleware(AccessMiddleware())
    player_edit_router.callback_query.middleware(AccessMiddleware())
    squad_roster_router.message.middleware(AccessMiddleware())
    squad_roster_router.callback_query.middleware(AccessMiddleware())
    squad_status_router.message.middleware(AccessMiddleware())
    squad_status_router.callback_query.middleware(AccessMiddleware())
    history_router.message.middleware(AccessMiddleware())
    history_router.callback_query.middleware(AccessMiddleware())
    loan_router.message.middleware(AccessMiddleware())
    loan_router.callback_query.middleware(AccessMiddleware())
    injury_router.message.middleware(AccessMiddleware())
    injury_router.callback_query.middleware(AccessMiddleware())
    season_router.message.middleware(AccessMiddleware())
    season_router.callback_query.middleware(AccessMiddleware())
    router.message.middleware(AccessMiddleware())
    router.callback_query.middleware(AccessMiddleware())
    dp.include_router(transfer_router)
    dp.include_router(match_router)
    dp.include_router(awards_router)
    dp.include_router(rating_router)
    dp.include_router(player_edit_router)
    dp.include_router(squad_roster_router)
    dp.include_router(squad_status_router)
    dp.include_router(history_router)
    dp.include_router(loan_router)
    dp.include_router(injury_router)
    dp.include_router(season_router)
    dp.include_router(router)

    telegram_bot = Bot(
        token=token,
        default=DefaultBotProperties(parse_mode=ParseMode.HTML),
    )
    await setup_bot_commands(telegram_bot)
    await dp.start_polling(telegram_bot)


if __name__ == "__main__":
    asyncio.run(main())
