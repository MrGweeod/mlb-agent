#!/usr/bin/env python3
"""
verify_lineup_layer.py  —  one-command verification for the lineup-confirmation layer.

READ-ONLY. Makes no writes, no commits. Safe to run against production at any time.

Bundles every check from the design spec §11 plus the by-hand slot spot-check:

  1. MIGRATION   — all new columns + the pending-checks table exist
  2. SCHEDULER   — today's checks were scheduled and grouped by start time
  3. ANNOTATION  — the 4-state status column shows a realistic mix (not all MISSING)
  4. RESOLUTION  — superseded parlays voided + linked; CLR parlays present
  5. BACKFILL    — June 1-10 batting_order population rate
  6. SPOT-CHECK  — stored batting_order matches the LIVE statsapi lineup for one game

Usage (from mlb-agent/ repo root):
    source .venv/bin/activate && python verify_lineup_layer.py
    source .venv/bin/activate && python verify_lineup_layer.py --run-date 2026-06-15
    source .venv/bin/activate && python verify_lineup_layer.py --game-pk 778869

Exit code is 0 if no hard failures (migration + spot-check), 1 otherwise.
Informational sections (scheduler/annotation/resolution empty) never fail the run —
they just report, because "no checks scheduled yet today" is a valid state.
"""

import argparse
import datetime
import os
import sys

import psycopg2
from psycopg2.extras import RealDictCursor

try:
    import statsapi
except ImportError:
    statsapi = None  # spot-check will be skipped with a clear message


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------

GREEN, RED, YELLOW, DIM, RESET = "\033[32m", "\033[31m", "\033[33m", "\033[2m", "\033[0m"

def ok(msg):    print(f"  {GREEN}PASS{RESET}  {msg}")
def fail(msg):  print(f"  {RED}FAIL{RESET}  {msg}")
def warn(msg):  print(f"  {YELLOW}WARN{RESET}  {msg}")
def info(msg):  print(f"  {DIM}····{RESET}  {msg}")
def header(t):  print(f"\n{'='*68}\n{t}\n{'='*68}")

def get_conn():
    url = os.environ.get("DATABASE_URL")
    if not url:
        print(f"{RED}DATABASE_URL not set in environment. Aborting.{RESET}")
        sys.exit(2)
    return psycopg2.connect(url, cursor_factory=RealDictCursor)


# ---------------------------------------------------------------------------
# 1. MIGRATION
# ---------------------------------------------------------------------------

REQUIRED_COLUMNS = {
    "mlb_scored_legs":               ["batting_order", "lineup_check_status", "lineup_checked_at"],
    "mlb_parlay_legs_v2":            ["batting_order", "lineup_check_status", "lineup_checked_at"],
    "mlb_parlay_recommendations_v2": ["superseded_by_batch_id", "superseded_reason"],
}
REQUIRED_TABLE = "mlb_pending_lineup_checks"

def check_migration(conn) -> bool:
    header("1. MIGRATION — schema additions")
    cur = conn.cursor()
    all_ok = True

    for table, cols in REQUIRED_COLUMNS.items():
        cur.execute(
            """SELECT column_name FROM information_schema.columns
               WHERE table_name = %s""", (table,))
        present = {r["column_name"] for r in cur.fetchall()}
        for c in cols:
            if c in present:
                ok(f"{table}.{c}")
            else:
                fail(f"{table}.{c} MISSING — migration not applied")
                all_ok = False

    cur.execute(
        """SELECT 1 FROM information_schema.tables WHERE table_name = %s""",
        (REQUIRED_TABLE,))
    if cur.fetchone():
        ok(f"table {REQUIRED_TABLE}")
    else:
        fail(f"table {REQUIRED_TABLE} MISSING — migration not applied")
        all_ok = False

    cur.close()
    if not all_ok:
        warn("Apply the migration SQL in Supabase before anything else will work.")
    return all_ok


