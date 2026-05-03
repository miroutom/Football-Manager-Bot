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
    """Пакет трансферов или одиночный режим; заявка start/bench/reserve."""
    batch_to_count = State()  # клуб «куда» + число трансферов (1–5)
    batch_plan_kind = State()  # выбор: из клуба / св. агент (пока не набран план)
    batch_plan_club = State()  # строка «Клуб N» для очередного блока из клуба
    batch_plan_fa = State()  # число свободных агентов в блоке
    player_name = State()
    from_club = State()  # «из клуба»: сначала клуб → кнопки игроков
    pick_player = State()
    from_team = State()  # только «из клуба» (ввод имени вручную: шаг «откуда»)
    position = State()
    to_team = State()
    fa_overall = State()  # только св. агент: число overall
    fa_nation = State()  # только св. агент: нация (или -)
    new_status = State()


class AwardEnter(StatesGroup):
    """Награды сезона: после выбора вида, лиги, клуба — ввод имени игрока."""
    wait_name = State()


class RatingEnter(StatesGroup):
    """Правка overall: лига, клуб, многострочный ввод «имя +N / имя -N»."""
    wait_lines = State()


class SquadStatusEnter(StatesGroup):
    """Заявка start/bench/reserve: лига, клуб, строки «имя bench»."""
    wait_lines = State()


class PlayerFieldEnter(StatesGroup):
    """Правка одного поля игрока: лига → клуб → игрок → поле → значение."""
    pick_lg = State()
    pick_team = State()
    pick_player = State()
    pick_field = State()
    wait_value = State()
