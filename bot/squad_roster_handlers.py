"""Добавление / исключение игрока в составе клуба (лига → клуб → …)."""
from __future__ import annotations

import asyncio
import logging
import re
from html import escape as html_escape

from aiogram import F, Router
from aiogram.fsm.context import FSMContext
from aiogram.types import (
    CallbackQuery,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    Message,
)

from bot.services import LEAGUE_LABELS, split_text_chunks, teams_ordered_for_goalscorers
from bot.states import SquadRosterEnter
from bot.transfer_handlers import _ROSTER_PAGE_SIZE, _league_roster_tuples
from utils.roster_manual import (
    FREE_AGENT_TEAM,
    apply_team_squad_declaration,
    build_squad_declaration_template_from_db,
    parse_squad_declaration_text,
)
from utils.transfer_input import normalize_display_name, normalize_position

logger = logging.getLogger(__name__)

squad_roster_router = Router()


async def _ensure_squad_roster_fsm(callback: CallbackQuery, state: FSMContext) -> bool:
    """Есть активная сессия «В состав / из состава» и сообщение для ответа."""
    cur = await state.get_state()
    if cur is None or not str(cur).startswith("SquadRosterEnter"):
        await callback.answer(
            "Сессия сброшена. Снова: «Изменить игроков» → «В состав / из состава».",
            show_alert=True,
        )
        return False
    if callback.message is None:
        await callback.answer("Сообщение недоступно.", show_alert=True)
        return False
    return True

_TEXT_NOT_CMD = F.text & ~F.text.startswith("/")

_RE_SQR_LG = re.compile(r"^sqr:lg:([a-z0-9_]+)$")
_RE_SQR_TM = re.compile(r"^sqr:tm:([a-z0-9_]+):(\d+)$")


def _league_title(code: str) -> str:
    return dict(LEAGUE_LABELS).get(code, code)


def _club_btn_label(text: str, max_chars: int = 40) -> str:
    text = (text or "").strip()
    if len(text) <= max_chars:
        return text
    return text[: max_chars - 1] + "…"


def _sqr_league_kb() -> InlineKeyboardMarkup:
    row: list[InlineKeyboardButton] = []
    rows: list[list[InlineKeyboardButton]] = []
    for code, label in LEAGUE_LABELS:
        row.append(InlineKeyboardButton(text=label, callback_data=f"sqr:lg:{code}"))
        if len(row) == 3:
            rows.append(row)
            row = []
    if row:
        rows.append(row)
    return InlineKeyboardMarkup(inline_keyboard=rows)


def _sqr_teams_kb(league_code: str) -> InlineKeyboardMarkup:
    teams = teams_ordered_for_goalscorers(league_code)
    rows: list[list[InlineKeyboardButton]] = []
    row: list[InlineKeyboardButton] = []
    for idx, team in enumerate(teams):
        row.append(
            InlineKeyboardButton(
                text=_club_btn_label(team),
                callback_data=f"sqr:tm:{league_code}:{idx}",
            )
        )
        if len(row) == 2:
            rows.append(row)
            row = []
    if row:
        rows.append(row)
    return InlineKeyboardMarkup(inline_keyboard=rows)


def _sqr_roster_kb(
    candidates: list[tuple[str, str, int, str]], page: int
) -> InlineKeyboardMarkup:
    n = len(candidates)
    ps = _ROSTER_PAGE_SIZE
    total_pages = max(1, (n + ps - 1) // ps)
    page = max(0, min(int(page), total_pages - 1))
    chunk = candidates[page * ps : page * ps + ps]
    base = page * ps
    rows: list[list[InlineKeyboardButton]] = []
    for i, (nm, pos, ov, _dbt) in enumerate(chunk):
        gidx = base + i
        label = f"{nm} · {pos} · {ov}"
        if len(label) > 60:
            label = label[:57] + "…"
        rows.append(
            [InlineKeyboardButton(text=label, callback_data=f"sqr:rp:{gidx}")]
        )
    if total_pages > 1:
        nav: list[InlineKeyboardButton] = []
        if page > 0:
            nav.append(
                InlineKeyboardButton(
                    text=f"« {page + 1}/{total_pages}",
                    callback_data=f"sqr:rpg:{page - 1}",
                )
            )
        if page < total_pages - 1:
            nav.append(
                InlineKeyboardButton(
                    text=f"{page + 2}/{total_pages} »",
                    callback_data=f"sqr:rpg:{page + 1}",
                )
            )
        if nav:
            rows.append(nav)
    return InlineKeyboardMarkup(inline_keyboard=rows)


def _sqr_choice_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="📋 Полная заявка (текстом)",
                    callback_data="sqr:do:set_squad",
                ),
            ],
            [
                InlineKeyboardButton(
                    text="➕ Один игрок в состав", callback_data="sqr:do:add"
                ),
            ],
            [
                InlineKeyboardButton(
                    text="➖ Один из состава", callback_data="sqr:do:rm"
                ),
            ],
        ]
    )


