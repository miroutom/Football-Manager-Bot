"""
Состав клуба на схеме поля: слоты из ``team_squad_schemas`` / ``formation_geometry``.

Подбор по слотам формации: для каждого слота среди игроков команды, чья позиция в БД
входит в ``allowed_positions`` этого слота, выбирается с наивысшим рейтингом (как ЛЗ:
Дэвис vs Геррейро). Если «своих» нет — подстановка по взаимозаменяемости, как раньше.

Стартовые 11: футболка по ``KitSpec`` (1 цвет — сплошняк, 2 — полосы, 3 — полосы
и отдельный цвет воротника), см. ``squad_kit_palette``. Фамилия снизу, рейтинг справа.
Запасные/резерв — текстом как раньше.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from io import BytesIO
from pathlib import Path

from data.defender import Defender
from data.forward import Forward
from data.goalkeeper import Goalkeeper
from data.midfielder import Midfielder
from coach_squad_state import label_for_squad_caption, resolve_formation_key_for_team
from squad_kit_palette import KitSpec, kit_for_team
from team_squad_schemas import SquadSlot, get_slots_for_formation_key
from utils.utils import defenders, forwards, get_session, goalkeepers, midfielders

# Взаимозаменяемость (позиции из БД)
_INTER_ATTACK = frozenset(
    {"ФРВ", "ПФА", "ЛФА", "ПП", "ЛП", "ЦАП", "ЦФД", "ЛФД", "ПФД"}
)
_INTER_CM = frozenset({"ЦП", "ЦОП"})
_INTER_FB = frozenset({"ЛЗ", "ПЗ", "ЛФЗ", "ПФЗ"})
_CB_MARKERS = frozenset({"ЦЗ", "ЛЦЗ", "ПЦЗ"})
_FORWARD_SLOT_IDS = frozenset({"LW", "RW", "ST", "STL", "STR", "CF"})

logger = logging.getLogger(__name__)

try:
    from PIL import Image, ImageDraw, ImageFont
except ImportError as e:
    raise ImportError("Нужен пакет Pillow: pip install pillow") from e

# Палитра «карточки» состава (тёмный UI + газон)
_PAGE_BG = (11, 18, 22)
_PAGE_BG_TOP = (17, 28, 34)
_PITCH_FRAME = (71, 85, 105)
_GRASS_LO = (18, 58, 42)
_GRASS_HI = (34, 92, 58)
_LINE_SOFT = (230, 240, 235)
_SLATE_MUTED = (148, 163, 184)
_SLATE_BRIGHT = (241, 245, 249)
_BADGE_FILL = (30, 41, 59)
_BADGE_EDGE = (51, 65, 85)


def _try_truetype(path: Path, size: int, index: int = 0) -> ImageFont.FreeTypeFont | None:
    if not path.exists():
        return None
    try:
        return ImageFont.truetype(str(path), size=size, index=index)
    except OSError:
        return None


def _pick_font(size: int, bold: bool = False) -> ImageFont.FreeTypeFont:
    if bold:
        candidates = (
            (Path("/System/Library/Fonts/Supplemental/Avenir Next.ttc"), 6),
            (Path("/System/Library/Fonts/Supplemental/Avenir.ttc"), 2),
            (Path("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"), 0),
            (Path("/System/Library/Fonts/Supplemental/Arial Bold.ttf"), 0),
            (Path("C:/Windows/Fonts/arialbd.ttf"), 0),
        )
    else:
        candidates = (
            (Path("/System/Library/Fonts/Supplemental/Avenir Next.ttc"), 0),
            (Path("/System/Library/Fonts/Supplemental/Avenir.ttc"), 0),
            (Path("/usr/share/fonts/truetype/noto/NotoSans-Regular.ttf"), 0),
            (Path("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"), 0),
            (Path("/System/Library/Fonts/Supplemental/Arial.ttf"), 0),
            (Path("C:/Windows/Fonts/arial.ttf"), 0),
        )
    for path, idx in candidates:
        f = _try_truetype(path, size, idx)
        if f is not None:
            return f
    logger.warning("Состав: не найден TTF, используется шрифт по умолчанию")
    return ImageFont.load_default()


def _team_name_as_in_db(team: str) -> str:
    if (team or "").strip() == "ЦСКА":
        return "Цска"
    return team


def _surname(full_name: str) -> str:
    s = (full_name or "").strip()
    if not s:
        return "?"
    parts = s.split()
    return parts[-1] if len(parts) >= 2 else parts[0]


def _display_score(overall: int, rating: float) -> str:
    o = int(overall or 0)
    if o > 0:
        return str(o)
    r = float(rating or 0.0)
    if r > 0:
        return f"{r:.1f}"
    return "—"


def _position_tags(pos: str) -> set[str]:
    p = (pos or "").strip()
    tags: set[str] = set()
    if p in goalkeepers:
        tags.add("gk")
    if p in ("ЛЗ", "ЛФЗ"):
        tags.add("lb")
    if p in ("ПЗ", "ПФЗ"):
        tags.add("rb")
    if p == "ЦЗ":
        tags.add("cb")
    if p == "ЛЦЗ":
        tags.update(("cb", "lb"))
    if p == "ПЦЗ":
        tags.update(("cb", "rb"))
    if p == "ЦОП":
        tags.add("cdm")
    if p in ("ЛП", "ЛЦП"):
        tags.update(("cm", "lcm"))
    if p in ("ПП", "ПЦП"):
        tags.update(("cm", "rcm"))
    if p in ("ЦП", "ЦАП"):
        tags.add("cm")
    if p in ("ЛФА", "ЛФД"):
        tags.add("lw")
    if p in ("ПФА", "ПФД"):
        tags.add("rw")
    if p in ("ФРВ", "ЦФД"):
        tags.add("st")
    if p in forwards and not tags:
        tags.add("st")
    if p in midfielders and not tags:
        tags.add("cm")
    if p in defenders and not tags:
        tags.add("cb")
    return tags


def _player_score(overall: int, rating: float) -> int:
    o = int(overall or 0)
    r = float(rating or 0.0)
    if o > 0:
        return o * 1000 + int(r * 10)
    return int(r * 100)


@dataclass
class _Pl:
    name: str
    position: str
    overall: int
    rating: float
    tags: set[str]
    score: int


def load_team_squad_players(team: str, tournament: str) -> list[_Pl]:
    team_db = _team_name_as_in_db(team)
    session = get_session(tournament)
    out: list[_Pl] = []
    for cls in (Forward, Midfielder, Defender, Goalkeeper):
        for p in session.query(cls).filter_by(team=team_db).all():
            pos = getattr(p, "position", "") or ""
            ov = int(getattr(p, "overall", 0) or 0)
            rt = float(getattr(p, "rating", 0.0) or 0.0)
            tags = _position_tags(pos)
            out.append(
                _Pl(
                    name=p.name,
                    position=pos,
                    overall=ov,
                    rating=rt,
                    tags=tags,
                    score=_player_score(ov, rt),
                )
            )
    return out


def _player_fits_slot(p: _Pl, slot: SquadSlot) -> bool:
    pos = (p.position or "").strip()
    allowed = slot.allowed_positions
    if pos in allowed:
        return True
    if allowed == frozenset({"ВРТ"}):
        return False
    if pos == "ЦОП" and allowed & _CB_MARKERS:
        return True
    if pos in _INTER_FB and allowed & _INTER_FB:
        return True
    if pos in _INTER_CM and allowed & _INTER_CM:
        return True
    if slot.slot_id in _FORWARD_SLOT_IDS and pos in _INTER_ATTACK:
        if allowed & _INTER_ATTACK or allowed & frozenset({"ЦФД"}):
            return True
    return False


def _natural_fits_slot(p: _Pl, slot: SquadSlot) -> bool:
    """Позиция из БД напрямую входит в допустимые для слота (без сдвигов по линиям)."""
    return (p.position or "").strip() in slot.allowed_positions


def _draw_shirt_shadow(draw: ImageDraw.ImageDraw, cx: int, cy: int, bw: int, bh: int) -> None:
    r = 12
    sx0 = int(cx - bw // 2 + 2)
    sy0 = int(cy - bh // 2 + 4)
    sx1, sy1 = sx0 + bw, sy0 + bh
    draw.rounded_rectangle([sx0, sy0, sx1, sy1], radius=r, fill=(8, 16, 12))


def _draw_shirt(
    draw: ImageDraw.ImageDraw,
    cx: int,
    cy: int,
    kit: KitSpec,
    is_gk: bool,
) -> tuple[int, int, int, int]:
    """Рисует упрощённую футболку; возвращает bbox (x0,y0,x1,y1)."""
    if is_gk:
        primary = (32, 38, 48)
        secondary = (72, 82, 98)
        striped = False
        collar = (22, 28, 36)
    else:
        primary = kit.primary
        striped = kit.striped
        secondary = kit.secondary if kit.secondary is not None else primary
        collar = kit.collar_rgb()
    bw, bh = 48, 52
    r = 12
    x0, y0 = int(cx - bw // 2), int(cy - bh // 2)
    x1, y1 = x0 + bw, y0 + bh
    edge = (220, 228, 236) if sum(primary) > 400 else (55, 65, 81)
    _draw_shirt_shadow(draw, cx, cy, bw, bh)
    draw.rounded_rectangle(
        [x0, y0, x1, y1],
        radius=r,
        fill=primary,
        outline=edge,
        width=1,
    )
    if striped:
        for sx in range(x0 + 5, x1 - 4, 8):
            draw.rectangle([sx, y0 + 6, min(sx + 3, x1 - 5), y1 - 6], fill=secondary)
    draw.polygon(
        [(cx, y0 + 5), (cx - 10, y0 + 17), (cx + 10, y0 + 17)],
        fill=collar,
        outline=edge,
        width=1,
    )
    return x0, y0, x1, y1


def _assign_slots(players: list[_Pl], team_db: str) -> tuple[dict[str, _Pl], list[_Pl]]:
    slots = get_slots_for_formation_key(resolve_formation_key_for_team(team_db))
    pool = players[:]
    used: set[int] = set()
    slot_player: dict[str, _Pl] = {}

    def take_best(cands: list[_Pl]) -> _Pl | None:
        if not cands:
            return None
        best = max(cands, key=lambda x: (x.score, x.name.lower()))
        used.add(id(best))
        return best

    for slot in slots:
        cands = [
            p for p in pool if id(p) not in used and _natural_fits_slot(p, slot)
        ]
        if not cands:
            cands = [p for p in pool if id(p) not in used and _player_fits_slot(p, slot)]
        if slot.slot_id == "LCM" and len(cands) > 1:
            pref = [p for p in cands if (p.position or "").strip() in ("ЛП", "ЛЦП")]
            cands = pref or cands
        if slot.slot_id == "RCM" and len(cands) > 1:
            pref = [p for p in cands if (p.position or "").strip() in ("ПП", "ПЦП")]
            cands = pref or cands
        if slot.slot_id == "LM" and len(cands) > 1:
            pref = [p for p in cands if (p.position or "").strip() in ("ЛП", "ЛЦП")]
            cands = pref or cands
        if slot.slot_id == "RM" and len(cands) > 1:
            pref = [p for p in cands if (p.position or "").strip() in ("ПП", "ПЦП")]
            cands = pref or cands
        if slot.slot_id == "CAM" and len(cands) > 1:
            pref = [p for p in cands if (p.position or "").strip() == "ЦАП"]
            cands = pref or cands
        if slot.slot_id == "CCM" and len(cands) > 1:
            pref = [p for p in cands if (p.position or "").strip() == "ЦП"]
            cands = pref or cands
        p = take_best(cands)
        if p:
            slot_player[slot.slot_id] = p

    bench = [p for p in pool if id(p) not in used]
    bench.sort(key=lambda x: (-x.score, x.name.lower()))
    return slot_player, bench


# Скамейка: первые N — запасные (как в заявке), остальные — резерв (до 22–25 в составе).
SUBSTITUTES_COUNT = 7
# С позицией строки длиннее — меньше ячеек в ряд, чтобы влезало в ширину PNG.
_BENCH_NAMES_PER_ROW = 5


def _format_bench_cell(p: _Pl) -> str:
    pos = (p.position or "").strip() or "—"
    return f"{_surname(p.name)} {pos} {_display_score(p.overall, p.rating)}"


def _format_bench_rows(players: list[_Pl], per_row: int = _BENCH_NAMES_PER_ROW) -> list[str]:
    chunks: list[str] = []
    row: list[str] = []
    for p in players:
        row.append(_format_bench_cell(p))
        if len(row) >= per_row:
            chunks.append("  ·  ".join(row))
            row = []
    if row:
        chunks.append("  ·  ".join(row))
    return chunks


def _draw_pitch_base(im: Image.Image, draw: ImageDraw.ImageDraw) -> None:
    w, h = im.size
    lo_r, lo_g, lo_b = _GRASS_LO
    hi_r, hi_g, hi_b = _GRASS_HI
    for y in range(h):
        t = y / max(h - 1, 1)
        r = int(lo_r + t * (hi_r - lo_r))
        g = int(lo_g + t * (hi_g - lo_g))
        b = int(lo_b + t * (hi_b - lo_b))
        draw.line([(0, y), (w, y)], fill=(r, g, b))
    margin = 36
    box = [margin, margin, w - margin, h - margin]
    br = 6
    draw.rounded_rectangle(box, radius=br, outline=_LINE_SOFT, width=1)
    cx = w // 2
    my = (box[1] + box[3]) // 2
    draw.line([(box[0], my), (box[2], my)], fill=_LINE_SOFT, width=1)
    draw.ellipse([cx - 70, my - 70, cx + 70, my + 70], outline=_LINE_SOFT, width=1)


def render_squad_pitch_png_bytes(team: str, tournament: str) -> bytes:
    team_db = _team_name_as_in_db(team)
    headline_sub = label_for_squad_caption(team_db)
    players = load_team_squad_players(team, tournament)
    if not players:
        w, h = 920, 400
        im = Image.new("RGB", (w, h), _PAGE_BG)
        draw = ImageDraw.Draw(im)
        for y in range(h):
            t = y / max(h - 1, 1)
            r = int(_PAGE_BG[0] + t * (_PAGE_BG_TOP[0] - _PAGE_BG[0]))
            g = int(_PAGE_BG[1] + t * (_PAGE_BG_TOP[1] - _PAGE_BG[1]))
            b = int(_PAGE_BG[2] + t * (_PAGE_BG_TOP[2] - _PAGE_BG[2]))
            draw.line([(0, y), (w, y)], fill=(r, g, b))
        tf = _pick_font(28, bold=True)
        sf = _pick_font(17, bold=False)
        draw.text((w // 2, 120), team, fill=_SLATE_BRIGHT, font=tf, anchor="mm", stroke_width=1, stroke_fill=(15, 23, 42))
        msg = "В базе нет игроков этой команды для выбранного турнира."
        draw.text((w // 2, 180), msg, fill=_SLATE_MUTED, font=sf, anchor="mm")
        if headline_sub:
            draw.text((w // 2, 220), headline_sub, fill=_SLATE_MUTED, font=sf, anchor="mm")
        out = BytesIO()
        im.save(out, format="PNG", optimize=True)
        return out.getvalue()

    slot_map, bench = _assign_slots(players, team_db)
    slots = get_slots_for_formation_key(resolve_formation_key_for_team(team_db))

    subs = bench[:SUBSTITUTES_COUNT]
    reserves = bench[SUBSTITUTES_COUNT:]
    sub_lines = _format_bench_rows(subs)
    reserve_lines = _format_bench_rows(reserves)

    bench_line_h = 22
    section_title_h = 26
    gap_between_sections = 18
    bottom_pad_top = 14
    bottom_pad_bottom = 28
    bottom_need = bottom_pad_top
    if sub_lines:
        bottom_need += section_title_h + len(sub_lines) * bench_line_h
    if reserve_lines:
        if sub_lines:
            bottom_need += gap_between_sections
        bottom_need += section_title_h + len(reserve_lines) * bench_line_h
    bottom_need += bottom_pad_bottom

    w = 920
    pitch_top = 100
    pitch_hh = 860
    h = pitch_top + pitch_hh + max(bottom_need, 120)

    im = Image.new("RGB", (w, h), _PAGE_BG)
    draw = ImageDraw.Draw(im)
    for y in range(h):
        t = y / max(h - 1, 1)
        r = int(_PAGE_BG[0] + t * (_PAGE_BG_TOP[0] - _PAGE_BG[0]))
        g = int(_PAGE_BG[1] + t * (_PAGE_BG_TOP[1] - _PAGE_BG[1]))
        b = int(_PAGE_BG[2] + t * (_PAGE_BG_TOP[2] - _PAGE_BG[2]))
        draw.line([(0, y), (w, y)], fill=(r, g, b))

    pitch_rect = (28, pitch_top, w - 28, pitch_top + pitch_hh)
    px0, py0, px1, py1 = pitch_rect
    pitch_w = px1 - px0
    pitch_hh = py1 - py0
    sub = Image.new("RGB", (pitch_w, pitch_hh), _GRASS_LO)
    sub_draw = ImageDraw.Draw(sub)
    _draw_pitch_base(sub, sub_draw)
    im.paste(sub, (int(px0), int(py0)))
    pr = 14
    draw.rounded_rectangle(
        [pitch_rect[0] - 2, pitch_rect[1] - 2, pitch_rect[2] + 2, pitch_rect[3] + 2],
        radius=pr,
        outline=_PITCH_FRAME,
        width=2,
    )

    title_font = _pick_font(32, bold=True)
    sub_font = _pick_font(17, bold=False)
    name_font = _pick_font(19, bold=True)
    rating_font = _pick_font(22, bold=True)
    pos_font = _pick_font(11, bold=False)
    bench_font = _pick_font(15, bold=False)
    kit = kit_for_team(team_db)

    title = team
    draw.text(
        (w // 2, 22),
        title,
        fill=_SLATE_BRIGHT,
        font=title_font,
        anchor="mt",
        stroke_width=1,
        stroke_fill=(15, 23, 42),
    )
    if headline_sub:
        draw.text((w // 2, 60), headline_sub, fill=_SLATE_MUTED, font=sub_font, anchor="mt")
    draw.line([(48, 86), (w - 48, 86)], fill=_PITCH_FRAME, width=1)

    for slot in slots:
        pl = slot_map.get(slot.slot_id)
        cx = px0 + slot.x * pitch_w
        cy = py0 + slot.y * pitch_hh
        label = slot.slot_id
        if pl:
            is_gk = slot.slot_id == "GK"
            ix, iy = int(cx), int(cy)
            shirt_cy = iy - 14
            x0, y0, x1, y1 = _draw_shirt(draw, ix, shirt_cy, kit, is_gk)
            score_txt = _display_score(pl.overall, pl.rating)
            bb_r = draw.textbbox((0, 0), score_txt, font=rating_font)
            tw = bb_r[2] - bb_r[0]
            rh = bb_r[3] - bb_r[1]
            rx = x1 + 10
            ry = (y0 + y1) // 2 - rh // 2
            pad_x, pad_y = 6, 4
            draw.rounded_rectangle(
                [rx - pad_x, ry - pad_y, rx + tw + pad_x, ry + rh + pad_y],
                radius=8,
                fill=_BADGE_FILL,
                outline=_BADGE_EDGE,
                width=1,
            )
            draw.text(
                (rx, ry),
                score_txt,
                fill=_SLATE_BRIGHT,
                font=rating_font,
                anchor="lt",
            )
            sur = _surname(pl.name)
            name_y = y1 + 10
            draw.text(
                (ix, name_y),
                sur,
                fill=_SLATE_BRIGHT,
                font=name_font,
                anchor="mt",
                stroke_width=1,
                stroke_fill=(15, 23, 42),
            )
            draw.text((ix, name_y + 21), label, fill=_SLATE_MUTED, font=pos_font, anchor="mt")
        else:
            draw.text((cx, cy), "—", fill=_SLATE_MUTED, font=name_font, anchor="mm")

    if sub_lines or reserve_lines:
        y0 = py1 + bottom_pad_top
        if sub_lines:
            draw.text((28, y0), "Запасные", fill=_SLATE_BRIGHT, font=bench_font)
            y0 += section_title_h - 2
            for line in sub_lines:
                draw.text((28, y0), line, fill=_SLATE_MUTED, font=bench_font)
                y0 += bench_line_h
        if reserve_lines:
            if sub_lines:
                y0 += gap_between_sections
            draw.text((28, y0), "Резерв", fill=_SLATE_BRIGHT, font=bench_font)
            y0 += section_title_h - 2
            for line in reserve_lines:
                draw.text((28, y0), line, fill=(100, 116, 139), font=bench_font)
                y0 += bench_line_h

    out = BytesIO()
    im.save(out, format="PNG", optimize=True)
    return out.getvalue()
