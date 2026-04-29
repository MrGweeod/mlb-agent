-- mlb_parlay_recommendations: stores 5 pre-built parlays per pipeline run
-- for serving to the web app without re-running the pipeline.
--
-- Run this in Supabase SQL Editor before deploying the updated pipeline.

CREATE TABLE IF NOT EXISTS mlb_parlay_recommendations (
  id SERIAL PRIMARY KEY,
  recommendation_date DATE NOT NULL,
  pipeline_run_time TIMESTAMP NOT NULL,
  rank INT NOT NULL,  -- 1 = best bet, 2-5 = alternates
  leg_odd_ids TEXT[] NOT NULL,  -- Array of odd_ids from mlb_scored_legs
  combined_odds INT NOT NULL,
  win_probability FLOAT NOT NULL,
  edge_pct FLOAT NOT NULL,
  analysis TEXT,  -- NULL until requested, populated on-demand
  bet_status TEXT DEFAULT 'pending',  -- pending/won/lost/void
  created_at TIMESTAMP DEFAULT NOW(),
  CONSTRAINT valid_rank CHECK (rank >= 1 AND rank <= 5),
  CONSTRAINT valid_bet_status CHECK (bet_status IN ('pending', 'won', 'lost', 'void'))
);

CREATE INDEX IF NOT EXISTS idx_recommendations_date ON mlb_parlay_recommendations(recommendation_date);
CREATE INDEX IF NOT EXISTS idx_recommendations_status ON mlb_parlay_recommendations(bet_status);