def _sqr_status_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="▶ Старт (11)", callback_data="sqr:st:start"
                ),
                InlineKeyboardButton(text="Скамейка", callback_data="sqr:st:bench"),
            ],
            [
                InlineKeyboardButton(text="Резерв", callback_data="sqr:st:reserve"),
            ],
        ]
    )


@squad_roster_router.callback_query(F.data == "menu:squad_roster")
async def cb_menu_squad_roster(callback: CallbackQuery, state: FSMContext) -> None:
    await callback.answer()
    if callback.message is None:
        return
    await state.clear()
    await state.set_state(SquadRosterEnter.pick_lg)
    await callback.message.answer(
        "👥 <b>В состав / из состава</b>\n\n"
        "Выбери лигу и клуб.\n"
        "<b>Полная заявка:</b> черновик из нац. БД (start/bench/reserve); "
        "одним сообщением — то же для ЛЧ у клубов из пула участников (отдельно в ЛЧ не нужно).\n"
        "Кто <b>не</b> в списке, уходит в СА.\n"
        "<b>Один игрок:</b> если есть в <code>common_synced.db</code> — достаточно имени и позиции; "
        "иначе overall и нация.\n"
        f"При статистике клуб в БД станет «{FREE_AGENT_TEAM}».\n"
        "/cancel — отмена.",
        parse_mode="HTML",
        reply_markup=_sqr_league_kb(),
    )


@squad_roster_router.callback_query(F.data.regexp(_RE_SQR_LG))
async def cb_sqr_league(callback: CallbackQuery, state: FSMContext) -> None:
    m = _RE_SQR_LG.match(callback.data or "")
    if not m:
        await callback.answer()
        return
    if not await _ensure_squad_roster_fsm(callback, state):
        return
    code = m.group(1)
    await callback.answer()
    await state.update_data(sqr_lg=code)
    await state.set_state(SquadRosterEnter.pick_team)
    await callback.message.answer(
        f"{_league_title(code)} — выберите клуб:",
        reply_markup=_sqr_teams_kb(code),
    )


@squad_roster_router.callback_query(F.data.regexp(_RE_SQR_TM))
async def cb_sqr_team(callback: CallbackQuery, state: FSMContext) -> None:
    m = _RE_SQR_TM.match(callback.data or "")
    if not m:
        await callback.answer()
        return
    if not await _ensure_squad_roster_fsm(callback, state):
        return
    code, idx_s = m.group(1), m.group(2)
    try:
        idx = int(idx_s)
    except ValueError:
        await callback.answer()
        return
    await callback.answer()
    try:
        teams = teams_ordered_for_goalscorers(code)
        team = teams[idx]
    except (IndexError, Exception) as e:
        await callback.message.answer(f"Клуб: ошибка: {e}")
        return
    rows = _league_roster_tuples(team)
    canonical = (rows[0][3] or team) if rows else team
    await state.update_data(sqr_team=canonical, sqr_lg=code)
    await state.set_state(SquadRosterEnter.pick_choice)
    await callback.message.answer(
        f"<b>{_league_title(code)}</b> · <b>{canonical}</b>\n\nЧто сделать?",
        parse_mode="HTML",
        reply_markup=_sqr_choice_kb(),
    )


