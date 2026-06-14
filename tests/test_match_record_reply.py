# -*- coding: utf-8 -*-
from bot.services import compose_match_record_reply


def test_compose_match_record_reply_preserves_bot_html():
    out = compose_match_record_reply(
        "✓ Интер 2:1 Милан",
        ["<b>Интер</b> прошли в <b>полуфинал</b> ЛЧ."],
    )
    assert "<b>Интер</b>" in out
    assert "&lt;b&gt;" not in out
    assert "✓ Интер 2:1 Милан" in out


def test_compose_match_record_reply_escapes_plain_log():
    out = compose_match_record_reply("score < 0", None)
    assert "&lt;" in out
    assert "<b>" not in out
