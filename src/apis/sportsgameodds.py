import time
import requests
import os
from dotenv import load_dotenv
from datetime import datetime, timezone, date as date_type

from src.utils.db import set_props_cache, log_sgo_request, get_sgo_daily_log

load_dotenv()

API_KEY = os.getenv('SPORTSGAMEODDS_API_KEY')
BASE_URL = 'https://api.sportsgameodds.com/v2'

# DraftKings MLB prop stat keys — matches SGO's statID naming convention.
# Batter hitting: hits, totalBases, rbi, homeRuns
# Batter counting: stolenBases, walks, runsScored
# Pitcher performance: strikeouts, inningsPitched, hitsAllowed, earnedRuns
PROP_STATS = [
    'hits',
    'totalBases',
    'rbi',
    'homeRuns',
    'stolenBases',
    'walks',
    'runsScored',
    'strikeouts',
    'inningsPitched',
    'hitsAllowed',
    'earnedRuns',
]

# Maps SGO statID strings (as they appear in the API's "statID" field and as
# odd-key prefixes) to internal pipeline stat keys.
# Live-validated 2026-04-17: SGO uses "batting_" prefix (not "hitting_").
# Add entries here if new SGO statIDs appear in production logs.
_SGO_STAT_ID_MAP: dict[str, str] = {
    # Batter hitting props — "batting_" prefix (live API format)
    "batting_hits":          "hits",
    "batting_totalBases":    "totalBases",
    "batting_RBI":           "rbi",         # SGO uses uppercase RBI
    "batting_rbi":           "rbi",         # lowercase variant guard
    "batting_homeRuns":      "homeRuns",
    "batting_stolenBases":   "stolenBases",
    "batting_basesOnBalls":  "walks",       # SGO field name for walks
    "batting_walks":         "walks",       # alternate SGO naming
    "batting_runs":          "runsScored",  # SGO field name for runs scored
    "batting_runsScored":    "runsScored",  # alternate SGO naming
    "batting_strikeouts":    "strikeouts",  # batter Ks
    # Pitcher performance props — "pitching_" prefix
    "pitching_strikeouts":     "strikeouts",
    "pitching_inningsPitched": "inningsPitched",
    "pitching_hitsAllowed":    "hitsAllowed",
    "pitching_hits":           "hitsAllowed",  # SGO alternate naming for hits allowed
    "pitching_earnedRuns":     "earnedRuns",
    "pitching_runs":           "earnedRuns",   # alternate SGO naming
    # Combination props — logged as unmapped, not used in pipeline
    # e.g. "batting_hits+runs+rbi"
}

# Maps internal pipeline stat name → the display label SGO appends to marketName.
# marketName format: "{Player Name} {Stat Label} Over/Under"
# Used to strip the stat label and recover a clean player name.
_STAT_NAME_SUFFIX: dict[str, str] = {
    "hits":           " Hits",
    "totalBases":     " Total Bases",
    "rbi":            " Runs Batted In",
    "homeRuns":       " Home Runs",
    "stolenBases":    " Stolen Bases",
    "walks":          " Walks",
    "runsScored":     " Runs",
    "strikeouts":     " Strikeouts",
    "hitsAllowed":    " Hits Allowed",
    "earnedRuns":     " Earned Runs",
    "inningsPitched": " Innings Pitched",
}


def _compute_ev(fair_line: float | None, standard_odds: str | None) -> float:
    """
    Compute EV per unit from SGO fair line and DraftKings book odds.

    fair_line is the SGO fairOverUnder — the line at which both sides
    have equal expected value. When book odds are worse than fair odds,
    EV is negative. When better, EV is positive.

    Returns 0.0 when either input is missing or unparseable.
    """
    try:
        if fair_line is None or standard_odds is None:
            return 0.0
        odds = int(str(standard_odds).replace("+", ""))
        if odds < 0:
            implied = abs(odds) / (abs(odds) + 100)
        else:
            implied = 100 / (odds + 100)
        return round(0.50 - implied, 4)
    except Exception:
        return 0.0


USAGE_WARN_PCT = 0.80  # warn at 80% of monthly quota


