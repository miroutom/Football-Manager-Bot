"""
Состав клуба на схеме поля: слоты из ``team_squad_schemas`` / ``formation_geometry``.

Подбор по слотам: если у команды заданы ``start``/``bench``/``reserve`` в БД, стартовые
ставятся **только** при точном совпадении позиции со слотом (без сдвига линий); при равенстве
слотов (ЦП/ЦАП на LCM/RCM) порядок как в файле заявки, CAM/CCM обрабатываются раньше боковых
центральных. Без статусов — как раньше: лучший рейтинг и взаимозаменяемость при нехватке «своих».

Стартовые 11: флаг по ``nation`` — flagcdn (ISO2 или ``gb-eng`` / ``gb-sct`` / ``gb-wls`` / ``gb-nir``),
кэш ``assets/cache/flags``; иначе упрощённые полосы. Эмблема: ``assets/crests/`` / ``wikimedia_commons.json``; на поле — как есть (пропорции),
без круга; тёмный фон, связный с краем картинки, делается прозрачным. Под заголовком: среднее по стартовым
на поле (overall / rating). Сайдбар: рейтинг, позиция, фамилия.
"""
from __future__ import annotations

import logging
from collections import deque
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
from utils.squad_graphics_assets import (
    commons_crest_filename_for_team,
    load_commons_crest_rgba,
    load_flag_png,
)
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
_RATING_TEXT = (190, 244, 210)

_CANVAS_W = 1208
_MARGINS_X = 18
_SIDEBAR_W = 300
_CONTENT_TOP = 96
_PITCH_H = 736
_SIDEBAR_BG = (28, 58, 158)
_SIDEBAR_BG_STRIPE = (22, 48, 130)
_SIDEBAR_EDGE = (96, 165, 250)
_FLAG_W = 22
_FLAG_H = 15
_SIDEBAR_LIST_TOP = 108
_SIDEBAR_ROW_H = 28
_PROJECT_ROOT = Path(__file__).resolve().parent.parent
_CREST_DIR = _PROJECT_ROOT / "assets" / "crests"


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


def _player_name_key(full_name: str) -> str:
    """Ключ дедупликации: нормализованное ФИО (один игрок = одна строка в ростере)."""
    return " ".join((full_name or "").split()).lower()


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


def _numeric_for_average(overall: int, rating: float) -> float | None:
    """Число для среднего по стартовым: приоритет overall, иначе rating (как на футболке)."""
    o = int(overall or 0)
    if o > 0:
        return float(o)
    r = float(rating or 0.0)
    if r > 0:
        return r
    return None


def _starting_xi_avg_fragment(slot_player: dict[str, _Pl]) -> str | None:
    """Среднее по игрокам на поле (занятые слоты формации)."""
    vals: list[float] = []
    for pl in slot_player.values():
        if pl is None:
            continue
        n = _numeric_for_average(pl.overall, pl.rating)
        if n is not None:
            vals.append(n)
    if not vals:
        return None
    return f"ср. старт {sum(vals) / len(vals):.1f}"


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
    nation: str | None
    status: str | None = None
    roster_rank: int = 9999


def _roster_order_map(team_db: str) -> dict[str, int]:
    """Порядок строк в заявке (АПЛ / Бундес): для сопоставления слотов при нескольких «своих»."""
    from data.england_apl_squads import ENGLAND_APL_SQUADS
    from data.germany_bundesliga_squads import GERMANY_BUNDESLIGA_SQUADS
    from data.italy_seria_a_squads import ITALY_SERIE_A_SQUADS
    from data.spain_la_liga_squads import SPAIN_LA_LIGA_SQUADS

    for squads in (
        ENGLAND_APL_SQUADS,
        GERMANY_BUNDESLIGA_SQUADS,
        ITALY_SERIE_A_SQUADS,
        SPAIN_LA_LIGA_SQUADS,
    ):
        rows = squads.get(team_db)
        if rows:
            return {_player_name_key(str(r[0])): i for i, r in enumerate(rows)}
    return {}


