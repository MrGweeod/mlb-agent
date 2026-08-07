-- 2026-08-06: today's 9AM run built parlays with combined odds up to +2312
-- (4 totalBases/over legs stacked together, before the win-rate calibration
-- fix), producing edge_percent = 1783.1%. edge_percent was NUMERIC(6,3), max
-- abs value <1000, so the INSERT threw "numeric field overflow" and the whole
-- batch (all 5 recommendations) silently rolled back inside
-- save_parlay_recommendations_v2()'s non-fatal try/except -- zero rows saved
-- for the day despite the pipeline completing successfully.
--
-- The scorer_version=v3_2026-08-06 calibration fix (simple_scorer.py) should
-- prevent this from recurring in the common case, but this is a defense-in-
-- depth safety net so a future edge case can't silently drop a whole batch
-- again. total_odds already had headroom (NUMERIC(8,3), max ~99999) but is
-- widened further alongside it for consistency.
--
-- Applied directly via Supabase MCP on 2026-08-06; this file documents it in
-- the repo per project convention.

ALTER TABLE mlb_parlay_recommendations_v2
  ALTER COLUMN edge_percent TYPE NUMERIC(9,3),
  ALTER COLUMN total_odds TYPE NUMERIC(10,3);
