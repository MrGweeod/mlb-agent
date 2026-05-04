# MLB Parlay Agent — Session Handoff
**Last Updated:** May 1, 2026 (End of Day)

## Current Status
⚠️ **Partially Fixed - One Issue Remaining**
- ✅ Database schema fixed (composite_score + per-day uniqueness)
- ✅ ML model pickle deserialization working
- ✅ 213 legs displaying in Legs tab
- ✅ Odds displaying correctly (+1420 not +undefined)
- ⚠️ **Only 1 parlay in Picks tab (should be 5)**

---

## Outstanding Issue

**Problem:** Pipeline builds 5 parlays from 352 legs, but web endpoint only builds 1 from 124 legs

**Root Cause:** 
- Pipeline (5:30 PM) processes 352 fresh legs from SGO
- But doesn't save them to database
- Web app queries stale morning data (215 legs)
- After filtering started games: 215 → 124 legs
- 124 legs insufficient for diversity filter → only 1 parlay

**Evidence from logs:**
```
[Pipeline 5:30 PM] 352 eligible legs → Built 5 parlays
[Web endpoint] 124 legs ≥55% ML score → Built 1 parlay
```

**Missing:** No "Logged 352 scored leg(s)" in pipeline logs

**Next Steps (Tomorrow):**
1. Investigate why pipeline isn't calling `log_scored_legs()` with all 352 legs
2. Verify Step 8/9 in main.py is actually saving to database
3. Ensure fresh legs update database after each pipeline run

---

## What Was Fixed Today (May 1, 2026)

### Fix 1: ML Model Pickle Import (Commit `4df6b28`)

**Problem:** `CalibratedModel` class moved but pickle still referenced `__main__.CalibratedModel`

**Solution:** Added `_CompatUnpickler` shim
```python
class _CompatUnpickler(pickle.Unpickler):
    def find_class(self, module: str, name: str):
        if name == "CalibratedModel":
            return CalibratedModel
        return super().find_class(module, name)
```

**Files Modified:**
- `src/engine/ml_leg_scorer.py` (+19 lines)

**Result:** ✅ Pipeline runs without pickle errors

---

### Fix 2: Database Type Mismatch (Commit `4df6b28`)

**Problem:** `date.today()` returns Python date object, compared against TEXT column

**Solution:** Convert to string
```python
# BEFORE
today = date.today()  # Python date object

# AFTER  
today = str(date.today())  # "2026-05-01" string
```

**Files Modified:**
- `src/web/server.py` (+1, -1)

**Result:** ✅ Database queries work correctly

---

### Fix 3: Database Schema Migration (Commit `20d8777`)

**Problem 1:** `UNIQUE (odd_id)` global constraint blocked same props across days
**Problem 2:** `composite_score` column didn't exist

**Solution - Code Changes:**
```python
# Added to CREATE TABLE
composite_score REAL,
UNIQUE (run_date, odd_id)  # Per-day uniqueness

# Added to INSERT
leg.get("composite_score"),
```

**Solution - Database Migration (Supabase):**
```sql
ALTER TABLE mlb_scored_legs ADD COLUMN composite_score REAL;
ALTER TABLE mlb_scored_legs DROP CONSTRAINT mlb_scored_legs_odd_id_uq;
DELETE FROM mlb_scored_legs WHERE run_date = '2026-05-01';
```

**Files Modified:**
- `src/utils/db.py` (+7, -5)
- `sql/migrate_scored_legs_composite_score.sql` (NEW)

**Result:** ✅ All eligible legs can now save (not just new odd_ids)

---

### Fix 4: Function Signature Mismatch (Commit `7fcbc2b`)

**Problem:** `/api/build-parlays` called function with parameters that don't exist

**Error:**
```
TypeError: build_hybrid_parlays() got an unexpected keyword argument 'min_legs'
```

**Solution:**
```python
# BEFORE (WRONG)
parlays = build_hybrid_parlays(
    qualifying_legs,
    min_legs=5,
    max_legs=8,
    min_total_odds=1000,
    max_total_odds=1500,
)

# AFTER (CORRECT)
parlays = build_hybrid_parlays(qualifying_legs)
```

