"""
One-time script to backfill game_start_time for legs with NULL values.
Default date: 2026-05-11. Pass a date as argv[1] to override.

Usage:
    python3 scripts/backfill_game_start_time.py
    python3 scripts/backfill_game_start_time.py 2026-05-11
    railway run python3 scripts/backfill_game_start_time.py
"""
import os
import sys
from datetime import datetime

import pytz
import statsapi

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from src.utils.db import get_conn


ET_TZ = pytz.timezone("America/New_York")


def backfill_game_times(run_date: str) -> int:
    conn = get_conn()
    cur = conn.cursor()

    # Check current state
    cur.execute(
        """
        SELECT COUNT(*) AS total, COUNT(game_start_time) AS have_time
        FROM mlb_scored_legs
        WHERE run_date = %s
        """,
        (run_date,),
    )
    row = dict(cur.fetchone())
    total, have_time = row["total"], row["have_time"]
    missing = total - have_time
    print(f"[backfill] run_date={run_date}: {total} total legs, {have_time} have time, {missing} missing")

    if missing == 0:
        print("[backfill] Nothing to do.")
        conn.close()
        return 0

    # Fetch schedule from MLB StatsAPI
    print(f"[backfill] Fetching schedule for {run_date}...")
    try:
        schedule = statsapi.schedule(date=run_date)
    except Exception as exc:
        print(f"[backfill] ERROR fetching schedule: {exc}")
        conn.close()
        return 0

    # Build team-name -> game_start_time mapping
    team_to_time: dict[str, str] = {}
    for game in schedule:
        game_dt_str = game.get("game_datetime")
        if not game_dt_str:
            continue
        try:
            utc_dt = datetime.fromisoformat(game_dt_str.replace("Z", "+00:00"))
            et_dt = utc_dt.astimezone(ET_TZ)
            game_time_str = et_dt.strftime("%Y-%m-%d %H:%M:%S")
        except Exception as exc:
            print(f"[backfill] Warning: could not parse '{game_dt_str}': {exc}")
            continue

        for key in ("away_name", "home_name"):
            name = game.get(key, "")
            if name:
                team_to_time[name] = game_time_str

    print(f"[backfill] {len(team_to_time)} team-to-time mappings from schedule")

    # Fetch all legs that still need a time
    cur.execute(
        """
        SELECT player_name, team, stat, direction
        FROM mlb_scored_legs
        WHERE run_date = %s AND game_start_time IS NULL
        """,
        (run_date,),
    )
    legs = [dict(r) for r in cur.fetchall()]
    print(f"[backfill] {len(legs)} legs with NULL game_start_time")

    updated = 0
    not_found: list[tuple[str, str]] = []

    for leg in legs:
        team = leg["team"] or ""
        player_name = leg["player_name"]
        stat = leg["stat"]
        direction = leg["direction"]

        # Exact match first
        game_time = team_to_time.get(team)

        # Partial match fallback
        if not game_time:
            for api_team, t in team_to_time.items():
                if team and (team in api_team or api_team in team):
                    game_time = t
                    break

        if game_time:
            cur.execute(
                """
                UPDATE mlb_scored_legs
                SET game_start_time = %s
                WHERE run_date = %s
                  AND player_name = %s
                  AND stat = %s
                  AND direction = %s
                """,
                (game_time, run_date, player_name, stat, direction),
            )
            updated += 1
        else:
            not_found.append((player_name, team))

    conn.commit()

    print(f"[backfill] Updated {updated}/{len(legs)} legs")
    if not_found:
        unmatched_teams = sorted({t for _, t in not_found})
        print(f"[backfill] WARNING: {len(not_found)} legs unmatched. Unknown teams: {unmatched_teams}")
        for player, team in not_found[:10]:
            print(f"  - {player} ({team!r})")

    # Verify final state
    cur.execute(
        """
        SELECT COUNT(*) AS total, COUNT(game_start_time) AS have_time
        FROM mlb_scored_legs
        WHERE run_date = %s
        """,
        (run_date,),
    )
    row = dict(cur.fetchone())
    pct = 100.0 * row["have_time"] / row["total"] if row["total"] else 0
    print(f"[backfill] AFTER: {row['total']} total, {row['have_time']} have time ({pct:.1f}%)")

    cur.close()
    conn.close()
    return updated


if __name__ == "__main__":
    run_date = sys.argv[1] if len(sys.argv) > 1 else "2026-05-11"
    print(f"[backfill] Starting backfill for run_date={run_date}")
    updated = backfill_game_times(run_date)
    print(f"[backfill] Done. {updated} legs updated.")
