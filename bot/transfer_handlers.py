"""Ввод трансфера игрока или свободного агента через Telegram (FSM)."""
from __future__ import annotations

import logging
import re

from aiogram import F, Router
from aiogram.filters import Command, StateFilter
from aiogram.fsm.context import FSMContext
from aiogram.types import (
    CallbackQuery,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    Message,
)

from bot.states import TransferEnter
from bot.transfer_storage import (
    append_transfer,
    get_transfer_shortcut,
    save_transfer_shortcut,
)
from utils.transfer_input import (
    normalize_display_name,
    normalize_nation,
    normalize_position,
    resolve_team_name,
    validate_batch_parts,
)

logger = logging.getLogger(__name__)

transfer_router = Router()

_TEXT_NOT_CMD = F.text & ~F.text.startswith("/")

_RE_OVERALL = re.compile(r"^\s*(\d{1,2})\s*$")

_SKIP_VALUE = frozenset({"", "-", "—"})

# Сколько игроков на одной странице клавиатуры (Telegram — много коротких рядов).
_ROSTER_PAGE_SIZE = 12

_TRANSFER_BATCH_MAX = 5
_RE_BATCH_DEST = re.compile(r"^(.+?)\s+([1-5])\s*$")
_RE_PLAN_CLUB = re.compile(r"^(.+?)\s+(\d+)\s*$")


def _team_name_as_in_db(team: str) -> str:
    if (team or "").strip().casefold() == "цска":
        return "Цска"
    return (team or "").strip()


def _league_roster_tuples(team: str) -> list[tuple[str, str, int, str]]:
    """Ростер клуба из нац. БД: имя, позиция, overall, team как в строке БД."""
    from data.defender import Defender
    from data.forward import Forward
    from data.goalkeeper import Goalkeeper
    from data.midfielder import Midfielder
    from utils.player_transfer import _filter_team
    from utils.utils import session_league

    resolved = resolve_team_name(team, session_league)
    t = resolved if resolved else _team_name_as_in_db(team.strip())
    out: list[tuple[str, str, int, str]] = []
    for Cls in (Forward, Midfielder, Defender, Goalkeeper):
        for r in session_league.query(Cls).filter(_filter_team(Cls, t)).all():
            nm = (r.name or "").strip()
            pos = (r.position or "").strip()
            db_team = (r.team or "").strip()
            if not nm:
                continue
            out.append((nm, pos, int(r.overall or 0), db_team))
    out.sort(key=lambda x: (-x[2], x[0].lower()))
    return out


def _roster_keyboard(
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
            [InlineKeyboardButton(text=label, callback_data=f"xfer:pk:{gidx}")]
        )
    if total_pages > 1:
        nav: list[InlineKeyboardButton] = []
        if page > 0:
            nav.append(
                InlineKeyboardButton(
                    text=f"« {page}/{total_pages}",
                    callback_data=f"xfer:pg:{page - 1}",
                )
            )
        if page < total_pages - 1:
            nav.append(
                InlineKeyboardButton(
                    text=f"{page + 2}/{total_pages} »",
                    callback_data=f"xfer:pg:{page + 1}",
                )
            )
        if nav:
            rows.append(nav)
    return InlineKeyboardMarkup(inline_keyboard=rows)


def _shortcut_markup(user_id: int | None) -> InlineKeyboardMarkup | None:
    sc = get_transfer_shortcut(user_id)
    if not sc:
        return None
    f, t = sc["from"], sc["to"]
    label = f"🔁 {f} → {t}"
    if len(label) > 58:
        label = label[:55] + "…"
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text=label, callback_data="xfer:sc:both")]
        ]
    )


def _batch_plan_kind_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="Из другого клуба", callback_data="xfer:bp:club"
                ),
            ],
            [
                InlineKeyboardButton(
                    text="Свободный агент", callback_data="xfer:bp:fa"
                ),
            ],
        ]
    )


def _segments_flatten(
    segments: list[dict],
) -> list[dict]:
    ops: list[dict] = []
    for seg in segments:
        if seg["kind"] == "club":
            for _ in range(int(seg["n"])):
                ops.append({"kind": "club", "from": seg["club"]})
        else:
            for _ in range(int(seg["n"])):
                ops.append({"kind": "fa"})
    return ops


