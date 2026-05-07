"""
migrate_parlays.py — Migrate historical parlays from old schema to v2 normalized tables.

Reads all rows from mlb_parlay_recommendations (which stores leg_odd_ids as an array
of odd_ids), hydrates the full leg details from mlb_scored_legs, and inserts into
mlb_parlay_recommendations_v2 + mlb_parlay_legs_v2.

Run after the v2 schema SQL has been executed in Supabase:
    python3 -m src.utils.migrate_parlays
"""
from __future__ import annotations

from src.utils.db import get_conn, now_utc


def migrate_historical_parlays(dry_run: bool = False) -> None:
    """
    Migrate all existing rows from mlb_parlay_recommendations to v2 tables.

    Each row in mlb_parlay_recommendations has a leg_odd_ids array.  The full
    leg detail (player_name, stat, line, etc.) lives in mlb_scored_legs keyed
    by (run_date, odd_id).  This function hydrates those fields and inserts
    the normalized rows.

    Args:
        dry_run: If True, print what would be migrated without writing to DB.
    """
    conn = get_conn()
    cur = conn.cursor()

    # Load all historical parlay recommendations
    cur.execute(
        """
        SELECT id, recommendation_date, rank, leg_odd_ids,
               combined_odds, win_probability, edge_pct, bet_status,
               pipeline_run_time, resolved_at
        FROM mlb_parlay_recommendations
        ORDER BY recommendation_date, rank
        """
    )
    old_parlays = [dict(r) for r in cur.fetchall()]

    if not old_parlays:
        print("[migrate] No historical parlays found in mlb_parlay_recommendations")
        cur.close()
        conn.close()
        return

    # Bulk-load all relevant scored legs in one query
    all_odd_ids = list({oid for p in old_parlays for oid in (p["leg_odd_ids"] or [])})
    if all_odd_ids:
        cur.execute(
            """
            SELECT odd_id, run_date, player_id, player_name, team, stat, line,
                   direction, odds, coverage_pct, ev_per_unit, opponent_adjustment,
                   composite_score, game_pk, opposing_pitcher_id
            FROM mlb_scored_legs
            WHERE odd_id = ANY(%s)
            """,
            (all_odd_ids,),
        )
        legs_by_odd_id = {row["odd_id"]: dict(row) for row in cur.fetchall()}
    else:
        legs_by_odd_id = {}

    cur.close()
    conn.close()

    print(f"[migrate] Found {len(old_parlays)} historical parlay(s) to migrate")
    print(f"[migrate] Hydrated {len(legs_by_odd_id)} unique leg(s) from mlb_scored_legs")

    migrated_count = 0
    skipped_count = 0

    for old_parlay in old_parlays:
        run_date = str(old_parlay["recommendation_date"])
        rank = old_parlay["rank"]
        odd_ids = old_parlay["leg_odd_ids"] or []

        legs = [legs_by_odd_id[oid] for oid in odd_ids if oid in legs_by_odd_id]
        missing = len(odd_ids) - len(legs)
        if missing:
            print(f"  [migrate] {run_date} rank {rank}: {missing}/{len(odd_ids)} leg(s) missing from scored_legs")

        # Map bet_status → outcome
        old_status = old_parlay.get("bet_status") or "pending"
        outcome = old_status if old_status in ("won", "lost", "void", "pending") else "pending"

        coverages = [l["coverage_pct"] for l in legs if l.get("coverage_pct") is not None]
        evs = [l["ev_per_unit"] for l in legs if l.get("ev_per_unit") is not None]
        avg_coverage = round(sum(coverages) / len(coverages), 3) if coverages else None
        avg_ev = round(sum(evs) / len(evs), 4) if evs else None

        batch_id = f"migration_{run_date}"

        if dry_run:
            print(
                f"  [DRY RUN] {run_date} rank {rank}: {len(legs)} legs, "
                f"outcome={outcome}, avg_cov={avg_coverage}"
            )
            migrated_count += 1
            continue

        try:
            conn = get_conn()
            cur = conn.cursor()

            # Insert parlay header
            cur.execute(
                """
                INSERT INTO mlb_parlay_recommendations_v2
                    (run_date, rank, total_odds, avg_coverage, avg_ev, num_legs,
                     outcome, source, batch_id, edge_percent, resolved_at)
                VALUES (%s, %s, %s, %s, %s, %s, %s, 'migrated_historical', %s, %s, %s)
                ON CONFLICT DO NOTHING
                RETURNING id
                """,
                (
                    run_date,
                    rank,
                    old_parlay.get("combined_odds"),
                    avg_coverage,
                    avg_ev,
                    len(legs),
                    outcome,
                    batch_id,
                    old_parlay.get("edge_pct"),
                    str(old_parlay["resolved_at"]) if old_parlay.get("resolved_at") else None,
                ),
            )
            row = cur.fetchone()
            if not row:
                # Already migrated (ON CONFLICT DO NOTHING)
                cur.close()
                conn.close()
                skipped_count += 1
                continue

            parlay_id = row["id"]

            # Insert legs
            for leg in legs:
                cur.execute(
                    """
                    INSERT INTO mlb_parlay_legs_v2
                        (parlay_id, player_id, player_name, team, stat, line,
                         direction, odds, composite_score, opponent_adjustment,
                         coverage, ev, game_id, opposing_pitcher_id, outcome)
                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                    """,
                    (
                        parlay_id,
                        leg.get("player_id"),
                        leg.get("player_name"),
                        leg.get("team"),
                        leg.get("stat"),
                        leg.get("line"),
                        leg.get("direction", "over"),
                        str(leg.get("odds") or ""),
                        leg.get("composite_score"),
                        leg.get("opponent_adjustment"),
                        leg.get("coverage_pct"),
                        leg.get("ev_per_unit"),
                        leg.get("game_pk"),
                        leg.get("opposing_pitcher_id"),
                        outcome,  # inherit parlay outcome — individual leg outcomes not tracked historically
                    ),
                )

            conn.commit()
            cur.close()
            conn.close()
            migrated_count += 1

        except Exception as e:
            print(f"  [migrate] ERROR on {run_date} rank {rank}: {e}")
            continue

    print(
        f"[migrate] Done: {migrated_count} migrated, {skipped_count} already existed"
    )


if __name__ == "__main__":
    import sys
    dry_run = "--dry-run" in sys.argv
    if dry_run:
        print("[migrate] DRY RUN mode — no DB writes")
    migrate_historical_parlays(dry_run=dry_run)