def _overlay_declared_roster(out: list[_Pl], team_db: str) -> None:
    """Поля позиция/нация/статус/overall из файла заявки — 1:1 с таблицей, даже если БД ещё не синкнута."""
    from data.england_apl_squads import ENGLAND_APL_SQUADS
    from data.germany_bundesliga_squads import GERMANY_BUNDESLIGA_SQUADS
    from data.italy_seria_a_squads import ITALY_SERIE_A_SQUADS
    from data.spain_la_liga_squads import SPAIN_LA_LIGA_SQUADS

    rows = None
    for squads in (
        ENGLAND_APL_SQUADS,
        GERMANY_BUNDESLIGA_SQUADS,
        ITALY_SERIE_A_SQUADS,
        SPAIN_LA_LIGA_SQUADS,
    ):
        if team_db in squads:
            rows = squads[team_db]
            break
    if not rows:
        return
    by_key: dict[str, tuple] = {_player_name_key(str(r[0])): r for r in rows}
    for p in out:
        r = by_key.get(_player_name_key(p.name))
        if r is None:
            continue
        _nm, pos, ov, nation, st = r[0], r[1], r[2], r[3], r[4]
        p.position = (str(pos) if pos is not None else "").strip()
        if nation is not None and str(nation).strip():
            p.nation = str(nation).strip()
        sx = (str(st) if st is not None else "").strip().lower()
        if sx in ("start", "bench", "reserve"):
            p.status = sx
        if int(ov or 0) > 0:
            p.overall = int(ov)
        p.tags = _position_tags(p.position)
        p.score = _player_score(p.overall, p.rating)


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
            nat = getattr(p, "nation", None)
            if nat is not None:
                nat = str(nat).strip() or None
            st = getattr(p, "status", None)
            if st is not None:
                st = str(st).strip().lower() or None
                if st not in ("start", "bench", "reserve"):
                    st = None
            out.append(
                _Pl(
                    name=p.name,
                    position=pos,
                    overall=ov,
                    rating=rt,
                    tags=tags,
                    score=_player_score(ov, rt),
                    nation=nat,
                    status=st,
                    roster_rank=9999,
                )
            )
    out = _dedupe_squad_pl_by_name(out)
    _overlay_declared_roster(out, team_db)
    order = _roster_order_map(team_db)
    for p in out:
        p.roster_rank = order.get(_player_name_key(p.name), 9999)
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


def _nation_to_flagcdn_code(raw: str | None) -> str | None:
    """Код для flagcdn: ISO2 в нижнем регистре (``de``) или UK-подрегион ``gb-eng`` … ``gb-nir``."""
    if not raw:
        return None
    s = str(raw).strip().replace("\u2019", "'").replace("\u2018", "'").upper()
    if not s:
        return None
    if len(s) == 2 and s.isalpha():
        return s.lower()
    ru: dict[str, str] = {
        "РОССИЯ": "ru",
        "РФ": "ru",
        "ИСПАНИЯ": "es",
        "ИТАЛИЯ": "it",
        "ФРАНЦИЯ": "fr",
        "ГЕРМАНИЯ": "de",
        "АНГЛИЯ": "gb-eng",
        "ШОТЛАНДИЯ": "gb-sct",
        "УЭЛЬС": "gb-wls",
        "СЕВЕРНАЯ ИРЛАНДИЯ": "gb-nir",
        "ОЛСТЕР": "gb-nir",
        "ВЕЛИКОБРИТАНИЯ": "gb",
        "БРИТАНИЯ": "gb",
        "ИРЛАНДИЯ": "ie",
        "БРАЗИЛИЯ": "br",
        "АРГЕНТИНА": "ar",
        "ПОРТУГАЛИЯ": "pt",
        "ПОЛЬША": "pl",
        "УКРАИНА": "ua",
        "ХОРВАТИЯ": "hr",
        "СЕРБИЯ": "rs",
        "БЕЛЬГИЯ": "be",
        "НИДЕРЛАНДЫ": "nl",
        "ГОЛЛАНДИЯ": "nl",
        "АВСТРИЯ": "at",
        "ШВЕЙЦАРИЯ": "ch",
        "ШВЕЦИЯ": "se",
        "НОРВЕГИЯ": "no",
        "ДАНИЯ": "dk",
        "ФИНЛЯНДИЯ": "fi",
        "ТУРЦИЯ": "tr",
        "ГРЕЦИЯ": "gr",
        "ЧЕХИЯ": "cz",
        "СЛОВАКИЯ": "sk",
        "ВЕНГРИЯ": "hu",
        "РУМЫНИЯ": "ro",
        "БОЛГАРИЯ": "bg",
        "ЯПОНИЯ": "jp",
        "КОРЕЯ": "kr",
        "ЮЖНАЯ КОРЕЯ": "kr",
        "КНР": "cn",
        "США": "us",
        "МЕКСИКА": "mx",
        "КАНАДА": "ca",
        "АВСТРАЛИЯ": "au",
        "НИГЕРИЯ": "ng",
        "ГАНА": "gh",
        "СЕНЕГАЛ": "sn",
        "МАРОККО": "ma",
        "АЛЖИР": "dz",
        "ЕГИПЕТ": "eg",
        "УРУГВАЙ": "uy",
        "КОЛУМБИЯ": "co",
        "ЧИЛИ": "cl",
        "ЭКВАДОР": "ec",
        "КАМЕРУН": "cm",
        "ЯМАЙКА": "jm",
        "ТОГО": "tg",
        "БУРКИНА-ФАСО": "bf",
        "БУРКИНАФАСО": "bf",
        "КОТ-Д'ИВУАР": "ci",
        "ИРАН": "ir",
        "ПАРАГВАЙ": "py",
        "АНГОЛА": "ao",
        "АЛБАНИЯ": "al",
        "ЧЕРНОГОРИЯ": "me",
        "КОСОВО": "xk",
        "СЕВЕРНАЯ МАКЕДОНИЯ": "mk",
        "МАКЕДОНИЯ": "mk",
        "ЭКВАТОРИАЛЬНАЯ ГВИНЕЯ": "gq",
        "СЛОВЕНИЯ": "si",
        "БОСНИЯ": "ba",
        "ИСРАИЛЬ": "il",
        "ГРУЗИЯ": "ge",
        "АРМЕНИЯ": "am",
        "АЗЕРБАЙДЖАН": "az",
        "КАЗАХСТАН": "kz",
        "УЗБЕКИСТАН": "uz",
        "БОЛИВИЯ": "bo",
        "ВЕНЕСУЭЛА": "ve",
        "МОЗАМБИК": "mz",
        "КАБО-ВЕРДЕ": "cv",
        "ДОМИНИКАНСКАЯ РЕСПУБЛИКА": "do",
    }
    en: dict[str, str] = {
        "ENGLAND": "gb-eng",
        "SCOTLAND": "gb-sct",
        "WALES": "gb-wls",
        "NORTHERN IRELAND": "gb-nir",
        "UNITED KINGDOM": "gb",
        "GREAT BRITAIN": "gb",
        "UK": "gb",
        "IRELAND": "ie",
        "REPUBLIC OF IRELAND": "ie",
        "RUSSIA": "ru",
        "SPAIN": "es",
        "ITALY": "it",
        "FRANCE": "fr",
        "GERMANY": "de",
        "BRAZIL": "br",
        "ARGENTINA": "ar",
        "PORTUGAL": "pt",
        "POLAND": "pl",
        "UKRAINE": "ua",
        "CROATIA": "hr",
        "SERBIA": "rs",
        "BELGIUM": "be",
        "NETHERLANDS": "nl",
        "AUSTRIA": "at",
        "SWITZERLAND": "ch",
        "SWEDEN": "se",
        "NORWAY": "no",
        "DENMARK": "dk",
        "FINLAND": "fi",
        "TURKEY": "tr",
        "GREECE": "gr",
        "CZECHIA": "cz",
        "CZECH REPUBLIC": "cz",
        "SLOVAKIA": "sk",
        "ROMANIA": "ro",
        "BULGARIA": "bg",
        "JAPAN": "jp",
        "SOUTH KOREA": "kr",
        "CHINA": "cn",
        "USA": "us",
        "MEXICO": "mx",
        "CANADA": "ca",
        "AUSTRALIA": "au",
        "NIGERIA": "ng",
        "GHANA": "gh",
        "SENEGAL": "sn",
        "MOROCCO": "ma",
        "ALGERIA": "dz",
        "EGYPT": "eg",
        "URUGUAY": "uy",
        "COLOMBIA": "co",
        "CHILE": "cl",
        "ECUADOR": "ec",
        "CAMEROON": "cm",
        "JAMAICA": "jm",
        "TOGO": "tg",
        "BURKINA FASO": "bf",
        "IVORY COAST": "ci",
        "COTE D'IVOIRE": "ci",
        "CÔTE D'IVOIRE": "ci",
        "IRAN": "ir",
        "PARAGUAY": "py",
        "ANGOLA": "ao",
        "ALBANIA": "al",
        "MONTENEGRO": "me",
        "KOSOVO": "xk",
        "NORTH MACEDONIA": "mk",
        "MACEDONIA": "mk",
        "EQUATORIAL GUINEA": "gq",
        "SLOVENIA": "si",
        "BOSNIA": "ba",
        "ISRAEL": "il",
        "GEORGIA": "ge",
        "ARMENIA": "am",
        "AZERBAIJAN": "az",
        "KAZAKHSTAN": "kz",
        "UZBEKISTAN": "uz",
        "BOLIVIA": "bo",
        "VENEZUELA": "ve",
        "MOZAMBIQUE": "mz",
        "CAPE VERDE": "cv",
        "CABO VERDE": "cv",
        "DOMINICAN REPUBLIC": "do",
    }
    return ru.get(s) or en.get(s)


