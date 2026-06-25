"""
main.py — MLB Parlay Agent full pipeline.

Pipeline:
  1. Transaction Wire  — IL placements and DFAs from today's transactions
  2. Schedule          — MLB slate + build pitcher and opponent maps
  3. Player Props      — fetch DK props from SportsGameOdds
  4. Coverage Gate     — historical hit rate per player/stat/line
  5. Injury Filter     — remove blocked players; LLM spot-check
  6. Enrichment        — attach pitcher matchup opponent_adjustment
  7. Trend Signals     — PA stability, stat slope, momentum, streak
  8. Parlay Builder    — hybrid anchor+swing construction

Called by:
  src/web/server.py scheduler (async, thread executor).
"""
from __future__ import annotations

from datetime import date, datetime, timedelta, timezone

import pytz
import statsapi

from src.apis.mlb_stats import (
    get_schedule,
    get_batter_game_log,
    get_pitcher_game_log,
    get_player_info,
    get_transactions,
    is_il_placement,
)
from src.apis.pitcher_stats import get_pitcher_ranks, get_starter_ranks_for_today
from src.apis.sportsgameodds import get_todays_games, get_player_props
from src.apis.team_stats import get_team_offensive_ranks
from src.engine.coverage import calculate_coverage, PROP_STAT_MAP
from src.engine.parlay_builder import build_parlays, _tier_params
from src.pipelines.enrich_legs import enrich_legs
from src.pipelines.trend_analysis import get_trend_signal
from src.utils.db import log_scored_legs, log_training_data_legs, save_parlay_recommendation, save_parlay_recommendations_v2, set_player_position

# ── Constants ─────────────────────────────────────────────────────────────────

# Single flat pool thresholds
POOL_MIN_COVERAGE = 65.0
POOL_MIN_ODDS     = -250
POOL_MAX_ODDS     = 150

# Transaction typeCodes that affect player availability.
# SC = Status Change (IL placements/reinstatements)
# DES = Designated for Assignment
# OU = Outright waivers
# CU = Unconditional release
_RELEVANT_TXNS = frozenset({"SC", "DES", "OU", "CU"})

# Position codes that identify a pitcher; these players' props are skipped
# because pitcher prop coverage is not yet implemented.
_PITCHER_POSITIONS = frozenset({"P", "SP", "RP", "TWP"})

# Hard odds boundaries — nothing outside this range is useful in parlays.
_FILTER_MIN_ODDS = -500
_FILTER_MAX_ODDS = +500

# ── Lineup Confirmation Layer ──────────────────────────────────────────────────
LINEUP_CHECK_OFFSET_MINUTES      = 45     # T-minus offset for primary check (Decision B)
LINEUP_CHECK_SECOND_PASS         = False  # set True to enable a late T-15 confirmation pass
LINEUP_CHECK_SECOND_PASS_OFFSET  = 15
LINEUP_DRAIN_INTERVAL_MINUTES    = 1      # how often the drain cron polls the DB
CLV_OFFSET_MINUTES               = 1      # snapshot closing odds at game_start_time − 1 minute

# Favorable batting-order slots per bet type.  PROPOSED DEFAULTS — flagged as tunable.
# Reasoning: hit-frequency props scale with plate appearances, which scale with slot.
# Slots 1-5 average ~4.2-4.8 PA/game; slots 7-9 average ~3.5-3.7.  These ranges are a
# starting hypothesis, NOT a validated fact — revisit after the backtest harness runs.
BATTING_ORDER_FAVORABLE: dict[tuple, range] = {
    ("hits",       "over"):  range(1, 6),   # slots 1-5
    ("strikeouts", "over"):  range(1, 7),   # slots 1-6 (more PA = more K chances)
    ("totalBases", "under"): range(1, 10),  # slot largely irrelevant for under; allow all
    ("hits",       "under"): range(1, 10),  # allow all; low-PA actually helps an under
}
# Default for any (stat, direction) not listed: allow all slots (range(1,10)).
# NOTE: validate these ranges against backfilled Jun 1-10 history before trusting in prod.

# In-process caches (reset each process run)
_player_id_cache: dict[str, int | None] = {}
_team_abbr_cache: dict[int, str] = {}   # team_id → abbreviation


# ── Pre-scoring prop filter ───────────────────────────────────────────────────

def _filter_useless_props(raw_props: list[dict]) -> list[dict]:
    """
    Remove props before coverage calculation that will never be useful in parlays.

    Filters out props with standard_odds outside [-500, +500].
    Prop-type filtering is handled by the ALLOWED_PROPS whitelist in _find_qualifying_legs().
    """
    filtered = []
    excluded_by_odds = 0

    for prop in raw_props:
        odds = prop.get("standard_odds")

        if odds is not None:
            try:
                odds_int = int(float(odds))
            except (TypeError, ValueError):
                excluded_by_odds += 1
                continue
            if odds_int < _FILTER_MIN_ODDS or odds_int > _FILTER_MAX_ODDS:
                excluded_by_odds += 1
                continue

        filtered.append(prop)

    print(f"[filter_props] {len(raw_props)} raw → {len(filtered)} usable")
    if excluded_by_odds:
        print(f"  Excluded {excluded_by_odds} by odds range (< {_FILTER_MIN_ODDS} or > +{_FILTER_MAX_ODDS})")

    return filtered


# ── Player / team ID resolution ───────────────────────────────────────────────

def _load_team_abbr_map() -> dict[int, str]:
    """
    Return {team_id: abbreviation} for all 30 MLB teams.

    Calls statsapi.teams() once per process and caches the result in
    _team_abbr_cache. Falls back to an empty dict on network error.
    """
    if _team_abbr_cache:
        return _team_abbr_cache
    try:
        for t in statsapi.get("teams", {"sportId": 1}).get("teams", []):
            _team_abbr_cache[t["id"]] = t["abbreviation"]
    except Exception as e:
        print(f"  [main] statsapi.get(teams) error: {e}")
    return _team_abbr_cache


def _lookup_player_id(name: str) -> int | None:
    """
    Resolve a display name to an MLB person ID via statsapi.lookup_player().

    Returns None when no match is found. Results are cached in _player_id_cache
    for the lifetime of the process.
    """
    if name in _player_id_cache:
        return _player_id_cache[name]
    try:
        matches = statsapi.lookup_player(name)
        pid = int(matches[0]["id"]) if matches else None
    except Exception:
        pid = None
    _player_id_cache[name] = pid
    return pid


# ── Step helpers ──────────────────────────────────────────────────────────────

def _get_blocked_players(today: str) -> set[str]:
    """
    Fetch the transaction wire and return lowercased names of players placed on IL.

    Pre-filters to _RELEVANT_TXNS before scanning for IL placements to reduce
    noise from the ~800 daily uniform-number and minor-league-assignment entries.
    """
    blocked: set[str] = set()
    try:
        all_txns = get_transactions(today)
        relevant = [t for t in all_txns if t.get("typeCode") in _RELEVANT_TXNS]
        print(f"  {len(all_txns)} raw transactions → {len(relevant)} MLB-relevant")
        for txn in relevant:
            if is_il_placement(txn):
                person = txn.get("person") or {}
                name = person.get("fullName", "")
                if name:
                    blocked.add(name.lower())
                    print(f"  IL placement: {name}")
    except Exception as e:
        print(f"  [transactions] error: {e}")
    return blocked


