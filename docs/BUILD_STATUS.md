# MLB Parlay Agent — Build Status
**Last Updated:** May 14, 2026 (End of Day - Prop Filtering Deployed)

## Overall System Status: ✅ FULLY OPERATIONAL + FILTERS DEPLOYED
┌────────────────────────────────────────────────────────────┐
│              SYSTEM HEALTH DASHBOARD                       │
├────────────────────────────────────────────────────────────┤
│ Coverage Calculation:  ✅ VALIDATED (direction-aware)      │
│ Prop Filtering:        ✅ DEPLOYED (awaiting validation)   │
│ UI Filtering:          ✅ DEPLOYED (awaiting validation)   │
│ ML Model:              ✅ OPERATIONAL (corrected data)     │
│ Pipeline Runtime:      ✅ OPERATIONAL (3x daily)           │
│ Database:              ✅ OPERATIONAL (3,727 corrected)    │
│ Deployment:            ✅ LIVE (Railway)                   │
│ Next Validation:       ⏳ May 15, 9 AM ET                  │
└────────────────────────────────────────────────────────────┘

---

## Today's Accomplishments (May 14, 2026)

### 🎉 **Coverage Fix Validated**

**Validation Query Results:**
```
Trea Turner hits_under 0.5:
- Before fix: 81.0% coverage (inverted)
- After fix:  35.7% coverage (correct)

Direction Symmetry:
- hits_over:  63.8% average
- hits_under: 36.7% average
- SUM: 100.5% ✅ PERFECT
```

**Status:** ✅ Coverage calculation working correctly

---

### ✅ **Prop Filtering Implemented**

**Problem Solved:** System was scoring 152 useless props with odds -500 to -2700

**Solution:** Pre-filter props BEFORE scoring

**Filters Applied:**
1. **Prop type exclusions:**
   - stolenBases_under (53 legs, avg -1023 odds)
   - walks_under (44 legs, avg -370 odds)

2. **Odds range filter:**
   - Minimum: -500 (no more juiced props)
   - Maximum: +500 (no longshots)

**Expected Impact:**
- Legs scored: 443 → 388 (12% reduction)
- Processing time: ~8% faster
- Database: Cleaner (no garbage)

**Commits:**
- `bc12d9c` - Initial filter (full pipeline)
- `f047808` - Added to targeted refresh

**Status:** ✅ Deployed to both pipeline modes, awaiting fresh data test

---

### ✅ **UI Display Filter Implemented**

**Problem Solved:** "Legs" tab showing 443 legs including -2700 odds garbage

**Solution:** Filter legs before display to only show odds -300 to +300

**Expected Impact:**
- UI legs: 443 → 250 (44% reduction)
- All displayed legs are parlay-usable
- No more user confusion

**Status:** ✅ Deployed, awaiting fresh legs to display

---

## Component Status

### **1. Coverage Calculation** ✅ VALIDATED

**What was fixed (May 13):**
- Direction parameter added to all coverage functions
- UNDER props now count times player stayed under (not over)
- Database updated with corrected values (5,226 legs re-scored)

**Validation results (May 14):**
- Trea Turner: 81% → 35.7% ✅
- Direction symmetry: hits_over + hits_under = 100.5% ✅
- 3,727 legs with updated coverage values ✅

**Status:** ✅ Validated and working correctly

---

### **2. Prop Filtering** ✅ DEPLOYED (Awaiting Validation)

**Filter Function:**
```python
_EXCLUDED_PROP_TYPES = frozenset([
    ("stolenBases", "under"),  # -2700 to -417 odds
    ("walks", "under"),         # -540 to -302 odds
])

_FILTER_MIN_ODDS = -500  # No worse than -500
_FILTER_MAX_ODDS = +500  # No longer than +500
```

**Integration Points:**
1. `main.py` line 580 - Full pipeline (run_pipeline)
2. `main.py` line 1090 - Targeted refresh

**Validation pending:** Tomorrow's 9 AM fresh props fetch

**Status:** ✅ Code deployed, test blocked by existing data

---

### **3. UI Display Filter** ✅ DEPLOYED

**Filter Logic:**
```python
# src/web/server.py handle_legs()
filtered_legs = [
    leg for leg in all_legs
    if -300 <= int(float(leg.get("odds", 0))) <= 300
]
```

**Expected Results:**
- Legs tab: 250 displayed (down from 443)
- All legs between -300 and +300 odds
- No stolenBases_under visible

**Status:** ✅ Deployed, awaiting fresh legs

---

### **4. ML Model** ✅ OPERATIONAL

**Model:** `leg_scorer_v2.pkl` (673 KB)
**Training data:** 81,282 samples with corrected coverage
**Trained:** May 13, 2026

**Metrics:**
- AUC: 0.8489
- Accuracy: 77%
- Hit rate: 45.7%

**Known issue:** Direction feature 69.7% importance (overfit on bugged training data)

**Plan:** Monitor for 7 days, retrain if needed after more corrected data accumulates

**Status:** ✅ Operational

---

### **5. Pipeline Execution** ✅ OPERATIONAL

**Schedule:**
- 9:00 AM ET - Full pipeline (resolution + fresh fetch + score + build)
- 12:00 PM ET - Targeted refresh (odds update + lineup check)
- 5:30 PM ET - Targeted refresh (odds update + lineup check)

**Latest run:** May 14, 6:15 PM ET
- 164 legs after lineup filter
- 73 legs eligible after all filters
- 5 parlays built (+1414 to +1465 odds)
- Coverage logging active ✅

