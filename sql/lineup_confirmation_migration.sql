-- ============================================================
-- Lineup Confirmation Layer — database migration
-- Run in Supabase SQL Editor before deploying the live code.
-- All statements are additive and IF NOT EXISTS / IF NOT EXISTS-guarded.
-- ============================================================

-- 3.1 Annotation columns on scored legs
ALTER TABLE mlb_scored_legs ADD COLUMN IF NOT EXISTS batting_order         integer;
ALTER TABLE mlb_scored_legs ADD COLUMN IF NOT EXISTS lineup_check_status   text;
ALTER TABLE mlb_scored_legs ADD COLUMN IF NOT EXISTS lineup_checked_at     timestamp without time zone;

-- 3.2 Annotation columns on parlay legs (production)
ALTER TABLE mlb_parlay_legs_v2 ADD COLUMN IF NOT EXISTS batting_order        integer;
ALTER TABLE mlb_parlay_legs_v2 ADD COLUMN IF NOT EXISTS lineup_check_status  varchar;
ALTER TABLE mlb_parlay_legs_v2 ADD COLUMN IF NOT EXISTS lineup_checked_at    timestamp with time zone;

-- 3.3 Superseded tracking on parlay recommendations
ALTER TABLE mlb_parlay_recommendations_v2 ADD COLUMN IF NOT EXISTS superseded_by_batch_id varchar;
ALTER TABLE mlb_parlay_recommendations_v2 ADD COLUMN IF NOT EXISTS superseded_reason      text;

-- 3.4 Persisted scheduler table
CREATE TABLE IF NOT EXISTS mlb_pending_lineup_checks (
    id               bigserial PRIMARY KEY,
    run_date         date        NOT NULL,
    start_time_group timestamp without time zone NOT NULL,   -- the shared first-pitch time
    game_pks         integer[]   NOT NULL,                    -- games sharing this first pitch
    trigger_at       timestamp without time zone NOT NULL,    -- start_time_group − offset
    offset_minutes   integer     NOT NULL DEFAULT 45,
    pass_number      smallint    NOT NULL DEFAULT 1,          -- 1 = primary, 2 = optional late pass
    status           text        NOT NULL DEFAULT 'pending',  -- pending|running|done|failed
    fired_at         timestamp without time zone,
    completed_at     timestamp without time zone,
    result_note      text,
    created_at       timestamp without time zone DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_pending_checks_due
    ON mlb_pending_lineup_checks (status, trigger_at);

-- ============================================================
-- Validation queries (run after deploying code to confirm setup)
-- ============================================================

-- After a 9 AM run: were checks scheduled?
-- SELECT run_date, start_time_group, array_length(game_pks,1) AS games, trigger_at, status
-- FROM mlb_pending_lineup_checks WHERE run_date = CURRENT_DATE ORDER BY trigger_at;

-- After checks fire: are the four states assigned?
-- SELECT lineup_check_status, COUNT(*)
-- FROM mlb_scored_legs WHERE run_date = (CURRENT_DATE)::text
-- GROUP BY lineup_check_status;

-- Phase 4: did superseded parlays get voided?
-- SELECT id, source, outcome, batch_id, superseded_by_batch_id, superseded_reason
-- FROM mlb_parlay_recommendations_v2
-- WHERE run_date = CURRENT_DATE
--   AND (source='confirmed_lineup_resolution' OR superseded_by_batch_id IS NOT NULL)
-- ORDER BY created_at;
