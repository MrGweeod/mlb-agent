"""
lineup_consistency.py — Lineup consistency filter for MLB props.

Checks whether a batter has been consistently in the starting lineup
over recent games using the statsapi battingOrder field.

A battingOrder value of 1-9 (e.g. 100, 200, ... 900 in the raw data)
indicates the player was in the starting lineup. Values >= 1000 or
missing indicate pinch hitter / bench player.
"""
from __future__ import annotations

import statsapi


def started_last_n_games(player_id: int, season: int, n: int = 10) -> float:
    """
    Return the fraction of the last n games where the player was a starter
    (had a battingOrder value in 1-9, i.e. 100-900 in raw data).

    Returns 0.0 if game log is unavailable or player has < 3 games.
    """
    try:
        logs = statsapi.player_stat_data(
            player_id,
            group="hitting",
            type="gameLog",
            season=season,
        )
        games = logs.get("stats", [])
        if not games:
            return 0.0
        # Most recent n games
        recent = games[-n:]
        if len(recent) < 3:
            return 0.0
        started = sum(
            1 for g in recent
            if g.get("batting_order") and int(g["batting_order"]) <= 900
        )
        return round(started / len(recent), 3)
    except Exception:
        return 0.0


def calculate_lineup_consistency(
    player_id: int,
    stat: str,
    season: int,
    n: int = 10,
) -> float:
    """
    Return a 0.0–1.0 lineup consistency score for a batter.

    Pitchers (stat in pitcher_stats) always return 1.0 (no check needed).
    Returns 0.0 if unable to fetch data.

    Args:
        player_id:  MLB person ID
        stat:       prop stat (e.g. 'hits', 'strikeouts', 'totalBases')
        season:     MLB season year
        n:          Number of recent games to check (default 10)

    Returns:
        float in [0.0, 1.0] — fraction of recent games where player was a starter
    """
    PITCHER_STATS = {"inningsPitched", "hitsAllowed", "earnedRuns"}
    if stat in PITCHER_STATS:
        return 1.0  # pitchers don't have batting orders
    return started_last_n_games(player_id, season, n)
