# MLB Parlay Agent — Session Handoff
**Last Updated:** May 19, 2026 (End of Day - Player Diversity Constraint Implemented)

## Current Status
✅ **OPERATIONAL - GENERATING 5 PARLAYS SUCCESSFULLY**
✅ **Player Diversity Constraint Active**
✅ **Total Bases Props Added**
✅ **Ready for Multi-Day Performance Monitoring**

---

## What Happened on May 19, 2026

### **Major Feature: Player Diversity Constraint**

**Problem Identified:**
- Analysis of last 14 days showed **65% wipeout rate** when players appeared in 5 parlays
- Example: May 18, Shane McClanahan appeared in all 25 parlays generated that day
- When he lost his leg → ALL 25 parlays lost (0% win rate for the entire day)
- This validated the concentration risk was real and severe

**Solution Implemented:**
- Added player diversity constraint: **max 1 appearance per player per generation run**
- Changed parlay builder from "one B&B pass → pick top 5" to "5 sequential B&B passes with progressive player exclusion"
- Each parlay now uses unique players, eliminating catastrophic correlation risk

**Technical Implementation:**
- Modified `src/engine/parlay_builder.py` to track `used_players` set across parlays
- Filter available legs before each parlay build to exclude already-used players
- After building each parlay, add those players to exclusion set for subsequent parlays

---

### **Bug Fix #1: Only 2 Parlays Building**

**Problem:** After implementing diversity constraint, system only built 2 parlays instead of 5

**Root Cause:** `POOL_SIZE = 50` limited B&B to top 50 legs. After parlays 1-2 used best 8 players, parlay 3 only had access to legs 9-50, which couldn't form valid combinations.

**Solution:** Changed `POOL_SIZE` from static 50 to dynamic (use ALL eligible legs)
- Parlay 3 now has access to all 74 legs minus 8 used players = 66 legs available
- B&B can now find valid combinations for parlays 3-5

---

### **Feature Addition: Total Bases 1.5 Props**

**Why:** Expand leg pool from ~70 to ~105 legs to provide more diversity for parlay construction

**Implementation:**
- Added `"totalBases"` to `ALLOWED_STATS` in `main.py`
- Strict line filter: only 1.5 (no 0.5, 2.5, 3.5, etc.)
- Over 1.5 = player gets 2+ total bases (double, HR, or 2 singles)
- Under 1.5 = player gets 0-1 total bases

**Result:** +33 totalBases legs per day, bringing total eligible from ~48 to ~74

---

### **Odds Range Adjustment**

**Changed:** +1000-1400 → **+900-1500**

**Rationale:** With player diversity constraint, need wider range for B&B to find valid combinations after best legs are used in early parlays

---

## System Performance After All Changes

### **Latest Run (May 19, 9:45 PM ET)**

**Parlay Generation:**
```
[parlay_builder] 74 eligible legs → using all 74 for parlay building
[parlay_builder] Built 5 parlays (20 unique players used)

Parlay 1: +1344 | 4 legs | avg cov 76.3%
Parlay 2: +1030 | 4 legs | avg cov 75.0%
Parlay 3: +1205 | 4 legs | avg cov 73.8%
Parlay 4: +1156 | 4 legs | avg cov 72.5%
Parlay 5: +949 | 4 legs | avg cov 71.2%
```

**Leg Pool Quality:**
- Total scored legs: 105
  - hits: 40 legs
  - strikeouts: 30 legs
  - totalBases: 33 legs ✅ NEW
  - walks: 2 legs
- Eligible legs (>= 65% coverage): 74
- Odds distribution: 45 overs + 29 unders

**Player Diversity:**
- ✅ 20 unique players across 5 parlays (4 legs × 5 parlays)
- ✅ No player appears in multiple parlays within same batch
- ✅ Eliminates 65% wipeout risk identified in data analysis

---

## Current System Architecture

### **Daily Pipeline Flow**

**9 AM ET (Morning Pipeline):**
1. Resolve yesterday's outcomes (legs + parlays)
2. Log resolved data to training tables
3. Fetch today's MLB schedule
4. Fetch all player props from SportsGameOdds
5. **Pre-filter:** Only hits 0.5, hitter SO 0.5, pitcher SO 3.5+, walks 0.5, **totalBases 1.5** ✅
6. Calculate coverage (direction-aware, handedness splits)
7. **Coverage gate:** Only legs >= 65% coverage
8. Lineup consistency filter (3+ AB in 7 of 10 games)
9. Enrich with pitcher matchups
10. Score legs (coverage + pitcher opponent adjustment)
11. Filter strikeouts (reliever patterns)
12. **Build 5 parlays with player diversity** (+900 to +1500 odds) ✅