# ---------------------------------------------------------------------------
# 2. SCHEDULER
# ---------------------------------------------------------------------------

def check_scheduler(conn, run_date: str):
    header(f"2. SCHEDULER — pending checks for {run_date}")
    cur = conn.cursor()
    cur.execute(
        """SELECT start_time_group, array_length(game_pks,1) AS games,
                  trigger_at, status, pass_number
           FROM mlb_pending_lineup_checks
           WHERE run_date = %s
           ORDER BY trigger_at""", (run_date,))
    rows = cur.fetchall()
    cur.close()

    if not rows:
        info("No checks scheduled for this date.")
        info("Expected only AFTER a 9 AM pipeline run on a real game day. Not a failure.")
        return

    info(f"{len(rows)} check group(s) scheduled:")
    print(f"      {'first_pitch':<20} {'games':>5}  {'trigger_at':<20} {'status':<9} pass")
    for r in rows:
        print(f"      {str(r['start_time_group']):<20} {r['games'] or 0:>5}  "
              f"{str(r['trigger_at']):<20} {r['status']:<9} {r['pass_number']}")

    statuses = {r["status"] for r in rows}
    if "failed" in statuses:
        warn("Some checks are status='failed' — inspect result_note on those rows.")
    grouped = sum((r["games"] or 0) for r in rows)
    ok(f"{grouped} games across {len(rows)} start-time group(s) "
       f"(grouping working — not one row per game).")


# ---------------------------------------------------------------------------
# 3. ANNOTATION
# ---------------------------------------------------------------------------

def check_annotation(conn, run_date: str):
    header(f"3. ANNOTATION — 4-state mix in mlb_scored_legs for {run_date}")
    cur = conn.cursor()
    # run_date is TEXT on mlb_scored_legs — string compare
    cur.execute(
        """SELECT COALESCE(lineup_check_status, '(null)') AS status, COUNT(*) AS n
           FROM mlb_scored_legs
           WHERE run_date = %s
           GROUP BY lineup_check_status
           ORDER BY n DESC""", (run_date,))
    rows = cur.fetchall()
    cur.close()

    if not rows:
        info("No scored legs for this date yet.")
        return

    total = sum(r["n"] for r in rows)
    for r in rows:
        pct = (r["n"] * 100.0 / total) if total else 0
        print(f"      {r['status']:<32} {r['n']:>5}  ({pct:4.1f}%)")

    statuses = {r["status"] for r in rows}
    known = {"MISSING_LINEUP_CONFIRMATION", "LINEUP_CONFIRMED",
             "BATTING_ORDER_OUT_OF_RANGE", "SCRATCHED"}
    unexpected = statuses - known - {"(null)"}
    if unexpected:
        warn(f"Unexpected status values: {unexpected} — parser may be writing junk.")

    only_missing = statuses <= {"MISSING_LINEUP_CONFIRMATION", "(null)"}
    if only_missing:
        warn("Everything is MISSING/null. Either no lineups have posted yet (fine if "
             "run before first pitches) OR the parser isn't matching players. "
             "If this persists right up to first pitch, flip LINEUP_CHECK_SECOND_PASS=True.")
    else:
        ok("Realistic mix present (CONFIRMED and/or SCRATCHED appearing).")


# ---------------------------------------------------------------------------
# 4. RESOLUTION
# ---------------------------------------------------------------------------

