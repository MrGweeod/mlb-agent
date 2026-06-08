# MLB Parlay Agent — Session Handoff
**Last Updated:** June 8, 2026 (Session 6 — Performance Review + Manual Regen Diversity Fix)

## Current Status
✅ **OPERATIONAL — SESSION 6 DEPLOYED**
✅ **Manual regen player exclusion: prior-run players excluded from Regenerate Now pool**
✅ **Fallback logic: full pool used if exclusion leaves fewer than 4 qualifying legs**
✅ **All Session 5 fixes confirmed in production (pitcher signals, K9 rank, parlay sort)**
✅ **Committed and pushed: `cd52b3a`**

---

## What Happened on June 8, 2026

### June 4 Performance Review
Reviewed parlay outcomes from June 4 (pre-Session 5 baseline):

| Source | Parlays | Won | Lost | Win Rate |
|---|---|---|---|---|
| auto_9am | 3 | 1 | 2 | 33.3% |
| auto_12pm | 4 | 2 | 2 | 50.0% |
| auto_530pm | 2 | 0 | 2 | 0% |
| manual | 7 | 0 | 7 | 0% |

9am and midday beat the ~17-20% breakeven. Evening and manual collapsed primarily due to:
- **Matt Olson** going 0-for-day on hits over 0.5, appearing in 5 of 7 manual parlays
- **Luke Keaschall** 0-for-3 on hits
- **Anthony Volpe** voided in 2 parlays (not in lineup — no lineup confirmation gate)

K9 rank signal partially firing: legs with pitcher data populated showed correct ±5 spread. ~60% of strikeout legs still showing `pitcher_name = NaN` — enrichment gap on those legs.

### Manual Regen Player Exclusion (New Feature)
**Problem:** Hitting Regenerate Now repeatedly returned the same high-score players from the prior automated or manual run, since the full eligible pool was always used.

**Fix:** In `run_pipeline()` in `main.py`, when `source == "manual"`:
1. Queries `mlb_parlay_legs_v2` for distinct player names from the most recent batch today
2. Filters those players out of `qualifying_legs` before `build_parlays()` is called
3. Falls back to full pool if fewer than 4 legs remain after exclusion (logs `[manual_regen] Pool too thin`)
4. Automated pipeline runs (9am, 12pm, 5:30pm) are completely untouched — full pool always

**Commit:** `cd52b3a` — `feat: exclude prior-run players from manual regen pool`

**Edge case to know:** First manual regen of the day (before any auto pipeline) finds no prior batch — `excluded_players` is empty, full pool used. Exclusion only starts firing on the second manual regen or after an auto pipeline has run. This is correct behavior.

---

## Pending Items — Next Session

### 1. Monitor Manual Regen Fallback Threshold
Current fallback threshold is `>= 4 legs`. With a 4-leg parlay structure that's the absolute minimum — if the pool is exactly 4 legs there's likely only one valid combination. If Railway logs show `[manual_regen] Pool too thin` firing regularly, consider raising the threshold to 8-10.

Watch for in Railway logs:
```
[manual_regen] Excluding N players from last run: [...]
[manual_regen] Pool after exclusion: N legs (was N)
[manual_regen] Pool too thin after exclusion (N legs) — falling back to full pool
```

### 2. Strikeout Leg NaN Pitcher Enrichment (~60% of SO legs)
June 4 data showed ~60% of strikeout legs with `pitcher_name = NaN`. These legs are missing K9 rank signal entirely. Investigate whether this is a timing issue (lineups not confirmed at pipeline run time), a game_pk mismatch, or an enrichment step ordering problem.

Query to check on any run date:
```sql
SELECT
    COUNT(*) as total_so_legs,
    COUNT(pitcher_name) as with_pitcher,
    COUNT(*) - COUNT(pitcher_name) as missing_pitcher,
    (COUNT(pitcher_name) * 100.0 / COUNT(*))::numeric(5,1) as pct_enriched
FROM mlb_scored_legs
WHERE run_date = (CURRENT_DATE)::text
  AND stat = 'strikeouts'
  AND line = 0.5
  AND position NOT IN ('SP','RP','P');
```

### 3. ERA Rank Signal Re-Evaluation (June 12+)
IP threshold fixed June 5 — ERA ranking pool now has 192 qualified starters. After 7+ days of clean data:
- Re-run ERA tier win rate analysis on `mlb_scored_legs_enriched`
- If directionally correct (ace ERA → lower hits over win rate), add back to enriched scorer for hits props

