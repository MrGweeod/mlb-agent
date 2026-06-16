"""
run_enriched_pipeline.py — Shadow pipeline for enriched scoring A/B comparison.

Runs after the production pipeline completes. Takes the same scored legs,
re-scores them with enriched_scorer.py (3 additional signals), builds shadow
parlays, and writes results to the *_enriched shadow tables.

Shadow tables (must already exist in Supabase):
  - mlb_scored_legs_enriched
  - mlb_parlay_recommendations_enriched
  - mlb_parlay_legs_enriched

Never touches production tables. All failures are silently logged.
"""

import copy
import datetime

import statsapi

from src.apis.mlb_stats import get_schedule
from src.apis.pitcher_stats import get_pitcher_ranks
from src.engine import enriched_scorer
from src.engine.enriched_scorer import (
    STACK_BONUS,
    STACK_MIN_LEGS,
    STACK_VULNERABILITY_THRESHOLD,
    STACK_ELIGIBLE_PROPS,
    pitcher_vulnerability,
)
from src.engine.parlay_builder import build_hybrid_parlays
from src.utils.db import get_conn, get_enriched_players_used_today


def apply_stack_bonuses(scored_legs: list[dict]) -> list[dict]:
    """
    Post-scoring pass. For each qualifying offense stack, apply STACK_BONUS
    to each leg in the stack. Modifies composite_score in place.

    A qualifying stack: 2+ legs sharing (team, game_pk) where the opposing
    pitcher's vulnerability score >= STACK_VULNERABILITY_THRESHOLD.

    Also sets stack_bonus_applied and pitcher_vulnerability on every leg.
    """
    today = datetime.date.today().isoformat()

    # Compute dynamic max ranks from the full scored leg pool
    max_era_rank  = max((leg.get("opp_pitcher_era_rank")  or leg.get("pitcher_era_rank")  or 0 for leg in scored_legs), default=0)
    max_k9_rank   = max((leg.get("opp_pitcher_k9_rank")   or leg.get("pitcher_k9_rank")   or 0 for leg in scored_legs), default=0)
    max_whip_rank = max((leg.get("opp_pitcher_whip_rank") or leg.get("pitcher_whip_rank") or 0 for leg in scored_legs), default=0)
    print(f"[stack_bonus] {today}: max ranks — ERA={max_era_rank}, K/9={max_k9_rank}, WHIP={max_whip_rank}")
    print(f"[stack_bonus] {today}: filtering for stack-eligible props: {STACK_ELIGIBLE_PROPS}")

    # Initialise stack tracking fields on all legs (vulnerability stored for data collection)
    for leg in scored_legs:
        leg.setdefault("stack_bonus_applied", False)
        leg["pitcher_vulnerability"] = pitcher_vulnerability(leg, max_era_rank, max_k9_rank, max_whip_rank)

    # Group by (team, game_pk) — only count stack-eligible (stat, direction) pairs
    groups: dict[tuple, list[dict]] = {}
    for leg in scored_legs:
        key = (leg.get("team"), leg.get("game_pk"))
        prop_key = (leg.get("stat"), leg.get("direction"))
        if key[0] and key[1] and prop_key in STACK_ELIGIBLE_PROPS:
            groups.setdefault(key, []).append(leg)

    qualifying_stacks = 0
    for (team, game_pk), group_legs in groups.items():
        if len(group_legs) < STACK_MIN_LEGS:
            # Too few legs — log non-qualifying if vulnerability is computed
            vuln = group_legs[0].get("pitcher_vulnerability")
            if vuln is not None:
                print(
                    f"[stack_bonus] No qualifying stacks: {team} (game {game_pk}) "
                    f"— only {len(group_legs)} leg(s) (need {STACK_MIN_LEGS})"
                )
            continue

        # All legs in the group face the same pitcher — use first leg's data
        vuln = group_legs[0].get("pitcher_vulnerability")

        if vuln is None:
            print(f"[stack_bonus] {team} (game {game_pk}) — no pitcher data, skipping")
            continue

        if vuln < STACK_VULNERABILITY_THRESHOLD:
            print(
                f"[stack_bonus] No qualifying stacks: {team} (game {game_pk}) "
                f"— vulnerability={vuln:.2f} (below threshold {STACK_VULNERABILITY_THRESHOLD})"
            )
            continue

        # Qualifying stack — apply bonus to each leg
        for leg in group_legs:
            current = leg.get("composite_score")
            if current is not None:
                leg["composite_score"] = min(95.0, current + STACK_BONUS)
            leg["stack_bonus_applied"] = True
        qualifying_stacks += 1
        print(
            f"[stack_bonus] Stack: {team} (game {game_pk}) "
            f"— pitcher_vulnerability={vuln:.2f} "
            f"— {len(group_legs)} leg(s) boosted (+{STACK_BONUS} each)"
        )

    if qualifying_stacks:
        stacked_games = len({leg.get("game_pk") for leg in scored_legs if leg.get("stack_bonus_applied")})
        print(
            f"[stack_bonus] {today}: {qualifying_stacks} qualifying stack(s) detected "
            f"across {stacked_games} game(s)"
        )
    else:
        print(f"[stack_bonus] {today}: no qualifying stacks detected")

    return scored_legs


