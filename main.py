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
    get_player_info,
    get_transactions,
    is_il_placement,
)
from src.apis.pitcher_stats import get_pitcher_ranks
from src.apis.sportsgameodds import get_todays_games, get_player_props
from src.apis.team_stats import get_team_offensive_ranks
from src.engine.claude_agent import analyze_parlays
from src.engine.coverage import calculate_coverage, PROP_STAT_MAP
from src.engine.parlay_builder import build_hybrid_parlays, _tier_params
from src.pipelines.enrich_legs import enrich_legs
from src.pipelines.trend_analysis import get_trend_signal
from src.tracker.recommendation_logger import log_recommendations
from src.utils.db import log_scored_legs, log_training_data_legs, save_parlay_recommendation

# ── Constants ─────────────────────────────────────────────────────────────────

# Minimum raw coverage rate (%) to enter the candidate pool.
# The parlay builder applies a stricter internal threshold (60% minimum).
MIN_COVERAGE_PCT = 55.0

# Transaction typeCodes that affect player availability.
# SC = Status Change (IL placements/reinstatements)
# DES = Designated for Assignment
# OU = Outright waivers
# CU = Unconditional release
_RELEVANT_TXNS = frozenset({"SC", "DES", "OU", "CU"})

# Position codes that identify a pitcher; these players' props are skipped
# because pitcher prop coverage is not yet implemented.
_PITCHER_POSITIONS = frozenset({"P", "SP", "RP", "TWP"})

# In-process caches (reset each process run)
_player_id_cache: dict[str, int | None] = {}
_team_abbr_cache: dict[int, str] = {}   # team_id → abbreviation


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
    Apply the coverage gate to all SGO props and return qualifying legs.

    For each prop:
      1. Skip unsupported stats (inningsPitched, hitsAllowed, earnedRuns).
      2. Resolve player name → MLB person ID via statsapi.lookup_player().
      3. Get player's current team from get_player_info().
         - Skip pitchers unless stat == 'strikeouts' (pitcher K props enabled
           via Poisson coverage model — calculate_pitcher_k_coverage()).
      4. Confirm the player's team is on today's schedule.
      5. Call calculate_coverage() for batter props or
         calculate_pitcher_k_coverage() for pitcher K props.
      6. Include the leg if coverage_rate × 100 >= MIN_COVERAGE_PCT.

    Only the standard (non-alt) DK line is used. Alt-line coverage is deferred
    to a later phase.

    Returns a list of leg dicts ready for enrichment and trend analysis.
    """
    qualifying: list[dict] = []
    seen_odd_ids: set[str] = set()

    for prop in sgo_props:
        stat = prop.get("stat", "")
        if stat not in PROP_STAT_MAP:
            continue  # pitcher-only stat (inningsPitched, hitsAllowed, earnedRuns)

        standard_line = prop.get("standard_line")
        standard_odds = prop.get("standard_odds")
        if standard_line is None or not standard_odds:
            continue
        line = float(standard_line)

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
        # Pitcher K props enabled via Poisson coverage model; all other pitcher
        # prop types (IP, HA, ER) are still unsupported and skipped.
        is_pitcher_k = stat == "strikeouts" and position in _PITCHER_POSITIONS
        if position in _PITCHER_POSITIONS and not is_pitcher_k:
            continue

        # Confirm player's team plays today
        team_id = info.get("team_id")
        team_abbr = team_id_to_abbr.get(team_id, "")
        game_pk = team_abbr_to_game_pk.get(team_abbr)
        if not team_abbr or not game_pk:
            continue  # team not playing today

        opposing_pitcher_id = pitcher_id_map.get(team_abbr) or None

        # Coverage calculation — all props route through calculate_coverage().
        # Pitcher position is passed so pitcher props use game-log coverage.
        coverage = calculate_coverage(
            player_id=mlb_player_id,
            prop_type=stat,
            line=line,
            opposing_pitcher_id=opposing_pitcher_id,
            season=season,
            position=position,
        )
        if coverage is None:
            continue  # below seasonal minimum games threshold

        # Gate on best available coverage signal: vs-hand if available, else overall.
        coverage_pct = coverage.get("coverage_vs_hand") or coverage.get("coverage_overall") or 0.0
        if coverage_pct < MIN_COVERAGE_PCT:
            continue

        qualifying.append({
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
            "coverage_recent_5":   coverage.get("coverage_recent_5"),
            "games_total":         coverage.get("games_total"),
            "games_vs_hand":       coverage.get("games_vs_hand"),
            "games_recent":        coverage.get("games_recent"),
            "pitcher_hand":        coverage.get("pitcher_hand"),
            "batter_hand":         coverage.get("batter_hand"),
            # Game context
            "game_pk":             game_pk,
            "opposing_pitcher_id": opposing_pitcher_id if opposing_pitcher_id else None,
        })

    return qualifying


def _attach_pitcher_rank_signals(
    legs: list[dict],
    pitcher_ranks: dict,
    team_offensive_ranks: dict,
    opponent_map: dict[str, str],
    abbr_to_team_id: dict[str, int],
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

    Returns:
        List of dicts: [{legs, combined_odds, win_probability, edge_pct}]
        ranked by edge_pct descending.
    """
    # Get up to 3× candidates to give the diversity filter room to work
    candidates = build_hybrid_parlays(qualifying_legs, top_n=15)
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

    # Diversity filter: each leg may appear in at most 2 of the final parlays
    leg_appearance: dict[str, int] = {}
    result: list[dict] = []

    for candidate in enriched:
        odd_ids = [leg["odd_id"] for leg in candidate["legs"]]

        # Tentatively count appearances
        temp = dict(leg_appearance)
        valid = True
        for oid in odd_ids:
            temp[oid] = temp.get(oid, 0) + 1
            if temp[oid] > 2:
                valid = False
                break

        if valid:
            leg_appearance = temp
            result.append(candidate)

        if len(result) >= max_recommendations:
            break

    return result


