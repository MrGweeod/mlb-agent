"""
pitcher_stats.py — Pitcher season stats and quality ranks (1–30).

Ranks all qualified starters (min 50 IP) from 1 (best) to 30 (worst)
and caches results for 24 hours to avoid hammering the MLB API.
"""
from __future__ import annotations

import datetime
import time

import statsapi

from src.utils.net import call_with_timeout

_STATSAPI_TIMEOUT = 15          # seconds per statsapi call
_RANKS_LOOP_DEADLINE = 90       # seconds — overall cap on the pitcher-ranks fetch loop

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
        data = call_with_timeout(
            statsapi.player_stat_data,
            pitcher_id, group="pitching", type="season", sportId=1,
            timeout=_STATSAPI_TIMEOUT,
            label=f"player_stat_data(pitcher={pitcher_id})",
        )
        if data is None:
            return None
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
    # Fetch all pitchers' season stats via the team roster approach
    # statsapi.get with season stats endpoint
    data = call_with_timeout(
        statsapi.get,
        "sports_players", {"season": season, "gameType": "R", "sportId": 1},
        timeout=_STATSAPI_TIMEOUT,
        label="statsapi.get(sports_players)",
    )
    if data is None:
        _ranks_cache[season] = {}
        _ranks_cache_ts[season] = now
        return {}
    players = data.get("people", [])

    pitcher_data: list[dict] = []
    loop_start = time.time()

    for p in players:
        if time.time() - loop_start > _RANKS_LOOP_DEADLINE:
            print(
                f"  [pitcher_stats] Ranks loop hit {_RANKS_LOOP_DEADLINE}s deadline "
                f"after {len(pitcher_data)}/{len(players)} pitchers — continuing with partial ranks",
                flush=True,
            )
            break

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
        raw = call_with_timeout(
            statsapi.player_stat_data,
            pid, group="pitching", type="season", sportId=1,
            timeout=_STATSAPI_TIMEOUT,
            label=f"player_stat_data(pitcher={pid})",
        )
        if raw is None:
            continue
        raw_s = (raw.get("stats") or [{}])[0].get("stats", {})
        ip = _parse_ip(raw_s.get("inningsPitched", "0"))
        starts = int(raw_s.get("gamesStarted") or 0)
        if starts < 3:
            continue
        ip_per_start = ip / starts if starts > 0 else 0
        if ip_per_start < 3.0:
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


def get_starter_ranks_for_today(
    today_starter_ids: list[int],
    season: int,
) -> dict[int, dict]:
    """
    Return ERA, K/9, and WHIP ranks computed only across today's confirmed
    starting pitchers.

    Ranks 1 (best) to N (worst), where N = number of starters with available
    stats today. Eliminates reliever contamination from the full-season pool.

    Data analysis (Jun 25, 2026) showed the full-season rank pool mixes
    starters and relievers, causing rank 161+ to behave anomalously.
    Restricting to today's starters produces a clean, meaningful rank signal.

    Args:
        today_starter_ids: List of MLB pitcher IDs starting tonight.
                           Built from pitcher_id_map in main.py.
        season: Current season year.

    Returns:
        {pitcher_id: {"era_rank": int, "k9_rank": int, "whip_rank": int}}
        Only contains pitchers with available season stats.
        Returns {} if today_starter_ids is empty or no stats available.
    """
    if not today_starter_ids:
        return {}

    pitcher_data: list[dict] = []
    for pid in today_starter_ids:
        stats = get_pitcher_stats(pid, season)
        if stats is not None:
            pitcher_data.append({"id": pid, **stats})

    if not pitcher_data:
        print(f"  [pitcher_stats] get_starter_ranks_for_today: no stats for {len(today_starter_ids)} starter(s)")
        return {}

    # Rank ERA: lower is better → rank 1 = lowest ERA
    era_sorted  = sorted(pitcher_data, key=lambda x: x["era"])
    # Rank K/9: higher is better → rank 1 = highest K/9
    k9_sorted   = sorted(pitcher_data, key=lambda x: x["k9"], reverse=True)
    # Rank WHIP: lower is better → rank 1 = lowest WHIP
    whip_sorted = sorted(pitcher_data, key=lambda x: x["whip"])

    ranks: dict[int, dict] = {}
    for i, p in enumerate(era_sorted):
        ranks.setdefault(p["id"], {})["era_rank"] = i + 1
    for i, p in enumerate(k9_sorted):
        ranks.setdefault(p["id"], {})["k9_rank"] = i + 1
    for i, p in enumerate(whip_sorted):
        ranks.setdefault(p["id"], {})["whip_rank"] = i + 1

    print(
        f"  [pitcher_stats] Today's starter ranks: {len(ranks)} pitchers | "
        f"ERA/K9/WHIP ranks 1–{len(ranks)}"
    )
    return ranks


def normalize_rank(rank: int, inverted: bool = False) -> float:
    """
    Convert a 1–30 rank to [-1.0, 1.0].

    rank=1 (best) → +1.0, rank=15 (avg) → 0.0, rank=30 (worst) → -1.0.
    If inverted=True, flip the scale.
    """
    score = 1.0 - (rank - 1) * (2.0 / 29.0)
    return -score if inverted else score
