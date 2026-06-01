"""Состояния FSM для ввода счёта в Telegram."""
from __future__ import annotations

from aiogram.fsm.state import State, StatesGroup


class MatchEnter(StatesGroup):
    next_score = State()
    manual_cl_phase = State()
    manual_home_pick = State()
    manual_away_pick = State()
    manual_home = State()
    manual_away = State()
    manual_score = State()


class SkipPlay(StatesGroup):
    """Выбор матча из skipped_matches.json и ввод счёта."""
    awaiting_score = State()


class PostMatch(StatesGroup):
    """После записи счёта — предложение ввести статистику игроков."""
    offer_stats = State()
    stats_wait_lines = State()


class AddOnlyStats(StatesGroup):
    """Статистика по уже сыгранному матчу (выбор из календаря, без ввода счёта)."""
    cl_phase = State()
    browsing = State()


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
    sign_overall = State()  # новый игрок: рейтинг
    sign_nation = State()  # новый игрок: нация
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
    confirm_merge = State()


class LoanEnter(StatesGroup):
    """Аренда: лига → клуб → строка «имя позиция overall Nм»."""
    pick_lg = State()
    pick_team = State()
    wait_line = State()


class InjuryEnter(StatesGroup):
    """Травмы: лига → клуб → строка «имя Nм» / «имя сM Nм» / «имя Nм тип»."""
    pick_lg = State()
    pick_team = State()
    wait_line = State()


class SquadRosterEnter(StatesGroup):
    """Добавить / убрать игрока в составе клуба (лига → клуб → действие)."""
    pick_lg = State()
    pick_team = State()
    pick_choice = State()
    wz_pick_start = State()
    wz_pick_bench = State()
    wz_pick_reserve = State()
    wz_edit_pick = State()
    wz_edit_wait_line = State()
    wait_paste_squad = State()
    pick_rm = State()
    wait_bulk_add = State()
    add_name = State()
    add_pos = State()
    add_ovr = State()
    add_nat = State()
    wait_status_add = State()


class MatchPerfRatingEnter(StatesGroup):
    """Ввод оценок за матч: выбор матча → сторона → вставка состава со смайликами."""
    session = State()
    wait_paste = State()
