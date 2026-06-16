"""
Backfill May 18, 2026 parlay resolutions.

Two bugs were fixed in parlay_outcome_resolver.py:
  1. Void legs weren't being persisted to mlb_parlay_legs_v2.outcome
  2. Pitcher strikeout props extracted from wrong boxscore path

This caused 14 of 25 May 18 parlays to be incorrectly marked 'void'.
This script re-resolves all 25 parlays using the fixed logic.

Usage:
    python scripts/backfill_may_18_parlays.py --dry-run   # preview only
    python scripts/backfill_may_18_parlays.py             # commit changes
"""
import argparse
import sys
from datetime import datetime, timezone

from src.utils.db import get_conn
from src.tracker.parlay_outcome_resolver import resolve_parlay_recommendations_v2

TARGET_DATE = "2026-05-18"


def get_parlay_states(date: str) -> list[dict]:
    """Fetch current parlay + leg outcomes for date."""
    conn = get_conn()
    cur = conn.cursor()
    cur.execute(
        """
        SELECT id, rank, outcome
        FROM mlb_parlay_recommendations_v2
        WHERE run_date = %s
        ORDER BY id
        """,
        (date,),
    )
    parlays = [dict(r) for r in cur.fetchall()]

    if parlays:
        parlay_ids = [p["id"] for p in parlays]
        cur.execute(
            """
            SELECT id, parlay_id, outcome, result_value
            FROM mlb_parlay_legs_v2
            WHERE parlay_id = ANY(%s)
            ORDER BY parlay_id, id
            """,
            (parlay_ids,),
        )
        legs_by_parlay: dict[int, list] = {}
        for leg in cur.fetchall():
            legs_by_parlay.setdefault(leg["parlay_id"], []).append(dict(leg))
        for p in parlays:
            p["legs"] = legs_by_parlay.get(p["id"], [])

    cur.close()
    conn.close()
    return parlays


def reset_to_pending(date: str) -> None:
    """Reset all parlay legs and parlay outcomes for date back to 'pending'."""
    conn = get_conn()
    cur = conn.cursor()
    cur.execute(
        """
        UPDATE mlb_parlay_legs_v2 l
        SET outcome = 'pending', result_value = NULL
        FROM mlb_parlay_recommendations_v2 p
        WHERE l.parlay_id = p.id AND p.run_date = %s
        """,
        (date,),
    )
    leg_rows = cur.rowcount
    cur.execute(
        """
        UPDATE mlb_parlay_recommendations_v2
        SET outcome = 'pending', resolved_at = NULL
        WHERE run_date = %s
        """,
        (date,),
    )
    parlay_rows = cur.rowcount
    conn.commit()
    cur.close()
    conn.close()
    print(f"  Reset {parlay_rows} parlays and {leg_rows} legs to 'pending'")


def restore_states(states: list[dict]) -> None:
    """Restore parlay + leg outcomes to saved values (dry-run cleanup)."""
    conn = get_conn()
    cur = conn.cursor()
    for state in states:
        cur.execute(
            "UPDATE mlb_parlay_recommendations_v2 SET outcome = %s, resolved_at = NULL WHERE id = %s",
            (state["outcome"], state["id"]),
        )
        for leg in state["legs"]:
            cur.execute(
                "UPDATE mlb_parlay_legs_v2 SET outcome = %s, result_value = %s WHERE id = %s",
                (leg["outcome"], leg["result_value"], leg["id"]),
            )
    conn.commit()
    cur.close()
    conn.close()


def main() -> None:
    parser = argparse.ArgumentParser(description="Backfill May 18 parlay resolutions")
    parser.add_argument("--dry-run", action="store_true", help="Preview changes without committing")
    args = parser.parse_args()

    dry = args.dry_run
    prefix = "[DRY RUN] " if dry else ""
    print(f"{prefix}Backfilling {TARGET_DATE} parlays...")

    before_states = get_parlay_states(TARGET_DATE)
    if not before_states:
        print(f"No parlays found for {TARGET_DATE}. Nothing to do.")
        sys.exit(0)

    print(f"Found {len(before_states)} parlays to re-resolve\n")

    # Reset to pending so resolve_parlay_recommendations_v2 will pick them up
    reset_to_pending(TARGET_DATE)

    # Re-resolve using the fixed logic (verbose=False to keep output clean)
    resolve_parlay_recommendations_v2(TARGET_DATE, verbose=False)

    after_states = get_parlay_states(TARGET_DATE)
    after_map = {s["id"]: s for s in after_states}

    changed = 0
    unchanged = 0
    errors = 0

    for before in before_states:
        pid = before["id"]
        after = after_map.get(pid)
        if not after:
            print(f"Parlay {pid}: ERROR - not found after resolution")
            errors += 1
            continue

        old_out = before["outcome"]
        new_out = after["outcome"]

        if old_out != new_out:
            void_legs = sum(1 for l in before["legs"] if l["outcome"] == "void")
            lost_legs = sum(1 for l in before["legs"] if l["outcome"] == "lost")
            print(
                f"Parlay {pid}: {old_out} → {new_out} "
                f"(FIXED - {void_legs} void legs, {lost_legs} lost leg{'s' if lost_legs != 1 else ''})"
            )
            changed += 1
        else:
            print(f"Parlay {pid}: {old_out} → {new_out} (no change)")
            unchanged += 1

    print(f"\nSummary:")
    print(f"- {len(before_states)} parlays processed")
    print(f"- {changed} changed (void → won/lost)")
    print(f"- {unchanged} unchanged")
    print(f"- {errors} errors")

    if dry:
        print(f"\n[DRY RUN] Restoring original outcomes (no changes committed)...")
        restore_states(before_states)
        print("[DRY RUN] Done. Run without --dry-run to apply changes.")
    else:
        print(f"\nBackfill complete. Changes committed to database.")


if __name__ == "__main__":
    main()