**12 PM ET (Midday Refresh):**
- Skip resolution step
- Fetch fresh props, calculate fresh coverage
- Rescore and rebuild parlays with latest odds
- **Player diversity resets** - players can reappear in new generation run

**5:30 PM ET (Evening Refresh):**
- Same as 12 PM - final refresh before games start
- **Player diversity resets** - players can reappear in new generation run

**Manual Regenerate (Web UI):**
- Same as 12 PM/5:30 PM - triggered by user button
- **Player diversity resets** - players can reappear

---

## Database Tables Status

### **mlb_scored_legs**
- Stores all qualified legs (>= 65% coverage)
- Fields: player_name, stat, line, direction, odds, coverage_pct, composite_score, result
- **New:** totalBases stats now appearing

### **mlb_parlay_recommendations_v2**
- Stores daily parlay recommendations
- Fields: recommendation_date, rank, legs (JSON), combined_odds, win_probability, batch_id
- Used for: Web UI display, outcome resolution, performance tracking

### **mlb_parlay_legs_v2**
- Stores individual legs per parlay
- Fields: parlay_id, player_name, stat, line, direction, odds, outcome
- **Critical:** Used to validate player diversity constraint via queries

### **mlb_training_data**
- Stores all scored legs for future ML model training
- Not currently used for scoring (simple scorer in use)

---

## Key Metrics to Monitor (May 20-25)

### **Player Diversity Validation**

**Query to run daily:**
```sql
-- Should return 0 rows (no player appears in multiple parlays per batch)
WITH player_counts AS (
  SELECT 
    p.batch_id,
    l.player_name,
    COUNT(DISTINCT p.id) as parlay_count
  FROM mlb_parlay_recommendations_v2 p
  JOIN mlb_parlay_legs_v2 l ON l.parlay_id = p.id
  WHERE p.run_date = CURRENT_DATE
  GROUP BY p.batch_id, l.player_name
)
SELECT batch_id, player_name, parlay_count
FROM player_counts
WHERE parlay_count > 1;
```

**Expected result:** 0 rows ✅

---

### **System Health Indicators**

**Green Lights (System Healthy):**
- ✅ 4-5 parlays building per run (not 0-2)
- ✅ All parlays within +900-1500 odds range
- ✅ 100-110 scored legs per day
- ✅ 70-80 eligible legs per day
- ✅ Only hits 0.5, SO (0.5/3.5+), walks 0.5, TB 1.5 in pool
- ✅ No player appears in multiple parlays per batch
- ✅ Pipeline completing in <5 minutes

**Yellow Flags (Monitor Closely):**
- ⚠️ Parlay count drops to 2-3 (may need to widen odds range further)
- ⚠️ Leg pool < 60 or > 120 (filter too strict/loose)
- ⚠️ Pipeline execution > 5 minutes (performance degradation)

**Red Flags (Immediate Action Required):**
- 🔴 0-1 parlays built multiple days in row (system broken)
- 🔴 Player appears 2+ times in same batch (diversity constraint broken)
- 🔴 Unwanted prop types in pool (filters not working)
- 🔴 Pipeline crashes or timeouts (code error)

---

## Working Well - Don't Change

| Component | Status | Evidence |
|-----------|--------|----------|
| Prop filtering | ✅ Excellent | Only 0.5 hits/SO, 3.5+ pitcher SO, 1.5 TB |
| Coverage calculation | ✅ Validated | Direction-aware, handedness splits working |
| Player diversity | ✅ Active | 20 unique players, 0 duplicates per batch |
| Parlay construction | ✅ Operational | Building 5 parlays at +900-1500 |
| Total Bases props | ✅ Working | 33 TB legs adding to diversity |
| Database logging | ✅ Stable | All legs and parlays persisting correctly |
| Web UI | ✅ Functional | All tabs working, Regenerate working |
| Opponent pitcher adjustment | ✅ Keep | Valuable signal, not causing issues |
| Strikeout filters | ✅ Correct | Hitter 0.5, pitcher 3.5+ as designed |
| Lineup consistency | ✅ Working | 70% threshold filtering correctly |

---

## Known Issues (Non-Critical)

### **Issue 1: Scikit-learn Version Warning**

**Observation:** Railway logs show version mismatch warnings (1.7.2 → 1.8.0)

**Impact:** None - models still load and work correctly

**Fix:** Not urgent - can retrain models on 1.8.0 later if needed

---

### **Issue 2: Training Data Resolver Failure Warning**

**Observation:** `RESOLVER FAILURE: 254 props unresolved (>40%) — resolver likely did not run for: 2026-04-02`

**Impact:** Historical data gap for one day in April

**Fix:** Not urgent - backfill script can resolve this later

---

## Next Steps - Monitoring Period (May 20-25)

### **Daily Monitoring Tasks**