def _build_team_maps(
    schedule: list[dict],
    team_id_to_abbr: dict[int, str],
) -> tuple[dict[str, int], dict[str, int | None], dict[str, str]]:
    """
    Build per-team lookups from the MLB schedule.

    Args:
        schedule:       Output of get_schedule() for today.
        team_id_to_abbr: {team_id: abbreviation} from _load_team_abbr_map().

    Returns:
        team_abbr_to_game_pk  : {team_abbr: MLB gamePk}
        pitcher_id_map        : {batter_team_abbr: opposing_pitcher_id | None}
        opponent_map          : {team_abbr: opponent_team_abbr}

    Notes:
        home_probable_pitcher / away_probable_pitcher in the schedule are NAME
        STRINGS (e.g. "Gerrit Cole"), not IDs. This function resolves them to
        MLB person IDs via statsapi.lookup_player(). Unknown or TBD starters
        leave pitcher_id_map[abbr] = None, causing coverage.py to fall back
        to the overall (non-handedness-split) coverage rate.
    """
    team_abbr_to_game_pk: dict[str, int] = {}
    pitcher_id_map: dict[str, int | None] = {}
    opponent_map: dict[str, str] = {}

    for game in schedule:
        home_id  = game.get("home_id")
        away_id  = game.get("away_id")
        game_pk  = game.get("game_id")

        home_abbr = team_id_to_abbr.get(home_id, "")
        away_abbr = team_id_to_abbr.get(away_id, "")
        if not home_abbr or not away_abbr or not game_pk:
            continue

        team_abbr_to_game_pk[home_abbr] = game_pk
        team_abbr_to_game_pk[away_abbr] = game_pk
        opponent_map[home_abbr] = away_abbr
        opponent_map[away_abbr] = home_abbr

        home_pitcher_name = game.get("home_probable_pitcher", "") or ""
        away_pitcher_name = game.get("away_probable_pitcher", "") or ""

        home_pitcher_id = _lookup_player_id(home_pitcher_name) if home_pitcher_name else None
        away_pitcher_id = _lookup_player_id(away_pitcher_name) if away_pitcher_name else None

        # Home batters face the AWAY pitcher; away batters face the HOME pitcher
        pitcher_id_map[home_abbr] = away_pitcher_id
        pitcher_id_map[away_abbr] = home_pitcher_id

        print(
            f"  {away_abbr} @ {home_abbr} | "
            f"SP {away_abbr}: {away_pitcher_name or 'TBD'} (id={away_pitcher_id}) | "
            f"SP {home_abbr}: {home_pitcher_name or 'TBD'} (id={home_pitcher_id})"
        )

    return team_abbr_to_game_pk, pitcher_id_map, opponent_map


def _find_qualifying_legs(
    sgo_props: list[dict],
    team_id_to_abbr: dict[int, str],
    team_abbr_to_game_pk: dict[str, int],
    pitcher_id_map: dict[str, int | None],
    season: int,
) -> list[dict]:
    """
    Apply the coverage gate to all SGO props and return pool_legs.

    Allowed props: hits o/u 0.5, strikeouts o 0.5 (hitter only).

    For each prop:
      1. Reject if not in ALLOWED_PROPS whitelist.
      2. Resolve player name → MLB person ID via statsapi.lookup_player().
      3. Get player's current team from get_player_info(). Skip all pitchers.
      4. Confirm the player's team is on today's schedule.
      5. Call calculate_coverage().
      6. Gate 1: coverage_overall >= 65%. Gate 2: hits under >= 70%.
         Gate 3: odds in [-250, +150].
      7. All qualifying legs go into a single flat pool.

    Returns pool_qualifying ready for enrichment and parlay building.
    """
    pool_qualifying: list[dict] = []
    seen_odd_ids: set[str] = set()

    ALLOWED_PROPS = {
        ("hits",        "over",  0.5),
        ("hits",        "under", 0.5),
        ("strikeouts",  "over",  0.5),  # hitter K only — pitcher SO removed
        ("totalBases",  "under", 1.5),  # shadow validation only — never enters production parlays
    }

    for prop in sgo_props:
        stat = prop.get("stat", "")
        if stat not in PROP_STAT_MAP:
            continue  # pitcher-only stat (inningsPitched, hitsAllowed, earnedRuns)

        standard_line = prop.get("standard_line")
        standard_odds = prop.get("standard_odds")
        if standard_line is None or not standard_odds:
            continue
        line = float(standard_line)
        direction = prop.get("direction", "over")

        if (stat, direction, line) not in ALLOWED_PROPS:
            continue

        odd_id = prop.get("odd_id", "")
        if odd_id in seen_odd_ids:
            continue
        seen_odd_ids.add(odd_id)

        player_name = prop.get("player_name", "")
        if not player_name:
            continue

        # Resolve MLB person ID from display name
        mlb_player_id = _lookup_player_id(player_name)
        if not mlb_player_id:
            continue

        # Get player profile (position + team)
        info = get_player_info(mlb_player_id)
        if not info:
            continue

        position = info.get("position", "")
        if position in _PITCHER_POSITIONS:
            continue

        # Confirm player's team plays today
        team_id = info.get("team_id")
        team_abbr = team_id_to_abbr.get(team_id, "")
        game_pk = team_abbr_to_game_pk.get(team_abbr)
        if not team_abbr or not game_pk:
            continue  # team not playing today

        opposing_pitcher_id = pitcher_id_map.get(team_abbr) or None

        # Populate batter handedness cache BEFORE coverage runs so that
        # get_player_handedness() inside coverage.py finds it in mlb_player_positions.
        bats = info.get("bats")
        if bats:
            set_player_position(str(mlb_player_id), position, bats=bats)

        # Coverage calculation — all props route through calculate_coverage().
        # Pitcher position is passed so pitcher props use game-log coverage.
        coverage = calculate_coverage(
            player_id=mlb_player_id,
            prop_type=stat,
            line=line,
            opposing_pitcher_id=opposing_pitcher_id,
            season=season,
            position=position,
            direction=prop.get("direction", "over"),
        )
        if coverage is None:
            continue  # below seasonal minimum games threshold

        coverage_overall_raw = coverage.get("coverage_overall") or 0.0
        coverage_pct = coverage.get("coverage_vs_hand") or coverage_overall_raw

        # Gate 1: direction-aware coverage floor
        # For overs: standard 65% minimum
        # For unders: 40% minimum — a hitter going hitless 40%+ of games
        #   corresponds to roughly a .240 batting average, targeting genuine
        #   weak hitters. The 65% over gate is structurally impossible for
        #   unders (no healthy MLB hitter is hitless 65%+ of the time).
        if direction == "over" and coverage_overall_raw < 65.0:
            continue
        if direction == "under" and coverage_overall_raw < 40.0:
            continue

        # Gate 2: hits/under requires same 65% floor as overs.
        # Data analysis (Jun 25, 2026): 411 hits/under legs at 40% gate averaged
        # 48.8% coverage and 50.1% win rate vs 56.4% breakeven (−6.3pp edge).
        # The 14 hits/under legs selected into parlays averaged 66.0% coverage
        # and won at 57.1% — confirming the gate raise keeps the good legs.
        if stat == "hits" and direction == "under":
            if coverage_overall_raw < 65.0:
                continue

        # Single pool check: odds in [-250, +150]
        try:
            odds_val = float(standard_odds)
        except (ValueError, TypeError):
            continue
        if not (POOL_MIN_ODDS <= odds_val <= POOL_MAX_ODDS):
            continue

        leg_dict = {
            # Identifiers
            "player_id":           mlb_player_id,
            "player_name":         player_name,
            "team":                team_abbr,
            "position":            position,
            # Prop
            "stat":                stat,
            "best_line":           line,
            "best_odds":           standard_odds,
            "direction":           prop.get("direction", "over"),
            "odd_id":              odd_id,
            # Scoring signals
            "ev_per_unit":         prop.get("ev_per_unit", 0.0),
            "p_over":              round(coverage_pct / 100.0, 4),
            "coverage_pct":        coverage_pct,
            # New multi-signal coverage values
            "coverage_overall":    coverage.get("coverage_overall"),
            "coverage_vs_hand":    coverage.get("coverage_vs_hand"),
            "coverage_recent_10":  coverage.get("coverage_recent_10"),
            "games_total":         coverage.get("games_total"),
            "games_vs_hand":       coverage.get("games_vs_hand"),
            "games_recent":        coverage.get("games_recent"),
            "pitcher_hand":        coverage.get("pitcher_hand"),
            "batter_hand":         coverage.get("batter_hand") or bats,
            # Game context
            "game_pk":             game_pk,
            "opposing_pitcher_id": opposing_pitcher_id if opposing_pitcher_id else None,
            # Pool classification
            "leg_type":            "pool",
        }

        pool_qualifying.append(leg_dict)

    return pool_qualifying


