"""
lineup_consistency.py — Lineup consistency filter for MLB props.

Checks whether a batter has been consistently in the starting lineup
over recent games by counting games with 3+ at-bats (AB >= 3).

A player with AB >= 3 in 7+ of their last 10 games is considered a
consistent starter. Bench/platoon players will typically fall below
this threshold.
"""
from __future__ import annotations

from typing import Optional

import statsapi


def started_last_n_games(player_id: int, season: int, n: int = 10) -> Optional[float]:
    """
    Return the fraction of the last n games where the player had 3+ at-bats.

    Returns None if game log is unavailable (caller should not filter that player).
    Returns 0.0 only when we have data and the player genuinely never has 3+ AB.
    """
    try:
        logs = statsapi.player_stat_data(
            player_id,
            group="hitting",
            type="gameLog",
        )
        games = logs.get("stats", [])
        if not games:
            print(f"[lineup_consistency] player {player_id}: no game log returned, skipping filter")
            return None
        # Most recent n games
        recent = games[-n:]
        if len(recent) < 3:
            print(f"[lineup_consistency] player {player_id}: only {len(recent)} games (<3), skipping filter")
            return None
        qualified = sum(1 for g in recent if g.get("ab", 0) >= 3)
        score = round(qualified / len(recent), 3)
        print(f"[lineup_consistency] player {player_id}: {qualified}/{len(recent)} games with 3+ AB = {score:.3f}")
        return score
    except Exception as exc:
        print(f"[lineup_consistency] player {player_id}: error fetching game log: {exc} — skipping filter")
        return None


def calculate_lineup_consistency(
    player_id: int,
    stat: str,
    season: int,
    n: int = 10,
) -> Optional[float]:
    """
    Return a 0.0–1.0 lineup consistency score for a batter.

    Pitchers (stat in pitcher_stats) always return 1.0 (no check needed).
    Returns None if unable to fetch data — callers must NOT filter players
    with a None score (treat as unknown, include conservatively).

    Args:
        player_id:  MLB person ID
        stat:       prop stat (e.g. 'hits', 'strikeouts', 'totalBases')
        season:     MLB season year
        n:          Number of recent games to check (default 10)

    Returns:
        float in [0.0, 1.0] — fraction of recent games where player had 3+ AB,
        or None if game log data is unavailable.
    """
    PITCHER_STATS = {"inningsPitched", "hitsAllowed", "earnedRuns"}
    if stat in PITCHER_STATS:
        return 1.0  # pitchers don't have batting orders
    return started_last_n_games(player_id, season, n)
