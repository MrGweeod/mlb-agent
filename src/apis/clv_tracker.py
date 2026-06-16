"""
clv_tracker.py — Closing Line Value (CLV) snapshot worker.

Architecture:
  schedule_clv_checks()   called from log_slate_start_times() in main.py after
                          schedule_lineup_checks() — inserts one check_type='clv'
                          row per start-time group into mlb_pending_lineup_checks.

  run_clv_snapshot(row)   called from drain_due_lineup_checks() in lineup_confirmation.py
                          when check_type='clv'.  Fetches current SGO odds, matches
                          scored legs by natural key, and writes closing_odds.

  compute_clv()           read-side helper — implied-prob delta, not stored.

CLV natural key: (player_id_int, stat, line_float, direction)
  — same representation used by get_player_props() at selection time.
  Line must match exactly; a mismatch silently leaves closing_odds NULL.
"""
from __future__ import annotations

from datetime import date, datetime, timedelta
from typing import Optional

import psycopg2.extras

from src.utils.db import get_conn


CLV_OFFSET_MINUTES = 1  # snapshot closing odds at scheduled game_start_time − 1 minute


# ── CLV scheduling ────────────────────────────────────────────────────────────

def schedule_clv_checks(
    groups: dict[datetime, list[int]],
    run_date: date,
    offset_minutes: int = CLV_OFFSET_MINUTES,
) -> int:
    """
    Insert mlb_pending_lineup_checks rows with check_type='clv' for each
    start-time group.

    Idempotent: deletes any existing *pending* CLV row for the same
    (run_date, start_time_group, pass_number=1) before inserting a fresh one.
    Done/running CLV rows are left untouched — they've already fired.

    Args:
        groups:         {start_time_group (UTC-naive datetime): [game_pk, ...]}
        run_date:       Today's date.
        offset_minutes: Minutes before scheduled first pitch to fire the snapshot.

    Returns:
        Number of rows inserted.
    """
    if not groups:
        print("[clv_scheduler] No start-time groups to schedule — skipping.")
        return 0

    conn = get_conn()
    cur  = conn.cursor()
    now  = datetime.utcnow()
    inserted = 0

    for start_time, game_pks in groups.items():
        trigger_at = start_time - timedelta(minutes=offset_minutes)

        # If trigger is already past, schedule immediately (now+2min) so the
        # drain picks it up without it being silently skipped.
        if trigger_at <= now:
            trigger_at = now + timedelta(minutes=2)
            print(
                f"[clv_scheduler] {start_time} CLV: "
                f"trigger already past — rescheduled to now+2min"
            )

        # Idempotency: remove pending CLV row for this group (pass_number=1).
        # check_type='clv' filter ensures lineup rows for the same group are
        # never touched.
        cur.execute(
            """
            DELETE FROM mlb_pending_lineup_checks
            WHERE run_date       = %s
              AND start_time_group = %s
              AND check_type     = 'clv'
              AND pass_number    = 1
              AND status         = 'pending'
            """,
            (run_date, start_time),
        )

        cur.execute(
            """
            INSERT INTO mlb_pending_lineup_checks
                (run_date, start_time_group, game_pks, trigger_at,
                 offset_minutes, pass_number, status, check_type)
            VALUES (%s, %s, %s, %s, %s, 1, 'pending', 'clv')
            """,
            (run_date, start_time, game_pks, trigger_at, offset_minutes),
        )
        inserted += 1
        print(
            f"[clv_scheduler] Scheduled CLV check for "
            f"{start_time.strftime('%H:%M')} group "
            f"({len(game_pks)} game(s): {game_pks}) "
            f"→ fires at {trigger_at.strftime('%H:%M UTC')}"
        )

    conn.commit()
    cur.close()
    conn.close()
    return inserted


# ── CLV snapshot worker ───────────────────────────────────────────────────────

