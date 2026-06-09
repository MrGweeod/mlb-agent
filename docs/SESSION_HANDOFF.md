# MLB Parlay Agent — Session Handoff
**Last Updated:** June 9, 2026 (Session 9 — Performance Analysis + Data Pipeline Gaps + TB Under + Bug Fixes)

## Current Status
✅ **OPERATIONAL — SESSION 9 DEPLOYED**
✅ **Training data pipeline gaps identified and fixed (6 gaps)**
✅ **Prop-specific pitcher signal routing in shadow pipeline**
✅ **Total Bases under 1.5 added to coverage pipeline for shadow validation**
✅ **Manual regen player exclusion fixed (was silently failing since June 8)**
✅ **Deprecated recommendation_logger FK crash fixed**
✅ **Shadow pipeline now running after every production run**
✅ **Pitcher enrichment rate: 52% → 100%**

---

## What Happened on June 9, 2026 (Session 9)

### Era-Based Performance Analysis
Pulled 558 resolved parlays across three eras to evaluate whether strategy changes improved results:

| Era | Resolved | Win Rate | Avg Odds |
|---|---|---|---|
| 1 — High odds (pre anchor/swing) | 508 | 6.5% | +1263 |
| 2 — Anchor/Swing | 58 | 6.9% | +1054 |
| 3 — Flat pool +400–+700 | 136 | 19.1% | +464 |

**Key finding:** Neither era is materially beating the market — all three are near breakeven when odds are factored in. Era 3's higher win rate is offset by lower odds. The real improvement in Era 3 came from prop whitelist cleanup (removing hits under, SO under, walks under which were active loss drivers in Era 1).

### Training Data Deep Dive
Discovered the coverage calculation flip date: **week of April 27, 2026**. Hits over jumped from 31.5% to 57.6% and hits under dropped from 68.5% to 41.9% in a single week — a mirror image flip confirming a direction logic fix landed that week. All training data before April 27 is built on incorrect coverage calculations and must not be used for signal validation.

**Clean data (April 27+) coverage bucket analysis confirmed:**
- Coverage IS predictive for hits over and SO over in the 65–84% range
- 85%+ coverage is a trap — win rates collapse (hits over drops from 71.8% to 31.5%)
- TB under shows 60–61% win rate in 65–84% bucket but breakeven is 61–64% — marginal edge only

### Training Data Gap Analysis (6 Gaps Fixed)
Discovered that pitcher rank signals, coverage_overall, and coverage_recent_10 were never being written to mlb_training_data. Full gap list and fixes:

| Gap | Severity | Fix |
|---|---|---|
| `coverage_overall` + `coverage_recent_10` not in training data | Critical | Added to log_training_data_legs() INSERT |
| `pitcher_era_rank`, `k9_rank`, `whip_rank` not in training data | Critical | Wired from leg dict to training data upsert |
| `coverage_vs_hand` only 57% populated | Medium | Fallback to coverage_overall when None in coverage.py |
| `coverage_recent_5` only 3% populated (deprecated) | Medium | Removed from all INSERTs |
| Pitcher enrichment failures silent | Medium | Added [enrich_legs] failure logging with player/team context |
| Shadow pipeline not at parity | Medium | coverage_recent_5 removed, rank columns added to enriched INSERT |

**Supabase migrations run:**
```sql
ALTER TABLE mlb_training_data ADD COLUMN IF NOT EXISTS coverage_overall double precision;
ALTER TABLE mlb_training_data ADD COLUMN IF NOT EXISTS coverage_recent_10 double precision;
ALTER TABLE mlb_scored_legs ADD COLUMN IF NOT EXISTS pitcher_k9_rank integer;
ALTER TABLE mlb_scored_legs ADD COLUMN IF NOT EXISTS pitcher_whip_rank integer;
ALTER TABLE mlb_scored_legs_enriched ADD COLUMN IF NOT EXISTS pitcher_era_rank integer;
ALTER TABLE mlb_scored_legs_enriched ADD COLUMN IF NOT EXISTS pitcher_k9_rank integer;
ALTER TABLE mlb_scored_legs_enriched ADD COLUMN IF NOT EXISTS pitcher_whip_rank integer;
```