**Status:** ✅ Running on schedule

---

### **6. Database** ✅ OPERATIONAL

**Tables:**
- `mlb_scored_legs`: 5,226 total (4,599 with corrected coverage)
- `mlb_training_data`: 81,282 samples (corrected)
- `mlb_parlay_recommendations_v2`: Active
- `mlb_parlay_legs_v2`: Active

**Recent updates:**
- Coverage values corrected for all UNDER props
- Direction symmetry validated (hits sum to ~100%)
- May 14 data: 443 legs (pre-filter), 53 stolenBases_under (will be 0 tomorrow)

**Status:** ✅ All tables operational

---

### **7. Deployment** ✅ LIVE

**Platform:** Railway
**Latest deploy:** May 14, 2026, 7:00 PM ET
**Commits:** 
- `6311eee` - Coverage fix
- `cc367ef` - Coverage backfill fixes
- `ec0bf30` - Model retrain
- `bc12d9c` - Initial prop filter
- `f047808` - Filter in targeted refresh

**Health:**
- No errors on startup ✅
- Model loaded successfully ✅
- Coverage fix active ✅
- Prop filters active ✅

**Status:** ✅ Deployed and running

---

## Expected Improvements (Track May 15-20)

### **Leg-Level:**
| Metric | Before | Expected After | Target Date |
|--------|--------|----------------|-------------|
| hits_under hit rate | 36.7% | 65-70% | May 20 |
| hits_over hit rate | 63.8% | 63-68% | May 20 |
| Overall leg hit rate | 52% | 60-65% | May 20 |
| Legs scored per day | 443 | 388 | May 15 (immediate) |
| UI legs displayed | 443 | 250 | May 15 (immediate) |

### **Parlay-Level:**
| Metric | Before | Expected After | Target Date |
|--------|--------|----------------|-------------|
| 4-leg hit rate | 7% | 15-20% | May 20 |
| 5-leg hit rate | 4% | 10-15% | May 20 |
| Avg legs per parlay | 5.2 | 4-5 | May 20 |

---

## Validation Plan (May 15, 9 AM)

### **Step 1: Check Railway Logs**

**Expected output:**
```
[filter_props] 540 raw → 388 usable
  Excluded 53 by prop type (stolenBases_under, walks_under)
  Excluded 99 by odds range (< -500 or > +500)
```

**If missing:** Filter not being called - troubleshoot deployment

### **Step 2: Database Validation**

```sql
-- Should be 0 (down from 53)
SELECT COUNT(*) FROM mlb_scored_legs
WHERE run_date = '2026-05-15'
  AND stat = 'stolenBases' AND direction = 'under';

-- Should be 0 (down from 152)
SELECT COUNT(*) FROM mlb_scored_legs
WHERE run_date = '2026-05-15'
  AND odds::numeric < -500;

-- Should be ~388 (down from 443)
SELECT COUNT(*) FROM mlb_scored_legs
WHERE run_date = '2026-05-15';
```

### **Step 3: UI Validation**

- Open web app "Legs" tab
- Should show ~250 legs (not 443)
- All legs between -300 and +300 odds
- No stolenBases_under props visible

### **Step 4: Parlay Quality Check**

- 4-5 parlays built ✅
- Legs with odds -100 to -210 range ✅
- No change expected (parlay builder was already correct)

---

## Working Well - Don't Change

| Component | Status | Evidence |
|-----------|--------|----------|
| Coverage calculation | ✅ Validated | Trea Turner 81% → 35.7%, symmetry confirmed |
| ML model retraining | ✅ Working | AUC 0.85, no errors |
| Database connectivity | ✅ Stable | No connection errors |
| Deployment pipeline | ✅ Reliable | Auto-deploy working |
| Game start filter | ✅ Accurate | Correctly filters started games |
| Parlay builder | ✅ Correct | Already filtering by odds properly |
| Pitcher data infrastructure | ✅ Complete | Full enrichment working |

---

## Known Issues

### **Issue 1: Direction Feature Still Dominant**
- **Severity:** Low (expected with current data)
- **Description:** ML model relies 70% on direction feature
- **Why:** Model trained on coverage that was correlated with direction
- **Impact:** Model may still be biased, but now has correct coverage to work with
- **Next step:** Monitor for 7 days, retrain if improvement insufficient
- **Status:** Monitoring

### **Issue 2: Prop Filter Untested**
- **Severity:** None (not a bug, just pending validation)
- **Description:** Filter code deployed but hasn't processed fresh props yet
- **Why:** Today's legs pre-date the filter, manual run loaded existing data
- **Impact:** Will know if it works tomorrow at 9 AM
- **Status:** Awaiting validation

---

## Priority Matrix (Next Week)

| Priority | Item | Effort | Expected Impact |
|----------|------|--------|-----------------|
| HIGH | Validate prop filters work | 30 min | Confirm 443→388 reduction |
| HIGH | Monitor hit rates daily | 15 min/day | Track 52%→60%+ improvement |
| MEDIUM | Adjust if filters too aggressive | 2 hours | Fine-tune if needed |
| MEDIUM | Address direction bias if needed | 4-6 hours | Retrain if improvement insufficient |
| LOW | Expand to more prop types | 4 hours | Increase variety |

---

**Last Review:** May 14, 2026, 7:30 PM ET  
**Next Review:** May 15, 2026, 9:30 AM ET (after morning pipeline)  
**Major Milestones:** Coverage validated ✅, Filters deployed ✅, Awaiting fresh data test ⏳