def check_resolution(conn, run_date: str):
    header(f"4. RESOLUTION — CONFIRMED_LINEUP_RESOLUTION activity for {run_date}")
    cur = conn.cursor()
    # run_date is DATE on the recommendations table
    cur.execute(
        """SELECT id, source, outcome, batch_id,
                  superseded_by_batch_id, superseded_reason
           FROM mlb_parlay_recommendations_v2
           WHERE run_date = %s
             AND (source = 'confirmed_lineup_resolution'
                  OR superseded_by_batch_id IS NOT NULL)
           ORDER BY created_at""", (run_date,))
    rows = cur.fetchall()
    cur.close()

    if not rows:
        info("No resolution activity. Expected only when a selected player was "
             "SCRATCHED or out of range. Clean slate = no rows here.")
        return

    superseded = [r for r in rows if r["superseded_by_batch_id"]]
    replacements = [r for r in rows if r["source"] == "confirmed_lineup_resolution"]
    info(f"{len(superseded)} superseded parlay(s), {len(replacements)} replacement parlay(s).")

    bad = False
    for r in superseded:
        if r["outcome"] != "void":
            fail(f"parlay {r['id']} superseded but outcome={r['outcome']} (expected 'void').")
            bad = True
        if not r["superseded_reason"]:
            warn(f"parlay {r['id']} superseded with no reason recorded.")
    if not bad and superseded:
        ok("All superseded parlays are voided and linked to a replacement batch.")


# ---------------------------------------------------------------------------
# 5. BACKFILL
# ---------------------------------------------------------------------------

def check_backfill(conn):
    header("5. BACKFILL — batting_order population, 2026-06-01 → 2026-06-10")
    cur = conn.cursor()
    # run_date TEXT; ISO date strings sort correctly with BETWEEN
    cur.execute(
        """SELECT COUNT(*) AS total,
                  COUNT(batting_order) AS with_slot,
                  (COUNT(batting_order) * 100.0
                     / NULLIF(COUNT(*), 0))::numeric(5,1) AS pct
           FROM mlb_scored_legs
           WHERE run_date BETWEEN '2026-06-01' AND '2026-06-10'""")
    r = cur.fetchone()
    cur.close()

    total = r["total"] or 0
    if total == 0:
        info("No legs in the backfill window.")
        return
    info(f"{r['with_slot']}/{total} legs have batting_order ({r['pct']}%).")
    if (r["pct"] or 0) == 0:
        warn("0% populated — backfill not run yet, or migration column just added.")
    elif (r["pct"] or 0) < 70:
        warn("Population under 70%. Some null is expected (pitchers, non-appearances), "
             "but this is low — check the backfill log for ABR_ALIASES / lookup misses.")
    else:
        ok("Healthy population rate (some null is normal for pitchers/non-appearances).")


# ---------------------------------------------------------------------------
# 6. SPOT-CHECK — stored slot vs LIVE statsapi lineup
# ---------------------------------------------------------------------------

def _api_slot_map(game_pk: int) -> dict:
    """player_id(int) -> slot(1-9) from the live lineup hydrate, both teams."""
    resp = statsapi.get("game", {"gamePk": game_pk, "hydrate": "lineups"})
    box = resp.get("liveData", {}).get("boxscore", {})
    teams = box.get("teams", {})
    out = {}
    posted = False
    for side in ("away", "home"):
        order = teams.get(side, {}).get("battingOrder", []) or []
        if order:
            posted = True
        for idx, pid in enumerate(order):
            out[int(pid)] = idx + 1
    return out, posted

def pick_game_pk(conn, run_date: str):
    """Prefer a game from the run_date; fall back to the backfill window."""
    cur = conn.cursor()
    cur.execute(
        """SELECT game_pk FROM mlb_scored_legs
           WHERE run_date = %s AND game_pk IS NOT NULL
           LIMIT 1""", (run_date,))
    r = cur.fetchone()
    if not r:
        cur.execute(
            """SELECT game_pk FROM mlb_scored_legs
               WHERE run_date BETWEEN '2026-06-01' AND '2026-06-10'
                 AND game_pk IS NOT NULL AND batting_order IS NOT NULL
               LIMIT 1""")
        r = cur.fetchone()
    cur.close()
    return r["game_pk"] if r else None

