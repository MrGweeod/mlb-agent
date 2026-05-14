#!/usr/bin/env python3
"""
Rescore historical legs with corrected direction-aware coverage model.

Fixes applied vs the previous version:
  1. Removes the `opposing_pitcher_id IS NOT NULL` restriction — hitter legs
     without a known pitcher still get coverage_overall / recent coverage.
  2. Updates ALL coverage columns in mlb_scored_legs (coverage_overall,
     coverage_vs_hand, coverage_recent_10, coverage_recent_5, coverage_pct,
     p_over) instead of only coverage_pct / p_over.
  3. Also backfills mlb_training_data.coverage_pct for each matching leg so
     the ML model can be retrained on corrected data.

The mlb_stats in-memory cache deduplicates API calls across legs for the
same player, so actual network traffic is proportional to unique
(player, season) pairs, not total legs.

Run from the project root:
    source .venv/bin/activate
    python scripts/rescore_historical_legs.py
"""
import sys
import os

# Ensure project root is on the path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src.utils.db import get_conn
from src.engine.coverage import calculate_coverage


BATCH_SIZE = 50  # commit and print progress every N legs


def rescore_all_legs():
    conn = get_conn()
    cur = conn.cursor()

    print("Fetching all resolved legs (including those without opposing_pitcher_id)...")
    cur.execute("""
        SELECT id, player_id, stat, line, opposing_pitcher_id,
               run_date, odd_id,
               coverage_pct AS old_coverage,
               COALESCE(direction, 'over') AS direction
        FROM mlb_scored_legs
        WHERE result IS NOT NULL
          AND player_id IS NOT NULL
        ORDER BY run_date, id
    """)
    legs = cur.fetchall()
    total = len(legs)
    print(f"Found {total} resolved legs to rescore\n")

    rescored = 0
    failed = 0
    skipped = 0

    for i, leg in enumerate(legs, 1):
        leg_id   = leg["id"]
        stat     = leg["stat"]
        line     = float(leg["line"])
        run_date = leg["run_date"]
        old_cov  = leg["old_coverage"]
        raw_odd_id = leg.get("odd_id")

        # IDs are stored as TEXT in the DB; pitcher_id may be NULL
        try:
            player_id = int(leg["player_id"])
        except (TypeError, ValueError) as e:
            failed += 1
            print(f"  ERROR leg {leg_id}: bad player_id ({e})")
            continue

        pitcher_id_raw = leg.get("opposing_pitcher_id")
        try:
            pitcher_id = int(pitcher_id_raw) if pitcher_id_raw else None
        except (TypeError, ValueError):
            pitcher_id = None

        season = int(run_date.split("-")[0])
        direction = leg.get("direction", "over")

        try:
            result = calculate_coverage(
                player_id=player_id,
                prop_type=stat,
                line=line,
                opposing_pitcher_id=pitcher_id,
                season=season,
                direction=direction,
            )

            if result is None:
                skipped += 1
                continue

            # Best available coverage signal (0-100 scale)
            new_coverage_pct = result.get("coverage_vs_hand") or result.get("coverage_overall") or 0.0
            new_p_over       = new_coverage_pct / 100.0

            # Update all coverage columns in mlb_scored_legs
            cur.execute(
                """
                UPDATE mlb_scored_legs
                SET coverage_pct       = %s,
                    p_over             = %s,
                    coverage_overall   = %s,
                    coverage_vs_hand   = %s,
                    coverage_recent_10 = %s,
                    coverage_recent_5  = %s
                WHERE id = %s
                """,
                (
                    new_coverage_pct,
                    new_p_over,
                    result.get("coverage_overall"),
                    result.get("coverage_vs_hand"),
                    result.get("coverage_recent_10"),
                    result.get("coverage_recent_5"),
                    leg_id,
                ),
            )

            # Also update mlb_training_data.coverage_pct for this leg.
            # Training rows use odd_id format: "{run_date}|{raw_odd_id}"
            if raw_odd_id:
                training_odd_id = f"{run_date}|{raw_odd_id}"
                cur.execute(
                    """
                    UPDATE mlb_training_data
                    SET coverage_pct = %s
                    WHERE odd_id = %s
                    """,
                    (new_coverage_pct, training_odd_id),
                )

            rescored += 1

        except Exception as e:
            failed += 1
            print(f"  ERROR leg {leg_id} (player={player_id}, stat={stat}): {e}")
            continue

        if i % BATCH_SIZE == 0:
            conn.commit()
            print(f"  [{i:>4}/{total}] rescored={rescored}  skipped={skipped}  failed={failed}")

    # Final commit for remaining rows
    conn.commit()
    cur.close()
    conn.close()

    print(f"\n{'='*60}")
    print(f"RESCORING COMPLETE")
    print(f"{'='*60}")
    print(f"Total legs:  {total}")
    print(f"Rescored:    {rescored}")
    print(f"Skipped:     {skipped}  (insufficient game-log data)")
    print(f"Failed:      {failed}  (API or ID errors)")
    print(f"\nNext steps:")
    print(f"  1. Verify with SQL query below")
    print(f"  2. Retrain ML model: python scripts/train_ml_model.py")
    print(f"\nValidation query:")
    print(f"""
  -- Trea Turner hits_under sanity check (should be ~20-25%, not 81%)
  SELECT player_name, stat, direction, line,
         coverage_pct, coverage_overall, coverage_vs_hand,
         coverage_recent_10
  FROM mlb_scored_legs
  WHERE player_name ILIKE '%turner%'
    AND stat = 'hits'
    AND direction = 'under'
  ORDER BY run_date DESC
  LIMIT 10;

  -- Direction symmetry check (over + under should sum to ~100)
  SELECT stat, direction,
         ROUND(AVG(coverage_overall)::numeric, 1) AS avg_coverage_overall,
         COUNT(*) AS legs
  FROM mlb_scored_legs
  WHERE stat IN ('hits', 'totalBases', 'strikeouts')
    AND coverage_overall IS NOT NULL
  GROUP BY stat, direction
  ORDER BY stat, direction;
""")


if __name__ == "__main__":
    rescore_all_legs()
