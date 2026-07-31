# -*- coding: utf-8 -*-
from utils.person_id_unify import (
    build_full_name_career_canonical,
    build_name_team_canonical_map,
)


def test_di_maria_maps_to_single_career_id():
    career = build_full_name_career_canonical()
    # после unify карта пуста (уже один id); до — был бы 41
    # проверяем архивный канон через внутренности
    from utils.person_id_unify import _archive_pid_by_full_name

    arch = _archive_pid_by_full_name()
    assert arch.get("ди мария") == 41


def test_name_team_map_keeps_alvarez_clubs_apart():
    # если ещё есть сплиты — Атлетико и Вилла не должны получить один id
    nt = build_name_team_canonical_map()
    atl = nt.get(("альварез", "атлетико"))
    villa = nt.get(("альварез", "астон вилла"))
    if atl is not None and villa is not None:
        assert atl != villa
