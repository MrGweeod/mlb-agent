-- matchup_debug_columns_migration.sql
-- Session 19 follow-up: persist the five matchup adjustment debug fields
-- computed by _compute_matchup_adjustment() in enriched_scorer.py.
--
-- These columns are NULL when the factor is not applicable to the prop type:
--   matchup_era_adj   — hits/over, hits/under, totalBases/under only
--   matchup_whip_adj  — hits/over, hits/under, totalBases/under only
--   matchup_k9_adj    — strikeouts/over, totalBases/under only
--   matchup_batter_adj — totalBases/under only
--   matchup_adj       — net combined adjustment (all props that have any formula)
-- NULL means "not applicable to this prop," not "computed as zero."

ALTER TABLE mlb_scored_legs_enriched
  ADD COLUMN matchup_adj         numeric,
  ADD COLUMN matchup_era_adj     numeric,
  ADD COLUMN matchup_whip_adj    numeric,
  ADD COLUMN matchup_k9_adj      numeric,
  ADD COLUMN matchup_batter_adj  numeric;
