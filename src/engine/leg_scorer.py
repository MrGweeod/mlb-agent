"""
leg_scorer.py — Five-factor composite scoring for qualifying MLB parlay legs.

MLB adaptation of the NBA leg_scorer. Key differences:
  - PA stability replaces minutes stability as the 5th factor.
    pa_avg_10 (avg atBats/game over last 10) is sourced from the trend signal
    attached to each leg dict by the scoring pipeline.
  - Recency-weighted coverage uses the MLB batter game log (oldest-first)
    rather than nba_api game log (most-recent-first).
  - _build_team_to_blocked uses leg dict team fields rather than nba_api static
    player lookup. Fallback builds the map from the candidate leg pool.
  - Pitcher props (position SP/RP) fall back to coverage_pct / 100 for the
    recency-weighted coverage factor since pitcher prop coverage is not yet
    implemented in a separate pipeline stage.

Factors and weights (emergency recalibration 2026-04-21):

  Calibration findings (176 resolved legs, April 17–18):
    - Coverage rate: 10–30% overconfident → apply confidence multiplier upstream
      + prop-specific penalty multipliers below
    - EV signal: INVERTED in old formula (zeroed until new formula validated)
    - Trend signal: zero predictive value (dropped)
    - Opponent adjustment: logical signal, kept
    - Pitcher K props (Poisson model): well calibrated, no penalty needed

  Both anchor and swing now share the same emergency weight profile:
    1. Coverage (with prop penalty)  70%
    2. Opponent adjustment           20%
    3. PA stability                  10%
    EV / trend                        0%  (re-enable after calibration confirms)

All factors normalised to [0, 1] before weighting.
Final composite_score ∈ [0, 100], attached to each leg dict in-place.
"""
from __future__ import annotations

_WEIGHT_COVERAGE_ANCHOR  = 0.70
_WEIGHT_EV_ANCHOR        = 0.00
_WEIGHT_TREND_ANCHOR     = 0.00
_WEIGHT_OPPONENT_ANCHOR  = 0.20
_WEIGHT_PA_ANCHOR        = 0.10

_WEIGHT_COVERAGE_SWING   = 0.70
_WEIGHT_EV_SWING         = 0.00
_WEIGHT_TREND_SWING      = 0.00
_WEIGHT_OPPONENT_SWING   = 0.20
_WEIGHT_PA_SWING         = 0.10

# Per-prop overconfidence correction factors (2026-04-21 calibration, 458 legs).
# strikeouts (Poisson pitcher model): +2.6% error → 1.0 (well calibrated).
# hits: +2.4% error → 0.85 (well calibrated after penalty).
# totalBases: +13.4% error (24 legs) → tightened to 0.78.
# rbi: +29.2% error (14 legs) — too small to retune; keep 0.90 pending more data.
# walks: +13.0% error (11 legs) — too small to retune; keep 0.85 pending more data.
# These multiply the recency-weighted coverage factor before composite scoring.
_PROP_COVERAGE_PENALTY: dict[str, float] = {
    "strikeouts":  1.00,  # pitcher K props — well calibrated (+2.6% error, 77 legs)
    "hits":        0.85,  # well calibrated after penalty (+2.4% error, 150 legs)
    "totalBases":  0.78,  # tightened: +13.4% error on 24 legs
    "rbi":         0.90,  # insufficient data (14 legs) — pending retune
    "walks":       0.85,  # insufficient data (11 legs) — pending retune
    "homeRuns":    0.85,
    "runsScored":  0.90,
    "stolenBases": 0.90,
}

_EV_CLIP_LOW  = -0.5
_EV_CLIP_HIGH =  0.5
_TREND_MAX    =  8.0
_PA_FULL      =  4.0   # 4+ AB/game → PA stability = 1.0

# Pitcher-only prop stats that fall back to coverage_pct for recency weighting
_PITCHER_STATS = frozenset({"inningsPitched", "hitsAllowed", "earnedRuns"})


