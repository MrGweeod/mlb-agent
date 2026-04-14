"""
recommendation_logger.py — Auto-log every recommended parlay for model evaluation.

Every parlay the agent recommends is stored here regardless of whether the user bets.
This provides the training signal for calibration: P(over) predictions vs actual outcomes.
"""
from __future__ import annotations

from datetime import date
from src.utils.db import get_conn, now_utc


def log_recommendations(parlays: list[dict]) -> list[int]:
    """
    Insert all recommended parlays and their legs into the DB.
    Returns list of recommendation IDs created.
    Skips parlays already logged for today (idempotent on re-runs).
    """
    if not parlays:
        return []

    today = str(date.today())
    conn = get_conn()
    cur = conn.cursor()

    # Check if we already logged recommendations today to avoid duplicates on re-runs
    cur.execute(
        "SELECT COUNT(*) FROM mlb_recommendations WHERE date = %s", (today,)
    )
    existing = cur.fetchone()["count"]
    if existing:
        cur.execute(
            "SELECT id FROM mlb_recommendations WHERE date = %s ORDER BY id", (today,)
        )
        ids = [r["id"] for r in cur.fetchall()]
        cur.close()
        conn.close()
        print(f"  Recommendations already logged today ({existing} parlays) — skipping")
        return ids

    rec_ids = []
    for parlay in parlays:
        cur.execute(
            """
            INSERT INTO mlb_recommendations
                (date, parlay_odds, num_legs, avg_coverage, avg_ev, parlay_type, status, created_at)
            VALUES (%s, %s, %s, %s, %s, %s, 'pending', %s)
            RETURNING id
            """,
            (
                today,
                parlay.get("parlay_odds"),
                parlay.get("num_legs"),
                parlay.get("avg_coverage"),
                parlay.get("avg_ev"),
                parlay.get("parlay_type", "hybrid"),
                now_utc(),
            ),
        )
        rec_id = cur.fetchone()["id"]
        rec_ids.append(rec_id)

        for leg in parlay.get("legs", []):
            cur.execute(
                """
                INSERT INTO mlb_recommendation_legs
                    (recommendation_id, player_name, stat, line, odds,
                     coverage_pct, p_over, ev_per_unit, predicted_mean, predicted_std,
                     direction, team)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                """,
                (
                    rec_id,
                    leg.get("player_name", ""),
                    leg.get("stat", ""),
                    leg.get("best_line"),
                    str(leg.get("best_odds", "")),
                    leg.get("coverage_pct"),
                    leg.get("p_over"),
                    leg.get("ev_per_unit"),
                    leg.get("predicted_mean"),
                    leg.get("predicted_std"),
                    leg.get("direction", "over"),
                    leg.get("team"),
                ),
            )

    conn.commit()
    cur.close()
    conn.close()
    print(f"  Logged {len(rec_ids)} recommended parlay(s) for tracking")
    return rec_ids
