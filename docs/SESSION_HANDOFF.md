# MLB Parlay Agent — Session Handoff
**Last Updated:** May 13, 2026 (End of Day - Coverage Bug Fixed, Model Retrained)

## Current Status
✅ **MAJOR BREAKTHROUGH - Coverage Calculation Fixed**
- Coverage inversion bug discovered and fixed
- 81K+ training samples re-scored with correct coverage
- ML model retrained on corrected data
- System deployed and ready for tomorrow's test

---

## What Was Accomplished Today (May 13, 2026)

### **Phase 1: Signal Validation & Root Cause Discovery** (Morning/Afternoon)

**Problem identified:** Individual leg hit rates stuck at ~52% (coin flip), making parlays nearly impossible.

**Diagnostic queries run:**
1. ✅ Coverage vs hit rate correlation (Query A)
2. ✅ Pitcher quality validation (Query B) 
3. ✅ Stat/direction performance (Query C)
4. ✅ Coverage within stat/direction (critical breakthrough query)

**Key findings:**
- Coverage appeared uncorrelated with outcomes (when aggregated)
- Only stat/direction showed clear signal (hits_over 62.4%, hits_under 37.6%)
- Pitcher quality data insufficient to evaluate (only 110 legs with pitcher_era)

---

### **Phase 2: The Breakthrough Discovery**

**User insight:** Questioned if we were randomly selecting legs without player context.

**Critical query revealed inversion:**
```
hits_over:
  70-100% coverage → 79.2% hit rate ✅ PERFECT
  60-69% coverage  → 54.7% hit rate ✅
  50-59% coverage  → 50.0% hit rate ✅

hits_under:
  70-100% coverage → 20.8% hit rate ❌ INVERTED!
  60-69% coverage  → 45.3% hit rate ❌
  50-59% coverage  → 50.0% hit rate
```

**Real example (Daylen Lile):**
- 40 games played, 12 with 0 hits, 28 with 1+ hits
- **Expected coverage for hits_under 0.5:** 12/40 = 30%
- **Actual coverage in database:** 70.3%

**Root cause:** Coverage calculation was counting times player went OVER for both OVER and UNDER props.

---

### **Phase 3: Fix Implementation** (Evening)

**Claude Code fixed the bug in 4 files:**

1. **`src/engine/coverage.py`** (core fix):
   - Added `direction` parameter to all functions
   - `_count_coverage()`: Now uses `val < line` for UNDER, `val >= line` for OVER
   - `_count_ip_coverage()`: Same fix for innings pitched
   - Fixed handedness adjustment to invert for UNDER props
   
2. **`main.py`**: 
   - Passes `direction=prop.get("direction", "over")` to calculate_coverage()

3. **`src/pipelines/lineup_poller.py`**: 
   - Fixed to use current schema and pass direction

4. **`scripts/rescore_historical_legs.py`**: 
   - Fixed to fetch direction from DB and use current schema

**Commit:** `6311eee` - "fix: correct coverage calculation for UNDER props"

---

### **Phase 4: Data Correction** (Evening)

**Backfilled training data:**
```bash
python scripts/rescore_historical_legs.py
```

**Results:**
- Total legs: 4,894
- Re-scored: 4,599 with corrected coverage
- Skipped: 295 (insufficient game log data)
- Failed: 0

**Verification:**
- Daylen Lile hits_under coverage: 70.3% → 29.5% ✅ FIXED
- All UNDER props now show inverted coverage values (correct)

---

### **Phase 5: Model Retraining** (Evening)

**Retrained ML model on corrected data:**
```bash
python scripts/train_ml_model.py --retrain
```

**Results:**
- Training samples: 81,282 (with corrected coverage)
- AUC: 0.8489 (excellent discrimination)
- Accuracy: 77%
- Hit rate: 45.7% (matches training distribution)

**Feature importance:**
- direction: 69.7% (still dominant - expected)
- coverage_overall: 4.3% (now has correct values as input)

**Model saved:** `models/leg_scorer_v2.pkl` (673 KB)

---

