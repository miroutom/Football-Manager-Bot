# -*- coding: utf-8 -*-
"""
Ресурсы для PNG состава: флаги по ISO (CDN + кэш), эмблемы с Wikimedia Commons (опционально).

Флаги: ``https://flagcdn.com`` — ISO2 (``fr``) или регион UK (``gb-eng``, ``gb-sct``, ``gb-wls``, ``gb-nir``);
кэш ``assets/cache/flags/<код>.png``.
Эмблемы: локальные файлы в ``assets/crests/``; словарь ``assets/crests/wikimedia_commons.json``
``{ "<команда>": "Имя_файла.svg" }`` — ``Special:FilePath`` сначала на Commons, затем на **en.wikipedia**
(многие гербы клубов есть только там, на Commons файла нет).
"""
from __future__ import annotations

import hashlib
import json
import logging
import re
import ssl
import http.client
import urllib.error
import urllib.parse
import urllib.request
from io import BytesIO
from pathlib import Path

from PIL import Image

logger = logging.getLogger(__name__)

_ROOT = Path(__file__).resolve().parent.parent
_FLAG_CACHE_DIR = _ROOT / "assets" / "cache" / "flags"
_COMMONS_CACHE_DIR = _ROOT / "assets" / "cache" / "commons_crests"
_COMMONS_JSON = _ROOT / "assets" / "crests" / "wikimedia_commons.json"

# Некоторые CDN отдают 200 только при «браузерном» UA; нестандартный бот может получить пусто/403.
_BROWSER_UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36"
)

_commons_map: dict[str, str] | None = None


def _https_context() -> ssl.SSLContext | None:
    """На части macOS-сборок Python нет корневых сертификатов — без cafile HTTPS падает."""
    try:
        import certifi

        return ssl.create_default_context(cafile=certifi.where())
    except (ImportError, OSError, ssl.SSLError):
        return None


def _http_get(url: str, timeout: float = 15.0) -> bytes | None:
    req = urllib.request.Request(
        url,
        headers={
            "User-Agent": _BROWSER_UA,
            "Accept": "image/png,image/webp,image/*;q=0.8,*/*;q=0.5,application/json;q=0.1",
            "Accept-Language": "en-US,en;q=0.9",
        },
    )
    ctx = _https_context() if url.lower().startswith("https://") else None
    try:
        kw: dict = {"timeout": timeout}
        if ctx is not None:
            kw["context"] = ctx
        with urllib.request.urlopen(req, **kw) as resp:
            code = getattr(resp, "status", None) or resp.getcode()
            if code != 200:
                logger.warning("HTTP %s для %s", code, url[:96])
                return None
            data = resp.read()
            if not data:
                logger.warning("Пустое тело ответа: %s", url[:96])
                return None
            return data
    except (
        urllib.error.URLError,
        urllib.error.HTTPError,
        http.client.HTTPException,
        OSError,
        TimeoutError,
    ) as e:
        logger.info("HTTP ошибка %s: %s", url[:96], e)
        return None


_FLAGCDN_CODE = re.compile(r"^[a-z]{2}$")
_FLAGCDN_SUB = re.compile(r"^[a-z]{2}-[a-z]{3}$")


def load_flag_png(flag_code: str | None) -> Image.Image | None:
    """PNG с flagcdn: ISO2 (``de``) или подрегион UK ``gb-eng`` / ``gb-sct`` / ``gb-wls`` / ``gb-nir``."""
    if not flag_code:
        return None
    code = flag_code.strip().lower()
    if not code:
        return None
    if not (_FLAGCDN_CODE.match(code) or _FLAGCDN_SUB.match(code)):
        return None
    _FLAG_CACHE_DIR.mkdir(parents=True, exist_ok=True)
    safe_name = code.replace("-", "_")
    cache_path = _FLAG_CACHE_DIR / f"{safe_name}.png"
    if cache_path.is_file():
        try:
            return Image.open(cache_path).convert("RGBA")
        except OSError:
            return None
    url = f"https://flagcdn.com/w80/{code}.png"
    data = _http_get(url)
    if not data:
        return None
    try:
        im = Image.open(BytesIO(data)).convert("RGBA")
    except OSError as e:
        head = data[:32].hex() if len(data) >= 8 else ""
        logger.warning("Флаг %s: не удалось открыть как изображение (%s), head=%s", code, e, head)
        return None
    try:
        im.save(cache_path, format="PNG")
    except OSError:
        pass
    return im


