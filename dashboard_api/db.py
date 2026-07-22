"""
dashboard_api/db.py — dashboard-api's own write path for bet logging
(POST /api/dashboard/parlay).

Phase 1 architecture decision: this service must be able to write parlay
recommendations independently of the mlb-agent service's uptime, so
save_dashboard_parlay() below is a direct copy of src/utils/db.py's
save_parlay_recommendations_v2() INSERT logic rather than an import/proxy
of that function. Reads still go through the shared src/utils/db.get_conn()
connection helper — that's just a psycopg2 connection wrapper (same repo,
same DB), not a call to the other Railway service.
"""
from datetime import datetime as _dt

from src.utils.db import get_conn


def get_legs_by_odd_ids(run_date: str, odd_ids: list[str]) -> list[dict]:
    """
    Re-fetch legs fresh from mlb_scored_legs by odd_id, scoped to run_date
    (today's slate — the only slate the dashboard ever offers for selection).
    Never trust line/odds/coverage from the client request body.
    """
    conn = get_conn()
    cur = conn.cursor()
    cur.execute(
        """
        SELECT *
        FROM mlb_scored_legs
        WHERE run_date = %s
          AND odd_id = ANY(%s)
        """,
        (run_date, odd_ids),
    )
    rows = [dict(r) for r in cur.fetchall()]
    cur.close()
    conn.close()
    return rows


def save_dashboard_parlay(legs: list[dict], run_date: str, combined_odds: int) -> int:
    """
    Insert one row into mlb_parlay_recommendations_v2 (source='dashboard_pick')
    and one row per leg into mlb_parlay_legs_v2 — same shape as
    save_parlay_recommendations_v2() in src/utils/db.py, copied rather than
    imported (see module docstring).

    Returns the new mlb_parlay_recommendations_v2.id (int).
    """
    from src.utils.sorting import sort_legs_by_game_time

    legs = sort_legs_by_game_time(legs)
    batch_id = f"{run_date}_{_dt.now().strftime('%H:%M:%S')}"

    coverages = [l.get("coverage_pct") for l in legs if l.get("coverage_pct") is not None]
    evs = [l.get("ev_per_unit") for l in legs if l.get("ev_per_unit") is not None]
    avg_coverage = round(sum(coverages) / len(coverages), 3) if coverages else None
    avg_ev = round(sum(evs) / len(evs), 4) if evs else None

    conn = get_conn()
    cur = conn.cursor()

    cur.execute(
        """
        INSERT INTO mlb_parlay_recommendations_v2
            (run_date, rank, total_odds, avg_coverage, avg_ev, num_legs,
             outcome, source, batch_id, edge_percent)
        VALUES (%s, 1, %s, %s, %s, %s, 'pending', 'dashboard_pick', %s, NULL)
        RETURNING id
        """,
        (run_date, combined_odds, avg_coverage, avg_ev, len(legs), batch_id),
    )
    row = cur.fetchone()
    if row is None:
        conn.rollback()
        cur.close()
        conn.close()
        raise RuntimeError(
            f"[dashboard_api.db] INSERT INTO mlb_parlay_recommendations_v2 RETURNING id "
            f"returned None for run_date={run_date!r}, batch_id={batch_id!r}"
        )
    parlay_id = row["id"]

    for leg in legs:
        cur.execute(
            """
            INSERT INTO mlb_parlay_legs_v2
                (parlay_id, player_id, player_name, team, stat, line,
                 direction, odds, composite_score, opponent_adjustment,
                 coverage, ev, game_id, opposing_pitcher_id,
                 opposing_pitcher_name, outcome)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, 'pending')
            """,
            (
                parlay_id,
                leg.get("player_id"),
                leg.get("player_name"),
                leg.get("team"),
                leg.get("stat"),
                leg.get("best_line") or leg.get("line"),
                leg.get("direction", "over"),
                leg.get("best_odds") or leg.get("odds"),
                leg.get("composite_score"),
                leg.get("opponent_adjustment"),
                leg.get("coverage_pct"),
                leg.get("ev_per_unit"),
                leg.get("game_pk"),
                leg.get("opposing_pitcher_id"),
                leg.get("opposing_pitcher_name"),
            ),
        )

    conn.commit()
    cur.close()
    conn.close()
    print(f"[dashboard_api.db] Saved parlay {parlay_id} (batch: {batch_id}, source=dashboard_pick)")
    return parlay_id
