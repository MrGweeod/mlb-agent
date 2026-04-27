-- training_data_views.sql
-- Run in Supabase SQL Editor: Database → SQL Editor → New query → paste → Run
-- All views are CREATE OR REPLACE — safe to re-run when schema evolves.

-- ── VIEW 1: Daily Collection Health ─────────────────────────────────────────
-- Last 14 days of collection volume and resolution status.
-- Use for: monitoring whether the daily pipeline is logging props.

CREATE OR REPLACE VIEW training_data_daily_health AS
SELECT
    game_date,
    COUNT(*)                                                      AS total_props,
    COUNT(*) FILTER (WHERE result = 'hit')                        AS hits,
    COUNT(*) FILTER (WHERE result = 'miss')                       AS misses,
    COUNT(*) FILTER (WHERE result IS NULL)                        AS pending,
    COUNT(*) FILTER (WHERE result = 'void')                       AS voided,
    ROUND(
        100.0 * COUNT(*) FILTER (WHERE result = 'hit') /
        NULLIF(COUNT(*) FILTER (WHERE result IN ('hit', 'miss')), 0),
        1
    )                                                             AS hit_rate_pct,
    COUNT(*) FILTER (WHERE composite_score IS NOT NULL AND composite_score >= 60) AS high_score_legs,
    COUNT(*) FILTER (WHERE coverage_pct IS NOT NULL AND coverage_pct >= 60)       AS high_coverage_legs,
    MAX(logged_at)                                                AS last_updated
FROM mlb_training_data
WHERE game_date >= (CURRENT_DATE - INTERVAL '14 days')::text
GROUP BY game_date
ORDER BY game_date DESC;


-- ── VIEW 2: Feature Health ───────────────────────────────────────────────────
-- Shows what percentage of rows have each ML feature populated.
-- Last 14 days. Use for: detecting pipeline feature-engineering failures.

CREATE OR REPLACE VIEW training_data_feature_health AS
SELECT
    game_date,
    COUNT(*)                                                                      AS total_rows,
    COUNT(*) FILTER (WHERE coverage_pct IS NOT NULL)                              AS has_coverage,
    COUNT(*) FILTER (WHERE composite_score IS NOT NULL)                           AS has_score,
    COUNT(*) FILTER (WHERE opponent_adjustment IS NOT NULL)                       AS has_opponent,
    COUNT(*) FILTER (WHERE trend_score IS NOT NULL)                               AS has_trend,
    ROUND(100.0 * COUNT(*) FILTER (WHERE coverage_pct IS NOT NULL)      / COUNT(*), 1) AS coverage_pct,
    ROUND(100.0 * COUNT(*) FILTER (WHERE composite_score IS NOT NULL)   / COUNT(*), 1) AS score_pct,
    ROUND(100.0 * COUNT(*) FILTER (WHERE opponent_adjustment IS NOT NULL) / COUNT(*), 1) AS opponent_pct,
    ROUND(100.0 * COUNT(*) FILTER (WHERE trend_score IS NOT NULL)       / COUNT(*), 1) AS trend_pct
FROM mlb_training_data
WHERE game_date >= (CURRENT_DATE - INTERVAL '14 days')::text
GROUP BY game_date
ORDER BY game_date DESC;


-- ── VIEW 3: Direction Bias Analysis ─────────────────────────────────────────
-- Hit rates by stat + direction for the last 30 days.
-- Filtered to stat+direction combos with at least 20 resolved samples.
-- Use for: validating over/under bias and prop-type selection strategy.

CREATE OR REPLACE VIEW training_data_direction_analysis AS
SELECT
    stat,
    direction,
    COUNT(*)                                                      AS total,
    COUNT(*) FILTER (WHERE result = 'hit')                        AS hits,
    COUNT(*) FILTER (WHERE result = 'miss')                       AS misses,
    ROUND(
        100.0 * COUNT(*) FILTER (WHERE result = 'hit') /
        NULLIF(COUNT(*) FILTER (WHERE result IN ('hit', 'miss')), 0),
        1
    )                                                             AS hit_rate_pct
FROM mlb_training_data
WHERE result IN ('hit', 'miss')
  AND game_date >= (CURRENT_DATE - INTERVAL '30 days')::text
GROUP BY stat, direction
HAVING COUNT(*) >= 20
ORDER BY stat, direction;


-- ── VIEW 4: Coverage Calibration ────────────────────────────────────────────
-- Predicted coverage % vs actual hit rate, bucketed by coverage level.
-- Use for: assessing whether the coverage formula is well-calibrated.

CREATE OR REPLACE VIEW training_data_calibration AS
SELECT
    CASE
        WHEN coverage_pct < 55 THEN '<55%'
        WHEN coverage_pct < 60 THEN '55-60%'
        WHEN coverage_pct < 65 THEN '60-65%'
        WHEN coverage_pct < 70 THEN '65-70%'
        ELSE '70%+'
    END                                                           AS coverage_bucket,
    COUNT(*)                                                      AS total,
    COUNT(*) FILTER (WHERE result = 'hit')                        AS hits,
    ROUND(
        100.0 * COUNT(*) FILTER (WHERE result = 'hit') / COUNT(*),
        1
    )                                                             AS actual_hit_rate,
    ROUND(AVG(coverage_pct)::numeric, 1)                          AS avg_predicted_coverage,
    ROUND(
        AVG(coverage_pct) -
        100.0 * COUNT(*) FILTER (WHERE result = 'hit') / COUNT(*),
        1
    )                                                             AS error_pp
FROM mlb_training_data
WHERE coverage_pct IS NOT NULL
  AND result IN ('hit', 'miss')
GROUP BY coverage_bucket
ORDER BY coverage_bucket;
