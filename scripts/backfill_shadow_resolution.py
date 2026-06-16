"""
backfill_shadow_resolution.py — Sync result/actual_value from mlb_scored_legs
into mlb_scored_legs_enriched using a 1:1 join on player_name, stat, direction,
run_date, line.

Default: dry-run (no writes). Pass --apply to execute updates.

Usage:
    python scripts/backfill_shadow_resolution.py           # dry-run
    python scripts/backfill_shadow_resolution.py --apply   # execute
"""
from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from src.utils.db import get_conn


def run(apply: bool = False) -> None:
    conn = get_conn()
    cur = conn.cursor()

    # Rows in enriched that have a resolved production match
    cur.execute(
        """
        SELECT
            e.id,
            e.run_date,
            e.player_name,
            e.stat,
            e.direction,
            e.line,
            s.result,
            s.actual_value
        FROM mlb_scored_legs_enriched e
        JOIN mlb_scored_legs s
          ON s.player_name = e.player_name
         AND s.stat        = e.stat
         AND s.direction   = e.direction
         AND s.run_date    = e.run_date
         AND s.line        = e.line
        WHERE e.result IS NULL
          AND s.result IS NOT NULL
        """
    )
    to_update = [dict(r) for r in cur.fetchall()]

    # Enriched rows already resolved (skipped)
    cur.execute(
        "SELECT COUNT(*) AS cnt FROM mlb_scored_legs_enriched WHERE result IS NOT NULL"
    )
    already_resolved: int = cur.fetchone()["cnt"]

    # Enriched rows still NULL with no production match at all
    cur.execute(
        """
        SELECT COUNT(*) AS cnt
        FROM mlb_scored_legs_enriched e
        WHERE e.result IS NULL
          AND NOT EXISTS (
              SELECT 1
              FROM mlb_scored_legs s
              WHERE s.player_name = e.player_name
                AND s.stat        = e.stat
                AND s.direction   = e.direction
                AND s.run_date    = e.run_date
                AND s.line        = e.line
          )
        """
    )
    no_match: int = cur.fetchone()["cnt"]

    cur.close()

    mode = "DRY RUN" if not apply else "APPLY"
    print(f"\n[{mode}] Shadow resolution backfill (mlb_scored_legs → mlb_scored_legs_enriched)")
    print(f"  Rows to update:       {len(to_update)}")
    print(f"  Already resolved:     {already_resolved}  (skipped)")
    print(f"  No production match:  {no_match}")

    if not apply:
        print("\nDry run complete. Pass --apply to execute updates.")
        conn.close()
        return

    cur = conn.cursor()
    updated = 0
    for row in to_update:
        cur.execute(
            """
            UPDATE mlb_scored_legs_enriched
               SET result       = %s,
                   actual_value = %s
             WHERE id = %s
            """,
            (row["result"], row["actual_value"], row["id"]),
        )
        updated += 1

    conn.commit()
    cur.close()
    conn.close()

    print(f"\nApplied: {updated} row(s) updated.")


if __name__ == "__main__":
    apply = "--apply" in sys.argv
    run(apply=apply)
