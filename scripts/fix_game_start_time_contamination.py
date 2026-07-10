"""
One-time cleanup: fix game_start_time UTC/ET contamination in mlb_scored_legs
and mlb_scored_legs_enriched.

Issue: scripts/backfill_game_start_time.py (now retired) stored naive Eastern Time
strings into game_start_time. enrich_legs.py stores UTC ISO strings. The two formats
are indistinguishable by value, causing 15 game_pks to have conflicting times.

This script:
  1. Fetches authoritative UTC game_start_time from MLB StatsAPI for the 10
     confirmed 4-hour-offset (EDT vs UTC) game_pks and overwrites all affected legs.
  2. Investigates the 5 non-4-hour-offset game_pks to determine if they are
     genuinely the same game (same fix) or a data-modeling issue.
  3. Checks mlb_scored_legs_enriched for the same contamination.
  4. Confirms zero conflicting game_pks remain after cleanup.

Usage:
    python3 scripts/fix_game_start_time_contamination.py [--dry-run]
"""
import os
import sys
import datetime

import statsapi

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from src.utils.db import get_conn

# ── Confirmed 4-hour-offset game_pks (EDT vs UTC — certain timezone mixup) ────
CONFIRMED_CONTAMINATED = [
    822983, 823140, 823384, 823707, 824037,
    824194, 824360, 824601, 824925, 825009,
    # Postponed/rescheduled games — confirmed via StatsAPI, same fix
    823471, 824362, 824684, 824840, 824850,
]

# ── Non-4-hour-offset game_pks — investigate only, don't touch without confirmation
INVESTIGATE_ONLY = []

DRY_RUN = "--dry-run" in sys.argv


def fetch_utc_game_start(game_pk: int) -> str | None:
    """Fetch authoritative UTC start time via MLB StatsAPI (same call as enrich_legs.py)."""
    try:
        game_data = statsapi.get("game", {"gamePk": game_pk})
        game_datetime = game_data["gameData"]["datetime"]["dateTime"]
        utc_time = datetime.datetime.fromisoformat(game_datetime.replace("Z", "+00:00"))
        return utc_time.isoformat()
    except Exception as e:
        print(f"  ERROR fetching game_pk={game_pk}: {e}")
        return None


def get_current_times(cur, game_pk: int, table: str) -> list[str]:
    cur.execute(
        f"SELECT DISTINCT game_start_time::text AS t FROM {table} WHERE game_pk = %s",
        (game_pk,),
    )
    return [r["t"] for r in cur.fetchall()]


def count_legs(cur, game_pk: int, table: str) -> int:
    cur.execute(f"SELECT COUNT(*) AS n FROM {table} WHERE game_pk = %s", (game_pk,))
    return cur.fetchone()["n"]


def fix_game_pk(cur, game_pk: int, utc_time: str, table: str) -> int:
    if DRY_RUN:
        n = count_legs(cur, game_pk, table)
        print(f"    [DRY RUN] would update {n} rows in {table} → {utc_time}")
        return n
    cur.execute(
        f"UPDATE {table} SET game_start_time = %s WHERE game_pk = %s",
        (utc_time, game_pk),
    )
    return cur.rowcount


def main():
    conn = get_conn()
    cur = conn.cursor()

    print("=" * 70)
    print("STEP 1: Fix 10 confirmed 4-hour-offset game_pks")
    print("=" * 70)
    total_fixed = 0
    failed = []

    for table in ("mlb_scored_legs", "mlb_scored_legs_enriched"):
        print(f"\n  Table: {table}")
        for game_pk in CONFIRMED_CONTAMINATED:
            before = get_current_times(cur, game_pk, table)
            if not before or before == [None]:
                print(f"  game_pk={game_pk}: no rows in {table} — skip")
                continue
            utc_time = fetch_utc_game_start(game_pk)
            if utc_time is None:
                failed.append(game_pk)
                continue
            n = fix_game_pk(cur, game_pk, utc_time, table)
            print(f"  game_pk={game_pk}: was {before} → {utc_time!r} ({n} rows)")
            total_fixed += n

    if not DRY_RUN:
        conn.commit()

    print(f"\n  Total rows updated: {total_fixed}")
    if failed:
        print(f"  FAILED to fetch authoritative time for: {failed}")

    print("\n" + "=" * 70)
    print("STEP 2: Investigate 5 non-4-hour-offset game_pks")
    print("=" * 70)
    for game_pk in INVESTIGATE_ONLY:
        print(f"\n  game_pk={game_pk}")
        for table in ("mlb_scored_legs", "mlb_scored_legs_enriched"):
            before = get_current_times(cur, game_pk, table)
            n = count_legs(cur, game_pk, table)
            print(f"    {table}: {n} rows, distinct times = {before}")
        # Fetch from API to see what's authoritative
        try:
            game_data = statsapi.get("game", {"gamePk": game_pk})
            gd = game_data.get("gameData", {})
            dt = gd.get("datetime", {})
            status = gd.get("status", {}).get("detailedState", "unknown")
            api_time = dt.get("dateTime", "N/A")
            orig_date = dt.get("originalDate", "N/A")
            print(f"    StatsAPI: dateTime={api_time!r}  originalDate={orig_date!r}  status={status!r}")
        except Exception as e:
            print(f"    StatsAPI ERROR: {e}")

    print("\n" + "=" * 70)
    print("STEP 3: Verify — zero game_pks should have conflicting times")
    print("=" * 70)
    for table in ("mlb_scored_legs", "mlb_scored_legs_enriched"):
        cur.execute(
            f"""
            SELECT game_pk, COUNT(DISTINCT game_start_time) AS distinct_times
            FROM {table}
            WHERE game_pk IS NOT NULL
            GROUP BY game_pk
            HAVING COUNT(DISTINCT game_start_time) > 1
            ORDER BY game_pk
            """
        )
        conflicts = cur.fetchall()
        if conflicts:
            print(f"\n  WARNING: {len(conflicts)} game_pk(s) still have conflicts in {table}:")
            for row in conflicts:
                print(f"    game_pk={row['game_pk']}: {row['distinct_times']} distinct times")
        else:
            print(f"\n  {table}: CLEAN — no conflicting game_start_times")

    cur.close()
    conn.close()
    print("\nDone." + (" (DRY RUN — no changes written)" if DRY_RUN else ""))


if __name__ == "__main__":
    main()
