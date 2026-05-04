# MLB Parlay Agent — Architecture Decisions

**Last Updated:** May 4, 2026

---

## In-Memory Parlay Cache (May 4, 2026)

**Decision:** Implement 30-minute in-memory cache for parlay recommendations

### Context

Picks tab was running full pipeline (1-2 min) on every page load because frontend always sent `refresh=true`. This caused:
- Poor user experience (long waits)
- Database connection pool exhaustion (concurrent pipelines)
- Wasted compute resources (same data fetched repeatedly)

### Problem Analysis

**User workflow:**
```
User clicks "Picks" tab
  → Frontend sends refresh=true
  → Backend runs 8-step pipeline (1-2 min)
  → User clicks away, comes back
  → Frontend sends refresh=true AGAIN
  → Another full pipeline run
```

**Evidence from logs (May 4, 15:37):**
```
[build_parlays] LIVE REFRESH requested — running pipeline
[db] connection attempt 1 failed (EDBHANDLEREXITED)
[db] connection attempt 1 failed (ECHECKOUTTIMEOUT)
```

Three pipeline runs in parallel exhausted Supabase's 15-connection pool.

### Solution Options Considered

**Option A: Database cache with timestamp column** ❌
- Pros: Persistent across server restarts
- Cons: Still requires DB query on every load, adds table complexity

**Option B: Redis/Memcached external cache** ❌
- Pros: Scales across multiple instances
- Cons: Additional infrastructure cost, overkill for single Railway instance

**Option C: In-memory cache with threading.Lock()** ✅ **CHOSEN**
- Pros: Zero infrastructure, fast (no I/O), simple to implement
- Cons: Lost on server restart, doesn't scale to multiple instances
- Rationale: Current single-instance Railway deployment makes this ideal

### Implementation

**Cache structure:**
```python
_parlay_cache = {
    "parlays": None,          # List of parlay dicts
    "timestamp": None,        # datetime when cached
    "generated_at": None,     # ISO timestamp for frontend
    "lock": threading.Lock()  # Thread-safe access
}
_CACHE_TTL_MINUTES = 30
```

**Cache logic flow:**
```python
async def handle_build_parlays(request):
    force_refresh = request.query.get("refresh") == "true"
    
    # Check cache first
    with _parlay_cache["lock"]:
        cache_age = datetime.now() - _parlay_cache["timestamp"]
        cache_valid = cache_age < timedelta(minutes=30)
        
        if cache_valid and not force_refresh:
            return cached_parlays  # < 1 sec
    
    # Cache miss or forced refresh
    run_pipeline()  # 1-2 min
    build_parlays()
    
    # Store in cache
    with _parlay_cache["lock"]:
        _parlay_cache["parlays"] = parlays
        _parlay_cache["timestamp"] = datetime.now()
    
    return parlays
```

**Frontend coordination:**
```javascript
// Initial Picks tab load
loadRecommendations(forceRefresh=false)  // Uses cache if available

// "Regenerate Now" button
loadRecommendations(forceRefresh=true)   // Forces fresh pipeline
```

### Impact

**Before (Broken):**
- Every tab load: 1-2 min pipeline run
- Connection pool exhausted: HTTP 500 errors
- Poor UX: Long waits, no visual feedback

**After (Fixed):**
- First load: 1-2 min (cache miss)
- Subsequent loads: < 1 sec (cache hit)
- Regenerate button: 1-2 min (forced refresh)
- Cache expires after 30 min: Auto-refresh on next load

### Trade-offs Accepted

**Cache invalidation complexity:**
- Cache doesn't know about external data changes (lineups, odds)
- User must manually click "Regenerate Now" for fresh data
- **Mitigation:** 30-min TTL ensures data never more than 30 min stale

**Lost on server restart:**
- Railway restarts clear cache (cold start = full pipeline)
- **Mitigation:** Acceptable for current usage pattern

**Single-instance only:**
- Won't work with load balancing (each instance has own cache)
- **Mitigation:** Not needed now; revisit if scaling horizontally

### Key Lessons

**1. Default to cached, opt-in to fresh**
- Never run expensive operations by default
- Make user explicitly request fresh data

**2. In-memory cache sufficient for single instance**
- Don't over-engineer with Redis for 1 Railway dyno
- Start simple, add complexity only when needed

