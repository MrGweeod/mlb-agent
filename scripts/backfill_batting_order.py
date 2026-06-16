#!/usr/bin/env python3
"""
scripts/backfill_batting_order.py

Backfills mlb_scored_legs.batting_order for run_dates 2026-06-01 through
2026-06-10 using one statsapi boxscore call per unique game_pk.

Strategy
--------
1. SELECT DISTINCT game_pk, player_id from mlb_scored_legs in the target window
   where batting_order IS NULL (skip already-populated rows).
2. Group player_ids by game_pk.
3. For each unique game_pk: call statsapi.get('game', {'gamePk': pk, 'hydrate':
   'lineups'}) — same call used by lineup_confirmation.py at runtime.
4. Extract liveData.boxscore.teams.{home|away}.battingOrder (list of int
   player_ids in slot order; slot = index + 1).
5. Build (game_pk, player_id) → slot map.
6. In dry-run mode: print intended updates + population rate, commit nothing.
   In --commit mode: bulk-update mlb_scored_legs.batting_order.

Usage
-----
    # Dry run (default):
    python scripts/backfill_batting_order.py

    # Custom date range (still dry unless --commit):
    python scripts/backfill_batting_order.py --start-date 2026-06-01 --end-date 2026-06-10

    # Apply changes:
    python scripts/backfill_batting_order.py --commit

    # Single game for testing:
    python scripts/backfill_batting_order.py --game-pk 777543 --commit
"""
import argparse
import sys
import os
import time
from collections import defaultdict

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import statsapi
from src.utils.db import get_conn

# Alias map — keep in sync with lineup_confirmation.py
ABR_ALIASES: dict[str, str] = {
    "ATH": "OAK",
    "AZ":  "ARI",
}

DEFAULT_START = "2026-06-01"
DEFAULT_END   = "2026-06-10"

# Delay between statsapi calls (seconds) to avoid hammering the API
API_DELAY = 0.3


def fetch_batting_order_for_game(game_pk: int) -> dict[int, int]:
    """
    Returns {player_id: slot} for all players in the batting order of game_pk.
    Slot is 1-indexed (leadoff = 1).  Returns {} if lineup not posted.
    """
    try:
        resp = statsapi.get("game", {"gamePk": game_pk, "hydrate": "lineups"})
        boxscore = resp.get("liveData", {}).get("boxscore", {})
        teams    = boxscore.get("teams", {})
        player_map: dict[int, int] = {}
        for side in ("home", "away"):
            batting_order: list[int] = teams.get(side, {}).get("battingOrder", [])
            for slot_idx, pid in enumerate(batting_order):
                if pid:
                    player_map[int(pid)] = slot_idx + 1
        return player_map
    except Exception as exc:
        print(f"  [WARN] statsapi call failed for game_pk={game_pk}: {exc}")
        return {}


def check_column_exists(conn, table: str, column: str) -> bool:
    cur = conn.cursor()
    cur.execute(
        """
        SELECT 1 FROM information_schema.columns
        WHERE table_name = %s AND column_name = %s
        """,
        (table, column),
    )
    exists = cur.fetchone() is not None
    cur.close()
    return exists


def get_legs_needing_batting_order(conn, start_date: str, end_date: str) -> list[dict]:
    """
    Returns rows from mlb_scored_legs where batting_order IS NULL within the
    date window.  player_id is TEXT in this table — cast handled in caller.
    """
    cur = conn.cursor()
    cur.execute(
        """
        SELECT id, run_date, game_pk, player_id
        FROM mlb_scored_legs
        WHERE run_date BETWEEN %s AND %s
          AND batting_order IS NULL
          AND game_pk IS NOT NULL
          AND player_id IS NOT NULL
        ORDER BY run_date, game_pk
        """,
        (start_date, end_date),
    )
    rows = cur.fetchall()
    cur.close()
    return [dict(r) for r in rows]


