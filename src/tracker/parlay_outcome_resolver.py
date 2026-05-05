"""
parlay_outcome_resolver.py — Resolve daily parlay recommendation outcomes.

Depends on mlb_scored_legs already having result populated for the target date
(run resolve_all_legs() first via outcome_resolver.py).

Logic:
  - If ANY leg = 'void'  → parlay = 'void'
  - If ANY leg = 'lost'  → parlay = 'lost'
  - If ALL legs = 'won'  → parlay = 'won'
  - If any leg still NULL → skip (not all legs resolved yet)

Run standalone:
    python -m src.tracker.parlay_outcome_resolver 2026-05-04
"""
from __future__ import annotations

import sys
from datetime import datetime, timezone

from src.utils.db import get_conn


def resolve_parlay_recommendations(date: str, verbose: bool = True) -> dict:
    """
    Resolve all pending parlay recommendations for *date*.

    Looks up each recommendation's leg results in mlb_scored_legs, determines
    the parlay outcome, and updates mlb_parlay_recommendations.bet_status and
    resolved_at.

    Args:
        date: 'YYYY-MM-DD' matching mlb_parlay_recommendations.recommendation_date
              AND mlb_scored_legs.run_date.
        verbose: Print progress to stdout.

    Returns:
        {'won': int, 'lost': int, 'void': int, 'skipped': int, 'total': int}
    """
    conn = get_conn()
    cur  = conn.cursor()
    cur.execute(
        """
        SELECT id, rank, leg_odd_ids
        FROM mlb_parlay_recommendations
        WHERE recommendation_date = %s
          AND bet_status = 'pending'
        ORDER BY rank
        """,
        (date,),
    )
    parlays = [dict(r) for r in cur.fetchall()]
    cur.close()
    conn.close()

    if not parlays:
        if verbose:
            print(f"[PARLAY RESOLVER] No pending parlays for {date}.")
        return {"won": 0, "lost": 0, "void": 0, "skipped": 0, "total": 0}

    if verbose:
        print(f"[PARLAY RESOLVER] Resolving {len(parlays)} parlay(s) for {date}...")

    # Bulk-fetch all relevant leg results in one query
    all_odd_ids = list({oid for p in parlays for oid in p["leg_odd_ids"]})
    conn = get_conn()
    cur  = conn.cursor()
    cur.execute(
        """
        SELECT odd_id, result
        FROM mlb_scored_legs
        WHERE run_date = %s
          AND odd_id = ANY(%s)
        """,
        (date, all_odd_ids),
    )
    leg_results: dict[str, str | None] = {
        row["odd_id"]: row["result"] for row in cur.fetchall()
    }
    cur.close()
    conn.close()

    counts = {"won": 0, "lost": 0, "void": 0, "skipped": 0}
    resolved_at = datetime.now(timezone.utc)

    for parlay in parlays:
        rank     = parlay["rank"]
        odd_ids  = parlay["leg_odd_ids"]
        parlay_id = parlay["id"]

        results = [leg_results.get(oid) for oid in odd_ids]

        # Skip if any leg hasn't been resolved yet
        if any(r is None for r in results):
            unresolved = sum(1 for r in results if r is None)
            if verbose:
                print(f"  Rank {rank}: {unresolved}/{len(results)} leg(s) unresolved → SKIP")
            counts["skipped"] += 1
            continue

        # Determine parlay outcome (conservative: void beats lost beats won)
        if any(r == "void" for r in results):
            outcome = "void"
        elif any(r == "lost" for r in results):
            outcome = "lost"
        else:
            outcome = "won"

        counts[outcome] += 1

        conn = get_conn()
        cur  = conn.cursor()
        cur.execute(
            """
            UPDATE mlb_parlay_recommendations
            SET bet_status = %s, resolved_at = %s
            WHERE id = %s
            """,
            (outcome, resolved_at, parlay_id),
        )
        conn.commit()
        cur.close()
        conn.close()

        if verbose:
            icon = "✓" if outcome == "won" else ("○" if outcome == "void" else "✗")
            leg_summary = ", ".join(str(r) for r in results)
            print(f"  [{icon}] Rank {rank}: [{leg_summary}] → {outcome.upper()}")

    total = sum(counts.values())
    if verbose:
        print(
            f"\n[PARLAY RESOLVER] Complete: "
            f"{counts['won']} won, {counts['lost']} lost, "
            f"{counts['void']} void, {counts['skipped']} skipped "
            f"({total} total)"
        )

    return {**counts, "total": total}


if __name__ == "__main__":
    if len(sys.argv) > 1:
        resolve_parlay_recommendations(sys.argv[1])
    else:
        from datetime import date, timedelta
        yesterday = str(date.today() - timedelta(days=1))
        resolve_parlay_recommendations(yesterday)
