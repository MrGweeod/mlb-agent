-- Deprecate v1 parlay tables by renaming them with a _deprecated suffix.
-- These tables are no longer written to by the pipeline; all new data goes
-- into mlb_parlay_recommendations_v2 / mlb_parlay_legs_v2.
-- Safe to DROP after 2026-06-11 (30-day safety window).
--
-- Run AFTER scripts/migrate_v1_to_v2.py completes successfully.

ALTER TABLE IF EXISTS mlb_recommendations
    RENAME TO mlb_recommendations_deprecated_20260512;

ALTER TABLE IF EXISTS mlb_parlay_legs
    RENAME TO mlb_parlay_legs_deprecated_20260512;

COMMENT ON TABLE mlb_recommendations_deprecated_20260512 IS
    'Deprecated 2026-05-12. Migrated to mlb_parlay_recommendations_v2. Safe to DROP after 2026-06-11.';

COMMENT ON TABLE mlb_parlay_legs_deprecated_20260512 IS
    'Deprecated 2026-05-12. Data superseded by mlb_parlay_legs_v2. Safe to DROP after 2026-06-11.';