_FLAG_V3: dict[str, tuple[tuple[int, int, int], tuple[int, int, int], tuple[int, int, int]]] = {
    "RU": ((255, 255, 255), (0, 57, 166), (213, 43, 30)),
    "FR": ((0, 85, 164), (255, 255, 255), (239, 65, 53)),
    "DE": ((0, 0, 0), (221, 0, 0), (255, 204, 0)),
    "IT": ((0, 140, 69), (255, 255, 255), (206, 43, 55)),
    "ES": ((170, 0, 0), (252, 194, 27), (170, 0, 0)),
    "BE": ((0, 0, 0), (255, 215, 0), (255, 0, 0)),
    "NL": ((174, 28, 40), (255, 255, 255), (33, 70, 139)),
    "GB": ((0, 36, 125), (255, 255, 255), (204, 0, 0)),
    "gb-eng": ((255, 255, 255), (200, 30, 50), (255, 255, 255)),
    "gb-sct": ((0, 36, 125), (255, 255, 255), (0, 36, 125)),
    "gb-wls": ((33, 115, 70), (255, 255, 255), (206, 17, 38)),
    "gb-nir": ((255, 255, 255), (206, 20, 43), (0, 56, 120)),
    "PT": ((6, 115, 57), (255, 0, 0), (6, 115, 57)),
    "BR": ((0, 156, 59), (255, 223, 0), (0, 39, 118)),
    "AR": ((116, 172, 223), (255, 255, 255), (116, 172, 223)),
    "PL": ((255, 255, 255), (220, 20, 60), (255, 255, 255)),
    "UA": ((0, 91, 187), (255, 213, 0), (0, 91, 187)),
    "HR": ((255, 0, 0), (255, 255, 255), (23, 23, 150)),
    "RS": ((198, 54, 60), (14, 84, 176), (255, 255, 255)),
    "CH": ((255, 0, 0), (255, 255, 255), (255, 0, 0)),
    "AT": ((255, 0, 0), (255, 255, 255), (255, 0, 0)),
    "SE": ((0, 106, 167), (254, 204, 0), (0, 106, 167)),
    "NO": ((186, 12, 47), (255, 255, 255), (0, 32, 91)),
    "DK": ((198, 12, 48), (255, 255, 255), (198, 12, 48)),
    "FI": ((255, 255, 255), (0, 53, 128), (255, 255, 255)),
    "TR": ((227, 10, 23), (255, 255, 255), (227, 10, 23)),
    "US": ((178, 34, 52), (255, 255, 255), (60, 59, 110)),
    "MX": ((0, 104, 71), (255, 255, 255), (206, 17, 38)),
    "JP": ((255, 255, 255), (188, 0, 45), (255, 255, 255)),
    "KR": ((205, 0, 26), (255, 255, 255), (0, 56, 168)),
    "NG": ((0, 135, 81), (255, 255, 255), (0, 135, 81)),
    "GH": ((206, 17, 38), (252, 209, 22), (0, 107, 63)),
    "SN": ((0, 133, 63), (227, 27, 35), (227, 27, 35)),
    "MA": ((193, 39, 45), (0, 98, 51), (193, 39, 45)),
    "EG": ((0, 0, 0), (255, 255, 255), (206, 17, 38)),
    "CO": ((252, 209, 22), (0, 56, 168), (213, 9, 27)),
    "CL": ((213, 43, 30), (255, 255, 255), (0, 57, 166)),
    "EC": ((252, 209, 22), (0, 56, 168), (206, 17, 38)),
    "CM": ((0, 122, 94), (206, 17, 38), (252, 209, 22)),
    "JM": ((0, 155, 58), (252, 209, 22), (0, 0, 0)),
    "TG": ((0, 122, 61), (252, 209, 22), (206, 17, 38)),
    "BF": ((206, 17, 38), (0, 122, 61), (252, 209, 22)),
    "CI": ((252, 209, 22), (255, 255, 255), (0, 135, 81)),
    "UY": ((0, 56, 168), (255, 255, 255), (0, 56, 168)),
    "CZ": ((215, 20, 26), (255, 255, 255), (17, 69, 126)),
    "SK": ((255, 255, 255), (11, 100, 185), (238, 28, 37)),
    "HU": ((205, 42, 62), (255, 255, 255), (67, 111, 77)),
    "RO": ((0, 43, 127), (252, 209, 22), (206, 17, 38)),
    "BG": ((255, 255, 255), (0, 150, 110), (214, 38, 18)),
    "GR": ((13, 94, 175), (255, 255, 255), (13, 94, 175)),
    "IE": ((22, 155, 98), (255, 255, 255), (255, 134, 92)),
    "CA": ((255, 0, 0), (255, 255, 255), (255, 0, 0)),
    "AU": ((0, 0, 139), (255, 255, 255), (255, 0, 0)),
    "NZ": ((0, 0, 0), (255, 255, 255), (204, 0, 0)),
    "IL": ((0, 56, 184), (255, 255, 255), (0, 56, 184)),
    "GE": ((255, 255, 255), (255, 0, 0), (255, 255, 255)),
    "KZ": ((0, 127, 255), (255, 215, 0), (0, 127, 255)),
    "CN": ((222, 41, 16), (255, 222, 0), (222, 41, 16)),
    "IR": ((35, 159, 64), (255, 255, 255), (213, 39, 48)),
    "MK": ((206, 17, 38), (252, 209, 22), (206, 17, 38)),
    "GQ": ((62, 112, 189), (255, 255, 255), (62, 112, 189)),
    "PY": ((206, 17, 38), (255, 255, 255), (0, 56, 168)),
    "AL": ((206, 17, 38), (0, 0, 0), (206, 17, 38)),
    "ME": ((206, 17, 38), (252, 209, 22), (206, 17, 38)),
    "XK": ((36, 74, 165), (252, 209, 22), (255, 255, 255)),
    "AO": ((206, 17, 38), (0, 0, 0), (206, 17, 38)),
    "BO": ((206, 17, 38), (252, 209, 22), (0, 121, 52)),
    "VE": ((207, 20, 43), (252, 209, 22), (0, 36, 148)),
    "MZ": ((0, 107, 63), (0, 0, 0), (252, 209, 22)),
    "CV": ((0, 56, 168), (252, 209, 22), (206, 17, 38)),
    "DO": ((0, 36, 148), (255, 255, 255), (206, 17, 38)),
}


