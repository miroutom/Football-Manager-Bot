# -*- coding: utf-8 -*-
"""
Публичный HTTPS-туннель для мультиплеера (Yandex si-infra tunneler).

Документация: https://docs.yandex-team.ru/si-infra/tunneler/tunneler

Команда по умолчанию задаётся через TW_TUNNEL_CMD (плейсхолдер {port}):
  export TW_TUNNEL_CMD='tunneler http --port {port}'
  python3 tools/transfer_window_app/main.py --tunnel

Если tunneler запускаете вручную в другом терминале:
  python3 tools/transfer_window_app/main.py --tunnel --tunnel-url 'https://…'
"""
from __future__ import annotations

import json
import os
import re
import shlex
import shutil
import subprocess
import threading
import time
from typing import Callable
from urllib.parse import urlparse

DOCS_URL = "https://docs.yandex-team.ru/si-infra/tunneler/tunneler"

_DEFAULT_CMD = "tunneler http --port {port}"

_HTTPS_RE = re.compile(r"https://[^\s'\"<>]+", re.I)

_SKIP_URL_PARTS = (
    "yastatic.net",
    "passport.yandex",
    "mc.yandex.ru",
    "developers.cloudflare.com",
    "trycloudflare.com",
)


def find_tunneler() -> str | None:
    override = (os.environ.get("TUNNELER_BIN") or os.environ.get("TW_TUNNEL_BIN") or "").strip()
    if override and os.path.isfile(override):
        return override
    return shutil.which("tunneler")


def tunnel_cmd_template() -> str:
    for key in ("TW_TUNNEL_CMD", "TUNNELER_CMD"):
        raw = (os.environ.get(key) or "").strip()
        if raw:
            return raw
    return _DEFAULT_CMD


def build_tunneler_argv(port: int, *, host: str = "127.0.0.1") -> list[str]:
    tpl = tunnel_cmd_template()
    rendered = tpl.format(port=int(port), host=host)
    return shlex.split(rendered)


def parse_tunnel_url(text: str) -> str | None:
    if not text:
        return None
    try:
        data = json.loads(text)
    except (TypeError, json.JSONDecodeError):
        data = None
    if isinstance(data, dict):
        for key in ("url", "public_url", "tunnel_url", "link"):
            val = data.get(key)
            if isinstance(val, str) and val.startswith("https://"):
                return _normalize_public_url(val)

    best: str | None = None
    for m in _HTTPS_RE.finditer(text):
        url = _normalize_public_url(m.group(0))
        if not url:
            continue
        host = (urlparse(url).hostname or "").lower()
        if any(part in host for part in _SKIP_URL_PARTS):
            continue
        best = url
    return best


def _normalize_public_url(raw: str) -> str | None:
    s = (raw or "").strip().rstrip(".,;)")
    if not s.lower().startswith("https://"):
        return None
    if not urlparse(s).netloc:
        return None
    return s.rstrip("/") + "/"


def start_tunneler_process(
    port: int,
    *,
    on_url: Callable[[str], None] | None = None,
    on_error: Callable[[str], None] | None = None,
    timeout_sec: float = 120.0,
    host: str = "127.0.0.1",
) -> subprocess.Popen | None:
    """
    Запустить Yandex tunneler (si-infra) для локального http://127.0.0.1:PORT.
    URL читается из stdout/stderr процесса.
    """
    try:
        argv = build_tunneler_argv(port, host=host)
    except ValueError as e:
        if on_error:
            on_error(f"неверный TW_TUNNEL_CMD: {e}")
        return None
    if not argv:
        if on_error:
            on_error("TW_TUNNEL_CMD пуст")
        return None

    bin_path = argv[0]
    if "/" not in bin_path and not shutil.which(bin_path):
        if on_error:
            on_error(
                "tunneler не найден в PATH.\n"
                f"  Установка и команда — в доке: {DOCS_URL}\n"
                f"  Либо: export TUNNELER_BIN=/path/to/tunneler\n"
                f"  Либо вручную: python3 tools/transfer_window_app/main.py --tunnel --tunnel-url 'https://…'"
            )
        return None

    try:
        proc = subprocess.Popen(
            argv,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            bufsize=1,
        )
    except OSError as e:
        if on_error:
            on_error(f"не удалось запустить tunneler ({shlex.join(argv)}): {e}")
        return None

    def _watch() -> None:
        deadline = time.monotonic() + timeout_sec
        url_found = False
        assert proc.stdout is not None
        buf: list[str] = []
        while True:
            if proc.poll() is not None:
                rest = proc.stdout.read() or ""
                if rest:
                    buf.append(rest)
                blob = "".join(buf)
                if not url_found:
                    url = parse_tunnel_url(blob)
                    if url:
                        url_found = True
                        if on_url:
                            on_url(url)
                if not url_found and on_error:
                    on_error(
                        "tunneler завершился без публичной ссылки.\n"
                        f"  Команда: {shlex.join(argv)}\n"
                        f"  Дока: {DOCS_URL}\n"
                        "  Проверь TW_TUNNEL_CMD или передай --tunnel-url вручную."
                    )
                return
            line = proc.stdout.readline()
            if not line:
                if time.monotonic() > deadline and not url_found:
                    if on_error:
                        on_error(
                            "таймаут ожидания ссылки от tunneler.\n"
                            f"  Дока: {DOCS_URL}\n"
                            "  Запусти tunneler вручную и передай --tunnel-url."
                        )
                    proc.kill()
                time.sleep(0.05)
                continue
            buf.append(line)
            url = parse_tunnel_url(line)
            if url and not url_found:
                url_found = True
                if on_url:
                    on_url(url)

    threading.Thread(target=_watch, daemon=True).start()
    return proc


# Совместимость со старым импортом.
start_cloudflared_tunnel = start_tunneler_process
start_remote_tunnel = start_tunneler_process