async def _begin_next_batch_op(message: Message, state: FSMContext) -> None:
    """Начать текущий слот пакета (или завершить пакет)."""
    data = await state.get_data()
    ops: list[dict] = data.get("tr_batch_ops") or []
    idx = int(data.get("tr_batch_op_idx") or 0)
    to_t = (data.get("tr_batch_to") or "").strip()
    total_slots = len(ops)
    if not ops or idx >= total_slots:
        await state.clear()
        await message.answer(
            "✓ Пакет трансферов <b>завершён</b>.", parse_mode="HTML"
        )
        return
    op = ops[idx]
    n_slot = idx + 1
    await state.update_data(
        tr_to=to_t,
        tr_batch_active=True,
        tr_meta_patch={},
        tr_kind=op["kind"],
        tr_roster_ui=(op["kind"] == "club"),
    )
    if op["kind"] == "club":
        from_c = op["from"]
        rows = _league_roster_tuples(from_c)
        if not rows:
            await message.answer(
                f"Нет состава для клуба «{from_c}» в нац. лиге — прервано.\n"
                "Начни снова с /transfer.",
                parse_mode="HTML",
            )
            await state.clear()
            return
        canonical_from = rows[0][3] or from_c
        serial = [list(x) for x in rows]
        await state.update_data(
            tr_candidates=serial,
            tr_from=canonical_from,
            tr_roster_page=0,
            tr_player="",
            tr_pos="",
        )
        await state.set_state(TransferEnter.pick_player)
        cands = [tuple(x) for x in serial]
        kb = _roster_keyboard(cands, 0)
        await message.answer(
            f"Трансфер <b>{n_slot}/{total_slots}</b> (из клуба).\n"
            f"<b>Откуда:</b> {canonical_from} → <b>куда:</b> {to_t}\n"
            f"В базе <b>{len(cands)}</b> игрок(ов). Выбери игрока кнопками.\n"
            f"/cancel — отменить только этот трансфер и начать слот заново.",
            parse_mode="HTML",
            reply_markup=kb,
        )
        return
    await state.update_data(tr_player="", tr_pos="", tr_kind="fa")
    await state.set_state(TransferEnter.player_name)
    await message.answer(
        f"Трансфер <b>{n_slot}/{total_slots}</b> — <b>свободный агент</b>.\n"
        f"Куда: <b>{to_t}</b>.\nВведи <b>имя</b> игрока.\n"
        f"/cancel — отменить только этот трансфер.",
        parse_mode="HTML",
    )


async def _prompt_batch_plan_kind(message: Message, state: FSMContext) -> None:
    data = await state.get_data()
    total = int(data.get("tr_batch_total") or 0)
    segments: list[dict] = data.get("tr_batch_segments") or []
    used = sum(int(s["n"]) for s in segments)
    remaining = total - used
    await state.set_state(TransferEnter.batch_plan_kind)
    await message.answer(
        f"Куда: <b>{data.get('tr_batch_to')}</b>, всего трансферов: <b>{total}</b>.\n"
        f"Уже распределено: <b>{used}</b>, осталось распределить: <b>{remaining}</b>.\n\n"
        f"Выбери источник следующей <b>группы</b> трансферов:\n"
        f"• <b>Из клуба</b> — затем введи строку вида «Торино 2» (клуб и число).\n"
        f"• <b>Свободный агент</b> — затем введи одно число (сколько агентов подряд).\n"
        f"Сумма по всем группам должна дать ровно <b>{total}</b> (максимум {_TRANSFER_BATCH_MAX}).\n"
        f"/cancel — отменить весь пакет.",
        parse_mode="HTML",
        reply_markup=_batch_plan_kind_keyboard(),
    )


@transfer_router.callback_query(F.data == "xfer:sc:both")
async def cb_transfer_shortcut_repeat(callback: CallbackQuery, state: FSMContext) -> None:
    uid = callback.from_user.id if callback.from_user else None
    sc = get_transfer_shortcut(uid)
    if not sc:
        await callback.answer(
            "Нет сохранённой связки. Один раз пройди трансфер до конца.", show_alert=True
        )
        return
    if not callback.message:
        await callback.answer()
        return
    from_t, to_t = sc["from"], sc["to"]
    rows = _league_roster_tuples(from_t)
    if not rows:
        await callback.answer()
        await callback.message.answer(
            f"В нац. лиге не нашёл состав для «{from_t}». Введи клуб откуда текстом.",
            parse_mode="HTML",
        )
        return
    canonical_from = rows[0][3] or from_t
    serial = [list(x) for x in rows]
    await state.update_data(
        tr_kind="club",
        tr_candidates=serial,
        tr_from=canonical_from,
        tr_to=to_t,
        tr_roster_page=0,
        tr_roster_ui=True,
        tr_meta_patch={},
    )
    await state.set_state(TransferEnter.pick_player)
    cands = [tuple(x) for x in serial]
    n = len(cands)
    kb = _roster_keyboard(cands, 0)
    await callback.answer()
    await callback.message.answer(
        f"🔁 <b>Откуда:</b> {canonical_from}\n<b>Куда:</b> {to_t}\n\n"
        f"В базе <b>{n}</b> игрок(ов). Шаг 2/6 — <b>выбери игрока</b>.\n/cancel — отмена.",
        parse_mode="HTML",
        reply_markup=kb,
    )


def _kind_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="Из другого клуба", callback_data="xfer:kind:club"
                ),
            ],
            [
                InlineKeyboardButton(
                    text="Свободный агент (новый игрок)", callback_data="xfer:kind:fa"
                ),
            ],
        ]
    )


