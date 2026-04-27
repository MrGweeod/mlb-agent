#!/usr/bin/env python3
"""
scripts/training_health_check.py — Automated training data health monitoring.

Checks:
  1. Daily collection volume (last N days) — missing or low-volume days
  2. Unresolved data — game_dates before today with result IS NULL
  3. Feature completeness — coverage_pct, composite_score, opponent_adjustment, trend_score
  4. Overall hit rate — should be 40–55% for a well-calibrated model

Usage:
    python scripts/training_health_check.py           # 7-day window, prints report
    python scripts/training_health_check.py --days 14 # longer window
    python scripts/training_health_check.py --quiet    # summary line only

Exit codes:
    0 — all checks passed
    1 — one or more issues detected

Importable API:
    from scripts.training_health_check import check_training_health
    health = check_training_health(days_back=7)
    # {'healthy': bool, 'issues': [...], 'daily_stats': [...],
    #  'hit_rate': float|None, 'last_check': str}
"""
from __future__ import annotations

import argparse
import os
import sys
from datetime import date, timedelta

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src.utils.db import get_conn, now_utc


_HIT_RATE_LOW  = 40.0   # below this is suspicious (model may be broken)
_HIT_RATE_HIGH = 58.0   # above this is suspicious (likely selection bias)
_MIN_DAILY_PROPS = 50   # flag if a non-weekend day has fewer than this
_FEATURE_MISSING_THRESHOLD = 10.0  # % missing before flagging as an issue


def check_training_health(days_back: int = 7) -> dict:
    """
    Run all training data health checks for the last *days_back* days.

    Returns:
        {
          'healthy':     bool,
          'issues':      list[str],           # human-readable problem descriptions
          'daily_stats': list[tuple],         # (date_str, total, hits, misses, pending)
          'hit_rate':    float | None,        # overall 7-day hit rate (0–100 scale)
          'last_check':  str,                 # ISO UTC timestamp
        }
    """
    issues: list[str] = []
    conn = get_conn()
    cur = conn.cursor()

    today = date.today()
    start_date = today - timedelta(days=days_back)

    # ── CHECK 1: Daily collection volume ──────────────────────────────────────
    cur.execute(
        """
        SELECT
            game_date,
            COUNT(*)                                          AS total,
            COUNT(*) FILTER (WHERE result = 'hit')            AS hits,
            COUNT(*) FILTER (WHERE result = 'miss')           AS misses,
            COUNT(*) FILTER (WHERE result IS NULL)            AS pending
        FROM mlb_training_data
        WHERE game_date >= %s
        GROUP BY game_date
        ORDER BY game_date DESC
        """,
        (str(start_date),),
    )
    daily_rows = cur.fetchall()
    daily_stats = [
        (str(r["game_date"]), r["total"], r["hits"], r["misses"], r["pending"])
        for r in daily_rows
    ]
    # Normalise to strings for comparison (psycopg2 may return datetime.date objects)
    dates_with_data = {str(r["game_date"]) for r in daily_rows}

    # Check for missing dates (excluding today — pipeline may not have run yet)
    missing_dates = []
    for i in range(1, days_back + 1):
        check_date = str(today - timedelta(days=i))
        if check_date not in dates_with_data:
            missing_dates.append(check_date)

    if missing_dates:
        issues.append(
            f"MISSING DATA: No props collected for {len(missing_dates)} day(s): "
            + ", ".join(sorted(missing_dates))
        )

    # Check for low-volume days (exclude today which may still be loading)
    for r in daily_rows:
        if r["game_date"] == str(today):
            continue
        if r["total"] < _MIN_DAILY_PROPS:
            issues.append(
                f"LOW VOLUME: {r['game_date']} has only {r['total']} props "
                f"(expected >={_MIN_DAILY_PROPS})"
            )

    # ── CHECK 2: Unresolved data from past dates ───────────────────────────────
    # 10–15% unresolved is normal (DNP / scratched players left as NULL).
    # Flag only dates where >40% of props are unresolved — that signals the
    # resolver didn't run at all for that date.
    cur.execute(
        """
        SELECT
            game_date,
            COUNT(*) FILTER (WHERE result IS NULL)  AS pending,
            COUNT(*)                                AS total
        FROM mlb_training_data
        WHERE game_date < %s
        GROUP BY game_date
        HAVING COUNT(*) FILTER (WHERE result IS NULL) > 0.40 * COUNT(*)
           AND COUNT(*) >= 20
        ORDER BY game_date
        """,
        (str(today),),
    )
    unresolved_rows = cur.fetchall()
    if unresolved_rows:
        total_unresolved = sum(r["pending"] for r in unresolved_rows)
        dates_str = ", ".join(str(r["game_date"]) for r in unresolved_rows)
        issues.append(
            f"RESOLVER FAILURE: {total_unresolved} props unresolved (>40%) — "
            f"resolver likely did not run for: {dates_str}"
        )

    # ── CHECK 3: Feature completeness for prospective rows ────────────────────
    # Backfill rows (inserted before today) don't have ML features by design.
    # Only rows logged by the live pipeline have coverage_pct / composite_score.
    # We detect "prospective" rows by having composite_score OR coverage_pct set.
    # Check today's rows only — yesterday's backfill rows are expected to lack features.
    cur.execute(
        """
        SELECT
            game_date,
            COUNT(*)                                                              AS total,
            COUNT(*) FILTER (WHERE coverage_pct IS NOT NULL)                     AS has_coverage,
            ROUND(100.0 * COUNT(*) FILTER (WHERE coverage_pct IS NULL)      / COUNT(*), 1) AS missing_coverage,
            ROUND(100.0 * COUNT(*) FILTER (WHERE opponent_adjustment IS NULL) / COUNT(*), 1) AS missing_opponent,
            ROUND(
                100.0 * COUNT(*) FILTER (
                    WHERE composite_score IS NULL
                      AND coverage_pct IS NOT NULL AND coverage_pct >= 60
                ) / NULLIF(COUNT(*) FILTER (WHERE coverage_pct IS NOT NULL AND coverage_pct >= 60), 0),
                1
            )                                                                    AS missing_score_60plus
        FROM mlb_training_data
        WHERE game_date = %s
        GROUP BY game_date
        """,
        (str(today),),
    )
    feature_rows = cur.fetchall()
    for r in feature_rows:
        # Only flag feature gaps on days where prospective logging ran (has_coverage > 0)
        if (r["has_coverage"] or 0) == 0:
            continue
        if r["missing_coverage"] is not None and float(r["missing_coverage"]) > _FEATURE_MISSING_THRESHOLD:
            issues.append(
                f"FEATURE GAP: {r['game_date']} — {r['missing_coverage']}% rows missing coverage_pct"
            )
        if r["missing_opponent"] is not None and float(r["missing_opponent"]) > _FEATURE_MISSING_THRESHOLD:
            issues.append(
                f"FEATURE GAP: {r['game_date']} — {r['missing_opponent']}% rows missing opponent_adjustment"
            )
        if r["missing_score_60plus"] is not None and float(r["missing_score_60plus"]) > _FEATURE_MISSING_THRESHOLD:
            issues.append(
                f"FEATURE GAP: {r['game_date']} — {r['missing_score_60plus']}% of 60%+ coverage rows missing composite_score"
            )

    # ── CHECK 4: Overall hit rate (last N days resolved props) ────────────────
    cur.execute(
        """
        SELECT
            COUNT(*) FILTER (WHERE result = 'hit')  AS hits,
            COUNT(*) FILTER (WHERE result = 'miss') AS misses
        FROM mlb_training_data
        WHERE result IN ('hit', 'miss')
          AND game_date >= %s
        """,
        (str(start_date),),
    )
    rate_row = cur.fetchone()
    hit_rate: float | None = None
    if rate_row:
        h = rate_row["hits"] or 0
        m = rate_row["misses"] or 0
        total_resolved = h + m
        if total_resolved >= 10:
            hit_rate = round(100.0 * h / total_resolved, 1)
            if hit_rate < _HIT_RATE_LOW:
                issues.append(
                    f"HIT RATE LOW: {hit_rate:.1f}% over last {days_back} days "
                    f"(expected {_HIT_RATE_LOW}–{_HIT_RATE_HIGH}%) — "
                    f"model may be selecting poorly"
                )
            elif hit_rate > _HIT_RATE_HIGH:
                issues.append(
                    f"HIT RATE HIGH: {hit_rate:.1f}% over last {days_back} days "
                    f"(expected {_HIT_RATE_LOW}–{_HIT_RATE_HIGH}%) — "
                    f"check for selection bias or resolver bugs"
                )

    cur.close()
    conn.close()

    return {
        "healthy":     len(issues) == 0,
        "issues":      issues,
        "daily_stats": daily_stats,
        "hit_rate":    hit_rate,
        "last_check":  now_utc(),
    }


