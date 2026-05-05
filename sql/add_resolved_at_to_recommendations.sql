-- Migration: add resolved_at column to mlb_parlay_recommendations
-- Run in Supabase SQL Editor once.
-- Safe to re-run (IF NOT EXISTS / no-op if column already present).

ALTER TABLE mlb_parlay_recommendations
    ADD COLUMN IF NOT EXISTS resolved_at TIMESTAMP;

CREATE INDEX IF NOT EXISTS idx_recommendations_resolved
    ON mlb_parlay_recommendations(resolved_at)
    WHERE resolved_at IS NOT NULL;
