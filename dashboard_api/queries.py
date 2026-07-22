"""
dashboard_api/queries.py — dashboard-only Supabase query.

Reuses the real src/utils/db.py's get_conn() (same retry/connection logic
your pipeline already relies on) instead of duplicating it. Nothing here
touches or modifies the production db.py file.
"""
from src.utils.db import get_conn

# Confirmed with the operator: 60%. Deliberately NOT the same as the
# production parlay builder's composite_score >= 65 gate — this filters on
# the raw season hit-rate (coverage_overall), not the blended eligibility
# score. See coverage.py's own docstring: "% of ALL games this season where
# stat met the line".
MIN_COVERAGE_OVERALL = 60.0


def get_qualified_scored_legs(run_date: str, min_coverage: float = MIN_COVERAGE_OVERALL) -> list[dict]:
    """
    Today's scored legs, deduped per (player_name, stat, direction) the same
    way production's get_scored_legs() does, filtered to
    coverage_overall >= min_coverage. This is the dashboard's ONLY leg
    source — legs that don't clear the floor never reach the frontend.
    """
    conn = get_conn()
    cur = conn.cursor()
    cur.execute(
        """
        WITH ranked_legs AS (
            SELECT *,
                   ROW_NUMBER() OVER (
                       PARTITION BY player_name, stat, direction
                       ORDER BY logged_at DESC NULLS LAST,
                                ev_per_unit DESC NULLS LAST,
                                coverage_pct DESC NULLS LAST
                   ) AS rn
            FROM mlb_scored_legs
            WHERE run_date = %s
              AND coverage_overall >= %s
        )
        SELECT *
        FROM ranked_legs
        WHERE rn = 1
        ORDER BY stat, direction, coverage_overall DESC NULLS LAST
        """,
        (run_date, min_coverage)
    )
    rows = [dict(r) for r in cur.fetchall()]
    cur.close()
    conn.close()
    return rows
