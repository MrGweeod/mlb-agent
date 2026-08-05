-- Migration: scorer_version instrumentation + new signal columns for the
-- 2026-08-05 leg-scoring redesign (hits/over exposure-weighted ERA/WHIP,
-- totalBases promoted to the live pool, pt_tb_rate percentile scoring).
--
-- scorer_version lets "how did v2_2026-08-05 actually perform" be queried
-- cleanly, separated from whatever scored a leg before this change — the
-- substitute safety net for shipping without a full shadow-test cycle.
--
-- Run this once in the Supabase SQL Editor (or via the Supabase MCP).

-- mlb_scored_legs: version tag + the new per-leg signals used to produce it
ALTER TABLE mlb_scored_legs
    ADD COLUMN IF NOT EXISTS scorer_version  TEXT,
    ADD COLUMN IF NOT EXISTS pt_tb_rate      REAL,
    ADD COLUMN IF NOT EXISTS effective_era   NUMERIC,
    ADD COLUMN IF NOT EXISTS effective_whip  NUMERIC,
    ADD COLUMN IF NOT EXISTS exposure_weight REAL;

CREATE INDEX IF NOT EXISTS idx_scored_legs_scorer_version
    ON mlb_scored_legs (scorer_version);

-- mlb_parlay_recommendations_v2 / mlb_parlay_legs_v2: version tag on every
-- parlay + leg produced by this scoring logic
ALTER TABLE mlb_parlay_recommendations_v2
    ADD COLUMN IF NOT EXISTS scorer_version TEXT;

CREATE INDEX IF NOT EXISTS idx_parlay_recs_v2_scorer_version
    ON mlb_parlay_recommendations_v2 (scorer_version);

ALTER TABLE mlb_parlay_legs_v2
    ADD COLUMN IF NOT EXISTS scorer_version TEXT;
