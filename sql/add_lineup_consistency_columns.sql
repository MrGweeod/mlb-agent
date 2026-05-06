-- Add lineup consistency tracking columns to mlb_scored_legs
-- Run this once against the Supabase database before deploying the lineup consistency filter.

ALTER TABLE mlb_scored_legs
  ADD COLUMN IF NOT EXISTS lineup_consistency REAL,
  ADD COLUMN IF NOT EXISTS void_reason TEXT;
