# MLB Parlay Agent — Build Status
**Last Updated:** May 13, 2026 (End of Day - Coverage Bug Fixed)

## Overall System Status: ✅ FULLY OPERATIONAL + MAJOR FIX DEPLOYED
┌────────────────────────────────────────────────────────────┐
│              SYSTEM HEALTH DASHBOARD                       │
├────────────────────────────────────────────────────────────┤
│ Coverage Calculation:  ✅ FIXED (direction-aware)          │
│ ML Model:              ✅ RETRAINED (corrected data)       │
│ Pipeline Runtime:      ✅ OPERATIONAL (3x daily)           │
│ Database:              ✅ OPERATIONAL                      │
│ Deployment:            ✅ LIVE (Railway)                   │
│ Next Critical Test:    ⏳ May 14, 9 AM ET                  │
└────────────────────────────────────────────────────────────┘

---

## Today's Major Accomplishment

### 🎉 Coverage Inversion Bug Fixed

**Problem:** Coverage for UNDER props was inverted
- Calculated: % times player went OVER
- Should calculate: % times player stayed UNDER

**Example (Daylen Lile):**
- 40 games: 12 with 0 hits, 28 with 1+ hits  
- Before: coverage = 70.3% (wrong - counting times he got hits)
- After: coverage = 29.5% (correct - counting times he stayed under)

**Impact:** We were selecting high hitters for UNDER bets → they got hits → we lost

**Fix:** Added direction parameter to coverage calculation
- Commit: `6311eee`
- Files changed: 4 (coverage.py, main.py, lineup_poller.py, rescore script)
- Lines changed: ~80

---

## Component Status

### **1. Coverage Calculation** ✅ FIXED

**What was broken:**
```python
# BEFORE (wrong)
coverage = times_player_went_over / total_games  # Always counted overs

# AFTER (fixed)
if direction == "over":
    coverage = times_player_went_over / total_games
elif direction == "under":
    coverage = times_player_stayed_under / total_games
```

**Verification:**
- Backfilled 4,599 historical legs
- Daylen Lile: 70.3% → 29.5% ✅
- All UNDER props now show correct (inverted) values

**Status:** ✅ Fixed and deployed

---

### **2. ML Model** ✅ RETRAINED

**Model:** `leg_scorer_v2.pkl` (673 KB)
**Training data:** 81,282 samples with corrected coverage
**Trained:** May 13, 2026, 6:30 PM ET

**Metrics:**
- AUC: 0.8489 (excellent)
- Accuracy: 77%
- Hit rate: 45.7%

**Feature importance:**
- direction: 69.7% (still dominant - known issue)
- coverage_overall: 4.3% (now with correct values)
- strikeouts: 5.3%

**Status:** ✅ Retrained and deployed

---

### **3. Pipeline Execution** ✅ OPERATIONAL

**Schedule:**
- 9:00 AM ET - Morning (resolution + full fetch/score/build)
- 12:00 PM ET - Midday (targeted refresh)
- 5:30 PM ET - Evening (targeted refresh)

**Latest run:** May 13, 7:01 PM ET (evening catch-up)
- Deployed with new model
- 27 legs scored, 15 upcoming
- 5 overs passed filters
- 0 parlays built (most games started - expected at 7 PM)

**Status:** ✅ Operational, awaiting tomorrow's full test

---

### **4. Database** ✅ OPERATIONAL

**Tables:**
- mlb_scored_legs: 4,894 total (4,599 with corrected coverage)
- mlb_training_data: 81,282 samples (corrected)
- mlb_parlay_recommendations_v2: Active
- mlb_parlay_legs_v2: Active

**Recent changes:**
- coverage_pct values updated for UNDER props
- Daylen Lile and similar players now show correct low coverage

**Status:** ✅ All tables operational

---

### **5. Deployment** ✅ LIVE

**Platform:** Railway
**Latest deploy:** May 13, 2026, 6:45 PM ET
**Commit:** `6311eee` + model file

**Health:**
- No errors on startup ✅
- Model loaded successfully ✅
- Coverage fix active ✅
- Evening pipeline executed ✅

**Status:** ✅ Deployed and running

---

## Expected Improvements (Track May 14-20)