**3. Thread-safe critical for web servers**
- Multiple requests can hit endpoint simultaneously
- `threading.Lock()` prevents race conditions

### Future Considerations

**If scaling to multiple instances:**
- Move to Redis with shared cache
- Or accept eventual consistency (each instance caches independently)

**If lineup changes matter more:**
- Reduce TTL from 30 min to 10 min
- Or implement webhook from MLB lineup API to invalidate cache

**If cache hit rate low:**
- Investigate user patterns (are they clicking Regenerate too often?)
- May indicate data freshness is more important than speed

---

## Parlay Construction Strategy Restoration (May 4, 2026)

**Decision:** Revert to 4-6 legs targeting +1000-1500 odds with 65% ML threshold

### Context

Previous fix (May 1) widened odds to +600-2500 to solve "0 parlays built" issue. This moved away from core betting strategy of 10-15x returns with manageable risk.

### Root Cause Analysis

**The math problem:**
```
5 legs at -110 each:
  decimal_odds = (100/110 + 1) = 1.909
  combined = (1.909^5 - 1) × 100 = +2,435
  → Exceeds +1500 target ❌

4 legs at -110 each:
  combined = (1.909^4 - 1) × 100 = +1,228
  → Fits +1000-1500 range ✅
```

**The actual issue:** Minimum 5 legs incompatible with +1000-1500 target, not that target was wrong.

### Solution Chosen

**Change minimum legs from 5 to 4:**
```python
# Before (broken)
MIN_LEGS = 5  # Can't hit +1000-1500 with typical -110 props
MAX_LEGS = 8
MIN_PARLAY_ODDS = 600   # Too permissive
MAX_PARLAY_ODDS = 2500  # Too risky

# After (correct)
MIN_LEGS = 4  # Perfect for +1000-1500 range
MAX_LEGS = 6  # Reasonable ceiling
MIN_PARLAY_ODDS = 1000  # Core strategy target
MAX_PARLAY_ODDS = 1500  # Risk management
```

### Why Not Widen Odds Window?

**User's core betting philosophy:**
- 10-15x returns on small wagers (entertainment + upside)
- Avoid "lottery ticket" parlays (+2000+) with < 5% hit rate
- Manageable risk (4-6 legs, not 8-10)

**Widening to +600-2500 would:**
- Include 3-leg parlays (+600-800 range) = too conservative
- Include 7-8 leg parlays (+2000+ range) = too risky
- Dilute focus from sweet spot (4-6 legs, +1000-1500)

### Impact

**Odds distribution validation:**
```
4 legs at -110: +1,228 ✅
4 legs at -120: +1,073 ✅
4 legs at -130: +941 (close, acceptable) ✅
4 legs at -150: +775 ❌ (below range)

5 legs at -110: +2,435 ❌ (exceeds range)
6 legs at -110: +4,741 ❌ (way too high)
```

**Conclusion:** 4-6 legs with typical DK prop odds (-110 to -130) fit +1000-1500 target.

### Key Lessons

**1. Math constraints inform architecture**
- Can't just "set target odds" without validating achievability
- Must test with real prop pricing (-110, -120, -130)

**2. User strategy is non-negotiable**
- +1000-1500 target reflects deliberate risk/reward philosophy
- Technical "fixes" that violate strategy are bugs, not features

**3. Minimum leg count matters**
- 4 legs = accessible sweet spot
- 5 legs = forces too-high odds or too-low individual odds
- 6+ legs = lottery territory

---

## ML Model as Gatekeeper (May 4, 2026)

**Decision:** Raise ML threshold from 55% to 65% for strict quality filter

### Context

Original 55% threshold was producing 270 qualifying legs from ~1800 raw props (15% pass rate). This created two problems:

1. **Too many mediocre legs** - parlay builder only uses top 20, wasting 250 scored legs
2. **Diluted quality** - 55% prediction is barely better than coin flip

### Philosophy Change

**Old approach (quantity focus):**
```
Cast wide net → Score everything ≥55% → Parlay builder picks best 20
```

**New approach (quality focus):**
```
ML model filters strictly ≥65% → Only elite legs scored → Parlay builder optimizes from curated pool
```

