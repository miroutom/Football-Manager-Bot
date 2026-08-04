# -*- coding: utf-8 -*-
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "tools" / "transfer_window_app"))

from remote_tunnel import build_tunneler_argv, parse_tunnel_url


def test_parse_tunnel_url_from_tunneler_line():
    line = "tunnel ready: https://my-app.tunneler.yandex.net/foo"
    assert parse_tunnel_url(line) == "https://my-app.tunneler.yandex.net/foo/"


def test_parse_tunnel_url_from_json():
    blob = '{"url": "https://tw-demo.yandex-team.ru/abc/"}'
    assert parse_tunnel_url(blob) == "https://tw-demo.yandex-team.ru/abc/"


def test_parse_tunnel_url_skips_cloudflare():
    line = "fallback https://random-words-here.trycloudflare.com"
    assert parse_tunnel_url(line) is None


def test_parse_tunnel_url_none():
    assert parse_tunnel_url("no url here") is None


def test_build_tunneler_argv_default(monkeypatch):
    monkeypatch.delenv("TW_TUNNEL_CMD", raising=False)
    assert build_tunneler_argv(8765) == ["tunneler", "http", "--port", "8765"]


def test_build_tunneler_argv_custom(monkeypatch):
    monkeypatch.setenv("TW_TUNNEL_CMD", "tunneler tunnel -p {port}")
    assert build_tunneler_argv(9000) == ["tunneler", "tunnel", "-p", "9000"]
