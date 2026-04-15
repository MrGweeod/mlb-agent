"""
matchup.py — Pitcher profile fetcher and opponent adjustment calculator.

Replaces the NBA agent's DEF_RATING-based matchup module with MLB pitcher stats:
  ERA, K/9, WHIP — sourced from MLB-StatsAPI cumulative season stats.

Caching strategy:
  - In-process dict (session-level): avoids redundant DB calls across one run.
  - pitcher_profiles DB table (24h TTL): avoids redundant MLB-StatsAPI calls.

Normalization:
  All three stats are normalised to [-1.0, +1.0] from the BATTER's perspective:
    positive → pitcher is weaker in that dimension → easier matchup for batter
    negative → pitcher is stronger → harder matchup

  ERA ranges:  2.0 (elite) → 6.0 (poor);  midpoint 4.0, scale 2.0
  K/9 ranges:  5.0 (low)   → 12.0 (high); midpoint 8.5, scale 3.5
  WHIP ranges: 0.90 (elite) → 1.60 (poor); midpoint 1.25, scale 0.35

Public interface:
    get_pitcher_matchup_profile(pitcher_id, season) -> dict | None
"""
from __future__ import annotations

import datetime
import requests

from src.utils.db import get_pitcher_profile, set_pitcher_profile

BASE_URL = "https://statsapi.mlb.com/api/v1"

# ── Normalisation constants ───────────────────────────────────────────────────

_ERA_MID   = 4.00
_ERA_SCALE = 2.00   # (ERA_POOR 6.0 - ERA_ELITE 2.0) / 2

_K9_MID    = 8.50
_K9_SCALE  = 3.50   # (K9_HIGH 12.0 - K9_LOW 5.0) / 2

_WHIP_MID   = 1.25
_WHIP_SCALE = 0.35  # (WHIP_POOR 1.60 - WHIP_ELITE 0.90) / 2

# In-process cache: {pitcher_id: dict}
_process_cache: dict[int, dict] = {}


# ── IP parsing ────────────────────────────────────────────────────────────────

def _parse_ip(ip_str: str | None) -> float:
    """
    Parse MLB-StatsAPI inningsPitched format to decimal innings.

    "145.1" = 145⅓ innings (the digit after '.' is outs, not tenths).
    Returns 0.0 for invalid/missing values.
    """
    if not ip_str:
        return 0.0
    try:
        parts = str(ip_str).split(".")
        full = int(parts[0])
        outs = int(parts[1]) if len(parts) > 1 and parts[1] else 0
        return full + outs / 3.0
    except (ValueError, IndexError):
        return 0.0


# ── Normalisation helpers ─────────────────────────────────────────────────────

def _clip(value: float, low: float = -1.0, high: float = 1.0) -> float:
    return max(low, min(high, value))


def _era_adj(era: float) -> float:
    """
    ERA → batter-perspective adjustment ∈ [-1.0, +1.0].

    Positive → pitcher has poor ERA → favorable matchup for batter.
    """
    return round(_clip((era - _ERA_MID) / _ERA_SCALE), 4)


def _k9_adj(k9: float) -> float:
    """
    K/9 → adjustment ∈ [-1.0, +1.0].

    Positive → pitcher has high K/9.
    Sign interpretation depends on prop type (see enrich_legs.py):
      batter hits prop:      use  -k9_adj  (high K/9 hurts hit coverage)
      batter strikeouts prop: use +k9_adj  (high K/9 helps batter K coverage)
    """
    return round(_clip((k9 - _K9_MID) / _K9_SCALE), 4)


def _whip_adj(whip: float) -> float:
    """
    WHIP → batter-perspective adjustment ∈ [-1.0, +1.0].

    Positive → pitcher has high WHIP → more baserunners → favorable for batter.
    """
    return round(_clip((whip - _WHIP_MID) / _WHIP_SCALE), 4)


def _percentile_rank(value: float, low: float, high: float, invert: bool = False) -> int:
    """
    Map value ∈ [low, high] to percentile rank 1–100.

    rank 1 = best performance, rank 100 = worst.
    invert=True when higher value = better (e.g. K/9: higher is better for the pitcher).
    """
    frac = (value - low) / (high - low) if high != low else 0.5
    frac = max(0.0, min(1.0, frac))
    if invert:
        frac = 1.0 - frac
    return max(1, min(100, int(frac * 99) + 1))


# ── MLB-StatsAPI fetch ────────────────────────────────────────────────────────

