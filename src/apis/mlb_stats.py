"""
mlb_stats.py — MLB-StatsAPI wrapper for the MLB Parlay Agent.

Replaces nba_stats.py / nba_api. All network calls go to statsapi.mlb.com
(no API key required). In-memory dict cache with per-function TTLs avoids
redundant network calls within a single pipeline run and between runs on the
same day.

Cache TTLs:
  schedule     30 min    — slate is fixed once announced, but status updates live
  game_log     24 hr     — today's games don't appear until tomorrow anyway
  pitcher_hand 7 days    — handedness never changes
  box_score    status-aware — re-fetched until status == 'Final', then frozen
  lineup       30 min    — updates as game progresses and lineup confirmed
  transactions 1 hr      — IL moves post throughout the day
  player_info  7 days    — position, bats, team — stable

Each cache entry: _cache[key] = {"data": ..., "ts": float, "final": bool}
"final" is only used by box_score to freeze resolved games indefinitely.
"""
import time
import requests
import statsapi

BASE_URL = "https://statsapi.mlb.com/api/v1"

# ── In-memory cache ──────────────────────────────────────────────────────────

_cache: dict[str, dict] = {}

TTL_SCHEDULE     = 30 * 60       # 30 minutes
TTL_GAME_LOG     = 24 * 60 * 60  # 24 hours
TTL_PITCHER_HAND = 7 * 24 * 60 * 60  # 7 days
TTL_LINEUP       = 30 * 60       # 30 minutes
TTL_TRANSACTIONS = 60 * 60       # 1 hour
TTL_PLAYER_INFO  = 7 * 24 * 60 * 60  # 7 days


def _get(key: str, ttl: float) -> object | None:
    """Return cached value if present and fresher than ttl seconds, else None."""
    entry = _cache.get(key)
    if not entry:
        return None
    # Frozen entries (resolved box scores) never expire
    if entry.get("final"):
        return entry["data"]
    if time.time() - entry["ts"] < ttl:
        return entry["data"]
    return None


def _set(key: str, data: object, final: bool = False):
    """Write a value into the in-memory cache."""
    _cache[key] = {"data": data, "ts": time.time(), "final": final}


# ── 1. get_schedule ──────────────────────────────────────────────────────────

def get_schedule(date: str) -> list[dict]:
    """
    Return today's MLB slate as a list of game dicts.

    Args:
        date: ISO date string 'YYYY-MM-DD'.

    Returns:
        List of game dicts. Each dict has at minimum:
          game_id, game_datetime, game_date, status,
          away_name, home_name, away_id, home_id,
          home_probable_pitcher, away_probable_pitcher,
          away_score, home_score, venue_name, summary.
        Returns [] on network error.
    """
    key = f"schedule:{date}"
    cached = _get(key, TTL_SCHEDULE)
    if cached is not None:
        return cached

    try:
        games = statsapi.schedule(date=date, sportId=1)
        # Filter to regular season and postseason games only
        games = [g for g in games if g.get("game_type") in ("R", "F", "D", "L", "W", "C")]
        _set(key, games)
        return games
    except Exception as e:
        print(f"  [mlb_stats] get_schedule({date}) error: {e}")
        return []


# ── 2. get_batter_game_log ───────────────────────────────────────────────────

def get_batter_game_log(player_id: int, season: int) -> list[dict]:
    """
    Return a batter's game-by-game hitting log for the given season.

    Args:
        player_id: MLB person ID (integer).
        season: Season year (e.g. 2026).

    Returns:
        List of game split dicts, each containing:
          date (str), stat (dict with hits/totalBases/rbi/homeRuns/atBats/...),
          opponent (dict with id/name), isHome (bool), isWin (bool),
          game (dict with gamePk).
        Ordered oldest-first. Returns [] on error or no data.

    Cache TTL: 24 hours. Keyed by (player_id, season).
    """
    key = f"batter_log:{player_id}:{season}"
    cached = _get(key, TTL_GAME_LOG)
    if cached is not None:
        return cached

    try:
        r = requests.get(
            f"{BASE_URL}/people/{player_id}/stats",
            params={"stats": "gameLog", "group": "hitting", "season": str(season)},
            timeout=15,
        )
        r.raise_for_status()
        splits = r.json().get("stats", [{}])[0].get("splits", [])
        _set(key, splits)
        return splits
    except Exception as e:
        print(f"  [mlb_stats] get_batter_game_log({player_id}, {season}) error: {e}")
        return []


# ── 3. get_pitcher_game_log ──────────────────────────────────────────────────