def _load_commons_map() -> dict[str, str]:
    global _commons_map
    if _commons_map is not None:
        return _commons_map
    if not _COMMONS_JSON.is_file():
        _commons_map = {}
        return _commons_map
    try:
        raw = json.loads(_COMMONS_JSON.read_text(encoding="utf-8"))
        if isinstance(raw, dict):
            _commons_map = {str(k).strip(): str(v).strip() for k, v in raw.items() if str(v).strip()}
        else:
            _commons_map = {}
    except (json.JSONDecodeError, OSError) as e:
        logger.warning("wikimedia_commons.json: %s", e)
        _commons_map = {}
    return _commons_map


def _looks_like_raster_image(data: bytes) -> bool:
    if len(data) < 12:
        return False
    if data[:8] == b"\x89PNG\r\n\x1a\n":
        return True
    if data[:2] == b"\xff\xd8":
        return True
    if data[:4] == b"RIFF" and data[8:12] == b"WEBP":
        return True
    return False


def commons_crest_filename_for_team(team_db: str) -> str | None:
    t = (team_db or "").strip()
    if not t:
        return None
    m = _load_commons_map()
    v = m.get(t) or m.get(t.replace(" ", "_"))
    if v:
        return v
    tcf = t.casefold()
    for k, val in m.items():
        if str(k).strip().casefold() == tcf:
            return val
    return None


def _wiki_en_thumb_raster_url(filename: str, width: int = 256) -> str | None:
    """Растровый thumb для ``File:…`` через API en.wikipedia (SVG с Special:FilePath PIL не открыть)."""
    fn = (filename or "").strip()
    if not fn:
        return None
    title = fn if fn.lower().startswith("file:") else f"File:{fn}"
    qs = urllib.parse.urlencode(
        {
            "action": "query",
            "titles": title,
            "prop": "imageinfo",
            "iiprop": "url",
            "iiurlwidth": str(int(width)),
            "format": "json",
            "formatversion": "2",
        }
    )
    api_url = f"https://en.wikipedia.org/w/api.php?{qs}"
    raw = _http_get(api_url, timeout=20.0)
    if not raw:
        return None
    try:
        payload = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError, ValueError) as e:
        logger.info("wiki thumb API: %s", e)
        return None
    raw_pages = (payload.get("query") or {}).get("pages") or []
    if isinstance(raw_pages, dict):
        pages = list(raw_pages.values())
    else:
        pages = list(raw_pages)
    if not pages or pages[0].get("missing"):
        return None
    infos = (pages[0].get("imageinfo") or [])[:1]
    if not infos:
        return None
    info = infos[0]
    return info.get("thumburl") or info.get("url")


def load_commons_crest_rgba(commons_filename: str) -> Image.Image | None:
    """Скачать по имени файла Wiki: ``Special:FilePath`` на Commons, иначе en.wikipedia; кэш PNG."""
    fn = commons_filename.strip()
    if not fn:
        return None
    _COMMONS_CACHE_DIR.mkdir(parents=True, exist_ok=True)
    key = hashlib.sha256(fn.encode("utf-8")).hexdigest()[:20]
    cache_path = _COMMONS_CACHE_DIR / f"{key}.png"
    if cache_path.is_file():
        try:
            return Image.open(cache_path).convert("RGBA")
        except OSError:
            return None
    if fn.startswith(("http://", "https://")):
        data = _http_get(fn, timeout=25.0)
        if data and _looks_like_raster_image(data):
            try:
                im = Image.open(BytesIO(data)).convert("RGBA")
                im.save(cache_path, format="PNG")
                return im
            except OSError:
                pass
        return None
    q = urllib.parse.quote(fn, safe="")
    bases = (
        "https://commons.wikimedia.org/wiki/Special:FilePath/",
        "https://en.wikipedia.org/wiki/Special:FilePath/",
    )
    for base in bases:
        url = f"{base}{q}?width=256"
        data = _http_get(url, timeout=20.0)
        if not data or not _looks_like_raster_image(data):
            if data and not _looks_like_raster_image(data):
                logger.info("Эмблема %s: ответ не растровое изображение (%s)", fn, base.rstrip("/"))
            continue
        try:
            im = Image.open(BytesIO(data)).convert("RGBA")
        except OSError as e:
            logger.info("Эмблема %s: PIL %s (%s)", fn, e, base.rstrip("/"))
            continue
        try:
            im.save(cache_path, format="PNG")
        except OSError:
            pass
        return im
    thumb = _wiki_en_thumb_raster_url(fn, width=256)
    if thumb:
        data = _http_get(thumb, timeout=25.0)
        if data and _looks_like_raster_image(data):
            try:
                im = Image.open(BytesIO(data)).convert("RGBA")
                im.save(cache_path, format="PNG")
                return im
            except OSError as e:
                logger.info("Эмблема %s: thumb PIL %s", fn, e)
    return None
