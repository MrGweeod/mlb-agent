"""
Migrate v1 parlay data from mlb_parlay_recommendations to v2 normalized schema.

V1 Schema (mlb_parlay_recommendations):
    recommendation_date DATE
    pipeline_run_time   TEXT
    rank                INTEGER
    leg_odd_ids         TEXT[]   -- odd_ids referencing mlb_scored_legs
    combined_odds       INTEGER
    win_probability     REAL
    edge_pct            REAL
    bet_status          TEXT     -- 'won', 'lost', 'void', 'pending'
    analysis            TEXT

V2 Schema:
    mlb_parlay_recommendations_v2  -- parlay headers
    mlb_parlay_legs_v2             -- individual legs (one row per leg)

Usage:
    cd /home/gweeod/mlb-agent
    source venv/bin/activate
    python scripts/migrate_v1_to_v2.py
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src.utils.db import get_conn
from datetime import datetime, timezone


def now_utc() -> str:
    return datetime.now(timezone.utc).isoformat()


def migrate_v1_parlays() -> tuple[int, int]:
    """
    Migrate all v1 parlays that don't already exist in v2 (checked by
    run_date + rank + source='v1_migration').

    Returns (migrated_count, error_count).
    """
    conn = get_conn()
    cur = conn.cursor()

    # Fetch all v1 parlays
    cur.execute(
        """
        SELECT id, recommendation_date::text AS run_date, pipeline_run_time,
               rank, leg_odd_ids, combined_odds, win_probability, edge_pct, bet_status
        FROM mlb_parlay_recommendations
        ORDER BY recommendation_date ASC, rank ASC
        """
    )
    v1_parlays = [dict(r) for r in cur.fetchall()]
    print(f"Found {len(v1_parlays)} v1 parlays to evaluate")

    if not v1_parlays:
        cur.close()
        conn.close()
        return 0, 0

    # Fetch all odd_ids referenced by v1 parlays in one batch
    all_odd_ids = list({oid for p in v1_parlays for oid in (p["leg_odd_ids"] or [])})
    legs_by_oid: dict[str, dict] = {}
    if all_odd_ids:
        cur.execute(
            """
            SELECT odd_id, player_id, player_name, team, stat, line,
                   direction, odds, coverage_pct, ev_per_unit,
                   composite_score, opponent_adjustment, game_pk,
                   opposing_pitcher_id
            FROM mlb_scored_legs
            WHERE odd_id = ANY(%s)
            """,
            (all_odd_ids,),
        )
        legs_by_oid = {row["odd_id"]: dict(row) for row in cur.fetchall()}
    print(f"  Hydrated {len(legs_by_oid)} legs from mlb_scored_legs")

    migrated_count = 0
    skipped_count = 0
    error_count = 0

    for v1 in v1_parlays:
        run_date = v1["run_date"]
        rank = v1["rank"]
        try:
            # Check if already migrated
            cur.execute(
                """
                SELECT id FROM mlb_parlay_recommendations_v2
                WHERE run_date = %s AND rank = %s AND source = 'v1_migration'
                LIMIT 1
                """,
                (run_date, rank),
            )
            if cur.fetchone():
                skipped_count += 1
                continue

            # Hydrate legs for this parlay
            odd_ids = v1["leg_odd_ids"] or []
            legs = [legs_by_oid[oid] for oid in odd_ids if oid in legs_by_oid]
            coverages = [l["coverage_pct"] for l in legs if l.get("coverage_pct") is not None]
            avg_coverage = round(sum(coverages) / len(coverages), 3) if coverages else None

            # Map bet_status → outcome (same values, just different column names)
            outcome = v1.get("bet_status") or "pending"

            # Insert v2 parlay header
            batch_id = f"v1_{run_date}_{rank}"
            cur.execute(
                """
                INSERT INTO mlb_parlay_recommendations_v2
                    (run_date, rank, total_odds, avg_coverage, avg_ev, num_legs,
                     outcome, source, batch_id, edge_percent)
                VALUES (%s, %s, %s, %s, NULL, %s, %s, 'v1_migration', %s, %s)
                RETURNING id
                """,
                (
                    run_date,
                    rank,
                    str(v1.get("combined_odds", "")),
                    avg_coverage,
                    len(legs),
                    outcome,
                    batch_id,
                    v1.get("edge_pct"),
                ),
            )
            parlay_id = cur.fetchone()["id"]

            # Insert v2 legs
            for position, leg in enumerate(legs, start=1):
                cur.execute(
                    """
                    INSERT INTO mlb_parlay_legs_v2
                        (parlay_id, player_id, player_name, team, stat, line,
                         direction, odds, composite_score, opponent_adjustment,
                         coverage, ev, game_id, opposing_pitcher_id,
                         opposing_pitcher_name, outcome)
                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, NULL, %s)
                    """,
                    (
                        parlay_id,
                        leg.get("player_id"),
                        leg.get("player_name"),
                        leg.get("team"),
                        leg.get("stat"),
                        leg.get("line"),
                        leg.get("direction", "over"),
                        leg.get("odds"),
                        leg.get("composite_score"),
                        leg.get("opponent_adjustment"),
                        leg.get("coverage_pct"),
                        leg.get("ev_per_unit"),
                        leg.get("game_pk"),
                        leg.get("opposing_pitcher_id"),
                        outcome,
                    ),
                )

            conn.commit()
            migrated_count += 1
            print(
                f"  ✅ Migrated parlay {v1['id']} "
                f"(run_date={run_date}, rank={rank}, {len(legs)} legs)"
            )

        except Exception as e:
            conn.rollback()
            error_count += 1
            print(f"  ❌ Error migrating parlay {v1['id']} (run_date={run_date}, rank={rank}): {e}")

    cur.close()
    conn.close()

    print(
        f"\nMigration complete:\n"
        f"  ✅ Migrated: {migrated_count}\n"
        f"  ⏭  Skipped (already in v2): {skipped_count}\n"
        f"  ❌ Errors:  {error_count}"
    )
    return migrated_count, error_count


if __name__ == "__main__":
    _, errors = migrate_v1_parlays()
    sys.exit(0 if errors == 0 else 1)
