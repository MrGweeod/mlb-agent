-- Extend pitcher_profiles table with handedness split stats and pitcher_name.
-- The base table (pitcher_id, team_id, era, era_rank, k9, k9_rank, whip, whip_rank,
-- hand, last_updated) is created by initialize_db() in src/utils/db.py.
-- This migration adds the columns needed for batter-handedness split coverage.

ALTER TABLE pitcher_profiles
ADD COLUMN IF NOT EXISTS pitcher_name TEXT,
ADD COLUMN IF NOT EXISTS vs_rhb_era   NUMERIC,
ADD COLUMN IF NOT EXISTS vs_lhb_era   NUMERIC,
ADD COLUMN IF NOT EXISTS vs_rhb_k9    NUMERIC,
ADD COLUMN IF NOT EXISTS vs_lhb_k9    NUMERIC;

-- NOTE: pitcher_hand_check constraint intentionally omitted.
-- Existing rows contain hand='' (191 rows); constraint can be added after data cleanup.

CREATE INDEX IF NOT EXISTS idx_pitcher_profiles_last_updated
    ON pitcher_profiles(last_updated);
