"""
backfill_park_factor_enriched.py

Backfills park_factor on mlb_parlay_legs_enriched for all historical rows
where park_factor is NULL.

Builds a game_pk → park_factor map once upfront (one API call per unique
game, not per leg). Abbreviation mismatches between MLB API and our
ballpark_factors table are handled via ABR_ALIASES.
"""

import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import statsapi
from src.utils.db import get_conn
from src.engine.enriched_scorer import _load_ballpark_factors

# MLB API abbreviation → ballpark_factors table abbreviation
ABR_ALIASES = {
    "AZ":  "ARI",   # Diamondbacks
    "ATH": "OAK",   # Athletics
}

def backfill():
    ballpark_factors = _load_ballpark_factors()
    if not ballpark_factors:
        print("[BACKFILL] No ballpark factors loaded — aborting")
        return
    print(f"[BACKFILL] Loaded {len(ballpark_factors)} ballpark factors")

    conn = get_conn()
    cur = conn.cursor()

    # Fetch all enriched legs missing park_factor
    cur.execute("""
        SELECT le.id, le.game_id
        FROM mlb_parlay_legs_enriched le
        JOIN mlb_parlay_recommendations_enriched re ON re.id = le.parlay_id
        WHERE le.park_factor IS NULL
          AND le.game_id IS NOT NULL
    """)
    rows = cur.fetchall()
    print(f"[BACKFILL] Found {len(rows)} legs with NULL park_factor")

    # Build game_pk → park_factor map — one API call per unique game
    unique_game_pks = {row["game_id"] for row in rows}
    print(f"[BACKFILL] Resolving {len(unique_game_pks)} unique games...")

    game_pk_to_park_factor: dict[int, int] = {}
    for game_pk in unique_game_pks:
        try:
            game_data = statsapi.get("game", {"gamePk": game_pk})
            home_abbr = (
                game_data.get("gameData", {})
                .get("teams", {})
                .get("home", {})
                .get("abbreviation", "")
            )
            # Resolve alias if needed
            home_abbr = ABR_ALIASES.get(home_abbr, home_abbr)
            park_data = ballpark_factors.get(home_abbr)
            if park_data:
                game_pk_to_park_factor[game_pk] = park_data["run_factor"]
            else:
                print(f"  [BACKFILL] No park factor for '{home_abbr}' (game {game_pk})")
        except Exception as e:
            print(f"  [BACKFILL] Error fetching game {game_pk}: {e}")

    print(f"[BACKFILL] Resolved park factors for {len(game_pk_to_park_factor)}/{len(unique_game_pks)} games")

    # Update legs using the pre-built map
    updated = 0
    skipped = 0
    for row in rows:
        park_factor = game_pk_to_park_factor.get(row["game_id"])
        if park_factor is None:
            skipped += 1
            continue
        cur.execute(
            "UPDATE mlb_parlay_legs_enriched SET park_factor = %s WHERE id = %s",
            (park_factor, row["id"]),
        )
        updated += 1

    conn.commit()
    cur.close()
    conn.close()
    print(f"[BACKFILL] Done — updated {updated} rows, skipped {skipped}")

if __name__ == "__main__":
    backfill()