def _fetch_pitcher_season_stats(pitcher_id: int, season: int) -> dict | None:
    """
    Fetch cumulative pitching stats from /people/{id}/stats?stats=season.

    Returns dict with era, k9, whip, ip, games_started, or None on error.
    Requires at least 5.0 innings pitched to be considered valid (filters out
    openers/relievers who have been used very briefly).
    """
    try:
        r = requests.get(
            f"{BASE_URL}/people/{pitcher_id}/stats",
            params={"stats": "season", "group": "pitching", "season": str(season)},
            timeout=15,
        )
        r.raise_for_status()
        stats_list = r.json().get("stats", [])
        if not stats_list:
            return None
        splits = stats_list[0].get("splits", [])
        if not splits:
            return None
        stat = splits[0].get("stat", {})

        ip = _parse_ip(stat.get("inningsPitched"))
        if ip < 5.0:
            return None  # too few innings to be meaningful

        # Use API-computed era/whip when available; compute from raw otherwise
        era_raw = stat.get("era")
        whip_raw = stat.get("whip")

        try:
            era = float(era_raw)
        except (TypeError, ValueError):
            er = float(stat.get("earnedRuns") or 0)
            era = (er / ip * 9.0) if ip > 0 else 0.0

        try:
            whip = float(whip_raw)
        except (TypeError, ValueError):
            h = float(stat.get("hits") or 0)
            bb = float(stat.get("baseOnBalls") or 0)
            whip = (h + bb) / ip if ip > 0 else 0.0

        k = float(stat.get("strikeOuts") or 0)
        k9 = (k / ip * 9.0) if ip > 0 else 0.0

        return {
            "era":           round(era, 3),
            "k9":            round(k9, 3),
            "whip":          round(whip, 3),
            "ip":            round(ip, 1),
            "games_started": int(stat.get("gamesStarted") or 0),
        }
    except Exception as e:
        print(f"  [matchup] _fetch_pitcher_season_stats({pitcher_id}, {season}) error: {e}")
        return None


# ── Public API ────────────────────────────────────────────────────────────────

def get_pitcher_matchup_profile(
    pitcher_id: int,
    season: int | None = None,
) -> dict | None:
    """
    Return pitcher matchup profile with normalised batter-perspective adjustments.

    Cache hierarchy:
      1. In-process dict (session-level, always checked first)
      2. pitcher_profiles DB table (24h TTL)
      3. MLB-StatsAPI live fetch

    Args:
        pitcher_id: MLB person ID for the starting pitcher.
        season:     Season year; defaults to current calendar year.

    Returns:
        Dict with keys:
          era, k9, whip, ip, games_started
          era_rank, k9_rank, whip_rank  (1–100 percentile, 1 = best performance)
          era_adj, k9_adj, whip_adj     (each ∈ [-1.0, +1.0], batter-perspective)

        era_adj > 0 → pitcher has poor ERA → favorable for batter.
        k9_adj  > 0 → pitcher has high K/9 (sign depends on prop; see enrich_legs.py).
        whip_adj > 0 → pitcher has high WHIP → favorable for batter.

        Returns None when pitcher has < 5 IP (too small a sample), when the
        API returns no data, or on network error.
    """
    if season is None:
        season = datetime.datetime.now().year

    pid = int(pitcher_id)

    # 1. In-process cache
    if pid in _process_cache:
        return _process_cache[pid]

    # 2. DB cache (24h TTL)
    cached = get_pitcher_profile(str(pid))
    if cached is not None:
        profile = _build_profile_from_db(cached)
        _process_cache[pid] = profile
        return profile

    # 3. Live fetch from MLB-StatsAPI
    print(f"  [matchup] fetching pitcher stats for {pid} season {season}...")
    raw = _fetch_pitcher_season_stats(pid, season)
    if raw is None:
        return None

    era  = raw["era"]
    k9   = raw["k9"]
    whip = raw["whip"]

    era_rank  = _percentile_rank(era,  low=2.0, high=6.0, invert=False)  # lower ERA = better = rank 1
    k9_rank   = _percentile_rank(k9,   low=5.0, high=12.0, invert=True)  # higher K/9 = better = rank 1
    whip_rank = _percentile_rank(whip, low=0.90, high=1.60, invert=False)  # lower WHIP = better = rank 1

    # Persist to DB (hand=None; will be set separately if needed)
    try:
        set_pitcher_profile(
            pitcher_id=str(pid),
            team_id="",
            era=era,
            era_rank=era_rank,
            k9=k9,
            k9_rank=k9_rank,
            whip=whip,
            whip_rank=whip_rank,
            hand="",
        )
    except Exception as e:
        print(f"  [matchup] DB write failed for {pid}: {e}")

    profile = {
        "era":          era,
        "k9":           k9,
        "whip":         whip,
        "ip":           raw["ip"],
        "games_started": raw["games_started"],
        "era_rank":     era_rank,
        "k9_rank":      k9_rank,
        "whip_rank":    whip_rank,
        "era_adj":      _era_adj(era),
        "k9_adj":       _k9_adj(k9),
        "whip_adj":     _whip_adj(whip),
    }
    _process_cache[pid] = profile
    return profile


def _build_profile_from_db(row: dict) -> dict:
    """Build a full profile dict from a pitcher_profiles DB row."""
    era  = float(row["era"]  or 4.0)
    k9   = float(row["k9"]   or 8.5)
    whip = float(row["whip"] or 1.25)
    return {
        "era":          era,
        "k9":           k9,
        "whip":         whip,
        "ip":           None,
        "games_started": None,
        "era_rank":     int(row.get("era_rank") or 50),
        "k9_rank":      int(row.get("k9_rank") or 50),
        "whip_rank":    int(row.get("whip_rank") or 50),
        "era_adj":      _era_adj(era),
        "k9_adj":       _k9_adj(k9),
        "whip_adj":     _whip_adj(whip),
    }
