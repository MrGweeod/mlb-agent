# MLB Parlay Agent — Architecture Decisions

**Last Updated:** May 1, 2026

---

## Database Schema Evolution (May 1, 2026)

**Decision:** Add `composite_score` column and scope uniqueness per day

### Context

System broken May 1 morning:
- No legs displaying in web app
- Picks tab HTTP 500 errors
- Database missing composite_score column
- Global UNIQUE constraint blocking multi-day data

### Root Causes

**Problem 1: Missing Column**
```python
# Code expected this field
leg.get("composite_score")  # But column didn't exist in DB
```

**Problem 2: Wrong Constraint Scope**
```sql
-- OLD (WRONG) - Global uniqueness
UNIQUE (odd_id)

-- Blocks same prop across days:
-- 2026-05-01: Aaron Judge TB O1.5 (odd_id=123)
-- 2026-05-02: Aaron Judge TB O1.5 (odd_id=123) ← BLOCKED
```

### Solution

**Schema Changes:**
```sql
-- Add column
ALTER TABLE mlb_scored_legs ADD COLUMN composite_score REAL;

-- Fix constraint
ALTER TABLE mlb_scored_legs DROP CONSTRAINT mlb_scored_legs_odd_id_uq;
-- Kept: UNIQUE (run_date, odd_id)
```

**Code Changes:**
```python
# CREATE TABLE
composite_score REAL,
UNIQUE (run_date, odd_id)

# INSERT
leg.get("composite_score"),
```

### Impact

**Before Fix:**
- 10-20 legs/day (only new odd_ids)
- composite_score always NULL

**After Fix:**
- 200+ legs/day (all props for the day)
- composite_score populated with ML predictions

### Key Lesson

**Always coordinate schema and code deployments:**

1. Run migration in Supabase FIRST
2. Verify with diagnostic queries
3. THEN deploy code that depends on new schema

**Never deploy code before schema exists.**

---

## Pickle Serialization Compatibility (May 1, 2026)

**Decision:** Add compatibility unpickler instead of retraining model

### Context

ML model pickle failed to load:
```
Can't get attribute 'CalibratedModel' on <module '__main__' from '/app/src/web/server.py'>
```

### Root Cause

**Timeline:**
1. April 29: `CalibratedModel` defined in `scripts/train_ml_model.py`
2. Model trained while script running as `__main__`
3. Pickle stored class path as `__main__.CalibratedModel`
4. Commit `05a6e1d`: Moved class to `src/engine/ml_leg_scorer.py`
5. Commit `7318b4a`: Committed pickle with old path reference
6. May 1: Unpickling fails - `__main__` is now `server.py`, doesn't have class

### Solution Options

**Option A: Retrain Model**
- Pros: Clean, no compatibility code
- Cons: Expensive (40min training), loses calibration work

**Option B: Compatibility Shim (CHOSEN)**
- Pros: Zero retraining, model unchanged
- Cons: Small compatibility layer

**Implementation:**
```python
class _CompatUnpickler(pickle.Unpickler):
    """Redirect old class path to new location"""
    def find_class(self, module: str, name: str):
        if name == "CalibratedModel":
            return CalibratedModel  # From ml_leg_scorer
        return super().find_class(module, name)

def _compat_load(file_obj):
    return _CompatUnpickler(file_obj).load()

# Use in _load_model()
_cached = _compat_load(f)
```

### Key Lessons

**1. Pickle stores absolute class paths**
- Moving classes breaks deserialization
- Class must exist at same module path

**2. When refactoring class locations:**
- Either retrain pickle with new location, OR
- Add compatibility unpickler, OR
- Use format-agnostic serialization (ONNX, joblib)

**3. Always define picklable classes at module level**
- Never inside functions
- Path must be importable: `module.ClassName`

### Future Consideration

**Switch to ONNX or joblib for better portability:**
- ONNX: Framework-agnostic, production-grade
- joblib: Python-friendly, version-stable
- Pickle: Fragile, Python-specific

