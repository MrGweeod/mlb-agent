"""
team_stats.py — Team offensive stats and quality ranks (1–30).

Ranks all 30 MLB teams from 1 (best offense) to 30 (worst offense)
and caches results for 24 hours.
"""
from __future__ import annotations

import time

import statsapi

# ── In-memory cache ───────────────────────────────────────────────────────────

_ranks_cache: dict[int, dict] = {}        # season → ranks dict
_ranks_cache_ts: dict[int, float] = {}    # season → epoch timestamp
_CACHE_TTL = 86400                        # 24 hours


# ── Public API ────────────────────────────────────────────────────────────────

def get_team_offensive_stats(team_id: int, season: int) -> dict | None:
    """
    Return offensive stats for one team.

    Returns:
        {"k_pct": 25.8, "batting_avg": 0.230, "runs_per_game": 3.8} or None.
    """
    try:
        data = statsapi.get(
            "team_stats",
            {
                "teamId": team_id,
                "season": season,
                "stats": "season",
                "group": "hitting",
                "sportId": 1,
            },
        )
        splits = (
            data.get("stats", [{}])[0]
                .get("splits", [])
        )
        if not splits:
            return None
        s = splits[0].get("stat", {})

        at_bats     = float(s.get("atBats")      or 0)
        walks       = float(s.get("baseOnBalls") or 0)
        hbp         = float(s.get("hitByPitch")  or 0)
        sac_flies   = float(s.get("sacFlies")    or 0)
        ks          = float(s.get("strikeOuts")  or 0)
        hits        = float(s.get("hits")        or 0)
        runs        = float(s.get("runs")        or 0)
        games       = float(s.get("gamesPlayed") or 0)

        pa_denom = at_bats + walks + hbp + sac_flies
        k_pct    = (ks / pa_denom * 100) if pa_denom > 0 else 0.0
        ba       = (hits / at_bats) if at_bats > 0 else 0.0
        rpg      = (runs / games) if games > 0 else 0.0

        return {
            "k_pct":         round(k_pct, 2),
            "batting_avg":   round(ba, 3),
            "runs_per_game": round(rpg, 2),
        }
    except Exception as e:
        print(f"  [team_stats] get_team_offensive_stats({team_id}, {season}) error: {e}")
        return None


def get_team_offensive_ranks(season: int) -> dict:
    """
    Return offensive rank dict for all 30 teams.

    Ranks are 1 (best offense) to 30 (worst offense) for K%, BA, RPG.
    Results are cached for 24 hours.

    Returns:
        {team_id: {"k_pct_rank": int, "ba_rank": int, "rpg_rank": int}}
    """
    now = time.time()
    if season in _ranks_cache and (now - _ranks_cache_ts.get(season, 0)) < _CACHE_TTL:
        return _ranks_cache[season]

    print(f"  [team_stats] Fetching team offensive ranks for {season}...")
    try:
        data = statsapi.get("teams", {"sportId": 1, "season": season})
        teams = data.get("teams", [])
    except Exception as e:
        print(f"  [team_stats] Error fetching teams: {e}")
        _ranks_cache[season] = {}
        _ranks_cache_ts[season] = now
        return {}

    team_data: list[dict] = []
    for t in teams:
        tid = t.get("id")
        if not tid:
            continue
        stats = get_team_offensive_stats(tid, season)
        if stats is None:
            continue
        team_data.append({"id": tid, **stats})

    if not team_data:
        _ranks_cache[season] = {}
        _ranks_cache_ts[season] = now
        return {}

    # K%: lower is better offense → sort ascending, rank 1 = lowest K%
    k_sorted   = sorted(team_data, key=lambda x: x["k_pct"])
    # BA: higher is better → sort descending, rank 1 = highest BA
    ba_sorted  = sorted(team_data, key=lambda x: x["batting_avg"], reverse=True)
    # RPG: higher is better → sort descending, rank 1 = highest RPG
    rpg_sorted = sorted(team_data, key=lambda x: x["runs_per_game"], reverse=True)

    ranks: dict[int, dict] = {}
    for i, t in enumerate(k_sorted):
        ranks.setdefault(t["id"], {})["k_pct_rank"] = i + 1
    for i, t in enumerate(ba_sorted):
        ranks.setdefault(t["id"], {})["ba_rank"] = i + 1
    for i, t in enumerate(rpg_sorted):
        ranks.setdefault(t["id"], {})["rpg_rank"] = i + 1

    _ranks_cache[season] = ranks
    _ranks_cache_ts[season] = now
    print(f"  [team_stats] Ranked {len(ranks)} teams")
    return ranks
