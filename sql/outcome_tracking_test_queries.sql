-- Outcome tracking validation queries
-- Run in Supabase SQL Editor to verify resolution is working.

-- ── Query 1: Yesterday's leg resolutions ─────────────────────────────────────
SELECT
    run_date,
    player_name,
    team,
    stat,
    direction,
    line,
    actual_value,
    result,
    composite_score
FROM mlb_scored_legs
WHERE run_date = (CURRENT_DATE - INTERVAL '1 day')::text
ORDER BY result NULLS LAST, composite_score DESC NULLS LAST;

-- ── Query 2: Yesterday's parlay resolutions ───────────────────────────────────
SELECT
    r.recommendation_date,
    r.rank,
    r.combined_odds,
    r.win_probability,
    r.edge_pct,
    r.bet_status,
    r.resolved_at,
    r.leg_odd_ids
FROM mlb_parlay_recommendations r
WHERE r.recommendation_date = CURRENT_DATE - INTERVAL '1 day'
ORDER BY r.rank;

-- ── Query 3: Hit rate over last 7 days (legs) ─────────────────────────────────
SELECT
    run_date,
    COUNT(*)                                                   AS total_legs,
    COUNT(*) FILTER (WHERE result = 'won')                     AS won,
    COUNT(*) FILTER (WHERE result = 'lost')                    AS lost,
    COUNT(*) FILTER (WHERE result = 'void')                    AS voided,
    COUNT(*) FILTER (WHERE result IS NULL)                     AS pending,
    ROUND(
        100.0 * COUNT(*) FILTER (WHERE result = 'won') /
        NULLIF(COUNT(*) FILTER (WHERE result IN ('won', 'lost')), 0),
        1
    )                                                          AS hit_rate_pct
FROM mlb_scored_legs
WHERE run_date >= (CURRENT_DATE - INTERVAL '7 days')::text
GROUP BY run_date
ORDER BY run_date DESC;

-- ── Query 4: Parlay hit rate over last 7 days ─────────────────────────────────
SELECT
    recommendation_date,
    COUNT(*)                                                   AS total_parlays,
    COUNT(*) FILTER (WHERE bet_status = 'won')                 AS won,
    COUNT(*) FILTER (WHERE bet_status = 'lost')                AS lost,
    COUNT(*) FILTER (WHERE bet_status = 'void')                AS voided,
    COUNT(*) FILTER (WHERE bet_status = 'pending')             AS pending,
    ROUND(
        100.0 * COUNT(*) FILTER (WHERE bet_status = 'won') /
        NULLIF(COUNT(*) FILTER (WHERE bet_status IN ('won', 'lost')), 0),
        1
    )                                                          AS parlay_hit_rate_pct
FROM mlb_parlay_recommendations
WHERE recommendation_date >= CURRENT_DATE - INTERVAL '7 days'
GROUP BY recommendation_date
ORDER BY recommendation_date DESC;

-- ── Query 5: NULL check — legs still unresolved ───────────────────────────────
SELECT
    run_date,
    COUNT(*) AS unresolved_count
FROM mlb_scored_legs
WHERE result IS NULL
  AND run_date < CURRENT_DATE::text  -- prior days only
GROUP BY run_date
ORDER BY run_date DESC;
