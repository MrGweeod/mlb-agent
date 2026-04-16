"""
lineup_poller.py — Background lineup confirmation and targeted re-score.

Called by the bot on a 30-minute interval between 6:00 PM and 8:00 PM ET
only. Finds today's scored legs that have not yet been lineup-confirmed,
checks each game's lineup via get_lineup(), and re-scores any leg where
the player appears in the confirmed batting order.

Public API:
    poll_and_refresh(season: int | None = None) -> int
        Returns the number of legs updated this poll cycle.

Schema migration:
    Adds game_pk, player_id, opposing_pitcher_id, lineup_confirmed, and
    last_updated to mlb_scored_legs if the table is missing them. Safe to
    run on an already-migrated table — uses ADD COLUMN IF NOT EXISTS.
"""
from __future__ import annotations

from datetime import date

from src.apis.mlb_stats import get_lineup, get_pitcher_hand
from src.engine.coverage import calculate_coverage
from src.engine.leg_scorer import score_leg
from src.utils.db import (
    get_conn,
    get_pending_lineup_legs,
    mark_lineup_confirmed,
    update_leg_after_rescore,
)

# Columns added in this phase — each entry is (column_name, column_def)
_NEW_COLUMNS = [
    ("game_pk",              "INTEGER"),
    ("player_id",            "TEXT"),
    ("opposing_pitcher_id",  "TEXT"),
    ("lineup_confirmed",     "BOOLEAN NOT NULL DEFAULT FALSE"),
    ("last_updated",         "TEXT"),
]


def _ensure_schema() -> None:
    """
    Add new columns to mlb_scored_legs if they don't exist yet.

    Uses ADD COLUMN IF NOT EXISTS so this is idempotent on already-migrated
    tables. Called once per poll_and_refresh() invocation — cheap on a live
    table because PG caches the schema after the first run.
    """
    conn = get_conn()
    cur = conn.cursor()
    for col_name, col_def in _NEW_COLUMNS:
        cur.execute(
            f"ALTER TABLE mlb_scored_legs ADD COLUMN IF NOT EXISTS {col_name} {col_def}"
        )
    conn.commit()
    cur.close()
    conn.close()


def _rescore_leg(leg: dict, season: int) -> bool:
    """
    Re-calculate coverage for a single leg using the confirmed opposing pitcher.

    If coverage succeeds, updates the DB row with the new coverage_pct and
    marks lineup_confirmed=TRUE. On any error, falls back to just marking the
    leg confirmed so it isn't re-attempted on the next poll cycle.

    Returns True if the DB was updated, False if skipped entirely.
    """
    leg_id = leg.get("id")
    if not leg_id:
        return False

    player_id_raw    = leg.get("player_id")
    pitcher_id_raw   = leg.get("opposing_pitcher_id")
    stat             = leg.get("stat")
    line             = leg.get("line")

    # Must have at least player_id + stat + line to attempt a re-score
    if not (player_id_raw and stat and line is not None):
        mark_lineup_confirmed(leg_id)
        return True

    try:
        player_id  = int(player_id_raw)
        pitcher_id = int(pitcher_id_raw) if pitcher_id_raw else None

        coverage = calculate_coverage(player_id, stat, float(line), pitcher_id, season)
        if coverage is None:
            mark_lineup_confirmed(leg_id)
            return True

        # Re-build a minimal leg dict so score_leg() can compute the composite
        scored = dict(leg)
        scored["coverage_pct"] = coverage["coverage_rate"]

        new_composite = score_leg(scored)

        update_leg_after_rescore(
            leg_id=leg_id,
            coverage_pct=coverage["coverage_rate"],
            p_over=leg.get("p_over"),          # p_over not recomputed here
            ev_per_unit=leg.get("ev_per_unit"),
            trend_score=new_composite,
            opponent_adjustment=leg.get("opponent_adjustment"),
        )
        return True

    except Exception as exc:
        print(f"  [lineup_poller] rescore error leg {leg_id}: {exc}")
        # Mark confirmed so we don't loop on a broken leg
        try:
            mark_lineup_confirmed(leg_id)
        except Exception:
            pass
        return False


def poll_and_refresh(season: int | None = None) -> int:
    """
    Poll lineup confirmations for today's unconfirmed legs and re-score them.

    Steps:
      1. Ensure schema columns exist (idempotent ALTER TABLE).
      2. Fetch today's unconfirmed legs from mlb_scored_legs.
      3. Group by game_pk and call get_lineup() for each game.
      4. For confirmed lineups, check which legs have a player in the order.
      5. Re-score those legs and mark them confirmed in the DB.

    Args:
        season: Season year override. Defaults to current calendar year.

    Returns:
        Number of legs updated (re-scored or at minimum marked confirmed).
    """
    if season is None:
        season = date.today().year

    today = str(date.today())

    _ensure_schema()

    legs = get_pending_lineup_legs(today)
    if not legs:
        print(f"  [lineup_poller] No pending unconfirmed legs for {today}")
        return 0

    print(f"  [lineup_poller] {len(legs)} unconfirmed leg(s) for {today}")

    # Group legs by game_pk so we call get_lineup() once per game
    games: dict[int, list[dict]] = {}
    for leg in legs:
        gp = leg.get("game_pk")
        if gp:
            games.setdefault(gp, []).append(leg)

    refreshed = 0

    for game_pk, game_legs in games.items():
        try:
            lineup = get_lineup(game_pk)
        except Exception as exc:
            print(f"  [lineup_poller] get_lineup({game_pk}) error: {exc}")
            continue

        if not lineup.get("confirmed"):
            print(f"  [lineup_poller] game {game_pk} lineup not yet confirmed — skipping")
            continue

        # Build set of confirmed player IDs (int) from both batting orders
        confirmed_ids: set[int] = set()
        for pid in lineup.get("home_batting_order", []) + lineup.get("away_batting_order", []):
            try:
                confirmed_ids.add(int(pid))
            except (TypeError, ValueError):
                pass

        print(
            f"  [lineup_poller] game {game_pk} confirmed — "
            f"{len(confirmed_ids)} batters in lineup"
        )

        for leg in game_legs:
            pid_raw = leg.get("player_id")
            if pid_raw:
                try:
                    pid_int = int(pid_raw)
                except (TypeError, ValueError):
                    pid_int = None

                if pid_int and pid_int not in confirmed_ids:
                    # Player not in today's lineup — mark confirmed to stop polling
                    # (scratched players stay in DB so the record is preserved)
                    print(
                        f"  [lineup_poller] {leg.get('player_name')} "
                        f"(id={pid_raw}) not in confirmed lineup — marking confirmed"
                    )
                    try:
                        mark_lineup_confirmed(leg["id"])
                        refreshed += 1
                    except Exception as exc:
                        print(f"  [lineup_poller] mark_confirmed error: {exc}")
                    continue

            updated = _rescore_leg(leg, season)
            if updated:
                refreshed += 1
                print(
                    f"  [lineup_poller] refreshed {leg.get('player_name')} "
                    f"{leg.get('stat')} {leg.get('line')}"
                )

    print(f"  [lineup_poller] poll_and_refresh complete — {refreshed} leg(s) updated")
    return refreshed
