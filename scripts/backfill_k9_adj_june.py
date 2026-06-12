"""
Backfill corrected k9_adj and composite_score for SO over legs in
mlb_scored_legs_enriched, June 5-12 2026.

Corrects the inverted K/9 direction bug: (15.5 - k9_rank) → (k9_rank - 15.5)

Usage:
    source .venv/bin/activate && set -a && source .env && set +a
    python scripts/backfill_k9_adj_june.py --dry-run   # preview
    python scripts/backfill_k9_adj_june.py             # apply
"""

import sys
import os
import argparse

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src.utils.db import get_conn

BACKFILL_START = '2026-06-05'
BACKFILL_END   = '2026-06-12'

def compute_corrected_k9_adj(k9_rank: int) -> float:
    """Corrected formula: rank 1 = elite = penalize SO over."""
    adj = round((k9_rank - 15.5) / 2.9, 1)
    return max(-5.0, min(5.0, adj))

def compute_old_k9_adj(k9_rank: int) -> float:
    """Old (wrong) formula for comparison."""
    adj = round((15.5 - k9_rank) / 2.9, 1)
    return max(-5.0, min(5.0, adj))

def run(dry_run: bool):
    conn = get_conn()
    cur = conn.cursor()

    # Fetch all affected legs
    cur.execute("""
        SELECT run_date, odd_id, player_name, pitcher_k9_rank,
               composite_score
        FROM mlb_scored_legs_enriched
        WHERE stat = 'strikeouts'
          AND direction = 'over'
          AND pitcher_k9_rank IS NOT NULL
          AND run_date >= %s
          AND run_date <= %s
        ORDER BY run_date, player_name
    """, (BACKFILL_START, BACKFILL_END))
    rows = cur.fetchall()

    print(f"Found {len(rows)} SO over legs with k9_rank data in {BACKFILL_START}–{BACKFILL_END}")
    print(f"Mode: {'DRY RUN' if dry_run else 'LIVE'}\n")

    updated = 0
    skipped = 0
    errors = 0

    for row in rows:
        run_date    = row["run_date"]
        odd_id      = row["odd_id"]
        player_name = row["player_name"]
        k9_rank     = row["pitcher_k9_rank"]
        old_score   = row["composite_score"]

        if old_score is None:
            skipped += 1
            continue

        old_formula_adj = compute_old_k9_adj(k9_rank)
        new_k9_adj      = compute_corrected_k9_adj(k9_rank)
        delta           = new_k9_adj - old_formula_adj

        # New score = old score - old adj + new adj, clamped to [5, 95]
        new_score = max(5.0, min(95.0, old_score + delta))

        print(
            f"  {run_date} {player_name:25s} "
            f"k9_rank={k9_rank:3d} "
            f"old_k9_adj={old_formula_adj:+.1f} → new_k9_adj={new_k9_adj:+.1f} "
            f"score: {old_score:.1f} → {new_score:.1f}"
        )

        if not dry_run:
            try:
                cur.execute("""
                    UPDATE mlb_scored_legs_enriched
                    SET composite_score = %s
                    WHERE run_date = %s AND odd_id = %s
                """, (new_score, run_date, odd_id))
                updated += 1
            except Exception as e:
                print(f"    ERROR: {e}")
                errors += 1

    if not dry_run:
        conn.commit()

    cur.close()
    conn.close()

    print(f"\n{'[DRY RUN] Would update' if dry_run else 'Updated'}: {updated if not dry_run else len(rows) - skipped} legs")
    if skipped:
        print(f"Skipped (null composite_score): {skipped}")
    if errors:
        print(f"Errors: {errors}")

if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()
    run(dry_run=args.dry_run)