def _flag_v3_trip(flag_code: str | None) -> tuple[tuple[int, int, int], tuple[int, int, int], tuple[int, int, int]] | None:
    if not flag_code:
        return None
    c = flag_code.strip().lower()
    if len(c) == 6 and c[2] == "-" and c[:2].isalpha() and c[3:].isalpha() and len(c[3:]) == 3:
        return _FLAG_V3.get(c)
    if len(c) == 2 and c.isalpha():
        return _FLAG_V3.get(c.upper())
    return None


def _paste_or_draw_flag(
    im: Image.Image,
    draw: ImageDraw.ImageDraw,
    x: int,
    y: int,
    nation: str | None,
) -> None:
    fcode = _nation_to_flagcdn_code(nation)
    fimg = load_flag_png(fcode) if fcode else None
    if fimg is not None:
        tw, th = _FLAG_W, _FLAG_H
        thumb = fimg.resize((tw, th), Image.Resampling.LANCZOS)
        mask = Image.new("L", (tw, th), 0)
        ImageDraw.Draw(mask).rounded_rectangle([0, 0, tw - 1, th - 1], radius=3, fill=255)
        im.paste(thumb, (x, y), mask)
        return
    _draw_mini_flag(draw, x, y, nation)


def _draw_mini_flag(draw: ImageDraw.ImageDraw, x: int, y: int, nation: str | None) -> None:
    trip = _flag_v3_trip(_nation_to_flagcdn_code(nation))
    if trip is None:
        draw.rounded_rectangle(
            [x, y, x + _FLAG_W, y + _FLAG_H],
            radius=3,
            fill=(51, 65, 85),
            outline=(71, 85, 105),
            width=1,
        )
        return
    seg = _FLAG_W / 3.0
    for i, col in enumerate(trip):
        xa = int(x + i * seg)
        xb = int(x + (i + 1) * seg) if i < 2 else x + _FLAG_W
        draw.rectangle([xa, y, xb, y + _FLAG_H], fill=col)
    draw.rounded_rectangle(
        [x, y, x + _FLAG_W, y + _FLAG_H],
        radius=3,
        outline=(15, 23, 42),
        width=1,
    )


