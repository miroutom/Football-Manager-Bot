# -*- coding: utf-8 -*-
from typing import Optional
from unittest.mock import patch

from utils.transfer_window_apply import (
    apply_squads_text,
    parse_transfers_text,
    strip_transfers_appendix,
    apply_transfer_window_upload,
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


def test_apply_progress_callback_dry_run():
    calls: list[tuple[int, int, str, Optional[str], int, int]] = []

    def on_progress(done, total, phase, detail, phase_done, phase_total):
        calls.append((done, total, phase, detail, phase_done, phase_total))

    squads = "@Arsenal\n==== start ===\n\n==== bench ===\n\n==== reserve ===\n"
    transfers = "Игрок\tПозиция\tРейтинг\tКоманда (из)\tКоманда (в)\n"
    apply_transfer_window_upload(
        squads_text=squads,
        transfers_content=transfers,
        transfers_filename="t.txt",
        dry_run=True,
        on_progress=on_progress,
    )
    assert calls
    assert calls[0][0] == 0
    assert calls[-1][2] == "Готово"


def test_apply_squads_text_skips_complete_roster():
    squads = (
        "@Zenit\n==== start ===\nИванов ЦП 80\n\n"
        "@Spartak\n==== start ===\nПетров ЦП 80\n"
    )
    with patch("utils.roster_manual.team_squad_is_complete") as complete:
        complete.side_effect = lambda team, **_: team == "Zenit"
        with patch("utils.roster_manual.apply_team_squad_declaration") as apply_decl:
            applied, skipped = apply_squads_text(squads, dry_run=False)
    assert applied == 1
    assert skipped == 1
    apply_decl.assert_called_once()
    assert apply_decl.call_args[0][0] == "Spartak"
