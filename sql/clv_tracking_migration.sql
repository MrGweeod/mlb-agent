-- CLV Tracking Migration
-- Apply in Supabase SQL Editor (consistent with how lineup migration was applied).
-- Safe to re-run — all statements use IF NOT EXISTS / DEFAULT guards.

-- 1. Discriminator on the existing scheduler table.
--    Default 'lineup' so existing rows and existing inserts keep their current meaning.
ALTER TABLE mlb_pending_lineup_checks
    ADD COLUMN IF NOT EXISTS check_type text NOT NULL DEFAULT 'lineup';  -- 'lineup' | 'clv'

-- 2. Closing-odds capture on scored legs.
ALTER TABLE mlb_scored_legs
    ADD COLUMN IF NOT EXISTS closing_odds          text;                          -- mirrors odds (TEXT)
ALTER TABLE mlb_scored_legs
    ADD COLUMN IF NOT EXISTS closing_odds_captured_at timestamp without time zone; -- when the snapshot fired

-- 3. Index to make type-filtered queries cheap.
--    The drain's due-query filters on (status, trigger_at); this covers check_type lookups.
CREATE INDEX IF NOT EXISTS idx_pending_checks_type
    ON mlb_pending_lineup_checks (check_type, status, trigger_at);

-- Verification queries (run after applying):
--
-- Confirm columns exist on scored legs:
-- SELECT column_name FROM information_schema.columns
-- WHERE table_name='mlb_scored_legs'
--   AND column_name IN ('closing_odds','closing_odds_captured_at');
--
-- Confirm check_type column exists on scheduler table:
-- SELECT column_name FROM information_schema.columns
-- WHERE table_name='mlb_pending_lineup_checks' AND column_name='check_type';
--
-- After a 9 AM run — both check types should be scheduled per group:
-- SELECT check_type, COUNT(*) AS groups, MIN(trigger_at) AS earliest, MAX(trigger_at) AS latest
-- FROM mlb_pending_lineup_checks
-- WHERE run_date = CURRENT_DATE
-- GROUP BY check_type;
--
-- After CLV snapshots fire — capture rate:
-- SELECT
--     COUNT(*) AS total_legs,
--     COUNT(closing_odds) AS captured,
--     (COUNT(closing_odds)*100.0/NULLIF(COUNT(*),0))::numeric(5,1) AS pct_captured
-- FROM mlb_scored_legs
-- WHERE run_date = (CURRENT_DATE)::text;