def run_clv_snapshot(row: dict) -> str:
    """
    Snapshot closing odds for all scored legs in this start-time group.

    Steps:
      1. Load today's scored legs for row['game_pks'] where closing_odds IS NULL.
      2. Fetch current SGO odds for today's full slate (one bulk call).
      3. Build natural-key map: (player_id_int, stat, line_float, direction) → odds_str.
      4. Match each scored leg; bulk-update closing_odds + closing_odds_captured_at.
      5. Count no-market legs (NULL is intentional signal — don't fabricate).

    Returns a one-line result_note string.
    """
    # Lazy import to avoid circular dependency at module load time
    from src.apis.sportsgameodds import get_todays_games, get_player_props

    run_date_str = str(row["run_date"])
    game_pks: list[int] = list(row["game_pks"])

    print(f"[clv_snapshot] run_date={run_date_str} games={game_pks}")

    # ── Step 1: Load scored legs needing a snapshot ───────────────────────────
    conn = get_conn()
    cur  = conn.cursor()
    cur.execute(
        """
        SELECT id, player_id, stat, line, direction
        FROM mlb_scored_legs
        WHERE run_date   = %s
          AND game_pk    = ANY(%s)
          AND closing_odds IS NULL
          AND player_id IS NOT NULL
        """,
        (run_date_str, game_pks),
    )
    legs = [dict(r) for r in cur.fetchall()]
    cur.close()
    conn.close()

    num_games = len(game_pks)

    if not legs:
        note = f"{num_games} games, 0 legs to snapshot"
        print(f"[clv_snapshot] {note}")
        return note

    print(f"[clv_snapshot] {len(legs)} legs to snapshot across {num_games} games")

    # ── Step 2: Fetch current SGO odds (one bulk call for the full day) ───────
    # date= parameter fetches ALL events on that calendar day regardless of
    # start time, so markets at T-1 are included even for imminent games.
    try:
        sgo_games = get_todays_games(date=run_date_str)
    except Exception as exc:
        raise RuntimeError(f"SGO fetch failed: {exc}") from exc

    print(f"[clv_snapshot] SGO returned {len(sgo_games)} event(s)")

    # ── Step 3: Build natural-key odds map ────────────────────────────────────
    # Key: (player_id_int, stat, line_float, direction) → odds_str
    # Reuses get_player_props() parsing verbatim — same stat names, same alt-line
    # structure, same player_id resolution as selection time.
    odds_map: dict[tuple, str] = {}

    for sgo_game in sgo_games:
        props = get_player_props(sgo_game)
        for prop in props:
            pid = prop.get("player_id")
            if pid is None:
                continue
            stat      = prop.get("stat", "")
            direction = prop.get("direction", "over")
            for entry in prop.get("all_lines", []):
                ln = entry.get("line")
                od = entry.get("odds")
                if ln is None or od is None:
                    continue
                key = (int(pid), stat, float(ln), direction)
                # First-seen wins (standard line before alt lines due to sort order)
                if key not in odds_map:
                    odds_map[key] = str(od)

    print(f"[clv_snapshot] Odds map: {len(odds_map)} (player,stat,line,dir) entries")

    # ── Step 4: Match legs → bulk update ─────────────────────────────────────
    captured_at = datetime.utcnow()
    updates: list[tuple] = []   # (closing_odds, captured_at, leg_id)
    no_market = 0

    for leg in legs:
        try:
            pid_int = int(leg["player_id"])
        except (TypeError, ValueError):
            no_market += 1
            continue

        if leg["line"] is None:
            no_market += 1
            continue

        direction = leg["direction"] or "over"
        key       = (pid_int, leg["stat"], float(leg["line"]), direction)
        closing   = odds_map.get(key)

        if closing is None:
            no_market += 1
        else:
            updates.append((closing, captured_at, leg["id"]))

    if updates:
        conn = get_conn()
        cur  = conn.cursor()
        psycopg2.extras.execute_batch(
            cur,
            """
            UPDATE mlb_scored_legs
               SET closing_odds              = %s,
                   closing_odds_captured_at  = %s
             WHERE id = %s
            """,
            updates,
        )
        conn.commit()
        cur.close()
        conn.close()

    captured = len(updates)
    note = (
        f"{num_games} games, {len(legs)} legs, "
        f"{captured} captured, {no_market} no-market"
    )
    print(f"[clv_snapshot] {note}")
    return note


# ── CLV computation helper ────────────────────────────────────────────────────

def compute_clv(
    selection_odds: "str | int | float | None",
    closing_odds:   "str | int | float | None",
) -> Optional[float]:
    """
    Compute CLV as implied-probability delta: implied(closing) − implied(selection).

    Positive = closing line implies higher probability → you beat the close (edge).
    Negative = market moved against your position.

    Formula:
        implied(odds) = |odds| / (|odds| + 100)   if odds < 0
                      = 100   / (odds + 100)       if odds > 0

        clv_prob_delta = implied(closing_odds) − implied(selection_odds)

    Args:
        selection_odds: Odds at selection time (e.g. "-115", -115, or 115).
        closing_odds:   Odds at closing time (same formats).

    Returns:
        Float prob delta (e.g. 0.032 = +3.2 percentage points), or None if
        either input is null or unparseable.
    """
    def _implied(val) -> Optional[float]:
        if val is None:
            return None
        try:
            o = int(float(str(val).replace("+", "")))
            if o == 0:
                return None
            if o < 0:
                return abs(o) / (abs(o) + 100)
            else:
                return 100 / (o + 100)
        except (TypeError, ValueError):
            return None

    imp_close = _implied(closing_odds)
    imp_sel   = _implied(selection_odds)

    if imp_close is None or imp_sel is None:
        return None

    return round(imp_close - imp_sel, 6)


# ── Monitoring query (reference) ──────────────────────────────────────────────
#
# CLV by stat/direction, last 14 days. Positive avg_clv = beating the close.
#
# SELECT
#     stat, direction,
#     COUNT(*) FILTER (WHERE closing_odds IS NOT NULL) AS captured,
#     COUNT(*) FILTER (WHERE closing_odds IS NULL)     AS no_close_market,
#     (AVG(
#         CASE
#             WHEN closing_odds IS NULL OR odds IS NULL THEN NULL
#             ELSE
#                 (CASE WHEN closing_odds::numeric < 0
#                       THEN ABS(closing_odds::numeric)/(ABS(closing_odds::numeric)+100)
#                       ELSE 100/(closing_odds::numeric+100) END)
#               - (CASE WHEN odds::numeric < 0
#                       THEN ABS(odds::numeric)/(ABS(odds::numeric)+100)
#                       ELSE 100/(odds::numeric+100) END)
#         END
#     ) * 100)::numeric(5,2) AS avg_clv_pct
# FROM mlb_scored_legs
# WHERE run_date >= (CURRENT_DATE - INTERVAL '14 days')::text
#   AND closing_odds IS NOT NULL
# GROUP BY stat, direction
# ORDER BY avg_clv_pct DESC;