---

## API Response Structure Mismatches (May 1, 2026)

**Decision:** Always validate field names between producer and consumer

### Context

Frontend displayed "+undefined" for parlay odds despite function returning valid data.

### Root Cause

**Function returned:**
```python
{
    "parlay_odds": "+1476",  # String, American odds
    "legs": [...]
}
```

**Code expected:**
```python
combined_odds = parlay.get("combined_odds", 0)  # ← Missing field!
# Returns 0
# Edge calc: (0 + 100) / 100 = 1.0 → negative edge
```

### Why It Failed Silently

1. `.get()` with default returns 0 (no error)
2. Edge calculation runs with wrong value
3. Frontend displays 0 → JavaScript shows "undefined"
4. No logs, no exceptions, just wrong output

### Solution

**Parse string odds into expected field:**
```python
# Add missing field
raw_odds_str = parlay.get("parlay_odds", "+0")
combined_odds = int(raw_odds_str.replace("+", ""))
parlay["combined_odds"] = combined_odds

# Now both fields exist
assert "parlay_odds" in parlay  # "+1476" string
assert "combined_odds" in parlay  # 1476 integer
```

### Additional Bug Found

**Wrong decimal odds formula:**
```python
# WRONG (what we had)
decimal_odds = (combined_odds + 100) / 100
# For +1476: (1476 + 100) / 100 = 15.76 ✓

# But for +100: (100 + 100) / 100 = 2.0 ✓
# For -110: (-110 + 100) / 100 = -0.1 ✗ NEGATIVE!

# CORRECT
decimal_odds = (combined_odds / 100) + 1  # For positive odds
# For +1476: (1476 / 100) + 1 = 15.76 ✓
# For +100: (100 / 100) + 1 = 2.0 ✓
```

### Key Lessons

**1. Field name mismatches fail silently**
- `.get(missing_key, default)` returns default
- No error, just wrong data
- Hard to debug without logging

**2. Prevention strategies:**
- Log response structure at boundaries
- Use type hints: `ParleyDict` with known fields
- Validate field existence before use
- Unit test data structure contracts

**3. Always verify formulas with edge cases**
- Test with positive odds (+100, +200)
- Test with negative odds (-110, -200)
- Test with even money (+100)

---

## UNIQUE Constraint Scoping (May 1, 2026)

**Decision:** Scope uniqueness per day, not globally

### Context

Only 10-20 legs saved per day despite 350+ qualifying.

### Root Cause

**Schema had:**
```sql
UNIQUE (odd_id)  -- Global across all days
```

**DraftKings reuses odd_ids:**
```
2026-05-01: Aaron Judge TB O1.5 → odd_id=123
2026-05-02: Aaron Judge TB O1.5 → odd_id=123 (SAME)
```

**INSERT behavior:**
```sql
INSERT INTO mlb_scored_legs (run_date, odd_id, ...)
VALUES ('2026-05-02', '123', ...)
ON CONFLICT (odd_id) DO NOTHING;  -- Silently drops!
```

**Result:**
- May 1: 350 props, 340 already seen → 10 inserted
- May 2: 350 props, 350 already seen → 0 inserted
- Data stops growing after first day

### Solution

**Change constraint scope:**
```sql
-- Per-day uniqueness
UNIQUE (run_date, odd_id)

-- Now both rows can exist:
-- ('2026-05-01', '123')  ✓
-- ('2026-05-02', '123')  ✓
```

### Impact

**Before:**
- Day 1: 350 inserted
- Day 2: 0 inserted (all blocked)
- Day 3: 0 inserted (all blocked)

**After:**
- Day 1: 350 inserted
- Day 2: 350 inserted
- Day 3: 350 inserted

### Key Lessons

**1. Think about constraint scope:**
- Per-day data → `UNIQUE (date, id)`
- Per-user data → `UNIQUE (user_id, resource_id)`
- Truly global → `UNIQUE (id)` alone

