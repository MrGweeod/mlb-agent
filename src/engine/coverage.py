"""
coverage.py — Handedness-split batter coverage rate calculator.

For a given player, prop type, line, and opposing pitcher, returns the
historical coverage rate (how often the batter's stat meets or exceeds
the line) split by pitcher handedness.

## API reality (confirmed April 2026)

MLB-StatsAPI gameLog ignores sitCodes — it returns all games regardless.
Handedness splits are available via statSplits&sitCodes=vl/vr, which gives:
  - gamesPlayed: games where batter had PA vs that pitcher type
  - counting stats: aggregate season totals vs that pitcher type

For stats supported by statSplits (hits, totalBases, rbi, homeRuns,
baseOnBalls, strikeOuts), coverage rate vs a handedness is estimated
using a Poisson approximation from the per-game average:

  P(stat >= line) ≈ 1 − Poisson_CDF(floor(line), avg_per_game)

This is a good estimate for low-count discrete stats (0–4 range / game).

For stats NOT available in statSplits (stolenBases, runs), the function
always falls back to the overall game-log coverage rate.

## Blueprint Section 4.2 confidence multipliers
  ≥50 split games → 1.0
  30–49           → 0.85
  20–29           → 0.70
  10–19           → 0.60
  <10             → fall back to overall coverage rate at 0.65
"""
import datetime
import math
import requests

from src.apis.mlb_stats import get_batter_game_log, get_pitcher_hand
from src.utils.db import get_player_handedness

# Position codes that identify a pitcher (used by leg_scorer to route coverage)
PITCHER_POSITIONS = frozenset({"P", "SP", "RP", "TWP"})

BASE_URL = "https://statsapi.mlb.com/api/v1"

def get_season_minimum(games_played: int) -> int:
    """
    Return the minimum games threshold for the current point in the season.

    Ramps up from 8 (first two weeks) to 20 (full season) so early-season
    players aren't blanket-excluded when sample sizes are still building.
    """
    if games_played < 15:
        return 8
    if games_played < 30:
        return 12
    return 20

# Prop type → stat field in MLB-StatsAPI gameLog splits (all confirmed live)
PROP_STAT_MAP: dict[str, str] = {
    "hits":        "hits",
    "totalBases":  "totalBases",
    "rbi":         "rbi",
    "homeRuns":    "homeRuns",
    "stolenBases": "stolenBases",
    "runsScored":  "runs",
    "walks":       "baseOnBalls",
    "strikeouts":  "strikeOuts",
}

# Stats available in statSplits sitCodes response (vl/vr).
# stolenBases and runs are null there — must use overall game log fallback.
_SPLIT_SUPPORTED = {"hits", "totalBases", "rbi", "homeRuns", "baseOnBalls", "strikeOuts"}


# ── helpers ──────────────────────────────────────────────────────────────────

def _get_stat_splits(player_id: int, season: int, pitcher_hand: str) -> dict | None:
    """
    Return statSplits aggregate for a batter vs one pitcher handedness.

    Calls the statSplits&sitCodes=vl/vr endpoint.  Returns a dict with the
    stat fields and 'gamesPlayed', or None on network error / no data.

    Note: gamesPlayed here counts games where the batter had at least one PA
    against a pitcher of that type (including relievers), not strictly games
    where the opposing starter had that handedness.  It is an overcount relative
    to "starter hand" but is the best available signal without per-game starter
    lookups.
    """
    sit_code = "vl" if pitcher_hand == "L" else "vr"
    try:
        r = requests.get(
            f"{BASE_URL}/people/{player_id}/stats",
            params={
                "stats": "statSplits",
                "group": "hitting",
                "season": str(season),
                "sitCodes": sit_code,
            },
            timeout=15,
        )
        r.raise_for_status()
        splits = r.json().get("stats", [{}])[0].get("splits", [])
        if not splits:
            return None
        return splits[0].get("stat")
    except Exception as e:
        print(f"  [coverage] _get_stat_splits({player_id}, {season}, {pitcher_hand}) error: {e}")
        return None