def main():
    parser = argparse.ArgumentParser(description="Backfill batting_order for mlb_scored_legs")
    parser.add_argument("--start-date", default=DEFAULT_START, help="Start run_date (YYYY-MM-DD)")
    parser.add_argument("--end-date",   default=DEFAULT_END,   help="End run_date (YYYY-MM-DD)")
    parser.add_argument("--game-pk",    type=int, default=None, help="Restrict to a single game_pk")
    parser.add_argument("--commit",     action="store_true",    help="Write changes (default: dry-run)")
    args = parser.parse_args()

    dry_run = not args.commit
    mode    = "DRY-RUN" if dry_run else "COMMIT"
    print(f"[backfill_batting_order] Mode: {mode} | {args.start_date} → {args.end_date}")

    conn = get_conn()

    # Guard: migration must be applied first
    if not check_column_exists(conn, "mlb_scored_legs", "batting_order"):
        print(
            "\n  ERROR: Column mlb_scored_legs.batting_order does not exist.\n"
            "  Run sql/lineup_confirmation_migration.sql against your database first.\n"
        )
        conn.close()
        sys.exit(1)

    # -----------------------------------------------------------------------
    # 1. Fetch legs that need batting_order
    # -----------------------------------------------------------------------
    rows = get_legs_needing_batting_order(conn, args.start_date, args.end_date)

    if args.game_pk:
        rows = [r for r in rows if r["game_pk"] == args.game_pk]

    total_legs = len(rows)
    print(f"  Legs with NULL batting_order in window: {total_legs}")
    if total_legs == 0:
        print("  Nothing to backfill. Done.")
        conn.close()
        return

    # -----------------------------------------------------------------------
    # 2. Group player_ids by game_pk
    # -----------------------------------------------------------------------
    # game_pk → list of (leg_id, player_id_int)
    game_to_legs: dict[int, list[tuple[int, int]]] = defaultdict(list)
    skipped_non_int = 0
    for row in rows:
        try:
            pid_int = int(row["player_id"])
        except (ValueError, TypeError):
            skipped_non_int += 1
            continue
        game_to_legs[row["game_pk"]].append((row["id"], pid_int))

    if skipped_non_int:
        print(f"  Skipped {skipped_non_int} rows with non-integer player_id")

    unique_games = sorted(game_to_legs.keys())
    print(f"  Unique game_pks to fetch: {len(unique_games)}")

    # -----------------------------------------------------------------------
    # 3. Fetch batting orders game by game, build update list
    # -----------------------------------------------------------------------
    updates: list[tuple[int, int]] = []  # (slot, leg_id)
    populated = 0
    not_in_lineup = 0
    lineup_not_posted = 0

    for i, game_pk in enumerate(unique_games, 1):
        print(f"  [{i}/{len(unique_games)}] game_pk={game_pk} ...", end=" ", flush=True)
        player_map = fetch_batting_order_for_game(game_pk)

        if not player_map:
            lineup_not_posted += len(game_to_legs[game_pk])
            print(f"lineup not posted ({len(game_to_legs[game_pk])} legs unresolved)")
            time.sleep(API_DELAY)
            continue

        game_hits = 0
        game_misses = 0
        for leg_id, pid_int in game_to_legs[game_pk]:
            slot = player_map.get(pid_int)
            if slot is not None:
                updates.append((slot, leg_id))
                game_hits += 1
            else:
                game_misses += 1

        populated       += game_hits
        not_in_lineup   += game_misses
        print(f"matched {game_hits}/{game_hits + game_misses} legs")
        time.sleep(API_DELAY)

    # -----------------------------------------------------------------------
    # 4. Report population rate
    # -----------------------------------------------------------------------
    resolvable = total_legs - skipped_non_int
    pop_rate   = (populated / resolvable * 100) if resolvable else 0
    print()
    print(f"  Summary:")
    print(f"    Total legs checked   : {total_legs}")
    print(f"    Slots matched        : {populated}  ({pop_rate:.1f}% of resolvable)")
    print(f"    Not in lineup        : {not_in_lineup}")
    print(f"    Lineup not posted    : {lineup_not_posted}")
    print(f"    Non-int player_id    : {skipped_non_int}")

    if not updates:
        print("  No updates to apply. Done.")
        conn.close()
        return

    # -----------------------------------------------------------------------
    # 5. Apply or preview updates
    # -----------------------------------------------------------------------
    if dry_run:
        print(f"\n  [DRY-RUN] Would UPDATE {len(updates)} rows in mlb_scored_legs.batting_order")
        # Show a sample
        sample = updates[:10]
        print(f"  Sample (up to 10):")
        for slot, leg_id in sample:
            print(f"    leg_id={leg_id}  →  batting_order={slot}")
        print("\n  Re-run with --commit to apply.")
    else:
        cur = conn.cursor()
        batch_size = 500
        written = 0
        for start in range(0, len(updates), batch_size):
            batch = updates[start:start + batch_size]
            # psycopg2 executemany
            cur.executemany(
                "UPDATE mlb_scored_legs SET batting_order = %s WHERE id = %s",
                batch,
            )
            written += len(batch)
            conn.commit()
            print(f"  Committed {written}/{len(updates)} rows ...")

        cur.close()
        print(f"\n  Done. {written} rows updated.")

    conn.close()


if __name__ == "__main__":
    main()
