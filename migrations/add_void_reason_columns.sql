-- Add void_reason column to mlb_parlay_legs_v2
-- mlb_scored_legs already has void_reason; this brings parlay legs in sync.
ALTER TABLE mlb_parlay_legs_v2
ADD COLUMN IF NOT EXISTS void_reason text;
