-- Migration: add composite_score column and fix UNIQUE constraint on mlb_scored_legs
--
-- Problem 1: UNIQUE (odd_id) is global — same DK odd_id reused across days causes
--            ON CONFLICT DO NOTHING to silently drop all previously-seen legs,
--            so only brand-new odd_ids are inserted for today.
--
-- Problem 2: composite_score was never saved to mlb_scored_legs, so
--            /api/build-parlays always saw NULL >= 55 → 0 qualifying legs.
--
-- Run this once in the Supabase SQL Editor.

-- Step 1: Add composite_score column (idempotent)
ALTER TABLE mlb_scored_legs
    ADD COLUMN IF NOT EXISTS composite_score REAL;

-- Step 2: Drop the old global unique constraint on odd_id
ALTER TABLE mlb_scored_legs
    DROP CONSTRAINT IF EXISTS mlb_scored_legs_odd_id_key;

-- Step 3: Add per-date unique constraint so the same prop can be re-inserted each day
ALTER TABLE mlb_scored_legs
    ADD CONSTRAINT mlb_scored_legs_run_date_odd_id_key UNIQUE (run_date, odd_id);