**Analogy:** ML model is the **strict gatekeeper**, parlay builder is the **optimizer**.

### Impact Analysis

**Expected leg counts:**
```
55% threshold: 270 legs (15% of 1800 props)
65% threshold: 40-60 legs (2-3% of 1800 props)

For parlay building:
- Need minimum 20 legs for diversity
- Target 40-60 for good combination space
- Above 100 = wasted computation
```

**Quality improvement:**
```
55% legs: Barely above break-even (52% actual hit rate typical)
65% legs: Clear edge (60-70% actual hit rate expected)
```

### Trade-offs Accepted

**Fewer parlays on thin slates:**
- If only 30 elite legs available, combinations limited
- May build 2-3 parlays instead of 5
- **Mitigation:** Better to have 2 quality parlays than 5 mediocre ones

**Stricter than calibration target:**
- ML model calibrated across full distribution (40-80% range)
- Using only top end (≥65%) may introduce selection bias
- **Mitigation:** Monitor actual hit rates over 7 days, recalibrate if needed

**Smaller training signal:**
- Fewer legs logged = slower accumulation of outcome data
- **Mitigation:** Still logging 40-60 props/day × 150 days/season = 6-9K samples

### Validation Plan

**Week 1 (May 5-11):**
- Track actual hit rate of ≥65% legs
- Target: 60-70% (allowing for ±5pp calibration error)
- If < 55%: Model overconfident, retrain or lower threshold
- If > 75%: Model underconfident, could raise threshold

**Week 2-4 (May 12-31):**
- A/B test 60% vs 65% vs 70% thresholds
- Measure: hit rate, parlay quality, user satisfaction
- Choose optimal threshold based on data

### Key Lessons

**1. ML threshold is strategic, not technical**
- 65% reflects betting philosophy (elite legs only)
- Could set at 50% (more legs) or 80% (fewer legs)
- Right answer depends on user's risk tolerance

**2. Quantity ≠ Quality**
- 270 mediocre legs worse than 40 elite legs
- Parlay builder can't fix low-quality input

**3. Gatekeeper pattern separates concerns**
- ML model: Is this leg good? (binary filter)
- Parlay builder: Which legs combine best? (optimization)

---

## Pipeline Schedule Simplification (May 4, 2026)

**Decision:** Remove 12 PM and 5:30 PM scheduled runs, keep only 9 AM resolution

### Context

Original schedule had three daily runs:
- **9:00 AM ET:** Resolve yesterday + fresh props for today
- **12:00 PM ET:** Updated props, mid-day recommendations
- **5:30 PM ET:** Final props before first pitches, lineup confirmations

This created two problems:

1. **Scheduled recommendations stale by viewing time** - 5:30 PM props stale by 7 PM when user checks
2. **Wasted compute** - Most 12 PM/5:30 PM runs never viewed

### New Architecture

**Morning pipeline (9 AM only):**
```python
def run_morning_pipeline():
    """Resolution and data maintenance only"""
    resolve_yesterday_outcomes()
    fetch_transaction_wire()  # IL placements
    update_training_data()
    generate_calibration_report()
    # NO prop fetching
    # NO leg scoring
    # NO parlay building
```

**Live recommendations (on-demand):**
```python
def handle_build_parlays(refresh=false):
    """User clicks Picks tab or Regenerate button"""
    if cached and not expired:
        return cached_parlays  # Instant
    else:
        run_full_pipeline()    # Fresh props, fresh scores
        build_parlays()
        cache_results()
        return parlays
```

### Why This Is Better

**Freshness:**
```
Old: 5:30 PM scheduled run → User views at 7 PM = 1.5 hr stale
New: User clicks at 7 PM → Fresh pipeline run = 0 min stale
```

**Efficiency:**
```
Old: 3 scheduled runs/day × 2 min each = 6 min compute
     May never be viewed (if user doesn't check that day)
     
New: 1 scheduled run (9 AM resolution) = 1 min
     + On-demand runs only when user requests = user-driven cost
```

**User control:**
```
Old: "These are the recommendations from 5:30 PM" (take it or leave it)
New: "These are fresh recommendations" (user trusts data is current)
```

### Trade-offs Accepted

**Initial load slower:**
- First Picks tab load triggers full pipeline (1-2 min)
- **Mitigation:** Cache makes subsequent loads instant

