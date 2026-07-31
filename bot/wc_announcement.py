# -*- coding: utf-8 -*-
"""Автообъявление «Чемпионат мира начался» после финала ЛЧ (конец м.10)."""
from __future__ import annotations

import asyncio
import logging
import random
from html import escape as html_escape

from aiogram.types import BufferedInputFile, InlineKeyboardButton, InlineKeyboardMarkup, Message

logger = logging.getLogger(__name__)

_TAGLINES: tuple[str, ...] = (
    "Финал ЛЧ сыгран — открывается Чемпионат мира!",
    "Клубный сезон закончен. Время сборных!",
    "Мяч на поле, флаги подняты — World Cup!",
    "48 сборных, один кубок. Поехали!",
    "От Лиги чемпионов — к мировому трону.",
    "Сборные выходят на сцену. ЧМ начался!",
)


def _pick_tagline(season: int, host: str) -> str:
    rng = random.Random(season * 7919 + abs(hash(host.casefold())) % 10000)
    return rng.choice(_TAGLINES)


def should_announce_wc_start(
    *,
    ok: bool,
    league_code: str,
    cl_phase: str | None,
    home: str,
    away: str,
) -> bool:
    if not ok or league_code != "cl" or cl_phase != "knockout":
        return False
    from utils.cl_knockout_schedule import _cl_knockout_is_final_match
    from utils import season_paths
    from utils.world_cup import is_world_cup_season

    season = season_paths.get_active_season()
    if not is_world_cup_season(season):
        return False
    if not _cl_knockout_is_final_match(home, away):
        return False
    from utils.wc_branding import is_wc_start_announced

    return not is_wc_start_announced(season)


def build_wc_start_caption(season: int, host: str) -> str:
    tagline = _pick_tagline(season, host)
    host_e = html_escape(host)
    return (
        f"🏆 <b>{html_escape(tagline)}</b>\n\n"
        f"Хозяйка: <b>{host_e}</b> · сезон {int(season)}\n"
        f"Месяц 11 — группы, плей-офф и финал на одном кубке."
    )


def _wc_start_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="🌍 Меню ЧМ", callback_data="menu:wc")],
        ]
    )


async def maybe_announce_world_cup_started(
    message: Message,
    *,
    ok: bool,
    home: str,
    away: str,
    league_code: str,
    cl_phase: str | None = None,
) -> None:
    if not should_announce_wc_start(
        ok=ok,
        league_code=league_code,
        cl_phase=cl_phase,
        home=home,
        away=away,
    ):
        return
    from utils import season_paths
    from utils.wc_branding import ensure_branding, mark_wc_start_announced
    from bot.wc_logo import render_wc_logo_png_bytes

    season = season_paths.get_active_season()
    brand = ensure_branding(season)
    host = str(brand.get("host") or "Host")
    try:
        png = await asyncio.to_thread(
            render_wc_logo_png_bytes, season, branding=brand, use_cache=False
        )
        await message.answer_photo(
            BufferedInputFile(png, filename=f"wc_start_s{season}.png"),
            caption=build_wc_start_caption(season, host),
            parse_mode="HTML",
            reply_markup=_wc_start_kb(),
        )
        mark_wc_start_announced(season)
    except Exception:
        logger.exception("wc start announcement")