def _legacy_entry_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="Одиночный трансфер (пошагово)",
                    callback_data="xfer:legacy:start",
                ),
            ],
        ]
    )


@transfer_router.callback_query(F.data == "xfer:legacy:start")
async def cb_transfer_legacy_start(callback: CallbackQuery, state: FSMContext) -> None:
    await callback.answer()
    if not callback.message:
        return
    await state.set_state(TransferEnter.player_name)
    await state.update_data(
        tr_kind="",
        tr_roster_ui=False,
        tr_meta_patch={},
        tr_batch_active=False,
        tr_batch_ops=None,
    )
    await callback.message.answer(
        "Одиночный режим — как раньше.\n"
        "Выбери тип кнопками или введи <b>имя</b> игрока (трансфер из клуба).\n"
        "/cancel — отмена.",
        parse_mode="HTML",
        reply_markup=_kind_keyboard(),
    )


def _status_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="▶ Старт (11)", callback_data="xfer:st:start"
                ),
                InlineKeyboardButton(
                    text="Скамейка", callback_data="xfer:st:bench"
                ),
            ],
            [
                InlineKeyboardButton(
                    text="Резерв", callback_data="xfer:st:reserve"
                ),
            ],
        ]
    )


@transfer_router.callback_query(F.data == "xfer:start")
async def cb_transfer_start(callback: CallbackQuery, state: FSMContext) -> None:
    await callback.answer()
    if not callback.message:
        return
    await state.set_state(TransferEnter.batch_to_count)
    await state.update_data(tr_meta_patch={})
    await callback.message.answer(
        "🔄 <b>Пакет трансферов</b>\n\n"
        "Шаг 1 — введи в одном сообщении: <b>клуб, куда идут трансферы</b>, и "
        f"<b>число трансферов</b> (1–{_TRANSFER_BATCH_MAX}) через пробел.\n"
        "Пример: <code>Крылья Советов 3</code> или <code>урал 5</code>\n\n"
        "<b>Одиночный режим</b> (без пакета): выбери кнопку ниже или введи имя игрока "
        "как раньше после выбора типа.\n"
        "/cancel — отмена.",
        parse_mode="HTML",
        reply_markup=_legacy_entry_keyboard(),
    )


@transfer_router.callback_query(F.data.startswith("xfer:kind:"))
async def cb_transfer_kind(callback: CallbackQuery, state: FSMContext) -> None:
    kind = (callback.data or "").rsplit(":", 1)[-1]
    if kind not in ("club", "fa"):
        return
    await callback.answer()
    if not callback.message:
        return
    if kind == "club":
        await state.set_state(TransferEnter.from_club)
        await state.update_data(tr_kind=kind, tr_roster_ui=False, tr_meta_patch={})
        uid = callback.from_user.id if callback.from_user else None
        sk = _shortcut_markup(uid)
        await callback.message.answer(
            "Тип: <b>трансфер из клуба</b>.\n\n"
            "Шаг 1/6 — введи <b>клуб откуда</b> (как в БД, например «Рома»).\n"
            "Потом выберешь игрока кнопками.\n"
            "Или нажми кнопку ниже — последняя пара «откуда → куда» из прошлого трансфера.\n"
            "/cancel — отмена.",
            parse_mode="HTML",
            reply_markup=sk,
        )
        return

    await state.set_state(TransferEnter.player_name)
    await state.update_data(tr_kind=kind, tr_roster_ui=False, tr_meta_patch={})
    await callback.message.answer(
        "Тип: <b>свободный агент</b> (новая строка в БД).\n\n"
        "Шаг 1/6 — <b>имя игрока</b>.\n/cancel — отмена.",
        parse_mode="HTML",
    )


@transfer_router.message(Command("transfer"))
async def cmd_transfer(message: Message, state: FSMContext) -> None:
    await state.set_state(TransferEnter.batch_to_count)
    await state.update_data(tr_meta_patch={})
    await message.answer(
        "🔄 <b>Пакет трансферов</b>\n\n"
        "Шаг 1 — в одной строке: <b>клуб назначения</b> и <b>число трансферов</b> (1–"
        f"{_TRANSFER_BATCH_MAX}) через пробел.\n"
        "Пример: <code>Урал 5</code>\n\n"
        "Потом распределишь трансферы по источникам (из клубов / св. агенты); "
        "сумма по группам должна совпасть с числом.\n\n"
        "<b>Одиночный режим:</b> кнопка ниже.\n"
        "/cancel — отмена.",
        parse_mode="HTML",
        reply_markup=_legacy_entry_keyboard(),
    )


