"""
One-time script to resolve all pending legs from April 22 - May 3, 2026.
These dates predate the automated resolution system (built May 5).
"""
import sys
import traceback

from src.tracker.outcome_resolver import resolve_all_legs, resolve_training_data
from src.tracker.parlay_outcome_resolver import resolve_parlay_recommendations

BACKFILL_DATES = [
    '2026-04-22',
    '2026-04-29',
    '2026-04-30',
    '2026-05-01',
    '2026-05-02',
    '2026-05-03',
]


def backfill_pending_legs():
    print("=" * 60)
    print("BACKFILL: Resolving pending legs from April 22 - May 3")
    print("=" * 60)

    totals = {'dates_processed': 0, 'legs': 0, 'training': 0, 'parlays': 0}

    for date_str in BACKFILL_DATES:
        print(f"\n{'='*60}")
        print(f"Processing: {date_str}")
        print(f"{'='*60}")

        try:
            print(f"\n[1/3] Resolving scored legs for {date_str}...")
            leg_stats = resolve_all_legs(date_str, verbose=True)
            resolved = leg_stats.get('won', 0) + leg_stats.get('lost', 0) + leg_stats.get('void', 0)
            print(f"  Scored legs: {leg_stats.get('won', 0)} won, {leg_stats.get('lost', 0)} lost, {leg_stats.get('void', 0)} void")
            totals['legs'] += resolved

            print(f"\n[2/3] Resolving training data for {date_str}...")
            training_stats = resolve_training_data(date_str, verbose=True)
            tr_resolved = training_stats.get('hit', 0) + training_stats.get('miss', 0) + training_stats.get('void', 0)
            print(f"  Training data: {training_stats.get('hit', 0)} hits, {training_stats.get('miss', 0)} misses, {training_stats.get('void', 0)} void")
            totals['training'] += tr_resolved

            print(f"\n[3/3] Resolving parlays for {date_str}...")
            parlay_stats = resolve_parlay_recommendations(date_str, verbose=True)
            if parlay_stats.get('total', 0) > 0:
                print(f"  Parlays: {parlay_stats.get('won', 0)} won, {parlay_stats.get('lost', 0)} lost, {parlay_stats.get('void', 0)} void")
                totals['parlays'] += parlay_stats.get('total', 0)
            else:
                print(f"  No parlays found for {date_str}")

            totals['dates_processed'] += 1

        except Exception as e:
            print(f"\nERROR processing {date_str}: {e}")
            traceback.print_exc()
            continue

    print(f"\n{'='*60}")
    print("BACKFILL COMPLETE")
    print(f"{'='*60}")
    print(f"Dates processed : {totals['dates_processed']}/{len(BACKFILL_DATES)}")
    print(f"Legs resolved   : {totals['legs']}")
    print(f"Training resolved: {totals['training']}")
    print(f"Parlays resolved : {totals['parlays']}")
    print(f"{'='*60}\n")


if __name__ == '__main__':
    backfill_pending_legs()