def check_sgo_usage() -> dict | None:
    """
    Fetch SGO account usage from /account/usage (does not count against limits).

    Prints a warning if monthly object usage exceeds USAGE_WARN_PCT (80%).
    Raises RuntimeError immediately if the monthly quota is exhausted so
    get_todays_games() skips the /events call and triggers the Odds API
    fallback without wasting a request that would 429 anyway.

    Returns:
        The 'rateLimits' dict from the usage response, or None if the
        request fails (treated as non-fatal — pipeline continues).
    """
    try:
        r = requests.get(f'{BASE_URL}/account/usage', params={'apiKey': API_KEY}, timeout=10)
        if r.status_code != 200:
            print(f"  [SGO] Usage check failed ({r.status_code}) — skipping quota check")
            return None
        data = r.json().get('data', {})
        limits = data.get('rateLimits', {})
        monthly = limits.get('per-month', {})
        used = monthly.get('current-entities', 0)
        cap = monthly.get('max-entities')

        if cap == 'unlimited' or cap is None:
            return limits

        # Always show today's local call log — useful even when quota is exhausted
        today = str(date_type.today())
        daily_log = get_sgo_daily_log(today)
        today_entities = sum(r['entities_consumed'] for r in daily_log)
        today_requests = len([r for r in daily_log if r['http_status'] == 200])
        today_errors = len([r for r in daily_log if r['http_status'] != 200])

        pct = used / cap
        if pct >= USAGE_WARN_PCT:
            print(
                f"  [SGO] WARNING: monthly quota {pct:.0%} used "
                f"({used}/{cap} objects) — approaching limit"
            )
        else:
            print(f"  [SGO] Monthly quota: {used}/{cap} objects used ({pct:.0%})")

        print(
            f"  [SGO] Today: {today_requests} successful request(s), "
            f"{today_entities} objects consumed"
            + (f", {today_errors} error(s)" if today_errors else "")
        )

        if pct >= 1.0:
            raise RuntimeError(
                f"SGO monthly object quota exhausted ({used}/{cap}). "
                f"Resets on next billing cycle."
            )

        return limits
    except RuntimeError:
        raise
    except Exception as e:
        print(f"  [SGO] Usage check error: {e} — skipping quota check")
        return None


def _sgo_get(path: str, params: dict) -> dict:
    """
    Make a GET request to the SportsGameOdds API with one 429 retry.

    Logs every request (success or failure) to mlb_sgo_request_log so quota
    consumption can be audited per-run and per-day. On a 429 response, waits
    60 seconds and retries once. If the retry also returns 429, raises
    RuntimeError so the caller fails loudly rather than silently returning
    empty data. Raises RuntimeError for any other non-200 status code as well.

    Args:
        path: API path relative to BASE_URL (e.g. '/events').
        params: Query parameters dict (API key should be included by caller).

    Returns:
        Parsed JSON response dict.
    """
    url = f'{BASE_URL}{path}'
    r = requests.get(url, params=params, timeout=15)

    if r.status_code == 429:
        log_sgo_request(path, 429, 0, notes='rate_limited')
        print(f"[SGO] Rate limited (429) — waiting 60s before retry...")
        time.sleep(60)
        r = requests.get(url, params=params, timeout=15)
        if r.status_code == 429:
            log_sgo_request(path, 429, 0, notes='rate_limited_retry')
            raise RuntimeError("SportsGameOdds API rate limit exceeded after retry. Try again later.")

    if r.status_code != 200:
        log_sgo_request(path, r.status_code, 0, notes=f'error: {r.text[:100]}')
        raise RuntimeError(f"SportsGameOdds API error {r.status_code}: {r.text[:200]}")

    data = r.json()
    entities = len(data.get('data', [])) if isinstance(data.get('data'), list) else 0
    log_sgo_request(path, 200, entities)
    return data


