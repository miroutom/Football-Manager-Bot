# -*- coding: utf-8 -*-
import pytest

from utils import transfer_window as tw


@pytest.fixture
def window_file(tmp_path, monkeypatch):
    p = tmp_path / "transfer_window.json"
    monkeypatch.setattr(tw, "_PATH", p)
    return p


def test_default_open_blocks_matches(window_file):
    tw.set_window_open()
    assert tw.is_window_open()
    assert tw.blocks_matches()
    assert not tw.blocks_transfers()


def test_closed_allows_matches(window_file):
    tw.set_window_closed()
    assert not tw.is_window_open()
    assert not tw.blocks_matches()
    assert tw.blocks_transfers()


def test_quotas_in_out(window_file):
    tw.set_window_open()
    ok, _ = tw.check_transfer("Интер", "Цска", free_agent=False)
    assert ok
    tw.record_transfer("Интер", "Цска", free_agent=False)
    q_from = tw.get_quota("Интер")
    q_to = tw.get_quota("Цска")
    assert q_from["out"] == 1
    assert q_to["in"] == 1


def test_quota_in_limit(window_file):
    tw.set_window_open(reset_quotas=True)
    for _ in range(5):
        tw.record_transfer("(fa)", "Урал", free_agent=True)
    ok, err = tw.can_transfer_in("Урал")
    assert not ok
    assert err


def test_free_agent_only_counts_in(window_file):
    tw.set_window_open(reset_quotas=True)
    tw.record_transfer("", "Спартак", free_agent=True)
    q = tw.get_quota("Спартак")
    assert q["in"] == 1
    assert q["out"] == 0
