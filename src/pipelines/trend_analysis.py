"""
trend_analysis.py — Per-player, per-stat trend signals for MLB parlay eligibility.

MLB-specific differences from the NBA version:
  - Rolling windows: 10 and 20 games (NBA: 5/10/15).
  - PA stability replaces minutes stability.
    Proxy: atBats from game log. pa_pass = atBats_avg_10 >= 3.0.
  - No turnovers signal (no MLB equivalent).
  - Game log format: entry["stat"][field] (MLB-StatsAPI nested dict).
  - Game log order: OLDEST-FIRST (mlb_stats native — no reversal needed for chron).
    Streak calculation iterates NEWEST-FIRST (reversed game_log).
  - Momentum: avg over last 10 games > avg over last 20 games.
  - Prop stat names via PROP_STAT_MAP from coverage.py.

Public interface:
    get_trend_signal(player_id, stat, game_log, best_line, role) -> dict
"""
from __future__ import annotations

import numpy as np

from src.engine.coverage import PROP_STAT_MAP

# In-process cache keyed by (player_id, stat, best_line).
_process_cache: dict[tuple, dict] = {}

_SAFE_DEFAULT: dict = {
    "pa_avg_10":   0.0,
    "pa_pass":     False,
    "pa_slope":    0.0,
    "stat_slope":  0.0,
    "momentum":    False,
    "streak":      0,
    "recent_std":  0.0,
    "form_label":  "NEUTRAL",
    "trend_score": 0.0,
    "trend_pass":  False,
}


def _get_stat(entry: dict, field: str) -> float | None:
    """Extract a numeric stat from an MLB game log entry's 'stat' sub-dict."""
    val = entry.get("stat", {}).get(field)
    if val is None:
        return None
    try:
        return float(val)
    except (ValueError, TypeError):
        return None


def _slope(values: list[float]) -> float:
    """
    Compute the OLS slope of a series (oldest → newest).

    Returns 0.0 when fewer than 3 values are present or variance is zero.
    """
    if len(values) < 3:
        return 0.0
    y = np.array(values, dtype=float)
    if y.std() < 1e-6:
        return 0.0
    x = np.arange(len(values), dtype=float)
    return float(np.polyfit(x, y, 1)[0])


def _compute_streak(game_log: list[dict], stat_field: str, best_line: float) -> int:
    """
    Count consecutive games covering (positive) or missing (negative) best_line.

    game_log is OLDEST-FIRST — iterates reversed (most-recent-first).
    Returns positive integer for consecutive overs, negative for unders.
    A None stat value terminates the streak.
    """
    streak = 0
    for entry in reversed(game_log):
        v = _get_stat(entry, stat_field)
        if v is None:
            break
        if v >= best_line:
            if streak >= 0:
                streak += 1
            else:
                break
        else:
            if streak <= 0:
                streak -= 1
            else:
                break
    return streak


def get_trend_signal(
    player_id: str,
    stat: str,
    game_log: list[dict],
    best_line: float,
    role: str,
) -> dict:
    """
    Compute trend signals for a player/stat/line combination.

    Args:
        player_id:  Any string ID (used as cache key component only).
        stat:       Prop type key from PROP_STAT_MAP (e.g. "hits", "totalBases").
        game_log:   MLB game log in OLDEST-FIRST order (mlb_stats native).
        best_line:  The qualifying prop line from the coverage engine.
        role:       "anchor" for stricter trend_pass, "swing" for more lenient.

    Returns:
        Dict with all trend signal fields. Returns _SAFE_DEFAULT (trend_pass=False)
        when game_log has fewer than 5 entries or stat is not recognised.

    Scoring rules for trend_score:
      - PA slope   > +0.1  → +2
      - PA slope flat        →  0
      - PA slope   < -0.1  → -1
      - Stat slope > +0.1  → +2
      - Stat slope flat      →  0
      - Stat slope < -0.1  → -1
      - Momentum True        → +1

    Form label rules:
      HOT     : streak >= 4 AND momentum
      COLD    : streak <= -3 OR (stat_slope < 0 AND NOT momentum)
      NEUTRAL : everything else

    trend_pass rules:
      anchor : pa_pass AND stat_slope >= 0 AND momentum
      swing  : pa_pass AND (stat_slope >= 0 OR momentum)
    """
    key = (player_id, stat, best_line)
    if key in _process_cache:
        return _process_cache[key]

    stat_field = PROP_STAT_MAP.get(stat)
    if not stat_field or len(game_log) < 5:
        result = _SAFE_DEFAULT.copy()
        _process_cache[key] = result
        return result

    # game_log is oldest-first; no reversal needed for chronological calculations.
    chron = game_log

    # ── PA stability (proxy: atBats) ─────────────────────────────────────────
    pa_vals = [(_get_stat(g, "atBats") or 0.0) for g in chron]
    recent_10_pa = pa_vals[-10:] if len(pa_vals) >= 10 else pa_vals
    pa_avg_10 = float(np.mean(recent_10_pa)) if recent_10_pa else 0.0
    pa_pass = pa_avg_10 >= 3.0
    pa_slope = _slope(recent_10_pa)

    # ── Stat values ───────────────────────────────────────────────────────────
    stat_vals = [float(_get_stat(g, stat_field) or 0.0) for g in chron]
    recent_10_stat = stat_vals[-10:] if len(stat_vals) >= 10 else stat_vals
    recent_20_stat = stat_vals[-20:] if len(stat_vals) >= 20 else stat_vals

    stat_slope = _slope(recent_10_stat)
    avg_10 = float(np.mean(recent_10_stat)) if recent_10_stat else 0.0
    avg_20 = float(np.mean(recent_20_stat)) if recent_20_stat else avg_10
    momentum = avg_10 > avg_20
    recent_std = float(np.std(recent_10_stat)) if len(recent_10_stat) >= 2 else 0.0

    # ── Streak (most-recent-first) ────────────────────────────────────────────
    streak = _compute_streak(game_log, stat_field, best_line)

    # ── trend_score ───────────────────────────────────────────────────────────
    score = 0.0

    if pa_slope > 0.1:
        score += 2.0
    elif pa_slope < -0.1:
        score -= 1.0

    if stat_slope > 0.1:
        score += 2.0
    elif stat_slope < -0.1:
        score -= 1.0

    if momentum:
        score += 1.0

    # ── form_label ────────────────────────────────────────────────────────────
    if streak >= 4 and momentum:
        form_label = "HOT"
    elif streak <= -3 or (stat_slope < 0 and not momentum):
        form_label = "COLD"
    else:
        form_label = "NEUTRAL"

    # ── trend_pass ────────────────────────────────────────────────────────────
    if role == "anchor":
        trend_pass = bool(pa_pass and stat_slope >= 0 and momentum)
    else:  # swing
        trend_pass = bool(pa_pass and (stat_slope >= 0 or momentum))

    result = {
        "pa_avg_10":   round(pa_avg_10, 2),
        "pa_pass":     pa_pass,
        "pa_slope":    round(float(pa_slope), 4),
        "stat_slope":  round(float(stat_slope), 4),
        "momentum":    momentum,
        "streak":      streak,
        "recent_std":  round(float(recent_std), 4),
        "form_label":  form_label,
        "trend_score": round(float(score), 2),
        "trend_pass":  trend_pass,
    }
    _process_cache[key] = result
    return result