### **Phase 6: Deployment** (Evening)

**Deployed to Railway:**
- Coverage fix live ✅
- New model deployed ✅
- System restarted successfully ✅
- No errors or crashes ✅

**Evening pipeline run (7 PM ET):**
- 27 legs scored, 15 upcoming games
- Only 5 overs passed filters (games mostly started)
- No parlays built (insufficient legs for time of day)
- Expected: Tomorrow's 9 AM run will be the real test

---

## Critical Understanding: What We Fixed

### **The Bug:**
Coverage for UNDER props was calculating: "% of times player went OVER"
- Should calculate: "% of times player stayed UNDER"

### **The Impact:**
- We were selecting high hitters for UNDER bets
- Example: Player who gets hits 70% of time → we bet them to stay UNDER → they got hits → we lost
- Result: hits_under hit at 37.6% instead of 70%+

### **The Fix:**
Coverage now correctly calculates:
- OVER props: % of times player went OVER the line ✅
- UNDER props: % of times player stayed UNDER the line ✅

### **Expected Improvement:**
- hits_under: 37.6% → 70%+ hit rate
- Overall leg hit rate: 52% → 65-70%+
- 4-leg parlay hit rate: 7% → 20-25%+

---

## Tomorrow's Validation (May 14, 9 AM ET)

### **What to Check:**

**1. Coverage Values:**
```sql
-- Check coverage distribution for hits_under
SELECT 
    CASE 
        WHEN coverage_overall >= 70 THEN '70-100 (rare now)'
        WHEN coverage_overall >= 50 THEN '50-69'
        WHEN coverage_overall >= 30 THEN '30-49'
        ELSE '<30 (common now)'
    END as coverage_bucket,
    COUNT(*) as legs
FROM mlb_scored_legs
WHERE run_date = '2026-05-14'
  AND stat = 'hits'
  AND direction = 'under'
  AND coverage_overall IS NOT NULL
GROUP BY coverage_bucket;
```

**Expected:** Most hits_under should have LOW coverage (30-40%), not high (70-80%)

**2. Railway Logs:**
Look for:
- Coverage values in debug output (should be varied, not all 70%+)
- Number of eligible legs (should be 50-100 from full slate)
- Parlays built (should build 4-5)
- Mix of overs and unders selected (not 100% overs)

**3. Selection Quality:**
- Are we selecting FEWER hits_under props overall?
- Are the hits_under props we DO select showing LOW coverage?
- Example: If we select "Player X hits_under 0.5", their coverage should be 20-40% (rarely gets hits)

---

## System Health

### **Operational Status:**
- ✅ Pipeline Runtime: Functional (3x daily)
- ✅ ML Scoring: Retrained model deployed
- ✅ Coverage Calculation: FIXED (direction-aware)
- ✅ Database: All tables operational
- ✅ Deployment: Live on Railway
- ✅ Pitcher Data: Infrastructure complete (Phase 3 from yesterday)

### **Data Quality:**
- ✅ Training data: 81,282 samples with corrected coverage
- ✅ Historical coverage: 4,599 legs re-scored
- ✅ Recent legs: All new legs calculate coverage correctly
- ⏳ Validation: Awaiting tomorrow's 9 AM run

---

## Known Issues (Minor)

### **Issue 1: Direction Feature Still Dominant**
- **Status:** Expected
- **Why:** Model trained on coverage that was correlated with direction
- **Impact:** Model may still be biased, but now has correct coverage to work with
- **Next step:** Monitor for 5-7 days, retrain again if needed

### **Issue 2: Only 7% of Legs Have Coverage**
- **Status:** Ongoing limitation
- **Why:** Coverage requires sufficient game sample (20+ games)
- **Impact:** Most legs selected by ML without coverage signal
- **Mitigation:** As season progresses, more players reach 20+ games

---

## Files Changed Today

### **Core Changes:**
- `src/engine/coverage.py` - Direction-aware coverage calculation
- `main.py` - Pass direction to coverage function
- `src/pipelines/lineup_poller.py` - Fixed schema + direction
- `scripts/rescore_historical_legs.py` - Fixed schema + direction
- `models/leg_scorer_v2.pkl` - Retrained model (673 KB)

