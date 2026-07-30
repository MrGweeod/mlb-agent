"""
test_prop_legs_capture.py — Isolated test for src/pipelines/prop_legs_capture.py.

Replicates ONLY Steps 2-3 of main.py's run_pipeline() (schedule fetch, SGO
fetch) and calls capture_full_prop_lines() directly, WITHOUT running the
rest of the pipeline (coverage gate, injury filter, parlay building, or any
write to mlb_scored_legs / mlb_parlay_recommendations_v2 / mlb_training_data).
Safe to run standalone before wiring is trusted in production.

Costs one real SGO /events call (same as any single production run).

Usage:
    python -m scripts.test_prop_legs_capture

Environment variables required: DATABASE_URL, SPORTSGAMEODDS_API_KEY
"""
from __future__ import annotations

from datetime import date

from src.apis.mlb_stats import get_schedule
from src.apis.sportsgameodds import get_todays_games, get_player_props
from src.pipelines.prop_legs_capture import capture_full_prop_lines
from src.utils.db import get_conn


def main():
    today = str(date.today())
    print(f"[test] Fetching schedule for {today}...")
    schedule = get_schedule(today)
    print(f"[test] {len(schedule)} games on the slate")
    if not schedule:
        print("[test] No games today — nothing to test.")
        return

    print("[test] Fetching SGO events + player props...")
    sgo_games = get_todays_games()

    from src.pipelines.prop_legs_capture import _abbr
    schedule_pairs = {(_abbr(g.get("away_name", "")), _abbr(g.get("home_name", ""))) for g in schedule}
    print(f"[test] schedule team-pairs (from _abbr on full names): {sorted(schedule_pairs)}")
    for g in sgo_games:
        teams = g.get("teams", {})
        away_short = (teams.get("away", {}).get("names") or {}).get("short", "")
        home_short = (teams.get("home", {}).get("names") or {}).get("short", "")
        away_full = teams.get("away", {}).get("names", {})
        home_full = teams.get("home", {}).get("names", {})
        matched = (away_short, home_short) in schedule_pairs
        print(f"  SGO pair: ({away_short!r}, {home_short!r}) matched={matched} "
              f"| away.names={away_full} home.names={home_full}")

    all_sgo_props: list[dict] = []
    for sgo_game in sgo_games:
        all_sgo_props.extend(get_player_props(sgo_game))
    print(f"[test] {len(sgo_games)} SGO game(s) | {len(all_sgo_props)} raw props")

    print("[test] Calling capture_full_prop_lines()...")
    summary = capture_full_prop_lines(sgo_games, all_sgo_props, schedule)
    print(f"[test] Summary: {summary}")

    print()
    print("[test] Spot-checking what actually landed in mlb_prop_legs_history...")
    conn = get_conn()
    cur = conn.cursor()
    cur.execute(
        """
        SELECT market_scope, player_role, stat, direction, count(*) AS n
        FROM mlb_prop_legs_history
        GROUP BY market_scope, player_role, stat, direction
        ORDER BY market_scope, player_role NULLS FIRST, stat, direction
        """
    )
    for row in cur.fetchall():
        print(f"  {dict(row)}")

    cur.execute("SELECT count(*) AS total FROM mlb_prop_legs_history")
    print(f"  total rows: {cur.fetchone()['total']}")

    print()
    print("[test] Sample game-scope row:")
    cur.execute("SELECT * FROM mlb_prop_legs_history WHERE market_scope = 'game' LIMIT 1")
    row = cur.fetchone()
    print(f"  {dict(row) if row else '(none)'}")

    print()
    print("[test] Sample player-scope pitcher row:")
    cur.execute("SELECT * FROM mlb_prop_legs_history WHERE player_role = 'pitcher' LIMIT 1")
    row = cur.fetchone()
    print(f"  {dict(row) if row else '(none)'}")

    cur.close()
    conn.close()


if __name__ == "__main__":
    main()
