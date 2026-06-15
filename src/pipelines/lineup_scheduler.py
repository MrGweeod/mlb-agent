"""
lineup_scheduler.py — Persist lineup-check triggers to mlb_pending_lineup_checks.

Called from run_morning_pipeline() after scored legs are written.  One row per
start-time group (set of games with identical first-pitch times) is inserted for
each day.  The drain cron in server.py polls this table every minute and fires
run_lineup_check() when trigger_at <= now().
"""
from __future__ import annotations

from datetime import date, datetime, timedelta, timezone

from src.utils.db import get_conn


def schedule_lineup_checks(
    groups: dict[datetime, list[int]],
    run_date: date,
    offset_minutes: int = 45,
    second_pass: bool = False,
    second_pass_offset: int = 15,
) -> int:
    """
    Insert mlb_pending_lineup_checks rows for each start-time group.

    Idempotent: deletes any existing 'pending' rows for the same
    run_date + start_time_group + pass_number before inserting fresh ones so a
    manual 9 AM re-run never double-schedules.

    Args:
        groups:              {start_time_group (UTC-naive ET datetime): [game_pk, ...]}
        run_date:            Today's date.
        offset_minutes:      Minutes before first pitch to fire the primary check.
        second_pass:         Whether to also schedule a T-minus second_pass_offset check.
        second_pass_offset:  Minutes for the second pass (default 15).

    Returns:
        Number of rows inserted.
    """
    if not groups:
        print("[lineup_scheduler] No start-time groups to schedule — skipping.")
        return 0

    conn = get_conn()
    cur  = conn.cursor()
    now  = datetime.utcnow()
    inserted = 0

    for start_time, game_pks in groups.items():
        passes = [(1, offset_minutes)]
        if second_pass:
            passes.append((2, second_pass_offset))

        for pass_number, off_min in passes:
            trigger_at = start_time - timedelta(minutes=off_min)

            # If trigger is already past, schedule it for now+2min so the drain
            # picks it up immediately rather than it being silently skipped.
            if trigger_at <= now:
                trigger_at = now + timedelta(minutes=2)
                print(
                    f"[lineup_scheduler] {start_time} pass={pass_number}: "
                    f"trigger already past — rescheduled to now+2min"
                )

            # Idempotency: remove any existing pending row for this group/pass
            cur.execute(
                """
                DELETE FROM mlb_pending_lineup_checks
                WHERE run_date = %s
                  AND start_time_group = %s
                  AND pass_number = %s
                  AND status = 'pending'
                """,
                (run_date, start_time, pass_number),
            )

            game_pks_str = "{" + ",".join(str(pk) for pk in game_pks) + "}"
            cur.execute(
                """
                INSERT INTO mlb_pending_lineup_checks
                    (run_date, start_time_group, game_pks, trigger_at,
                     offset_minutes, pass_number, check_type, status)
                VALUES (%s, %s, %s, %s, %s, %s, 'lineup', 'pending')
                """,
                (run_date, start_time, game_pks_str, trigger_at, off_min, pass_number),
            )
            inserted += 1
            print(
                f"[lineup_scheduler] Scheduled pass={pass_number} for "
                f"{start_time.strftime('%H:%M')} group "
                f"({len(game_pks)} game(s): {game_pks}) "
                f"→ fires at {trigger_at.strftime('%H:%M UTC')}"
            )

    conn.commit()
    cur.close()
    conn.close()
    return inserted
