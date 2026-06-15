from datetime import date, timedelta
from src.tracker.outcome_resolver import resolve_enriched_parlays

start = date(2026, 6, 4)
end = date(2026, 6, 14)
d = start
while d <= end:
    print(f"\n=== Backfilling {d} ===")
    resolve_enriched_parlays(str(d), verbose=False)
    d += timedelta(days=1)