@transfer_router.message(TransferEnter.batch_to_count, _TEXT_NOT_CMD)
async def on_batch_to_and_count(message: Message, state: FSMContext) -> None:
    raw = (message.text or "").strip()
    m = _RE_BATCH_DEST.match(raw)
    if not m:
        await message.answer(
            f"Нужна строка вида: <code>Клуб 3</code> — название и число 1–{_TRANSFER_BATCH_MAX} через пробел.",
            parse_mode="HTML",
        )
        return
    dest_raw = m.group(1).strip()
    n_total = int(m.group(2))
    from utils.utils import session_league

    to_res = resolve_team_name(dest_raw, session_league)
    to_t = to_res if to_res else _team_name_as_in_db(dest_raw)
    rows_probe = _league_roster_tuples(to_t)
    if not rows_probe:
        await message.answer(
            f"Клуб «{to_t}» в нац. лиге не найден. Проверь название.\n"
            f"Регистр не важен — строка приводится к виду из базы.",
            parse_mode="HTML",
        )
        return
    canon_to = rows_probe[0][3] or to_t
    await state.update_data(
        tr_batch_to=canon_to,
        tr_batch_total=n_total,
        tr_batch_segments=[],
        tr_batch_ops=None,
        tr_batch_op_idx=0,
        tr_batch_active=False,
    )
    await _prompt_batch_plan_kind(message, state)


@transfer_router.callback_query(
    TransferEnter.batch_plan_kind,
    F.data.startswith("xfer:bp:"),
)
async def cb_batch_plan_pick_source(callback: CallbackQuery, state: FSMContext) -> None:
    await callback.answer()
    if not callback.message or not callback.data:
        return
    kind_bp = (callback.data or "").rsplit(":", 1)[-1]
    if kind_bp not in ("club", "fa"):
        return
    data = await state.get_data()
    total = int(data.get("tr_batch_total") or 0)
    segments: list[dict] = list(data.get("tr_batch_segments") or [])
    used = sum(int(s["n"]) for s in segments)
    remaining = total - used
    if remaining <= 0:
        await callback.message.answer("Уже распределено полное число трансферов.")
        return
    if kind_bp == "club":
        await state.set_state(TransferEnter.batch_plan_club)
        await callback.message.answer(
            f"Осталось распределить: <b>{remaining}</b>.\n"
            f"Введи строку: <b>клуб откуда</b> и <b>число</b> через пробел "
            f"(число от 1 до {remaining}).\n"
            f"Пример: <code>торино 2</code>\n/cancel — отменить весь пакет.",
            parse_mode="HTML",
        )
        return
    await state.set_state(TransferEnter.batch_plan_fa)
    await callback.message.answer(
        f"Осталось распределить: <b>{remaining}</b>.\n"
        f"Введи <b>одно число</b> — сколько подряд свободных агентов "
        f"(от 1 до {remaining}).\n/cancel — отменить весь пакет.",
        parse_mode="HTML",
    )


@transfer_router.message(TransferEnter.batch_plan_club, _TEXT_NOT_CMD)
async def on_batch_plan_club(message: Message, state: FSMContext) -> None:
    raw = (message.text or "").strip()
    m = _RE_PLAN_CLUB.match(raw)
    if not m:
        await message.answer(
            "Формат: «Клуб 2» — название клуба и число через пробел.", parse_mode="HTML"
        )
        return
    club_raw = m.group(1).strip()
    n = int(m.group(2))
    data = await state.get_data()
    total = int(data.get("tr_batch_total") or 0)
    segments: list[dict] = list(data.get("tr_batch_segments") or [])
    used = sum(int(s["n"]) for s in segments)
    remaining = total - used
    if n < 1 or n > remaining:
        await message.answer(
            f"Число должно быть от 1 до {remaining} (остаток плана)."
        )
        return
    from utils.utils import session_league

    canon = resolve_team_name(club_raw, session_league)
    club_fin = canon if canon else _team_name_as_in_db(club_raw)
    probe = _league_roster_tuples(club_fin)
    if not probe:
        await message.answer(
            f"Клуб «{club_fin}» не найден в нац. лиге. Попробуй другое написание.",
            parse_mode="HTML",
        )
        return
    club_db = probe[0][3] or club_fin
    segments.append({"kind": "club", "club": club_db, "n": n})
    await state.update_data(tr_batch_segments=segments)
    used2 = sum(int(s["n"]) for s in segments)
    if used2 < total:
        await _prompt_batch_plan_kind(message, state)
        return
    ok, err = validate_batch_parts(total, [int(s["n"]) for s in segments])
    if not ok:
        await message.answer(err or "Ошибка суммы.")
        return
    ops = _segments_flatten(segments)
    await state.update_data(tr_batch_ops=ops, tr_batch_op_idx=0)
    await _begin_next_batch_op(message, state)


