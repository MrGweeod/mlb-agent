# MLB Parlay Agent — Architecture Decisions

**Last Updated:** May 5, 2026

This document tracks all major architectural decisions, their rationale, and lessons learned.

---

## Move ML Scoring Upstream in Pipeline (May 5, 2026)

**Decision:** Score ALL qualifying legs (≥55% coverage) in main.py BEFORE logging to database, instead of scoring only eligible legs (≥65% coverage) inside parlay_builder.py.

### Context

**The NULL Score Crisis:**
- Database showed 378 legs, but only 170 had composite_score (55% NULL)
- Logs claimed "374/374 scored successfully"
- Disconnect between pipeline execution and database persistence

**Root cause analysis:**
```python
# OLD FLOW (broken):
main.py:
  1. Filter to qualifying_legs (coverage ≥55%) → 374 legs
  2. Log qualifying_legs to database → 374 rows inserted
  
parlay_builder.py:
  3. Filter to eligible_legs (coverage ≥65%) → 170 legs
  4. Score eligible_legs with ML model → 170 scored
  5. Build parlays

# RESULT: 374 logged, 170 scored = 204 NULL (55% NULL rate)
```

### Options Considered

**Option A: Filter qualifying_legs to ≥65% before logging** ❌
- Only log legs that will be scored
- Cons: Lose data for ML training (55-65% legs useful for training)
- Cons: Can't track performance of marginal legs
- Not chosen: Too restrictive, limits dataset