def _attach_pitcher_rank_signals(
    legs: list[dict],
    pitcher_ranks: dict,
    team_offensive_ranks: dict,
    opponent_map: dict[str, str],
    abbr_to_team_id: dict[str, int],
    today_starter_ranks: dict | None = None,   # ← add this parameter
) -> None:
    """
    Attach pitcher quality and opponent offense rank fields to pitcher legs.

    For each pitcher leg, looks up:
      - pitcher_era_rank, pitcher_k9_rank, pitcher_whip_rank  (from pitcher_ranks)
      - opponent_k_pct_rank, opponent_ba_rank, opponent_rpg_rank (from team_offensive_ranks)
    and merges them into the leg dict in-place.

    Non-pitcher legs are left unchanged.
    """
    for leg in legs:
        position = leg.get("position", "")
        stat     = leg.get("stat", "")
        is_pitcher = (
            position in _PITCHER_POSITIONS
            or stat in {"inningsPitched", "hitsAllowed", "earnedRuns"}
        )
        if not is_pitcher:
            opp_pitcher_id = leg.get("opposing_pitcher_id") or leg.get("pitcher_id")
            if opp_pitcher_id:
                try:
                    pid_int = int(opp_pitcher_id)
                    opp_ranks = pitcher_ranks.get(pid_int, {})
                    today_ranks = (today_starter_ranks or {}).get(pid_int, {})

                    # ERA rank: prefer today's starter-only rank, fall back to full pool
                    leg["opp_pitcher_era_rank"] = (
                        today_ranks.get("era_rank") or opp_ranks.get("era_rank")
                    )
                    # K/9 rank: prefer today's starter-only rank, fall back to full pool
                    leg["opp_pitcher_k9_rank"] = (
                        today_ranks.get("k9_rank") or opp_ranks.get("k9_rank")
                    )
                    # WHIP rank: prefer today's starter-only rank, fall back to full pool
                    # Data analysis confirmed full-pool WHIP rank is contaminated by
                    # relievers — today's starter-only rank is the clean signal
                    leg["opp_pitcher_whip_rank"] = (
                        today_ranks.get("whip_rank") or opp_ranks.get("whip_rank")
                    )
                except (ValueError, TypeError):
                    pass
            continue

        # Pitcher quality ranks
        player_id = leg.get("player_id")
        p_ranks = pitcher_ranks.get(player_id, {})
        leg["pitcher_era_rank"]  = p_ranks.get("era_rank")
        leg["pitcher_k9_rank"]   = p_ranks.get("k9_rank")
        leg["pitcher_whip_rank"] = p_ranks.get("whip_rank")

        # Opponent offense ranks
        team_abbr    = leg.get("team", "")
        opp_abbr     = opponent_map.get(team_abbr, "")
        opp_team_id  = abbr_to_team_id.get(opp_abbr)
        opp_ranks    = team_offensive_ranks.get(opp_team_id, {}) if opp_team_id else {}
        leg["opponent_k_pct_rank"] = opp_ranks.get("k_pct_rank")
        leg["opponent_ba_rank"]    = opp_ranks.get("ba_rank")
        leg["opponent_rpg_rank"]   = opp_ranks.get("rpg_rank")


def _attach_trend_signals(legs: list[dict], season: int) -> None:
    """
    Compute trend signals for each leg and merge them into the leg dict in-place.

    Trend signals are sourced from the player's game log (cached 24h).
    """
    for leg in legs:
        player_id = leg.get("player_id")
        stat      = leg.get("stat", "")
        line      = leg.get("best_line")
        position  = leg.get("position", "")
        if not player_id or not stat or line is None:
            continue

        # Pitcher K legs have no batter game log — skip trend signal for pitchers
        is_pitcher_k = stat == "strikeouts" and position in _PITCHER_POSITIONS
        if is_pitcher_k:
            continue

        game_log = get_batter_game_log(int(player_id), season)
        if not game_log:
            continue

        signals = get_trend_signal(
            player_id=str(player_id),
            stat=stat,
            game_log=game_log,
            best_line=float(line),
        )
        leg.update(signals)


# ── Recommendation generation ─────────────────────────────────────────────────

def generate_recommendations(
    qualifying_legs: list[dict],
    max_recommendations: int = 5,
    run_date: str | None = None,
) -> list[dict]:
    """
    Generate up to max_recommendations ranked parlays for daily storage.

    Uses the same B&B search as build_hybrid_parlays (4–8 legs, +600–+1500),
    then adds win_probability and edge_pct metrics and applies a diversity
    filter so no single leg appears in more than 2 of the returned parlays.

    Args:
        qualifying_legs:    All scored legs from the pipeline (already have
                            composite_score set from Step 8).
        max_recommendations: Max parlays to return (default 5).
        run_date:           YYYY-MM-DD date string. When provided, filters out
                            players already used in today's parlays so each
                            player appears in at most 1 parlay per day.

    Returns:
        List of dicts: [{legs, combined_odds, win_probability, edge_pct}]
        ranked by edge_pct descending.
    """
    # Get up to 3× candidates to give the diversity filter room to work
    candidates = build_parlays(qualifying_legs, top_n=50)
    if not candidates:
        return []

    # Enrich each candidate with win_probability and edge_pct
    enriched = []
    for p in candidates:
        legs = p["legs"]

        # win_probability: product of (composite_score / 100) × 100 → percentage
        win_prob = 1.0
        for leg in legs:
            score = leg.get("composite_score") or 50.0
            win_prob *= score / 100.0
        win_prob_pct = round(win_prob * 100, 2)

        # combined_odds: parse "+1200" → 1200
        combined_odds = int(p["parlay_odds"].lstrip("+"))

        # edge_pct = win_probability_pct × (combined_odds / 100) - 100
        edge_pct = round(win_prob_pct * (combined_odds / 100) - 100, 2)

        enriched.append({
            "legs":            legs,
            "combined_odds":   combined_odds,
            "win_probability": win_prob_pct,
            "edge_pct":        edge_pct,
        })

    # Rank by edge_pct descending
    enriched.sort(key=lambda x: x["edge_pct"], reverse=True)

    # REMOVED: Within-recommendation diversity filter (May 2026).
    # Diagnostic data shows legs appearing 3+ times have 48.3% win rate (best),
    # while the 2-appearance cap forced use of 32.8% win-rate legs (worst).
    # ML composite scores determine selection; no artificial leg-appearance cap.
    return enriched[:max_recommendations]


# ── Public pipeline function ──────────────────────────────────────────────────

