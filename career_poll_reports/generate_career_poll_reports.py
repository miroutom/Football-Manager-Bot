#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Досье от агента: варианты продолжения карьеры Максима Ветрова."""
from __future__ import annotations

from io import BytesIO
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

OUT = Path(__file__).resolve().parent
W = 1080
FONT = "/System/Library/Fonts/Supplemental/Arial Unicode.ttf"
FONT_B = "/System/Library/Fonts/Supplemental/Arial Bold.ttf"
if not Path(FONT_B).exists():
    FONT_B = FONT

# «бумага» досье
PAPER = (246, 242, 234)
INK = (28, 26, 24)
INK_DIM = (110, 100, 90)
RULE = (200, 188, 170)
GOLD = (160, 120, 50)
GREEN = (40, 110, 70)
RED = (150, 55, 45)
NAVY = (30, 48, 78)


def font(size: int, bold: bool = False) -> ImageFont.FreeTypeFont:
    return ImageFont.truetype(FONT_B if bold else FONT, size)


def fit(draw: ImageDraw.ImageDraw, text: str, fnt, max_w: int) -> str:
    t = text
    while t and draw.textbbox((0, 0), t, font=fnt)[2] > max_w:
        t = t[:-1]
    if t != text and len(t) > 1:
        t = t[:-1] + "…"
    return t or text[:1]


def wrap(draw: ImageDraw.ImageDraw, text: str, fnt, max_w: int) -> list[str]:
    words = text.split()
    lines: list[str] = []
    cur = ""
    for w in words:
        trial = f"{cur} {w}".strip()
        if draw.textbbox((0, 0), trial, font=fnt)[2] <= max_w:
            cur = trial
        else:
            if cur:
                lines.append(cur)
            cur = w
    if cur:
        lines.append(cur)
    return lines or [""]


def paper_bg(h: int, accent: tuple[int, int, int]) -> Image.Image:
    im = Image.new("RGB", (W, h), PAPER)
    d = ImageDraw.Draw(im)
    # боковая «папка»
    d.rectangle([0, 0, 18, h], fill=accent)
    # лёгкая текстура линиями
    for y in range(0, h, 4):
        c = 242 - (y % 12)
        d.line([(18, y), (W, y)], fill=(c, c - 3, c - 8))
    # тень слева от контента
    d.rectangle([18, 0, 22, h], fill=(220, 210, 195))
    return im


def round_rect(d, box, r, fill, outline=None, width=1):
    d.rounded_rectangle(box, radius=r, fill=fill, outline=outline, width=width)


def measure_bullets(d, items, max_w, fnt, line_h=22, gap=3) -> int:
    h = 0
    for item in items:
        lines = wrap(d, item, fnt, max_w - 20)
        h += max(line_h, len(lines) * line_h) + gap
    return h


def draw_bullets(d, items, x, y, max_w, fnt, color, mark, line_h=22, gap=3) -> int:
    for item in items:
        lines = wrap(d, item, fnt, max_w - 20)
        d.text((x, y), mark, font=fnt, fill=color)
        for i, line in enumerate(lines):
            d.text((x + 18, y + i * line_h), line, font=fnt, fill=INK)
        y += max(line_h, len(lines) * line_h) + gap
    return y


def agency_header(d, y: int, doc_no: str, stamp: str) -> int:
    d.text((48, y), "VETROV MANAGEMENT", font=font(18, True), fill=GOLD)
    d.text((48, y + 26), "конфиденциально · только для клиента", font=font(14), fill=INK_DIM)
    # stamp
    sw = d.textbbox((0, 0), stamp, font=font(13, True))[2] + 20
    round_rect(d, [W - 48 - sw, y, W - 48, y + 28], 4, (236, 228, 210), GOLD, 1)
    d.text((W - 48 - sw + 10, y + 6), stamp, font=font(13, True), fill=GOLD)
    d.text((W - 48 - 200, y + 36), doc_no, font=font(13), fill=INK_DIM)
    d.line([(48, y + 58), (W - 48, y + 58)], fill=RULE, width=2)
    return y + 72


