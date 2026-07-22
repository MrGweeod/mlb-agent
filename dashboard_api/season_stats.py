"""
dashboard_api/season_stats.py — BA/OBP/K%/BB% (batters) and era/k9/whip/W/L
(pitchers), sourced live from the MLB Stats API.

Confirmed nowhere else in the codebase — genuinely new. Deliberately kept out
of src/apis/mlb_stats.py so that file (used by the live production pipeline)
never has to be touched for this dashboard. Piggybacks on mlb_stats.py's
existing in-memory cache dict/helpers (_get/_set) and BASE_URL so we're not
running a second parallel cache — just adding new cache keys to the same one.
"""
import requests

from src.apis.mlb_stats import _get, _set, BASE_URL

TTL_SEASON_STATS = 6 * 60 * 60  # 6 hours — season rate stats shift every game
                                 # played, shorter than mlb_stats.py's 24h game
                                 # log / 7-day player_info TTLs.


def get_batter_season_stats(player_id: int, season: int) -> dict | None:
    """Returns {"ba": float, "obp": float, "kPct": int, "bbPct": int} or None."""
    key = f"batter_season:{player_id}:{season}"
    cached = _get(key, TTL_SEASON_STATS)
    if cached is not None:
        return cached
    try:
        r = requests.get(
            f"{BASE_URL}/people/{player_id}/stats",
            params={"stats": "season", "group": "hitting", "season": str(season)},
            timeout=15,
        )
        r.raise_for_status()
        splits = r.json().get("stats", [{}])[0].get("splits", [])
        if not splits:
            return None
        s = splits[0].get("stat", {})
        pa = float(s.get("plateAppearances") or 0)
        so = float(s.get("strikeOuts") or 0)
        bb = float(s.get("baseOnBalls") or 0)
        result = {
            "ba": round(float(s.get("avg") or 0), 3),
            "obp": round(float(s.get("obp") or 0), 3),
            "kPct": round((so / pa) * 100, 0) if pa > 0 else 0,
            "bbPct": round((bb / pa) * 100, 0) if pa > 0 else 0,
        }
        _set(key, result)
        return result
    except Exception as e:
        print(f"  [season_stats] get_batter_season_stats({player_id}, {season}) error: {e}")
        return None


def get_pitcher_season_stats(player_id: int, season: int) -> dict | None:
    """Returns {"era": float, "k9": float, "whip": float, "wins": int, "losses": int} or None."""
    key = f"pitcher_season:{player_id}:{season}"
    cached = _get(key, TTL_SEASON_STATS)
    if cached is not None:
        return cached
    try:
        r = requests.get(
            f"{BASE_URL}/people/{player_id}/stats",
            params={"stats": "season", "group": "pitching", "season": str(season)},
            timeout=15,
        )
        r.raise_for_status()
        splits = r.json().get("stats", [{}])[0].get("splits", [])
        if not splits:
            return None
        s = splits[0].get("stat", {})
        result = {
            "era": round(float(s.get("era") or 0), 2),
            "k9": round(float(s.get("strikeoutsPer9Inn") or 0), 2),
            "whip": round(float(s.get("whip") or 0), 2),
            "wins": int(s.get("wins") or 0),
            "losses": int(s.get("losses") or 0),
        }
        _set(key, result)
        return result
    except Exception as e:
        print(f"  [season_stats] get_pitcher_season_stats({player_id}, {season}) error: {e}")
        return None
