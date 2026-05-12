-- Add coverage_overall, coverage splits, and pitcher/batter columns to mlb_scored_legs
-- Run against Supabase before deploying the updated log_scored_legs() function.

ALTER TABLE mlb_scored_legs
ADD COLUMN IF NOT EXISTS coverage_overall       NUMERIC,
ADD COLUMN IF NOT EXISTS coverage_vs_hand       NUMERIC,
ADD COLUMN IF NOT EXISTS coverage_recent_10     NUMERIC,
ADD COLUMN IF NOT EXISTS coverage_recent_5      NUMERIC,
ADD COLUMN IF NOT EXISTS pitcher_id             TEXT,
ADD COLUMN IF NOT EXISTS pitcher_name           TEXT,
ADD COLUMN IF NOT EXISTS pitcher_team           TEXT,
ADD COLUMN IF NOT EXISTS pitcher_era            NUMERIC,
ADD COLUMN IF NOT EXISTS pitcher_k9             NUMERIC,
ADD COLUMN IF NOT EXISTS pitcher_whip           NUMERIC,
ADD COLUMN IF NOT EXISTS batter_hand            TEXT,
ADD COLUMN IF NOT EXISTS pitcher_vs_batter_hand_era NUMERIC;

-- Note: pitcher_hand already exists (added in a prior migration)

CREATE INDEX IF NOT EXISTS idx_scored_legs_pitcher_id
    ON mlb_scored_legs(pitcher_id);

CREATE INDEX IF NOT EXISTS idx_scored_legs_coverage_overall
    ON mlb_scored_legs(coverage_overall);