def parse_metric(val) -> float | None:
    if val is None:
        return None
    if isinstance(val, (int, float)):
        return float(val)
    s = str(val).strip().replace("–", "—")
    if s in ("", "—", "-", "?", "–"):
        return None
    if "/" in s:
        nums: list[float] = []
        for p in s.split("/"):
            try:
                nums.append(float(p.strip()))
            except ValueError:
                pass
        return max(nums) if nums else None
    try:
        return float(s.replace("+", "").split()[0])
    except ValueError:
        return None


def _duel_row(d, x, y, w, label, left_v, right_v, accent, kind: str) -> int:
    """Одна строка сравнения с барами от центра. Возвращает y после блока."""
    bar_left, bar_right = x, x + w
    mid = x + w // 2
    half = w // 2 - 8
    ln, rn = parse_metric(left_v), parse_metric(right_v)

    d.text((bar_left, y), label, font=font(12, True), fill=INK_DIM)
    y += 16
    d.text((bar_left, y), str(left_v) if left_v is not None else "—", font=font(24, True), fill=accent)
    rs = str(right_v) if right_v is not None else "—"
    rw = d.textbbox((0, 0), rs, font=font(24, True))[2]
    d.text((bar_right - rw, y), rs, font=font(24, True), fill=RED)
    y += 28

    ty = y
    round_rect(d, [bar_left, ty, bar_right, ty + 16], 8, (228, 220, 208))
    d.rectangle([mid - 1, ty, mid + 1, ty + 16], fill=(190, 178, 160))

    if kind == "ovr":

        def frac(v: float) -> float:
            return max(0.1, min(1.0, (v - 70.0) / 20.0))

    else:
        scale = max(ln or 0, rn or 0, 1.0)

        def frac(v: float) -> float:
            return max(0.1, min(1.0, v / scale))

    if ln is not None:
        lw = int(half * frac(ln))
        round_rect(d, [mid - 3 - lw, ty + 3, mid - 3, ty + 13], 5, accent)
    if rn is not None:
        rbw = int(half * frac(rn))
        round_rect(d, [mid + 3, ty + 3, mid + 3 + rbw, ty + 13], 5, RED)

    return y + 24


def _player_tours(side: dict) -> list[dict]:
    if side.get("tours"):
        return list(side["tours"])
    # fallback: старые строковые lines
    out = []
    for line in side.get("lines") or []:
        out.append({"comp": line, "stat": "", "apps": ""})
    return out or [{"comp": "—", "stat": "—", "apps": ""}]


TOUR_CARD_H = 50
TOUR_GAP = 6
TOUR_ORDER = {"ЛЧ": 0, "ЛЕ": 1, "ЛК": 2, "РПЛ": 3, "Кубок": 4, "Всего": 5, "Лига": 6, "ПФА": 7}


def _tour_index(tours: list[dict]) -> dict[str, dict]:
    return {str(t.get("comp") or ""): t for t in tours}


def _aligned_tour_rows(left_t: list[dict], right_t: list[dict]) -> list[tuple[dict | None, dict | None]]:
    """Если есть общие названия турниров — выравниваем в строки, иначе две независимые колонки."""
    li, ri = _tour_index(left_t), _tour_index(right_t)
    common = set(li) & set(ri) - {""}
    if not common:
        n = max(len(left_t), len(right_t), 1)
        rows = []
        for i in range(n):
            rows.append((left_t[i] if i < len(left_t) else None, right_t[i] if i < len(right_t) else None))
        return rows

    names = sorted(set(li) | set(ri), key=lambda c: (TOUR_ORDER.get(c, 40), c))
    return [(li.get(n), ri.get(n)) for n in names]


def tours_block_height(left: dict, right: dict) -> int:
    n = max(len(_aligned_tour_rows(_player_tours(left), _player_tours(right))), 1)
    return n * TOUR_CARD_H + max(0, n - 1) * TOUR_GAP


