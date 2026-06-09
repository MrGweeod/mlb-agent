"""
coverage.py — Multi-signal coverage calculator for MLB prop legs.

Returns three distinct coverage rates so they can be weighted independently
in composite scoring (Phase 2), rather than being collapsed into one number.

## Return structure

For HITTERS:
    coverage_overall   — % of ALL games this season where stat met the line
    coverage_vs_hand   — % adjusted for pitcher handedness (None if <10 games
                         vs that hand, or if the prop type lacks a split-ratio
                         mapping)
    coverage_recent_10 — % of the LAST 10 games where stat met the line
    games_total        — total games in game log this season
    games_vs_hand      — games vs this pitcher handedness (None if unknown)
    games_recent       — number of recent games used (≤10)
    pitcher_hand       — 'L', 'R', or None
    batter_hand        — 'L', 'R', 'S', or None

For PITCHERS (position in SP/RP/P/TWP, or stat in pitcher-only set):
    coverage_overall   — % of ALL starts where stat met the line
    coverage_vs_hand   — None (no handedness split for pitchers)
    coverage_recent_10 — % of LAST 10 starts where stat met the line
    games_total        — total starts in log this season
    games_vs_hand      — None
    games_recent       — number of recent starts used (≤10)
    pitcher_hand       — None
    batter_hand        — None

## Handedness adjustment (hitters only)

For hits / totalBases / walks, the vs-hand rate is derived via log-odds
adjustment using StatSplits rate stats (avg/slg/obp). Props not listed in
SPLIT_RATIO_STAT get coverage_vs_hand=None.

Minimum 10 games vs that handedness required; otherwise coverage_vs_hand=None.

## Innings pitched

The MLB API stores inningsPitched as "6.1" meaning 6⅓ innings (6 full + 1 out).
_count_ip_coverage() handles this conversion separately.
"""
import datetime
import math
import requests

from src.apis.mlb_stats import get_batter_game_log, get_pitcher_game_log, get_pitcher_hand
from src.utils.db import get_player_handedness

# Position codes that identify a pitcher
PITCHER_POSITIONS = frozenset({"P", "SP", "RP", "TWP"})

BASE_URL = "https://statsapi.mlb.com/api/v1"

# Prop type → stat field in batter game log
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

# Prop type → stat field in pitcher game log
PITCHER_PROP_STAT_MAP: dict[str, str] = {
    "strikeouts":     "strikeOuts",
    "inningsPitched": "inningsPitched",
    "hitsAllowed":    "hits",
    "earnedRuns":     "earnedRuns",
    "walks":          "baseOnBalls",
}

# Props that support log-odds split adjustment, mapped to their rate stat
SPLIT_RATIO_STAT: dict[str, str] = {
    "hits":       "avg",
    "totalBases": "slg",
    "walks":      "obp",
}


def get_season_minimum(games_played: int) -> int:
    """Minimum games threshold that ramps up as the season deepens."""
    if games_played < 15:
        return 8
    if games_played < 30:
        return 12
    return 20


def get_season_minimum_pitcher(games_played: int) -> int:
    """Minimum starts threshold for pitchers."""
    if games_played < 10:
        return 6
    if games_played < 15:
        return 8
    return 10
    
    # ── helpers ───────────────────────────────────────────────────────────────────

def _count_coverage(game_log: list[dict], stat_field: str, line: float, direction: str = "over") -> tuple[int, int]:
    """
    Count games in game_log where stat_field covered the line.

    For 'over': counts games where val >= line.
    For 'under': counts games where val < line.

    Returns (games_covered, total_valid_games).
    Entries missing the field or with non-numeric values are skipped.
    """
    covered = 0
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
        if direction == "under":
            if val < line:
                covered += 1
        else:
            if val >= line:
                covered += 1
    return covered, total


def _count_ip_coverage(game_log: list[dict], line: float, direction: str = "over") -> tuple[int, int]:
    """
    Count starts where inningsPitched covered the line.

    Parses the MLB API "6.1" format: integer part = full innings,
    decimal part = outs (so "6.1" = 6⅓, "6.2" = 6⅔).

    For 'over': counts starts where val >= line.
    For 'under': counts starts where val < line.
    """
    covered = 0
    total = 0
    for entry in game_log:
        raw = entry.get("stat", {}).get("inningsPitched")
        if raw is None:
            continue
        try:
            parts = str(raw).split(".")
            full = int(parts[0])
            thirds = int(parts[1]) if len(parts) > 1 else 0
            val = full + thirds / 3.0
        except (ValueError, TypeError, IndexError):
            continue
        total += 1
        if direction == "under":
            if val < line:
                covered += 1
        else:
            if val >= line:
                covered += 1
    return covered, total


def _get_stat_splits(player_id: int, season: int, pitcher_hand: str) -> dict | None:
    """Return statSplits stat dict for a batter vs one pitcher handedness."""
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
    """Return overall season hitting stats for a batter (avg, slg, obp, etc.)."""
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


# ── public API ────────────────────────────────────────────────────────────────

