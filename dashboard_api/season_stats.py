"""
dashboard_api/season_stats.py — BA/OBP/K%/BB% (batters) and era/k9/whip/W/L
(pitchers) for the dashboard's Batters/Pitchers tabs.

Reads from the reference schema first (mlb_player_season_batting_stats /
mlb_player_season_pitching_stats, populated by
scripts/backfill_reference_snapshots.py + scripts/daily_reference_refresh.py)
instead of making a live MLB Stats API call per player per request.

Those reference tables are QUALIFIED-PLAYERS-ONLY by design (~150 hitters,
~60 pitchers on a given day — see that script's module docstring). The
dashboard's Batters/Pitchers tabs are NOT restricted to qualified players
(any player with a prop leg today shows up, including part-timers and
September-callup types who haven't cleared the PA/IP threshold) — so a
DB-only version would silently go blank for exactly the players who are
least likely to already be well-known, which is a real regression, not a
neutral change. Falls back to the original live API call ONLY for players
not found in the reference table, so coverage is unchanged; only the common
case (qualified players, the majority of any day's props) skips the network
round-trip.
"""
import requests

from src.apis.mlb_stats import _get, _set, BASE_URL
from src.utils.db import get_conn

TTL_SEASON_STATS = 6 * 60 * 60  # 6 hours — matches the prior live-call TTL,
                                 # kept for the live-fallback path; DB reads
                                 # are cheap enough not to strictly need it,
                                 # but a consistent cache key scheme is kept.


def _db_batter_stats(player_id: int, season: int) -> dict | None:
    conn = get_conn()
    cur = conn.cursor()
    cur.execute(
        """
        SELECT at_bats, plate_appearances, strikeouts, walks, avg, obp
        FROM mlb_player_season_batting_stats
        WHERE player_id = %s AND season = %s
        ORDER BY as_of_date DESC
        LIMIT 1
        """,
        (player_id, season),
    )
    row = cur.fetchone()
    cur.close()
    conn.close()
    if not row:
        return None
    pa = float(row["plate_appearances"] or 0)
    so = float(row["strikeouts"] or 0)
    bb = float(row["walks"] or 0)
    return {
        "ba": round(float(row["avg"]), 3) if row["avg"] is not None else None,
        "obp": round(float(row["obp"]), 3) if row["obp"] is not None else None,
        "kPct": round((so / pa) * 100, 0) if pa > 0 else 0,
        "bbPct": round((bb / pa) * 100, 0) if pa > 0 else 0,
    }


def _db_pitcher_stats(player_id: int, season: int) -> dict | None:
    conn = get_conn()
    cur = conn.cursor()
    cur.execute(
        """
        SELECT era, whip, wins, losses, strikeouts, innings_pitched
        FROM mlb_player_season_pitching_stats
        WHERE player_id = %s AND season = %s
        ORDER BY as_of_date DESC
        LIMIT 1
        """,
        (player_id, season),
    )
    row = cur.fetchone()
    cur.close()
    conn.close()
    if not row:
        return None
    ip = float(row["innings_pitched"] or 0)
    so = float(row["strikeouts"] or 0)
    return {
        "era": round(float(row["era"]), 2) if row["era"] is not None else None,
        "k9": round((so / ip) * 9, 2) if ip > 0 else 0.0,
        "whip": round(float(row["whip"]), 2) if row["whip"] is not None else None,
        "wins": int(row["wins"] or 0),
        "losses": int(row["losses"] or 0),
    }


def get_batter_season_stats(player_id: int, season: int) -> dict | None:
    """Returns {"ba": float, "obp": float, "kPct": int, "bbPct": int} or None."""
    key = f"batter_season:{player_id}:{season}"
    cached = _get(key, TTL_SEASON_STATS)
    if cached is not None:
        return cached

    try:
        result = _db_batter_stats(player_id, season)
    except Exception as e:
        print(f"  [season_stats] _db_batter_stats({player_id}, {season}) error: {e}")
        result = None

    if result is not None:
        _set(key, result)
        return result

    # Not in the qualified-players reference table — fall back to a live call.
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
        print(f"  [season_stats] get_batter_season_stats({player_id}, {season}) live-fallback error: {e}")
        return None


def get_pitcher_season_stats(player_id: int, season: int) -> dict | None:
    """Returns {"era": float, "k9": float, "whip": float, "wins": int, "losses": int} or None."""
    key = f"pitcher_season:{player_id}:{season}"
    cached = _get(key, TTL_SEASON_STATS)
    if cached is not None:
        return cached

    try:
        result = _db_pitcher_stats(player_id, season)
    except Exception as e:
        print(f"  [season_stats] _db_pitcher_stats({player_id}, {season}) error: {e}")
        result = None

    if result is not None:
        _set(key, result)
        return result

    # Not in the qualified-players reference table — fall back to a live call.
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
        print(f"  [season_stats] get_pitcher_season_stats({player_id}, {season}) live-fallback error: {e}")
        return None