**Option B: Score inside log_scored_legs()** ❌
- Add ML scoring call inside db.py logging function
- Cons: Violates separation of concerns (DB layer shouldn't do ML)
- Cons: Harder to test and debug
- Not chosen: Poor architecture

**Option C: Move scoring upstream to main.py** ✅ **CHOSEN**
- Score ALL qualifying_legs before build_hybrid_parlays
- Log already-scored legs to database
- Pros: 100% scoring coverage, clean separation of concerns
- Pros: Can still filter to ≥65% for parlay building
- Cons: Minimal (scores legs that won't be used in parlays)

### Implementation

**Modified `main.py` (line 637-650):**
```python
# ── ML Scoring (all qualifying legs, before logging and parlay builder) ──
from src.engine.ml_leg_scorer import score_legs_ml
score_legs_ml(qualifying_legs)
scored_count = sum(1 for l in qualifying_legs if l.get("composite_score") is not None)
avg_score = (
    sum(l["composite_score"] for l in qualifying_legs if l.get("composite_score") is not None)
    / scored_count
    if scored_count else 0.0
)
above_65 = sum(1 for l in qualifying_legs if (l.get("composite_score") or 0) >= 65)
print(
    f"  [ml_scorer] Scored {scored_count}/{len(qualifying_legs)} legs | "
    f"avg={avg_score:.1f} | ≥65%: {above_65}"
)
```

**Modified `parlay_builder.py`:**
```python
# Removed scoring block (lines 155-162 deleted)
# Added lightweight fallback for edge cases:
unscored = [l for l in eligible if l.get("composite_score") is None]
if unscored:
    from src.engine.ml_leg_scorer import score_legs_ml
    score_legs_ml(unscored)
    print(f"  [parlay_builder] Fallback-scored {len(unscored)} unscored legs")
```

### Impact

**Before:**
- Total legs: 378
- Scored: 170 (45%)
- NULL: 208 (55%)

**After:**
- Total legs: 376
- Scored: 376 (100%)
- NULL: 0 (0%)

**Key metric:** 121% increase in scoring coverage, 100% reduction in NULL rate

### Lessons Learned

1. **Pipeline ordering matters** - The sequence of filter → score → log vs filter → log → score has massive impact on data quality
2. **Logs can lie** - "374 scored" in logs but 170 in database means the logging and scoring are disconnected
3. **Always score before persisting** - Don't log incomplete data and backfill later; complete it first
4. **Separation of concerns** - Scoring belongs in orchestration layer (main.py), not builder layer (parlay_builder.py) or persistence layer (db.py)

---

## ON CONFLICT DO UPDATE for Backfilling (May 5, 2026)

**Decision:** Change database conflict resolution from `DO NOTHING` to `DO UPDATE SET composite_score = EXCLUDED.composite_score WHERE composite_score IS NULL`

### Context

**The Backfill Problem:**
- Pipeline ran at 1:13 PM (before fix) → inserted 208 legs with NULL composite_score
- Fix deployed at 2:48 PM
- Pipeline ran at 2:53 PM (after fix) → tried to insert same legs with real scores
- Database rejected updates silently due to `ON CONFLICT ... DO NOTHING`

**Evidence:**
```sql
-- Query run at 3:00 PM showed:
total_legs: 378
scored_legs: 170
null_scores: 208

-- Even though logs at 2:53 PM showed:
[ml_scorer] Scored 374/374 legs | avg=50.4
```

### Options Considered

**Option A: Delete and re-insert** ❌
- `DELETE FROM mlb_scored_legs WHERE run_date = today; INSERT ...`
- Cons: Loses historical data if run multiple times per day
- Cons: Race condition if multiple processes running
- Not chosen: Too destructive

**Option B: DO NOTHING (status quo)** ❌
- Keep existing behavior, manually delete NULL rows
- Cons: Requires manual intervention
- Cons: Doesn't prevent future occurrences
- Not chosen: Not sustainable

**Option C: DO UPDATE unconditionally** ❌
- `ON CONFLICT DO UPDATE SET composite_score = EXCLUDED.composite_score`
- Cons: Overwrites good scores with potentially bad ones
- Cons: Last-write-wins is dangerous
- Not chosen: Too aggressive

**Option D: DO UPDATE with WHERE clause** ✅ **CHOSEN**
- `ON CONFLICT DO UPDATE SET composite_score = EXCLUDED.composite_score WHERE composite_score IS NULL`
- Only updates NULL scores, preserves existing good scores
- Pros: Safe backfilling, idempotent
- Pros: Handles both initial insert and re-run scenarios
- Cons: None

### Implementation

**Modified `src/utils/db.py` (line 775-777):**
```python
# OLD:
ON CONFLICT (run_date, odd_id) DO NOTHING

# NEW:
ON CONFLICT (run_date, odd_id) DO UPDATE
    SET composite_score = EXCLUDED.composite_score
    WHERE mlb_scored_legs.composite_score IS NULL
```

### Impact

**Test case:**
1. Pipeline run 1: Inserts leg with composite_score = NULL
2. Fix deployed
3. Pipeline run 2: Tries to insert same leg with composite_score = 72.4
4. Result: Row updated, composite_score changed from NULL → 72.4

**Verification:**
```sql
-- After regenerating picks:
SELECT COUNT(*) as null_scores
FROM mlb_scored_legs
WHERE run_date = '2026-05-05' AND composite_score IS NULL;

-- Result: 0 (was 208)
```

### Lessons Learned

1. **ON CONFLICT strategy matters** - `DO NOTHING` is rarely the right choice for data pipelines
2. **Conditional updates are safe** - `WHERE composite_score IS NULL` protects good data while fixing bad
3. **Idempotency is valuable** - Re-running the pipeline should be safe and fix issues, not break things
4. **Test deployment scenarios** - Consider: first run, re-run after fix, re-run after code change

---

## Two-Tier Outcome Resolution (May 5, 2026)

**Decision:** Implement separate resolution phases for individual legs (Tier 1) and parlays (Tier 2), running sequentially in morning pipeline.

### Context

**Requirements:**
1. Track individual leg outcomes (did player X hit line Y?)
2. Track parlay outcomes (did all legs in this parlay hit?)
3. Resolve daily at 9 AM automatically
4. Support historical queries (hit rate over time)

**Dependency:**
- Can't resolve parlays without first resolving legs
- Parlay outcome = function of leg outcomes

### Options Considered

**Option A: Single-tier (parlay only)** ❌
- Only track parlay outcomes, not individual legs
- Cons: Can't analyze which leg types perform best
- Cons: Can't train ML model on outcomes
- Not chosen: Insufficient granularity

**Option B: Parallel resolution** ❌
- Resolve legs and parlays simultaneously
- Cons: Race condition (parlay resolver might run before leg resolver)
- Cons: Complex error handling
- Not chosen: Too fragile

**Option C: Two-tier sequential** ✅ **CHOSEN**
- Resolve legs first (Tier 1)
- Then resolve parlays using leg results (Tier 2)
- Pros: Clear dependency chain
- Pros: Can validate each tier independently
- Pros: Easy to debug (logs show each phase)

### Implementation

**Morning Pipeline Structure (`main.py` lines 793-818):**
```python
# Step 2a: Resolve scored legs (Tier 1)
from src.tracker.outcome_resolver import resolve_all_legs
leg_stats = resolve_all_legs(yesterday, verbose=True)
print(f"  Scored legs: {leg_stats['won']} won, {leg_stats['lost']} lost")

# Step 2b: Resolve training data (parallel to 2a, both Tier 1)
from src.tracker.outcome_resolver import resolve_training_data
resolution_stats = resolve_training_data(yesterday, verbose=True)
print(f"  Training data: {resolution_stats['hit']} hits, {resolution_stats['miss']} misses")

# Step 2c: Resolve parlay recommendations (Tier 2, depends on 2a)
from src.tracker.parlay_outcome_resolver import resolve_parlay_recommendations
parlay_stats = resolve_parlay_recommendations(yesterday, verbose=True)
print(f"  Parlays: {parlay_stats['won']} won, {parlay_stats['lost']} lost")
```

**Tier 1 Logic (Legs):**
1. Fetch box scores for yesterday's games
2. Extract actual stat values
3. Compare to line: `actual > line and direction='over' → 'won'`
4. Handle edge cases: DNP → 'void', exact match → 'push'
5. Update `mlb_scored_legs.result` and `actual_value`

**Tier 2 Logic (Parlays):**
1. Fetch all parlays where `recommendation_date = yesterday` and `bet_status = 'pending'`
2. Bulk-fetch all leg results in one query
3. Apply outcome logic:
   ```python
   if any(leg.result == 'void'):
       parlay.bet_status = 'void'
   elif any(leg.result == 'lost'):
       parlay.bet_status = 'lost'
   elif all(leg.result == 'won'):
       parlay.bet_status = 'won'
   else:
       # Some legs still NULL - skip
       continue
   ```
4. Update `mlb_parlay_recommendations.bet_status` and `resolved_at`

### Design Choices

**Conservative void handling:**
- Decision: Any void leg → entire parlay voids
- Rationale: Parlay is invalid if any leg didn't play
- Alternative: Reduce payout proportionally (not implemented)

**Skip unresolved legs:**
- Decision: If any leg has NULL result, skip parlay resolution
- Rationale: Wait for complete data rather than guess
- Alternative: Mark as 'incomplete' status (not implemented)

**Bulk query optimization:**
```python
# Inefficient (N queries):
for parlay in parlays:
    for odd_id in parlay.leg_odd_ids:
        leg_result = query_leg(odd_id)

# Efficient (1 query):
all_odd_ids = set(id for p in parlays for id in p.leg_odd_ids)
leg_results = query_all_legs(all_odd_ids)  # Single query
```

### Impact

**Before:**
- No leg outcome tracking
- No parlay outcome tracking
- No hit rate data
- No validation of ML model predictions

**After:**
- ✅ Leg outcomes resolved daily
- ✅ Parlay outcomes resolved daily
- ✅ Historical hit rate queryable
- 🎯 First data tomorrow 9 AM

### Lessons Learned

1. **Sequential > Parallel for dependencies** - Clear ordering prevents race conditions
2. **Bulk queries matter** - 1 query for 50 legs beats 50 queries
3. **Conservative error handling** - Void handling should favor data quality over payout
4. **Separate concerns** - Legs and parlays are different enough to warrant separate resolvers
5. **Log everything** - Each tier logs its stats separately for debugging

---

## Single ML Pipeline (Removed Heuristic Fallback) (May 5, 2026)

**Decision:** Remove `USE_ML_SCORING` environment variable and heuristic scorer fallback, always use ML model.

### Context

**Dual System Problem:**
```python
# OLD CODE in parlay_builder.py:
use_ml = os.getenv("USE_ML_SCORING", "false").lower() == "true"
if use_ml:
    from src.engine.ml_leg_scorer import score_legs_ml
    score_legs_ml(eligible)
else:
    score_legs_composite(eligible, ...)  # Heuristic
```

**Issues:**
1. Two code paths to maintain
2. Confusion about which is active
3. ML model deployed but could be disabled silently
4. Heuristic scorer (`leg_scorer.py`) still in codebase but unused

### Options Considered

**Option A: Keep dual system** ❌
- Maintain both scorers for flexibility
- Cons: More code to maintain
- Cons: Confusion about which is active
- Cons: Can't consolidate improvements
- Not chosen: Complexity outweighs benefits

**Option B: Make heuristic the fallback** ❌
- Use ML as primary, fall back to heuristic on errors
- Cons: Masks ML model bugs
- Cons: Silent degradation of quality
- Not chosen: Better to fail loudly than degrade silently

**Option C: ML only, remove heuristic** ✅ **CHOSEN**
- Delete `USE_ML_SCORING` env var
- Always call `score_legs_ml()`
- Keep `leg_scorer.py` in repo but don't import it
- Pros: Single code path, clear behavior
- Pros: ML bugs surface immediately
- Cons: No fallback if ML breaks (acceptable - fix the bug instead)

### Implementation

**Removed from `parlay_builder.py`:**
```python
# Deleted lines 155-162:
if not all(leg.get("composite_score") for leg in eligible):
    use_ml = os.getenv("USE_ML_SCORING", "false").lower() == "true"
    if use_ml:
        from src.engine.ml_leg_scorer import score_legs_ml
        score_legs_ml(eligible)
    else:
        score_legs_composite(eligible, ...)
```

**Replaced with:**
```python
# Scoring is performed upstream in main.py (ML model, all qualifying legs).
# Fallback: if any leg is still missing a score (e.g. regeneration path), score now.
unscored = [l for l in eligible if l.get("composite_score") is None]
if unscored:
    from src.engine.ml_leg_scorer import score_legs_ml
    score_legs_ml(unscored)
    print(f"  [parlay_builder] Fallback-scored {len(unscored)} unscored legs with ML model")
```

**Removed imports:**
```python
import os  # No longer needed
from src.engine.leg_scorer import score_legs_composite  # Dead code
```

**Deleted env var:**
- `USE_ML_SCORING` removed from Railway environment variables

### Impact

**Code reduction:**
- Deleted: 50+ lines across parlay_builder.py and related files
- Simplified: Scoring logic now has one path, not two

**Behavioral change:**
- Before: Might use heuristic if env var missing or set wrong
- After: Always uses ML, fails if ML unavailable (good - surfaces bugs)

**Performance:**
- No change (ML was already active via env var)

### Lessons Learned

1. **Feature flags are technical debt** - `USE_ML_SCORING` started as a safe toggle, became a maintenance burden
2. **Single code path >> dual paths** - Simpler to reason about, test, and debug
3. **Fail fast > silent fallback** - If ML breaks, we want to know immediately, not silently degrade to heuristic
4. **Delete dead code** - Keeping `leg_scorer.py` in repo but not importing it is better than deleting (preserves history)

---

## Parlay Persistence Strategy (May 5, 2026)

**Decision:** Auto-save all generated parlays to database when `/api/build-parlays` runs, using `ON CONFLICT (recommendation_date, rank) DO UPDATE`.

### Context

**Requirements:**
1. Track all recommendations (not just ones user clicks)
2. Allow regeneration without creating duplicates
3. Support outcome resolution
4. Enable historical analysis

**Challenge:**
- User might click "Regenerate Now" multiple times per day
- Each regeneration builds 5 new parlays
- Need to track latest recommendation without duplicates

### Options Considered

**Option A: Only save on user action** ❌
- Save parlay only when user clicks "Place Bet" button
- Cons: Doesn't track all recommendations
- Cons: Can't measure system hit rate (only user's choices)
- Not chosen: Insufficient tracking

**Option B: Create new row each regeneration** ❌
- Each regeneration inserts 5 new rows (rank 1-5)
- Timestamp tracks when generated
- Cons: Duplicates (could have 20 rows for May 5 if regenerated 4 times)
- Cons: Which one to resolve? Latest? All?
- Not chosen: Too messy

**Option C: ON CONFLICT DO UPDATE (timestamp)** ✅ **CHOSEN**
- `UNIQUE (recommendation_date, rank)`
- Each regeneration updates existing rows
- Latest recommendation replaces previous
- Pros: Always 5 rows per day (ranks 1-5)
- Pros: Simple resolution (resolve the 5 that exist)
- Pros: Tracks latest recommendation, not all iterations

### Implementation

**Modified `src/web/server.py` (lines 422-437):**
```python
# After building and caching parlays:
from src.utils.db import save_parlay_recommendation
run_time = datetime.now(timezone.utc)
for parlay in top_5:
    try:
        save_parlay_recommendation({
            "recommendation_date": date.today(),
            "pipeline_run_time":   run_time,
            "rank":                parlay["rank"],
            "leg_odd_ids":         [leg["odd_id"] for leg in parlay.get("legs", [])],
            "combined_odds":       parlay.get("combined_odds", 0),
            "win_probability":     parlay.get("win_probability", 0.0),
            "edge_pct":            parlay.get("edge_pct", 0.0),
        })
    except Exception as _save_err:
        print(f"[build_parlays] Failed to save rank {parlay.get('rank')}: {_save_err}")
```

**Database function (`src/utils/db.py`):**
```python
def save_parlay_recommendation(rec):
    """
    Upsert parlay recommendation.
    ON CONFLICT (recommendation_date, rank) DO UPDATE
    ensures only latest recommendation per rank per day is kept.
    """
    # ... implementation details ...
```

### Design Choices

**Track pipeline_run_time:**
- Decision: Store when parlay was generated
- Rationale: Distinguish morning vs afternoon recommendations
- Use case: Debug if parlay quality varies by time of day

**Store leg_odd_ids as array:**
- Decision: `leg_odd_ids INT[]` instead of JSON
- Rationale: Easier to query for resolution
- Alternative: Full leg JSON (more data, harder to query)

**Minimal fields:**
- Decision: Only store what's needed for resolution + analysis
- Fields: date, rank, leg IDs, odds, status, resolved_at
- Not stored: Full leg details, Claude analysis text, etc.
- Rationale: Keep table lean, join to `mlb_scored_legs` for details

### Impact

**Before:**
- Parlays generated but not saved
- No historical record
- No way to track hit rate
- Manual tracking required

**After:**
- ✅ All parlays saved automatically
- ✅ 5 rows per day (ranks 1-5)
- ✅ Latest recommendation always current
- ✅ Ready for resolution

**Verification:**
```sql
SELECT recommendation_date, rank, combined_odds, bet_status
FROM mlb_parlay_recommendations
WHERE recommendation_date >= '2026-05-02'
ORDER BY recommendation_date DESC, rank;
```

Results:
- May 5: 5 parlays (ranks 1-5, pending)
- May 2-4: 7 parlays (pending, awaiting resolution)

### Lessons Learned

1. **ON CONFLICT is powerful** - Solves upsert pattern cleanly
2. **Latest > all iterations** - Tracking every regeneration adds noise, not signal
3. **Unique constraint as business rule** - `(recommendation_date, rank)` encodes "one top-5 list per day"
4. **Minimal schema** - Store IDs, not full objects; join for details
5. **Auto-save > manual save** - If it requires user action, it won't be consistent

---

## Summary of May 5 Architecture Principles

### **Pipeline Ordering Principle**
**Score → Log → Build**, not **Log → Build → Score**

Data must be complete before persistence. The sequence matters:
1. Fetch raw data
2. Calculate features
3. **Score with ML model**
4. **Persist to database**
5. Filter for specific use case (parlay building)

### **Database Update Strategy Principle**
**ON CONFLICT DO UPDATE** with conditions, not **DO NOTHING**

Idempotent operations should fix bad data, not ignore it:
- `WHERE composite_score IS NULL` - safe backfilling
- `WHERE bet_status = 'pending'` - safe outcome updates
- Never unconditional UPDATE (protects good data)

### **Tier Separation Principle**
**Resolve dependencies first**, then dependents

When outcome B depends on outcome A:
- Tier 1: Resolve A
- Tier 2: Resolve B using A's results
- Never parallel if dependency exists

### **Single Path Principle**
**One code path** beats **conditional paths**

Feature flags and if/else scorers create:
- Confusion about which is active
- Bugs that only appear in one branch
- Maintenance burden

Remove the flag, choose the path, commit.

### **Persistence Consistency Principle**
**Always save**, with **unique constraints** to prevent duplicates

Don't rely on user actions for tracking:
- Auto-save on generation
- Use `ON CONFLICT` to handle duplicates
- Track latest, not all iterations
- Resolution works on what exists, not what user clicked

---

These principles form the foundation of the current architecture. Future decisions should align with or explicitly override these patterns.