def run_pipeline(starts_after_override=None, source: str | None = None, skip_resolution: bool = False) -> list[dict]:
    """
    Execute the full MLB parlay pipeline and return parlays.

    Called by the web server scheduler in a background thread. All console
    output is visible in Railway logs.

    Args:
        starts_after_override: Optional UTC datetime. When provided, only SGO
            games starting after this time are fetched (used by /api/refresh to
            skip games starting within the next N hours and minimise API quota).

    Returns:
        parlays — list of hybrid parlay dicts; empty when no qualifying output
        is produced.
    """
    today  = str(date.today())
    season = date.today().year

    print(f"\nMLB Parlay Agent — {today}")
    print("=" * 50)

    if skip_resolution:
        print("\n[1/8] Skipping resolution (not a morning run)")

    # Load team ID → abbreviation map once (used across multiple steps)
    team_id_to_abbr = _load_team_abbr_map()

    # ── Step 1: Transaction Wire ──────────────────────────────────────────────
    print("\n[1/8] Fetching transaction wire (IL/DFA)...")
    blocked_names = _get_blocked_players(today)
    print(f"  {len(blocked_names)} player(s) blocked from today's transactions")

    # ── Step 2: Schedule + Pitcher / Opponent maps ────────────────────────────
    print("\n[2/8] Building schedule and pitcher maps...")
    schedule = get_schedule(today)
    if not schedule:
        print("  No games scheduled today. Exiting.")
        return [], ""

    print(f"  {len(schedule)} games on the slate")
    team_abbr_to_game_pk, pitcher_id_map, opponent_map = _build_team_maps(
        schedule, team_id_to_abbr
    )

    # Build today-only starter ranks — cleaner signal than full-season pool
    # (eliminates reliever contamination at rank extremes)
    today_starter_ids = [pid for pid in pitcher_id_map.values() if pid is not None]
    today_starter_ranks = get_starter_ranks_for_today(today_starter_ids, season)
    print(f"[main] Today's starter-only ranks built for {len(today_starter_ids)} pitcher(s)")

    # ── Step 3: Player Props (SportsGameOdds) ─────────────────────────────────
    print("\n[3/8] Fetching player props from SportsGameOdds...")
    try:
        sgo_games = get_todays_games(starts_after_override=starts_after_override)
    except RuntimeError as e:
        print(f"  SGO error: {e}")
        return [], ""

    all_sgo_props: list[dict] = []
    for sgo_game in sgo_games:
        all_sgo_props.extend(get_player_props(sgo_game))
    print(f"  {len(sgo_games)} SGO game(s) | {len(all_sgo_props)} raw props")

    if not all_sgo_props:
        print("  No props returned. Exiting.")
        return [], ""

    all_sgo_props = _filter_useless_props(all_sgo_props)

    # ── Step 4: Coverage Gate ─────────────────────────────────────────────────
    print(f"\n[4/8] Computing coverage (pool≥{POOL_MIN_COVERAGE}%, odds {POOL_MIN_ODDS} to +{POOL_MAX_ODDS})...")
    qualifying_legs = _find_qualifying_legs(
        all_sgo_props,
        team_id_to_abbr,
        team_abbr_to_game_pk,
        pitcher_id_map,
        season,
    )
    print(f"  {len(qualifying_legs)} qualifying leg(s) in pool")

    if not qualifying_legs:
        print("  No qualifying legs. Exiting.")
        return [], ""

    # ── Step 5: Injury Filter ─────────────────────────────────────────────────
    print("\n[5/8] Filtering blocked players...")

    # Injury filter is Transaction Wire only — get_injured_players() LLM check
    # removed; the wire at Step 1 is the authoritative IL source.

    # Build team_to_blocked BEFORE removing blocked legs so we preserve context
    name_to_team = {l["player_name"]: l["team"] for l in qualifying_legs if l.get("team")}
    team_to_blocked: dict[str, int] = {}
    for bname in blocked_names:
        # Try exact match first, then case-insensitive
        team = name_to_team.get(bname)
        if team is None:
            team = next(
                (name_to_team[n] for n in name_to_team if n.lower() == bname),
                None,
            )
        if team:
            team_to_blocked[team] = team_to_blocked.get(team, 0) + 1

    if team_to_blocked:
        print(f"  Teammate injury context: {team_to_blocked}")

    clean_legs = [
        l for l in qualifying_legs
        if l["player_name"].lower() not in blocked_names
    ]
    removed = len(qualifying_legs) - len(clean_legs)
    if removed:
        print(f"  Removed {removed} blocked leg(s)")
    qualifying_legs = clean_legs
    print(f"  {len(qualifying_legs)} legs remaining")

    # ── Step 5b: Lineup Consistency Filter ────────────────────────────────────
    print("\n[5b] Filtering low lineup-consistency legs...")
    try:
        from src.utils.lineup_consistency import calculate_lineup_consistency
        from src.utils.injury_context import check_expanded_role_due_to_injury
        _PITCHER_STATS = {"inningsPitched", "hitsAllowed", "earnedRuns"}
        _lc_kept, _lc_removed, _lc_errors = [], 0, 0
        _legs_before_lc = len(qualifying_legs)
        for _leg in qualifying_legs:
            _pid = _leg.get("player_id")
            _stat = _leg.get("stat", "")
            if not _pid or _stat in _PITCHER_STATS:
                _leg["lineup_consistency"] = 1.0
                _lc_kept.append(_leg)
                continue
            _lc = calculate_lineup_consistency(_pid, _stat, season)
            _leg["lineup_consistency"] = _lc
            if _lc is None:
                # API failed — include conservatively, don't penalise unknown players
                _lc_errors += 1
                _lc_kept.append(_leg)
            elif _lc >= 0.70:
                _lc_kept.append(_leg)
            else:
                _expanded = check_expanded_role_due_to_injury(_pid, _leg.get("team", ""), today)
                if _expanded.get("has_expanded_role"):
                    print(f"    Kept {_leg.get('player_name')} (lc={_lc:.2f}) — {_expanded.get('reason','expanded role')}")
                    _lc_kept.append(_leg)
                else:
                    _lc_removed += 1
        if _lc_removed:
            print(f"  Removed {_lc_removed} low-consistency leg(s)")
        if _lc_errors:
            print(f"  {_lc_errors} legs had API errors — included conservatively")
        # Safety circuit-breaker: if filter removed >90% of legs, something is wrong
        if _legs_before_lc > 0 and len(_lc_kept) < _legs_before_lc * 0.10:
            print(f"  WARNING: filter removed {_legs_before_lc - len(_lc_kept)}/{_legs_before_lc} legs (>90%).")
            print(f"  WARNING: This looks broken — disabling lineup consistency filter for this run.")
            # Restore original scores without filtering
            for _leg in qualifying_legs:
                _leg.setdefault("lineup_consistency", None)
        else:
            qualifying_legs = _lc_kept
        print(f"  {len(qualifying_legs)} legs remaining after lineup consistency filter")
    except Exception as _lc_err:
        print(f"  WARNING: Lineup consistency filter failed: {_lc_err}. Skipping.")

    if not qualifying_legs:
        print("  No legs after injury filter. Exiting.")
        return [], ""

    # ── Step 6: Opponent Enrichment (pitcher profiles) ────────────────────────
    print("\n[6/8] Enriching legs with pitcher matchup profiles...")
    qualifying_legs = enrich_legs(qualifying_legs, pitcher_id_map, opponent_map, season)

    # ── Filter: remove legs whose games have already started ─────────────────
    _et_tz = pytz.timezone("America/New_York")
    _now_et = datetime.now(_et_tz)
    _cutoff = _now_et + timedelta(minutes=15)
    upcoming_legs = []
    _started_count = 0
    _null_count = 0
    for _leg in qualifying_legs:
        _gst = _leg.get("game_start_time")
        if not _gst:
            _null_count += 1
            continue  # fail-closed: missing time = exclude
        try:
            _gt = datetime.fromisoformat(str(_gst))
            if _gt.tzinfo is None:
                # Legacy naive ET timestamp — localize before comparing
                _gt = _et_tz.localize(_gt)
            if _gt > _cutoff:
                upcoming_legs.append(_leg)
            else:
                _started_count += 1
        except Exception:
            _null_count += 1
            continue  # fail-closed: unparseable time = exclude
    print(
        f"  [filter_started] {len(qualifying_legs)} legs → "
        f"{len(upcoming_legs)} upcoming (filtered {_started_count} started, {_null_count} missing time)"
    )
    qualifying_legs = upcoming_legs

    # ── Step 7: Trend Signals ─────────────────────────────────────────────────
    print("\n[7/8] Computing trend signals...")
    _attach_trend_signals(qualifying_legs, season)
    form_counts = {}
    for l in qualifying_legs:
        label = l.get("form_label", "NEUTRAL")
        form_counts[label] = form_counts.get(label, 0) + 1
    print(
        f"  {len(qualifying_legs)} legs | "
        + " | ".join(f"{k}:{v}" for k, v in sorted(form_counts.items()))
    )

    # ── Pitcher quality + opponent offense ranks (pitcher legs only) ─────────
    print("\n  Fetching pitcher quality and opponent offense ranks...")
    pitcher_ranks       = get_pitcher_ranks(season)
    team_offensive_ranks = get_team_offensive_ranks(season)
    abbr_to_team_id = {v: k for k, v in team_id_to_abbr.items()}
    _attach_pitcher_rank_signals(
        qualifying_legs,
        pitcher_ranks,
        team_offensive_ranks,
        opponent_map,
        abbr_to_team_id,
        today_starter_ranks=today_starter_ranks,   # ← add this
    )

    # ── Simple Scoring (all qualifying legs, before logging and parlay builder) ──
    from src.engine.simple_scorer import score_legs
    score_legs(qualifying_legs)
    scored_count = sum(1 for l in qualifying_legs if l.get("composite_score") is not None)
    if scored_count:
        scores = [l["composite_score"] for l in qualifying_legs if l.get("composite_score") is not None]
        print(f"[main] Score distribution: min={min(scores):.1f}, avg={sum(scores)/len(scores):.1f}, max={max(scores):.1f}")

        by_stat = {}
        for leg in qualifying_legs:
            stat = leg["stat"]
            if stat not in by_stat:
                by_stat[stat] = []
            by_stat[stat].append(leg["composite_score"])
        for stat, stat_scores in by_stat.items():
            avg = sum(stat_scores) / len(stat_scores)
            print(f"[main]   {stat}: {len(stat_scores)} legs, avg score {avg:.1f}")

    orig_qualifying_legs = list(qualifying_legs)

    # ── Cross-run player cap: max 2 parlay appearances per player per day ────────
    # A player selected in any prior parlay today is tracked. Once they've
    # appeared in 2 parlays across all runs today, they are removed from the
    # pool for this run. Players with 0 or 1 prior appearances remain eligible.
    try:
        from src.utils.db import get_conn
        conn = get_conn()
        cur = conn.cursor()
        cur.execute("""
            SELECT l.player_name, COUNT(*) as appearances
            FROM mlb_parlay_legs_v2 l
            JOIN mlb_parlay_recommendations_v2 p ON p.id = l.parlay_id
            WHERE p.run_date = CURRENT_DATE
            GROUP BY l.player_name
            HAVING COUNT(*) >= 2
        """)
        capped_players = {row["player_name"] for row in cur.fetchall()}
        cur.close()
        conn.close()
        if capped_players:
            before = len(qualifying_legs)
            qualifying_legs = [l for l in qualifying_legs if l.get("player_name") not in capped_players]
            removed = before - len(qualifying_legs)
            print(f"[player_cap] {len(capped_players)} player(s) at 2-parlay cap — removed {removed} leg(s): {sorted(capped_players)}")
        else:
            print("[player_cap] No players at cap yet today")
        # Fallback: if cap leaves production pool too thin, restore full pool.
        # Must simulate TB exclusion here — TB/under legs are excluded from
        # production parlays in Step 8, so checking total qualifying_legs is
        # misleading (they looked healthy at 41 legs but 31 were TB/under).
        production_eligible = [
            l for l in qualifying_legs
            if l.get("stat") != "totalBases"
        ]
        production_overs = [l for l in production_eligible if l.get("direction") == "over"]
        if len(production_eligible) < 12 or len(production_overs) < 6:
            print(
                f"[player_cap] Production pool too thin after cap "
                f"({len(production_eligible)} non-TB legs, {len(production_overs)} overs) — restoring full pool"
            )
            qualifying_legs = [l for l in orig_qualifying_legs if l.get("stat") != "totalBases"]
    except Exception as _cap_err:
        print(f"[player_cap] Could not apply player cap (non-fatal): {_cap_err}")

    # ── Step 8: Build Hybrid Parlays ──────────────────────────────────────────
    tier_info  = _tier_params(len(schedule))
    tier_label = f"Tier {tier_info['tier']}" if tier_info else "Tier 4 (thin slate)"
    print(f"\n[8/8] Building hybrid parlays ({len(schedule)} games → {tier_label})...")

    # Exclude totalBases legs from production parlays — they are scored and
    # logged for shadow validation but must never enter live parlays.
    production_legs = [l for l in qualifying_legs if l.get("stat") != "totalBases"]
    tb_shadow_count = len(qualifying_legs) - len(production_legs)
    if tb_shadow_count:
        print(f"  [{tb_shadow_count} totalBases leg(s) held for shadow — excluded from parlays]")

    parlays = build_parlays(
        production_legs,
        top_n=5,
        num_games=len(schedule),
    )
    print(f"  Built {len(parlays)} parlay(s)")

    # Log ALL scored legs (including totalBases shadow legs) regardless of parlay outcome
    parlay_odd_ids = {leg["odd_id"] for p in parlays for leg in p.get("legs", [])}
    n_logged = log_scored_legs(qualifying_legs, today, parlay_odd_ids)
    if n_logged:
        print(f"  Logged {n_logged} scored leg(s) ({len(parlay_odd_ids)} in parlay)")

    # Prospective training data collection (all scored legs, outcome=NULL until resolver runs)
    n_training = log_training_data_legs(qualifying_legs, today)
    if n_training:
        print(f"  Logged {n_training} prop(s) to training data (prospective collection)")

    # Training data health check (runs after prospective logging so today's rows are included)
    try:
        from scripts.training_health_check import check_training_health
        health = check_training_health(days_back=7)
        if not health["healthy"]:
            print("\n  [health] TRAINING DATA ISSUES DETECTED:")
            for issue in health["issues"]:
                print(f"    {issue}")
        else:
            print(f"  [health] Training data OK")
        if health["hit_rate"] is not None:
            print(f"  [health] Hit rate (7d): {health['hit_rate']:.1f}%")
    except Exception as _hc_err:
        print(f"  [health] Health check failed: {_hc_err}")

    # ── Step 9: Generate and save recommendations ─────────────────────────────
    print("\n[9/9] Generating parlay recommendations...")
    # Build recommendations by enriching the already-built parlays.
    # NOTE: generate_recommendations() was calling build_hybrid_parlays() a
    # second time on the post-strikeout-filter qualifying_legs, which could
    # return 0 results if the filter shrank the pool below the minimum needed
    # to form valid 4-leg parlays in the +1000–+1400 odds window.
    recommendations = []
    for p in parlays:
        legs = p["legs"]
        combined_odds = int(p["parlay_odds"].lstrip("+"))
        win_prob = 1.0
        for leg in legs:
            score = leg.get("composite_score") or 50.0
            win_prob *= score / 100.0
        win_prob_pct = round(win_prob * 100, 2)
        edge_pct = round(win_prob_pct * (combined_odds / 100) - 100, 2)
        recommendations.append({
            "legs":            legs,
            "combined_odds":   combined_odds,
            "win_probability": win_prob_pct,
            "edge_pct":        edge_pct,
        })

    run_time = datetime.now(timezone.utc)
    for rank, rec in enumerate(recommendations, start=1):
        try:
            save_parlay_recommendation({
                "recommendation_date": date.today(),
                "pipeline_run_time":   run_time,
                "rank":                rank,
                "leg_odd_ids":         [leg["odd_id"] for leg in rec["legs"]],
                "combined_odds":       rec["combined_odds"],
                "win_probability":     rec["win_probability"],
                "edge_pct":            rec["edge_pct"],
            })
        except Exception as _rec_err:
            print(f"  [recommendations] failed to save rank {rank}: {_rec_err}")

    if recommendations:
        print(
            f"  Saved {len(recommendations)} recommendation(s) "
            f"(rank 1 edge: {recommendations[0]['edge_pct']:.1f}%)"
        )
    else:
        print("  No recommendations generated")

    # Dual-write to v2 normalized schema
    _prod_batch_id = ""
    if recommendations:
        print(f"  [debug] About to save {len(recommendations)} recommendation(s) to v2")
        try:
            if source:
                _source = source
            else:
                _et = pytz.timezone("America/New_York")
                _hour_et = datetime.now(_et).hour
                if _hour_et < 11:
                    _source = "auto_9am"
                elif _hour_et < 14:
                    _source = "auto_12pm"
                else:
                    _source = "auto_530pm"
            _prod_batch_id = save_parlay_recommendations_v2(recommendations, today, source=_source)
        except Exception as _v2_err:
            print(f"  [v2] dual-write failed (non-fatal): {_v2_err}")

    if not parlays:
        print("  No valid parlays found. Exiting.")
        return [], ""

    # Print parlay summary to stdout (visible in Railway logs)
    print()
    for i, p in enumerate(parlays, 1):
        ev_str = f" | avg EV {p['avg_ev']:+.1%}" if p.get("avg_ev") is not None else ""
        print(
            f"  Parlay {i}: {p['parlay_odds']} | {p['num_legs']} legs "
            f"| avg cov {p['avg_coverage']}%{ev_str}"
        )
        for leg in p["legs"]:
            ev_str = f" EV={leg['ev_per_unit']:+.1%}" if "ev_per_unit" in leg else ""
            dl = "u" if leg.get("direction") == "under" else "o"
            team_str = f" ({leg['team']})" if leg.get("team") else ""
            direction_tag = " [UNDER]" if leg.get("direction") == "under" else ""
            print(
                f"    • {leg['player_name']}{team_str} {leg['stat']} "
                f"{dl}{leg['best_line']}{direction_tag} ({leg['best_odds']}) "
                f"hist={leg['coverage_pct']}%{ev_str}"
            )

    # Shadow enriched pipeline — never blocks production
    try:
        from src.pipelines.run_enriched_pipeline import run_enriched_pipeline
        run_enriched_pipeline(qualifying_legs, production_batch_id=_prod_batch_id)
    except Exception as _enr_err:
        print(f"[ENRICHED PIPELINE] Failed — production unaffected: {_enr_err}")

    return parlays


