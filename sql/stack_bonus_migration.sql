-- Stack bonus migration: add stack tracking columns to mlb_scored_legs_enriched
-- Apply in Supabase SQL Editor. IF NOT EXISTS-guarded — safe to run multiple times.

ALTER TABLE mlb_scored_legs_enriched
    ADD COLUMN IF NOT EXISTS stack_bonus_applied  boolean DEFAULT false;

ALTER TABLE mlb_scored_legs_enriched
    ADD COLUMN IF NOT EXISTS pitcher_vulnerability numeric;
