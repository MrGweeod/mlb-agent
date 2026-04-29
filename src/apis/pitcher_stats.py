"""
pitcher_stats.py — Pitcher season stats and quality ranks (1–30).

Ranks all qualified starters (min 50 IP) from 1 (best) to 30 (worst)
and caches results for 24 hours to avoid hammering the MLB API.
"""
from __future__ import annotations

import datetime
import time

import statsapi

# ── In-memory cache ───────────────────────────────────────────────────────────

_ranks_cache: dict[int, dict] = {}          # season → ranks dict
_ranks_cache_ts: dict[int, float] = {}      # season → epoch timestamp
_CACHE_TTL = 86400                          # 24 hours


# ── Helpers ───────────────────────────────────────────────────────────────────

def _parse_ip(raw) -> float:
    """Convert MLB API "6.1" format (6⅓ IP) to a float."""
    try:
        parts = str(raw).split(".")
        full   = int(parts[0])
        thirds = int(parts[1]) if len(parts) > 1 else 0
        return full + thirds / 3.0
    except (ValueError, TypeError, IndexError):
        return 0.0


# ── Public API ────────────────────────────────────────────────────────────────

def get_pitcher_stats(pitcher_id: int, season: int) -> dict | None:
    """
    Return ERA, K/9, and WHIP for a pitcher in the given season.

    Returns:
        {"era": 2.85, "k9": 11.2, "whip": 1.05} or None on failure.
    """
    try:
        data = statsapi.player_stat_data(
            pitcher_id, group="pitching", type="season", sportId=1
        )
        stats_list = data.get("stats", [])
        if not stats_list:
            return None
        s = stats_list[0].get("stats", {})

        ip = _parse_ip(s.get("inningsPitched", "0"))
        if ip == 0:
            return None

        era  = float(s.get("era")  or 0)
        whip = float(s.get("whip") or 0)
        ks   = float(s.get("strikeOuts") or 0)
        k9   = (ks / ip) * 9.0 if ip > 0 else 0.0

        return {"era": era, "k9": round(k9, 2), "whip": whip}
    except Exception as e:
        print(f"  [pitcher_stats] get_pitcher_stats({pitcher_id}, {season}) error: {e}")
        return None


def get_pitcher_ranks(season: int) -> dict:
    """
    Return rank dict for all qualified starters (min 50 IP) in the season.

    Ranks are 1 (best) to 30 (worst) for ERA, K/9, and WHIP.
    Results are cached for 24 hours.

    Returns:
        {pitcher_id: {"era_rank": int, "k9_rank": int, "whip_rank": int}}
    """
    now = time.time()
    if season in _ranks_cache and (now - _ranks_cache_ts.get(season, 0)) < _CACHE_TTL:
        return _ranks_cache[season]

    print(f"  [pitcher_stats] Fetching pitcher ranks for {season}...")
    try:
        # Fetch all pitchers' season stats via the team roster approach
        # statsapi.get with season stats endpoint
        data = statsapi.get(
            "sports_players",
            {"season": season, "gameType": "R", "sportId": 1},
        )
        players = data.get("people", [])
    except Exception as e:
        print(f"  [pitcher_stats] Error fetching players: {e}")
        _ranks_cache[season] = {}
        _ranks_cache_ts[season] = now
        return {}

    pitcher_data: list[dict] = []

    for p in players:
        pos = p.get("primaryPosition", {}).get("abbreviation", "")
        if pos not in {"P", "SP", "RP", "TWP"}:
            continue
        pid = p.get("id")
        if not pid:
            continue
        stats = get_pitcher_stats(pid, season)
        if stats is None:
            continue
        # Approximate IP from K9 — we need actual IP for the 50-IP filter.
        # Re-fetch raw stats for IP.
        try:
            raw = statsapi.player_stat_data(
                pid, group="pitching", type="season", sportId=1
            )
            raw_s = (raw.get("stats") or [{}])[0].get("stats", {})
            ip = _parse_ip(raw_s.get("inningsPitched", "0"))
        except Exception:
            continue
        if ip < 50:
            continue
        pitcher_data.append({"id": pid, **stats})

    if not pitcher_data:
        _ranks_cache[season] = {}
        _ranks_cache_ts[season] = now
        return {}

    # Rank ERA: lower is better → sort ascending, rank 1 = lowest ERA
    era_sorted = sorted(pitcher_data, key=lambda x: x["era"])
    k9_sorted  = sorted(pitcher_data, key=lambda x: x["k9"],  reverse=True)
    whip_sorted = sorted(pitcher_data, key=lambda x: x["whip"])

    ranks: dict[int, dict] = {}
    for i, p in enumerate(era_sorted):
        ranks.setdefault(p["id"], {})["era_rank"] = i + 1
    for i, p in enumerate(k9_sorted):
        ranks.setdefault(p["id"], {})["k9_rank"] = i + 1
    for i, p in enumerate(whip_sorted):
        ranks.setdefault(p["id"], {})["whip_rank"] = i + 1

    _ranks_cache[season] = ranks
    _ranks_cache_ts[season] = now
    print(f"  [pitcher_stats] Ranked {len(ranks)} qualified starters")
    return ranks


def normalize_rank(rank: int, inverted: bool = False) -> float:
    """
    Convert a 1–30 rank to [-1.0, 1.0].

    rank=1 (best) → +1.0, rank=15 (avg) → 0.0, rank=30 (worst) → -1.0.
    If inverted=True, flip the scale.
    """
    score = 1.0 - (rank - 1) * (2.0 / 29.0)
    return -score if inverted else score