def draw_tour_card(d, x, y, w, tour: dict | None, color) -> None:
    """Мини-карточка турнира: название · матчи · крупно G+A."""
    if tour is None:
        round_rect(d, [x, y, x + w, y + TOUR_CARD_H], 7, (244, 240, 232), (220, 210, 195), 1)
        d.text((x + 14, y + 16), "—", font=font(18, True), fill=(180, 170, 155))
        return

    round_rect(d, [x, y, x + w, y + TOUR_CARD_H], 7, (250, 246, 238), (210, 198, 180), 1)
    d.rectangle([x + 1, y + 6, x + 5, y + TOUR_CARD_H - 6], fill=color)

    comp = fit(d, str(tour.get("comp") or "—"), font(12, True), w - 24)
    d.text((x + 14, y + 7), comp, font=font(12, True), fill=GOLD)

    apps = tour.get("apps")
    if apps not in (None, ""):
        apps_s = str(apps)
        aw = d.textbbox((0, 0), apps_s, font=font(11))[2]
        d.text((x + w - 12 - aw, y + 8), apps_s, font=font(11), fill=INK_DIM)

    stat = str(tour.get("stat") if tour.get("stat") not in (None, "") else "—")
    d.text((x + 14, y + 24), fit(d, stat, font(20, True), w - 28), font=font(20, True), fill=color)


def draw_tours_compare(d, x, y, w, left, right, accent) -> int:
    """Две колонки карточек турниров. Возвращает y под блоком."""
    rows = _aligned_tour_rows(_player_tours(left), _player_tours(right))
    gap = 14
    col_w = (w - gap) // 2
    h = tours_block_height(left, right)

    d.text((x, y), "СТАТА ПО ТУРНИРАМ", font=font(12, True), fill=GOLD)
    y += 20

    for i, (lt, rt) in enumerate(rows):
        row_y = y + i * (TOUR_CARD_H + TOUR_GAP)
        draw_tour_card(d, x, row_y, col_w, lt, accent)
        draw_tour_card(d, x + col_w + gap, row_y, col_w, rt, RED)

    return y + h + 14


def vs_block_height(left: dict, right: dict) -> int:
    tours_h = 20 + tours_block_height(left, right) + 14
    # pad12 + names32 + ovr68 + tours + 3×duel68 + bottom12
    return 12 + 32 + 68 + tours_h + 68 * 3 + 12