**2. `ON CONFLICT DO NOTHING` hides errors:**
- Silent failures
- No logs by default
- Add logging: `RETURNING *` to count inserts

**3. Test with multi-day data:**
- Single-day testing wouldn't catch this
- Need 2+ days of test data
- Verify INSERT count matches expectation

---

## Dynamic Parlay Generation vs Static Storage (April 30, 2026)

**Decision:** Build parlays on-demand from live data, don't cache in database

### Context

Originally stored recommendations in `mlb_parlay_recommendations` table from pipeline runs. This created stale data problems.

### Problem with Static Storage

**Timeline:**
```
9:00 AM: Pipeline builds 5 parlays, saves to DB
1:05 PM: Game starts
4:00 PM: User views Picks tab → sees parlay with started game ✗
```

**Filtering after construction doesn't work:**
- Parlays are specific 5-leg combinations
- Can't just "remove" started leg
- Breaks the parlay entirely

### Solution: Dynamic Generation

**New flow:**
```
User views Picks tab:
├─ Query mlb_scored_legs (current data)
├─ Filter started games
├─ Build fresh parlays
└─ Return top 5
```

**Benefits:**
- Always current
- No stale games
- No dependency on pipeline schedule

**Cost:**
- 1-2 seconds to build parlays
- Acceptable for on-demand use

### Implementation

**Endpoint:**
```python
@routes.get('/api/build-parlays')
async def handle_build_parlays(request):
    scored_legs = get_scored_legs(today)
    upcoming = filter_started_games(scored_legs)
    qualifying = [leg for leg in upcoming 
                  if leg['composite_score'] >= 55]
    parlays = build_hybrid_parlays(qualifying, top_n=10)
    return parlays  # Fresh every time
```

**Deprecated:**
- `mlb_parlay_recommendations` table (no longer written to)
- `/api/recommendations` endpoint (static data)

### Key Lessons

**1. Dynamic > Static for volatile data:**
- Games start continuously
- Static caching = stale data
- Generate on-demand when data changes frequently

**2. Performance vs Correctness:**
- 1-2 sec generation time is acceptable
- Showing stale/wrong data is NOT acceptable
- Correctness > Speed for betting apps

**3. Cache invalidation is hard:**
- Smarter to avoid caching volatile data
- If caching needed, invalidate on every game start
- Dynamic generation simpler

---

## Future Architecture Considerations

### 1. Pipeline Leg Persistence Issue (May 1 - UNRESOLVED)

**Observation:** Pipeline processes 352 legs but web app only sees 215

**Hypothesis:** `log_scored_legs()` not being called with all legs

**Next Steps:**
- Verify Step 8 in main.py calls log_scored_legs()
- Add logging to confirm INSERT count
- Ensure all qualified legs save, not just parlay legs

### 2. Diversity Filter Tuning

**Current:** `top_n=10` to give diversity filter room

**Question:** Is 10 enough?

**Evidence:** Still only building 1 parlay from 124 legs

**Options:**
- Increase to top_n=20
- Relax diversity constraints
- Require fewer unique legs per parlay

### 3. Edge Calculation Validation

**Current Results:** +326% edge on 5-leg parlay

**Question:** Are these realistic?

**Next Steps:**
- Track actual outcomes over 7 days
- Compare predicted edges vs realized edges
- Recalibrate if systematic overconfidence

---

## Summary of May 1 Architectural Learnings

1. **Schema before code** - Always migrate database before deploying code
2. **Pickle is fragile** - Consider ONNX/joblib for production models
3. **Validate field names** - Silent failures from .get() with defaults
4. **Scope constraints carefully** - Think about temporal/spatial boundaries
5. **Dynamic > Static** - Generate fresh when data changes frequently
6. **Test edge cases** - Formulas need positive/negative/zero testing

**Critical Path Forward:** Fix pipeline leg persistence to enable full system operation.
