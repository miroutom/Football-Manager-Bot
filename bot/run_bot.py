"""Запуск Telegram-бота (long polling). Из корня проекта: python -m bot"""
from __future__ import annotations

import asyncio
import logging

from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.fsm.storage.memory import MemoryStorage

import bot  # noqa: F401 — ensure_project_paths при импорте пакета

from bot.awards_handlers import awards_router
from bot.bot_commands import setup_bot_commands
from bot.handlers import AccessMiddleware, router
from bot.match_handlers import match_router
from bot.transfer_handlers import transfer_router
from bot.settings import get_bot_token
from utils.migrate_player_awards import migrate_player_awards_columns
from utils.migrate_player_status import migrate_all_player_status_columns

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
        await asyncio.to_thread(migrate_player_awards_columns)
    except Exception:
        logging.getLogger(__name__).exception("Миграция наград (колонки golden_*)")
        raise
    token = get_bot_token()
    dp = Dispatcher(storage=MemoryStorage())
    match_router.message.middleware(AccessMiddleware())
    match_router.callback_query.middleware(AccessMiddleware())
    transfer_router.message.middleware(AccessMiddleware())
    transfer_router.callback_query.middleware(AccessMiddleware())
    awards_router.message.middleware(AccessMiddleware())
    awards_router.callback_query.middleware(AccessMiddleware())
    router.message.middleware(AccessMiddleware())
    router.callback_query.middleware(AccessMiddleware())
    dp.include_router(match_router)
    dp.include_router(transfer_router)
    dp.include_router(awards_router)
    dp.include_router(router)

    telegram_bot = Bot(
        token=token,
        default=DefaultBotProperties(parse_mode=ParseMode.HTML),
    )
    await setup_bot_commands(telegram_bot)
    await dp.start_polling(telegram_bot)


if __name__ == "__main__":
    asyncio.run(main())