@squad_roster_router.callback_query(
    SquadRosterEnter.pick_choice, F.data == "sqr:do:set_squad"
)
async def cb_sqr_set_squad(callback: CallbackQuery, state: FSMContext) -> None:
    await callback.answer()
    if not callback.message:
        return
    data = await state.get_data()
    team = (data.get("sqr_team") or "").strip()
    if not team:
        await callback.message.answer("Нет клуба в сессии. Начни с меню.")
        return
    try:
        template_blob = await asyncio.to_thread(
            build_squad_declaration_template_from_db, team
        )
    except Exception as e:
        logger.exception("build_squad_declaration_template_from_db")
        await callback.message.answer(f"Не удалось собрать состав из БД: {e}")
        return

    await state.set_state(SquadRosterEnter.wait_paste_squad)
    more_parts = ""
    chunks = split_text_chunks(template_blob, 3500)
    if len(chunks) > 1:
        more_parts = (
            f"Заявка на <b>{len(chunks)}</b> сообщений — скопируй все части подряд "
            "в редактор, поправь и пришли <b>одним</b> сообщением.\n\n"
        )
    await callback.message.answer(
        "Ниже — <b>черновик заявки</b> из нац. БД (секции "
        "<code>==== start ===</code>, <code>=== bench ===</code>, "
        "<code>=== reserve ===</code>). После отправки одним сообщением заявка "
        "применится и к нац. базе, и к ЛЧ (если клуб в актуальном пуле участников).\n"
        "Формат строки: <code>имя позиция overall нация</code> "
        "(нацию/overall можно опустить для игроков из common).\n\n"
        + more_parts
        + "Кого <b>нет</b> в тексте при отправке — уйдут в свободные агенты.\n\n"
        "<b>По-прежнему можно</b> без секций: последнее слово "
        "<code>start</code>/<code>bench</code>/<code>reserve</code>, "
        "или строки через <code>|</code>.\n"
        "/cancel — отмена.",
        parse_mode="HTML",
    )
    for j, chunk in enumerate(chunks):
        prefix = f"📋 {j + 1}/{len(chunks)}\n" if len(chunks) > 1 else ""
        await callback.message.answer(
            f"<pre>{html_escape(prefix + chunk)}</pre>",
            parse_mode="HTML",
        )


@squad_roster_router.message(SquadRosterEnter.wait_paste_squad, _TEXT_NOT_CMD)
async def on_sqr_paste_squad(message: Message, state: FSMContext) -> None:
    data = await state.get_data()
    team = (data.get("sqr_team") or "").strip()
    if not team:
        await state.clear()
        await message.answer("Сессия сброшена. Начни с меню.")
        return
    entries, p_errors = parse_squad_declaration_text(message.text or "")
    if p_errors:
        await message.answer(
            "Ошибки разбора:\n" + "\n".join(p_errors[:30])
            + ("\n…" if len(p_errors) > 30 else ""),
            parse_mode="HTML",
        )
        return
    if not entries:
        await message.answer("Нет ни одной строки заявки (пусто или только комментарии).")
        return
    try:
        r = await asyncio.to_thread(apply_team_squad_declaration, team, entries)
    except Exception as e:
        logger.exception("apply_team_squad_declaration")
        await message.answer(f"Ошибка применения: {e}")
        return
    await state.clear()
    det = r.get("released_detail") or []
    det_tail = "\n".join(det[:15]) if det else ""
    more = f"\n… ещё {len(det) - 15}" if len(det) > 15 else ""
    cl_note = ""
    if r.get("cl_pool"):
        cl_note = "\nЛЧ: заявка синхронизирована (<code>champions_league_new.db</code>)."
    await message.answer(
        f"✅ Клуб <b>{r['team']}</b>\n"
        f"В заявке: <b>{r['declared']}</b> игроков.\n"
        f"Снято в СА: <b>{r['released']}</b>.\n"
        + cl_note
        + (f"<pre>{det_tail}{more}</pre>" if det_tail else "")
        + "\n<code>common.db</code> / накопительные БД обновлены по режиму сезона.",
        parse_mode="HTML",
    )


