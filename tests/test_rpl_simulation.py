from config.leagues_config import (
    is_rpl_club,
    manager_session_label,
    match_journal_entry_type,
)


def test_is_rpl_club():
    assert is_rpl_club("Спартак")
    assert is_rpl_club("цска")
    assert not is_rpl_club("Челси")


def test_rpl_derby_is_simulation_even_cross_manager():
    assert manager_session_label("Цска", "Зенит") == "Симуляция"
    assert manager_session_label("Спартак", "Локомотив") == "Симуляция"


def test_rpl_cl_in_cl_match_is_simulation():
    assert manager_session_label("Спартак", "Барселона") == "Симуляция"
    assert manager_session_label("Сити", "Зенит") == "Симуляция"


def test_non_rpl_cross_manager_stays_game():
    assert manager_session_label("Челси", "Сити") == "Игра"
    assert manager_session_label("Реал", "Барселона") == "Игра"


def test_match_journal_entry_type_for_rpl():
    assert match_journal_entry_type("Цска", "Зенит") == "simulation"
    assert match_journal_entry_type("Челси", "Сити") == "play"