def get_todays_games(date=None):
    """
    Fetch all MLB games scheduled for today (or a given date) from SportsGameOdds.

    Runs a quota preflight via check_sgo_usage() before hitting /events.
    If the monthly object quota is exhausted, raises RuntimeError immediately
    so the caller can fall back to The Odds API without wasting a request.

    When no date is provided, uses the current UTC time as startsAfter so only
    games that haven't started yet are returned. When a date string is provided
    (YYYY-MM-DD), returns all games on that calendar day.

    Args:
        date: Optional date string in YYYY-MM-DD format. Defaults to today.

    Returns:
        List of game dicts from the SGO /events endpoint.
    """
    check_sgo_usage()  # raises RuntimeError if quota exhausted

    if date:
        starts_after = f'{date}T00:00:00Z'
        starts_before = f'{date}T23:59:59Z'
    else:
        now_utc = datetime.now(timezone.utc)
        starts_after = now_utc.strftime('%Y-%m-%dT%H:%M:%SZ')
        # Cap at 30 hours after today's UTC midnight — captures all games in the
        # current MLB day (latest first pitch ~02:00 UTC + ~3h runtime = ~05:00 UTC)
        # while excluding the next day's slate.
        today_midnight = now_utc.replace(hour=0, minute=0, second=0, microsecond=0)
        from datetime import timedelta
        cutoff = today_midnight + timedelta(hours=30)
        starts_before = cutoff.strftime('%Y-%m-%dT%H:%M:%SZ')

    params = {
        'apiKey': API_KEY,
        'leagueID': 'MLB',
        'startsAfter': starts_after,
        'startsBefore': starts_before,
        'includeAltLines': 'true',
        'limit': 20
    }
    return _sgo_get('/events', params).get('data', [])


def get_totals_props(game):
    """
    Fetch game total and team total markets from a SGO MLB game object.

    Returns a list of leg dicts covering:
      - Game total over/under  (runs-all-game-ou-over/under)
      - Home team total over/under (runs-home-game-ou-over/under)
      - Away team total over/under (runs-away-game-ou-over/under)

    Each leg has leg_type ("game_total" or "team_total"), team_id (None for
    game total), direction ("over"/"under"), and the standard all_lines list.
    """
    odds = game.get('odds', {})
    teams = game.get('teams', {})
    home_team_id = teams.get('home', {}).get('teamID', '')
    away_team_id = teams.get('away', {}).get('teamID', '')
    home_name = (teams.get('home', {}).get('names') or {}).get('short', home_team_id)
    away_name = (teams.get('away', {}).get('names') or {}).get('short', away_team_id)
    event_id = game.get('eventID', '')

    markets = [
        ('runs-all-game-ou-over',   'game_total', None,         'over',  f'{away_name}@{home_name} Total'),
        ('runs-all-game-ou-under',  'game_total', None,         'under', f'{away_name}@{home_name} Total'),
        ('runs-home-game-ou-over',  'team_total', home_team_id, 'over',  home_name),
        ('runs-home-game-ou-under', 'team_total', home_team_id, 'under', home_name),
        ('runs-away-game-ou-over',  'team_total', away_team_id, 'over',  away_name),
        ('runs-away-game-ou-under', 'team_total', away_team_id, 'under', away_name),
    ]

    props = []
    for odd_key, leg_type, team_id, direction, display_name in markets:
        mkt = odds.get(odd_key)
        if not mkt:
            continue
        dk = mkt.get('byBookmaker', {}).get('draftkings', {})
        if not dk:
            continue
        all_lines = []
        if dk.get('available') and dk.get('overUnder'):
            all_lines.append({
                'line': float(dk['overUnder']),
                'odds': dk.get('odds'),
                'available': True,
            })
        for alt in dk.get('altLines', []):
            if alt.get('available') and alt.get('overUnder'):
                all_lines.append({
                    'line': float(alt['overUnder']),
                    'odds': alt.get('odds'),
                    'available': True,
                })
        if not all_lines:
            continue
        all_lines.sort(key=lambda x: x['line'])
        props.append({
            'leg_type': leg_type,
            'team_id': team_id,
            'home_team_id': home_team_id,
            'away_team_id': away_team_id,
            'player_id': None,
            'player_name': display_name,
            'stat': 'game_total' if leg_type == 'game_total' else 'runs',
            'standard_line': dk.get('overUnder'),
            'standard_odds': dk.get('odds'),
            'all_lines': all_lines,
            'odd_id': f'{odd_key}_{event_id}',
            'direction': direction,
        })
    return props


