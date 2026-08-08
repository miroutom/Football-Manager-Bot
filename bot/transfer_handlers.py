# -*- coding: utf-8 -*-
"""Загрузка трансферного окна в бота: два файла → apply к БД."""
from __future__ import annotations

import asyncio
import io
import json
import logging
from html import escape as html_escape

from aiogram import F, Router
from aiogram.filters import Command, StateFilter
from aiogram.fsm.context import FSMContext
from aiogram.types import (
    CallbackQuery,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    Message,
)

from bot.states import TransferUpload

logger = logging.getLogger(__name__)

transfer_router = Router()

_TEXT_NOT_CMD = F.text & ~F.text.startswith("/")
_DOC = F.document


class _TransferApplyProgress:
    """Живой счётчик + полоса прогресса (apply в worker thread → edit через event loop)."""

    _SPINNERS = ("⠋", "⠙", "⠹", "⠸", "⠼", "⠴", "⠦", "⠧", "⠇", "⠏")

    def __init__(self, message: Message, loop: asyncio.AbstractEventLoop) -> None:
        self._message = message
        self._loop = loop
        self._started = __import__("time").monotonic()
        self._last_edit = 0.0
        self._last_done = -1
        self._last_phase = ""
        self._snapshot: tuple[int, int, str, str | None, int, int] = (0, 1, "", None, 0, 0)
        self._heartbeat_on = False
        self._heartbeat_task: asyncio.Task | None = None

    @staticmethod
    def _bar_with_pct(pct: int, width: int = 22) -> str:
        pct = max(0, min(100, int(pct)))
        filled = round(width * pct / 100)
        bar = "█" * filled + "░" * (width - filled)
        return f"[{bar}] {pct:3d}%"

    def _format(
        self,
        done: int,
        total: int,
        phase: str,
        detail: str | None,
        phase_done: int,
        phase_total: int,
        *,
        spinner: str = "",
    ) -> str:
        pct = int(100 * done / total) if total else 0
        elapsed = int(__import__("time").monotonic() - self._started)
        mins, secs = divmod(elapsed, 60)
        head = f"{spinner} <b>Применяю трансферы и составы</b>" if spinner else "<b>Применяю трансферы и составы</b>"
        lines = [
            head,
            f"<pre>{self._bar_with_pct(pct)}</pre>",
            f"Шагов: <b>{done}</b> / {total}",
        ]
        if phase_total > 0:
            lines.append(f"{html_escape(phase)}: <b>{phase_done}</b> / {phase_total}")
        elif phase:
            lines.append(html_escape(phase))
        if detail:
            lines.append(f"↳ <i>{html_escape(detail[:120])}</i>")
        lines.append(f"⏱ {mins}:{secs:02d}")
        return "\n".join(lines)

    def __call__(
        self,
        done: int,
        total: int,
        phase: str,
        detail: str | None,
        phase_done: int = 0,
        phase_total: int = 0,
    ) -> None:
        import time

        if total <= 0:
            return
        self._snapshot = (done, total, phase, detail, phase_done, phase_total)
        now = time.monotonic()
        phase_changed = phase != self._last_phase
        jumped = done - self._last_done
        finished = done >= total
        long_step = phase == "common.db" and detail and "пересборка" in (detail or "")

        if long_step and not self._heartbeat_on:
            self._heartbeat_on = True
            asyncio.run_coroutine_threadsafe(self._heartbeat(), self._loop)
        if finished:
            self._heartbeat_on = False

        force = finished or phase_changed or jumped >= 2 or long_step
        if not force and (now - self._last_edit) < 0.85:
            return
        self._last_edit = now
        self._last_done = done
        self._last_phase = phase
        text = self._format(done, total, phase, detail, phase_done, phase_total)
        asyncio.run_coroutine_threadsafe(self._edit(text), self._loop)

    async def _heartbeat(self) -> None:
        """Пока common.db пересобирается — крутим спиннер раз в секунду."""
        tick = 0
        while self._heartbeat_on:
            await asyncio.sleep(1.0)
            if not self._heartbeat_on:
                break
            done, total, phase, detail, phase_done, phase_total = self._snapshot
            spin = self._SPINNERS[tick % len(self._SPINNERS)]
            tick += 1
            text = self._format(
                done, total, phase, detail, phase_done, phase_total, spinner=spin
            )
            await self._edit(text)

    async def _edit(self, text: str) -> None:
        try:
            await self._message.edit_text(text, parse_mode="HTML")
        except Exception:
            logger.debug("progress edit skipped", exc_info=True)