def _build_team_maps() -> tuple[dict, dict]:
    """
    Return (team_id_to_abbr, abbr_to_team_id) for all 30 MLB teams.
    Falls back to empty dicts on network error.
    """
    team_id_to_abbr: dict[int, str] = {}
    try:
        for t in statsapi.get("teams", {"sportId": 1}).get("teams", []):
            team_id_to_abbr[t["id"]] = t["abbreviation"]
    except Exception as e:
        print(f"[ENRICHED PIPELINE] Failed to load team map: {e}")
    abbr_to_team_id = {v: k for k, v in team_id_to_abbr.items()}
    return team_id_to_abbr, abbr_to_team_id


def _build_game_pk_to_home_abbr(
    schedule: list[dict],
    team_id_to_abbr: dict[int, str],
) -> dict:
    """
    Build {game_pk: home_team_abbr} from today's schedule list.

    schedule entries have: game_id, home_id, away_id, home_name, away_name
    """
    result = {}
    for game in schedule:
        game_pk = game.get("game_id")
        home_id = game.get("home_id")
        if game_pk and home_id:
            abbr = team_id_to_abbr.get(home_id)
            if abbr:
                result[game_pk] = abbr
    return result


def _log_enriched_legs(legs: list[dict], run_date: str, parlay_odd_ids: set) -> int:
    """
    Upsert enriched scored legs to mlb_scored_legs_enriched.

    Mirrors the schema of mlb_scored_legs plus the 6 enriched columns:
      coverage_vs_opponent, games_vs_opponent, park_factor,
      park_adjustment, blended_era_rank, recent_form_rank.
    """
    if not legs:
        return 0

    rows = []
    for leg in legs:
        if not (leg.get("stat") and leg.get("player_name") and leg.get("odd_id")):
            continue
        rows.append((
            run_date,
            leg.get("player_name", ""),
            leg.get("team"),
            leg.get("opponent"),
            leg.get("stat", ""),
            leg.get("best_line"),
            leg.get("direction", "over"),
            str(leg.get("best_odds", "")),
            leg.get("coverage_pct"),
            leg.get("p_over"),
            leg.get("ev_per_unit"),
            leg.get("composite_score"),
            leg.get("coverage_overall"),
            leg.get("coverage_vs_hand"),
            leg.get("coverage_recent_10"),
            leg.get("pitcher_id"),
            leg.get("pitcher_name"),
            leg.get("pitcher_era"),
            leg.get("pitcher_k9"),
            leg.get("pitcher_whip"),
            leg.get("batter_hand"),
            leg.get("game_pk"),
            str(leg.get("player_id")) if leg.get("player_id") else None,
            str(leg.get("opposing_pitcher_id")) if leg.get("opposing_pitcher_id") else None,
            leg.get("odd_id"),
            leg.get("odd_id") in parlay_odd_ids,
            leg.get("opp_pitcher_era_rank") if leg.get("opp_pitcher_era_rank") is not None else leg.get("pitcher_era_rank"),
            leg.get("opp_pitcher_k9_rank")  if leg.get("opp_pitcher_k9_rank")  is not None else leg.get("pitcher_k9_rank"),
            leg.get("opp_pitcher_whip_rank") if leg.get("opp_pitcher_whip_rank") is not None else leg.get("pitcher_whip_rank"),
            # Enriched-only columns
            leg.get("coverage_vs_opponent"),
            leg.get("games_vs_opponent"),
            leg.get("park_factor"),
            leg.get("park_adjustment"),
            leg.get("blended_era_rank"),
            leg.get("recent_form_rank"),
            # Stack bonus columns
            leg.get("stack_bonus_applied", False),
            leg.get("pitcher_vulnerability"),
        ))

    if not rows:
        return 0

    import psycopg2.extras

    conn = get_conn()
    cur = conn.cursor()
    psycopg2.extras.execute_values(
        cur,
        """
        INSERT INTO mlb_scored_legs_enriched
            (run_date, player_name, team, opponent, stat, line, direction, odds,
             coverage_pct, p_over, ev_per_unit, composite_score,
             coverage_overall, coverage_vs_hand, coverage_recent_10,
             pitcher_id, pitcher_name, pitcher_era, pitcher_k9, pitcher_whip,
             batter_hand, game_pk, player_id, opposing_pitcher_id, odd_id, in_parlay,
             pitcher_era_rank, pitcher_k9_rank, pitcher_whip_rank,
             coverage_vs_opponent, games_vs_opponent, park_factor, park_adjustment,
             blended_era_rank, recent_form_rank,
             stack_bonus_applied, pitcher_vulnerability)
        VALUES %s
        ON CONFLICT (run_date, odd_id) DO UPDATE
            SET composite_score        = EXCLUDED.composite_score,
                coverage_vs_opponent   = EXCLUDED.coverage_vs_opponent,
                games_vs_opponent      = EXCLUDED.games_vs_opponent,
                park_factor            = EXCLUDED.park_factor,
                park_adjustment        = EXCLUDED.park_adjustment,
                blended_era_rank       = EXCLUDED.blended_era_rank,
                recent_form_rank       = EXCLUDED.recent_form_rank,
                in_parlay              = EXCLUDED.in_parlay,
                stack_bonus_applied    = EXCLUDED.stack_bonus_applied,
                pitcher_vulnerability  = EXCLUDED.pitcher_vulnerability
        """,
        rows,
    )
    conn.commit()
    inserted = cur.rowcount
    cur.close()
    conn.close()
    return inserted


