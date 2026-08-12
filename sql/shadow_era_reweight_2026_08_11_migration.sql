-- Migration: shadow hits/over composite_score columns for the ERA re-weight
-- diagnostic (2026-08-11) — see docs/ARCHITECTURE_DECISIONS.md §40 follow-up.
--
-- Live hits/over scoring's ERA term (src/engine/simple_scorer.py) is a
-- discretized +/-5 step that only fires when effective_era falls outside
-- [3.0, 5.0] -- ~70% of legs land in that dead zone and get +0. A read-only
-- diagnostic replacing the step with a continuous term (proportional to
-- effective_era - league_avg) showed correlation with outcome climbing
-- monotonically with the term's weight. These two columns store that
-- diagnostic's 4x/8x weight tiers, computed and logged on every hits/over
-- leg going forward, alongside (never substituting for) composite_score.
--
-- Applied directly via Supabase MCP against production and verified live via
-- information_schema.columns, same pattern as prior sessions.
--
-- Run this once in the Supabase SQL Editor (or via the Supabase MCP).

ALTER TABLE mlb_scored_legs
    ADD COLUMN IF NOT EXISTS shadow_composite_score_v1 REAL,
    ADD COLUMN IF NOT EXISTS shadow_composite_score_v2 REAL;
