# MLB Parlay Agent — Session Handoff
**Last Updated:** June 8, 2026 (Session 7 — Performance Analysis + Hits Under Pipeline Fix)

## Current Status
✅ **OPERATIONAL — SESSION 7 DEPLOYED**
✅ **Direction-aware coverage gate: unders use 40% floor, overs use 65% floor**
✅ **Direction-aware parlay builder score floor: unders use 40.0, overs use 65.0**
✅ **Shadow ERA rank normalization: blended_era_rank now 1-30 scale (was 1-192)**
✅ **park_factor now persisted to mlb_parlay_legs_enriched (was always NULL)**
✅ **WHIP rank signal added to simple_scorer.py for hits props (±5)**
✅ **870 historical shadow legs backfilled with park_factor (819 + 51 ATH/AZ fix)**
✅ **Backfill script rewritten: game_pk map (1 API call/game) + ABR_ALIASES**

---

## What Happened on June 8, 2026 (Session 7)

### Performance Review — June 5–7
Reviewed 3-day parlay and leg performance post-Session 5 signal fixes:

**Parlay win rates:**
| Date | Production | Shadow |
|---|---|---|
| 6/5 | 20.0% | 20.0% |
| 6/6 | 25.0% | 16.7% |
| 6/7 | 20.0% | 20.0% |

Shadow not beating production yet — blocked by ERA rank scale bug and park_factor NULL bug (both fixed this session).

**Leg win rates (June 5–7):**
| Stat | Direction | Win Rate | Notes |
|---|---|---|---|
| strikeouts | over | **80.6%** | Strong — well above 69% baseline |
| hits | over | 53.4% | Below breakeven — primary loss driver |
| hits | under | 0% | Only 1 leg in 3 days — gate was broken |

**Coverage bucket analysis revealed hits over signal is broken in 70-74% bucket:**
- 75-79% coverage: 61.5% win rate
- 70-74% coverage: **45.2% win rate** ← below breakeven, inverted
- 65-69% coverage: 53.7% win rate

The 70-74% bucket is where Soto, Steer, Bregman clustered — all going hitless (actual_value = 0.00 for every losing leg).

### Root Cause: Hits Under Gate Was Structurally Broken
`coverage_overall >= 65%` is impossible for hits under — a healthy MLB hitter goes hitless in only 27-35% of games. No hitter can ever clear 65% hitless rate. Result: 1 hits under leg across 3 days of data.

**Fix 1 — `main.py` direction-aware gate:**
```python
# Over: 65% floor (unchanged)
if direction == "over" and coverage_overall_raw < 65.0:
    continue
# Under: 40% floor (~.240 BA hitter, genuinely weak)
if direction == "under" and coverage_overall_raw < 40.0:
    continue
```

**Fix 2 — `parlay_builder.py` direction-aware score floor:**
```python
MIN_COV_POOL_UNDER = 40.0
floor = MIN_COV_POOL_UNDER if direction == "under" else MIN_COV_POOL
if score < floor:
    continue
```

**Result:** Today's pipeline: 30 overs + 30 unders = 60 eligible legs. Gate working. Unders still not appearing in final parlays — they score 43-61 vs overs scoring 65-81, lose pool competition on raw score. Decided to wait for validation data before normalizing scores across directions.

### Shadow Pipeline Bugs Fixed
Three bugs found in shadow pipeline via diagnostic queries:

**Bug 1 — `blended_era_rank` scale was 1-192, not 1-30**
Pool size grew to 192 qualified starters but normalization used `n=192` for both season rank and recent form rank. ERA bucket thresholds (elite ≤10, avg 11-20, weak 21+) were meaningless. Fixed in `enriched_scorer.py` — all 4 return paths now normalize to 1-30.

**Bug 2 — `park_factor` not written to `mlb_parlay_legs_enriched`**
Column was missing from INSERT statement in `run_enriched_pipeline.py`. `park_adjustment` was stored but `park_factor` (the raw integer) was not. Fixed — column added to INSERT.