**Morning (After 9 AM Run):**
1. Check Railway logs: Did pipeline complete? How many parlays built?
2. Run player diversity validation query (should return 0 rows)
3. Note which players appear across multiple generation runs (expected behavior)

**Evening (After Games Complete):**
1. No action needed - resolution happens next morning

**Next Morning (May 20-25):**
1. Check resolution: How many legs hit? How many parlays won?
2. Track parlay win rate: Expected 15-25% for 4-leg parlays at these coverages
3. Validate player diversity eliminated wipeout risk

---

### **Key Questions to Answer**

**After 5 Days of Data:**

1. **Is player diversity helping?**
   - Compare: May 18 (0 out of 25 parlays won) vs May 20-25 performance
   - Expected: No more total batch wipeouts, higher overall win rate

2. **Are Total Bases props performing well?**
   - Track: TB over vs TB under hit rates
   - Expected: TB 1.5 overs = 45-55%, TB 1.5 unders = 45-55%

3. **Is the +900-1500 range optimal?**
   - Track: Distribution of parlay odds within range
   - Adjust if needed: Can tighten to +1000-1400 if leg pool improves

4. **Are 4-leg parlays the right size?**
   - Track: Win rate for 4-leg parlays
   - Expected: 15-25% win rate
   - If too low: Reduce to 3 legs
   - If too high: Increase to 5 legs

---

## Decision Points After Monitoring

### **If Parlay Win Rate < 10% (Too Low):**
- 🔴 Increase MIN_COVERAGE_PCT to 70% (stricter leg quality)
- 🔴 Consider reducing to 3-leg parlays
- 🔴 Review coverage accuracy - are predictions optimistic?

### **If Parlay Win Rate > 30% (Too High):**
- ✅ System performing better than expected
- Consider: Increase to 5-leg parlays for higher payouts
- Consider: Tighten odds range to +1200-1600

### **If Player Diversity Causes Issues:**
- If same players winning across multiple runs → diversity is working correctly
- If diversity forcing use of bad legs → review data (unlikely based on May 19 data)
- Only revert diversity constraint if clear evidence it's hurting performance

---

## Environment & Infrastructure

**Deployment:** Railway (Hobby plan, $5/month)
- Auto-deploy on push to `master`
- Scheduler runs 3x daily (9 AM, 12 PM, 5:30 PM ET)
- Web UI: https://mlb-agent.up.railway.app

**Database:** Supabase PostgreSQL (Free tier)
- Tables: mlb_scored_legs, mlb_parlay_recommendations_v2, mlb_parlay_legs_v2, mlb_training_data
- Connection via DATABASE_URL environment variable

**APIs:**
- SportsGameOdds: Props and odds (Free tier, 100K objects/month)
- MLB-StatsAPI: Game logs, schedule, transactions (Free, no key required)

**Code Repository:** GitHub - github.com/MrGweeod/mlb-agent

---

## Quick Commands

### **Check System Status**
```bash
railway logs --follow
```

### **Manual Pipeline Trigger**
- Web UI: Click "Regenerate Now" button
- Or: `curl -X POST https://mlb-agent.up.railway.app/api/refresh -H "Authorization: Bearer MLBparlays"`

### **Validate Player Diversity**
```sql
-- Run after each generation - should return 0 rows
SELECT p.batch_id, l.player_name, COUNT(DISTINCT p.id) as appearances
FROM mlb_parlay_recommendations_v2 p
JOIN mlb_parlay_legs_v2 l ON l.parlay_id = p.id
WHERE p.run_date = CURRENT_DATE
GROUP BY p.batch_id, l.player_name
HAVING COUNT(DISTINCT p.id) > 1;
```

### **Check Today's Parlays**
```sql
SELECT p.rank, p.total_odds, p.outcome,
       l.player_name, l.stat, l.direction, l.line
FROM mlb_parlay_recommendations_v2 p
JOIN mlb_parlay_legs_v2 l ON l.parlay_id = p.id
WHERE p.run_date = CURRENT_DATE
ORDER BY p.rank, l.id;
```

---

## Contact for Next Session

**What to bring to next chat:**
1. Hit rate data from May 20-25 (overall and per stat type)
2. Parlay win rate data with comparison to May 18 baseline
3. Player diversity validation - any duplicates found?
4. Any errors or anomalies in Railway logs

**Questions to answer:**
- Did player diversity eliminate wipeout events?
- Are Total Bases props performing as expected?
- Is the +900-1500 odds range optimal?
- Should we adjust parlay leg count (3, 4, or 5)?

---

**Last Review:** May 19, 2026, 10:00 PM ET  
**System Status:** ✅ Operational - Generating 5 Parlays with Player Diversity  
**Next Review:** May 25, 2026 (After 5 days of monitoring data)  
**Major Milestone:** Player diversity constraint successfully implemented and validated
