"""
coverage.py — Handedness-split batter coverage rate calculator.

For a given player, prop type, line, and opposing pitcher, returns the
historical coverage rate (how often the batter's stat meets or exceeds
the line) adjusted for pitcher handedness via the split ratio method.

## API reality (confirmed April 2026)

MLB-StatsAPI gameLog ignores sitCodes — it returns all games regardless.
Handedness splits are available via statSplits&sitCodes=vl/vr, which gives
rate stats (avg, slg, obp) and gamesPlayed vs that pitcher type.

## Split ratio method

1. Compute exact overall coverage from game-by-game logs (count games >= line)
2. Fetch rate stat (avg/slg/obp) from statSplits for the specific pitcher hand
3. Fetch overall season rate stat for denominator
4. Split ratio = rate_vs_hand / rate_overall
5. Adjusted coverage = exact_overall_coverage × split_ratio

This avoids the Poisson approximation error (which was inverted relative to
actual calibrated results) and uses the game log as the ground truth base rate.

## Stat mappings for split ratio
  hits        → avg  (batting average)
  totalBases  → slg  (slugging percentage)
  walks       → obp  (on-base percentage)
  strikeouts, rbi, homeRuns, stolenBases, runsScored → overall only

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

# Prop types that support split ratio adjustment, mapped to the rate stat used
# for computing the ratio from statSplits vs the overall season stat.
# Props not listed here always use overall game-log coverage (no split adjustment).
SPLIT_RATIO_STAT: dict[str, str] = {
    "hits":       "avg",   # batting average
    "totalBases": "slg",   # slugging percentage
    "walks":      "obp",   # on-base percentage
}


# ── helpers ──────────────────────────────────────────────────────────────────

def _poisson_coverage(mu: float, line: float) -> float:
    """
    Estimate P(stat >= line) where stat ~ Poisson(mu).

    Used only by calculate_pitcher_k_coverage() — NOT used for batter props,
    which use the split ratio method instead.
    """
    if mu <= 0:
        return 0.0
    k = int(line)
    e_neg_mu = math.exp(-mu)
    cdf = 0.0
    term = e_neg_mu
    for i in range(k + 1):
        cdf += term
        term *= mu / (i + 1)
    return max(0.0, min(1.0, 1.0 - cdf))


def _get_stat_splits(player_id: int, season: int, pitcher_hand: str) -> dict | None:
    """
    Return statSplits stat dict for a batter vs one pitcher handedness.

    Calls the statSplits&sitCodes=vl/vr endpoint. Returns the full stat dict
    (including avg, slg, obp, gamesPlayed), or None on network error / no data.

    Note: gamesPlayed counts games where the batter had at least one PA against
    a pitcher of that type (including relievers). It is an overcount relative to
    "starter hand only" but is the best available signal.
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


def _get_overall_season_stats(player_id: int, season: int) -> dict | None:
    """
    Return overall season hitting stats (avg, slg, obp, etc.) for a batter.

    Used as the denominator when computing the split ratio.
    """
    try:
        r = requests.get(
            f"{BASE_URL}/people/{player_id}/stats",
            params={
                "stats": "season",
                "group": "hitting",
                "season": str(season),
            },
            timeout=15,
        )
        r.raise_for_status()
        splits = r.json().get("stats", [{}])[0].get("splits", [])
        if not splits:
            return None
        return splits[0].get("stat")
    except Exception as e:
        print(f"  [coverage] _get_overall_season_stats({player_id}, {season}) error: {e}")
        return None


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

    ## Split ratio path (hits, totalBases, walks)
    When pitcher_hand is known AND the prop type has a SPLIT_RATIO_STAT mapping
    AND split games >= 10 AND the overall rate stat is non-zero:
      - Fetches rate stat (avg/slg/obp) from statSplits vs that handedness
      - Fetches the same rate stat from overall season stats
      - Split ratio = rate_vs_hand / rate_overall
      - Adjusted coverage = exact_overall_coverage × split_ratio (capped 0–1)
      - Applies confidence multiplier from split game count

    ## Fallback path
    When pitcher_hand is unknown, prop type lacks a split ratio mapping, or
    split games < 10:
      - Uses exact game-log coverage rate (proportion of games >= line)
      - Applies fixed multiplier 0.65

    ## Switch hitters (bats='S')
    No special handling — the split stats already reflect their actual
    matchup-based splits across the season.
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

    # 3. Full-season game log — drives the minimum-games gate and base rate
    full_log = get_batter_game_log(player_id, season)
    overall_over, overall_games = _count_coverage(full_log, stat_field, line)

    # Seasonal ramp-up minimum — return None below threshold (blueprint §4.2)
    if overall_games < get_season_minimum(overall_games):
        return None

    overall_rate = overall_over / overall_games

    # 4. Split ratio adjustment
    #
    # Conditions for split path:
    #   a) pitcher_hand is known
    #   b) prop type has a rate stat mapped in SPLIT_RATIO_STAT
    #   c) split has >= 10 game appearances vs that hand
    #   d) overall rate stat > 0 (avoids division by zero)
    use_split = False
    rate_stat = SPLIT_RATIO_STAT.get(prop_type)

    if pitcher_hand and rate_stat:
        split_stats = _get_stat_splits(player_id, season, pitcher_hand)
        overall_stats = _get_overall_season_stats(player_id, season)

        if split_stats is not None and overall_stats is not None:
            split_games = int(split_stats.get("gamesPlayed") or 0)
            rate_vs_hand = float(split_stats.get(rate_stat) or 0)
            rate_overall = float(overall_stats.get(rate_stat) or 0)

            if split_games >= 10 and rate_overall > 0:
                split_ratio = rate_vs_hand / rate_overall
                coverage_rate = max(0.0, min(1.0, overall_rate * split_ratio))
                games_used = split_games
                split_used = "handedness"
                multiplier = _confidence_multiplier(split_games)
                use_split = True

    if not use_split:
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