@squad_roster_router.callback_query(SquadRosterEnter.pick_choice, F.data == "sqr:do:rm")
async def cb_sqr_choice_remove(callback: CallbackQuery, state: FSMContext) -> None:
    await callback.answer()
    if not callback.message:
        return
    data = await state.get_data()
    team = (data.get("sqr_team") or "").strip()
    rows = _league_roster_tuples(team)
    if not rows:
        await callback.message.answer("Состав пуст.")
        await state.clear()
        return
    serial = [list(x) for x in rows]
    await state.update_data(sqr_rm_candidates=serial, sqr_rm_page=0)
    await state.set_state(SquadRosterEnter.pick_rm)
    cands = [tuple(x) for x in serial]
    await callback.message.answer(
        "Выбери игрока для <b>исключения</b> из состава:",
        parse_mode="HTML",
        reply_markup=_sqr_roster_kb(cands, 0),
    )


@squad_roster_router.callback_query(SquadRosterEnter.pick_rm, F.data.startswith("sqr:rpg:"))
async def cb_sqr_rm_page(callback: CallbackQuery, state: FSMContext) -> None:
    if not callback.message or not callback.data:
        await callback.answer()
        return
    try:
        page = int((callback.data or "").rsplit(":", 1)[-1])
    except ValueError:
        await callback.answer()
        return
    data = await state.get_data()
    raw = data.get("sqr_rm_candidates") or []
    cands = [tuple(x) for x in raw]
    if not cands:
        await callback.answer("Сессия устарела.", show_alert=True)
        return
    ps = _ROSTER_PAGE_SIZE
    total_pages = max(1, (len(cands) + ps - 1) // ps)
    page = max(0, min(page, total_pages - 1))
    try:
        await callback.message.edit_reply_markup(reply_markup=_sqr_roster_kb(cands, page))
    except Exception:
        await callback.message.answer(
            f"Стр. {page + 1}/{total_pages}:",
            reply_markup=_sqr_roster_kb(cands, page),
        )
    await callback.answer()


@squad_roster_router.callback_query(SquadRosterEnter.pick_rm, F.data.startswith("sqr:rp:"))
async def cb_sqr_rm_pick(callback: CallbackQuery, state: FSMContext) -> None:
    if not callback.message or not callback.data:
        await callback.answer()
        return
    try:
        idx = int((callback.data or "").rsplit(":", 1)[-1])
    except ValueError:
        await callback.answer()
        return
    data = await state.get_data()
    team = (data.get("sqr_team") or "").strip()
    raw = data.get("sqr_rm_candidates") or []
    cands = [tuple(x) for x in raw]
    if not cands or idx < 0 or idx >= len(cands):
        await callback.answer("Неверный выбор.", show_alert=True)
        return
    name, pos, _ov, _t = cands[idx]
    await callback.answer()
    try:
        r = await asyncio.to_thread(
            __import__("utils.roster_manual", fromlist=["remove_player_from_team_roster"]).remove_player_from_team_roster,
            team,
            name,
            pos,
        )
    except Exception as e:
        logger.exception("remove_player_from_team_roster")
        await callback.message.answer(f"Ошибка: {e}")
        return
    await state.clear()
    await callback.message.answer(
        f"✅ Игрок <b>{name}</b> ({pos}) — клуб «{team}».\n"
        f"Результат: <code>{r.get('removed_as')}</code>.\n"
        "Справочник <code>free_agents.db</code> обновлён; нац./ЛЧ/common пересобраны.",
        parse_mode="HTML",
    )


@squad_roster_router.callback_query(SquadRosterEnter.pick_choice, F.data == "sqr:do:add")
async def cb_sqr_choice_add(callback: CallbackQuery, state: FSMContext) -> None:
    await callback.answer()
    if not callback.message:
        return
    await state.set_state(SquadRosterEnter.add_name)
    await callback.message.answer(
        "Введи <b>имя игрока</b> (как в заявке / common).\n/cancel — отмена.",
        parse_mode="HTML",
    )


@squad_roster_router.message(SquadRosterEnter.add_name, _TEXT_NOT_CMD)
async def on_sqr_add_name(message: Message, state: FSMContext) -> None:
    name = normalize_display_name(message.text or "")
    if len(name) < 2:
        await message.answer("Слишком коротко.")
        return
    await state.update_data(sqr_add_name=name)
    await state.set_state(SquadRosterEnter.add_pos)
    await message.answer(
        "Введи <b>позицию</b> (ЦП, ЦЗ, ФРВ, ВРТ…).\n/cancel — отмена.",
        parse_mode="HTML",
    )


@squad_roster_router.message(SquadRosterEnter.add_pos, _TEXT_NOT_CMD)
async def on_sqr_add_pos(message: Message, state: FSMContext) -> None:
    pos = normalize_position(message.text or "")
    if not pos:
        await message.answer("Нужна позиция.")
        return
    await state.update_data(sqr_add_pos=pos)
    await state.set_state(SquadRosterEnter.add_ovr)
    await message.answer(
        "Введи <b>overall</b> (1–99), если игрока <b>нет</b> в common_synced.\n"
        "Если он там есть — отправь <code>-</code>.\n/cancel — отмена.",
        parse_mode="HTML",
    )


@squad_roster_router.message(SquadRosterEnter.add_ovr, _TEXT_NOT_CMD)
async def on_sqr_add_ovr(message: Message, state: FSMContext) -> None:
    raw = (message.text or "").strip()
    ovr: int | None = None
    if raw not in ("", "-", "—"):
        if not raw.isdigit():
            await message.answer("Число 1–99 или «-».")
            return
        ovr = int(raw)
        if ovr < 1 or ovr > 99:
            await message.answer("Диапазон 1–99.")
            return
    await state.update_data(sqr_add_ovr=ovr)
    await state.set_state(SquadRosterEnter.add_nat)
    await message.answer(
        "Введи <b>нацию</b> (как в игре) или <code>-</code>, если игрок уже в common "
        "и нацию не меняем / пусто.\n/cancel — отмена.",
        parse_mode="HTML",
    )


@squad_roster_router.message(SquadRosterEnter.add_nat, _TEXT_NOT_CMD)
async def on_sqr_add_nat(message: Message, state: FSMContext) -> None:
    raw = (message.text or "").strip()
    nat = None if raw in ("", "-", "—") else raw
    await state.update_data(sqr_add_nat=nat)
    await state.set_state(SquadRosterEnter.wait_status_add)
    await message.answer(
        "Выбери <b>заявку</b> в клубе для добавляемого игрока.\n/cancel — отмена.",
        parse_mode="HTML",
        reply_markup=_sqr_status_kb(),
    )


@squad_roster_router.callback_query(
    SquadRosterEnter.wait_status_add, F.data.startswith("sqr:st:")
)
async def on_sqr_add_status(callback: CallbackQuery, state: FSMContext) -> None:
    st = (callback.data or "").rsplit(":", 1)[-1]
    if st not in ("start", "bench", "reserve"):
        return
    await callback.answer()
    if not callback.message:
        return
    data = await state.get_data()
    team = (data.get("sqr_team") or "").strip()
    name = (data.get("sqr_add_name") or "").strip()
    pos = (data.get("sqr_add_pos") or "").strip()
    ovr = data.get("sqr_add_ovr")
    nat = data.get("sqr_add_nat")
    if not (team and name and pos):
        await state.clear()
        await callback.message.answer("Сессия сброшена.")
        return
    try:
        r = await asyncio.to_thread(
            __import__("utils.roster_manual", fromlist=["add_player_to_team_roster"]).add_player_to_team_roster,
            team,
            name,
            pos,
            overall=ovr,
            nation=nat,
            status=st,
        )
    except Exception as e:
        logger.exception("add_player_to_team_roster")
        await callback.message.answer(f"Ошибка: {e}")
        return
    await state.clear()
    await callback.message.answer(
        f"✅ Игрок <b>{r['player']}</b> ({r['position']}) добавлен в <b>{r['team']}</b>, "
        f"overall <b>{r['overall']}</b>.\n"
        "Накопительные *_synced обновлены (если не legacy).",
        parse_mode="HTML",
    )
