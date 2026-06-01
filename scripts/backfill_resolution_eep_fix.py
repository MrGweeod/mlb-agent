"""
backfill_resolution_eep_fix.py

Re-resolve parlay outcomes for May 29 – June 1 that were incorrectly voided by
the Early Exit Protection (EEP) false-void bug.

The bug: batting.get("plateAppearances", 0) defaulted to 0 when boxscore_data()
returned an empty stats dict, triggering EEP for every batter leg.

This script:
  1. Prints a before-summary of outcome counts per date.
  2. Resets affected parlays (outcome=void) and their EEP-voided legs back to pending.
  3. Re-runs resolve_parlay_recommendations_v2() for each date.
  4. Prints an after-summary.

Usage:
    python -m scripts.backfill_resolution_eep_fix           # live run
    python -m scripts.backfill_resolution_eep_fix --dry-run # inspect without DB changes
"""
from __future__ import annotations

import argparse
import sys

AFFECTED_DATES = ["2026-05-29", "2026-05-30", "2026-05-31", "2026-06-01"]


def get_outcome_summary(cur) -> dict[str, dict[str, int]]:
    """Return {date: {outcome: count}} for AFFECTED_DATES."""
    cur.execute(
        """
        SELECT run_date::text, outcome, COUNT(*) AS cnt
        FROM mlb_parlay_recommendations_v2
        WHERE run_date BETWEEN %s AND %s
        GROUP BY run_date, outcome
        ORDER BY run_date, outcome
        """,
        (AFFECTED_DATES[0], AFFECTED_DATES[-1]),
    )
    summary: dict[str, dict[str, int]] = {}
    for row in cur.fetchall():
        summary.setdefault(row["run_date"], {})[row["outcome"]] = row["cnt"]
    return summary


def print_summary(label: str, summary: dict[str, dict[str, int]]) -> None:
    print(f"\n{'='*55}")
    print(f"  {label}")
    print(f"{'='*55}")
    for date in AFFECTED_DATES:
        counts = summary.get(date, {})
        if not counts:
            print(f"  {date}: (no rows)")
            continue
        parts = "  ".join(f"{o}={c}" for o, c in sorted(counts.items()))
        print(f"  {date}: {parts}")
    print(f"{'='*55}")


def count_eep_legs(cur) -> int:
    cur.execute(
        """
        SELECT COUNT(*) AS cnt
        FROM mlb_parlay_legs_v2 l
        JOIN mlb_parlay_recommendations_v2 p ON p.id = l.parlay_id
        WHERE p.run_date BETWEEN %s AND %s
          AND l.void_reason = 'early_exit_protection'
        """,
        (AFFECTED_DATES[0], AFFECTED_DATES[-1]),
    )
    return cur.fetchone()["cnt"]


def run(dry_run: bool) -> None:
    from src.utils.db import get_conn
    from src.tracker.parlay_outcome_resolver import resolve_parlay_recommendations_v2

    conn = get_conn()
    cur = conn.cursor()

    # ── Before summary ────────────────────────────────────────────────────────
    before = get_outcome_summary(cur)
    eep_legs_before = count_eep_legs(cur)
    print_summary("BEFORE", before)
    print(f"\n  EEP-voided legs in range: {eep_legs_before}")

    if dry_run:
        print("\n[DRY RUN] The following SQL would be executed:\n")
        print(
            "  -- Reset void parlays to pending\n"
            "  UPDATE mlb_parlay_recommendations_v2\n"
            "  SET outcome = 'pending', resolved_at = NULL\n"
            f"  WHERE run_date BETWEEN '{AFFECTED_DATES[0]}' AND '{AFFECTED_DATES[-1]}'\n"
            "    AND outcome = 'void';\n"
        )
        print(
            "  -- Reset EEP-voided legs to pending\n"
            "  UPDATE mlb_parlay_legs_v2\n"
            "  SET outcome = 'pending', void_reason = NULL, result_value = NULL\n"
            "  WHERE parlay_id IN (\n"
            "      SELECT id FROM mlb_parlay_recommendations_v2\n"
            f"      WHERE run_date BETWEEN '{AFFECTED_DATES[0]}' AND '{AFFECTED_DATES[-1]}'\n"
            "  )\n"
            "    AND void_reason = 'early_exit_protection';\n"
        )
        print(f"\n[DRY RUN] Would then call resolve_parlay_recommendations_v2() for:")
        for d in AFFECTED_DATES:
            print(f"  {d}")
        cur.close()
        conn.close()
        print("\n[DRY RUN] No changes made. Re-run without --dry-run to apply.")
        return

    # ── Reset parlays ─────────────────────────────────────────────────────────
    print("\n[BACKFILL] Resetting void parlays → pending...")
    cur.execute(
        """
        UPDATE mlb_parlay_recommendations_v2
        SET outcome = 'pending', resolved_at = NULL
        WHERE run_date BETWEEN %s AND %s
          AND outcome = 'void'
        """,
        (AFFECTED_DATES[0], AFFECTED_DATES[-1]),
    )
    parlays_reset = cur.rowcount
    conn.commit()
    print(f"  {parlays_reset} parlay row(s) reset to pending.")

    # ── Reset EEP legs ────────────────────────────────────────────────────────
    print("[BACKFILL] Resetting EEP-voided legs → pending...")
    cur.execute(
        """
        UPDATE mlb_parlay_legs_v2
        SET outcome = 'pending', void_reason = NULL, result_value = NULL
        WHERE parlay_id IN (
            SELECT id FROM mlb_parlay_recommendations_v2
            WHERE run_date BETWEEN %s AND %s
        )
          AND void_reason = 'early_exit_protection'
        """,
        (AFFECTED_DATES[0], AFFECTED_DATES[-1]),
    )
    legs_reset = cur.rowcount
    conn.commit()
    print(f"  {legs_reset} leg row(s) reset to pending.")

    cur.close()
    conn.close()

    # ── Re-resolve each date ──────────────────────────────────────────────────
    for date in AFFECTED_DATES:
        print(f"\n{'='*55}")
        print(f"  Re-resolving {date}")
        print(f"{'='*55}")
        resolve_parlay_recommendations_v2(date, verbose=True)

    # ── After summary ─────────────────────────────────────────────────────────
    conn2 = get_conn()
    cur2 = conn2.cursor()
    after = get_outcome_summary(cur2)
    eep_legs_after = count_eep_legs(cur2)
    cur2.close()
    conn2.close()

    print_summary("AFTER", after)
    print(f"\n  EEP-voided legs remaining: {eep_legs_after}")
    print(
        "\n[BACKFILL] Done. Review the AFTER summary above.\n"
        "  Expected: mix of won/lost/void per date, not all-void.\n"
        "  Any remaining void legs with void_reason='early_exit_protection'\n"
        "  are genuine early exits (pitcher removed after 1 batter, etc.)."
    )


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Re-resolve EEP false-void parlays.")
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Print what would be reset without making any DB changes.",
    )
    args = parser.parse_args()
    run(dry_run=args.dry_run)