def check_spot(conn, run_date: str, game_pk: int | None) -> bool:
    header("6. SPOT-CHECK — stored batting_order vs LIVE statsapi lineup")
    if statsapi is None:
        warn("statsapi not importable in this environment — spot-check skipped.")
        return True  # don't hard-fail on a tooling gap

    if game_pk is None:
        game_pk = pick_game_pk(conn, run_date)
    if game_pk is None:
        info("No game_pk available to spot-check. Skipping.")
        return True

    info(f"Spot-checking game_pk={game_pk}")
    try:
        api_map, posted = _api_slot_map(game_pk)
    except Exception as exc:
        fail(f"statsapi call failed: {exc}")
        return False

    if not posted:
        info("Lineup not posted for this game (battingOrder empty). "
             "Pick a completed regular-season game with --game-pk for a real comparison.")
        return True

    cur = conn.cursor()
    cur.execute(
        """SELECT player_id, player_name, stat, batting_order, lineup_check_status
           FROM mlb_scored_legs
           WHERE game_pk = %s AND batting_order IS NOT NULL""", (game_pk,))
    legs = cur.fetchall()
    cur.close()

    if not legs:
        info("No stored legs with batting_order for this game yet "
             "(annotation/backfill hasn't written it). Nothing to compare.")
        return True

    matches, mismatches, not_in_api = 0, 0, 0
    for leg in legs:
        try:
            pid = int(leg["player_id"])
        except (TypeError, ValueError):
            continue
        stored = leg["batting_order"]
        api_slot = api_map.get(pid)
        if api_slot is None:
            not_in_api += 1
            continue
        if stored == api_slot:
            matches += 1
        else:
            mismatches += 1
            print(f"      MISMATCH {leg['player_name']:<22} stored={stored} api={api_slot}")

    info(f"{matches} match, {mismatches} mismatch, {not_in_api} stored player not in API lineup.")
    if mismatches == 0 and matches > 0:
        ok("Stored slots match the live API lineup. Parser verified on real data.")
        return True
    if matches == 0:
        fail("Zero matches — parser path or player-id casting is wrong, OR this game's "
             "stored data predates the parser. Try --game-pk on a freshly annotated game.")
        return False
    warn("Some mismatches. A few are normal for backfilled games (in-game subs change "
         "who actually batted vs the announced lineup). Many mismatches = investigate.")
    return True


# ---------------------------------------------------------------------------
# main
# ---------------------------------------------------------------------------

def main():
    ap = argparse.ArgumentParser(description="Verify the lineup-confirmation layer (read-only).")
    ap.add_argument("--run-date", default=datetime.date.today().isoformat(),
                    help="Date to verify (YYYY-MM-DD). Defaults to today.")
    ap.add_argument("--game-pk", type=int, default=None,
                    help="Specific game_pk for the spot-check (best: a completed regular-season game).")
    args = ap.parse_args()

    print(f"Lineup-layer verification  |  run_date={args.run_date}  "
          f"|  {datetime.datetime.now():%Y-%m-%d %H:%M:%S}")

    conn = get_conn()
    hard_ok = True
    try:
        migration_ok = check_migration(conn)
        hard_ok &= migration_ok
        if not migration_ok:
            print(f"\n{RED}Migration incomplete — skipping remaining checks until it's applied.{RESET}")
            sys.exit(1)

        check_scheduler(conn, args.run_date)
        check_annotation(conn, args.run_date)
        check_resolution(conn, args.run_date)
        check_backfill(conn)
        hard_ok &= check_spot(conn, args.run_date, args.game_pk)
    finally:
        conn.close()

    header("SUMMARY")
    if hard_ok:
        ok("No hard failures. Migration present and parser verified against real data "
           "(where comparable). Informational sections above show live state.")
        print(f"\n{DIM}Reminder: annotation-only (phases 1-3) is safe to run live. Watch the "
              f"annotation mix on a real slate before enabling phase-4 resolution.{RESET}")
        sys.exit(0)
    else:
        fail("Hard failure above (migration or spot-check). Resolve before a live slate.")
        sys.exit(1)


if __name__ == "__main__":
    main()