def log_slate_start_times() -> None:
    """
    Read today's scored legs, group game_pks by start time, and persist lineup-check
    triggers to mlb_pending_lineup_checks via schedule_lineup_checks().

    Called at the end of run_morning_pipeline() after run_pipeline() has written
    today's scored legs (which carry game_start_time + game_pk).
    """
    from src.utils.db import get_conn
    from src.pipelines.lineup_scheduler import schedule_lineup_checks

    today_str = str(date.today())
    today_date = date.today()

    conn = get_conn()
    cur  = conn.cursor()
    cur.execute(
        """
        SELECT DISTINCT game_pk, game_start_time
        FROM mlb_scored_legs
        WHERE run_date = %s
          AND game_pk IS NOT NULL
        """,
        (today_str,),
    )
    rows = cur.fetchall()
    cur.close()
    conn.close()

    if not rows:
        print("[log_slate_start_times] No scored legs with game_pk found — skipping lineup scheduling.")
        return

    # Group game_pks by start time; fall back to statsapi schedule for missing times
    groups: dict[datetime, list[int]] = {}
    missing_pks: list[int] = []

    for row in rows:
        gst = row["game_start_time"]
        gpk = int(row["game_pk"])
        if not gst:
            missing_pks.append(gpk)
            continue
        try:
            dt = datetime.fromisoformat(str(gst))
            if dt.tzinfo is not None:
                dt = dt.astimezone(timezone.utc).replace(tzinfo=None)
            groups.setdefault(dt, []).append(gpk)
        except Exception:
            missing_pks.append(gpk)

    # Fall back to statsapi for any games missing start time
    if missing_pks:
        print(f"[log_slate_start_times] {len(missing_pks)} game(s) missing start time — fetching from statsapi")
        try:
            import statsapi as _sa
            sched = _sa.schedule(date=today_str.replace("-", "/"))
            pk_to_time: dict[int, datetime] = {}
            for g in sched:
                try:
                    dt_str = g.get("game_datetime", "")
                    dt = datetime.fromisoformat(dt_str.replace("Z", "+00:00"))
                    if dt.tzinfo is not None:
                        dt = dt.astimezone(timezone.utc).replace(tzinfo=None)
                    pk_to_time[int(g["game_id"])] = dt
                except Exception:
                    pass
            for gpk in missing_pks:
                if gpk in pk_to_time:
                    groups.setdefault(pk_to_time[gpk], []).append(gpk)
                else:
                    print(f"[log_slate_start_times] WARNING: game_pk={gpk} not found in statsapi schedule")
        except Exception as _err:
            print(f"[log_slate_start_times] statsapi fallback failed: {_err}")

    if not groups:
        print("[log_slate_start_times] No start-time groups built — skipping lineup scheduling.")
        return

    print(f"[log_slate_start_times] {len(groups)} start-time group(s) across {sum(len(v) for v in groups.values())} game(s)")

    n = schedule_lineup_checks(
        groups=groups,
        run_date=today_date,
        offset_minutes=LINEUP_CHECK_OFFSET_MINUTES,
        second_pass=LINEUP_CHECK_SECOND_PASS,
        second_pass_offset=LINEUP_CHECK_SECOND_PASS_OFFSET,
    )
    print(f"[log_slate_start_times] {n} lineup-check row(s) scheduled.")

    # Schedule CLV snapshot at game_start_time − CLV_OFFSET_MINUTES (T-1)
    try:
        from src.apis.clv_tracker import schedule_clv_checks
        n_clv = schedule_clv_checks(
            groups=groups,
            run_date=today_date,
            offset_minutes=CLV_OFFSET_MINUTES,
        )
        print(f"[log_slate_start_times] {n_clv} CLV-check row(s) scheduled.")
    except Exception as _clv_err:
        print(f"[log_slate_start_times] CLV scheduling failed (non-fatal): {_clv_err}")