def _save_enriched_parlays(
    recommendations: list[dict],
    run_date: str,
    source: str,
    production_batch_id: str = "",
) -> str:
    """
    Write enriched parlays to mlb_parlay_recommendations_enriched
    and mlb_parlay_legs_enriched.

    Mirrors save_parlay_recommendations_v2 structure but targets the
    enriched shadow tables and includes blended_era_rank / park_adjustment.
    """
    if not recommendations:
        return ""

    batch_id = f"{run_date}_{datetime.datetime.now().strftime('%H:%M:%S')}"
    conn = get_conn()
    cur = conn.cursor()

    for rank, rec in enumerate(recommendations, start=1):
        legs = rec.get("legs", [])
        coverages = [l.get("coverage_pct") for l in legs if l.get("coverage_pct") is not None]
        evs = [l.get("ev_per_unit") for l in legs if l.get("ev_per_unit") is not None]
        avg_coverage = round(sum(coverages) / len(coverages), 3) if coverages else None
        avg_ev = round(sum(evs) / len(evs), 4) if evs else None

        cur.execute(
            """
            INSERT INTO mlb_parlay_recommendations_enriched
                (run_date, rank, total_odds, avg_coverage, avg_ev, num_legs,
                 outcome, source, batch_id, edge_percent, production_batch_id)
            VALUES (%s, %s, %s, %s, %s, %s, 'pending', %s, %s, %s, %s)
            RETURNING id
            """,
            (
                run_date,
                rank,
                rec.get("combined_odds"),
                avg_coverage,
                avg_ev,
                len(legs),
                source,
                batch_id,
                rec.get("edge_pct"),
                production_batch_id or None,
            ),
        )
        row = cur.fetchone()
        if row is None:
            raise RuntimeError(
                f"[ENRICHED PIPELINE] INSERT INTO mlb_parlay_recommendations_enriched "
                f"RETURNING id returned None for rank={rank}"
            )
        parlay_id = row["id"]

        for leg in legs:
            cur.execute(
                """
                INSERT INTO mlb_parlay_legs_enriched
                    (parlay_id, player_id, player_name, team, stat, line,
                     direction, odds, composite_score, coverage, ev,
                     game_id, opposing_pitcher_id, opposing_pitcher_name,
                     blended_era_rank, park_factor, park_adjustment,
                     coverage_vs_opponent, outcome)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s,
                        %s, %s, %s, %s, %s, %s, %s, 'pending')
                """,
                (
                    parlay_id,
                    leg.get("player_id"),
                    leg.get("player_name"),
                    leg.get("team"),
                    leg.get("stat"),
                    leg.get("best_line") or leg.get("line"),
                    leg.get("direction", "over"),
                    leg.get("best_odds") or leg.get("odds"),
                    leg.get("composite_score"),
                    leg.get("coverage_pct"),
                    leg.get("ev_per_unit"),
                    leg.get("game_pk"),
                    leg.get("opposing_pitcher_id"),
                    leg.get("opposing_pitcher_name"),
                    leg.get("blended_era_rank"),
                    leg.get("park_factor"),
                    leg.get("park_adjustment"),
                    leg.get("coverage_vs_opponent"),
                ),
            )

    conn.commit()
    cur.close()
    conn.close()
    return batch_id


