# MLB Parlay Agent — Session Handoff
**Last Updated:** May 14, 2026 (End of Day - Prop Filtering Implemented)

## Current Status
✅ **Coverage Fix Validated - Working Correctly**
✅ **Prop Filtering Implemented - Awaiting Tomorrow's Test**
⏳ **Next Milestone:** May 15, 9 AM ET - First fresh pipeline run with filters

---

## What Was Accomplished Today (May 14, 2026)

### **Phase 1: Coverage Fix Validation** (Morning)

**Validated yesterday's coverage fix is working:**

**Database Query Results:**
```
Trea Turner hits_under 0.5:
- OLD: 81% coverage (inverted - was counting overs)
- NEW: 35.7% coverage (correct - counts unders)

Direction Symmetry Check:
- hits_over: 63.8% average coverage
- hits_under: 36.7% average coverage
- SUM: 100.5% ✅ PERFECT SYMMETRY
```

**Impact confirmed:**
- Coverage calculation is now direction-aware ✅
- OVER props count times player went over ✅
- UNDER props count times player stayed under ✅
- Mathematical inverses (sum to ~100%) ✅

---

### **Phase 2: Useless Props Problem Discovered** (Afternoon)

**Problem identified:** UI showing 443 legs with many heavily juiced props:
- Carlos Cortes stolenBases_under: **-2700 odds**
- 53 stolenBases_under legs averaging **-1023 odds**
- 44 walks_under legs averaging **-370 odds**
- 152 total legs with odds worse than -500

**Root cause:** System was scoring ALL props from SGO, including:
- Props that are always heavily juiced (stolenBases_under, walks_under)
- Props with odds outside usable range (-500 to +500)

**Parlay builder was correctly filtering these**, but they cluttered the database and UI.

---

### **Phase 3: Prop Filtering Implementation** (Afternoon/Evening)

**Two fixes implemented:**

#### **Fix 1: Pre-Scoring Props Filter (main.py)**

Added filtering BEFORE coverage calculation:

```python
_EXCLUDED_PROP_TYPES = frozenset([
    ("stolenBases", "under"),  # avg odds -1023
    ("walks", "under"),         # avg odds -370
])

_FILTER_MIN_ODDS = -500
_FILTER_MAX_ODDS = +500

def _filter_useless_props(raw_props):
    # Filters by prop type AND odds range
    # Returns only props that could be useful in parlays
```

**Added to TWO pipeline modes:**
1. Full pipeline (run_pipeline) - line 580
2. Targeted refresh - line 1090

**Expected impact:**
- Legs scored: 443 → 388 (12% reduction)
- Processing time: ~8% faster
- Database: No garbage props stored

#### **Fix 2: UI Display Filter (server.py)**

Added filter in handle_legs() to only show props with odds -300 to +300:

```python
# Only show legs with usable odds in the UI (-300 to +300)
filtered_legs = []
for leg in legs:
    odds_int = int(float(leg.get("odds") or 0))
    if -300 <= odds_int <= 300:
        filtered_legs.append(leg)
```

**Expected impact:**
- UI display: 443 → 250 legs (44% reduction)
- "Legs" tab becomes actually usable
- No more -2700 odds props visible

---

### **Phase 4: Deployment & Validation Attempt** (Evening)

**Commits:**
- `bc12d9c` - Initial filter implementation (full pipeline only)
- `f047808` - Added filter to targeted refresh pipeline

**Validation blocked:**
- Today's legs already exist in database (pre-filter)
- Manual pipeline run loaded existing legs, didn't fetch fresh props
- Filter only applies to NEW props fetched from SGO
- Decided to preserve today's training data rather than delete and re-fetch

**Decision:** Wait for tomorrow's 9 AM fresh pipeline run for validation.

---

## Tomorrow's Validation Plan (May 15, 9 AM ET)

### **Step 1: Check Railway Logs**

Look for:
```
[filter_props] 540 raw → 388 usable
  Excluded 53 by prop type (stolenBases_under, walks_under)
  Excluded 99 by odds range (< -500 or > +500)
```

**If you DON'T see this:** Filter isn't being called - troubleshoot.

### **Step 2: Validate Database**

```sql
-- Should be 0 (down from 53)
SELECT COUNT(*) 
FROM mlb_scored_legs
WHERE run_date = '2026-05-15'
  AND stat = 'stolenBases'
  AND direction = 'under';

-- Should be 0 (down from 152)
SELECT COUNT(*)
FROM mlb_scored_legs
WHERE run_date = '2026-05-15'
  AND odds::numeric < -500;

-- Total legs should be ~388 (down from 443)
SELECT COUNT(*)
FROM mlb_scored_legs
WHERE run_date = '2026-05-15';
```

### **Step 3: Check UI "Legs" Tab**

- Open web app
- Navigate to "Legs" tab
- Should show ~250 legs (not 443)
- All legs should have odds between -300 and +300
- NO stolenBases_under props visible

### **Step 4: Verify Parlay Quality**

Parlays should be unchanged (parlay builder was already filtering correctly):
- 4-5 parlays built
- Legs with odds -100 to -210 range
- No heavily juiced legs selected

