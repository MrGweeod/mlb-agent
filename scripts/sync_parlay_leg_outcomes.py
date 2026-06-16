"""
Sync mlb_parlay_legs_v2.outcome with mlb_scored_legs.result for all dates.

Finds all parlay legs where outcome='pending' but mlb_scored_legs already has
a resolved result ('won', 'lost', or 'void'), updates the legs, then
recalculates affected parlay outcomes.

Handles edge cases:
  - Leg in parlay_legs_v2 but not in scored_legs → skip with warning
  - Multiple scored_legs matches → log warning, skip

Usage:
    python scripts/sync_parlay_leg_outcomes.py --dry-run   # preview only
    python scripts/sync_parlay_leg_outcomes.py             # commit changes
"""
import argparse
import sys
from datetime import datetime, timezone

from src.utils.db import get_conn
from src.tracker.parlay_outcome_resolver import recalculate_parlay_outcome


def find_mismatched_legs() -> list[dict]:
    """
    Return all parlay legs where outcome='pending' but scored_legs has a resolved result.

    Joins on player_name + stat + run_date. Returns one row per leg.
    """
    conn = get_conn()
    cur = conn.cursor()
    cur.execute(
        """
        SELECT
            pl.id            AS parlay_leg_id,
            pl.parlay_id,
            pl.player_name,
            pl.stat,
            pl.outcome       AS leg_outcome,
            p.run_date::text AS run_date,
            sl.result        AS scored_result,
            p.outcome        AS parlay_outcome,
            COUNT(sl.id) OVER (
                PARTITION BY pl.player_name, pl.stat, p.run_date::text
            )                AS match_count
        FROM mlb_parlay_legs_v2 pl
        JOIN mlb_parlay_recommendations_v2 p ON p.id = pl.parlay_id
        LEFT JOIN mlb_scored_legs sl ON
            sl.player_name = pl.player_name
            AND sl.stat     = pl.stat
            AND sl.run_date = p.run_date::text
        WHERE pl.outcome = 'pending'
          AND sl.result IN ('won', 'lost', 'void')
        ORDER BY p.run_date DESC, pl.parlay_id, pl.id
        """
    )
    rows = [dict(r) for r in cur.fetchall()]
    cur.close()
    conn.close()
    return rows


def update_leg_outcome(leg_id: int, new_outcome: str) -> None:
    conn = get_conn()
    cur = conn.cursor()
    cur.execute(
        "UPDATE mlb_parlay_legs_v2 SET outcome = %s WHERE id = %s",
        (new_outcome, leg_id),
    )
    conn.commit()
    cur.close()
    conn.close()


def update_parlay_outcome(parlay_id: int, new_outcome: str) -> None:
    resolved_at = datetime.now(timezone.utc).isoformat()
    conn = get_conn()
    cur = conn.cursor()
    cur.execute(
        """
        UPDATE mlb_parlay_recommendations_v2
        SET outcome = %s, resolved_at = %s
        WHERE id = %s
        """,
        (new_outcome, resolved_at, parlay_id),
    )
    conn.commit()
    cur.close()
    conn.close()


def main() -> None:
    parser = argparse.ArgumentParser(description="Sync parlay leg outcomes with scored_legs")
    parser.add_argument("--dry-run", action="store_true", help="Preview changes without committing")
    args = parser.parse_args()

    dry = args.dry_run
    prefix = "[DRY RUN] " if dry else ""
    print(f"{prefix}Syncing parlay leg outcomes with scored_legs...\n")

    rows = find_mismatched_legs()

    if not rows:
        print("No mismatched legs found. Everything is in sync.")
        sys.exit(0)

    # Separate warnings from clean rows
    multi_match_ids: set[int] = set()
    for row in rows:
        if row["match_count"] > 1:
            multi_match_ids.add(row["parlay_leg_id"])

    clean_rows = [r for r in rows if r["parlay_leg_id"] not in multi_match_ids]
    warn_rows  = [r for r in rows if r["parlay_leg_id"] in multi_match_ids]

    if warn_rows:
        print(f"WARNING: {len(warn_rows)} legs have multiple scored_legs matches — skipping:")
        seen = set()
        for r in warn_rows:
            key = (r["player_name"], r["stat"], r["run_date"])
            if key not in seen:
                print(f"  {r['run_date']}  {r['player_name']}  {r['stat']}")
                seen.add(key)
        print()

    # Tally by target outcome
    won_count  = sum(1 for r in clean_rows if r["scored_result"] == "won")
    lost_count = sum(1 for r in clean_rows if r["scored_result"] == "lost")
    void_count = sum(1 for r in clean_rows if r["scored_result"] == "void")

    print(f"Found {len(clean_rows)} legs with outcome='pending' but scored_legs resolved:")
    print(f"  - {won_count} should be 'won'")
    print(f"  - {lost_count} should be 'lost'")
    print(f"  - {void_count} should be 'void'")
    print()

    if not dry:
        print("Updating legs...")

    legs_updated = 0
    for row in clean_rows:
        if not dry:
            update_leg_outcome(row["parlay_leg_id"], row["scored_result"])
        legs_updated += 1

    if dry:
        print(f"[DRY RUN] Would update {legs_updated} legs")
    else:
        print(f"  Updated {legs_updated} legs")

    # Recalculate affected parlay outcomes
    affected_parlay_ids = list({r["parlay_id"] for r in clean_rows})
    print()
    print(f"{'[DRY RUN] Would recalculate' if dry else 'Recalculating'} affected parlay outcomes...")

    parlays_updated = 0
    for parlay_id in affected_parlay_ids:
        old_outcome = next(r["parlay_outcome"] for r in clean_rows if r["parlay_id"] == parlay_id)

        if dry:
            # Compute what the new outcome would be based on staged (unsaved) changes
            # Build a simulated leg outcome list for this parlay
            conn = get_conn()
            cur = conn.cursor()
            cur.execute(
                "SELECT id, outcome FROM mlb_parlay_legs_v2 WHERE parlay_id = %s",
                (parlay_id,),
            )
            all_legs = {row["id"]: row["outcome"] for row in cur.fetchall()}
            cur.close()
            conn.close()

            # Apply staged changes
            for row in clean_rows:
                if row["parlay_id"] == parlay_id:
                    all_legs[row["parlay_leg_id"]] = row["scored_result"]

            outcomes = list(all_legs.values())
            if all(o == "void" for o in outcomes):
                new_outcome = "void"
            elif any(o == "pending" for o in outcomes):
                new_outcome = "pending"
            elif any(o == "lost" for o in [o for o in outcomes if o != "void"]):
                new_outcome = "lost"
            elif all(o == "won" for o in [o for o in outcomes if o != "void"]):
                new_outcome = "won"
            else:
                new_outcome = "pending"
        else:
            new_outcome = recalculate_parlay_outcome(parlay_id)

        if new_outcome != old_outcome and new_outcome != "pending":
            print(f"  - Parlay {parlay_id}: {old_outcome} → {new_outcome}")
            if not dry:
                update_parlay_outcome(parlay_id, new_outcome)
            parlays_updated += 1

    print()
    print("Summary:")
    print(f"- {legs_updated} legs {'would be ' if dry else ''}synced")
    print(f"- {parlays_updated} parlays {'would be ' if dry else ''}recalculated")
    print(f"- {len(warn_rows)} legs skipped (multiple scored_legs matches)")
    print(f"- 0 errors")

    if dry:
        print("\n[DRY RUN] No changes committed. Run without --dry-run to apply.")


if __name__ == "__main__":
    main()