def _home_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="📤 Загрузить файлы", callback_data="xfer:upload:start")],
            [
                InlineKeyboardButton(text="📥 Выгрузить составы", callback_data="xfer:export:squads"),
                InlineKeyboardButton(text="📥 Свободные агенты", callback_data="xfer:export:fa"),
            ],
            [InlineKeyboardButton(text="✖️ Закрыть", callback_data="xfer:upload:close")],
        ]
    )


def _confirm_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(text="✅ Применить", callback_data="xfer:upload:apply"),
                InlineKeyboardButton(text="❌ Отмена", callback_data="xfer:upload:cancel"),
            ],
        ]
    )


async def _send_home(message: Message, state: FSMContext) -> None:
    await state.clear()
    await message.answer(
        "🔄 <b>Трансферное окно</b>\n\n"
        "Подготовь выгрузку из desktop-приложения, затем загрузи <b>два файла</b>:\n"
        "1️⃣ <b>Составы</b> — <code>squads_export_*.txt</code>\n"
        "2️⃣ <b>Трансферы</b> — <code>transfers_export_*.txt</code> "
        "или <code>transfer_window_state_*.json</code>\n\n"
        "Кнопки ниже — выгрузить актуальные составы и пул свободных агентов из БД.\n"
        "JSON дополнительно применит схемы тренеров из state.\n"
        "/cancel — отмена.",
        parse_mode="HTML",
        reply_markup=_home_kb(),
    )


async def _download_document_text(message: Message) -> tuple[str, str]:
    doc = message.document
    if doc is None or doc.file_name is None:
        raise ValueError("Нужен файл-документ.")
    fn = doc.file_name.lower()
    if not fn.endswith((".txt", ".json")):
        raise ValueError("Нужен .txt или .json")
    buf = io.BytesIO()
    await message.bot.download(doc, destination=buf)
    raw = buf.getvalue()
    try:
        text = raw.decode("utf-8")
    except UnicodeDecodeError:
        text = raw.decode("utf-8-sig")
    return text, doc.file_name


@transfer_router.callback_query(F.data == "xfd:home")
@transfer_router.message(Command("transfer"))
async def cmd_transfer_entry(event: Message | CallbackQuery, state: FSMContext) -> None:
    if isinstance(event, CallbackQuery):
        await event.answer()
        msg = event.message
        if msg is None:
            return
        await _send_home(msg, state)
        return
    await _send_home(event, state)


@transfer_router.callback_query(F.data == "xfer:upload:close")
async def cb_xfer_close(callback: CallbackQuery, state: FSMContext) -> None:
    await callback.answer()
    await state.clear()
    if callback.message:
        await callback.message.answer("Закрыто.")


@transfer_router.callback_query(F.data == "xfer:upload:start")
async def cb_xfer_upload_start(callback: CallbackQuery, state: FSMContext) -> None:
    await callback.answer()
    await state.set_state(TransferUpload.waiting_squads)
    if callback.message:
        await callback.message.answer(
            "Шаг 1/2 — отправь файл <b>составов</b> (<code>squads_export_*.txt</code>).\n"
            "/cancel — отмена.",
            parse_mode="HTML",
        )


@transfer_router.callback_query(F.data == "xfer:upload:cancel")
async def cb_xfer_upload_cancel(callback: CallbackQuery, state: FSMContext) -> None:
    await callback.answer()
    await state.clear()
    if callback.message:
        await callback.message.answer("Загрузка отменена.")


