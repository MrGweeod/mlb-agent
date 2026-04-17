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
  bot.py via src/bot/runner.py (async, background thread).
"""
from __future__ import annotations

from datetime import date

import statsapi

from src.apis.mlb_stats import (
    get_schedule,
    get_batter_game_log,
    get_player_info,
    get_transactions,
    is_il_placement,
)
from src.apis.sportsgameodds import get_todays_games, get_player_props
from src.engine.claude_agent import analyze_parlays, get_injured_players
from src.engine.coverage import calculate_coverage, PROP_STAT_MAP
from src.engine.parlay_builder import build_hybrid_parlays, _tier_params
from src.pipelines.enrich_legs import enrich_legs
from src.pipelines.trend_analysis import get_trend_signal
from src.tracker.recommendation_logger import log_recommendations
from src.utils.db import log_scored_legs

# ── Constants ─────────────────────────────────────────────────────────────────

# Minimum raw coverage rate (%) to enter the candidate pool.
# The parlay builder applies stricter thresholds (70% anchors, 55% swings).
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
        for t in statsapi.teams(sportId=1):
            _team_abbr_cache[t["id"]] = t["abbreviation"]
    except Exception as e:
        print(f"  [main] statsapi.teams() error: {e}")
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
      1. Skip non-batter stats (inningsPitched, hitsAllowed, earnedRuns).
      2. Resolve player name → MLB person ID via statsapi.lookup_player().
      3. Get player's current team from get_player_info(); skip pitchers.
      4. Confirm the player's team is on today's schedule.
      5. Call calculate_coverage() with the standard line and opposing pitcher.
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

        # Skip pitchers — pitcher prop coverage not yet implemented
        position = info.get("position", "")
        if position in _PITCHER_POSITIONS:
            continue

        # Confirm player's team plays today
        team_id = info.get("team_id")
        team_abbr = team_id_to_abbr.get(team_id, "")
        game_pk = team_abbr_to_game_pk.get(team_abbr)
        if not team_abbr or not game_pk:
            continue  # team not playing today

        opposing_pitcher_id = pitcher_id_map.get(team_abbr) or 0

        # Coverage calculation (handedness-split via statSplits + Poisson)
        coverage = calculate_coverage(
            player_id=mlb_player_id,
            prop_type=stat,
            line=line,
            opposing_pitcher_id=opposing_pitcher_id,
            season=season,
        )
        if coverage is None:
            continue  # below seasonal minimum games threshold

        coverage_pct = round(coverage["coverage_rate"] * 100, 1)
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
            "p_over":              coverage["coverage_rate"],
            "coverage_pct":        coverage_pct,
            "confidence_mult":     coverage["confidence_multiplier"],
            "split_used":          coverage["split_used"],
            "pitcher_hand":        coverage["pitcher_hand"],
            "batter_hand":         coverage["batter_hand"],
            # Game context
            "game_pk":             game_pk,
            "opposing_pitcher_id": opposing_pitcher_id if opposing_pitcher_id else None,
        })

    return qualifying


def _attach_trend_signals(legs: list[dict], season: int) -> None:
    """
    Compute trend signals for each leg and merge them into the leg dict in-place.

    Role assignment: coverage_pct >= 70% → "anchor", otherwise "swing".
    Trend signals are sourced from the player's game log (cached 24h).
    """
    for leg in legs:
        player_id = leg.get("player_id")
        stat      = leg.get("stat", "")
        line      = leg.get("best_line")
        if not player_id or not stat or line is None:
            continue

        game_log = get_batter_game_log(int(player_id), season)
        if not game_log:
            continue

        role = "anchor" if leg.get("coverage_pct", 0) >= 70.0 else "swing"
        signals = get_trend_signal(
            player_id=str(player_id),
            stat=stat,
            game_log=game_log,
            best_line=float(line),
            role=role,
        )
        leg.update(signals)


# ── Public pipeline function ──────────────────────────────────────────────────

def run_pipeline() -> tuple[list[dict], str]:
    """
    Execute the full MLB parlay pipeline and return (parlays, analysis).

    Called by src/bot/runner.py in a background thread. All console output
    is visible in Railway logs.

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
        sgo_games = get_todays_games()
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

    # LLM spot-check on all player names entering the parlay pool
    leg_players = sorted({l["player_name"] for l in qualifying_legs})
    try:
        llm_flagged = get_injured_players(leg_players)
        if llm_flagged:
            blocked_names = blocked_names | {n.lower() for n in llm_flagged}
            print(f"  LLM flagged: {', '.join(sorted(llm_flagged))}")
        else:
            print("  LLM: no additional players flagged")
    except Exception as e:
        print(f"  LLM injury check error: {e} — skipping")

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

    # ── Step 7: Trend Signals ─────────────────────────────────────────────────
    print("\n[7/8] Computing trend signals...")
    _attach_trend_signals(qualifying_legs, season)
    trend_pass_count = sum(1 for l in qualifying_legs if l.get("trend_pass"))
    form_counts = {}
    for l in qualifying_legs:
        label = l.get("form_label", "NEUTRAL")
        form_counts[label] = form_counts.get(label, 0) + 1
    print(
        f"  {trend_pass_count}/{len(qualifying_legs)} pass trend filter | "
        + " | ".join(f"{k}:{v}" for k, v in sorted(form_counts.items()))
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

    # Log all scored legs regardless of parlay outcome
    parlay_odd_ids = {leg["odd_id"] for p in parlays for leg in p.get("legs", [])}
    n_logged = log_scored_legs(qualifying_legs, today, parlay_odd_ids)
    if n_logged:
        print(f"  Logged {n_logged} scored leg(s) ({len(parlay_odd_ids)} in parlay)")

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


def run():
    """CLI entry point — calls run_pipeline() and prints output."""
    run_pipeline()


if __name__ == "__main__":
    run()