**Bug 3 — `recent_form_rank` NULL for reliever/no-start paths**
Three early-return paths in `_compute_blended_era_rank()` were returning raw `float(era_rank)` on the 1-192 scale. All fixed to normalize to 1-30.

### Backfill
- 870 historical `mlb_parlay_legs_enriched` rows backfilled with `park_factor`
- Original script had per-leg API calls — rewrote to game_pk map (1 call per unique game)
- ABR_ALIASES added: `ATH → OAK`, `AZ → ARI`
- Final result: 870/870 updated, 0 skipped

### WHIP Signal Added to Production Scorer
`opp_pitcher_whip_rank` was already attached to all hitter legs but not used for hits props. Added to `simple_scorer.py`:
- Rank 1 (elite, low WHIP) → -5 for over, +5 for under
- Rank 15 (average) → 0
- Rank 30 (poor, high WHIP) → +5 for over, -5 for under
- Formula: `(whip_rank - 15.5) / 2.9`, capped ±5, inverted for unders

---

## Pending Items — Next Session

### 1. Monitor Hits Under Validation Data (Highest Priority)
Under legs are now in the pool and being scored. Need outcome data to validate the signal before normalizing scores. Run daily:
```sql
SELECT
    player_name, stat, direction,
    coverage_overall, composite_score,
    result, actual_value,
    pitcher_name, pitcher_whip
FROM mlb_scored_legs
WHERE run_date >= '2026-06-08'
  AND stat = 'hits' AND direction = 'under'
  AND result IN ('won', 'lost')
ORDER BY run_date DESC, composite_score DESC;
```
After 50+ resolved legs: evaluate whether WHIP correlates with win rate and whether score normalization is justified.

### 2. Shadow Pipeline Signal Re-Evaluation (June 12+)
ERA rank and park factor bugs are now fixed. After 3+ days of clean shadow data:
- Re-run ERA tier win rate analysis with corrected 1-30 buckets
- Re-run park factor bucket analysis with populated data
- Compare shadow vs production win rates

```sql
SELECT
    CASE
        WHEN le.blended_era_rank <= 10 THEN 'elite (1-10)'
        WHEN le.blended_era_rank <= 20 THEN 'avg (11-20)'
        ELSE 'weak (21-30)'
    END as era_bucket,
    le.stat, le.direction,
    COUNT(*) FILTER (WHERE le.outcome IN ('won','lost')) as resolved,
    (COUNT(*) FILTER (WHERE le.outcome = 'won') * 100.0 /
     NULLIF(COUNT(*) FILTER (WHERE le.outcome IN ('won','lost')), 0))::numeric(5,1) as win_rate
FROM mlb_parlay_legs_enriched le
JOIN mlb_parlay_recommendations_enriched re ON re.id = le.parlay_id
WHERE re.run_date >= '2026-06-08'
  AND le.blended_era_rank IS NOT NULL
GROUP BY era_bucket, le.stat, le.direction
HAVING COUNT(*) FILTER (WHERE le.outcome IN ('won','lost')) >= 5
ORDER BY le.stat, le.direction, era_bucket;
```

### 3. Hits Under Score Normalization (After Validation)
Under legs currently score 43-61 vs overs scoring 65-81 — overs always win the pool competition. Two options:
- **Option A:** Separate pool slots (1-2 guaranteed under slots per parlay)
- **Option B:** Normalize under scores so 40% hitless ≈ 70% hit rate in edge terms

Decision deferred until 50+ resolved under outcomes validate the signal. Do not implement before validation data exists.

### 4. Lineup Confirmation Gate (High Priority)
Anthony Volpe-style voids still possible — player not in lineup gets voided, killing the parlay. Blueprint Phase 3 item with demonstrated impact. Needs `main.py` + `enrich_legs.py`.

### 5. SO Enrichment NaN Investigation (~60% of SO legs)
~60% of strikeout legs have `pitcher_name = NaN`. K9 rank signal missing for those legs. Investigate timing vs game_pk mismatch.

