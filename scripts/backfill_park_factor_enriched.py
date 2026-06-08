"""
backfill_park_factor_enriched.py

Backfills park_factor on mlb_parlay_legs_enriched for all historical rows
where park_factor is NULL.

park_factor is a static lookup by home team — it doesn't change by date,
so this backfill is accurate regardless of when the parlay was generated.

Strategy:
1. Load ballpark_factors from DB (30-row static table)
2. For each parlay leg with park_factor IS NULL, find the home team
   via mlb_parlay_recommendations_enriched → game_id → schedule
3. Update park_factor on the leg row

Run once after deploying Fix 3. Safe to re-run — only touches NULL rows.
"""

import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src.utils.db import get_conn
from src.engine.enriched_scorer import _load_ballpark_factors

def backfill():
    ballpark_factors = _load_ballpark_factors()
    if not ballpark_factors:
        print("[BACKFILL] No ballpark factors loaded — aborting")
        return

    print(f"[BACKFILL] Loaded {len(ballpark_factors)} ballpark factors")

    conn = get_conn()
    cur = conn.cursor()

    # Fetch all enriched legs missing park_factor, with their game_id
    cur.execute("""
        SELECT
            le.id,
            le.game_id,
            le.team,
            re.run_date
        FROM mlb_parlay_legs_enriched le
        JOIN mlb_parlay_recommendations_enriched re ON re.id = le.parlay_id
        WHERE le.park_factor IS NULL
          AND le.game_id IS NOT NULL
        ORDER BY re.run_date DESC
    """)
    rows = cur.fetchall()
    print(f"[BACKFILL] Found {len(rows)} legs with NULL park_factor")

    updated = 0
    skipped = 0

    for row in rows:
        leg_id = row["id"]
        game_id = row["game_id"]
        run_date = str(row["run_date"])

        # Look up home team for this game from the schedule
        try:
            import statsapi
            game_data = statsapi.get("game", {"gamePk": game_id})
            teams = game_data.get("gameData", {}).get("teams", {})
            home_abbr = teams.get("home", {}).get("abbreviation", "")
        except Exception as e:
            print(f"  [BACKFILL] Could not fetch game {game_id}: {e}")
            skipped += 1
            continue

        park_factor = ballpark_factors.get(home_abbr)
        if park_factor is None:
            print(f"  [BACKFILL] No park factor for home team '{home_abbr}' (game {game_id})")
            skipped += 1
            continue

        cur.execute(
            "UPDATE mlb_parlay_legs_enriched SET park_factor = %s WHERE id = %s",
            (park_factor, leg_id),
        )
        updated += 1

    conn.commit()
    cur.close()
    conn.close()
    print(f"[BACKFILL] Done — updated {updated} rows, skipped {skipped}")

if __name__ == "__main__":
    backfill()
