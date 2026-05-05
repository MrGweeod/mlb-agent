# MLB Parlay Agent — Architecture Decisions

**Last Updated:** May 5, 2026

---

## Pass Full Parlay Payload Instead of DB ID (May 5, 2026)

**Decision:** Frontend sends full parlay object to `/api/analyze-recommendation` instead of just recommendation_id

### Context

The "Analyze Parlay" button was returning 404 "Recommendation not found" even though the endpoint existed and worked correctly.

### Root Cause

**The ID mismatch:**
```
Frontend:
  - Builds parlays dynamically via /api/build-parlays (in-memory, not saved to DB)
  - Assigns p.id = p.rank (1, 2, 3, 4, 5)
  - Sends {recommendation_id: 1} to backend

Backend:
  - Searches mlb_parlay_recommendations table for r["id"] == 1
  - But DB id is auto-increment PK (42, 43, 44...)
  - Lookup fails → returns 404
```

**The fundamental issue:** Frontend was using rank as ID, backend expected database primary key.

### Solution Options Considered

**Option A: Use rank as DB ID** ❌
- Store rank in database as ID
- Cons: Complicates DB schema, rank changes with reordering
- Not chosen: Rank is presentation layer, not data layer

**Option B: Return DB IDs from /api/build-parlays** ❌
- Save parlays to DB before returning
- Cons: Unnecessary DB writes for ephemeral recommendations
- Not chosen: Dynamic parlays shouldn't pollute recommendation table

**Option C: Pass full parlay object** ✅ **CHOSEN**
- Frontend stores parlays in memory
- Sends complete parlay object to analysis endpoint
- Backend uses object directly, skips DB lookup
- Pros: No ID mapping, works for both dynamic and saved parlays
- Cons: Larger request payload (~2KB vs 4 bytes)

### Implementation

**Frontend changes:**
```javascript
// Global to store current parlays
let _currentParlays = [];

// Populate when loading recommendations
async function loadRecommendations(forceRefresh) {
    const data = await fetch('/api/build-parlays?refresh=' + forceRefresh).then(r => r.json());
    _currentParlays = data.parlays;  // Cache in memory
    renderRecommendations(data.parlays);
}

// Send full object instead of just ID
async function analyzeRecommendation(recId) {
    const parlay = _currentParlays.find(p => p.id === recId);
    const response = await fetch('/api/analyze-recommendation', {
        method: 'POST',
        body: JSON.stringify(parlay ? { parlay } : { recommendation_id: recId })
    });
}
```

**Backend changes:**
```python
async def handle_analyze_recommendation(request):
    body = await request.json()
    
    # Accept both paths
    parlay_direct = body.get("parlay")
    recommendation_id = body.get("recommendation_id")
    
    if parlay_direct:
        # Use passed parlay (dynamic builds, no DB record)
        rec = parlay_direct
        recommendation_id = None
    elif recommendation_id:
        # Lookup in DB (saved recommendations)
        rec = next((r for r in all_recs if r["id"] == int(recommendation_id)), None)
        if not rec:
            return web.Response(status=404, text="Recommendation not found")
    else:
        return web.Response(status=400, text="recommendation_id or parlay required")
    
    # Generate analysis
    analysis = await call_claude_api(rec)
    
    # Only persist if we have a DB record
    if recommendation_id:
        update_recommendation_analysis(int(recommendation_id), analysis)
    
    return web.Response(text=json.dumps({"analysis": analysis}))
```

### Impact

**Before (Broken):**
```
User clicks "Analyze Parlay #1"
  → Frontend sends {recommendation_id: 1}
  → Backend searches DB for id=1
  → Not found (DB id is 42)
  → Returns 404
```

**After (Fixed):**
```
User clicks "Analyze Parlay #1"
  → Frontend sends {parlay: {legs: [...], combined_odds: 1490, ...}}
  → Backend uses object directly
  → Generates analysis
  → Returns 200 with Claude's analysis
```

### Trade-offs Accepted

**Larger request payload:**
- Sending full parlay object (~2KB) vs just ID (4 bytes)
- **Mitigation:** Acceptable for HTTP POST, gzipped by default

**Stateful frontend:**
- Frontend must keep `_currentParlays` in memory
- Lost on page refresh (acceptable - just reload)
- **Mitigation:** Simple array storage, no complexity