### **Leg-Level:**
| Metric | Before | Expected | Target Date |
|--------|--------|----------|-------------|
| hits_under | 37.6% | 65-70% | May 20 |
| hits_over | 62.4% | 62-65% | May 20 |
| Overall | 52% | 60-65% | May 20 |

### **Parlay-Level:**
| Metric | Before | Expected | Target Date |
|--------|--------|----------|-------------|
| 4-leg hit rate | 7% | 15-20% | May 20 |
| 5-leg hit rate | 4% | 10-15% | May 20 |

### **Selection Quality:**
- hits_under props should have LOW coverage (30-40%), not high (70%+)
- Fewer total hits_under props selected
- Better mix of prop types

---

## Validation Plan (May 14, 9 AM)

### **1. Check Railway Logs:**
```
Expected:
- 200-300 legs scored (full slate)
- Coverage values varied (not all 70%+)
- 50-100 eligible legs after filters
- 4-5 parlays built
- Mix of overs and unders
```

### **2. Run Database Queries:**
```sql
-- Coverage distribution for hits_under (should be LOW now)
SELECT 
    CASE 
        WHEN coverage_overall >= 70 THEN '70-100 (rare)'
        WHEN coverage_overall >= 50 THEN '50-69'
        WHEN coverage_overall >= 30 THEN '30-49'
        ELSE '<30 (common)'
    END as coverage_bucket,
    COUNT(*) as legs
FROM mlb_scored_legs
WHERE run_date = '2026-05-14'
  AND stat = 'hits'
  AND direction = 'under'
  AND coverage_overall IS NOT NULL
GROUP BY coverage_bucket;
```

### **3. Verify Selection Quality:**
- Pick 3 hits_under props that were selected
- Manually check their game logs
- Confirm they actually have LOW hit rates (stay under frequently)

---

## Known Issues

### **Issue 1: Direction Feature Still Dominant**
- **Severity:** Low (expected with current data)
- **Description:** ML model still relies 70% on direction feature
- **Why:** Coverage was correlated with direction in training
- **Mitigation:** Monitor for 7 days, retrain if needed
- **Status:** Monitoring

### **Issue 2: Low Coverage Population (7%)**
- **Severity:** Low (improves over season)
- **Description:** Only 7% of legs have coverage_overall calculated
- **Why:** Requires 20+ games, early in season
- **Impact:** Most selection still relies on ML
- **Status:** Expected, will improve

### **Issue 3: Evening Pipeline Insufficient Legs**
- **Severity:** None (expected behavior)
- **Description:** 7 PM run only found 5 eligible legs
- **Why:** Most games already started by evening
- **Status:** Expected, not a bug

---

## Success Criteria (May 14, 9 AM Run)

✅ **Pipeline completes successfully**
✅ **200-300 legs scored from full slate**
✅ **Coverage values show correct distribution**
✅ **hits_under props have LOW coverage (30-40%)**
✅ **4-5 parlays built**
✅ **No errors or crashes**

---

## Working Well - Don't Change

| Component | Status | Evidence |
|-----------|--------|----------|
| Coverage calculation | Fixed ✅ | Daylen Lile 70% → 30% |
| ML model retraining | Working ✅ | AUC 0.85, no errors |
| Database connectivity | Stable ✅ | No connection errors |
| Deployment pipeline | Reliable ✅ | Auto-deploy working |
| Game start filter | Accurate ✅ | Correctly filtered 12 started games |
| Pitcher data infrastructure | Complete ✅ | Phase 3 from yesterday |

---

## Priority Matrix (Next Week)

| Priority | Item | Effort | Expected Impact |
|----------|------|--------|-----------------|
| HIGH | Validate coverage fix works | 2 hours | Confirm 52%→60%+ improvement |
| HIGH | Monitor hit rates daily | 15 min/day | Track improvement trend |
| MEDIUM | Adjust coverage thresholds | 2 hours | Fine-tune selection if needed |
| MEDIUM | Address direction bias | 4-6 hours | Retrain if improvement insufficient |
| LOW | Expand coverage to more stats | 4 hours | Increase coverage population |

---

**Last Review:** May 13, 2026, 8 PM ET  
**Next Review:** May 14, 2026, 9:30 AM ET (after morning pipeline)  
**Major Milestone:** Coverage inversion bug fixed - first major breakthrough since launch