def run_morning_pipeline(source: str | None = None) -> None:
    """
    Morning pipeline (9 AM ET):
      1. Resolve yesterday's outcomes and update training data.
      2. Run the full pipeline to fetch props, score legs, and build parlays for today.

    This ensures today's scored legs are in the DB before the 12 PM targeted refresh runs.

    Args:
        source: Optional source label for saved recommendations (e.g. 'manual').
                When None, run_pipeline auto-detects from ET hour.
    """
    today  = str(date.today())
    yesterday = str(date.today() - timedelta(days=1))

    print("\nMLB Parlay Agent — Morning Resolution Pipeline")
    print("=" * 50)
    print(f"  Resolving outcomes for {yesterday}")

    # Step 1: Transaction wire (for blocked-player context in later pipeline runs)
    print("\n[1/4] Fetching transaction wire (IL/DFA)...")
    blocked_names = _get_blocked_players(today)
    print(f"  {len(blocked_names)} player(s) blocked from today's transactions")

    # Step 2: Resolve yesterday's scored legs (mlb_scored_legs)
    print(f"\n[2/4] Resolving scored legs for {yesterday}...")
    try:
        from src.tracker.outcome_resolver import resolve_all_legs, resolve_training_data, resolve_enriched_parlays, resolve_all_enriched_legs
        leg_stats = resolve_all_legs(yesterday, verbose=True)
        print(f"  Scored legs: {leg_stats['won']} won, "
              f"{leg_stats['lost']} lost, {leg_stats['void']} void")
        enriched_stats = resolve_all_enriched_legs(yesterday, verbose=True)
        print(f"  Enriched legs: {enriched_stats['won']} won, "
              f"{enriched_stats['lost']} lost, {enriched_stats['void']} void")
        resolve_enriched_parlays(yesterday)
    except Exception as _leg_err:
        print(f"  WARNING: Scored-leg resolution failed: {_leg_err}")

    # Step 2b: Resolve yesterday's training data outcomes
    try:
        resolution_stats = resolve_training_data(yesterday, verbose=True)
        print(f"  Training data: {resolution_stats['hit']} hits, "
              f"{resolution_stats['miss']} misses, {resolution_stats['void']} voids")
    except Exception as _res_err:
        print(f"  WARNING: Training data resolution failed: {_res_err}")

    # Step 2c: Resolve yesterday's parlay recommendations
    try:
        from src.tracker.parlay_outcome_resolver import (
            resolve_parlay_recommendations,
            resolve_parlay_recommendations_v2,
        )
        parlay_stats = resolve_parlay_recommendations(yesterday, verbose=True)
        print(f"  Parlays: {parlay_stats['won']} won, {parlay_stats['lost']} lost, "
              f"{parlay_stats['void']} void, {parlay_stats['skipped']} skipped")
    except Exception as _par_err:
        print(f"  WARNING: Parlay resolution failed: {_par_err}")

    # Step 2d: Resolve yesterday's v2 parlay recommendations
    try:
        v2_stats = resolve_parlay_recommendations_v2(yesterday, verbose=True)
        print(f"  Parlays v2: {v2_stats['won']} won, {v2_stats['lost']} lost, "
              f"{v2_stats['void']} void, {v2_stats['skipped']} skipped")
    except Exception as _v2_par_err:
        print(f"  WARNING: V2 Parlay resolution failed (non-fatal): {_v2_par_err}")

    # Step 3: Training data health check
    print("\n[3/4] Training data health check...")
    try:
        from scripts.training_health_check import check_training_health
        health = check_training_health(days_back=7)
        if not health["healthy"]:
            print("  [health] TRAINING DATA ISSUES DETECTED:")
            for issue in health["issues"]:
                print(f"    {issue}")
        else:
            print("  [health] Training data OK")
        if health["hit_rate"] is not None:
            print(f"  [health] Hit rate (7d): {health['hit_rate']:.1f}%")
    except Exception as _hc_err:
        print(f"  [health] Health check skipped: {_hc_err}")

    # Step 4: Log summary
    print("\n[4/4] Resolution complete — fetching fresh props for today...")

    # Step 5: Full pipeline run for today (fetch props, score legs, build parlays)
    run_pipeline(source=source)

    # Step 6: Schedule lineup checks for today's games (event-driven layer)
    try:
        log_slate_start_times()
    except Exception as _lss_err:
        print(f"  WARNING: lineup scheduling failed (non-fatal): {_lss_err}")


