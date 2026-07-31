# -*- coding: utf-8 -*-
from utils.player_nicknames import (
    complex_name_reasons,
    is_complex_player_name,
    load_nicknames,
    resolve_person_id_by_nickname,
    set_nickname,
)


def test_complex_hyphen_and_compound():
    assert is_complex_player_name("Жан-Клод")
    assert "дефис" in complex_name_reasons("Жан-Клод")
    assert is_complex_player_name("Ван Дейк")
    assert is_complex_player_name("О'Коннор") or is_complex_player_name("О’Коннор")
    assert is_complex_player_name("Ришарлисон")  # длинная фамилия ≥10
    assert not is_complex_player_name("Иванов")
    assert is_complex_player_name("Рандаль Коло Муани")  # составное ≥3


def test_nickname_roundtrip(tmp_path, monkeypatch):
    path = tmp_path / "player_nicknames.json"
    monkeypatch.setattr("utils.player_nicknames._PATH", str(path))
    set_nickname(42, "муани")
    data = load_nicknames()
    assert data["by_person_id"]["42"] == "муани"
    assert resolve_person_id_by_nickname("муани") == 42
    assert resolve_person_id_by_nickname("МУАНИ") == 42
    set_nickname(42, "")
    assert resolve_person_id_by_nickname("муани") is None
