# -*- coding: utf-8 -*-
"""
Публичный HTTPS-туннель для мультиплеера.

По умолчанию: cloudflared Quick Tunnel (работает с любой сети, в т.ч. хост на Windows).
Альтернатива: Yandex tunneler — TW_TUNNEL_BACKEND=tunneler (см. si-infra docs).

Хост поднимает app + туннель; напарник открывает только ссылку в браузере (cloudflare на его машине не нужен).
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

CLOUDFLARED_DOCS = (
    "https://developers.cloudflare.com/cloudflare-one/connections/connect-networks/downloads/"
)
TUNNELER_DOCS = "https://docs.yandex-team.ru/si-infra/tunneler/tunneler"

_CLOUDFLARE_URL_RE = re.compile(r"https://[a-z0-9-]+\.trycloudflare\.com", re.I)
_HTTPS_RE = re.compile(r"https://[^\s'\"<>]+", re.I)

_SKIP_URL_PARTS = (
    "yastatic.net",
    "passport.yandex",
    "mc.yandex.ru",
    "cloudflare.com",
)

_DEFAULT_TUNNELER_CMD = "tunneler http --port {port}"


def tunnel_backend() -> str:
    raw = (os.environ.get("TW_TUNNEL_BACKEND") or "cloudflared").strip().lower()
    if raw in ("tunneler", "yandex", "ya"):
        return "tunneler"
    return "cloudflared"


def find_cloudflared() -> str | None:
    override = (os.environ.get("CLOUDFLARED_BIN") or "").strip()
    if override and os.path.isfile(override):
        return override
    return shutil.which("cloudflared")


def find_tunneler() -> str | None:
    override = (os.environ.get("TUNNELER_BIN") or os.environ.get("TW_TUNNEL_BIN") or "").strip()
    if override and os.path.isfile(override):
        return override
    return shutil.which("tunneler")


def _normalize_public_url(raw: str) -> str | None:
    s = (raw or "").strip().rstrip(".,;)")
    if not s.lower().startswith("https://"):
        return None
    if not urlparse(s).netloc:
        return None
    return s.rstrip("/") + "/"


def parse_tunnel_url(text: str, *, backend: str | None = None) -> str | None:
    if not text:
        return None
    backend = backend or tunnel_backend()

    if backend == "cloudflared":
        # Только *.trycloudflare.com — cloudflared сначала печатает website-terms и др.
        m = _CLOUDFLARE_URL_RE.search(text)
        if m:
            return _normalize_public_url(m.group(0))
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


def _watch_process_output(
    proc: subprocess.Popen,
    *,
    on_url: Callable[[str], None] | None,
    on_error: Callable[[str], None] | None,
    timeout_sec: float,
    backend: str,
    argv: list[str],
    fail_hint: str,
) -> None:
    deadline = time.monotonic() + timeout_sec
    url_found = False
    assert proc.stdout is not None
    buf: list[str] = []
    while True:
        if proc.poll() is not None:
            rest = proc.stdout.read() or ""
            if rest:
                buf.append(rest)
            if not url_found:
                url = parse_tunnel_url("".join(buf), backend=backend)
                if url:
                    url_found = True
                    if on_url:
                        on_url(url)
            if not url_found and on_error:
                on_error(f"{fail_hint}\n  Команда: {shlex.join(argv)}")
            return
        line = proc.stdout.readline()
        if not line:
            if time.monotonic() > deadline and not url_found:
                if on_error:
                    on_error(
                        f"таймаут ожидания ссылки ({backend}).\n"
                        f"  {fail_hint}\n"
                        "  Или передай готовую ссылку: --tunnel-url 'https://…'"
                    )
                proc.kill()
            time.sleep(0.05)
            continue
        buf.append(line)
        url = parse_tunnel_url(line, backend=backend)
        if url and not url_found:
            url_found = True
            if on_url:
                on_url(url)


def start_cloudflared_tunnel(
    port: int,
    *,
    on_url: Callable[[str], None] | None = None,
    on_error: Callable[[str], None] | None = None,
    timeout_sec: float = 90.0,
) -> subprocess.Popen | None:
    """cloudflared tunnel --url http://127.0.0.1:PORT → https://….trycloudflare.com"""
    bin_path = find_cloudflared()
    if not bin_path:
        if on_error:
            on_error(
                "cloudflared не найден в PATH.\n"
                "  Windows: winget install Cloudflare.cloudflared\n"
                "  macOS: brew install cloudflared\n"
                f"  Или: {CLOUDFLARED_DOCS}"
            )
        return None

    argv = [
        bin_path,
        "tunnel",
        "--no-autoupdate",
        "--url",
        f"http://127.0.0.1:{int(port)}",
    ]
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
            on_error(f"не удалось запустить cloudflared: {e}")
        return None

    threading.Thread(
        target=_watch_process_output,
        kwargs={
            "proc": proc,
            "on_url": on_url,
            "on_error": on_error,
            "timeout_sec": timeout_sec,
            "backend": "cloudflared",
            "argv": argv,
            "fail_hint": "cloudflared завершился без публичной ссылки.",
        },
        daemon=True,
    ).start()
    return proc


def _tunneler_cmd_template() -> str:
    for key in ("TW_TUNNEL_CMD", "TUNNELER_CMD"):
        raw = (os.environ.get(key) or "").strip()
        if raw:
            return raw
    return _DEFAULT_TUNNELER_CMD


def build_tunneler_argv(port: int, *, host: str = "127.0.0.1") -> list[str]:
    tpl = _tunneler_cmd_template()
    rendered = tpl.format(port=int(port), host=host)
    return shlex.split(rendered)


def start_tunneler_process(
    port: int,
    *,
    on_url: Callable[[str], None] | None = None,
    on_error: Callable[[str], None] | None = None,
    timeout_sec: float = 120.0,
    host: str = "127.0.0.1",
) -> subprocess.Popen | None:
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
    if "/" not in bin_path and "\\" not in bin_path and not shutil.which(bin_path):
        if on_error:
            on_error(
                "tunneler не найден в PATH.\n"
                f"  Дока: {TUNNELER_DOCS}\n"
                f"  Либо: set TUNNELER_BIN=C:\\path\\to\\tunneler.exe"
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
            on_error(f"не удалось запустить tunneler: {e}")
        return None

    threading.Thread(
        target=_watch_process_output,
        kwargs={
            "proc": proc,
            "on_url": on_url,
            "on_error": on_error,
            "timeout_sec": timeout_sec,
            "backend": "tunneler",
            "argv": argv,
            "fail_hint": f"tunneler завершился без ссылки. Дока: {TUNNELER_DOCS}",
        },
        daemon=True,
    ).start()
    return proc


def start_remote_tunnel(
    port: int,
    *,
    on_url: Callable[[str], None] | None = None,
    on_error: Callable[[str], None] | None = None,
    timeout_sec: float = 90.0,
) -> subprocess.Popen | None:
    if tunnel_backend() == "tunneler":
        return start_tunneler_process(
            port, on_url=on_url, on_error=on_error, timeout_sec=max(timeout_sec, 120.0)
        )
    return start_cloudflared_tunnel(
        port, on_url=on_url, on_error=on_error, timeout_sec=timeout_sec
    )
