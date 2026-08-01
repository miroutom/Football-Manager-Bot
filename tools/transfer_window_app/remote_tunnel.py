# -*- coding: utf-8 -*-
"""Публичный HTTPS-туннель для мультиплеера из разных сетей (cloudflared Quick Tunnel)."""
from __future__ import annotations

import re
import shutil
import subprocess
import threading
import time
from typing import Callable

_TUNNEL_URL_RE = re.compile(r"https://[a-z0-9-]+\.trycloudflare\.com", re.I)


def find_cloudflared() -> str | None:
    return shutil.which("cloudflared")


def parse_tunnel_url(text: str) -> str | None:
    m = _TUNNEL_URL_RE.search(text or "")
    return m.group(0) if m else None


def start_cloudflared_tunnel(
    port: int,
    *,
    on_url: Callable[[str], None] | None = None,
    on_error: Callable[[str], None] | None = None,
    timeout_sec: float = 90.0,
) -> subprocess.Popen | None:
    """
    Запустить ``cloudflared tunnel --url http://127.0.0.1:PORT``.
    URL приходит асинхронно из stdout/stderr процесса.
    """
    bin_path = find_cloudflared()
    if not bin_path:
        if on_error:
            on_error(
                "cloudflared не найден. Установите: brew install cloudflared "
                "(или скачайте с https://developers.cloudflare.com/cloudflare-one/connections/connect-networks/downloads/)"
            )
        return None

    try:
        proc = subprocess.Popen(
            [
                bin_path,
                "tunnel",
                "--no-autoupdate",
                "--url",
                f"http://127.0.0.1:{int(port)}",
            ],
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            bufsize=1,
        )
    except OSError as e:
        if on_error:
            on_error(f"не удалось запустить cloudflared: {e}")
        return None

    def _watch() -> None:
        deadline = time.monotonic() + timeout_sec
        url_found = False
        assert proc.stdout is not None
        while True:
            if proc.poll() is not None and proc.stdout.readable():
                rest = proc.stdout.read() or ""
                if not url_found:
                    url = parse_tunnel_url(rest)
                    if url:
                        url_found = True
                        if on_url:
                            on_url(url)
                if not url_found and on_error:
                    on_error("cloudflared завершился без публичной ссылки")
                return
            line = proc.stdout.readline()
            if not line:
                if time.monotonic() > deadline and not url_found:
                    if on_error:
                        on_error("таймаут ожидания ссылки от cloudflared")
                    proc.kill()
                time.sleep(0.05)
                continue
            url = parse_tunnel_url(line)
            if url and not url_found:
                url_found = True
                if on_url:
                    on_url(url)

    threading.Thread(target=_watch, daemon=True).start()
    return proc