---

## System Health Summary

### **What's Working:**
✅ **Coverage calculation** - Direction-aware, mathematically correct
✅ **ML model** - Retrained on 81K samples with correct coverage
✅ **Parlay builder** - Correctly filters by odds, builds valid parlays
✅ **Database** - 3,727 legs with updated coverage values
✅ **Deployment** - Railway auto-deploy functioning

### **What's Deployed (Awaiting Validation):**
⏳ **Prop filtering** - Code deployed, not yet tested with fresh data
⏳ **UI filtering** - Code deployed, will show effect once fresh legs exist

### **Known Issues:**
- **None** - All blocking issues resolved

---

## Key Metrics to Track (May 15-20)

### **Leg-Level Performance:**
| Metric | Baseline (May 14) | Target (May 20) |
|--------|-------------------|-----------------|
| hits_under hit rate | 36.7% (pre-fix) | 65-70% |
| hits_over hit rate | 63.8% | 63-68% (maintain) |
| Overall leg hit rate | 52% | 60-65% |
| Legs scored per day | 443 | 388 |
| UI legs displayed | 443 | 250 |

### **Parlay-Level Performance:**
| Metric | Baseline | Target |
|--------|----------|--------|
| 4-leg hit rate | 7% | 15-20% |
| 5-leg hit rate | 4% | 10-15% |
| Avg legs per parlay | 5.2 | 4-5 |

---

## Files Changed This Session

### **Core Changes:**
- `src/engine/coverage.py` - Direction-aware coverage (deployed May 13)
- `main.py` - Added `_filter_useless_props()` and calls in both pipeline modes
- `src/web/server.py` - Added UI display filter for reasonable odds
- `models/leg_scorer_v2.pkl` - Retrained on corrected coverage data
- `scripts/rescore_historical_legs.py` - Updates all 6 coverage columns + training data

### **Documentation:**
- `SESSION_HANDOFF.md` - This document
- `BUILD_STATUS.md` - Updated with filter status
- `ARCHITECTURE_DECISIONS.md` - Documented filtering decisions
- `README.md` - Updated with current performance metrics

---

## Open Questions for Tomorrow

### **Q1: Will the prop filter reduce leg count as expected?**
**Expected:** 443 → 388 legs  
**Validate:** Count legs in database for May 15

### **Q2: Will UI filter make "Legs" tab usable?**
**Expected:** Display 250 legs instead of 443  
**Validate:** Open web app and check

### **Q3: Will coverage improvement show in hit rates?**
**Expected:** hits_under 37% → 65%+  
**Validate:** Track resolved outcomes over next week

### **Q4: Is parlay quality maintained?**
**Expected:** No change (was already filtering correctly)  
**Validate:** Check parlay composition and odds ranges

---

## Quick Reference Commands

### **Check Pipeline Status:**
```bash
# View Railway logs (live)
railway logs --follow

# Trigger manual pipeline
curl -X POST https://mlb-agent.up.railway.app/api/admin/run_full_pipeline \
  -H "Authorization: Bearer MLBparlays"
```

### **Database Queries:**
```sql
-- Verify filter worked (should be 0)
SELECT COUNT(*) FROM mlb_scored_legs
WHERE run_date = '2026-05-15'
  AND stat = 'stolenBases' AND direction = 'under';

-- Check total legs (should be ~388)
SELECT COUNT(*) FROM mlb_scored_legs
WHERE run_date = '2026-05-15';

-- Coverage validation
SELECT stat, direction, 
       ROUND(AVG(coverage_overall::numeric), 1) as avg_coverage
FROM mlb_scored_legs
WHERE run_date = '2026-05-15'
  AND stat = 'hits'
  AND coverage_overall IS NOT NULL
GROUP BY stat, direction;
```

---

## Success Criteria for Tomorrow

✅ **Filter logging appears in Railway logs**  
✅ **Zero stolenBases_under legs in database**  
✅ **Zero legs with odds < -500 in database**  
✅ **~388 total legs (not 443)**  
✅ **UI shows ~250 legs (not 443)**  
✅ **All UI legs have odds -300 to +300**  
✅ **Parlays still build (4-5 per day)**  

---

## Context for Next Session

**You left off having:**
- ✅ Validated coverage fix is working (Trea Turner: 81% → 35.7%)
- ✅ Implemented prop filtering in both pipeline modes
- ✅ Implemented UI filtering for display
- ✅ Deployed all changes to Railway
- ⏳ Waiting for tomorrow's 9 AM fresh pipeline run to validate filters

**The major breakthrough today:** Coverage calculation is now mathematically correct - hits_over and hits_under are inverses (63.8% + 36.7% = 100.5%).

**The cleanup implemented:** Filtering out 152 useless props (stolenBases_under, walks_under, heavily juiced odds) before they're scored.

**Next critical moment:** Tomorrow (May 15) 9:00 AM ET - First fresh pipeline run with prop filters active.

---

**Last Updated:** May 14, 2026, 7:30 PM ET  
**Status:** ✅ Coverage fix validated, prop filters deployed  
**Next Milestone:** May 15, 9 AM ET - Filter validation