def _poisson_coverage(mu: float, line: float) -> float:
    """
    Estimate P(stat >= line) where stat ~ Poisson(mu).

    Works for non-integer lines (0.5, 1.5, 2.5) by using floor(line) as the
    highest integer strictly below line.  Returns 0.0 if mu <= 0.

    Example:
      line=0.5 → P(stat >= 1) = 1 − P(stat=0) = 1 − e^{−mu}
      line=1.5 → P(stat >= 2) = 1 − P(stat=0) − P(stat=1)
    """
    if mu <= 0:
        return 0.0
    # highest integer k such that k < line  →  we want P(stat >= k+1) = 1 − CDF(k)
    k = int(line)  # floor(line); for line=0.5 k=0; for line=1.5 k=1
    # Poisson CDF: P(X <= k) = Σ_{i=0}^{k} e^{-mu} * mu^i / i!
    e_neg_mu = math.exp(-mu)
    cdf = 0.0
    term = e_neg_mu
    for i in range(k + 1):
        cdf += term
        term *= mu / (i + 1)
    return max(0.0, min(1.0, 1.0 - cdf))


def _count_coverage(game_log: list[dict], stat_field: str, line: float) -> tuple[int, int]:
    """
    Exact count of games in *game_log* where stat_field met or exceeded line.

    Returns (games_over_line, total_valid_games).  Entries missing the field
    or with non-numeric values are skipped from both counts.
    """
    over = 0
    total = 0
    for entry in game_log:
        raw = entry.get("stat", {}).get(stat_field)
        if raw is None:
            continue
        try:
            val = float(raw)
        except (ValueError, TypeError):
            continue
        total += 1
        if val >= line:
            over += 1
    return over, total


def _confidence_multiplier(n_games: int) -> float:
    """
    Return confidence multiplier per blueprint Section 4.2.

    Called only when n_games >= 10 (the <10 fallback is handled by caller).
    """
    if n_games >= 50:
        return 1.0
    if n_games >= 30:
        return 0.85
    if n_games >= 20:
        return 0.70
    return 0.60  # 10–19


# ── public API ────────────────────────────────────────────────────────────────

def calculate_coverage(
    player_id: int,
    prop_type: str,
    line: float,
    opposing_pitcher_id: int,
    season: int = None,
) -> dict | None:
    """
    Calculate handedness-split coverage rate for a batter prop.

    Args:
        player_id:            MLB person ID for the batter.
        prop_type:            One of: hits, totalBases, rbi, homeRuns,
                              stolenBases, runsScored, walks, strikeouts.
        line:                 The prop line (e.g. 0.5 for HR, 1.5 for hits).
        opposing_pitcher_id:  MLB person ID for today's opposing starter.
        season:               Season year; defaults to current calendar year.

    Returns:
        Dict with keys:
          coverage_rate         float   0.0–1.0
          games_used            int     sample size behind coverage_rate
          split_used            str     'handedness' or 'overall_fallback'
          confidence_multiplier float   per blueprint Section 4.2
          pitcher_hand          str|None  'L' or 'R'
          batter_hand           str|None  'L', 'R', or 'S'

        Returns None when the player has fewer than get_season_minimum()
        overall games (8/12/20 depending on season depth per blueprint §4.2).

    ## Split path
    When pitcher_hand is known AND the prop type is supported in statSplits
    (hits, totalBases, rbi, homeRuns, walks, strikeouts) AND split games >= 10:
      - Fetches statSplits aggregate vs that handedness
      - Estimates coverage using Poisson(avg_per_game) approximation
      - Applies confidence multiplier from split game count

    ## Fallback path
    When pitcher_hand is unknown, prop type unsupported in statSplits, or
    split games < 10:
      - Uses exact game-log coverage rate (proportion of games >= line)
      - Applies fixed multiplier 0.65

    ## Switch hitters (bats='S')
    No special handling — they face the opposite handedness on any given day
    so their split is already consistent as-is.
    """
    if season is None:
        season = datetime.datetime.now().year

    stat_field = PROP_STAT_MAP.get(prop_type)
    if not stat_field:
        print(f"  [coverage] Unknown prop_type '{prop_type}'. "
              f"Valid: {list(PROP_STAT_MAP)}")
        return None

    # 1. Pitcher handedness — from mlb_stats in-memory cache (7-day TTL)
    pitcher_hand = get_pitcher_hand(opposing_pitcher_id)

    # 2. Batter handedness — from DB position cache; None if not populated yet
    try:
        batter_hand = get_player_handedness(str(player_id))
    except Exception:
        batter_hand = None

    # 3. Full-season game log — drives the minimum-games gate and fallback rate
    full_log = get_batter_game_log(player_id, season)
    overall_over, overall_games = _count_coverage(full_log, stat_field, line)

    # Seasonal ramp-up minimum — return None below threshold (blueprint §4.2)
    if overall_games < get_season_minimum(overall_games):
        return None

    overall_rate = overall_over / overall_games

    # 4–6. Handedness split or fallback
    #
    # Conditions for using the split path:
    #   a) pitcher_hand is known
    #   b) the stat is available in statSplits (not stolenBases or runs)
    #   c) split has >= 10 game appearances vs that hand
    use_split = False
    if pitcher_hand and stat_field in _SPLIT_SUPPORTED:
        split_stats = _get_stat_splits(player_id, season, pitcher_hand)
        if split_stats is not None:
            split_games = split_stats.get("gamesPlayed") or 0
            split_total = split_stats.get(stat_field)
            if split_games >= 10 and split_total is not None:
                use_split = True

    if use_split:
        avg_per_game = float(split_total) / split_games
        coverage_rate = _poisson_coverage(avg_per_game, line)
        games_used = split_games
        split_used = "handedness"
        multiplier = _confidence_multiplier(split_games)
    else:
        # Fall back to exact overall coverage rate at multiplier 0.65
        coverage_rate = overall_rate
        games_used = overall_games
        split_used = "overall_fallback"
        multiplier = 0.65

    return {
        "coverage_rate":          coverage_rate,
        "games_used":             games_used,
        "split_used":             split_used,
        "confidence_multiplier":  multiplier,
        "pitcher_hand":           pitcher_hand,
        "batter_hand":            batter_hand,
    }


