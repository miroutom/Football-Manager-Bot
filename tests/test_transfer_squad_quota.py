# -*- coding: utf-8 -*-
from utils.transfer_squad_quota import assign_substitutes_to_groups, reserve_groups_for_formation


def _groups_433():
    slots = [
        {"slot_id": "GK", "allowed_positions": ["ВРТ"]},
        {"slot_id": "LCM", "allowed_positions": ["ЦП", "ЦОП"]},
        {"slot_id": "RCM", "allowed_positions": ["ЦП", "ЦОП"]},
        {"slot_id": "CAM", "allowed_positions": ["ЦАП", "ЦП"]},
    ]
    return reserve_groups_for_formation(slots)


def test_cam_does_not_fill_cm_slot():
    groups = _groups_433()
    subs = [{"name": "Playmaker", "position": "ЦАП"}]
    assigned, missing, surplus = assign_substitutes_to_groups(subs, groups)
    by_slot = {g.slot_id: assigned[i] for i, g in enumerate(groups)}
    assert by_slot["CAM"] == 1
    assert by_slot["LCM"] == 0
    assert by_slot["RCM"] == 0
    assert not surplus


def test_4222_lcam_rcam_reserve_label_is_cam():
    """4-2-2-2: LCAM/RCAM на поле — ЦАП, замены тоже по ЦАП (не ЛП/ПП)."""
    slots = [
        {"slot_id": "LCAM", "allowed_positions": ["ЛП", "ЛЦП", "ЦАП", "ЦП"]},
        {"slot_id": "RCAM", "allowed_positions": ["ПП", "ПЦП", "ЦАП", "ЦП"]},
    ]
    groups = reserve_groups_for_formation(slots)
    assert [g.label for g in groups] == ["ЦАП", "ЦАП"]
    subs = [
        {"name": "A", "position": "ЦАП"},
        {"name": "B", "position": "ЦАП"},
        {"name": "C", "position": "ЦАП"},
        {"name": "D", "position": "ЦАП"},
    ]
    assigned, missing, surplus = assign_substitutes_to_groups(subs, groups)
    assert assigned == [2, 2]
    assert not missing
    assert not surplus


def test_two_cm_slots_counted_separately():
    groups = _groups_433()
    subs = [{"name": "CM1", "position": "ЦП"}]
    assigned, missing, surplus = assign_substitutes_to_groups(subs, groups)
    by_slot = {g.slot_id: assigned[i] for i, g in enumerate(groups)}
    assert by_slot["LCM"] == 1
    assert by_slot["RCM"] == 0
    assert by_slot["CAM"] == 0
    assert not surplus
