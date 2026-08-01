# -*- coding: utf-8 -*-
from utils.transfer_window_apply import (
    parse_transfers_text,
    strip_transfers_appendix,
)


def test_strip_transfers_appendix():
    text = "@Arsenal\n==== start ===\n\n=== transfers ===\nx"
    out = strip_transfers_appendix(text)
    assert "=== transfers ===" not in out


def test_parse_transfers_tsv():
    raw = (
        "Игрок\tПозиция\tРейтинг\tКоманда (из)\tКоманда (в)\n"
        "Муани\tЦН\t84\tПСЖ\tTottenham\n"
    )
    rows = parse_transfers_text(raw)
    assert len(rows) == 1
    assert rows[0]["name"] == "Муани"
    assert rows[0]["overall"] == 84
