-- Add UNIQUE constraint on (recommendation_date, rank) to support UPSERT.
-- Run this once in Supabase SQL Editor before deploying the updated pipeline.
--
-- Safe to run more than once — ADD CONSTRAINT IF NOT EXISTS is idempotent.

ALTER TABLE mlb_parlay_recommendations
  ADD CONSTRAINT IF NOT EXISTS uq_recommendations_date_rank
  UNIQUE (recommendation_date, rank);
