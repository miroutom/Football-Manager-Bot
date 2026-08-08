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
from bot.month_motm_handlers import month_motm_router
from bot.cl_draw_handlers import cl_draw_router
from bot.wc_handlers import wc_router
from bot.rating_handlers import rating_router
from bot.player_edit_handlers import player_edit_router
from bot.squad_roster_handlers import squad_roster_router
from bot.squad_status_handlers import squad_status_router
from bot.history_handlers import history_router
from bot.loan_handlers import loan_router
from bot.injury_handlers import injury_router
from bot.players_position_handlers import players_pos_router
from bot.stats_position_handlers import stats_pos_router
from bot.settings import get_bot_token, get_telegram_proxy
from utils.db_startup import run_startup_schema_migrations
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
)

_log = logging.getLogger(__name__)


async def _migrate_free_agents_background() -> None:
    """Не блокировать polling: перенос FA из league/cl в free_agents.db."""
    try:
        from utils.free_agents_db import ensure_free_agents_db, migrate_free_agents_from_league_dbs

        _log.info("Startup: FA migration (background)…")
        await asyncio.to_thread(ensure_free_agents_db)
        stats = await asyncio.to_thread(migrate_free_agents_from_league_dbs)
        if stats.get("migrated") or stats.get("removed_league"):
            _log.info("Startup: FA migration done: %s", stats)
        else:
            _log.info("Startup: FA migration done (no changes)")
    except Exception:
        _log.exception("Startup: FA migration failed")


async def main() -> None:
    _log.info("Startup: begin")
    try:
        await asyncio.wait_for(
            asyncio.to_thread(run_startup_schema_migrations),
            timeout=120.0,
        )
    except asyncio.TimeoutError:
        _log.exception(
            "Startup: schema migrations timed out after 120s "
            "(проверьте lock на db/season_*/ *.db; можно BOT_SKIP_STARTUP_MIGRATIONS=1)"
        )
        raise
    except Exception:
        _log.exception("Startup: schema migrations failed")
        raise
    _log.info("Startup: schema migrations OK")
    token = get_bot_token()
    _log.info("Startup: TELEGRAM_BOT_TOKEN loaded")
    dp = Dispatcher(storage=MemoryStorage())
    match_router.message.middleware(AccessMiddleware())
    match_router.callback_query.middleware(AccessMiddleware())
    transfer_router.message.middleware(AccessMiddleware())
    transfer_router.callback_query.middleware(AccessMiddleware())
    awards_router.message.middleware(AccessMiddleware())
    awards_router.callback_query.middleware(AccessMiddleware())
    month_motm_router.message.middleware(AccessMiddleware())
    month_motm_router.callback_query.middleware(AccessMiddleware())
    cl_draw_router.message.middleware(AccessMiddleware())
    cl_draw_router.callback_query.middleware(AccessMiddleware())
    wc_router.message.middleware(AccessMiddleware())
    wc_router.callback_query.middleware(AccessMiddleware())
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
    players_pos_router.message.middleware(AccessMiddleware())
    players_pos_router.callback_query.middleware(AccessMiddleware())
    stats_pos_router.message.middleware(AccessMiddleware())
    stats_pos_router.callback_query.middleware(AccessMiddleware())
    season_router.message.middleware(AccessMiddleware())
    season_router.callback_query.middleware(AccessMiddleware())
    router.message.middleware(AccessMiddleware())
    router.callback_query.middleware(AccessMiddleware())
    dp.include_router(match_router)
    dp.include_router(transfer_router)
    dp.include_router(awards_router)
    dp.include_router(month_motm_router)
    dp.include_router(cl_draw_router)
    dp.include_router(wc_router)
    dp.include_router(rating_router)
    dp.include_router(player_edit_router)
    dp.include_router(squad_roster_router)
    dp.include_router(squad_status_router)
    dp.include_router(history_router)
    dp.include_router(loan_router)
    dp.include_router(injury_router)
    dp.include_router(players_pos_router)
    dp.include_router(stats_pos_router)
    dp.include_router(season_router)
    dp.include_router(router)

    bot_props = DefaultBotProperties(parse_mode=ParseMode.HTML)
    proxy = get_telegram_proxy()
    if proxy:
        from aiogram.client.session.aiohttp import AiohttpSession

        # Не логируем credentials из URL прокси.
        proxy_log = proxy.split("@")[-1] if "@" in proxy else proxy
        _log.info("Startup: TELEGRAM_PROXY=%s", proxy_log)
        telegram_bot = Bot(
            token=token,
            session=AiohttpSession(proxy=proxy),
            default=bot_props,
        )
    else:
        telegram_bot = Bot(token=token, default=bot_props)
    dp.startup.register(_migrate_free_agents_background)
    _log.info("Startup: registering routers…")
    try:
        await asyncio.wait_for(setup_bot_commands(telegram_bot), timeout=45.0)
        _log.info("Startup: bot commands registered")
    except Exception:
        _log.exception("Startup: set_my_commands failed (continuing to poll)")
    _log.info("Startup: polling (bot is accepting /start and menu)")
    await dp.start_polling(telegram_bot)


if __name__ == "__main__":
    asyncio.run(main())
