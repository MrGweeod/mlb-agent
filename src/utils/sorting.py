"""
sorting.py — Parlay leg sorting utilities.
"""
from __future__ import annotations

from datetime import datetime


def sort_legs_by_game_time(legs: list[dict]) -> list[dict]:
    """
    Sort parlay legs by game start time (earliest first).
    Legs without game_start_time are placed at the end.
    """

    def get_sort_key(leg: dict) -> datetime:
        game_time = leg.get("game_start_time")
        if not game_time:
            return datetime.max
        if isinstance(game_time, datetime):
            return game_time
        if isinstance(game_time, str):
            try:
                return datetime.fromisoformat(game_time.replace("Z", "+00:00"))
            except ValueError:
                pass
            try:
                return datetime.strptime(game_time, "%Y-%m-%d %H:%M:%S")
            except ValueError:
                pass
        return datetime.max

    return sorted(legs, key=get_sort_key)