def draw_vs(d, x, y, w, left, right, accent) -> int:
    """
    Сравнение: OVR → стата по турнирам → голы / пасы / Г+П.
    Возвращает y сразу под блоком.
    """
    h = vs_block_height(left, right)
    round_rect(d, [x, y, x + w, y + h], 8, (255, 252, 246), RULE, 1)
    pad_in = 14
    ix, iw = x + pad_in, w - 2 * pad_in

    cy = y + 12
    d.text((ix, cy), fit(d, left["name"], font(18, True), iw // 2 - 40), font=font(18, True), fill=accent)
    vs = "VS"
    vsw = d.textbbox((0, 0), vs, font=font(13, True))[2]
    d.text((ix + (iw - vsw) // 2, cy + 2), vs, font=font(13, True), fill=GOLD)
    rn = fit(d, right["name"], font(18, True), iw // 2 - 40)
    rnw = d.textbbox((0, 0), rn, font=font(18, True))[2]
    d.text((ix + iw - rnw, cy), rn, font=font(18, True), fill=RED)
    cy += 32

    cy = _duel_row(d, ix, cy, iw, "РЕЙТИНГ (OVR)", left.get("ovr"), right.get("ovr"), accent, "ovr")
    cy = draw_tours_compare(d, ix, cy, iw, left, right, accent)

    g_l, a_l = left.get("g"), left.get("a")
    g_r, a_r = right.get("g"), right.get("a")
    ga_l = left.get("ga")
    ga_r = right.get("ga")
    if ga_l is None and g_l is not None and a_l is not None:
        try:
            ga_l = int(g_l) + int(a_l)
        except (TypeError, ValueError):
            ga_l = None
    if ga_r is None and g_r is not None and a_r is not None:
        try:
            ga_r = int(g_r) + int(a_r)
        except (TypeError, ValueError):
            ga_r = None

    cy = _duel_row(d, ix, cy, iw, "ГОЛЫ", g_l, g_r, accent, "stat")
    cy = _duel_row(d, ix, cy, iw, "ПАСЫ", a_l, a_r, accent, "stat")
    cy = _duel_row(d, ix, cy, iw, "ГОЛЫ + ПАСЫ", ga_l, ga_r, accent, "stat")

    return y + h


YOU_TOURS = [
    {"comp": "РПЛ", "stat": "35+17", "apps": "30 игр"},
    {"comp": "Кубок", "stat": "4+1", "apps": "3 игры"},
]

YOU_VS = {"name": "Ты", "ovr": "78", "g": 39, "a": 18, "ga": 57, "tours": YOU_TOURS}


def render_dossier(data: dict) -> bytes:
    accent = data["accent"]
    pad = 48
    inner = W - 2 * pad

    probe = Image.new("RGB", (W, 80), PAPER)
    pd = ImageDraw.Draw(probe)
    f_body = font(17)
    f_b = font(15)

    intro_h = sum(len(wrap(pd, t, f_body, inner)) * 24 for t in data["intro"]) + 8
    note_h = sum(len(wrap(pd, t, f_body, inner - 28)) * 24 for t in data["competition_lines"]) + 16
    if data.get("vs"):
        vs_h = vs_block_height(data["vs"][0], data["vs"][1])
    else:
        vs_h = 0
    half = (inner - 14) // 2
    pros_h = 36 + measure_bullets(pd, data["pros"], half - 28, f_b)
    cons_h = 36 + measure_bullets(pd, data["cons"], half - 28, f_b)
    pc_h = max(pros_h, cons_h)

    # header + greet + club + intro + section title + note + vs + pc + verdict + footer
    H = 90 + 70 + 78 + intro_h + 34 + note_h + 12 + vs_h + 20 + pc_h + 70 + 50
    im = paper_bg(H, accent)
    d = ImageDraw.Draw(im)

    y = agency_header(d, 28, data["doc_no"], data["stamp"])

    # обращение
    d.text((pad, y), "Максим,", font=font(28, True), fill=INK)
    y += 40
    d.text((pad, y), data["greeting"], font=font(16), fill=INK_DIM)
    y += 36

    # карточка клуба
    round_rect(d, [pad, y, W - pad, y + 62], 8, (255, 252, 246), accent, 2)
    d.text((pad + 16, y + 10), data["club"], font=font(28, True), fill=INK)
    d.text((pad + 16, y + 40), data["subtitle"], font=font(15), fill=INK_DIM)
    chip = f"{data['formation']}  ·  {data['europe']}"
    cw = d.textbbox((0, 0), chip, font=font(14, True))[2]
    d.text((W - pad - 16 - cw, y + 22), chip, font=font(14, True), fill=accent)
    y += 78

    for para in data["intro"]:
        for line in wrap(d, para, f_body, inner):
            d.text((pad, y), line, font=f_body, fill=INK)
            y += 24
        y += 6

    y += 8
    d.text((pad, y), "ПОЗИЦИЯ ПФА — РАСКЛАД", font=font(14, True), fill=GOLD)
    y += 26

    # короткий текст конкуренции
    if data["competition_lines"]:
        round_rect(d, [pad, y, W - pad, y + note_h], 8, (255, 252, 246), RULE, 1)
        cy = y + 10
        for line in data["competition_lines"]:
            for wrapped in wrap(d, line, f_body, inner - 28):
                d.text((pad + 14, cy), wrapped, font=f_body, fill=INK)
                cy += 24
        y += note_h + 10

    if data.get("vs"):
        y = draw_vs(d, pad, y, inner, data["vs"][0], data["vs"][1], accent) + 16

    # плюсы / минусы
    round_rect(d, [pad, y, pad + half, y + pc_h], 8, (240, 248, 242), GREEN, 1)
    d.text((pad + 12, y + 10), "ЗА", font=font(15, True), fill=GREEN)
    draw_bullets(d, data["pros"], pad + 12, y + 34, half - 28, f_b, GREEN, "+")

    x2 = pad + half + 14
    round_rect(d, [x2, y, W - pad, y + pc_h], 8, (250, 240, 238), RED, 1)
    d.text((x2 + 12, y + 10), "ПРОТИВ", font=font(15, True), fill=RED)
    draw_bullets(d, data["cons"], x2 + 12, y + 34, half - 28, f_b, RED, "–")
    y += pc_h + 16

    round_rect(d, [pad, y, W - pad, y + 52], 8, (255, 252, 246), GOLD, 2)
    d.text((pad + 14, y + 8), "ЗАМЕТКА АГЕНТА", font=font(12, True), fill=GOLD)
    d.text((pad + 14, y + 28), fit(d, data["verdict"], font(16, True), inner - 28), font=font(16, True), fill=INK)
    y += 64

    d.text((pad, y), "Ознакомься и скажи, куда копаем дальше.", font=font(14), fill=INK_DIM)
    d.text((W - pad - 180, y), "— твой агент", font=font(14, True), fill=GOLD)

    buf = BytesIO()
    im.convert("RGB").save(buf, format="PNG", optimize=True)
    return buf.getvalue()


def render_cover() -> bytes:
    H = 1280
    im = paper_bg(H, NAVY)
    d = ImageDraw.Draw(im)
    y = agency_header(d, 28, "ПАКЕТ № VM-26", "ДЛЯ КЛИЕНТА")

    d.text((48, y), "Максим,", font=font(36, True), fill=INK)
    y += 50
    for line in wrap(
        d,
        "Собрал для тебя шесть вариантов, куда можно двинуться после сезона. "
        "Это не приказ — это досье. Смотри цифры, плюсы/минусы и свою чуйку.",
        font(18),
        W - 96,
    ):
        d.text((48, y), line, font=font(18), fill=INK)
        y += 26

    y += 16
    round_rect(d, [48, y, W - 48, y + 110], 10, (255, 252, 246), GOLD, 2)
    d.text((68, y + 16), "ТВОЙ СЕЗОН (кратко)", font=font(14, True), fill=GOLD)
    d.text((68, y + 42), "Максим Ветров · ПФА · OVR 78", font=font(22, True), fill=INK)
    d.text((68, y + 74), "РПЛ 35+17 / 30 · Кубок 4+1 / 3 · оценка 8+", font=font(17), fill=INK_DIM)
    y += 130

    d.text((48, y), "ВНУТРИ ПАКЕТА", font=font(14, True), fill=GOLD)
    y += 28
    clubs = [
        ("01", "Зенит", "престиж · ЛЧ"),
        ("02", "Динамо", "сюжет · ЛЕ"),
        ("03", "Спартак", "схема 4-3-3 · ЛЕ"),
        ("04", "Краснодар", "вайлдкард"),
        ("05", "СКА Хабаровск", "дом"),
        ("06", "Европа", "новый вызов"),
    ]
    for num, name, tag in clubs:
        round_rect(d, [48, y, W - 48, y + 72], 8, (255, 252, 246), RULE, 1)
        d.text((68, y + 20), num, font=font(24, True), fill=GOLD)
        d.text((130, y + 14), name, font=font(22, True), fill=INK)
        d.text((130, y + 42), tag, font=font(15), fill=INK_DIM)
        y += 84

    y += 8
    d.text((48, y), "Решение за тобой. Я только разложил карты.", font=font(16), fill=INK_DIM)
    d.text((W - 48 - 160, y), "— твой агент", font=font(16, True), fill=GOLD)

    buf = BytesIO()
    im.convert("RGB").save(buf, format="PNG", optimize=True)
    return buf.getvalue()


DOSSIERS = [
    {
        "file": "01_zenit.png",
        "doc_no": "ДОКУМЕНТ 01 / 06",
        "stamp": "ПРЕСТИЖ",
        "accent": (0, 90, 140),
        "club": "Зенит",
        "subtitle": "Чемпионы РПЛ · отбор в Лигу чемпионов",
        "greeting": "Первый вариант — самый громкий. Разберём без розовых очков.",
        "formation": "4-3-3",
        "europe": "1 место · ЛЧ",
        "intro": [
            "Зенит — фавориты на титул и прямой билет в ЛЧ. Для бренда карьеры это потолок по статусу.",
            "Но ты идёшь не в пустой фланг: там Луис Энрике (84). Рейтингом он выше, цифрами — нет.",
        ],
        "competition_lines": [
            "На ПФА сейчас Энрике. Место в основе придётся отбирать, Зенит любит покупать топов.",
        ],
        "vs": (
            YOU_VS,
            {
                "name": "Энрике",
                "ovr": "84",
                "g": 14,
                "a": 10,
                "ga": 24,
                "tours": [
                    {"comp": "ЛЧ", "stat": "2+1", "apps": ""},
                    {"comp": "РПЛ", "stat": "3+3", "apps": ""},
                    {"comp": "Кубок", "stat": "9+6", "apps": ""},
                ],
            },
        ),
        "pros": [
            "Фавориты на чемпионство",
            "Прямой путь в ЛЧ",
            "Максимальный престиж",
            "Ты сильнее его по стате",
        ],
        "cons": [
            "Риск ротации",
            "Может стать скучно среди звёзд",
            "78 vs 84 — старт не гарантия",
        ],
        "verdict": "Бери, если хочешь ЛЧ и большой свет. Готовься драться за минуты.",
    },
    {
        "file": "02_dynamo.png",
        "doc_no": "ДОКУМЕНТ 02 / 06",
        "stamp": "СЮЖЕТ",
        "accent": (50, 90, 160),
        "club": "Динамо",
        "subtitle": "3 место РПЛ · отбор в Лигу Европы · 4-4-2",
        "greeting": "Вариант «история». Тут не только очки — тут нарратив.",
        "formation": "4-4-2",
        "europe": "3 место · ЛЕ",
        "intro": [
            "Динамо дерётся за чемпионство, едет в ЛЕ и выглядит живо: молодой состав, есть голод.",
            "Чемпионство у них не брали с советских времён. Привести их куда-то — это уже кино.",
        ],
        "competition_lines": [
            "На фланге Ярослав Гладышев (77). Ты уже чуть выше рейтингом и сильно выше по отдаче.",
        ],
        "vs": (
            YOU_VS,
            {
                "name": "Гладышев",
                "ovr": "77",
                "g": 4,
                "a": 2,
                "ga": 6,
                "tours": [
                    {"comp": "РПЛ", "stat": "~4+2", "apps": "~23 игры"},
                ],
            },
        ),
        "pros": [
            "Борьба за чемпионство",
            "Молодой интересный состав",
            "Сильный сюжет для сезона",
            "Конкурент слабее тебя",
        ],
        "cons": [
            "ЛЕ, не ЛЧ",
            "Меньше престижа, чем Зенит",
            "4-4-2: ПФА ближе к RM",
        ],
        "verdict": "Если хочешь смысл и лидерство — Динамо очень вкусно смотрится.",
    },
    {
        "file": "03_spartak.png",
        "doc_no": "ДОКУМЕНТ 03 / 06",
        "stamp": "СХЕМА",
        "accent": (160, 30, 35),
        "club": "Спартак",
        "subtitle": "2 место РПЛ · отбор в Лигу Европы · 4-3-3",
        "greeting": "Этот вариант я бы назвал «встал и играй»: схема прямо под тебя.",
        "formation": "4-3-3",
        "europe": "2 место · ЛЕ",
        "intro": [
            "Спартак — борьба за титул и ЛЕ. Главный плюс: классическая 4-3-3, правый фланг твой профиль.",
            "Конкуренты на бумаге есть, по игре — почти нет.",
        ],
        "competition_lines": [
            "Бонгонда (74) и Солари (80): один слабый рейтингом, второй — провальной статой (0+2).",
        ],
        "vs": (
            YOU_VS,
            {
                "name": "Солари",
                "ovr": "80",
                "g": 0,
                "a": 2,
                "ga": 2,
                "tours": [
                    {"comp": "Солари", "stat": "0+2", "apps": "80 OVR"},
                    {"comp": "Бонгонда", "stat": "4+6", "apps": "74 OVR"},
                ],
            },
        ),
        "pros": [
            "Идеальная 4-3-3 под ПФА",
            "Борьба за чемпионство",
            "Слабая конкуренция по отдаче",
            "Отбор в ЛЕ",
        ],
        "cons": [
            "ЛЕ вместо ЛЧ",
            "Сюжет слабее, чем у Динамо",
            "Недавно брали трофеи — меньше голода",
        ],
        "verdict": "Если важна схема и быстрый старт в основе — Спартак почти идеальный фит.",
    },
    {
        "file": "04_krasnodar.png",
        "doc_no": "ДОКУМЕНТ 04 / 06",
        "stamp": "ВАЙЛДКАРД",
        "accent": (30, 120, 70),
        "club": "Краснодар",
        "subtitle": "4 место РПЛ · 4-2-3-1 · неочевидный ход",
        "greeting": "Не самый громкий клуб — зато можно зайти королём фланга.",
        "formation": "4-2-3-1",
        "europe": "4 место · ЛК/?",
        "intro": [
            "Краснодар — вайлдкард. Европа под вопросом, но конкуренция на твоей позиции почти бутафорская.",
            "Если цель — взорвать сезон цифрами и быть главным, это рабочий план.",
        ],
        "competition_lines": [
            "Мантуан (79) рядом по OVR, но 8+4 за 46 — это не твой уровень. Глубина фланга ещё слабее.",
        ],
        "vs": (
            YOU_VS,
            {
                "name": "Мантуан",
                "ovr": "79",
                "g": 8,
                "a": 4,
                "ga": 12,
                "tours": [
                    {"comp": "Всего", "stat": "8+4", "apps": "46 игр"},
                ],
            },
        ),
        "pros": [
            "Почти нет конкуренции",
            "Сразу лидер фланга",
            "Необычный ход для сезона",
            "Простор для больших цифр",
        ],
        "cons": [
            "4 место: ЛК или без Европы",
            "Уже брали лигу и кубок с 2023",
            "Состав менее яркий",
        ],
        "verdict": "Бери, если хочешь доминировать, а не делить свет с суперзвёздами.",
    },
    {
        "file": "05_ska.png",
        "doc_no": "ДОКУМЕНТ 05 / 06",
        "stamp": "ДОМ",
        "accent": (150, 110, 40),
        "club": "СКА Хабаровск",
        "subtitle": "Родная команда · ФНЛ → РПЛ · ты уже герой",
        "greeting": "Самый тёплый вариант. И самый опасный для динамики карьеры.",
        "formation": "основа",
        "europe": "без евро",
        "intro": [
            "Ты вывел их в РПЛ и помог остаться. Город родной, место в старте — твоё.",
            "Вопрос не «возьмут ли». Вопрос — не застрянешь ли на третьем круге выживания.",
        ],
        "competition_lines": [
            "Конкуренции на ПФА нет. Ты основной. Это и плюс, и потолок.",
        ],
        "vs": (
            YOU_VS,
            {
                "name": "Конкурент",
                "ovr": "—",
                "g": "—",
                "a": "—",
                "ga": "—",
                "tours": [
                    {"comp": "ПФА", "stat": "пусто", "apps": "нет конкурента"},
                ],
            },
        ),
        "pros": [
            "Родная команда и город",
            "100% основа",
            "Связь с болельщиками",
            "Стабильность",
        ],
        "cons": [
            "Уже 2 года — 3-й может надоесть",
            "Снова выживание",
            "Нет еврокубков",
            "Нет нового вызова",
        ],
        "verdict": "Оставь, только если сердце громче амбиций. Иначе — шаг назад.",
    },
    {
        "file": "06_europe.png",
        "doc_no": "ДОКУМЕНТ 06 / 06",
        "stamp": "ЭКСПАТ",
        "accent": (100, 70, 150),
        "club": "Европейский середняк",
        "subtitle": "Новая страна · новый язык · новый уровень сложности",
        "greeting": "Самый рисковый лист в папке. И самый свежий по ощущениям.",
        "formation": "?",
        "europe": "скорее без евро",
        "intro": [
            "Рандомный середняк в Европе — это не статус, это приключение: адаптация, другая лига, другой прессинг.",
            "Будет тяжелее, чем в РПЛ. Значит, интереснее снимать и расти.",
        ],
        "competition_lines": [
            "Кто на позиции — неизвестно. Гарантий нет. Зато страница карьеры точно новая.",
        ],
        "vs": (
            YOU_VS,
            {
                "name": "Конкурент",
                "ovr": "?",
                "g": "?",
                "a": "?",
                "ga": "?",
                "tours": [
                    {"comp": "Лига", "stat": "?", "apps": "неизвестно"},
                ],
            },
        ),
        "pros": [
            "Новая страна",
            "Новый вызов",
            "Сложнее РПЛ",
            "Свежий сюжет сезона",
        ],
        "cons": [
            "Скорее без еврокубков",
            "Рандомный клуб/страна",
            "Неизвестная конкуренция",
            "Можно потерять статус звезды",
        ],
        "verdict": "Если хочешь риск и «вау» для сезона — это твой джокер.",
    },
]


def main() -> None:
    (OUT / "00_cover.png").write_bytes(render_cover())
    print("wrote 00_cover.png")
    for data in DOSSIERS:
        path = OUT / data["file"]
        path.write_bytes(render_dossier(data))
        print("wrote", path.name)


if __name__ == "__main__":
    main()