def _sidebar_bench_content_height(subs: list[_Pl], reserves: list[_Pl]) -> int:
    """Минимальная высота поля/сайдбара, чтобы влезли списки запасных и резерва."""
    row = _SIDEBAR_ROW_H
    h = _SIDEBAR_LIST_TOP + 28 + len(subs) * row + 10
    if reserves:
        h += 26 + len(reserves) * row
    return h + 28


def _sidebar_bench_line(p: _Pl) -> str:
    pos = (p.position or "").strip() or "—"
    score = _display_score(p.overall, p.rating)
    return f"{score}  {pos}  {_surname(p.name)}"


def _crest_initials(team_db: str) -> str:
    t = (team_db or "").strip()
    if not t:
        return "?"
    if len(t) <= 2:
        return t.upper()
    parts = t.replace("-", " ").split()
    if len(parts) >= 2 and parts[0] and parts[1]:
        return (parts[0][0] + parts[1][0]).upper()
    return t[:2].upper()


def _try_load_crest_rgba(team_db: str) -> Image.Image | None:
    """Локальный файл в ``assets/crests/``, иначе Wikimedia Commons по ``wikimedia_commons.json``."""
    base = (team_db or "").strip()
    if not base:
        return None
    if _CREST_DIR.is_dir():
        for name in (base, base.replace(" ", "_")):
            for ext in (".png", ".webp", ".jpg", ".jpeg"):
                path = _CREST_DIR / f"{name}{ext}"
                if path.is_file():
                    try:
                        return Image.open(path).convert("RGBA")
                    except OSError:
                        logger.warning("Состав: не удалось открыть эмблему %s", path)
                        return None
    cfn = commons_crest_filename_for_team(base)
    if cfn:
        cr = load_commons_crest_rgba(cfn)
        if cr is not None:
            return cr
    return None


def _crest_dematte_linked_dark_from_edges(rgba: Image.Image, rgb_lim: int = 40) -> Image.Image:
    """Делает прозрачным тёмный фон, 4-связный с краями изображения (часто чёрная «подложка» с Wiki)."""
    im = rgba.copy()
    w, h = im.size
    if w < 2 or h < 2:
        return im
    px = im.load()

    def dark(r: int, g: int, b: int, a: int) -> bool:
        return a > 48 and r <= rgb_lim and g <= rgb_lim and b <= rgb_lim

    q: deque[tuple[int, int]] = deque()
    seen: set[tuple[int, int]] = set()
    for x in range(w):
        for y in (0, h - 1):
            t = (x, y)
            if t not in seen and dark(*px[x, y]):
                seen.add(t)
                q.append(t)
    for y in range(h):
        for x in (0, w - 1):
            t = (x, y)
            if t not in seen and dark(*px[x, y]):
                seen.add(t)
                q.append(t)
    while q:
        x, y = q.popleft()
        r, g, b, a = px[x, y]
        if not dark(r, g, b, a):
            continue
        px[x, y] = (r, g, b, 0)
        for nx, ny in ((x + 1, y), (x - 1, y), (x, y + 1), (x, y - 1)):
            if nx < 0 or ny < 0 or nx >= w or ny >= h:
                continue
            nt = (nx, ny)
            if nt in seen:
                continue
            rr, gg, bb, aa = px[nx, ny]
            if dark(rr, gg, bb, aa):
                seen.add(nt)
                q.append(nt)
    return im