**Two code paths in backend:**
- Must handle both `{parlay}` and `{recommendation_id}`
- **Benefit:** Supports both dynamic and DB-backed recommendations
- **Mitigation:** Clear if/elif logic, well-documented

### Key Lessons

**1. ID semantics matter**
- Rank (1, 2, 3) is presentation order, not persistent identity
- Database IDs are persistent, but not guaranteed to match rank
- Never assume frontend and backend share ID namespace

**2. Pass objects when IDs are ambiguous**
- If ID mapping is complex or error-prone, pass the full object
- Slightly larger payload beats broken functionality

**3. Support multiple access patterns**
- Dynamic (in-memory) vs persistent (DB) recommendations
- Backend should accept both, not force one pattern

---

## Perpetual Data Loop - Option A (May 5, 2026)

**Decision:** Automate outcome resolution daily, keep model retraining manual for quality control

### Context

User expected **perpetual calibration** where the ML model continuously learns from new data:
1. Props logged daily → 2. Outcomes resolved daily → 3. Model retrained automatically → 4. Predictions improve

Investigation revealed only step 1 was working. Steps 2-4 were broken or manual-only.

### Problem Analysis

**What was working:**
- ✅ Props logged to `mlb_training_data` daily (result = NULL)
- ✅ Training script exists (`scripts/train_ml_model.py`)
- ✅ Manual retrain endpoint exists (`GET /api/train-model?secret=PASSWORD`)

**What was broken:**
- ❌ Outcome resolution not automated (`resolve_training_data()` exists but not called by pipeline)
- ❌ Model retraining not scheduled (no cron, no automation)
- ❌ Model never reloads (cached at startup, even if pickle updates)

**The data flow gap:**
```
Props logged (result=NULL)
  → Sit unresolved forever
  → Training data doesn't grow
  → Model uses April 30 weights indefinitely
```

### Solution Options Considered

**Option A: Quick Fix (Automated Resolution + Manual Retraining)** ✅ **CHOSEN**
- Automate outcome resolution (9 AM daily)
- Keep retraining manual (weekly via `/api/train-model`)
- Keep deployment manual (Railway redeploy)
- Pros: Simple, immediate impact, manual quality control
- Cons: Still requires weekly human intervention