**Files Modified:**
- `src/web/server.py` (+1, -7)

**Result:** ✅ Endpoint no longer throws TypeError

---

### Fix 5: Combined Odds + Edge Calculation (Commit `98fd9bb`)

**Problem 1:** Frontend showed "+undefined" odds
**Problem 2:** Edge calculation was wrong

**Root Cause:**
- Function returns `parlay_odds: "+1476"` (string)
- Code expected `combined_odds` (integer)
- Wrong formula: `(0 + 100) / 100 = 1.0` → negative edge

**Solution:**
```python
# Parse string odds into integer
raw_odds_str = parlay.get("parlay_odds", "+0")
combined_odds = int(raw_odds_str.replace("+", ""))
parlay["combined_odds"] = combined_odds

# Fix edge calculation formula
decimal_odds = (combined_odds / 100) + 1  # Was: (combined_odds + 100) / 100
edge_pct = (win_prob * decimal_odds - 1) * 100
```

**Also increased parlay candidates:**
```python
parlays = build_hybrid_parlays(qualifying_legs, top_n=10)  # Was: default 5
```

**Files Modified:**
- `src/web/server.py` (+7, -2)

**Result:** 
- ✅ Odds display correctly (+1420)
- ✅ Edge calculations correct (+326.5%)
- ⚠️ Still only 1 parlay (diversity filter issue)

---

## Git Commits This Session

1. `4df6b28` - fix: ML model pickle import + database type mismatch
2. `20d8777` - fix: add composite_score to scored_legs and scope uniqueness per day
3. `7fcbc2b` - fix: correct build_hybrid_parlays parameters in /api/build-parlays
4. `98fd9bb` - fix: return multiple parlays with combined_odds in /api/build-parlays

**Branch:** master  
**Remote:** origin/master (all pushed)

---

## Key Learnings

### 1. Database Schema Changes Require Coordination
**Lesson:** Always run migrations BEFORE deploying code changes

**Order:**
1. Run ALTER TABLE in Supabase
2. Verify with diagnostic queries
3. THEN deploy code

### 2. Pickle Serialization is Fragile
**Lesson:** Moving classes breaks pickle deserialization

**Solutions:**
- Retrain model with new class location, OR
- Add compatibility shim (what we did)

### 3. Field Name Mismatches Fail Silently
**Lesson:** Function returned `parlay_odds`, code expected `combined_odds` → "+undefined"

**Prevention:**
- Always verify field names in responses
- Use logging to inspect data structures

### 4. UNIQUE Constraints Need Proper Scope
**Lesson:** Global `UNIQUE (odd_id)` prevented multi-day data

**Impact:** 10 legs/day → 200+ legs/day after fix

---

## Next Session Priorities (May 2)

**CRITICAL:**
1. ⚠️ **Fix pipeline leg saving** - Why aren't all 352 legs being saved?
2. Investigate `log_scored_legs()` call in main.py
3. Verify database INSERT is happening

**HIGH:**
4. Monitor 9 AM pipeline - does it save fresh legs?
5. Validate edge calculations - are +326% edges realistic?
6. Track actual outcomes on today's recommendations

**MEDIUM:**
7. Review diversity filter - is top_n=10 sufficient?
8. Why only 124/215 legs pass ≥55% filter?
9. Add parlay-level outcome tracking

**LOW:**
10. Clean up deprecated `mlb_parlay_recommendations` table
11. Update blueprint v2.0 with today's fixes

---

## Session Summary

**Time Investment:** ~8 hours debugging

**Status:** 4 of 5 issues fixed, 1 remaining

**Fixed:**
1. ✅ ML model pickle deserialization
2. ✅ Database schema (composite_score + uniqueness)
3. ✅ Function signature mismatches
4. ✅ Combined odds parsing and display

**Remaining:**
1. ⚠️ Pipeline not saving all legs to database → only 1 parlay builds

**Critical Blocker:** Pipeline processes 352 legs but web app only sees stale 215 legs. Need to investigate why `log_scored_legs()` isn't persisting fresh data.