def calculate_pitcher_k_coverage(
    pitcher_id: int,
    line: float,
    season: int = None,
) -> dict | None:
    """
    Calculate Poisson coverage rate for a pitcher strikeout prop.

    Fetches the pitcher's season strikeout total and games started (falling
    back to games pitched when starts < 3), computes K/start average, then
    applies the same Poisson approximation used for batter props.

    Args:
        pitcher_id: MLB person ID for the starting pitcher.
        line:       The prop line (e.g. 4.5 for over 4.5 Ks).
        season:     Season year; defaults to current calendar year.

    Returns:
        Dict matching calculate_coverage() output shape, or None if season
        stats are unavailable or the pitcher has fewer than 3 appearances.
    """
    if season is None:
        season = datetime.datetime.now().year

    try:
        import statsapi as _statsapi
        data = _statsapi.player_stat_data(
            pitcher_id, group="pitching", type="season", sportId=1
        )
        stat_entries = data.get("stats", [])
        if not stat_entries:
            return None
        # player_stat_data returns a list of {type, group, season, stats: {...}}
        st = stat_entries[0].get("stats", {})
        total_k       = float(st.get("strikeOuts", 0) or 0)
        games_started = int(st.get("gamesStarted", 0) or 0)
        games_pitched = int(st.get("gamesPitched", 0) or 0)
    except Exception as e:
        print(f"  [coverage] calculate_pitcher_k_coverage({pitcher_id}) error: {e}")
        return None

    # Prefer starts as denominator (K/start is the meaningful rate for props);
    # fall back to appearances for relievers with enough outings.
    denom = games_started if games_started >= 3 else games_pitched
    if denom < 3:
        return None  # too small a sample to estimate reliably

    k_per_game   = total_k / denom
    coverage_rate = _poisson_coverage(k_per_game, line)
    multiplier   = _confidence_multiplier(denom) if denom >= 10 else 0.60

    return {
        "coverage_rate":         coverage_rate,
        "games_used":            denom,
        "split_used":            "pitcher_season_k_rate",
        "confidence_multiplier": multiplier,
        "pitcher_hand":          None,
        "batter_hand":           None,
    }
