from utils.player_discipline import (
    _injury_blocks_at_month,
    _injury_period_key,
    get_active_injuries_for_team,
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