### Prop-Specific Pitcher Signal Routing (Shadow Only)
Implemented isolated pitcher signal routing in enriched_scorer.py based on prop type:

| Prop | Signal | Cap | Rationale |
|---|---|---|---|
| Total Bases under 1.5 | WHIP rank only | ±5 | WHIP = hits+walks/IP, most direct TB signal |
| Strikeouts over 0.5 | K/9 rank only | ±5 | K/9 literally measures strikeout rate |
| Hits over/under 0.5 | ERA + K/9 + WHIP | ±2 each (±6 max) | All three dimensions affect hits |

Also added `whip_adj`, `k9_adj`, `era_adj` columns to training data for future signal validation.

### Total Bases Under 1.5 Added to Coverage Pipeline
TB under was not flowing through the production coverage pipeline at all — it was being fetched from SGO but dropped before coverage was calculated. Fixed by:
- Adding `("totalBases", "under", 1.5)` to ALLOWED_PROPS in main.py
- Adding `production_legs` filter before build_parlays() to exclude TB from production parlays
- TB under now flows through coverage → scoring → mlb_scored_legs → shadow pipeline
- **Result today:** 113 TB under legs scored, 108/113 (95.6%) with pitcher_whip_rank populated

### Bug Fixes
**FK crash on every pipeline run:** `recommendation_logger.py` was trying to write to `mlb_recommendations_deprecated_20260512` (a renamed legacy table). Removed the import and call entirely from main.py. The module is now dead code.

**Shadow pipeline never ran:** The FK crash was happening after production parlays were saved but before the shadow pipeline call, causing every run to error out before reaching run_enriched_pipeline(). Fixed by removing the crash.

**Manual regen exclusion silently failing since June 8:** `get_conn()` uses RealDictCursor which returns dict rows — the exclusion query was using `row[0]` (integer index) which raised KeyError silently. Every manual regen fell back to full pool. Fixed to `row["player_name"]`. First working manual regen confirmed: 20 players excluded, 33 legs dropped, completely different parlays generated.

---

## Commits This Session
- `314c59e` — fix: gap1 - add coverage_overall and coverage_recent_10 to training data upsert
- `76e2090` — fix: gap2 - write pitcher_era_rank, pitcher_k9_rank, pitcher_whip_rank to scored legs and training data
- `14e28e1` — fix: gap3 - fallback coverage_vs_hand to coverage_overall when None
- `546b370` — fix: gap4 - remove deprecated coverage_recent_5
- `587709f` — fix: gap5 - log enrichment failures in enrich_legs with player/team context
- `ae087fe` — feat: shadow - prop-specific pitcher signal routing in enriched scorer
- `7bcfa49` — fix: remove deprecated recommendation_logger write path causing FK crash
- `ead44f8` — feat: add totalBases under 1.5 to coverage pipeline for shadow validation
- `[pending]` — fix: manual regen exclusion - RealDictCursor requires row key not index

---

## Pending Items — Next Session

### 1. Monitor TB Under Validation Data (Highest Priority)
113 TB under legs scored today, 108 with WHIP rank. Need resolved outcomes to validate WHIP signal correlation. Run after ~2 weeks of accumulation:
```sql
SELECT
    CASE
        WHEN pitcher_whip_rank <= 8 THEN '1_elite'
        WHEN pitcher_whip_rank <= 16 THEN '2_above_avg'
        WHEN pitcher_whip_rank <= 24 THEN '3_below_avg'
        ELSE '4_weak'
    END as whip_tier,
    COUNT(*) FILTER (WHERE result IN ('hit','miss')) as resolved,
    (COUNT(*) FILTER (WHERE result = 'hit') * 100.0 /
     NULLIF(COUNT(*) FILTER (WHERE result IN ('hit','miss')), 0))::numeric(5,1) as hit_rate_pct
FROM mlb_training_data
WHERE game_date >= '2026-04-27'
  AND stat = 'totalBases' AND direction = 'under'
  AND result IN ('hit','miss')
  AND pitcher_whip_rank IS NOT NULL
GROUP BY whip_tier ORDER BY whip_tier;
```

### 2. Coverage 85%+ Ceiling (Quick Win)
Training data confirmed 85%+ coverage is a trap — win rates collapse. Add a hard ceiling of 84% to the production coverage gate to stop inflated-coverage legs from polluting the pool. One-line fix in main.py.