@transfer_router.message(TransferEnter.batch_plan_fa, _TEXT_NOT_CMD)
async def on_batch_plan_fa(message: Message, state: FSMContext) -> None:
    raw = (message.text or "").strip()
    if not raw.isdigit():
        await message.answer("Введи одно число — сколько свободных агентов подряд.")
        return
    n = int(raw)
    data = await state.get_data()
    total = int(data.get("tr_batch_total") or 0)
    segments: list[dict] = list(data.get("tr_batch_segments") or [])
    used = sum(int(s["n"]) for s in segments)
    remaining = total - used
    if n < 1 or n > remaining:
        await message.answer(f"Число от 1 до {remaining}.")
        return
    segments.append({"kind": "fa", "n": n})
    await state.update_data(tr_batch_segments=segments)
    used2 = sum(int(s["n"]) for s in segments)
    if used2 < total:
        await _prompt_batch_plan_kind(message, state)
        return
    ok, err = validate_batch_parts(total, [int(s["n"]) for s in segments])
    if not ok:
        await message.answer(err or "Ошибка суммы.")
        return
    ops = _segments_flatten(segments)
    await state.update_data(tr_batch_ops=ops, tr_batch_op_idx=0)
    await _begin_next_batch_op(message, state)


@transfer_router.message(TransferEnter.from_club, _TEXT_NOT_CMD)
async def on_transfer_from_club(message: Message, state: FSMContext) -> None:
    raw = (message.text or "").strip()
    if len(raw) < 2:
        await message.answer("Введи название клуба (как в БД).")
        return
    rows = _league_roster_tuples(raw)
    if not rows:
        await message.answer(
            "В <b>нац. лиге</b> никого не нашёл с таким клубом. "
            "Проверь написание (как в игре, например «Цска» вместо ЦСКА).\n"
            "Попробуй ещё раз или /cancel.",
            parse_mode="HTML",
        )
        return
    canonical_from = rows[0][3] or raw
    serial = [list(x) for x in rows]
    await state.update_data(
        tr_candidates=serial,
        tr_from=canonical_from,
        tr_roster_page=0,
        tr_roster_ui=True,
    )
    await state.set_state(TransferEnter.pick_player)
    cands = [tuple(x) for x in serial]
    n = len(cands)
    kb = _roster_keyboard(cands, 0)
    await message.answer(
        f"Клуб: <b>{canonical_from}</b> — в базе <b>{n}</b> игрок(ов).\n"
        f"Шаг 2/6 — <b>выбери игрока</b> (ниже кнопки; при длинном списке — листание).\n"
        f"/cancel — отмена.",
        parse_mode="HTML",
        reply_markup=kb,
    )