def get_player_props(game, include_unders=True):
    """
    Parse DraftKings MLB player props from an SGO game object.

    Also caches the full alt-line ladder to mlb_player_props_cache under a
    team-pair key (e.g. 'NYY@BOS') so the Odds API fallback adapter can
    retrieve SGO alt lines when SGO is rate-limited later in the day.

    Covers all MLB prop categories: batter hitting (hits, totalBases, rbi,
    homeRuns), batter counting (stolenBases, walks, runsScored), and pitcher
    performance (strikeouts, inningsPitched, hitsAllowed, earnedRuns).

    Args:
        game: SGO game dict as returned by get_todays_games().
        include_unders: Whether to include under-direction props.

    Returns:
        List of prop dicts with 'stat', 'player_id', 'player_name',
        'all_lines', 'direction', 'fair_line', 'odd_id', etc.
    """
    odds = game.get('odds', {})
    props = []
    directions = [("over", "game-ou-over"), ("under", "game-ou-under")] if include_unders else [("over", "game-ou-over")]
    for stat in PROP_STATS:
        # Derive the API key prefixes for this internal stat from _SGO_STAT_ID_MAP.
        # e.g. 'hits' → ['batting_hits'], 'walks' → ['batting_basesOnBalls', 'batting_walks']
        api_prefixes = [ak for ak, iv in _SGO_STAT_ID_MAP.items() if iv == stat]
        if not api_prefixes:
            continue
        for direction, key_fragment in directions:
            matches = [
                v for k, v in odds.items()
                if any(k.startswith(p) for p in api_prefixes)
                and 'MLB' in k
                and key_fragment in k
            ]
            for prop in matches:
                dk = prop.get('byBookmaker', {}).get('draftkings', {})
                if not dk:
                    continue
                all_lines = []
                if dk.get('available') and dk.get('overUnder'):
                    all_lines.append({
                        'line': float(dk['overUnder']),
                        'odds': dk.get('odds'),
                        'available': True
                    })
                for alt in dk.get('altLines', []):
                    if alt.get('available') and alt.get('overUnder'):
                        all_lines.append({
                            'line': float(alt['overUnder']),
                            'odds': alt.get('odds'),
                            'available': True
                        })
                if not all_lines:
                    continue
                all_lines.sort(key=lambda x: x['line'])
                raw_stat_id = prop.get('statID', '')
                normalized_stat = _SGO_STAT_ID_MAP.get(raw_stat_id, raw_stat_id)
                fair_line  = prop.get('fairOverUnder')
                book_odds  = dk.get('odds')
                # Clean player name: strip " {Stat Label} Over/Under" from marketName.
                _raw_name = prop.get('marketName', '')
                if _raw_name.endswith(' Over/Under'):
                    _raw_name = _raw_name[:-len(' Over/Under')]
                _suffix = _STAT_NAME_SUFFIX.get(normalized_stat, '')
                if _suffix and _raw_name.endswith(_suffix):
                    _raw_name = _raw_name[:-len(_suffix)].strip()
                leg_dict = {
                    'stat': normalized_stat,
                    'player_id': prop.get('playerID'),
                    'player_name': _raw_name,
                    'standard_line': dk.get('overUnder'),
                    'standard_odds': book_odds,
                    'all_lines': all_lines,
                    'fair_line': fair_line,
                    'ev_per_unit': _compute_ev(fair_line, book_odds),
                    'odd_id': prop.get('oddID'),
                    'direction': direction,
                }
                if leg_dict['stat'] not in PROP_STATS:
                    print(f"  [SGO] unmapped statID: {raw_stat_id!r} → {leg_dict['stat']!r}")
                props.append(leg_dict)

    # Cache the full alt-line ladder under a team-pair key so the Odds API
    # fallback adapter can merge these alt lines into its standard-line props
    # if SGO becomes rate-limited later in the same day.
    teams = game.get('teams', {})
    away_abbr = (teams.get('away', {}).get('names') or {}).get('abbr', '')
    home_abbr = (teams.get('home', {}).get('names') or {}).get('abbr', '')
    if away_abbr and home_abbr:
        team_key = f"{away_abbr}@{home_abbr}"
        set_props_cache(str(date_type.today()), team_key, props)

    return props