def calculate_coverage(
    player_id: int,
    prop_type: str,
    line: float,
    opposing_pitcher_id: int | None,
    season: int = None,
    position: str = "",
    direction: str = "over",
) -> dict | None:
    """
    Calculate multi-signal coverage for a single prop leg.

    Detects pitcher props by position (SP/RP/P/TWP) or prop_type
    (inningsPitched, hitsAllowed, earnedRuns). Pitcher strikeouts are treated
    as pitcher props only when position is a pitcher position.

    direction: 'over' or 'under'. Coverage is the % of games where the prop
    would have won — for 'over' that means val >= line, for 'under' val < line.

    Returns:
        Dict with coverage signals (see module docstring), or None when there
        are too few games to compute a reliable estimate.
    """
    if season is None:
        season = datetime.datetime.now().year

    if direction not in ("over", "under"):
        raise ValueError(f"[coverage] Invalid direction '{direction}' — must be 'over' or 'under'")
    print(f"  [coverage] calculating {prop_type} {direction} {line} player={player_id}")

    is_pitcher = (
        position in PITCHER_POSITIONS
        or prop_type in {"inningsPitched", "hitsAllowed", "earnedRuns"}
    )

    if is_pitcher:
        result = _pitcher_coverage(player_id, prop_type, line, season, direction)
    else:
        result = _hitter_coverage(player_id, prop_type, line, opposing_pitcher_id, season, direction)

    # Warn on suspiciously high coverage for risky props
    if result and prop_type == "strikeouts":
        cov = result.get("coverage_overall", 0) or 0
        if cov > 90 and direction == "over" and line > 0.5 and not is_pitcher:
            print(f"  [coverage WARNING] player={player_id} SO {direction} {line} = {cov:.1f}% — hitter with >0.5 line, verify data")

    return result


def _hitter_coverage(
    player_id: int,
    prop_type: str,
    line: float,
    opposing_pitcher_id: int | None,
    season: int,
    direction: str = "over",
) -> dict | None:
    """Calculate overall, vs-hand, and recent-10 coverage for a batter prop."""
    stat_field = PROP_STAT_MAP.get(prop_type)
    if not stat_field:
        print(f"  [coverage] Unknown prop_type '{prop_type}'. Valid: {list(PROP_STAT_MAP)}")
        return None

    full_log = get_batter_game_log(player_id, season)
    overall_covered, overall_games = _count_coverage(full_log, stat_field, line, direction)

    if overall_games < get_season_minimum(overall_games):
        return None

    coverage_overall = round(100.0 * overall_covered / overall_games, 1)
    overall_rate = overall_covered / overall_games

    # Recent 10 games
    recent_log = full_log[-10:]
    recent_covered, recent_games = _count_coverage(recent_log, stat_field, line, direction)
    coverage_recent_10 = round(100.0 * recent_covered / recent_games, 1) if recent_games > 0 else None

    # Handedness split
    coverage_vs_hand = None
    games_vs_hand = None
    pitcher_hand = get_pitcher_hand(opposing_pitcher_id) if opposing_pitcher_id else None
    rate_stat = SPLIT_RATIO_STAT.get(prop_type)

    if pitcher_hand and rate_stat:
        split_stats = _get_stat_splits(player_id, season, pitcher_hand)
        overall_stats = _get_overall_season_stats(player_id, season)

        if split_stats and overall_stats:
            n_vs_hand = int(split_stats.get("gamesPlayed") or 0)
            games_vs_hand = n_vs_hand if n_vs_hand > 0 else None

            if n_vs_hand >= 10:
                rate_vs_hand = float(split_stats.get(rate_stat) or 0)
                rate_overall_stat = float(overall_stats.get(rate_stat) or 0)

                if rate_overall_stat > 0 and rate_vs_hand > 0:
                    if 0 < overall_rate < 1:
                        log_odds_base = math.log(overall_rate / (1 - overall_rate))
                        # For UNDER props, higher batting stat means WORSE coverage,
                        # so invert the adjustment direction.
                        ratio = rate_vs_hand / rate_overall_stat
                        if direction == "under":
                            log_odds_adj = -math.log(ratio)
                        else:
                            log_odds_adj = math.log(ratio)
                        adjusted_rate = 1.0 / (1.0 + math.exp(-(log_odds_base + log_odds_adj)))
                        coverage_vs_hand = round(adjusted_rate * 100, 1)
                    else:
                        coverage_vs_hand = round(overall_rate * 100, 1)

    batter_hand = None
    try:
        batter_hand = get_player_handedness(str(player_id))
    except Exception:
        pass

    if coverage_vs_hand is None:
        coverage_vs_hand = coverage_overall

    return {
        "coverage_overall":   coverage_overall,
        "coverage_vs_hand":   coverage_vs_hand,
        "coverage_recent_10": coverage_recent_10,
        "games_total":        overall_games,
        "games_vs_hand":      games_vs_hand,
        "games_recent":       recent_games,
        "pitcher_hand":       pitcher_hand,
        "batter_hand":        batter_hand,
    }


def _pitcher_coverage(
    player_id: int,
    prop_type: str,
    line: float,
    season: int,
    direction: str = "over",
) -> dict | None:
    """Calculate overall and recent-10 coverage for a pitcher prop."""
    if prop_type not in PITCHER_PROP_STAT_MAP:
        print(f"  [coverage] Unknown pitcher prop_type '{prop_type}'.")
        return None

    game_log = get_pitcher_game_log(player_id, season)

    if prop_type == "inningsPitched":
        overall_covered, overall_games = _count_ip_coverage(game_log, line, direction)
        recent_log = game_log[-10:]
        recent_covered, recent_games = _count_ip_coverage(recent_log, line, direction)
    else:
        stat_field = PITCHER_PROP_STAT_MAP[prop_type]
        overall_covered, overall_games = _count_coverage(game_log, stat_field, line, direction)
        recent_log = game_log[-10:]
        recent_covered, recent_games = _count_coverage(recent_log, stat_field, line, direction)

    if overall_games < get_season_minimum_pitcher(overall_games):
        return None

    return {
        "coverage_overall":  round(100.0 * overall_covered / overall_games, 1),
        "coverage_vs_hand":  None,
        "coverage_recent_10": round(100.0 * recent_covered / recent_games, 1) if recent_games > 0 else None,
        "games_total":       overall_games,
        "games_vs_hand":     None,
        "games_recent":      recent_games,
        "pitcher_hand":      None,
        "batter_hand":       None,
    }

