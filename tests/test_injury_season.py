from utils.player_discipline import (
    _MAX_INJURY_DURATION_MONTHS,
    _injury_blocks_at_month,
    _injury_period_key,
    format_injuries_season_report_text,
    format_injury_frequency_report_text,
    get_active_injuries_for_team,
    list_injury_seasons,
)


def test_injury_s2_month1_4_not_active_in_s3():
    inj = {
        "out_from_month": 1,
        "return_month": 4,
        "season": 2,
        "name": "Чалханоглу",
        "team_norm": "интер",
    }
    assert not _injury_blocks_at_month(inj, 1, current_season=3)
    assert not _injury_blocks_at_month(inj, 3, current_season=3)


def test_injury_without_season_never_blocks():
    inj = {"out_from_month": 1, "return_month": 4}
    assert not _injury_blocks_at_month(inj, 1, current_season=3)


def test_injury_carryover_from_s2_to_s3():
    inj = {"out_from_month": 7, "return_month": 14, "season": 2}
    assert _injury_blocks_at_month(inj, 1, current_season=3)
    assert _injury_blocks_at_month(inj, 3, current_season=3)
    assert not _injury_blocks_at_month(inj, 4, current_season=3)


def test_injury_key_includes_season():
    assert (
        _injury_period_key("Чалханоглу", "Интер", 1, 4, 2)
        == "чалханоглу|интер|2|1|4"
    )


def test_inter_active_injuries_after_s2_calhanoglu_healed():
    # Барелла 7→14 (сезон 2) переносится на м1–м3 сезона 3; Чалханоглу 1→4 (сезон 2) — нет.
    injuries = [
        {
            "name": "Чалханоглу",
            "name_norm": "чалханоглу",
            "team": "Интер",
            "team_norm": "интер",
            "out_from_month": 1,
            "return_month": 4,
            "season": 2,
            "type": "травма",
        },
        {
            "name": "Барелла",
            "name_norm": "барелла",
            "team": "Интер",
            "team_norm": "интер",
            "out_from_month": 7,
            "return_month": 14,
            "season": 2,
            "type": "травма",
        },
    ]
    active = []
    for inj in injuries:
        if _injury_blocks_at_month(inj, 1, current_season=3):
            active.append(inj["name"])
    assert active == ["Барелла"]


def test_max_injury_duration_allows_long_carryover():
    assert _MAX_INJURY_DURATION_MONTHS >= 24


def test_list_injury_seasons_and_reports(tmp_path, monkeypatch):
    import utils.player_discipline as pd

    store = tmp_path / "player_discipline.json"
    store.write_text(
        """{
      "version": 1,
      "suspensions": [],
      "yellow_cycle": [],
      "injuries": [
        {
          "name": "Эдерсон", "name_norm": "эдерсон",
          "team": "Сити", "team_norm": "сити",
          "out_from_month": 1, "return_month": 15,
          "season": 3, "type": "травма"
        },
        {
          "name": "Эдерсон", "name_norm": "эдерсон",
          "team": "Сити", "team_norm": "сити",
          "out_from_month": 2, "return_month": 5,
          "season": 2, "type": "травма"
        },
        {
          "name": "Барелла", "name_norm": "барелла",
          "team": "Интер", "team_norm": "интер",
          "out_from_month": 7, "return_month": 14,
          "season": 2, "type": "травма"
        }
      ]
    }""",
        encoding="utf-8",
    )
    monkeypatch.setattr(pd, "_STATE_PATH", store)

    assert list_injury_seasons() == [3, 2]
    s3 = format_injuries_season_report_text(3)
    assert "Эдерсон" in s3
    assert "Барелла" not in s3
    freq = format_injury_frequency_report_text(limit=10)
    assert "Эдерсон" in freq
    # Эдерсон выше Бареллы по числу периодов (2 > 1)
    assert freq.index("Эдерсон") < freq.index("Барелла")
