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

import statsapi

from src.apis.matchup import get_pitcher_matchup_profile, _ERA_MID, _WHIP_MID
from src.utils.db import get_starter_rolling_ip
from src.utils.net import call_with_timeout

# Exposure-weighted starter quality (2026-08-05 scoring redesign, hits/over only).
# Confirmed via two rounds of live-data testing: raw ERA/WHIP is a backwards
# signal because weak-tier starters get pulled early (4.68 IP/start vs 5.39 for
# strong-tier), so the batter disproportionately faces the bullpen instead.
# effective_x blends the starter's raw stat with a league-average fallback,
# weighted by how deep they typically go (rolling_avg_ip_last_5_starts / 6.0).
# League-average constants: reused from matchup.py's own normalisation
# midpoints (_ERA_MID=4.00, _WHIP_MID=1.25) rather than a fresh live aggregate —
# those were already validated as reasonable season-average anchors there.
_LEAGUE_AVG_ERA  = _ERA_MID
_LEAGUE_AVG_WHIP = _WHIP_MID
_EXPOSURE_FULL_IP = 6.0


def get_game_start_time(game_pk: int) -> str | None:
    """Fetch game start time from MLB-StatsAPI. Returns UTC ISO timestamp string."""
    try:
        game_data = call_with_timeout(
            statsapi.get, 'game', {'gamePk': game_pk},
            timeout=15, label=f"statsapi.get(game, gamePk={game_pk})",
        )
        if game_data is None:
            return None
        game_datetime = game_data['gameData']['datetime']['dateTime']
        utc_time = datetime.datetime.fromisoformat(game_datetime.replace('Z', '+00:00'))
        return utc_time.isoformat()
    except Exception as e:
        print(f"Warning: Failed to fetch game time for game_pk {game_pk}: {e}")
        return None


def get_pitcher_handedness(player_id: int, position: str) -> str | None:
    """Fetch pitcher handedness from MLB-StatsAPI. Returns 'RHP', 'LHP', or None."""
    if position not in ('SP', 'RP', 'P'):
        return None
    try:
        player_data = call_with_timeout(
            statsapi.lookup_player, player_id,
            timeout=15, label=f"statsapi.lookup_player({player_id})",
        )
        if player_data:
            pitch_hand = player_data[0].get('pitchHand', {}).get('code')
            if pitch_hand == 'R':
                return 'RHP'
            elif pitch_hand == 'L':
                return 'LHP'
        return None
    except Exception as e:
        print(f"Warning: Failed to fetch handedness for player {player_id}: {e}")
        return None

# ── Prop routing ──────────────────────────────────────────────────────────────