def run_targeted_pipeline(buffer_minutes: int = 15, source: str = "auto") -> None:
    """
    DEPRECATED: Use run_pipeline(skip_resolution=True) instead.

    This function reuses stale database legs and only updates odds.
    The new approach fetches fresh props every time for better reliability.

    Kept for reference only - not used in production.

    Midday/evening targeted refresh — fetches fresh SGO odds for eligible players.

    Steps:
      1. IL check (transaction wire)
      2. Load today's scored legs from DB
      3. Filter composite_score >= MIN_COVERAGE_PCT (55)
      4. Remove IL-blocked players
      5. Remove started/imminent games (cutoff = now + buffer_minutes)
      6. Fetch fresh SGO odds for eligible players
      7. Check confirmed lineups; remove scratched players
      8. Re-run lineup consistency filter
      9. Rebuild parlay recommendations

    SGO objects consumed: ~12-16 (one /events call for the day's slate).
    """
    from src.utils.db import get_scored_legs, save_parlay_recommendation
    from src.utils.lineup_consistency import calculate_lineup_consistency
    from src.utils.injury_context import check_expanded_role_due_to_injury
    from src.apis.sportsgameodds import fetch_props_for_players
    import statsapi as _statsapi

    today  = str(date.today())
    season = date.today().year
    et_tz  = pytz.timezone("America/New_York")
    now_et = datetime.now(et_tz)
    cutoff = now_et + timedelta(minutes=buffer_minutes)

    _PITCHER_STATS = {"inningsPitched", "hitsAllowed", "earnedRuns"}

    print("\nMLB Parlay Agent — Targeted Refresh Pipeline")
    print("=" * 50)
    print(f"  Date: {today}  |  Buffer: {buffer_minutes} min  |  Cutoff: {cutoff.strftime('%H:%M ET')}")

    # ── Step 1: IL check ─────────────────────────────────────────────────────
    print("\n[1/8] Fetching transaction wire (IL/DFA)...")
    blocked_names = _get_blocked_players(today)
    print(f"  {len(blocked_names)} player(s) blocked from today's transactions")

    # ── Step 2: Load today's scored legs from DB ──────────────────────────────
    print("\n[2/8] Loading today's scored legs from DB...")
    all_legs = get_scored_legs(today)
    print(f"  {len(all_legs)} total legs in DB for {today}")

    if not all_legs:
        print("  No legs in DB. Exiting targeted pipeline.")
        return

    # Debug: show pitcher field coverage on loaded legs
    _with_pitcher_id   = sum(1 for l in all_legs if l.get("pitcher_id"))
    _with_pitcher_hand = sum(1 for l in all_legs if l.get("pitcher_hand"))
    _with_batter_hand  = sum(1 for l in all_legs if l.get("batter_hand"))
    print(
        f"  [pitcher_debug] pitcher_id={_with_pitcher_id}/{len(all_legs)} legs "
        f"| pitcher_hand={_with_pitcher_hand} | batter_hand={_with_batter_hand}"
    )

    # ── Step 3: Filter composite_score >= SWING_MIN_COVERAGE (55) ───────────
    eligible = [l for l in all_legs if (l.get("composite_score") or 0) >= POOL_MIN_COVERAGE]
    print(f"  {len(eligible)} legs with composite_score >= {POOL_MIN_COVERAGE}")

    if not eligible:
        print("  No eligible legs. Exiting targeted pipeline.")
        return

    # ── Step 4: Remove IL-blocked players ────────────────────────────────────
    pre_il = len(eligible)
    eligible = [l for l in eligible if l.get("player_name", "").lower() not in blocked_names]
    if pre_il - len(eligible):
        print(f"  Removed {pre_il - len(eligible)} IL-blocked leg(s)")

    # ── Step 5: Remove started/imminent games ────────────────────────────────
    upcoming = []
    started_count = 0
    null_count = 0
    for leg in eligible:
        gst = leg.get("game_start_time")
        if not gst:
            null_count += 1
            continue  # fail-closed: missing time = exclude
        try:
            gt = datetime.fromisoformat(str(gst))
            if gt.tzinfo is None:
                # Legacy naive ET timestamp — localize before comparing
                gt = et_tz.localize(gt)
            if gt > cutoff:
                upcoming.append(leg)
            else:
                started_count += 1
        except Exception:
            null_count += 1
            continue  # fail-closed: unparseable time = exclude

    print(f"\n[3/8] Game-start filter: {len(eligible)} legs → {len(upcoming)} upcoming"
          + (f" (removed {started_count} started, {null_count} missing time)" if (started_count or null_count) else ""))

    if not upcoming:
        print("  No upcoming legs after game-start filter. Exiting.")
        return

    # ── Step 6: Fetch fresh SGO odds for eligible players ────────────────────
    print(f"\n[4/8] Fetching fresh SGO odds for {len(upcoming)} eligible legs...")
    player_ids   = list({leg.get("player_id")   for leg in upcoming if leg.get("player_id")})
    player_names = list({leg.get("player_name") for leg in upcoming if leg.get("player_name")})
    # Primary resolution source: IDs we already trust from the database.
    _db_name_to_id: dict[str, int] = {
        leg["player_name"].lower(): leg["player_id"]
        for leg in upcoming
        if leg.get("player_name") and leg.get("player_id")
    }
    print(f"  {len(player_ids)} unique player(s) | {len(_db_name_to_id)} name→ID entries in DB map")

    try:
        fresh_props = fetch_props_for_players(today, player_ids=player_ids, player_names=player_names)
        print(f"  Received {len(fresh_props)} prop(s) from SGO")
        fresh_props = _filter_useless_props(fresh_props)
        print(f"  {len(fresh_props)} prop(s) after filtering useless prop types")

        # ── Two-stage player ID resolution ───────────────────────────────────
        # Props may arrive with player_id=None when the SGO-side statsapi call
        # fails.  Resolve in order: DB mapping (fast) → statsapi (new players only).
        _statsapi_id_cache: dict[str, int | None] = {}
        _resolved_db = _resolved_api = _unresolved = 0
        for prop in fresh_props:
            if prop.get("player_id") is not None:
                continue
            name = prop.get("player_name", "")
            # Fast path — authoritative DB mapping
            db_id = _db_name_to_id.get(name.lower())
            if db_id is not None:
                prop["player_id"] = db_id
                _resolved_db += 1
                continue
            # Slow path — statsapi (only for genuinely new players not in DB)
            if name not in _statsapi_id_cache:
                try:
                    results = statsapi.lookup_player(name)
                    _statsapi_id_cache[name] = results[0]["id"] if results else None
                except Exception as _e:
                    _statsapi_id_cache[name] = None
                    print(f"  [ID:api] {name!r} → lookup error: {_e}")
            api_id = _statsapi_id_cache[name]
            prop["player_id"] = api_id
            if api_id is not None:
                _resolved_api += 1
            else:
                _unresolved += 1

        print(
            f"  ID resolution: {_resolved_db} via DB, "
            f"{_resolved_api} via statsapi"
            + (f", {_unresolved} unresolved" if _unresolved else "")
        )

        # Build lookup: (player_id, stat, direction) → {line → odds}
        prop_lookup: dict[tuple, dict[float, int | str]] = {}
        for prop in fresh_props:
            key = (prop.get("player_id"), prop.get("stat"), prop.get("direction", "over"))
            if key not in prop_lookup:
                prop_lookup[key] = {}
            for entry in prop.get("all_lines", []):
                ln = entry.get("line")
                od = entry.get("odds")
                if ln is not None and od is not None:
                    prop_lookup[key][float(ln)] = od

        updated_count = 0
        for leg in upcoming:
            key = (leg.get("player_id"), leg.get("stat"), leg.get("direction", "over"))
            line_map = prop_lookup.get(key, {})
            db_line = leg.get("line")
            if db_line is not None:
                fresh_odds = line_map.get(float(db_line))
                if fresh_odds is not None:
                    leg["odds"] = fresh_odds
                    updated_count += 1
        print(f"  Updated odds for {updated_count}/{len(upcoming)} leg(s)")
    except Exception as _sgo_err:
        print(f"  WARNING: SGO fetch failed ({_sgo_err}) — keeping 9 AM odds")

    # ── Step 7: Check confirmed lineups; remove scratched players ────────────
    print(f"\n[5/8] Checking confirmed lineups...")

    # Group by game_pk
    by_game: dict[int, list[dict]] = {}
    for leg in upcoming:
        gpk = leg.get("game_pk")
        if gpk:
            by_game.setdefault(gpk, []).append(leg)

    scratched_count = 0
    for game_pk, game_legs in by_game.items():
        try:
            boxscore = _statsapi.boxscore_data(game_pk)
            starters: set[int] = set()
            for side in ("away", "home"):
                team_data = boxscore.get(side, {})
                for pid_str in team_data.get("battingOrder", []):
                    try:
                        starters.add(int(pid_str))
                    except (ValueError, TypeError):
                        pass
            if not starters:
                # Batting order not yet available — lineups not announced, include all
                print(f"    [lineup] No batting order for game {game_pk} (lineups not yet announced) — including all")
                for leg in game_legs:
                    leg["lineup_status"] = "unknown"
                continue
            for leg in game_legs:
                stat = leg.get("stat", "")
                pid = leg.get("player_id")
                # Pitchers aren't in the batting order — skip lineup check for them
                if stat in _PITCHER_STATS or not pid:
                    leg["lineup_status"] = "confirmed"
                elif int(pid) in starters:
                    leg["lineup_status"] = "confirmed"
                else:
                    leg["lineup_status"] = "scratched"
                    scratched_count += 1
                    print(f"    SCRATCHED: {leg.get('player_name')} not in lineup for game {game_pk}")
        except Exception as _lu_err:
            print(f"    Lineup check failed for game {game_pk}: {_lu_err} — including conservatively")
            for leg in game_legs:
                leg["lineup_status"] = "unknown"

    print(f"  Marked {scratched_count} player(s) as scratched")
    pre_scratch = len(upcoming)
    upcoming = [leg for leg in upcoming if leg.get("lineup_status") != "scratched"]
    if pre_scratch - len(upcoming):
        print(f"  Removed {pre_scratch - len(upcoming)} scratched leg(s)")

    if not upcoming:
        print("  No legs after lineup check. Exiting.")
        return

    # ── Step 8: Re-run lineup consistency filter ──────────────────────────────
    print(f"\n[6/8] Re-running lineup consistency filter...")
    _lc_kept, _lc_removed, _lc_errors = [], 0, 0
    _legs_before = len(upcoming)
    for _leg in upcoming:
        _pid  = _leg.get("player_id")
        _stat = _leg.get("stat", "")
        if not _pid or _stat in _PITCHER_STATS:
            _leg["lineup_consistency"] = 1.0
            _lc_kept.append(_leg)
            continue
        _lc = calculate_lineup_consistency(_pid, _stat, season)
        _leg["lineup_consistency"] = _lc
        if _lc is None:
            _lc_errors += 1
            _lc_kept.append(_leg)
        elif _lc >= 0.70:
            _lc_kept.append(_leg)
        else:
            _expanded = check_expanded_role_due_to_injury(_pid, _leg.get("team", ""), today)
            if _expanded.get("has_expanded_role"):
                print(f"    Kept {_leg.get('player_name')} (lc={_lc:.2f}) — {_expanded.get('reason','expanded role')}")
                _lc_kept.append(_leg)
            else:
                _lc_removed += 1
    if _lc_removed:
        print(f"  Removed {_lc_removed} low-consistency leg(s)")
    if _lc_errors:
        print(f"  {_lc_errors} legs had API errors — included conservatively")
    # Safety circuit-breaker: if >90% removed, something is wrong — skip filter
    if _legs_before > 0 and len(_lc_kept) < _legs_before * 0.10:
        print(f"  WARNING: filter removed >90% of legs — disabling for this run.")
        for _leg in upcoming:
            _leg.setdefault("lineup_consistency", None)
    else:
        upcoming = _lc_kept
    print(f"  {len(upcoming)} legs remaining after lineup consistency filter")

    if not upcoming:
        print("  No legs after lineup filter. Exiting.")
        return

    # ── Bridge field names for generate_recommendations ───────────────────────
    qualified = [
        {**leg, "best_odds": leg.get("odds"), "best_line": leg.get("line")}
        for leg in upcoming
    ]

    # ── Step 9: Build and save recommendations ────────────────────────────────
    print(f"\n[7/8] Building parlay recommendations from {len(qualified)} legs...")
    recommendations = generate_recommendations(qualified, run_date=today)
    print(f"  Built {len(recommendations)} recommendation(s)")

    if not recommendations:
        print("  No recommendations generated. Exiting.")
        return

    saved = 0
    run_time = datetime.now(timezone.utc)
    for rank, rec in enumerate(recommendations, start=1):
        rec_row = {
            "recommendation_date": today,
            "pipeline_run_time":   run_time,
            "rank":                rank,
            "leg_odd_ids":         [leg["odd_id"] for leg in rec["legs"]],
            "combined_odds":       rec["combined_odds"],
            "win_probability":     rec["win_probability"],
            "edge_pct":            rec["edge_pct"],
        }
        try:
            save_parlay_recommendation(rec_row)
            saved += 1
        except Exception as _save_err:
            print(f"  WARNING: failed to save rank {rank}: {_save_err}")

    best_edge = recommendations[0]["edge_pct"] if recommendations else 0
    print(f"\n[8/8] Saved {saved} recommendation(s) (rank 1 edge: {best_edge}%)")

    # Dual-write to v2 normalized schema
    try:
        save_parlay_recommendations_v2(recommendations, today, source=source)
    except Exception as _v2_err:
        print(f"  [v2] dual-write failed (non-fatal): {_v2_err}")

    print("\nTargeted refresh pipeline complete.")