@transfer_router.callback_query(TransferEnter.pick_player, F.data.startswith("xfer:pg:"))
async def cb_transfer_roster_page(callback: CallbackQuery, state: FSMContext) -> None:
    if not callback.message or not callback.data:
        return
    try:
        page = int((callback.data or "").rsplit(":", 1)[-1])
    except ValueError:
        await callback.answer()
        return
    data = await state.get_data()
    raw = data.get("tr_candidates") or []
    cands = [tuple(x) for x in raw]
    if not cands:
        await callback.answer("Сессия устарела. Начни с /transfer.", show_alert=True)
        return
    await state.update_data(tr_roster_page=page)
    ps = _ROSTER_PAGE_SIZE
    total_pages = max(1, (len(cands) + ps - 1) // ps)
    page = max(0, min(page, total_pages - 1))
    try:
        await callback.message.edit_reply_markup(
            reply_markup=_roster_keyboard(cands, page),
        )
    except Exception:
        await callback.message.answer(
            f"Стр. {page + 1}/{total_pages} — выбери игрока:",
            reply_markup=_roster_keyboard(cands, page),
        )
    await callback.answer()


@transfer_router.callback_query(TransferEnter.pick_player, F.data.startswith("xfer:pk:"))
async def cb_transfer_pick_player(callback: CallbackQuery, state: FSMContext) -> None:
    if not callback.message or not callback.data:
        return
    try:
        idx = int((callback.data or "").rsplit(":", 1)[-1])
    except ValueError:
        await callback.answer()
        return
    data = await state.get_data()
    raw = data.get("tr_candidates") or []
    cands = [tuple(x) for x in raw]
    if not cands or idx < 0 or idx >= len(cands):
        await callback.answer("Неверный выбор. Начни с /transfer.", show_alert=True)
        return
    name, pos, _ov, from_t = cands[idx]
    data_prev = await state.get_data()
    preset_to = (data_prev.get("tr_to") or "").strip()
    batch_on = bool(data_prev.get("tr_batch_active"))
    await state.update_data(tr_player=name, tr_pos=pos, tr_from=from_t, tr_roster_ui=True)
    await callback.answer()
    if preset_to or batch_on:
        await state.set_state(TransferEnter.xfer_optional_overall)
        try:
            await callback.message.edit_text(
                f"Выбрано: <b>{name}</b> ({pos})\n"
                f"Откуда: <b>{from_t}</b> → куда: <b>{preset_to}</b> (как в быстром маршруте)\n\n"
                f"Шаг 4/6 — новый <b>overall</b> (1–99) или <code>-</code>, чтобы не менять.\n"
                f"/cancel — отмена.",
                parse_mode="HTML",
                reply_markup=None,
            )
        except Exception:
            await callback.message.answer(
                f"Выбрано: <b>{name}</b> ({pos}). Куда: <b>{preset_to}</b>.\n\n"
                f"Шаг 4/6 — <b>overall</b> или <code>-</code>.\n/cancel — отмена.",
                parse_mode="HTML",
            )
        return
    await state.set_state(TransferEnter.to_team)
    try:
        await callback.message.edit_text(
            f"Выбрано: <b>{name}</b> ({pos})\n"
            f"Откуда: <b>{from_t}</b>\n\n"
            f"Шаг 3/6 — введи клуб <b>куда</b> переходит игрок.\n/cancel — отмена.",
            parse_mode="HTML",
            reply_markup=None,
        )
    except Exception:
        await callback.message.answer(
            f"Выбрано: <b>{name}</b> ({pos}), откуда: <b>{from_t}</b>.\n\n"
            f"Шаг 3/6 — клуб <b>куда</b>.\n/cancel — отмена.",
            parse_mode="HTML",
        )


@transfer_router.message(TransferEnter.player_name, _TEXT_NOT_CMD)
async def on_transfer_player(message: Message, state: FSMContext) -> None:
    name = normalize_display_name(message.text or "")
    if len(name) < 2:
        await message.answer("Слишком коротко. Введи имя игрока.")
        return
    data = await state.get_data()
    kind = (data.get("tr_kind") or "").strip()
    if not kind:
        # по умолчанию — трансфер из клуба
        kind = "club"
        await state.update_data(tr_kind="club", tr_roster_ui=False)
    await state.update_data(tr_player=name)
    if kind == "fa":
        await state.set_state(TransferEnter.position)
        await message.answer(
            f"Шаг 2/6 — <b>позиция</b> (ЦН, ЦП, ЦЗ, ВР…).\n"
            f"Игрок: «{name}»\n/cancel — отмена.",
            parse_mode="HTML",
        )
        return
    await state.set_state(TransferEnter.from_team)
    await message.answer(
        f"Шаг 2/7 — команда, <b>откуда</b> уходит игрок:\n"
        f"«{name}»\n\n/cancel — отмена.",
        parse_mode="HTML",
    )


@transfer_router.message(TransferEnter.from_team, _TEXT_NOT_CMD)
async def on_transfer_from(message: Message, state: FSMContext) -> None:
    raw_t = (message.text or "").strip()
    if len(raw_t) < 2:
        await message.answer("Введи название клуба.")
        return
    from utils.utils import session_league

    resolved = resolve_team_name(raw_t, session_league)
    team = resolved if resolved else _team_name_as_in_db(raw_t)
    await state.update_data(tr_from=team)
    await state.set_state(TransferEnter.position)
    await message.answer(
        "Шаг 3/7 — <b>позиция</b> (например ЦН, ЦП, ЦЗ, ВР…).\n/cancel — отмена.",
        parse_mode="HTML",
    )


@transfer_router.message(TransferEnter.position, _TEXT_NOT_CMD)
async def on_transfer_position(message: Message, state: FSMContext) -> None:
    pos = normalize_position(message.text or "")
    if len(pos) < 1:
        await message.answer("Введи позицию.")
        return
    await state.update_data(tr_pos=pos)
    data = await state.get_data()
    kind = data.get("tr_kind")
    if (
        kind == "fa"
        and data.get("tr_batch_active")
        and (data.get("tr_to") or "").strip()
    ):
        await state.set_state(TransferEnter.fa_overall)
        await message.answer(
            f"Шаг — <b>overall</b> (<code>1–99</code>).\n"
            f"Игрок: «{data.get('tr_player')}», куда: <b>{data.get('tr_to')}</b>.\n"
            f"/cancel — отмена только этого трансфера.",
            parse_mode="HTML",
        )
        return
    await state.set_state(TransferEnter.to_team)
    if kind == "fa":
        step = "3/6"
    else:
        step = "4/7"
    await message.answer(
        f"Шаг {step} — команда, <b>куда</b> переходит игрок.\n/cancel — отмена.",
        parse_mode="HTML",
    )


@transfer_router.message(TransferEnter.to_team, _TEXT_NOT_CMD)
async def on_transfer_to(message: Message, state: FSMContext) -> None:
    raw_t = (message.text or "").strip()
    if len(raw_t) < 2:
        await message.answer("Введи название клуба.")
        return
    from utils.utils import session_league

    resolved = resolve_team_name(raw_t, session_league)
    to_t = resolved if resolved else _team_name_as_in_db(raw_t)
    await state.update_data(tr_to=to_t, tr_meta_patch={})
    data = await state.get_data()
    if data.get("tr_kind") == "fa":
        await state.set_state(TransferEnter.fa_overall)
        await message.answer(
            "Шаг 4/6 — <b>overall</b> (число <code>1–99</code>, например <code>72</code>).\n"
            "/cancel — отмена.",
            parse_mode="HTML",
        )
        return
    await state.set_state(TransferEnter.xfer_optional_overall)
    roster = bool(data.get("tr_roster_ui"))
    step_ov = "4/6" if roster else "5/7"
    await message.answer(
        f"Шаг {step_ov} — новый <b>overall</b> в базе: число <b>1–99</b> или "
        "<code>-</code>, чтобы не менять значение из базы.\n\n"
        "/cancel — отмена.",
        parse_mode="HTML",
    )


@transfer_router.message(TransferEnter.xfer_optional_overall, _TEXT_NOT_CMD)
async def on_xfer_optional_overall(message: Message, state: FSMContext) -> None:
    raw = (message.text or "").strip()
    meta = (await state.get_data()).get("tr_meta_patch") or {}
    if raw not in _SKIP_VALUE:
        m = _RE_OVERALL.match(raw)
        if not m:
            await message.answer("Введи число 1–99 или -.")
            return
        o = int(m.group(1))
        if o < 1 or o > 99:
            await message.answer("Диапазон 1–99.")
            return
        meta["overall"] = o
    await state.update_data(tr_meta_patch=meta)
    await state.set_state(TransferEnter.xfer_optional_nation)
    data = await state.get_data()
    roster = bool(data.get("tr_roster_ui"))
    step_nat = "5/6" if roster else "6/7"
    await message.answer(
        f"Шаг {step_nat} — <b>нация</b> в базе (как в игре, например «Бразилия») или "
        "<code>-</code>, чтобы не менять.\n\n"
        "/cancel — отмена.",
        parse_mode="HTML",
    )


@transfer_router.message(TransferEnter.xfer_optional_nation, _TEXT_NOT_CMD)
async def on_xfer_optional_nation(message: Message, state: FSMContext) -> None:
    raw = (message.text or "").strip()
    meta = (await state.get_data()).get("tr_meta_patch") or {}
    if raw not in _SKIP_VALUE:
        meta["nation"] = normalize_nation(raw)
    await state.update_data(tr_meta_patch=meta)
    await state.set_state(TransferEnter.new_status)
    data = await state.get_data()
    roster = bool(data.get("tr_roster_ui"))
    step_st = "6/6" if roster else "7/7"
    await message.answer(
        f"Шаг {step_st} — <b>заявка</b> в новом клубе (старт / скамейка / резерв). "
        "Правила: <b>старт</b> — среди игроков с этой позицией и заявкой «старт» остаются лучшие по рейтингу "
        "(например, до двух центральных защитников); остальные на скамейку; затем худший на скамейке → резерв; "
        "<b>скамейка</b> — худший на скамейке (если больше одного) → резерв; "
        "<b>резерв</b> — только в резерв.\n"
        "/cancel — отмена.",
        parse_mode="HTML",
        reply_markup=_status_keyboard(),
    )


@transfer_router.message(TransferEnter.fa_overall, _TEXT_NOT_CMD)
async def on_fa_overall(message: Message, state: FSMContext) -> None:
    raw = (message.text or "").strip()
    m = _RE_OVERALL.match(raw)
    if not m:
        await message.answer("Введи одно число 1–99, например 72.")
        return
    o = int(m.group(1))
    if o < 1 or o > 99:
        await message.answer("Диапазон 1–99.")
        return
    await state.update_data(tr_overall=o)
    await state.set_state(TransferEnter.fa_nation)
    await message.answer(
        "Шаг 5/6 — <b>нация</b> (как в игре, например «Бразилия») или "
        "<code>-</code>, если поле оставить пустым.\n"
        "/cancel — отмена.",
        parse_mode="HTML",
    )


@transfer_router.message(TransferEnter.fa_nation, _TEXT_NOT_CMD)
async def on_fa_nation(message: Message, state: FSMContext) -> None:
    raw = (message.text or "").strip()
    if raw in _SKIP_VALUE:
        nation = None
    else:
        nation = normalize_nation(raw)
    await state.update_data(tr_fa_nation=nation)
    await state.set_state(TransferEnter.new_status)
    await message.answer(
        "Шаг 6/6 — <b>заявка</b> (старт / скамейка / резерв).\n/cancel — отмена.",
        parse_mode="HTML",
        reply_markup=_status_keyboard(),
    )


@transfer_router.callback_query(TransferEnter.new_status, F.data.startswith("xfer:st:"))
async def on_transfer_status(
    callback: CallbackQuery, state: FSMContext
) -> None:
    st = (callback.data or "").rsplit(":", 1)[-1]
    if st not in ("start", "bench", "reserve"):
        return
    await callback.answer()
    if not callback.message:
        return
    data = await state.get_data()
    player = data.get("tr_player", "")
    pos = data.get("tr_pos", "")
    to_t = data.get("tr_to", "")
    kind = data.get("tr_kind")
    uid = callback.from_user.id if callback.from_user else None

    if kind == "fa":
        ovr = int(data.get("tr_overall") or 72)
        nation_fa = data.get("tr_fa_nation")
        try:
            from utils.player_transfer import add_free_agent

            counts = add_free_agent(
                player=player,
                position=pos,
                to_team=to_t,
                new_status=st,
                overall=ovr,
                nation=nation_fa,
            )
        except Exception as e:
            logger.exception("add_free_agent")
            await callback.message.answer(f"Не удалось обновить базы: {e}")
            return
        try:
            append_transfer(
                user_id=uid,
                player=player,
                from_team="(свободный агент)",
                position=pos,
                to_team=to_t,
                new_status=st,
                free_agent=True,
                overall=ovr,
                nation=nation_fa,
            )
        except Exception as e:
            logger.exception("transfer_save")
            await callback.message.answer(
                f"Базы обновлены, но журнал не записан: {e}",
            )
            if not data.get("tr_batch_active"):
                await state.clear()
            return
        batch_active = bool(data.get("tr_batch_active"))
        lines = [
            "✓ <b>Свободный агент</b> добавлен.",
            f"БД: нац. — <b>{counts['league']}</b>, ЛЧ — <b>{counts['cl']}</b>.",
            f"Overall: <b>{ovr}</b>, заявка: <b>{st}</b>.",
        ]
        if nation_fa:
            lines.append(f"Нация: <b>{nation_fa}</b>.")
        lines.extend(
            [
                "",
                f"<b>{player}</b> ({pos}) → {to_t}",
                "Журнал: <code>data/transfers.json</code>",
            ]
        )
        await callback.message.answer("\n".join(lines), parse_mode="HTML")
        if batch_active:
            idx = int(data.get("tr_batch_op_idx") or 0)
            await state.update_data(tr_batch_op_idx=idx + 1)
            await _begin_next_batch_op(callback.message, state)
            return
        await state.clear()
        return

    from_t = data.get("tr_from", "")
    meta = data.get("tr_meta_patch") or {}
    new_ov = meta.get("overall")
    nation_update = "nation" in meta
    nat_val = meta.get("nation") if nation_update else None
    try:
        from utils.player_transfer import apply_transfer_with_status

        counts = apply_transfer_with_status(
            player=player,
            from_team=from_t,
            position=pos,
            to_team=to_t,
            new_status=st,
            new_overall=new_ov,
            nation_update=nation_update,
            new_nation=nat_val,
        )
    except Exception as e:
        logger.exception("transfer_apply")
        await callback.message.answer(f"Не удалось обновить базы: {e}")
        return
    try:
        append_transfer(
            user_id=uid,
            player=player,
            from_team=from_t,
            position=pos,
            to_team=to_t,
            new_status=st,
            free_agent=False,
        )
    except Exception as e:
        logger.exception("transfer_save")
        await callback.message.answer(
            f"Базы обновлены, но журнал transfers.json не записан: {e}",
        )
        if not data.get("tr_batch_active"):
            save_transfer_shortcut(uid, from_t, to_t)
            await state.clear()
        return

    batch_active = bool(data.get("tr_batch_active"))
    if not batch_active:
        save_transfer_shortcut(uid, from_t, to_t)
    n_db = counts.get("league", 0) + counts.get("cl", 0)
    warn = ""
    if n_db == 0:
        warn = (
            "⚠️ В нац. БД и ЛЧ строк не найдено "
            "(проверь имя, клуб «откуда» и позицию как в базе).\n\n"
        )
    lines = [
        warn,
        f"✓ БД: нац. — <b>{counts['league']}</b>, ЛЧ — <b>{counts['cl']}</b>. "
        "<code>common.db</code> пересобран.",
        "",
    ]
    if new_ov is not None or nation_update:
        bits = []
        if new_ov is not None:
            bits.append(f"overall → <b>{new_ov}</b>")
        if nation_update:
            bits.append(f"нация → <b>{nat_val or '—'}</b>")
        lines.append("Обновлено в строке: " + ", ".join(bits))
        lines.append("")
    lines.extend(
        [
            f"Заявка: <b>{st}</b>",
            "Журнал: <code>data/transfers.json</code>",
            "",
            f"<b>{player}</b> ({pos})",
            f"{from_t} → {to_t}",
        ]
    )
    await callback.message.answer("\n".join(lines), parse_mode="HTML")
    if batch_active:
        idx = int(data.get("tr_batch_op_idx") or 0)
        await state.update_data(tr_batch_op_idx=idx + 1)
        await _begin_next_batch_op(callback.message, state)
        return
    await state.clear()


@transfer_router.message(Command("cancel"), StateFilter(TransferEnter))
async def cmd_cancel_transfer_fsm(message: Message, state: FSMContext) -> None:
    cur = await state.get_state()
    cs = str(cur or "")
    data = await state.get_data()
    if cs.startswith("TransferEnter:batch_"):
        await state.clear()
        await message.answer("Пакет трансферов отменён.")
        return
    if data.get("tr_batch_active"):
        await _begin_next_batch_op(message, state)
        await message.answer(
            "Отменён только текущий трансфер — повтори шаги для этого слота.",
            parse_mode="HTML",
        )
        return
    await state.clear()
    await message.answer("Трансфер отменён.")