def run_enriched_pipeline(scored_legs: list, production_batch_id: str = "") -> None:
    """
    Re-score production pipeline legs with enriched signals and write to
    shadow tables for A/B comparison.

    Takes the same legs produced by the production pipeline (already filtered,
    coverage-computed, and coverage-scored). Does not re-fetch from APIs —
    all per-leg API calls in enriched_scorer hit the 24h in-memory cache
    populated during the production run.

    Does not affect production tables under any circumstances.
    """
    if not scored_legs:
        print("[ENRICHED PIPELINE] No legs to score — skipping")
        return

    today = datetime.date.today().isoformat()
    season = datetime.date.today().year

    # Deep copy so enriched scoring never mutates production leg dicts
    enriched_legs = copy.deepcopy(scored_legs)

    # Shadow pipeline prop whitelist — only score validated prop types
    # totalBases line gate in enriched_scorer acts as a secondary safety net
    _SHADOW_WHITELIST = {
        ("hits", "over", 0.5),
        ("hits", "under", 0.5),
        ("strikeouts", "over", 0.5),
        ("totalBases", "under", 1.5),
    }
    enriched_legs = [
        leg for leg in enriched_legs
        if (leg.get("stat"), leg.get("direction"), leg.get("best_line")) in _SHADOW_WHITELIST
    ]
    if not enriched_legs:
        print("[ENRICHED PIPELINE] No qualifying legs after whitelist filter — skipping")
        return

    # Build team maps for opponent matching and park factor lookup
    team_id_to_abbr, abbr_to_team_id = _build_team_maps()

    # Build game_pk → home team abbr from today's cached schedule
    try:
        schedule = get_schedule(today)
    except Exception as e:
        print(f"[ENRICHED PIPELINE] Schedule fetch failed: {e}")
        schedule = []
    game_pk_to_home_abbr = _build_game_pk_to_home_abbr(schedule, team_id_to_abbr)

    # Fetch pitcher ranks (hits 24h cache populated by production run)
    pitcher_ranks = get_pitcher_ranks(season)

    # Load ballpark factors (hits module-level cache if already loaded)
    ballpark_factors = enriched_scorer._load_ballpark_factors()

    # Re-score with enriched signals
    enriched_scorer.score_legs(
        enriched_legs,
        season=season,
        pitcher_ranks=pitcher_ranks,
        ballpark_factors=ballpark_factors,
        abbr_to_team_id=abbr_to_team_id,
        game_pk_to_home_abbr=game_pk_to_home_abbr,
    )

    # Post-scoring stack bonus pass (must run after individual scores, before DB write)
    apply_stack_bonuses(enriched_legs)

    # Apply cross-run 2x player cap — mirrors production player_cap logic
    pool_for_parlays = enriched_legs
    try:
        capped_player_ids = get_enriched_players_used_today(today)
        if capped_player_ids:
            before = len(pool_for_parlays)
            pool_for_parlays = [
                l for l in pool_for_parlays
                if str(l.get("player_id", "")) not in capped_player_ids
            ]
            removed = before - len(pool_for_parlays)
            print(
                f"[enriched_player_diversity] Filtered {removed} legs from "
                f"{len(capped_player_ids)} players already used today: "
                f"{sorted(capped_player_ids)}"
            )
            # Fallback: if cap leaves pool too thin, restore full pool
            if len(pool_for_parlays) < 20:
                print(
                    f"[enriched_player_diversity] Pool too thin after cap "
                    f"({len(pool_for_parlays)} legs) — restoring full pool"
                )
                pool_for_parlays = enriched_legs
        else:
            print(f"[enriched_player_diversity] No players at cap yet today — {len(pool_for_parlays)} legs in pool")
    except Exception as _cap_err:
        print(f"[enriched_player_diversity] Could not apply player cap (non-fatal): {_cap_err}")

    # Build 4-leg +400-+700 shadow parlays from single flat pool
    shadow_parlays = build_hybrid_parlays(
        pool_for_parlays,
        [],
        num_games=len(schedule) if schedule else 15,
    )

    # Determine source label (matches production _source + _enriched suffix)
    import pytz
    _et = pytz.timezone("America/New_York")
    _hour_et = datetime.datetime.now(_et).hour
    if _hour_et < 11:
        _source = "auto_9am_enriched"
    elif _hour_et < 14:
        _source = "auto_12pm_enriched"
    else:
        _source = "auto_530pm_enriched"

    # Write enriched legs to shadow table
    parlay_odd_ids = {leg["odd_id"] for p in shadow_parlays for leg in p.get("legs", [])}
    n_logged = _log_enriched_legs(enriched_legs, today, parlay_odd_ids)

    # Build and write shadow recommendations
    recommendations = []
    for p in shadow_parlays:
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

    if recommendations:
        _save_enriched_parlays(recommendations, today, _source, production_batch_id=production_batch_id)

    print(
        f"[ENRICHED PIPELINE] Complete: {n_logged} legs scored, "
        f"{len(shadow_parlays)} parlay(s) built"
    )