```sql
SELECT
    COUNT(*) as total_so_legs,
    COUNT(pitcher_name) as with_pitcher,
    (COUNT(pitcher_name) * 100.0 / COUNT(*))::numeric(5,1) as pct_enriched
FROM mlb_scored_legs
WHERE run_date = (CURRENT_DATE)::text
  AND stat = 'strikeouts' AND line = 0.5
  AND position NOT IN ('SP','RP','P');
```

### 6. ERA Rank Re-Evaluation (June 12+)
192 qualified starters now ranked correctly. After 7 days clean post-IP-fix data, re-validate ERA rank signal for hits over props. If directionally correct (elite ERA → lower hits over win rate), add back to enriched scorer.

### 7. Promote Shadow to Production (June 15+)
After ERA rank and park factor signals validate via shadow comparison. Target: mid-June.

### 8. Dead ERA Cleanup in `simple_scorer.py` (Low Priority)
Raw `pitcher_era` block for hits props validated as directionally unreliable. Remove after ERA rank signal re-validates.

### 9. Manual Regen Fallback Threshold Review (Low Priority)
Monitor Railway logs for `[manual_regen] Pool too thin`. If firing regularly, raise threshold from 4 to 8-10.

### 10. Health Check Threshold Update (Low Priority)
Flags hit rate >58% as anomalous. Expected range with 65%+ gate is 63-75%. Update to avoid misleading warnings.

### 11. `won_with_void` Outcome Tracking (Low Priority)
Still not implemented.

---

## Key Data Findings From This Session

- SO over win rate June 5-7: **80.6%** — significantly above 69% baseline, signal is real
- Hits over win rate June 5-7: 53.4% — below breakeven at typical odds
- Hits over 70-74% coverage bucket: **45.2% win rate** — inverted, worst bucket
- All losing hits over legs had actual_value = 0.00 (hitless, not unlucky)
- Losers faced *worse* pitchers on average than winners — ERA not explaining losses
- Under legs today after fix: 41 scored, 30 cleared builder floor, 0 in final parlays (score competition)
- WHIP signal firing correctly on today's under legs: Harrison 1.03 → boost, Abbott 1.44 → boost for over

---

## Commits This Session
- `[pending]` — fix: direction-aware gate + shadow ERA rank normalization + park_factor + WHIP signal
- `[pending]` — fix: backfill script - game_pk map + ABR_ALIASES for ATH/OAK and AZ/ARI
- `[pending]` — fix: direction-aware score floor in parlay builder - unders use 40.0 not 65.0

---

## System Health Indicators

### Green Lights
✅ Direction-aware coverage gate deployed (overs 65%, unders 40%)
✅ Direction-aware parlay builder floor (overs 65.0, unders 40.0)
✅ Hits under legs now scoring and reaching builder pool (30 today)
✅ WHIP rank signal firing for hits props in production
✅ Shadow ERA rank normalized to 1-30 (was 1-192)
✅ park_factor now persisting to mlb_parlay_legs_enriched
✅ 870 historical shadow legs backfilled with park_factor
✅ Backfill script: game_pk map + ABR_ALIASES (ATH/AZ)
✅ Manual regen player exclusion with fallback
✅ SO over signal strong: 80.6% win rate June 5-7
✅ All changes committed and pushed

### Yellow Flags
⚠️ Hits under legs not reaching parlays yet (score normalization needed — awaiting validation data)
⚠️ Hits over 70-74% coverage bucket underperforming (45.2% win rate)
⚠️ ~60% of SO legs still missing pitcher enrichment (NaN pitcher_name)
⚠️ ERA rank signal needs 3+ days clean shadow data post-fix
⚠️ No lineup confirmation gate — Volpe-style voids still possible
⚠️ Negative EV legs appearing in parlays
⚠️ Health check hit rate threshold stale

### Red Flags
None currently

---

**Last Review:** June 8, 2026
**System Status:** ✅ Operational — Hits Under Pipeline Unblocked + Shadow Fixes
**Next Review:** June 9, 2026 (Monitor hits under outcomes + shadow ERA rank buckets)
**Pending Decisions:** Hits under score normalization (after 50+ resolved legs), shadow promotion (June 15+)
