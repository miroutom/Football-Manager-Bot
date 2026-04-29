"""Условия для UI сезона (завершение только после полного календаря)."""
from __future__ import annotations


def can_finish_season() -> bool:
    from main import count_remaining_in_schedule, load_or_generate_mixed_schedule

    return count_remaining_in_schedule(load_or_generate_mixed_schedule()) == 0
