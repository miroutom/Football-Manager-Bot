# -*- coding: utf-8 -*-
from utils.wc_branding import (
    LOGO_STYLES,
    ensure_branding,
    get_branding,
)


def test_ensure_branding_stable(tmp_path, monkeypatch):
    path = tmp_path / "wc_branding.json"
    monkeypatch.setattr("utils.wc_branding._PATH", str(path))
    monkeypatch.setattr(
        "utils.wc_branding._host_pool",
        lambda: ["Япония", "Бразилия", "Франция", "Германия"],
    )
    monkeypatch.setattr("utils.wc_branding.migrate_branding_styles", lambda: None)
    a = ensure_branding(4)
    b = ensure_branding(4)
    assert a["host"] == b["host"]
    assert a["style"] in LOGO_STYLES
    assert a["season"] == 4
    assert get_branding(4)["seed"] == a["seed"]
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
    monkeypatch.setattr("utils.wc_branding.migrate_branding_styles", lambda: None)
    monkeypatch.setattr("bot.wc_logo._CACHE_DIR", str(cache))
    from bot.wc_logo import render_wc_logo_png_bytes

    for style in LOGO_STYLES:
        brand = {
            "host": "Япония",
            "style": style,
            "seed": 42,
            "season": 4,
        }
        png = render_wc_logo_png_bytes(4, branding=brand, use_cache=False)
        assert png[:8] == b"\x89PNG\r\n\x1a\n"


def test_legacy_style_maps_to_trophy():
    from bot.wc_logo import _resolve_style

    assert _resolve_style("ribbon") == "trophy_rings"
    assert _resolve_style("trophy_center") == "trophy_center"
