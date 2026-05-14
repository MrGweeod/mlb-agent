"""
Test regenerate with new ML scoring + temporary adjustments.

Mirrors the logic in handle_regenerate_recommendations (server.py) but:
  - Uses score_legs_ml() instead of coverage_pct as composite_score
  - Applies temporary adjustments (direction bias, odds signal, same-game)
  - Prints detailed parlay breakdown

Usage:
    python3 scripts/test_regenerate.py
    python3 scripts/test_regenerate.py 2026-05-11
    railway run python3 scripts/test_regenerate.py
"""
import os
import sys
from datetime import datetime, timedelta

import pytz

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from src.utils.db import get_scored_legs
from src.engine.ml_leg_scorer import score_legs_ml
from src.engine.parlay_builder import build_hybrid_parlays

ET_TZ = pytz.timezone("America/New_York")


def main():
    run_date = sys.argv[1] if len(sys.argv) > 1 else "2026-05-11"

    print(f"\n{'='*60}")
    print(f"[test_regenerate] run_date={run_date}")
    print(f"{'='*60}\n")

    # 1. Load legs from DB
    print(f"[test] Loading legs from mlb_scored_legs for {run_date}...")
    legs = get_scored_legs(run_date)
    print(f"[test] Loaded {len(legs)} legs")

    if not legs:
        print("[test] No legs found. Did the morning pipeline run?")
        return

    # 2. Check game_start_time coverage
    missing_time = [l for l in legs if not l.get("game_start_time")]
    print(f"[test] game_start_time: {len(legs) - len(missing_time)} populated, {len(missing_time)} NULL")
    if missing_time:
        print("[test] WARNING: Some legs are missing game_start_time.")
        print("[test]   Run: python3 scripts/backfill_game_start_time.py")
        print("[test]   Legs missing time will be excluded from parlays.\n")

    # 3. Apply ML scoring + temporary adjustments
    print("[test] Running score_legs_ml (ML model + direction/odds/same-game adjustments)...")
    legs = score_legs_ml(legs)

    # 4. Filter by game start time (15-min forward buffer, same as regenerate)
    now_et = datetime.now(ET_TZ)
    cutoff = now_et + timedelta(minutes=15)
    active_legs = []
    started_count = 0
    null_count = 0

    for leg in legs:
        gst = leg.get("game_start_time")
        if not gst:
            null_count += 1
            continue
        try:
            gt = ET_TZ.localize(datetime.strptime(gst, "%Y-%m-%d %H:%M:%S"))
            if gt > cutoff:
                active_legs.append(leg)
            else:
                started_count += 1
        except Exception:
            null_count += 1

    print(
        f"\n[test] {len(legs)} legs → {len(active_legs)} upcoming "
        f"(cutoff {cutoff.strftime('%H:%M ET')}, "
        f"filtered {started_count} started, {null_count} missing time)"
    )

    # 5. Check ML gatekeeper pool (composite_score >= 65%)
    eligible = [l for l in active_legs if (l.get("composite_score") or 0) >= 65]
    print(f"[test] {len(eligible)} legs pass ML gatekeeper (composite_score >= 65%)")

    if len(active_legs) < 4:
        print("[test] Not enough active legs to build parlays (need 4+).")
        return

    # Print score distribution
    over_legs = [l for l in active_legs if l.get("direction") == "over"]
    under_legs = [l for l in active_legs if l.get("direction") == "under"]
    print(f"\n[test] Direction split: {len(over_legs)} overs, {len(under_legs)} unders")
    if over_legs:
        avg_over = sum(l.get("composite_score", 0) for l in over_legs) / len(over_legs)
        print(f"[test] Avg over score: {avg_over:.1f}%")
    if under_legs:
        avg_under = sum(l.get("composite_score", 0) for l in under_legs) / len(under_legs)
        print(f"[test] Avg under score: {avg_under:.1f}%")

    # 6. Build parlays
    print("\n[test] Building parlays...")
    parlays = build_hybrid_parlays(active_legs, top_n=5)
    print(f"\n[test] Built {len(parlays)} parlays")

    if not parlays:
        print("[test] No parlays built. Possible causes:")
        print("  - Not enough legs with composite_score >= 65%")
        print("  - No combinations hit the +1000–+1500 odds window")
        print("  - Too many legs filtered by same-game or player-per-game limits")
        return

    # 7. Print parlay details
    print(f"\n{'='*60}")
    for i, p in enumerate(parlays, 1):
        legs_in_parlay = p.get("legs", [])
        total_odds = p.get("total_odds", p.get("parlay_odds", "?"))
        avg_score = p.get("avg_composite", p.get("avg_coverage", 0))

        print(f"\nParlay {i}:")
        print(f"  Legs: {len(legs_in_parlay)}")
        print(f"  Total odds: +{total_odds}")
        print(f"  Avg ML score: {avg_score:.1f}%")

        # Direction breakdown
        n_over = sum(1 for l in legs_in_parlay if l.get("direction") == "over")
        n_under = sum(1 for l in legs_in_parlay if l.get("direction") == "under")
        print(f"  Directions: {n_over} over, {n_under} under")

        for leg in legs_in_parlay:
            print(
                f"    - {leg.get('player_name', '?')} | {leg.get('stat', '?')} "
                f"{leg.get('direction', '?')} | "
                f"{leg.get('composite_score', 0):.1f}% ML | "
                f"{leg.get('odds', 0):+d} odds | "
                f"{leg.get('team', '?')}"
            )

    print(f"\n{'='*60}")
    n_over_total = sum(
        sum(1 for l in p.get("legs", []) if l.get("direction") == "over")
        for p in parlays
    )
    n_under_total = sum(
        sum(1 for l in p.get("legs", []) if l.get("direction") == "under")
        for p in parlays
    )
    total_legs = n_over_total + n_under_total
    if total_legs:
        print(f"[test] Overall direction: {n_over_total} overs ({100*n_over_total/total_legs:.0f}%), "
              f"{n_under_total} unders ({100*n_under_total/total_legs:.0f}%)")


if __name__ == "__main__":
    main()
