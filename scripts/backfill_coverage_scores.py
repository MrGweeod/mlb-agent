#!/usr/bin/env python3
"""
scripts/backfill_coverage_scores.py

Recalculates coverage_overall (and related signals) for UNDER props in
mlb_scored_legs where coverage was inverted due to the pre-May-13 bug.

Scope
-----
Primary target: pitcher strikeout UNDER props in the full history — these were
missed by the May-14 backfill because rescore_historical_legs.py did not pass
`position` to calculate_coverage(), causing pitcher SO legs to be evaluated
against the batter game log (producing near-100% coverage for elite K pitchers
instead of the correct ~20-50% range).

Hitter UNDER props (hits, totalBases, walks, rbi) were correctly backfilled by
the May-14 run of rescore_historical_legs.py and do NOT need to be re-run
unless --stat is explicitly specified.

Usage
-----
    # Dry run (default) — shows what would change, commits nothing:
    python scripts/backfill_coverage_scores.py

    # Restrict to a specific stat:
    python scripts/backfill_coverage_scores.py --stat strikeouts

    # Restrict to a date range:
    python scripts/backfill_coverage_scores.py --start-date 2026-04-17 --end-date 2026-05-13

    # Apply changes:
    python scripts/backfill_coverage_scores.py --commit
"""
import argparse
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src.utils.db import get_conn
from src.engine.coverage import calculate_coverage

BATCH_SIZE = 50


def backfill_coverage(
    start_date: str = "2026-04-17",
    end_date: str = "2026-05-13",
    stat_filter: str | None = None,
    direction_filter: str = "under",
    dry_run: bool = True,
) -> None:
    conn = get_conn()
    cur = conn.cursor()

    stat_clause = "AND stat = %s" if stat_filter else ""
    params: list = [start_date, end_date, direction_filter]
    if stat_filter:
        params.append(stat_filter)

    cur.execute(
        f"""
        SELECT id, player_id, stat, line, opposing_pitcher_id,
               run_date, odd_id,
               COALESCE(position, '') AS position,
               coverage_overall AS old_coverage_overall,
               COALESCE(direction, 'over') AS direction
        FROM mlb_scored_legs
        WHERE run_date >= %s
          AND run_date <= %s
          AND direction = %s
          AND result IS NOT NULL
          AND player_id IS NOT NULL
          {stat_clause}
        ORDER BY run_date, id
        """,
        params,
    )
    legs = cur.fetchall()
    total = len(legs)
    print(f"Found {total} UNDER props to recalculate ({start_date} – {end_date})")

    if total == 0:
        print("Nothing to do.")
        conn.close()
        return

    updates = []
    skipped = 0
    failed = 0

    for i, leg in enumerate(legs, 1):
        leg_id = leg["id"]
        stat = leg["stat"]
        line = float(leg["line"])
        run_date = leg["run_date"]
        position = leg.get("position", "")
        direction = leg.get("direction", "under")
        old_cov = leg["old_coverage_overall"]

        try:
            player_id = int(leg["player_id"])
        except (TypeError, ValueError) as e:
            failed += 1
            print(f"  ERROR leg {leg_id}: bad player_id ({e})")
            continue

        pitcher_id_raw = leg.get("opposing_pitcher_id")
        try:
            pitcher_id = int(pitcher_id_raw) if pitcher_id_raw else None
        except (TypeError, ValueError):
            pitcher_id = None

        season = int(str(run_date).split("-")[0])

        try:
            result = calculate_coverage(
                player_id=player_id,
                prop_type=stat,
                line=line,
                opposing_pitcher_id=pitcher_id,
                season=season,
                position=position,
                direction=direction,
            )
            if result is None:
                skipped += 1
                continue

            new_cov = result.get("coverage_overall")
            diff = (new_cov - old_cov) if (new_cov is not None and old_cov is not None) else None
            updates.append({
                "id": leg_id,
                "player_id": player_id,
                "stat": stat,
                "line": line,
                "position": position,
                "old_cov": old_cov,
                "new_cov": new_cov,
                "diff": diff,
                "result": result,
            })

        except Exception as e:
            failed += 1
            print(f"  ERROR leg {leg_id} (player={leg.get('player_id')}, stat={stat}): {e}")
            continue

        if i % 100 == 0:
            print(f"  [{i}/{total}] processed | updates={len(updates)} skipped={skipped} failed={failed}")

    print(f"\n{'='*65}")
    print(f"Recalculated {len(updates)} coverage scores ({skipped} skipped, {failed} failed)")

    if updates:
        diffs = [u["diff"] for u in updates if u["diff"] is not None]
        if diffs:
            print(f"Average coverage change: {sum(diffs)/len(diffs):+.1f} points")
            print(f"Max change: {max(diffs):+.1f}  Min: {min(diffs):+.1f}")

        print(f"\nSample of changes (first 15):")
        print(f"  {'Player':<8} {'Stat':<14} {'Pos':<5} {'Line':<5} {'Old':>6} {'New':>6} {'Diff':>6}")
        print(f"  {'-'*60}")
        for u in updates[:15]:
            old = f"{u['old_cov']:.1f}" if u["old_cov"] is not None else "NULL"
            new = f"{u['new_cov']:.1f}" if u["new_cov"] is not None else "NULL"
            diff = f"{u['diff']:+.1f}" if u["diff"] is not None else "N/A"
            print(f"  {str(u['player_id']):<8} {u['stat']:<14} {u['position']:<5} {u['line']:<5.1f} {old:>6} {new:>6} {diff:>6}")

    if dry_run:
        print(f"\nDRY RUN — no changes committed. Re-run with --commit to apply.")
        conn.close()
        return

    print(f"\nCommitting {len(updates)} updates...")
    for i, u in enumerate(updates, 1):
        r = u["result"]
        cur.execute(
            """
            UPDATE mlb_scored_legs
            SET coverage_overall   = %s,
                coverage_vs_hand   = %s,
                coverage_recent_10 = %s,
                coverage_recent_5  = %s
            WHERE id = %s
            """,
            (
                r.get("coverage_overall"),
                r.get("coverage_vs_hand"),
                r.get("coverage_recent_10"),
                r.get("coverage_recent_5"),
                u["id"],
            ),
        )
        if i % BATCH_SIZE == 0:
            conn.commit()
            print(f"  [{i}/{len(updates)}] committed")

    conn.commit()
    cur.close()
    conn.close()
    print(f"\nDone. {len(updates)} rows updated.")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Backfill coverage scores for UNDER props")
    parser.add_argument("--start-date", default="2026-04-17", help="First run_date to fix (inclusive)")
    parser.add_argument("--end-date", default="2026-05-13", help="Last run_date to fix (inclusive)")
    parser.add_argument("--stat", default=None, help="Restrict to a specific stat (e.g. strikeouts)")
    parser.add_argument("--direction", default="under", help="Direction to fix (default: under)")
    parser.add_argument("--commit", action="store_true", help="Apply changes (default is dry run)")
    args = parser.parse_args()

    backfill_coverage(
        start_date=args.start_date,
        end_date=args.end_date,
        stat_filter=args.stat,
        direction_filter=args.direction,
        dry_run=not args.commit,
    )
