# -*- coding: utf-8 -*-
from bot.wc_handlers import _player_row_label


def test_player_row_label_uses_nickname_for_complex_name():
    label = _player_row_label(
        "Ди Мария",
        "ПЗ",
        84,
        prefix="🟢 ",
        suffix="старт",
        nickname="Димария",
    )
    assert label == "🟢 Димария · ПЗ · 84 · старт"


def test_player_row_label_uses_nickname_when_name_too_long():
    long_name = "А" * 50
    label = _player_row_label(
        long_name,
        "ЦП",
        84,
        prefix="🟢 ",
        nickname="Короткий",
    )
    assert label == "🟢 Короткий · ЦП · 84"


def test_player_row_label_keeps_full_name_when_fits():
    label = _player_row_label("Иванов", "НП", 80, prefix="➕ ")
    assert label == "➕ Иванов · НП · 80"
