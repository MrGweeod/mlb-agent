-- Migration: v4 hits/over probability model (p_hit) + component features
-- See docs/ARCHITECTURE_DECISIONS.md §42 and src/engine/hits_v4.py.
--
-- p_hit replaces composite_score as the SELECTION signal for hits/over legs.
-- composite_score is still computed and stored on every leg for live
-- comparison — this migration adds columns, it removes nothing.
--
-- Column type is DOUBLE PRECISION rather than NUMERIC(p,s) deliberately.
-- The 2026-08-05/06 zero-save incident was a numeric-precision overflow on a
-- constrained NUMERIC column silently failing the write; DOUBLE PRECISION has
-- no declared precision to overflow. These are all model outputs in [0, ~10],
-- so float64 range is not a concern.
--
-- Apply via the Supabase MCP, then VERIFY LIVE against
-- information_schema.columns — never trust the exit status alone.

ALTER TABLE mlb_scored_legs
    -- Model output
    ADD COLUMN IF NOT EXISTS p_hit            DOUBLE PRECISION,
    ADD COLUMN IF NOT EXISTS p_per_ab         DOUBLE PRECISION,
    -- Batter components
    ADD COLUMN IF NOT EXISTS v4_base_rate     DOUBLE PRECISION,
    ADD COLUMN IF NOT EXISTS v4_platoon_mult  DOUBLE PRECISION,
    ADD COLUMN IF NOT EXISTS v4_trend_mult    DOUBLE PRECISION,
    ADD COLUMN IF NOT EXISTS v4_exp_ab        DOUBLE PRECISION,
    ADD COLUMN IF NOT EXISTS v4_prior_games   INTEGER,
    -- Environment components
    ADD COLUMN IF NOT EXISTS v4_hit_env       DOUBLE PRECISION,
    ADD COLUMN IF NOT EXISTS v4_hit_env_adj   DOUBLE PRECISION,
    ADD COLUMN IF NOT EXISTS v4_starter_share DOUBLE PRECISION,
    ADD COLUMN IF NOT EXISTS v4_sp_whip       DOUBLE PRECISION,
    ADD COLUMN IF NOT EXISTS v4_sp_era        DOUBLE PRECISION,
    ADD COLUMN IF NOT EXISTS v4_sp_avg_ip     DOUBLE PRECISION,
    ADD COLUMN IF NOT EXISTS v4_bp_whip       DOUBLE PRECISION,
    ADD COLUMN IF NOT EXISTS v4_bp_era        DOUBLE PRECISION,
    ADD COLUMN IF NOT EXISTS v4_opp_der       DOUBLE PRECISION;

-- Ranking index: the builder sorts the day's hits/over pool by p_hit DESC.
CREATE INDEX IF NOT EXISTS mlb_scored_legs_run_date_p_hit_idx
    ON mlb_scored_legs (run_date, p_hit DESC)
    WHERE p_hit IS NOT NULL;

-- ── Amendment 2026-08-12: calibrated probability ────────────────────────────
-- p_hit is over-dispersed (Platt slope 0.666 < 1). p_hit_cal is the
-- calibrated value; p_hit stays the raw model output for ranking and audit.
-- Ranking is unaffected — Platt is strictly monotone — but any comparison
-- that MULTIPLIES probabilities (joint probability, EV) must use p_hit_cal,
-- because over-confidence compounds with leg count.
-- See src/engine/hits_v4.py PLATT_A/PLATT_B and ARCHITECTURE_DECISIONS.md §42.
ALTER TABLE mlb_scored_legs
    ADD COLUMN IF NOT EXISTS p_hit_cal DOUBLE PRECISION;