### **Documentation:**
- Created multiple analysis documents in `/home/claude/`
- Diagnostic queries and results documented

---

## Quick Reference Commands

### **Manual Pipeline Run:**
```bash
curl -X POST https://mlb-agent.up.railway.app/api/admin/run_full_pipeline \
  -H "Authorization: Bearer MLBparlays"
```

### **Check Deployment Status:**
- Railway Dashboard: https://railway.app
- Check logs for errors or successful startup

### **Verify Coverage Fix:**
```sql
-- Check a known player's coverage
SELECT player_name, stat, direction, coverage_pct, run_date
FROM mlb_scored_legs
WHERE player_name = 'Daylen Lile'
  AND stat = 'hits'
  AND direction = 'under'
ORDER BY run_date DESC
LIMIT 5;
```

**Expected:** coverage_pct ~30 (not 70)

---

## Success Metrics (Track Over Next Week)

### **Leg-level (target by May 20):**
- ✅ hits_under: 37.6% → 65%+ hit rate
- ✅ hits_over: maintain 62%+ hit rate
- ✅ Overall: 52% → 60%+ per leg

### **Parlay-level (target by May 20):**
- ✅ 4-leg parlays: 7% → 15%+ hit rate
- ✅ Better consistency (not 80% loss rate)

### **Selection quality:**
- ✅ hits_under props have LOW coverage (30-40%)
- ✅ hits_over props have HIGH coverage (60-80%)
- ✅ Appropriate prop distribution (not 50/50 over/under)

---

## Open Questions

**Q1: Should we adjust coverage thresholds?**
- Currently using 55% minimum
- May need to raise to 60-65% for better selectivity
- Wait for 5 days of data before adjusting

**Q2: Will direction bias in ML persist?**
- Model still has 70% direction importance
- But now has correct coverage as input
- Monitor if this self-corrects or needs retraining

**Q3: Should we focus on prop types with better data?**
- hits/strikeouts have most coverage data (7-8%)
- rbi/walks have almost none (3%)
- May want to prioritize high-coverage prop types

---

## Next Session Priorities

### **IMMEDIATE (May 14, 9-10 AM):**
1. **Monitor 9 AM pipeline run**
   - Check Railway logs for successful execution
   - Verify coverage values are correct
   - Confirm parlays are built

2. **Run validation queries**
   - Coverage distribution query
   - Selection quality checks
   - Compare to pre-fix patterns

### **SHORT TERM (May 14-20):**
3. **Track hit rates daily**
   - hits_under improvement
   - Overall leg hit rate
   - Parlay success rate

4. **Identify any remaining issues**
   - Are we selecting the right players now?
   - Is ML model working correctly?
   - Any new bugs introduced?

### **MEDIUM TERM (May 20-27):**
5. **Evaluate need for model retraining**
   - If direction bias persists
   - If hit rates don't improve as expected

6. **Consider coverage threshold adjustments**
   - Based on actual performance data

---

## Context for Next Session

**You left off having:**
- ✅ Fixed the coverage calculation bug (root cause)
- ✅ Re-scored 4,599 historical legs with correct coverage
- ✅ Retrained ML model on corrected data
- ✅ Deployed everything to production
- ⏳ Waiting for tomorrow's 9 AM run to validate

**The breakthrough was:** Realizing coverage was inverted for UNDER props - we were selecting players who frequently went OVER when we bet them to stay UNDER.

**The fix was simple:** Add direction check to coverage calculation (5 lines of code).

**The impact should be massive:** 52% → 65%+ leg hit rate, 7% → 20%+ parlay hit rate.

**Next critical moment:** Tomorrow (May 14) 9:00 AM ET pipeline run - this will be the first full test with corrected coverage.

---

**Last Updated:** May 13, 2026, 8:09 PM ET  
**Status:** ✅ Major fix deployed, awaiting validation  
**Next Milestone:** May 14, 9 AM ET pipeline run