### 4. Shadow vs Production Comparison (June 12+)
```sql
SELECT
    'production' as pipeline,
    COUNT(*) FILTER (WHERE outcome = 'won') as won,
    COUNT(*) FILTER (WHERE outcome IN ('won','lost')) as resolved,
    (COUNT(*) FILTER (WHERE outcome = 'won') * 100.0 /
     NULLIF(COUNT(*) FILTER (WHERE outcome IN ('won','lost')), 0))::numeric(5,1) as win_rate
FROM mlb_parlay_recommendations_v2
WHERE run_date >= '2026-06-05'
UNION ALL
SELECT
    'shadow' as pipeline,
    COUNT(*) FILTER (WHERE outcome = 'won') as won,
    COUNT(*) FILTER (WHERE outcome IN ('won','lost')) as resolved,
    (COUNT(*) FILTER (WHERE outcome = 'won') * 100.0 /
     NULLIF(COUNT(*) FILTER (WHERE outcome IN ('won','lost')), 0))::numeric(5,1) as win_rate
FROM mlb_parlay_recommendations_enriched
WHERE run_date >= '2026-06-05';
```

### 5. Hits Under 0 Appearances in Pool
No hits under legs reaching the builder on recent slates. Investigate whether 70% coverage gate is too strict for this prop or if there simply aren't enough qualifying legs on typical slates.

### 6. Negative EV Legs in Parlay Selection
Legs like Alex Bregman -244 (EV=-20.9%) still appearing. Selection is by composite score, not EV. After 30+ days of outcome data on the new system, evaluate a minimum EV gate.

### 7. Lineup Confirmation Gate
Anthony Volpe's void on June 4 (not in lineup) highlights the lack of a lineup confirmation check. Players not in the confirmed lineup should be excluded from the pool. This was in the original blueprint as a Phase 3 item — worth prioritizing given demonstrated impact.

### 8. Health Check Threshold Update (Low Priority)
Flags hit rate >58% as anomalous. With 65%+ coverage gate, expected range is 63-75%. Update threshold to avoid misleading log warnings.

### 9. Dead ERA Adjustment Cleanup in `simple_scorer.py` (Low Priority)
Raw `pitcher_era` block for hits props still exists but validated as directionally unreliable. Remove after ERA rank signal is re-validated with clean data.

### 10. `won_with_void` Outcome Tracking (Low Priority)
Still not implemented.

---

## Key Data Findings From This Session

- June 4 auto_9am: 33.3% win rate, auto_12pm: 50.0% — both above breakeven
- Manual parlays (7): 0% — driven by Olson/Keaschall hits misses and Volpe void saturation
- Prior-run player repetition confirmed as root cause of manual regen quality collapse
- Fallback threshold of 4 legs is a floor — may need raising if thin-slate fallback fires often

---

## Commits This Session
- `cd52b3a` — feat: exclude prior-run players from manual regen pool

---

## System Health Indicators

### Green Lights
✅ Manual regen player exclusion deployed with fallback
✅ Bug 1 fixed — batter SO legs fully enriched
✅ Pitcher IP threshold fixed — 192 qualified starters
✅ Opposing pitcher ranks attached to hitter legs
✅ K9 rank signal firing in simple_scorer
✅ Parlay builder score-sort + MAX_CANDIDATES 50
✅ Shadow resolution backfilled and ongoing
✅ Park factor signal validated and active
✅ All changes committed and pushed

### Yellow Flags
⚠️ ~60% of SO legs still missing pitcher enrichment (NaN pitcher_name)
⚠️ ERA rank signal needs re-evaluation with clean data (7+ days post IP-fix)
⚠️ 0 hits under legs in recent pools — investigate coverage gate
⚠️ Negative EV legs appearing in parlays
⚠️ No lineup confirmation gate — Volpe-style voids still possible
⚠️ Health check hit rate threshold stale

### Red Flags
None currently

---

**Last Review:** June 8, 2026
**System Status:** ✅ Operational — Manual Regen Diversity + Full Signal Pipeline
**Next Review:** June 9, 2026 (Monitor manual regen exclusion logs + SO enrichment rates)
**Pending Code Changes:** Lineup confirmation gate, SO enrichment investigation, ERA rank revalidation, health check threshold, dead ERA cleanup