**Database may be empty:**
- If user checks Picks at 8 AM (before morning pipeline), no data yet
- **Mitigation:** Morning pipeline populates DB by 9:05 AM

**No "standing recommendations":**
- Can't review recommendations from yesterday
- **Mitigation:** Could add recommendation archive feature if needed

### Key Lessons

**1. Schedule for data maintenance, not delivery**
- Pipelines should resolve past, not predict future
- Predictions delivered on-demand when user needs them

**2. User-driven better than scheduled**
- User knows when they need fresh data (before betting)
- Scheduled runs often wasted (user doesn't check)

**3. Cache bridges the gap**
- On-demand expensive (1-2 min pipeline)
- Cache makes it feel instant (< 1 sec)

---

## Frontend Default to Cached Loads (May 4, 2026)

**Decision:** Use `refresh=false` by default, `refresh=true` only for "Regenerate Now" button

### Context

After implementing in-memory cache, frontend still sent `refresh=true` on every Picks tab load because earlier code said "always use refresh=true for live recommendations."

This defeated the entire purpose of the cache.

### Problem

**Code flow (broken):**
```javascript
// User clicks Picks tab
loadRecommendations()
  → fetch('/api/build-parlays?refresh=true')  // Always true!
  → Backend: "Oh, forced refresh, run pipeline"
  → 1-2 min wait every time
```

**Cache never used** because `refresh=true` bypassed it.

### Solution

**Add `forceRefresh` parameter:**
```javascript
async function loadRecommendations(forceRefresh = false) {
    const refreshParam = forceRefresh ? 'refresh=true' : 'refresh=false';
    fetch(`/api/build-parlays?${refreshParam}`);
}

// Tab load
loadRecommendations()  // forceRefresh=false (default)

// Button click
regenerateRecommendations() {
    loadRecommendations(true)  // forceRefresh=true
}
```

### Why This Pattern

**Principle: Make expensive operations opt-in, not default**

```
Fast operation (cache read): Default, always available
Slow operation (pipeline): Opt-in, user explicitly requests
```

**User mental model:**
```
Click tab → "Show me parlays" (expects instant)
Click button → "Get fresh parlays" (expects wait)
```

### UX Considerations

**Spinner text distinguishes operations:**
```javascript
// Cached load
"Loading parlay recommendations..."  // Implies quick

// Forced refresh
"Running fresh pipeline..."  // Implies wait
```

**Button state feedback:**
```javascript
// Before click
"Regenerate Now"

// During pipeline
"Regenerating..." (disabled)

// After complete
"Regenerated ✓" (2 sec) → "Regenerate Now"
```

### Key Lessons

**1. Default behavior should be fast**
- Users expect instant feedback on navigation (tab clicks)
- Slow operations require explicit action (button clicks)

**2. Visual feedback critical for slow operations**
- Spinner text: "Running pipeline" sets expectation
- Button state: Disabled during operation prevents double-clicks
- Success state: "✓" confirms completion

**3. Parameter naming matters**
- `refresh=true/false` clearer than `cache=true/false`
- `forceRefresh` explicit about intent (override cache)

---

## TypeError Prevention with Explicit None Checks (May 4, 2026)

**Decision:** Always check `if value is None: continue` before comparison operators

### Context

HTTP 500 error on line 319 of server.py:
```python
TypeError: '>=' not supported between instances of 'NoneType' and 'int'
```

Caused by:
```python
for leg in upcoming_legs:
    composite_score = leg.get("composite_score", 0)  # Returns None!
    if composite_score >= 65:  # None >= 65 → TypeError
        qualifying_legs.append(leg)
```

### Why .get() Didn't Help

**Common misconception:**
```python
leg.get("composite_score", 0)  # "This returns 0 if missing, right?"
```

**Reality:**
```python
leg = {"composite_score": None}  # Key exists, value is None
leg.get("composite_score", 0)    # Returns None (key exists!)
leg.get("missing_key", 0)        # Returns 0 (key missing)
```

`.get(key, default)` only returns default if **key is missing**, not if **value is None**.

### Root Cause

**Database column allows NULL:**
```sql
CREATE TABLE mlb_scored_legs (
    composite_score REAL,  -- NULL allowed
    ...
);
```

**Legs from old pipeline runs:**
- Scored before ML model existed
- `composite_score` column added later
- Old rows have `composite_score = NULL`

### Solution Pattern

**Wrong (fails on None):**
```python
score = leg.get("composite_score", 0)
if score >= 65:  # TypeError if score is None
    ...
```

**Right (explicit None check):**
```python
score = leg.get("composite_score")
if score is None:
    continue  # Skip legs without scores
if score >= 65:
    qualifying_legs.append(leg)
```

**Alternative (coalesce with `or`):**
```python
score = leg.get("composite_score") or 0  # None → 0
if score >= 65:
    qualifying_legs.append(leg)
```

### Why Skip Instead of Default?

**Option A: Skip None values** ✅ **CHOSEN**
```python
if score is None: continue
```
- Pros: Explicit about data quality issue
- Cons: Fewer legs available
- Rationale: Legs without ML scores shouldn't be in parlays

**Option B: Default None to 0** ❌
```python
score = leg.get("composite_score") or 0
```
- Pros: More legs available
- Cons: 0% confidence leg might get included (if threshold lowered)
- Rationale: 0% is wrong data, not absence of data

**Option C: Default None to 50** ❌
```python
score = leg.get("composite_score") or 50
```
- Pros: Neutral assumption (50% = coin flip)
- Cons: 50% confidence without evidence is misleading
- Rationale: Better to skip than guess

### Prevention Strategy

**At write time (ML scorer):**
```python
# Always set composite_score, never leave as None
leg["composite_score"] = model.predict_proba(...) * 100

# If prediction fails, set explicit 0 (not None)
if error:
    leg["composite_score"] = 0.0
```

**At read time (API endpoint):**
```python
# Defensive check even if write guarantees no None
score = leg.get("composite_score")
if score is None:
    print(f"[WARNING] {leg['player_name']} has None score")
    continue
```

### Key Lessons

**1. None is not 0**
- `None >= 65` → TypeError
- `0 >= 65` → False
- Always check `is None` before comparison

**2. .get(key, default) doesn't handle None**
- Only returns default if key missing
- If key exists with None value, returns None

**3. Explicit better than implicit**
```python
# Implicit (easy to miss None case)
score = leg.get("composite_score", 0)

# Explicit (clear intent)
score = leg.get("composite_score")
if score is None: continue
```

**4. Log warnings for None values**
- Helps debug why None values appearing
- Tracks data quality issues
- Example: "WARNING: Player X has None score - old DB row?"

---

## Summary of May 4 Architecture Decisions

### 1. In-Memory Cache (Performance)
- 30-min TTL, thread-safe
- Cache hit: < 1 sec
- Cache miss: 1-2 min pipeline
- **Philosophy:** Default to fast (cached), opt-in to slow (refresh)

### 2. Parlay Strategy Restoration (Quality)
- 4-6 legs, +1000-1500 odds
- ML ≥65% threshold
- **Philosophy:** User strategy is non-negotiable, math must support it

### 3. ML Gatekeeper (Quality over Quantity)
- 65% threshold = elite legs only
- 40-60 legs vs 270 legs
- **Philosophy:** ML filters strictly, parlay builder optimizes

### 4. Pipeline Schedule Simplification (Efficiency)
- Morning resolution only (9 AM)
- Live recommendations on-demand
- **Philosophy:** Schedule maintenance, not predictions

### 5. Frontend Default Behavior (UX)
- Default: cached loads (fast)
- Opt-in: forced refresh (slow)
- **Philosophy:** Fast by default, slow by request

### 6. None Handling Pattern (Robustness)
- Explicit `if value is None: continue`
- Skip rather than guess
- **Philosophy:** Bad data should fail obviously, not silently

---

## Architectural Principles Established

1. **User control > Automation** - Manual refresh beats scheduled runs
2. **Cache first** - Default to fast, opt-in to fresh
3. **Fail explicitly** - None values should error or skip, not silently convert
4. **Math validates strategy** - Technical implementation must support user philosophy
5. **Quality > Quantity** - 40 elite legs better than 270 mediocre legs
6. **Separate concerns** - ML filters (gatekeeper), parlay builder optimizes

These principles guide future architectural decisions and help evaluate proposed changes.