### 3. Shadow vs Production Comparison (June 12+)
ERA rank scale and park_factor bugs fixed June 8. Shadow pipeline now running cleanly. After 3+ days of clean data, compare shadow vs production win rates:
```sql
SELECT 'production' as pipeline,
    COUNT(*) FILTER (WHERE outcome = 'won') as won,
    COUNT(*) FILTER (WHERE outcome IN ('won','lost')) as resolved,
    (COUNT(*) FILTER (WHERE outcome = 'won') * 100.0 /
     NULLIF(COUNT(*) FILTER (WHERE outcome IN ('won','lost')), 0))::numeric(5,1) as win_rate
FROM mlb_parlay_recommendations_v2 WHERE run_date >= '2026-06-09'
UNION ALL
SELECT 'shadow' as pipeline, ...
FROM mlb_parlay_recommendations_enriched WHERE run_date >= '2026-06-09';
```

### 4. Hits Under Score Normalization (After 50+ Resolved Legs)
Under legs scoring 43-61 vs overs scoring 65-81 — losing pool competition. Options:
- Option A: Guaranteed under slots per parlay (1-2)
- Option B: Normalize scores so 40% hitless ≈ 70% hit rate in edge terms
Do not implement before 50+ resolved under outcomes.

### 5. Lineup Confirmation Gate (High Priority)
Volpe-style voids still possible. Blueprint Phase 3 item. Needs main.py + enrich_legs.py.

### 6. TB Under Promotion Decision (Late June)
After WHIP signal validation (~2 weeks data), decide whether to promote TB under to production whitelist. Decision criteria: does elite WHIP tier (rank 1-8) win at 65%+ vs weak WHIP tier (rank 23-30) winning at <55%? If spread ≥10pp, promote.

### 7. SO Enrichment NaN Investigation
~0% NaN today (100% enrichment rate) — this may have been resolved by the pipeline fixes. Confirm over 3+ days before closing.

### 8. Manual Regen Fallback Threshold
Monitor `[manual_regen] Pool too thin` in Railway logs. If firing regularly, raise threshold from 4 to 8-10.

---

## Key Data Findings From This Session

- Clean training data cutoff: **April 27, 2026** — everything before is built on incorrect coverage calculation
- 85%+ coverage bucket: hits over drops to 31.5%, SO over drops to 46.8% — confirmed trap
- TB under 45-54% bucket: 76.0% hit rate on 25 legs — strongest TB signal but small sample
- TB over: no edge at any coverage level, book prices it away completely — excluded permanently
- Pitcher enrichment rate: 52% → 100% after pipeline fixes today
- TB under legs today: 113 scored, avg score 60.8, 95.6% with WHIP rank
- Manual regen working: 20 players excluded, completely different parlay set confirmed

---

## System Health Indicators

### Green Lights
✅ Manual regen player exclusion working (first confirmed run today)
✅ Shadow pipeline running after every production run
✅ Pitcher enrichment 100% (was 52%)
✅ TB under 1.5 flowing through coverage pipeline
✅ Training data now capturing coverage_overall, coverage_recent_10, pitcher rank signals
✅ All 6 training data gaps fixed
✅ FK crash resolved
✅ Prop-specific pitcher signal routing in shadow (WHIP→TB, K9→SO, ERA+K9+WHIP→hits)
✅ 85%+ coverage trap identified and documented (gate fix pending)

### Yellow Flags
⚠️ 85%+ coverage ceiling not yet implemented in production gate
⚠️ TB under not in production parlays yet — awaiting WHIP signal validation
⚠️ Hits under legs not reaching parlays (score normalization needed)
⚠️ No lineup confirmation gate — Volpe-style voids still possible
⚠️ Shadow vs production comparison needs 3+ more days clean data

### Red Flags
None currently

---

**Last Review:** June 9, 2026
**System Status:** ✅ Operational — Training Data Gaps Fixed + TB Under Shadow Validation Active
**Next Review:** June 10, 2026 (Monitor TB under scoring + shadow pipeline + manual regen logs)
**Pending Decisions:** TB under promotion (late June), hits under score normalization (after 50+ resolved legs)