# Stats that belong to pitchers — opponent adjustment is 0.0 (not yet implemented)
_PITCHER_STATS = frozenset({"inningsPitched", "hitsAllowed", "earnedRuns", "strikeouts"})

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
    run_date: str | None = None,
) -> list[dict]:
    """
    Attach ``opponent``, ``opposing_pitcher_id``, and ``opponent_adjustment``
    to every leg in-place.

    Legs without a ``team`` field, legs with no opposing pitcher in
    pitcher_id_map, or legs where the pitcher profile cannot be fetched
    receive opponent_adjustment=0.0.

    Also attaches ``exposure_weight``/``effective_era``/``effective_whip`` to
    every hitter leg with a resolvable opposing starter (point-in-time rolling
    IP, strictly before ``run_date`` — see module-level docstring above).

    Args:
        legs:           List of scored leg dicts (modified in-place).
        pitcher_id_map: {batter_team_abbr: opposing_pitcher_id}.
                        Built by main.py from MLB schedule + lineup lookups.
        opponent_map:   {batter_team_abbr: opposing_team_abbr}.
                        Built alongside pitcher_id_map by main.py.
        season:         Season year; defaults to current calendar year.
        run_date:       'YYYY-MM-DD' date string for the point-in-time rolling
                        IP lookup; defaults to today.

    Returns:
        The same list with new fields on each leg.
    """
    if season is None:
        season = datetime.datetime.now().year
    if run_date is None:
        run_date = datetime.datetime.now().strftime("%Y-%m-%d")

    print(
        f"  [enrich_legs] pitcher_id_map has {len(pitcher_id_map)} team(s): "
        + ", ".join(f"{t}→{pid}" for t, pid in sorted(pitcher_id_map.items()) if pid is not None)
        + (f" | {sum(1 for v in pitcher_id_map.values() if v is None)} team(s) with no pitcher" if any(v is None for v in pitcher_id_map.values()) else "")
    )

    # Pre-fetch all unique pitcher profiles and names before the per-leg loop
    unique_pitcher_ids = set(pitcher_id_map.values())
    profiles: dict[int, dict | None] = {}
    pitcher_names: dict[int, str | None] = {}
    rolling_ip: dict[int, float | None] = {}
    for pid in sorted(pid for pid in unique_pitcher_ids if pid is not None):
        profiles[pid] = get_pitcher_matchup_profile(pid, season)
        try:
            rolling_ip[pid] = get_starter_rolling_ip(str(pid), run_date)
        except Exception as e:
            print(f"  [enrich_legs] get_starter_rolling_ip({pid}) failed: {e}")
            rolling_ip[pid] = None
        try:
            data = call_with_timeout(
                statsapi.lookup_player, pid,
                timeout=15, label=f"statsapi.lookup_player({pid})",
            )
            pitcher_names[pid] = data[0]["fullName"] if data else None
        except Exception:
            pitcher_names[pid] = None

    # Pre-fetch game start times (one API call per unique game_pk)
    unique_game_pks = {leg["game_pk"] for leg in legs if leg.get("game_pk")}
    game_times: dict[int, str | None] = {
        gk: get_game_start_time(gk) for gk in sorted(unique_game_pks)
    }

    enriched = 0
    for leg in legs:
        team = leg.get("team", "")
        stat = leg.get("stat", "")

        opp_team = opponent_map.get(team)
        pitcher_id = pitcher_id_map.get(team)

        leg["opponent"] = opp_team
        leg["opposing_pitcher_id"] = pitcher_id

        # NEW: populate game start time and pitcher handedness
        game_pk = leg.get("game_pk")
        leg["game_start_time"] = game_times.get(game_pk) if game_pk else None

        position = leg.get("position", "")
        player_id = leg.get("player_id")

        # For pitcher props, set pitcher_hand to the pitcher's OWN throwing hand.
        # For hitter legs, pitcher_hand was already set by coverage.py (opposing
        # pitcher's hand) — don't overwrite it with None.
        is_pitcher_prop_leg = position in ("SP", "RP", "P")
        if is_pitcher_prop_leg:
            leg["pitcher_hand"] = get_pitcher_handedness(player_id, position) if player_id else None
            leg["opponent_adjustment"] = 0.0
            leg["pitcher_id"] = None
            leg["pitcher_name"] = None
            leg["pitcher_era"] = None
            leg["pitcher_k9"] = None
            leg["pitcher_whip"] = None
            leg["pitcher_vs_batter_hand_era"] = None
            leg["exposure_weight"] = None
            leg["effective_era"] = None
            leg["effective_whip"] = None
            continue

        if not pitcher_id:
            print(f"  [enrich_legs] No opposing pitcher for team={team} player={leg.get('player_name')} stat={stat} — adjustment=0.0")
            leg["opponent_adjustment"] = 0.0
            leg["pitcher_id"]   = None
            leg["pitcher_name"] = None
            leg["pitcher_era"]  = None
            leg["pitcher_k9"]   = None
            leg["pitcher_whip"] = None
            leg["pitcher_vs_batter_hand_era"] = None
            leg["exposure_weight"] = None
            leg["effective_era"] = None
            leg["effective_whip"] = None
            continue

        profile = profiles.get(pitcher_id)
        if not profile:
            print(f"  [enrich_legs] No profile for pitcher_id={pitcher_id} team={team} player={leg.get('player_name')} — adjustment=0.0")
            leg["opponent_adjustment"] = 0.0
            leg["pitcher_id"]   = None
            leg["pitcher_name"] = None
            leg["pitcher_era"]  = None
            leg["pitcher_k9"]   = None
            leg["pitcher_whip"] = None
            leg["pitcher_vs_batter_hand_era"] = None
            leg["exposure_weight"] = None
            leg["effective_era"] = None
            leg["effective_whip"] = None
            continue

        # Attach raw pitcher profile stats so they persist in mlb_scored_legs
        leg["pitcher_id"]   = str(pitcher_id)
        leg["pitcher_name"] = pitcher_names.get(pitcher_id)
        leg["pitcher_era"]  = profile["era"]
        leg["pitcher_k9"]   = profile["k9"]
        leg["pitcher_whip"] = profile["whip"]

        # Exposure-weighted starter quality (hits/over; see module docstring).
        # rolling_ip is None when the starter has no logged starts before
        # run_date (e.g. season-opener) — fall back to the raw season stat.
        starter_ip = rolling_ip.get(pitcher_id)
        if starter_ip is not None:
            exposure_weight = min(starter_ip / _EXPOSURE_FULL_IP, 1.0)
            leg["exposure_weight"] = round(exposure_weight, 4)
            leg["effective_era"] = round(
                profile["era"] * exposure_weight + _LEAGUE_AVG_ERA * (1 - exposure_weight), 3
            )
            leg["effective_whip"] = round(
                profile["whip"] * exposure_weight + _LEAGUE_AVG_WHIP * (1 - exposure_weight), 3
            )
        else:
            leg["exposure_weight"] = None
            leg["effective_era"] = profile["era"]
            leg["effective_whip"] = profile["whip"]

        leg["opponent_adjustment"] = _compute_adjustment(stat, profile, is_pitcher_prop_leg)
        enriched += 1

    print(f"  [enrich_legs] Enriched {enriched}/{len(legs)} legs with pitcher matchup profiles")

    # Debug: show a sample hitter leg to verify pitcher fields are populated
    sample = next(
        (l for l in legs if l.get("pitcher_id") and l.get("position") not in ("SP", "RP", "P")),
        None
    )
    if sample:
        print(
            f"  [enrich_legs] Sample hitter leg pitcher fields — "
            f"player={sample.get('player_name')} batter_hand={sample.get('batter_hand')} "
            f"pitcher_id={sample.get('pitcher_id')} pitcher_name={sample.get('pitcher_name')} "
            f"pitcher_hand={sample.get('pitcher_hand')} "
            f"era={sample.get('pitcher_era')} k9={sample.get('pitcher_k9')} whip={sample.get('pitcher_whip')}"
        )

    return legs
