# -*- coding: utf-8 -*-
from utils.wc_branding import (
    LOGO_STYLES,
    display_year_for_season,
    ensure_branding,
    get_branding,
)


def test_display_year_mapping():
    assert display_year_for_season(4) == 2022
    assert display_year_for_season(8) == 2026
    assert display_year_for_season(12) == 2030


def test_ensure_branding_stable(tmp_path, monkeypatch):
    path = tmp_path / "wc_branding.json"
    monkeypatch.setattr("utils.wc_branding._PATH", str(path))
    monkeypatch.setattr(
        "utils.wc_branding._host_pool",
        lambda: ["Япония", "Бразилия", "Франция", "Германия"],
    )
    a = ensure_branding(4)
    b = ensure_branding(4)
    assert a["host"] == b["host"]
    assert a["style"] in LOGO_STYLES
    assert a["display_year"] == 2022
    c = ensure_branding(4, force=True)
    assert get_branding(4)["seed"] == c["seed"]


def test_wc_logo_png_smoke(tmp_path, monkeypatch):
    path = tmp_path / "wc_branding.json"
    cache = tmp_path / "logos"
    cache.mkdir()
    monkeypatch.setattr("utils.wc_branding._PATH", str(path))
    monkeypatch.setattr(
        "utils.wc_branding._host_pool",
        lambda: ["Япония", "Бразилия", "Франция"],
    )
    monkeypatch.setattr("bot.wc_logo._CACHE_DIR", str(cache))
    from bot.wc_logo import render_wc_logo_png_bytes

    for style in LOGO_STYLES:
        brand = {
            "host": "Япония",
            "style": style,
            "seed": 42,
            "display_year": 2026,
            "season": 8,
        }
        png = render_wc_logo_png_bytes(8, branding=brand, use_cache=False)
        assert png[:8] == b"\x89PNG\r\n\x1a\n"
