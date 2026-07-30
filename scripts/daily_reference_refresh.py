"""
daily_reference_refresh.py — Daily refresh for the MLB reference schema.

Intended to run once per day, early morning ET (after all of the previous
day's games have gone Final, and before the existing 9 AM production
pipeline run) — see run_daily_reference_refresh() below, which is the single
entry point meant to be wired into src/web/server.py's existing in-process
scheduler pattern (see _pipeline_scheduler()/_lineup_drain_scheduler() for
the convention: asyncio.ensure_future() at server startup, ET-time-slot
loop). NOT wired into server.py by this commit — adding a new scheduled job
that makes new API calls is flagged under WORKFLOW_RULES.md's "Red Flags —
Cost-Impact Changes" as something to confirm with the operator first, not a
Green Light to wire up unattended.

Four steps, reusing the exact same tested functions as the one-time backfill:
  1. Games + box-score logs for YESTERDAY (not "today" — a refresh that ran
     literally against date.today() at any hour before all of today's games
     finish would see mostly non-Final games and skip them; yesterday's
     games are guaranteed Final by an early-morning run).
  2. Resolve mlb_prop_legs_history against the game logs just backfilled in
     step 1 (same transaction — reads its own uncommitted step-1 writes,
     which Postgres supports fine within one transaction). This is the
     natural moment to resolve: it's exactly when yesterday's box scores
     first become available. See src/pipelines/prop_legs_capture.py's
     resolve_prop_legs_history() — writes ONLY to mlb_prop_legs_history.
  3. Season-stats snapshot (Qualified Players) as of TODAY — re-pulling
     `playerPool=QUALIFIED` naturally re-checks qualification against
     today's actual team-games-played for every team, and naturally rows
     any newly-qualified player for the first time today (see
     backfill_reference_snapshots.py's module docstring for why this
     approach doesn't need a separate "who newly qualified" computation).
  4. Standings + splits snapshot as of TODAY.

Usage (manual/cron invocation):
    python -m scripts.daily_reference_refresh
    python -m scripts.daily_reference_refresh --dry-run

Environment variables required: DATABASE_URL (same as the rest of the pipeline)
"""
from __future__ import annotations

import argparse
from datetime import date, timedelta

from scripts.backfill_reference_data import backfill_teams, backfill_date
from scripts.backfill_reference_snapshots import (
    backfill_season_batting_stats,
    backfill_season_pitching_stats,
    backfill_standings,
)
from src.pipelines.prop_legs_capture import resolve_prop_legs_history
from src.utils.db import get_conn


def run_daily_reference_refresh(dry_run: bool = False) -> dict:
    """
    Run the full daily reference-data refresh. Returns a summary dict.

    Designed to be called both from this script's CLI and from
    src/web/server.py's scheduler (via loop.run_in_executor, same pattern
    as run_morning_pipeline/run_full_refresh_pipeline) once wired in.
    """
    today = date.today()
    yesterday = today - timedelta(days=1)

    conn = get_conn()
    cur = conn.cursor()
    summary = {"date": today.isoformat(), "games_backfilled": None, "prop_legs_resolved": None,
               "hitters": None, "pitchers": None, "standings_teams": None, "standings_splits": None}

    try:
        backfill_teams(cur)
        games = backfill_date(cur, yesterday)
        summary["games_backfilled"] = games
        print(f"[daily_refresh] games/logs for {yesterday}: {games} games")

        summary["prop_legs_resolved"] = resolve_prop_legs_history(cur)

        summary["hitters"] = backfill_season_batting_stats(cur, today, today.year)
        summary["pitchers"] = backfill_season_pitching_stats(cur, today, today.year)
        n_teams, n_splits = backfill_standings(cur, today, today.year)
        summary["standings_teams"] = n_teams
        summary["standings_splits"] = n_splits

        if dry_run:
            conn.rollback()
            print("[daily_refresh] DRY RUN — rolled back")
        else:
            conn.commit()
            print("[daily_refresh] committed")
    except Exception:
        conn.rollback()
        raise
    finally:
        cur.close()
        conn.close()

    return summary


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()
    summary = run_daily_reference_refresh(dry_run=args.dry_run)
    print(f"[daily_refresh] summary: {summary}")


if __name__ == "__main__":
    main()