@transfer_router.message(StateFilter(TransferUpload.waiting_squads), _DOC)
async def on_squads_file(message: Message, state: FSMContext) -> None:
    try:
        text, fname = await _download_document_text(message)
    except ValueError as e:
        await message.answer(f"✗ {html_escape(str(e))}", parse_mode="HTML")
        return
    if "@" not in text and "==== start ===" not in text.lower():
        await message.answer(
            "✗ Не похоже на squads_export: нужны блоки <code>@Клуб</code> и секции start/bench/reserve.",
            parse_mode="HTML",
        )
        return
    await state.update_data(xfer_squads_text=text, xfer_squads_name=fname)
    await state.set_state(TransferUpload.waiting_transfers)
    await message.answer(
        f"✓ Составы (<code>{html_escape(fname)}</code>) получены.\n\n"
        "Шаг 2/2 — отправь файл <b>трансферов</b> "
        "(<code>transfers_export_*.txt</code> или <code>transfer_window_state_*.json</code>).",
        parse_mode="HTML",
    )


@transfer_router.message(StateFilter(TransferUpload.waiting_transfers), _DOC)
async def on_transfers_file(message: Message, state: FSMContext) -> None:
    data = await state.get_data()
    squads_text = data.get("xfer_squads_text")
    if not squads_text:
        await state.clear()
        await message.answer("Сессия сброшена. Начни снова: /transfer")
        return
    try:
        tr_text, tr_name = await _download_document_text(message)
    except ValueError as e:
        await message.answer(f"✗ {html_escape(str(e))}", parse_mode="HTML")
        return
    from utils.transfer_window_apply import parse_transfers_file

    try:
        transfers, teams = parse_transfers_file(tr_text, tr_name)
    except (ValueError, json.JSONDecodeError) as e:
        await message.answer(f"✗ {html_escape(str(e))}", parse_mode="HTML")
        return

    from scripts.apply_bulk_squad_declarations import split_bulk_blocks
    from utils.transfer_window_apply import strip_transfers_appendix

    n_clubs = len(split_bulk_blocks(strip_transfers_appendix(str(squads_text))))
    await state.update_data(
        xfer_transfers_text=tr_text,
        xfer_transfers_name=tr_name,
        xfer_transfers_count=len(transfers),
        xfer_squads_clubs=n_clubs,
        xfer_has_formations=bool(teams),
    )
    await state.set_state(TransferUpload.confirm)
    extra = ""
    if teams:
        extra = "\n• схемы тренеров из JSON — да"
    await message.answer(
        f"<b>Проверь перед применением</b>\n\n"
        f"• составы: <code>{html_escape(str(data.get('xfer_squads_name') or ''))}</code> "
        f"— <b>{n_clubs}</b> клуб(ов)\n"
        f"• трансферы: <code>{html_escape(tr_name)}</code> "
        f"— <b>{len(transfers)}</b> переход(ов){extra}\n\n"
        "Применить изменения к БД сезона?",
        parse_mode="HTML",
        reply_markup=_confirm_kb(),
    )