def _recency_weighted_coverage(leg: dict) -> float:
    """
    Compute recency-weighted hit rate for a batter prop leg.

    MLB game log is OLDEST-FIRST from mlb_stats. Most recent 5 games are
    at the end of the list: games[-5:] carry 3×, games[-10:-5] carry 2×,
    games[:-10] carry 1×.

    Falls back to coverage_pct / 100 when:
      - player_id, stat, or best_line is missing from the leg
      - the game log cannot be fetched
      - the stat belongs to a pitcher prop (separate coverage logic TBD)
      - the player has no game log entries

    Returns:
        Float ∈ [0, 1].
    """
    from src.engine.coverage import PROP_STAT_MAP
    from src.apis.mlb_stats import get_batter_game_log

    pid       = leg.get("player_id", "")
    stat      = leg.get("stat", "")
    line      = leg.get("best_line")
    direction = leg.get("direction", "over")
    fallback  = leg.get("coverage_pct", 0.0) / 100.0

    if not pid or not stat or line is None:
        return fallback

    # Pitcher props — batter game log doesn't apply; use coverage_pct fallback.
    # Check both the pitcher-stat set and position field so that pitcher K props
    # (stat='strikeouts', position='SP'/'RP') are correctly routed here rather
    # than falling through to the batter game-log path.
    position = leg.get("position", "")
    if stat in _PITCHER_STATS or position in {"SP", "RP", "P", "TWP"}:
        return fallback

    stat_field = PROP_STAT_MAP.get(stat)
    if not stat_field:
        return fallback

    # MLB player_id may be stored as string "664285" or int; normalise to int
    try:
        mlb_id = int(pid)
    except (ValueError, TypeError):
        return fallback

    import datetime
    season = datetime.datetime.now().year
    games = get_batter_game_log(mlb_id, season)
    if not games:
        return fallback

    weighted_hits  = 0.0
    weighted_total = 0.0
    n = len(games)

    for i, game in enumerate(games):
        val_raw = game.get("stat", {}).get(stat_field)
        if val_raw is None:
            continue
        try:
            val = float(val_raw)
        except (ValueError, TypeError):
            continue

        # Recency weight: last 5 games (i >= n-5) = 3×, next 5 (i >= n-10) = 2×, older = 1×
        if i >= n - 5:
            weight = 3.0
        elif i >= n - 10:
            weight = 2.0
        else:
            weight = 1.0

        weighted_total += weight
        hit = (val <= line) if direction == "under" else (val >= line)
        if hit:
            weighted_hits += weight

    if weighted_total == 0.0:
        return fallback

    return weighted_hits / weighted_total


def _build_team_to_blocked(blocked_players: set[str], candidate_legs: list[dict]) -> dict[str, int]:
    """
    Return {team_abbr: blocked_player_count} from the candidate leg pool.

    MLB alternative to the NBA version that used nba_api static player lookup.
    Looks for blocked player names in the legs already processed, inferring
    their team from the leg dict's 'team' field.

    Args:
        blocked_players:  Set of blocked player display names (from injury filter).
        candidate_legs:   Legs from the current pipeline run (used to map name → team).

    Returns:
        {team_abbr: n_blocked} for teams with at least one blocked player.
    """
    name_to_team: dict[str, str] = {}
    for leg in candidate_legs:
        name = leg.get("player_name", "")
        team = leg.get("team", "")
        if name and team:
            name_to_team[name] = team

    team_blocked: dict[str, int] = {}
    for name in blocked_players:
        team = name_to_team.get(name)
        if team:
            team_blocked[team] = team_blocked.get(team, 0) + 1

    return team_blocked


def _pa_stability_factor(leg: dict) -> float:
    """
    Return a [0, 1] factor for plate-appearance stability.

    Sources pa_avg_10 from the leg dict (set by trend_analysis).
    4+ AB/game average → 1.0; 0 AB → 0.0.
    Falls back to 0.5 (neutral) when not available.
    """
    pa_avg = leg.get("pa_avg_10")
    if pa_avg is None:
        return 0.5
    return min(float(pa_avg) / _PA_FULL, 1.0)


