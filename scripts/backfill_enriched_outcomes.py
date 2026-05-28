"""
Backfill enriched parlay outcomes for May 20–27 by syncing from mlb_scored_legs.

Usage:
    python scripts/backfill_enriched_outcomes.py
"""
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src.tracker.outcome_resolver import resolve_enriched_parlays

DATES = [
    "2026-05-20",
    "2026-05-21",
    "2026-05-22",
    "2026-05-23",
    "2026-05-24",
    "2026-05-25",
    "2026-05-26",
    "2026-05-27",
]

totals = {"won": 0, "lost": 0, "void": 0, "total": 0}

for date in DATES:
    print(f"\n{'='*50}")
    print(f"Backfilling {date}...")
    stats = resolve_enriched_parlays(date, verbose=True)
    for k in totals:
        totals[k] += stats.get(k, 0)

print(f"\n{'='*50}")
print(f"BACKFILL COMPLETE: {totals['won']} won, {totals['lost']} lost, "
      f"{totals['void']} void ({totals['total']} legs total)")
