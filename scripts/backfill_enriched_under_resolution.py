"""
backfill_enriched_under_resolution.py

Backfill enriched parlay resolution for June 13–15, targeting under legs
that were previously missed due to the missing direction filter bug.

Usage:
    python scripts/backfill_enriched_under_resolution.py
"""
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src.tracker.outcome_resolver import resolve_enriched_parlays

DATES = ["2026-06-13", "2026-06-14", "2026-06-15"]

for date in DATES:
    print(f"\n{'='*60}")
    print(f"Resolving enriched parlays for {date}...")
    print('='*60)
    result = resolve_enriched_parlays(date, verbose=True)
    print(f"Result: {result}")