def print_report(health: dict, days_back: int) -> None:
    """Print a human-readable health report to stdout."""
    print(f"\n{'='*60}")
    print(f"  TRAINING DATA HEALTH CHECK  (last {days_back} days)")
    print(f"  {health['last_check'][:19]} UTC")
    print(f"{'='*60}")

    if health["healthy"]:
        print("  Status: HEALTHY")
    else:
        print(f"  Status: {len(health['issues'])} ISSUE(S) DETECTED")

    if health["hit_rate"] is not None:
        print(f"  Hit rate ({days_back}d): {health['hit_rate']:.1f}%")

    if health["daily_stats"]:
        print(f"\n  Daily collection (last {days_back} days):")
        for game_date, total, hits, misses, pending in health["daily_stats"]:
            resolved = hits + misses
            pend_str = f"  {pending} pending" if pending else ""
            print(f"    {game_date}: {total} props  ({resolved} resolved{pend_str})")

    if health["issues"]:
        print(f"\n  Issues:")
        for issue in health["issues"]:
            print(f"    {issue}")

    print(f"{'='*60}\n")


def main():
    parser = argparse.ArgumentParser(
        description="Check training data collection health."
    )
    parser.add_argument(
        "--days", type=int, default=7,
        help="Number of past days to inspect (default: 7)",
    )
    parser.add_argument(
        "--quiet", action="store_true",
        help="Print only the status summary line",
    )
    args = parser.parse_args()

    health = check_training_health(days_back=args.days)

    if args.quiet:
        status = "HEALTHY" if health["healthy"] else f"{len(health['issues'])} ISSUE(S)"
        hr = f"  hit_rate={health['hit_rate']:.1f}%" if health["hit_rate"] else ""
        print(f"[training_health] {status}{hr}")
    else:
        print_report(health, args.days)

    sys.exit(0 if health["healthy"] else 1)


if __name__ == "__main__":
    main()
