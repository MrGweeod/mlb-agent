"""
Backfill mlb_scored_legs_enriched.result by syncing from mlb_scored_legs.
Runs a direct UPDATE for each date — bypasses the parlay leg pending filter.
"""
from datetime import date, timedelta
from src.utils.db import get_conn

start = date(2026, 6, 4)
end = date(2026, 6, 14)

d = start
while d <= end:
    run_date = str(d)
    print(f"\n=== Backfilling {run_date} ===")
    conn = get_conn()
    cur = conn.cursor()
    cur.execute(
        """
        UPDATE mlb_scored_legs_enriched e
        SET result = s.result,
            actual_value = s.actual_value
        FROM mlb_scored_legs s
        WHERE e.player_name = s.player_name
          AND e.stat = s.stat
          AND e.run_date = s.run_date
          AND e.run_date = %s
          AND s.result IS NOT NULL
          AND s.result != 'pending'
          AND e.result IS NULL
        """,
        (run_date,),
    )
    updated = cur.rowcount
    conn.commit()
    cur.close()
    conn.close()
    print(f"  Updated {updated} rows")
    d += timedelta(days=1)