def get_pitcher_game_log(player_id: int, season: int) -> list[dict]:
    """
    Return a pitcher's game-by-game pitching log for the given season.

    Args:
        player_id: MLB person ID (integer).
        season: Season year (e.g. 2026).

    Returns:
        List of game split dicts, each containing:
          date (str), stat (dict with strikeOuts/inningsPitched/hits/
          earnedRuns/baseOnBalls/homeRuns/era/...), opponent, isHome,
          isWin, game (dict with gamePk).
        Ordered oldest-first. Returns [] on error or no data.

    Cache TTL: 24 hours. Keyed by (player_id, season).
    """
    key = f"pitcher_log:{player_id}:{season}"
    cached = _get(key, TTL_GAME_LOG)
    if cached is not None:
        return cached

    try:
        r = requests.get(
            f"{BASE_URL}/people/{player_id}/stats",
            params={"stats": "gameLog", "group": "pitching", "season": str(season)},
            timeout=15,
        )
        r.raise_for_status()
        splits = r.json().get("stats", [{}])[0].get("splits", [])
        _set(key, splits)
        return splits
    except Exception as e:
        print(f"  [mlb_stats] get_pitcher_game_log({player_id}, {season}) error: {e}")
        return []


# ── 4. get_pitcher_hand ──────────────────────────────────────────────────────

def get_pitcher_hand(player_id: int) -> str | None:
    """
    Return a pitcher's throwing hand: 'L', 'R', or None if unavailable.

    Uses the pitchHand.code field from the person endpoint.

    Args:
        player_id: MLB person ID (integer).

    Returns:
        'L' or 'R', or None on error / missing data.

    Cache TTL: 7 days. Handedness never changes.
    """
    key = f"pitcher_hand:{player_id}"
    cached = _get(key, TTL_PITCHER_HAND)
    if cached is not None:
        return cached

    try:
        r = requests.get(f"{BASE_URL}/people/{player_id}", timeout=10)
        r.raise_for_status()
        people = r.json().get("people", [])
        if not people:
            return None
        hand = people[0].get("pitchHand", {}).get("code")
        if hand:
            _set(key, hand)
        return hand
    except Exception as e:
        print(f"  [mlb_stats] get_pitcher_hand({player_id}) error: {e}")
        return None


# ── 5. get_box_score ─────────────────────────────────────────────────────────

def get_box_score(game_pk: int) -> dict | None:
    """
    Return final box score stats for a completed game.

    Uses statsapi.boxscore_data() which returns a clean dict with:
      awayBatters, homeBatters, awayBattingTotals, homeBattingTotals,
      playerInfo, teamInfo, and per-player stats/seasonStats.

    Cache behaviour: re-fetched on every call until the game is in a
    terminal status (Final / Game Over / Completed Early). Once final,
    the result is frozen in cache indefinitely.

    Args:
        game_pk: MLB game primary key (integer).

    Returns:
        boxscore_data dict, or None on error.
    """
    key = f"box_score:{game_pk}"
    # Return frozen cache immediately if game already resolved
    entry = _cache.get(key)
    if entry and entry.get("final"):
        return entry["data"]

    try:
        # Check game status before pulling full boxscore
        game_feed = requests.get(
            f"{BASE_URL}.1/game/{game_pk}/feed/live",
            params={"fields": "gameData,status,abstractGameState,detailedState"},
            timeout=15,
        ).json()
        state = (
            game_feed.get("gameData", {})
            .get("status", {})
            .get("abstractGameState", "")
        )
        is_final = state in ("Final",)

        data = statsapi.boxscore_data(game_pk)
        _set(key, data, final=is_final)
        return data
    except Exception as e:
        print(f"  [mlb_stats] get_box_score({game_pk}) error: {e}")
        return None


# ── 6. get_lineup ────────────────────────────────────────────────────────────

def get_lineup(game_pk: int) -> dict:
    """
    Return confirmed starters and batting orders for a game.

    Polls the live game feed for the batting order. Once a lineup is
    posted on MLB.com, the battingOrder list is populated (player IDs).
    Also returns probable pitchers from gameData.probablePitchers.

    Args:
        game_pk: MLB game primary key (integer).

    Returns:
        Dict with keys:
          home_batting_order: list[int] — player IDs in lineup order (empty until confirmed)
          away_batting_order: list[int]
          home_pitcher: dict with id/fullName, or {}
          away_pitcher: dict with id/fullName, or {}
          status: str — game status (e.g. 'Preview', 'In Progress', 'Final')
          confirmed: bool — True when both batting orders are non-empty
        Returns empty result dict on error.

    Cache TTL: 30 minutes. Re-fetched frequently until confirmed=True.
    """
    key = f"lineup:{game_pk}"
    cached = _get(key, TTL_LINEUP)
    if cached is not None and cached.get("confirmed"):
        return cached  # frozen once both lineups are confirmed

    try:
        result = statsapi.get("game", params={"gamePk": game_pk})
        game_data = result.get("gameData", {})
        live_data = result.get("liveData", {})

        home_order = (
            live_data.get("boxscore", {})
            .get("teams", {})
            .get("home", {})
            .get("battingOrder", [])
        )
        away_order = (
            live_data.get("boxscore", {})
            .get("teams", {})
            .get("away", {})
            .get("battingOrder", [])
        )

        probable = game_data.get("probablePitchers", {})
        status = game_data.get("status", {}).get("detailedState", "")
        confirmed = bool(home_order and away_order)

        lineup = {
            "home_batting_order": home_order,
            "away_batting_order": away_order,
            "home_pitcher": probable.get("home", {}),
            "away_pitcher": probable.get("away", {}),
            "status": status,
            "confirmed": confirmed,
        }
        _set(key, lineup)
        return lineup
    except Exception as e:
        print(f"  [mlb_stats] get_lineup({game_pk}) error: {e}")
        return {
            "home_batting_order": [],
            "away_batting_order": [],
            "home_pitcher": {},
            "away_pitcher": {},
            "status": "unknown",
            "confirmed": False,
        }