def _paste_crest_natural(im: Image.Image, crest: Image.Image, cx: int, cy: int, max_side: int) -> None:
    """Вписывает эмблему в квадрат max_side×max_side без искажения пропорций, без круглой маски."""
    work = crest.convert("RGBA")
    work = _crest_dematte_linked_dark_from_edges(work)
    thumb = work.copy()
    thumb.thumbnail((max_side, max_side), Image.Resampling.LANCZOS)
    nw, nh = thumb.size
    if nw < 1 or nh < 1:
        return
    left = int(cx - nw // 2)
    top = int(cy - nh // 2)
    im.paste(thumb, (left, top), thumb)


def _draw_crest_placeholder(
    draw: ImageDraw.ImageDraw,
    cx: int,
    cy: int,
    team_db: str,
    kit: KitSpec,
    font: ImageFont.ImageFont,
) -> None:
    r = 38
    prim = kit.primary
    lum = sum(prim)
    edge = (220, 228, 236) if lum > 380 else (148, 163, 184)
    txt = (248, 250, 252) if lum < 340 else (30, 41, 59)
    draw.ellipse([cx - r, cy - r, cx + r, cy + r], fill=prim, outline=edge, width=2)
    draw.text((cx, cy), _crest_initials(team_db), fill=txt, font=font, anchor="mm")


def _draw_sidebar_background(draw: ImageDraw.ImageDraw, rect: tuple[int, int, int, int]) -> None:
    x0, y0, x1, y1 = rect
    draw.rounded_rectangle(
        [x0, y0, x1, y1],
        radius=18,
        fill=_SIDEBAR_BG,
        outline=_SIDEBAR_EDGE,
        width=1,
    )


def _draw_sidebar_text(
    draw: ImageDraw.ImageDraw,
    *,
    subs: list[_Pl],
    reserves: list[_Pl],
    rect: tuple[int, int, int, int],
    title_font: ImageFont.ImageFont,
    row_font: ImageFont.ImageFont,
) -> None:
    x0, y0, x1, y1 = rect
    pad = 14
    ty = y0 + _SIDEBAR_LIST_TOP
    draw.text((x0 + pad, ty), "Запасные", fill=_SLATE_BRIGHT, font=title_font, anchor="lt")
    ty += 28
    row_h = _SIDEBAR_ROW_H
    for i, p in enumerate(subs):
        ry0 = ty + i * row_h
        stripe = _SIDEBAR_BG_STRIPE if i % 2 else (24, 54, 145)
        draw.rectangle([x0 + 8, ry0, x1 - 8, ry0 + row_h - 3], fill=stripe)
        draw.text((x0 + pad, ry0 + 4), _sidebar_bench_line(p), fill=_SLATE_BRIGHT, font=row_font, anchor="lt")
    ty += len(subs) * row_h + 10
    if reserves:
        draw.text((x0 + pad, ty), "Резерв", fill=(191, 219, 254), font=title_font, anchor="lt")
        ty += 26
        base_i = len(subs)
        for j, p in enumerate(reserves):
            i = base_i + j
            ry0 = ty + j * row_h
            stripe = _SIDEBAR_BG_STRIPE if i % 2 else (24, 54, 145)
            draw.rectangle([x0 + 8, ry0, x1 - 8, ry0 + row_h - 3], fill=stripe)
            draw.text(
                (x0 + pad, ry0 + 4),
                _sidebar_bench_line(p),
                fill=_SLATE_BRIGHT,
                font=row_font,
                anchor="lt",
            )


def _norm_pl_status(p: _Pl) -> str:
    s = (p.status or "").strip().lower()
    return s if s in ("start", "bench", "reserve") else ""


# Один ФИО — одна карточка: при дублях в БД (разные позиции/таблицы) оставляем заявку старт/скамейка.
_DEDUPE_STATUS_RANK: dict[str, int] = {"start": 0, "bench": 1, "reserve": 2, "": 3}


def _dedupe_squad_pl_by_name(rows: list[_Pl]) -> list[_Pl]:
    buckets: dict[str, list[_Pl]] = {}
    for p in rows:
        k = _player_name_key(p.name)
        if not k:
            continue
        buckets.setdefault(k, []).append(p)
    out: list[_Pl] = []
    for _k, group in buckets.items():
        if len(group) == 1:
            out.append(group[0])
            continue
        best = min(
            group,
            key=lambda p: (
                _DEDUPE_STATUS_RANK.get(_norm_pl_status(p), 3),
                -p.score,
                (p.name or "").lower(),
            ),
        )
        out.append(best)
    return out


def _slots_explicit_order(slots: tuple[SquadSlot, ...]) -> tuple[SquadSlot, ...]:
    """CAM/CCM раньше полузащиты; LM/RM раньше LCM/RCM (иначе ПП уходит в RCM и опустошает фланг)."""
    late_ids = frozenset({"LCM", "RCM", "LM", "RM"})
    cam_ids = frozenset({"CAM", "CCM"})
    early = [s for s in slots if s.slot_id not in late_ids and s.slot_id not in cam_ids]
    mid = [s for s in slots if s.slot_id in cam_ids]
    wide = [s for s in slots if s.slot_id in ("LM", "RM")]
    edge_cm = [s for s in slots if s.slot_id in ("LCM", "RCM")]
    return tuple(early + mid + wide + edge_cm)


def _place_on_slot_explicit(slot: SquadSlot, pool: list[_Pl], used: set[int]) -> _Pl | None:
    cands = [p for p in pool if id(p) not in used and _natural_fits_slot(p, slot)]
    if not cands:
        return None
    if slot.slot_id == "LCM" and len(cands) > 1:
        pref = [p for p in cands if (p.position or "").strip() in ("ЛП", "ЛЦП")]
        if pref:
            cands = pref
    if slot.slot_id == "RCM" and len(cands) > 1:
        pref = [p for p in cands if (p.position or "").strip() in ("ПП", "ПЦП")]
        if pref:
            cands = pref
    if slot.slot_id == "LM" and len(cands) > 1:
        pref = [p for p in cands if (p.position or "").strip() in ("ЛП", "ЛЦП")]
        if pref:
            cands = pref
    if slot.slot_id == "RM" and len(cands) > 1:
        pref = [p for p in cands if (p.position or "").strip() in ("ПП", "ПЦП")]
        if pref:
            cands = pref
    if slot.slot_id == "CAM" and len(cands) > 1:
        pref = [p for p in cands if (p.position or "").strip() == "ЦАП"]
        if pref:
            cands = pref
    if slot.slot_id == "CCM" and len(cands) > 1:
        pref_cdm = [p for p in cands if (p.position or "").strip() == "ЦОП"]
        if pref_cdm:
            cands = pref_cdm
        else:
            pref = [p for p in cands if (p.position or "").strip() == "ЦП"]
            if pref:
                cands = pref
    if slot.slot_id == "ST" and len(cands) > 1:
        pref = [p for p in cands if (p.position or "").strip() == "ФРВ"]
        if pref:
            cands = pref
    if slot.slot_id == "CF" and len(cands) > 1:
        pref = [p for p in cands if (p.position or "").strip() == "ЦФД"]
        if pref:
            cands = pref
    best = min(cands, key=lambda p: (p.roster_rank, -p.score, (p.name or "").lower()))
    used.add(id(best))
    return best


def _place_on_slot(slot: SquadSlot, pool: list[_Pl], used: set[int]) -> _Pl | None:
    cands = [p for p in pool if id(p) not in used and _natural_fits_slot(p, slot)]
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
        pref_cdm = [p for p in cands if (p.position or "").strip() == "ЦОП"]
        if pref_cdm:
            cands = pref_cdm
        else:
            pref = [p for p in cands if (p.position or "").strip() == "ЦП"]
            cands = pref or cands
    if not cands:
        return None
    best = max(cands, key=lambda x: (x.score, x.name.lower()))
    used.add(id(best))
    return best


def _assign_slots(players: list[_Pl], team_db: str) -> tuple[dict[str, _Pl], list[_Pl]]:
    slots = get_slots_for_formation_key(resolve_formation_key_for_team(team_db))
    explicit = any(_norm_pl_status(p) for p in players)
    if not explicit:
        pool = players[:]
        used: set[int] = set()
        slot_player: dict[str, _Pl] = {}
        for slot in slots:
            p = _place_on_slot(slot, pool, used)
            if p:
                slot_player[slot.slot_id] = p
        bench = [p for p in pool if id(p) not in used]
        bench.sort(key=lambda x: (-x.score, x.name.lower()))
        return slot_player, bench

    starters = [p for p in players if _norm_pl_status(p) == "start"]
    used: set[int] = set()
    slot_player: dict[str, _Pl] = {}
    slot_iter = _slots_explicit_order(slots)
    for slot in slot_iter:
        placed = _place_on_slot_explicit(slot, starters, used)
        if placed:
            slot_player[slot.slot_id] = placed
    bench = [p for p in players if id(p) not in used]
    bench.sort(
        key=lambda p: (
            0 if _norm_pl_status(p) == "bench" else 1 if _norm_pl_status(p) == "reserve" else 2,
            -p.score,
            p.name.lower(),
        )
    )
    return slot_player, bench


# Скамейка: первые N — запасные (как в заявке), остальные — резерв (до 22–25 в составе).
SUBSTITUTES_COUNT = 7


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
    w = _CANVAS_W

    if not players:
        h = 420
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
        draw.text(
            (w // 2, 130),
            team,
            fill=_SLATE_BRIGHT,
            font=tf,
            anchor="mm",
            stroke_width=1,
            stroke_fill=(15, 23, 42),
        )
        msg = "В базе нет игроков этой команды для выбранного турнира."
        draw.text((w // 2, 190), msg, fill=_SLATE_MUTED, font=sf, anchor="mm")
        if headline_sub:
            draw.text((w // 2, 230), headline_sub, fill=_SLATE_MUTED, font=sf, anchor="mm")
        out = BytesIO()
        im.save(out, format="PNG", optimize=True)
        return out.getvalue()

    slot_map, bench = _assign_slots(players, team_db)
    on_field_names = { _player_name_key(p.name) for p in slot_map.values() if p is not None }
    bench = [p for p in bench if _player_name_key(p.name) not in on_field_names]
    slots = get_slots_for_formation_key(resolve_formation_key_for_team(team_db))
    subs = bench[:SUBSTITUTES_COUNT]
    reserves = bench[SUBSTITUTES_COUNT:]

    pitch_body_h = max(_PITCH_H, _sidebar_bench_content_height(subs, reserves))
    h = _CONTENT_TOP + pitch_body_h + 36
    im = Image.new("RGB", (w, h), _PAGE_BG)
    draw = ImageDraw.Draw(im)
    for y in range(h):
        t = y / max(h - 1, 1)
        r = int(_PAGE_BG[0] + t * (_PAGE_BG_TOP[0] - _PAGE_BG[0]))
        g = int(_PAGE_BG[1] + t * (_PAGE_BG_TOP[1] - _PAGE_BG[1]))
        b = int(_PAGE_BG[2] + t * (_PAGE_BG_TOP[2] - _PAGE_BG[2]))
        draw.line([(0, y), (w, y)], fill=(r, g, b))

    px0 = _MARGINS_X
    px1 = w - _MARGINS_X - _SIDEBAR_W
    py0 = _CONTENT_TOP
    py1 = py0 + pitch_body_h
    pitch_w = px1 - px0
    pitch_hh = py1 - py0

    sub = Image.new("RGB", (pitch_w, pitch_hh), _GRASS_LO)
    sub_draw = ImageDraw.Draw(sub)
    _draw_pitch_base(sub, sub_draw)
    im.paste(sub, (int(px0), int(py0)))
    draw.rounded_rectangle(
        [px0 - 2, py0 - 2, px1 + 2, py1 + 2],
        radius=14,
        outline=_PITCH_FRAME,
        width=2,
    )

    sidebar_rect = (px1, py0, w - _MARGINS_X, py1)
    _draw_sidebar_background(draw, sidebar_rect)
    sb_title = _pick_font(17, bold=True)
    sb_row = _pick_font(14, bold=False)

    kit = kit_for_team(team_db)
    title_font = _pick_font(32, bold=True)
    sub_font = _pick_font(17, bold=False)
    name_font = _pick_font(19, bold=True)
    rating_font = _pick_font(22, bold=True)
    pos_font = _pick_font(11, bold=False)
    crest_font = _pick_font(22, bold=True)

    crest_cx = int(px1)
    crest_cy = int(py0 + 56)
    crest_max = 78
    crest_img = _try_load_crest_rgba(team_db)
    if crest_img is not None:
        _paste_crest_natural(im, crest_img, crest_cx, crest_cy, crest_max)
    else:
        _draw_crest_placeholder(draw, crest_cx, crest_cy, team_db, kit, crest_font)

    shirt_bw = 48
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
            flag_x = int(ix - shirt_bw // 2 - 8 - _FLAG_W)
            flag_y = int(shirt_cy - _FLAG_H // 2)
            _paste_or_draw_flag(im, draw, flag_x, flag_y, pl.nation)
            score_txt = _display_score(pl.overall, pl.rating)
            bb_r = draw.textbbox((0, 0), score_txt, font=rating_font)
            rh = bb_r[3] - bb_r[1]
            rx = x1 + 8
            ry = (y0 + y1) // 2 - rh // 2
            draw.text((rx, ry), score_txt, fill=_RATING_TEXT, font=rating_font, anchor="lt")
            sur = _surname(pl.name)
            name_y = y1 + 10
            draw.text((ix, name_y), sur, fill=_SLATE_BRIGHT, font=name_font, anchor="mt")
            draw.text((ix, name_y + 21), label, fill=_SLATE_MUTED, font=pos_font, anchor="mt")
        else:
            draw.text((cx, cy), "—", fill=_SLATE_MUTED, font=name_font, anchor="mm")

    _draw_sidebar_text(
        draw,
        subs=subs,
        reserves=reserves,
        rect=sidebar_rect,
        title_font=sb_title,
        row_font=sb_row,
    )

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
    avg_frag = _starting_xi_avg_fragment(slot_map)
    sub_parts = [p for p in (headline_sub, avg_frag) if p]
    if sub_parts:
        draw.text(
            (w // 2, 60),
            "   ·   ".join(sub_parts),
            fill=_SLATE_MUTED,
            font=sub_font,
            anchor="mt",
        )
    draw.line([(28, 86), (w - 28, 86)], fill=_PITCH_FRAME, width=1)

    out = BytesIO()
    im.save(out, format="PNG", optimize=True)
    return out.getvalue()