def run_full_refresh_pipeline(source: str = "manual") -> None:
    """
    Full refresh pipeline for manual regenerate — fetches ALL fresh props from
    SGO, re-calculates coverage, re-scores, stores new legs to DB, and rebuilds
    parlay recommendations.

    Unlike run_targeted_pipeline() which reuses stale DB legs, this runs the
    complete fetch-score-store cycle so the web UI gets fresh data every time.

    SKIPS resolution step - that only happens in the 9 AM morning run.
    """
    run_pipeline(source=source, skip_resolution=True)


def run():
    """CLI entry point — calls run_pipeline() with resolution (morning behavior)."""
    run_pipeline(source="manual", skip_resolution=False)


# ── Testing notes ─────────────────────────────────────────────────────────────
# To test the recommendations system:
#   1. Run the SQL migration:  sql/create_recommendations_table.sql
#      (paste into Supabase SQL Editor and execute)
#   2. Run the pipeline:       python main.py
#      Recommendations are saved at Step 9 — check the Railway logs for:
#      "Saved N recommendation(s) (rank 1 edge: X.X%)"
#   3. Verify DB rows:         SELECT * FROM mlb_parlay_recommendations ORDER BY rank;
#   4. Hit the API:            GET http://localhost:PORT/api/recommendations
#      Should return {"recommendations": [...]} with hydrated leg details.


if __name__ == "__main__":
    run()