@transfer_router.callback_query(StateFilter(TransferUpload.confirm), F.data == "xfer:upload:apply")
async def cb_xfer_apply(callback: CallbackQuery, state: FSMContext) -> None:
    await callback.answer("Применяю…")
    data = await state.get_data()
    squads = data.get("xfer_squads_text")
    tr_text = data.get("xfer_transfers_text")
    tr_name = data.get("xfer_transfers_name") or "transfers.txt"
    if not squads or not tr_text:
        await state.clear()
        if callback.message:
            await callback.message.answer("Данные потерялись — начни заново: /transfer")
        return
    progress_msg = None
    if callback.message:
        progress_msg = await callback.message.answer(
            "<b>Применяю трансферы и составы</b>\n"
            "<pre>[░░░░░░░░░░░░░░░░░░░░░░]   0%</pre>\n"
            "Шагов: <b>0</b> / …",
            parse_mode="HTML",
        )
    try:
        from utils.transfer_window_apply import apply_transfer_window_upload

        on_progress = None
        if progress_msg is not None:
            on_progress = _TransferApplyProgress(progress_msg, asyncio.get_running_loop())
        res = await asyncio.to_thread(
            apply_transfer_window_upload,
            squads_text=str(squads),
            transfers_content=str(tr_text),
            transfers_filename=str(tr_name),
            dry_run=False,
            on_progress=on_progress,
        )
        body = "\n".join(res.lines)
        await state.clear()
        if progress_msg is not None:
            try:
                await progress_msg.delete()
            except Exception:
                pass
        if callback.message:
            await callback.message.answer(f"✅ <b>Готово</b>\n{html_escape(body)}", parse_mode="HTML")
    except Exception as e:
        logger.exception("apply transfer window upload")
        await state.clear()
        if progress_msg is not None:
            try:
                await progress_msg.delete()
            except Exception:
                pass
        if callback.message:
            await callback.message.answer(
                f"✗ Ошибка: {html_escape(str(e))}",
                parse_mode="HTML",
            )


@transfer_router.callback_query(F.data == "xfer:export:squads")
async def cb_xfer_export_squads(callback: CallbackQuery) -> None:
    await callback.answer("Готовлю составы…")
    if not callback.message:
        return
    try:
        from aiogram.types import BufferedInputFile
        from utils.transfer_export import export_squads_txt_for_bot

        text = await asyncio.to_thread(export_squads_txt_for_bot)
        doc = BufferedInputFile(
            text.encode("utf-8"),
            filename="squads_export_bot.txt",
        )
        await callback.message.answer_document(
            doc,
            caption="📥 Актуальные составы 40 клубов (для transfer app → «Загрузить из бота»)",
        )
    except Exception as e:
        logger.exception("export squads")
        await callback.message.answer(f"✗ {html_escape(str(e))}", parse_mode="HTML")


@transfer_router.callback_query(F.data == "xfer:export:fa")
async def cb_xfer_export_fa(callback: CallbackQuery) -> None:
    await callback.answer("Готовлю FA…")
    if not callback.message:
        return
    try:
        from aiogram.types import BufferedInputFile
        from utils.transfer_export import export_free_agents_json_for_bot, export_free_agents_txt_for_bot

        jtext = await asyncio.to_thread(export_free_agents_json_for_bot)
        ttext = await asyncio.to_thread(export_free_agents_txt_for_bot)
        await callback.message.answer_document(
            BufferedInputFile(jtext.encode("utf-8"), filename="free_agents.json"),
            caption="📥 Свободные агенты → transfer app: «Загрузить FA из бота»",
        )
        await callback.message.answer_document(
            BufferedInputFile(ttext.encode("utf-8"), filename="free_agents.txt"),
            caption="📋 Тот же пул — таблица для просмотра",
        )
    except Exception as e:
        logger.exception("export free agents")
        await callback.message.answer(f"✗ {html_escape(str(e))}", parse_mode="HTML")


@transfer_router.message(StateFilter(TransferUpload), Command("cancel"))
@transfer_router.message(StateFilter(TransferUpload), F.text.casefold() == "отмена")
async def xfer_upload_cancel_cmd(message: Message, state: FSMContext) -> None:
    await state.clear()
    await message.answer("Загрузка трансферного окна отменена.")


@transfer_router.message(StateFilter(TransferUpload), _TEXT_NOT_CMD)
async def xfer_upload_hint(message: Message, state: FSMContext) -> None:
    cur = await state.get_state()
    if cur == TransferUpload.waiting_squads.state:
        await message.answer("Жду файл составов (.txt) — отправь документом, не текстом.")
    elif cur == TransferUpload.waiting_transfers.state:
        await message.answer("Жду файл трансферов (.txt или .json) — отправь документом.")
    else:
        await message.answer("Нажми «Применить» или «Отмена» под предыдущим сообщением.")