def score_leg(
    leg: dict,
    team_to_blocked: dict[str, int] | None = None,
    role: str = "swing",
) -> float:
    """
    Compute the composite score (0–100) for a single qualifying leg.

    Combines five normalised factors with role-specific weights:
      role="anchor" — coverage 60%, trend 15%, opponent 15%, PA stability 10%, EV 0%
      role="swing"  — coverage 40%, EV 25%, trend 15%, opponent 15%, PA stability 5%

    Args:
        leg:             Scored leg dict with trend signals attached.
        team_to_blocked: {team_abbr: n_blocked} for teammate injury context
                         (currently unused — PA stability is the 5th factor for anchors;
                         kept for API compatibility with parlay_builder.py).
        role:            "anchor" or "swing".

    Returns:
        Float ∈ [0, 100].
    """
    # Factor 1 — recency-weighted coverage [0, 1] with prop-specific penalty.
    # Penalty corrects for systematic overconfidence identified in calibration
    # (April 17-18 data: batter props 10-30% overconfident vs actual hit rate).
    stat       = leg.get("stat", "")
    prop_mult  = _PROP_COVERAGE_PENALTY.get(stat, 0.85)
    f_coverage = _recency_weighted_coverage(leg) * prop_mult

    # Factor 2 — EV / odds value [0, 1]
    ev         = float(leg.get("ev_per_unit") or 0.0)
    ev_clipped = max(_EV_CLIP_LOW, min(_EV_CLIP_HIGH, ev))
    f_ev       = (ev_clipped - _EV_CLIP_LOW) / (_EV_CLIP_HIGH - _EV_CLIP_LOW)

    # Factor 3 — trend score [0, 1]
    trend   = float(leg.get("trend_score") or 0.0)
    f_trend = min(max(trend, 0.0), _TREND_MAX) / _TREND_MAX

    # Factor 4 — opponent adjustment [0, 1]
    opp_adj    = float(leg.get("opponent_adjustment") or 0.0)
    f_opponent = (opp_adj + 1.0) / 2.0

    # Factor 5 — PA stability [0, 1]
    f_pa = _pa_stability_factor(leg)

    if role == "anchor":
        composite = (
            f_coverage  * _WEIGHT_COVERAGE_ANCHOR  +
            f_ev        * _WEIGHT_EV_ANCHOR        +
            f_trend     * _WEIGHT_TREND_ANCHOR     +
            f_opponent  * _WEIGHT_OPPONENT_ANCHOR  +
            f_pa        * _WEIGHT_PA_ANCHOR
        ) * 100.0
    else:
        composite = (
            f_coverage  * _WEIGHT_COVERAGE_SWING   +
            f_ev        * _WEIGHT_EV_SWING         +
            f_trend     * _WEIGHT_TREND_SWING      +
            f_opponent  * _WEIGHT_OPPONENT_SWING   +
            f_pa        * _WEIGHT_PA_SWING
        ) * 100.0

    return round(composite, 2)


def score_legs_composite(
    legs: list[dict],
    blocked_players: set[str] | None = None,
    team_to_blocked: dict[str, int] | None = None,
    role: str = "swing",
) -> list[dict]:
    """
    Attach composite_score to every leg in-place and return the list unchanged.

    Args:
        legs:            Qualifying legs entering the parlay builder.
        role:            "anchor" or "swing" — selects weight profile.
        team_to_blocked: Pre-built {team_abbr: count} mapping (preferred path).
                         Passed through to score_leg for future teammate injury
                         logic; currently not used in scoring calculation.
        blocked_players: Fallback — builds team_to_blocked from candidate legs
                         when team_to_blocked is not provided.

    Returns:
        The same list with composite_score added to each leg dict.
    """
    if team_to_blocked is None and blocked_players:
        team_to_blocked = _build_team_to_blocked(blocked_players, legs)

    if team_to_blocked:
        print(f"  [leg_scorer] teammate injury context: {team_to_blocked}")

    for leg in legs:
        leg["composite_score"] = score_leg(leg, team_to_blocked, role=role)

    return legs
