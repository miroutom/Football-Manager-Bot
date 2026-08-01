# -*- coding: utf-8 -*-
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "tools" / "transfer_window_app"))

from remote_tunnel import parse_tunnel_url


def test_parse_tunnel_url_from_cloudflared_line():
    line = (
        "2026-08-01T12:00:00Z INF |  https://random-words-here.trycloudflare.com"
    )
    assert parse_tunnel_url(line) == "https://random-words-here.trycloudflare.com"


def test_parse_tunnel_url_none():
    assert parse_tunnel_url("no url here") is None
