"""
enrich_legs.py — Attach opponent and pitcher-based adjustment to each prop leg.

MLB replacement for the NBA DEF_RATING enrichment. Instead of looking up
opponent team defensive rating, this module fetches the opposing starting
pitcher's ERA/K/9/WHIP profile and computes a batter-perspective adjustment.

Opponent adjustment signal routing (per blueprint Section 5.2):
  hits        → K/9 primary (high K/9 pitcher suppresses hits)
  totalBases  → ERA primary (higher ERA = more total bases conceded)
  rbi         → ERA primary, WHIP secondary
  homeRuns    → ERA primary
  walks       → WHIP primary (walks are directly embedded in WHIP)
  runsScored  → ERA + WHIP composite
  stolenBases → 0.0 (pitcher-independent)
  strikeouts (batter Ks) → K/9 positive (high K/9 → batter K prop easier)
  pitcher props (strikeouts/IP/hitsAllowed/earnedRuns) → 0.0 (TODO: team K-rate)

Interface:
    enrich_legs(legs, pitcher_id_map, opponent_map, season) -> list[dict]

The caller (main.py) is responsible for building:
  pitcher_id_map  : {batter_team_abbr: opposing_pitcher_id (int)}
  opponent_map    : {batter_team_abbr: opposing_team_abbr (str)}

Both are keyed by the batter's team abbreviation (e.g. "NYY").
"""
from __future__ import annotations

import datetime

from src.apis.matchup import get_pitcher_matchup_profile

# ── Prop routing ──────────────────────────────────────────────────────────────

# Stats that belong to pitchers — opponent adjustment is 0.0 (not yet implemented)
_PITCHER_STATS = frozenset({"inningsPitched", "hitsAllowed", "earnedRuns"})

# SGO stat names that map unambiguously to pitcher K props when prop_category is pitcher
# (disambiguated by position in enrich_legs; both sides use "strikeouts" from SGO)
_BATTER_STATS = frozenset({
    "hits", "totalBases", "rbi", "homeRuns",
    "stolenBases", "walks", "runsScored",
})


def _compute_adjustment(stat: str, profile: dict, is_pitcher_prop: bool = False) -> float:
    """
    Compute opponent_adjustment ∈ [-1.0, +1.0] for a stat given a pitcher profile.

    Positive → weaker pitcher / easier matchup for the prop.
    Negative → stronger pitcher / harder matchup.

    Args:
        stat:             SGO prop stat key (e.g. "hits", "totalBases").
        profile:          Dict from matchup.get_pitcher_matchup_profile().
        is_pitcher_prop:  True when the player is the pitcher (not the batter).

    Returns:
        Adjustment float. 0.0 for pitcher props, stolenBases, and unknown stats.
    """
    if is_pitcher_prop or stat in _PITCHER_STATS:
        # TODO (Phase 2 extension): use opponent team K-rate for pitcher props
        return 0.0

    era_adj  = profile["era_adj"]
    k9_adj   = profile["k9_adj"]
    whip_adj = profile["whip_adj"]

    if stat == "hits":
        # High K/9 pitcher suppresses hits → negate k9_adj
        return round(-k9_adj * 0.70 + era_adj * 0.20 + whip_adj * 0.10, 4)

    if stat == "totalBases":
        # Extra base hits correlate most strongly with ERA
        return round(era_adj * 0.60 + (-k9_adj) * 0.25 + whip_adj * 0.15, 4)

    if stat == "rbi":
        # RBIs driven by ERA; WHIP contributes via baserunner context
        return round(era_adj * 0.55 + whip_adj * 0.30 + (-k9_adj) * 0.15, 4)

    if stat == "homeRuns":
        # HRs most directly tied to ERA
        return round(era_adj * 0.75 + (-k9_adj) * 0.25, 4)

    if stat == "walks":
        # Walks are in WHIP; high WHIP pitcher issues more free passes
        return round(whip_adj * 0.80 + era_adj * 0.20, 4)

    if stat == "runsScored":
        # Composite: ERA and WHIP both drive run-scoring environment
        return round(era_adj * 0.50 + whip_adj * 0.30 + (-k9_adj) * 0.20, 4)

    if stat == "stolenBases":
        return 0.0

    if stat == "strikeouts":
        # Batter strikeout prop: high K/9 pitcher → batter K prop is easier
        return round(k9_adj * 0.90 + (-era_adj) * 0.10, 4)

    return 0.0


# ── Public API ────────────────────────────────────────────────────────────────

def enrich_legs(
    legs: list[dict],
    pitcher_id_map: dict[str, int],
    opponent_map: dict[str, str],
    season: int | None = None,
) -> list[dict]:
    """
    Attach ``opponent``, ``opposing_pitcher_id``, and ``opponent_adjustment``
    to every leg in-place.

    Legs without a ``team`` field, legs with no opposing pitcher in
    pitcher_id_map, or legs where the pitcher profile cannot be fetched
    receive opponent_adjustment=0.0.

    Args:
        legs:           List of scored leg dicts (modified in-place).
        pitcher_id_map: {batter_team_abbr: opposing_pitcher_id}.
                        Built by main.py from MLB schedule + lineup lookups.
        opponent_map:   {batter_team_abbr: opposing_team_abbr}.
                        Built alongside pitcher_id_map by main.py.
        season:         Season year; defaults to current calendar year.

    Returns:
        The same list with three new fields on each leg.
    """
    if season is None:
        season = datetime.datetime.now().year

    # Pre-fetch all unique pitcher profiles before the per-leg loop
    unique_pitcher_ids = set(pitcher_id_map.values())
    profiles: dict[int, dict | None] = {}
    for pid in sorted(unique_pitcher_ids):
        profiles[pid] = get_pitcher_matchup_profile(pid, season)

    enriched = 0
    for leg in legs:
        team = leg.get("team", "")
        stat = leg.get("stat", "")

        opp_team = opponent_map.get(team)
        pitcher_id = pitcher_id_map.get(team)

        leg["opponent"] = opp_team
        leg["opposing_pitcher_id"] = pitcher_id

        if not pitcher_id:
            leg["opponent_adjustment"] = 0.0
            continue

        profile = profiles.get(pitcher_id)
        if not profile:
            leg["opponent_adjustment"] = 0.0
            continue

        # Determine if this is a pitcher prop: position "SP"/"RP" or
        # stat explicitly in the pitcher-only set.
        position = leg.get("position", "")
        is_pitcher_prop = (
            position in ("SP", "RP", "P")
            or stat in _PITCHER_STATS
        )

        leg["opponent_adjustment"] = _compute_adjustment(stat, profile, is_pitcher_prop)
        enriched += 1

    print(f"  [enrich_legs] Enriched {enriched}/{len(legs)} legs with pitcher matchup profiles")
    return legs