# ── 7. get_transactions ──────────────────────────────────────────────────────

def get_transactions(date: str) -> list[dict]:
    """
    Return MLB Transaction Wire entries for a given date.

    Calls statsapi.mlb.com directly (statsapi library wrapper doesn't support
    the startDate+endDate form reliably). Filters to MLB-level (sport_id=1)
    active roster transactions only — minor league IL placements are excluded.

    IL-related transactions appear as typeCode='SC' (Status Change) with
    descriptions mentioning '10-day injured list' or '60-day injured list'.
    Reinstatements also appear as 'SC' with 'reinstated' in the description.
    Recalls from the minors are typeCode='CU'.

    Args:
        date: ISO date string 'YYYY-MM-DD'.

    Returns:
        List of transaction dicts, each with:
          id, person (id/fullName), toTeam, date, typeCode, typeDesc,
          description.
        Returns [] on error.

    Cache TTL: 1 hour.
    """
    key = f"transactions:{date}"
    cached = _get(key, TTL_TRANSACTIONS)
    if cached is not None:
        return cached

    try:
        r = requests.get(
            f"{BASE_URL}/transactions",
            params={"startDate": date, "endDate": date},
            timeout=15,
        )
        r.raise_for_status()
        all_txns = r.json().get("transactions", [])

        # Keep only MLB-level transactions. The description always starts with
        # the team name for MLB transactions; minor league ones name the affiliate.
        # We filter by checking if toTeam.sport.id == 1 (MLB) when available,
        # otherwise keep all and let the caller filter by description.
        mlb_txns = [
            t for t in all_txns
            if t.get("toTeam", {}).get("sport", {}).get("id") in (1, None)
        ]

        _set(key, mlb_txns)
        return mlb_txns
    except Exception as e:
        print(f"  [mlb_stats] get_transactions({date}) error: {e}")
        return []


def is_il_placement(txn: dict) -> bool:
    """
    Return True if the transaction is a 10-day or 60-day IL placement.

    Args:
        txn: Transaction dict from get_transactions().
    """
    if txn.get("typeCode") != "SC":
        return False
    desc = txn.get("description", "").lower()
    return (
        "10-day injured list" in desc
        or "15-day injured list" in desc
        or "60-day injured list" in desc
    ) and "placed" in desc


def is_il_reinstatement(txn: dict) -> bool:
    """
    Return True if the transaction is a reinstatement from the IL.

    Args:
        txn: Transaction dict from get_transactions().
    """
    if txn.get("typeCode") != "SC":
        return False
    desc = txn.get("description", "").lower()
    return "reinstated" in desc and "injured list" in desc


# ── 8. get_player_info ───────────────────────────────────────────────────────

def get_player_info(player_id: int) -> dict | None:
    """
    Return basic player info: position, batting hand, team, and name.

    Args:
        player_id: MLB person ID (integer).

    Returns:
        Dict with keys:
          id, fullName, position (abbreviation), bats ('L'/'R'/'S'),
          throws ('L'/'R'), team_id, team_name.
        Returns None on error or player not found.

    Cache TTL: 7 days. Position and batting hand are stable across a season.
    """
    key = f"player_info:{player_id}"
    cached = _get(key, TTL_PLAYER_INFO)
    if cached is not None:
        return cached

    try:
        r = requests.get(
            f"{BASE_URL}/people/{player_id}",
            params={"hydrate": "currentTeam"},
            timeout=10,
        )
        r.raise_for_status()
        people = r.json().get("people", [])
        if not people:
            return None
        p = people[0]
        info = {
            "id":        p.get("id"),
            "fullName":  p.get("fullName"),
            "position":  p.get("primaryPosition", {}).get("abbreviation"),
            "bats":      p.get("batSide", {}).get("code"),
            "throws":    p.get("pitchHand", {}).get("code"),
            "team_id":   p.get("currentTeam", {}).get("id"),
            "team_name": p.get("currentTeam", {}).get("name"),
        }
        _set(key, info)
        return info
    except Exception as e:
        print(f"  [mlb_stats] get_player_info({player_id}) error: {e}")
        return None
