"""Состояния FSM для ввода счёта в Telegram."""
from __future__ import annotations

from aiogram.fsm.state import State, StatesGroup


class MatchEnter(StatesGroup):
    next_score = State()
    manual_cl_phase = State()
    manual_home = State()
    manual_away = State()
    manual_score = State()


class SkipPlay(StatesGroup):
    """Выбор матча из skipped_matches.json и ввод счёта."""
    awaiting_score = State()


class PostMatch(StatesGroup):
    """После записи счёта — предложение ввести статистику игроков."""
    offer_stats = State()
    stats_lines = State()


class AddOnlyStats(StatesGroup):
    """Статистика по матчу без записи счёта через матч-день (как «a» в консоли)."""
    cl_phase = State()
    home = State()
    away = State()
    score = State()


class ClPenalties(StatesGroup):
    """ЛЧ нокаут: ответный матч, ничья по сумме двух матчей — ввод серии пенальти."""
    waiting = State()


class TransferEnter(StatesGroup):
    """Запись трансфера: игрок, клуб-отправитель, позиция, клуб-получатель."""
    player_name = State()
    from_team = State()
    position = State()
    to_team = State()


class AwardEnter(StatesGroup):
    """Награды сезона: после выбора вида, лиги, клуба — ввод имени игрока."""
    wait_name = State()
