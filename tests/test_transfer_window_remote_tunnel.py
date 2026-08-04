# -*- coding: utf-8 -*-
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "tools" / "transfer_window_app"))

from remote_tunnel import (
    build_tunneler_argv,
    parse_tunnel_url,
    tunnel_backend,
)


def test_parse_tunnel_url_from_cloudflared_line():
    line = (
        "2026-08-01T12:00:00Z INF |  https://random-words-here.trycloudflare.com"
    )
    assert (
        parse_tunnel_url(line, backend="cloudflared")
        == "https://random-words-here.trycloudflare.com/"
    )


def test_parse_tunnel_url_from_tunneler_line():
    line = "tunnel ready: https://my-app.tunneler.yandex.net/foo"
    assert (
        parse_tunnel_url(line, backend="tunneler")
        == "https://my-app.tunneler.yandex.net/foo/"
    )


def test_parse_tunnel_url_none():
    assert parse_tunnel_url("no url here") is None


def test_tunnel_backend_default(monkeypatch):
    monkeypatch.delenv("TW_TUNNEL_BACKEND", raising=False)
    assert tunnel_backend() == "cloudflared"


def test_build_tunneler_argv_custom(monkeypatch):
    monkeypatch.setenv("TW_TUNNEL_CMD", "tunneler tunnel -p {port}")
    assert build_tunneler_argv(9000) == ["tunneler", "tunnel", "-p", "9000"]