**Option B: Full Perpetual Calibration (Everything Automated)** ⏳ **FUTURE**
- Automate outcome resolution (9 AM daily)
- Automate model retraining (weekly via cron)
- Automate model hot-reload (after training completes)
- Add validation gates (don't deploy if AUC drops)
- Pros: True perpetual learning, zero intervention
- Cons: More complex, risk of bad model auto-deploying

**Why Option A chosen:**
1. Gets data flowing immediately
2. Validates retraining process manually before automating
3. User controls when model updates deploy
4. Can add automation incrementally once proven

### Implementation

**Modified `main.py` - `run_morning_pipeline()` function:**

**Added Step 2 (Outcome Resolution):**
```python
# Step 2: Resolve yesterday's training data outcomes
print(f"\n[2/4] Resolving outcomes for {yesterday}...")
try:
    from src.tracker.outcome_resolver import resolve_training_data
    resolution_stats = resolve_training_data(yesterday, verbose=True)
    print(f"  Resolution complete: {resolution_stats['hit']} hits, "
          f"{resolution_stats['miss']} misses, {resolution_stats['void']} voids")
except Exception as _res_err:
    print(f"  WARNING: Outcome resolution failed: {_res_err}")
    # Don't crash the pipeline if resolution fails
```

**No other changes needed:**
- `resolve_training_data()` already existed in `src/tracker/outcome_resolver.py`
- Just needed to wire it into the daily pipeline
- Function handles all box score fetching, outcome determination, DB updates

### Impact

**Before (Broken):**
```
9 AM Pipeline:
1. Transaction wire
2. Health check
3. Done
→ Props accumulate as NULL forever
```

**After (Fixed):**
```
9 AM Pipeline:
1. Transaction wire
2. Resolve yesterday's outcomes (NULL → hit/miss/void)
3. Health check
4. Done
→ Training dataset grows ~150-200 rows/day
```

**Data flow now:**
```
Day 1: Log 150 props (result=NULL)
Day 2 9AM: Resolve Day 1 props → 75 hits, 70 misses, 5 voids
Day 2: Log 150 new props (result=NULL)
Day 3 9AM: Resolve Day 2 props
...
Training data grows automatically
```

### Manual Retraining Workflow

**Every Sunday (or as desired):**

1. **Trigger retraining:**
   ```bash
   curl GET /api/train-model?secret=PASSWORD
   ```

2. **Evaluate response:**
   ```json
   {
     "status": "success",
     "auc": 0.8612,
     "samples": 84523,
     "old_auc": 0.8532,
     "improvement": "+0.0080"
   }
   ```

3. **Quality checks:**
   - AUC improved or stable (>0.85)?
   - Sample count grew (77K → 84K)?
   - Improvement positive or small negative (<0.01)?

4. **Deploy if good:**
   - Railway dashboard → Redeploy
   - Wait 2-3 min for new model to load

5. **Monitor next week:**
   - Are predictions calibrated?
   - Did quality improve?
   - Any new biases?

### Trade-offs Accepted

**Manual intervention still required:**
- Weekly trigger of `/api/train-model`
- Manual validation of results
- Manual Railway redeploy
- **Benefit:** User controls quality, can skip bad models

**Model doesn't auto-reload:**
- Even if pickle updates, must redeploy Railway
- **Mitigation:** Acceptable for weekly cadence
- **Future:** Can add hot-reload mechanism

**No validation gates:**
- Nothing prevents deploying a bad model
- User must check AUC manually
- **Mitigation:** Automated gates can be added later

### Key Lessons

**1. "Perpetual" requires explicit wiring**
- Having code doesn't mean it runs
- Must add to scheduled pipeline
- Automation is opt-in, not default

**2. Start with manual quality control**
- Validate process works before automating
- Build confidence in retraining quality
- Easier to add automation than remove it

**3. Separation of concerns**
- Data collection: Automated
- Model training: Manual
- Deployment: Manual
- Each can be automated independently

**4. Weekly cadence is reasonable**
- Model doesn't need daily retraining
- 1 week = ~1K new samples (enough to matter)
- Manual review feasible once per week

### Future Path to Full Automation (Option B)

**After 3-4 successful manual retrainings:**

1. **Add weekly cron job:**
   ```python
   # Railway cron: every Sunday 3 AM
   async def weekly_retrain():
       response = requests.get("/api/train-model?secret=...")
       if response.json()["auc"] > 0.85:
           trigger_railway_redeploy()
   ```

2. **Add model hot-reload:**
   ```python
   # In ml_leg_scorer.py
   def get_model():
       global _cached_model, _cached_timestamp
       if pickle_file_newer_than(_cached_timestamp):
           _cached_model = load_model()
           _cached_timestamp = now()
       return _cached_model
   ```

3. **Add validation gates:**
   ```python
   # Don't deploy if quality regresses
   if new_auc < old_auc - 0.02:
       alert_user("Model quality dropped, skipping deployment")
       return
   ```

4. **Add rollback mechanism:**
   ```python
   # Keep last 5 model versions
   # Revert to previous if production metrics degrade
   ```

But for now: **Automated data, manual quality control.**

---

## Summary of May 4-5 Architecture Decisions

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

### 7. Pass Full Objects Not IDs (Reliability)
- Send complete parlay object to analysis
- Backend supports both direct payload and DB lookup
- **Philosophy:** When ID mapping is complex, pass the object

### 8. Perpetual Data Loop - Option A (Quality Control)
- Automate data collection and resolution
- Manual model retraining and deployment
- **Philosophy:** Trust automation for data, validate quality manually for models

---

## Architectural Principles Established

1. **User control > Automation** - Manual refresh beats scheduled runs
2. **Cache first** - Default to fast, opt-in to fresh
3. **Fail explicitly** - None values should error or skip, not silently convert
4. **Math validates strategy** - Technical implementation must support user philosophy
5. **Quality > Quantity** - 40 elite legs better than 270 mediocre legs
6. **Separate concerns** - ML filters (gatekeeper), parlay builder optimizes
7. **Pass objects when IDs ambiguous** - Avoid ID namespace collisions
8. **Automate data, validate models** - Trust pipelines, verify intelligence

These principles guide future architectural decisions and help evaluate proposed changes.