# ── Public pipeline function ──────────────────────────────────────────────────

def run_pipeline(starts_after_override=None) -> tuple[list[dict], str]:
    """
    Execute the full MLB parlay pipeline and return (parlays, analysis).

    Called by the web server scheduler in a background thread. All console
    output is visible in Railway logs.

    Args:
        starts_after_override: Optional UTC datetime. When provided, only SGO
            games starting after this time are fetched (used by /api/refresh to
            skip games starting within the next N hours and minimise API quota).

    Returns:
        (parlays, analysis) — parlays is a list of hybrid parlay dicts;
        analysis is Claude's plain-English summary. Both are empty when no
        qualifying output is produced.
    """
    today  = str(date.today())
    season = date.today().year

    print(f"\nMLB Parlay Agent — {today}")
    print("=" * 50)

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

    # ── Step 4: Coverage Gate ─────────────────────────────────────────────────
    print(f"\n[4/8] Computing coverage (min {MIN_COVERAGE_PCT}%)...")
    qualifying_legs = _find_qualifying_legs(
        all_sgo_props,
        team_id_to_abbr,
        team_abbr_to_game_pk,
        pitcher_id_map,
        season,
    )
    print(f"  {len(qualifying_legs)} qualifying leg(s) at ≥{MIN_COVERAGE_PCT}% coverage")

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

    if not qualifying_legs:
        print("  No legs after injury filter. Exiting.")
        return [], ""

    # ── Step 6: Opponent Enrichment (pitcher profiles) ────────────────────────
    print("\n[6/8] Enriching legs with pitcher matchup profiles...")
    qualifying_legs = enrich_legs(qualifying_legs, pitcher_id_map, opponent_map, season)

    # ── Filter: remove legs whose games have already started ─────────────────
    _et_tz = pytz.timezone("America/New_York")
    _now_et = datetime.now(_et_tz)
    _cutoff = _now_et - timedelta(minutes=5)
    upcoming_legs = []
    for _leg in qualifying_legs:
        _gst = _leg.get("game_start_time")
        if not _gst:
            upcoming_legs.append(_leg)  # keep legs with no time data
            continue
        try:
            _gt = datetime.strptime(_gst, "%Y-%m-%d %H:%M:%S")
            if _et_tz.localize(_gt) > _cutoff:
                upcoming_legs.append(_leg)
        except Exception:
            upcoming_legs.append(_leg)
    print(
        f"  [filter_started] {len(qualifying_legs)} legs → "
        f"{len(upcoming_legs)} upcoming (filtered {len(qualifying_legs) - len(upcoming_legs)} started)"
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
    )

    # ── Step 8: Build Hybrid Parlays ──────────────────────────────────────────
    tier_info  = _tier_params(len(schedule))
    tier_label = f"Tier {tier_info['tier']}" if tier_info else "Tier 4 (thin slate)"
    print(f"\n[8/8] Building hybrid parlays ({len(schedule)} games → {tier_label})...")

    parlays = build_hybrid_parlays(
        qualifying_legs,
        num_games=len(schedule),
        team_to_blocked=team_to_blocked,
    )
    print(f"  Built {len(parlays)} parlay(s)")

    # Filter invalid strikeout lines before saving to DB
    # Hitter strikeouts: only line 0.5 allowed
    # Pitcher strikeouts: only line >= 3.5 allowed
    def _valid_strikeout_line(leg: dict) -> bool:
        if leg.get("stat") != "strikeouts":
            return True
        position = leg.get("position", "")
        is_pitcher = position in _PITCHER_POSITIONS
        line = leg.get("best_line")
        if is_pitcher:
            return line is not None and float(line) >= 3.5
        else:
            return line is not None and float(line) == 0.5

    before_so_filter = len(qualifying_legs)
    qualifying_legs = [l for l in qualifying_legs if _valid_strikeout_line(l)]
    if before_so_filter != len(qualifying_legs):
        print(f"  [so_filter] removed {before_so_filter - len(qualifying_legs)} invalid strikeout line(s)")

    # Log all scored legs regardless of parlay outcome
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
    recommendations = generate_recommendations(qualifying_legs)

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

    # Persist recommendations for calibration tracking
    log_recommendations(parlays)

    # LLM plain-English analysis
    print("\nSending to Claude for analysis...")
    try:
        analysis = analyze_parlays(parlays)
        print(analysis)
    except Exception as e:
        analysis = f"LLM analysis failed: {e}"
        print(f"  [claude_agent] error: {e}")

    return parlays, analysis


def run_morning_pipeline() -> None:
    """
    Morning resolution pipeline (9 AM ET): resolve yesterday's outcomes and
    update training data. Does NOT fetch props, score legs, or build parlays.

    Live recommendations are served on-demand via /api/build-parlays?refresh=true.
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

    # Step 2: Resolve yesterday's training data outcomes
    print(f"\n[2/4] Resolving outcomes for {yesterday}...")
    try:
        from src.tracker.outcome_resolver import resolve_training_data
        resolution_stats = resolve_training_data(yesterday, verbose=True)
        print(f"  Resolution complete: {resolution_stats['hit']} hits, "
              f"{resolution_stats['miss']} misses, {resolution_stats['void']} voids")
    except Exception as _res_err:
        print(f"  WARNING: Outcome resolution failed: {_res_err}")
        # Don't crash the pipeline if resolution fails

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
    print("\n[4/4] Morning pipeline complete")
    print("  For live recommendations, use /api/build-parlays?refresh=true")


def run():
    """CLI entry point — calls run_pipeline() and prints output."""
    run_pipeline()


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
#   5. Test on-demand analysis: POST http://localhost:PORT/api/analyze-recommendation
#      Body: {"recommendation_id": <id from step 3>}


if __name__ == "__main__":
    run()
