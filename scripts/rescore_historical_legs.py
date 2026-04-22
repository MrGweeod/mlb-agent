#!/usr/bin/env python3
"""
Rescore historical legs with the new split ratio coverage model.

Fetches all resolved legs (result IS NOT NULL) where player_id and
opposing_pitcher_id are populated, then recalculates coverage_pct using
the current calculate_coverage() logic.

The mlb_stats in-memory cache deduplicates API calls across legs for the
same player, so the actual network traffic is proportional to unique
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

    print("Fetching resolved legs...")
    cur.execute("""
        SELECT id, player_id, stat, line, opposing_pitcher_id,
               run_date, coverage_pct AS old_coverage
        FROM mlb_scored_legs
        WHERE result IS NOT NULL
          AND player_id IS NOT NULL
          AND opposing_pitcher_id IS NOT NULL
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

        # IDs are stored as TEXT in the DB
        try:
            player_id  = int(leg["player_id"])
            pitcher_id = int(leg["opposing_pitcher_id"])
        except (TypeError, ValueError) as e:
            failed += 1
            print(f"  ERROR leg {leg_id}: bad ID ({e})")
            continue

        season = int(run_date.split("-")[0])

        try:
            result = calculate_coverage(
                player_id=player_id,
                prop_type=stat,
                line=line,
                opposing_pitcher_id=pitcher_id,
                season=season,
            )

            if result is None:
                skipped += 1
                continue

            # coverage_pct is stored on 0-100 scale; coverage_rate is 0-1
            new_coverage_pct = result["coverage_rate"] * 100
            new_p_over       = result["coverage_rate"]

            cur.execute(
                """
                UPDATE mlb_scored_legs
                SET coverage_pct = %s,
                    p_over       = %s
                WHERE id = %s
                """,
                (new_coverage_pct, new_p_over, leg_id),
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
    print(f"\nRefresh your dashboard to see updated calibration data.")


if __name__ == "__main__":
    rescore_all_legs()
