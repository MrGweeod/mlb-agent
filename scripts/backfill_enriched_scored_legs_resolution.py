"""
backfill_enriched_scored_legs_resolution.py

Backfill resolve_all_enriched_legs() for June 4–15, 2026.

Non-parlay legs in mlb_scored_legs_enriched were never resolved because
resolve_enriched_parlays() only covers legs that made it into shadow parlays.
This script fills in results for the remaining ~140 legs/day via the same
box-score path used by resolve_all_legs().

Usage:
    python -m scripts.backfill_enriched_scored_legs_resolution
"""
from __future__ import annotations

from datetime import date, timedelta

from src.tracker.outcome_resolver import resolve_all_enriched_legs

START_DATE = date(2026, 6, 4)
END_DATE   = date(2026, 6, 15)  # inclusive


def main() -> None:
    current = START_DATE
    totals = {"won": 0, "lost": 0, "void": 0, "total": 0}

    while current <= END_DATE:
        run_date = str(current)
        print(f"\n{'=' * 50}")
        print(f"Backfilling enriched legs for {run_date}...")
        stats = resolve_all_enriched_legs(run_date, verbose=True)
        for k in totals:
            totals[k] += stats.get(k, 0)
        current += timedelta(days=1)

    print(f"\n{'=' * 50}")
    print(
        f"Backfill complete ({START_DATE} – {END_DATE}): "
        f"{totals['won']} won, {totals['lost']} lost, {totals['void']} void "
        f"({totals['total']} total)"
    )


if __name__ == "__main__":
    main()
