# MLB Parlay Agent — Architecture Decisions

**Last Updated:** April 30, 2026 (End of Day)

---

## Dynamic Picks Tab Architecture (April 30, 2026 - End of Day)

**Decision:** Rebuild Picks tab to generate parlays dynamically from live `mlb_scored_legs` data instead of displaying stale recommendations from the database.

**Context:**
- User screenshot at 4:33 PM showed timestamp "09:33 PM ET" (+5 hours wrong)
- Jung Hoo Lee appeared in recommendations despite SF @ PHI starting at 4:05 PM
- Fixes for timestamp and game filtering were deployed but bugs persisted
- Root cause: **Picks tab displayed static 9 AM recommendations from `mlb_parlay_recommendations` table**

**The Fundamental Problem:**

Static recommendations created at 9 AM become stale as games start throughout the day:

```
9:00 AM Pipeline:
├─ All games upcoming (1:05, 4:05, 7:05, 10:05 PM)
├─ Builds parlays from all legs
└─ Saves 5 recommendations to mlb_parlay_recommendations table

4:33 PM User Views Picks:
├─ 1:05 PM games finished 3 hours ago
├─ 4:05 PM games in progress
├─ But recommendations still include legs from these games
└─ Filtering AFTER parlays built is too late
```

**Filtering after parlay construction doesn't work** because:
- Parlays are specific combinations of legs
- Removing one leg from a 5-leg parlay breaks the whole parlay
- Can't just "filter out" started legs and keep the parlay intact

**User's Key Question:** "Why can't we build parlays from the same scored legs pool as the Legs tab?"

**The Answer:** We should. The Legs tab worked perfectly because it queries live data.

---

## Comparison: Static vs Dynamic

### Old Architecture (BROKEN):
```
Pipeline (3x/day):
├─ Fetch props from SGO
├─ Score legs with ML
├─ Save to mlb_scored_legs ✅
├─ Build parlays
└─ Save to mlb_parlay_recommendations ❌ STALE

Picks Tab:
└─ Query mlb_parlay_recommendations ❌ STALE DATA
```

### New Architecture (WORKING):
```
Pipeline (3x/day):
├─ Fetch props from SGO
├─ Score legs with ML
└─ Save to mlb_scored_legs ✅ SINGLE SOURCE OF TRUTH

Picks Tab:
├─ Query mlb_scored_legs ✅ LIVE DATA
├─ Filter started games
├─ Build parlays on-demand
└─ Display top 5 ✅ ALWAYS CURRENT

Legs Tab (already working):
├─ Query mlb_scored_legs ✅ SAME DATA SOURCE
├─ Filter started games
└─ Display in builder ✅ ALWAYS CURRENT
```

**Key Insight:** Both Picks and Legs tabs now use the same data path - query `mlb_scored_legs`, filter, display.

---

## Implementation Details

### New Endpoint: `/api/build-parlays`

**Purpose:** Build fresh parlays from current scored legs, filtered for upcoming games only.

**Process:**
1. Query `mlb_scored_legs` for today
2. Filter out games that started >5 minutes ago
3. Filter to legs with ≥55% ML score
4. Run Branch-and-Bound parlay builder (5-8 legs, +1000-1500 odds)
5. Calculate win probability and edge for each parlay
6. Sort by edge descending, return top 5

**Key Points:**
- **No SGO API calls** - uses cached data from pipeline runs
- **No database writes** - returns results directly to frontend
- **Pure computation** - parlay building is just Branch-and-Bound algorithm
- **Takes 1-2 seconds** - acceptable for on-demand generation
- **Always current** - filters started games in real-time

### Frontend Changes

**Old `loadRecommendations()`:**
```javascript
const res = await fetch('/api/recommendations');  // Static DB data
const data = await res.json();
displayRecommendations(data.recommendations);
```

**New `loadRecommendations()`:**
```javascript
const res = await fetch('/api/build-parlays');  // Dynamic generation
const data = await res.json();
data.parlays.forEach(p => { p.id = p.rank; });  // Assign IDs for rendering
displayRecommendations(data.parlays);
updateTimestamp(data.generated_at);  // Server timestamp
```

**Old "Regenerate Now" Button:**
```javascript
// Called /api/recommendations/regenerate (POST)
// Triggered full pipeline run
// Made SGO API calls
```

**New "Regenerate Now" Button:**
```javascript
// Just calls loadRecommendations()
// No pipeline run, no SGO calls
// Instant rebuild from current scored_legs
```

---

## SGO API Usage Analysis

**Monthly Limit:** 100,000 objects  
**Current Usage:** 265 objects (0.27%)

### Will Dynamic Picks Increase API Usage?

**No.** Here's the detailed breakdown:

**SGO API is only called during pipeline runs:**
```python
# main.py - run_pipeline()
props = fetch_props_from_sgo()  # ← ONLY SGO CALL
# ... compute coverage, ML scoring, etc ...
save_to_scored_legs(props)
```

**Dynamic parlay building uses cached data:**
```python
# server.py - /api/build-parlays
scored_legs = get_scored_legs(today)  # Database query (free)
upcoming = filter_started_games(scored_legs)  # In-memory filter (free)
parlays = build_hybrid_parlays(upcoming)  # Branch-and-Bound math (free)
return top_5_parlays  # No external calls
```

**SGO API Call Count:**
- **Before dynamic Picks:** 3 pipeline runs/day × 150 props = 450 props/day = 13,500/month
- **After dynamic Picks:** 3 pipeline runs/day × 150 props = 450 props/day = 13,500/month
- **Change:** +0 calls

**User Actions That Don't Call SGO:**
- ✅ Loading Picks tab
- ✅ Clicking "Regenerate Now"
- ✅ Auto-refresh on Legs tab (every 60 seconds)
- ✅ Viewing Dashboard or Training tabs

**User Actions That DO Call SGO:**
- ⚠️ Clicking "Refresh" button on Legs tab (manual refresh with 3-hour filter, ~75 props)

**Estimated Monthly Usage:**
- 3 pipeline runs/day × 30 days × 150 props = 13,500 objects
- 5 manual refreshes/day × 30 days × 75 props = 11,250 objects
- **Total: ~25,000 objects/month (25% of limit)**

---

## Trade-offs

### What We Gained:
1. ✅ **Always current data** - no stale recommendations
2. ✅ **No started games** - filtering happens before parlay building
3. ✅ **Simpler architecture** - same data path as Legs tab
4. ✅ **Zero additional API costs** - uses cached scored_legs
5. ✅ **Instant regeneration** - 1-2 second rebuild on demand
6. ✅ **Correct timestamps** - server-side UTC generation

### What We Lost:
1. ❌ **Historical recommendation tracking** - can't measure which parlays won/lost over time
2. ❌ **Pre-computed recommendations** - slight delay on page load (1-2 sec)

### What We Could Add Back:
If historical tracking is needed:
- Save generated parlays to database AFTER displaying them
- Add `placed_at` timestamp to track when user actually saw the recommendation
- Outcome resolver can still match against saved recommendations
- But: Don't use saved recommendations for display - always build fresh

---

## Alternative Architectures Considered

### Option 1: Filter Stale Legs from Stored Recommendations (REJECTED)

**Idea:** Keep storing recommendations in database, but filter out started legs when displaying.

**Problem:**
```python
# Parlay: [Leg A, Leg B, Leg C, Leg D, Leg E]
# If Leg B's game started, what do we show?

# Option 1: Show incomplete parlay [A, C, D, E]
# ❌ Odds are wrong (missing one leg)
# ❌ Edge calculation is wrong
# ❌ Not the parlay the algorithm selected

# Option 2: Hide entire parlay
# ❌ Might hide all 5 recommendations
# ❌ User sees nothing
```

**Why Rejected:** Filtering after parlay construction fundamentally doesn't work. Parlays are indivisible combinations.

---

### Option 2: Regenerate Every 30 Minutes (REJECTED)

**Idea:** Add scheduled task to regenerate recommendations every 30 minutes, save to database.

**Code:**
```python
@tasks.loop(minutes=30)
async def regenerate_recommendations():
    scored_legs = get_scored_legs(today)
    upcoming = filter_started_games(scored_legs)
    parlays = build_hybrid_parlays(upcoming)
    save_to_database(parlays)
```

**Problems:**
- Still can have 30-minute staleness window
- More complex (additional background task)
- Still need to filter at display time anyway
- Why cache if we're filtering every time?

**Why Rejected:** Doesn't fully solve staleness, adds complexity, provides minimal benefit over on-demand generation.

---

### Option 3: Client-Side Parlay Building (REJECTED)

**Idea:** Send all scored legs to frontend, build parlays in JavaScript.

**Problems:**
- Branch-and-Bound algorithm is compute-intensive (~1000 iterations)
- JavaScript performance worse than Python
- Sends unnecessary data over network (all legs, not just top 5)
- Can't leverage NumPy optimizations
- Mobile devices would struggle

**Why Rejected:** Performance, network overhead, complexity.

---

### Option 4: Dynamic Generation with Aggressive Caching (CONSIDERED BUT UNNECESSARY)

**Idea:** Build parlays on-demand but cache results for 5 minutes.

**Code:**
```python
cache = {}

async def handle_build_parlays(request):
    cache_key = f"parlays_{datetime.now().minute // 5}"
    if cache_key in cache:
        return cache[cache_key]
    
    parlays = build_fresh_parlays()
    cache[cache_key] = parlays
    return parlays
```

**Why Not Needed:**
- Parlay building takes 1-2 seconds (acceptable)
- Caching reintroduces staleness (games start continuously)
- Adds complexity for minimal benefit
- If performance becomes an issue, can add later

**Current Decision:** Skip caching, build fresh every time.

---

## Database Schema Impact

### Tables Affected:

**`mlb_parlay_recommendations` - DEPRECATED**
- No longer written to by pipeline or regenerate endpoint
- Frontend doesn't query it anymore
- Can keep for historical data or drop entirely
- Current rows: 5 (stale from 9 AM)

**`mlb_scored_legs` - NOW SINGLE SOURCE OF TRUTH**
- Both Picks and Legs tabs query this table
- Pipeline writes to it 3x/day
- No changes to schema needed
- Current rows: 31 (today's scored props)

### Optional Cleanup:

If we want to track recommendations historically:

```sql
-- Add new column to track when parlays were actually shown to user
ALTER TABLE mlb_parlay_recommendations 
ADD COLUMN displayed_at TIMESTAMP;

-- Or create new table for user-facing recommendations
CREATE TABLE mlb_displayed_recommendations (
  id SERIAL PRIMARY KEY,
  displayed_at TIMESTAMP NOT NULL,
  rank INT NOT NULL,
  leg_odd_ids TEXT[] NOT NULL,
  combined_odds INT NOT NULL,
  win_probability FLOAT NOT NULL,
  edge_pct FLOAT NOT NULL
);
```

**Decision:** Defer this until we have evidence that historical tracking is valuable.

---

## Timestamp Fix (Bonus Architecture Decision)

**Problem:** `datetime.now()` created naive datetime, browser interpreted as local time.

**Old Flow:**
```python
run_time = datetime.now()  # Naive: "2026-04-30 20:33:00"
# Serializes to JSON: "2026-04-30 20:33:00"
# Browser: new Date("2026-04-30 20:33:00") → treats as LOCAL time
# User in ET: 8:33 PM (but it's 4:33 PM UTC, should show as 4:33 PM ET)
# Displays: "09:33 PM ET" (wrong)
```

**New Flow:**
```python
run_time = datetime.now(timezone.utc)  # Aware: "2026-04-30 20:33:00+00:00"
# Serializes to JSON: "2026-04-30T20:33:00+00:00"
# Browser: new Date("2026-04-30T20:33:00+00:00") → treats as UTC
# User in ET: Converts to ET timezone
# Displays: "04:33 PM ET" (correct)
```

**Key Principle:** Always use timezone-aware datetimes for any value that will be serialized and consumed by a client.

---

## Lessons Learned

### 1. Static Data + Volatile Reality = Bugs

Games start continuously throughout the day. Static recommendations generated once in the morning can't adapt to this reality. **Dynamic generation from live data is the only architecture that works.**

### 2. Same Data Source for Related Features

Picks tab and Legs tab show different views of the same underlying data (scored legs). They should query the same source. Having one query live data and one query cached data created inconsistency and bugs.

### 3. Filter at the Source, Not the Destination

Filtering started games AFTER building parlays doesn't work because you can't remove a leg from a parlay without invalidating it. **Filter before building.**

### 4. User Questions Reveal Architecture Issues

"Why can't we build from the same scored legs pool?" - This simple question exposed the fundamental flaw: we were using two different data paths for similar features.

### 5. Performance vs Correctness

1-2 second parlay building time is acceptable. Showing stale or incorrect recommendations is not. **Correctness > Speed** for a betting application.

### 6. Timezone-Aware by Default

Never use `datetime.now()` for values that will be serialized. Always use `datetime.now(timezone.utc)`. **Explicit timezone > Implicit assumptions.**

---

## Migration Path

### For Existing Sessions:

No data migration needed. The old `mlb_parlay_recommendations` table can stay in the database harmlessly. It's simply no longer queried by the frontend.

### For Historical Analysis:

If we later want to analyze recommendation performance:

1. Query `mlb_scored_legs` for historical dates
2. Run parlay builder algorithm retroactively
3. Compare generated parlays to actual outcomes
4. No need for stored recommendations

---

## Future Enhancements (If Needed)

### 1. Parlay-Level Outcome Tracking

```python
# After user views recommendations, save what they saw
async def handle_build_parlays(request):
    parlays = build_fresh_parlays()
    
    # Optional: Save for historical tracking
    for parlay in parlays:
        save_displayed_recommendation({
            'displayed_at': datetime.now(timezone.utc),
            'rank': parlay['rank'],
            'legs': parlay['legs'],
            'odds': parlay['combined_odds'],
        })
    
    return parlays
```

### 2. Smart Caching (If Performance Becomes Issue)

```python
# Cache invalidation on game start
@dataclass
class ParlayCacheEntry:
    parlays: List[Dict]
    generated_at: datetime
    next_game_start: datetime

cache = None

async def handle_build_parlays(request):
    global cache
    
    now = datetime.now(timezone.utc)
    
    # Cache valid until next game starts
    if cache and now < cache.next_game_start:
        return cache.parlays
    
    # Rebuild
    parlays = build_fresh_parlays()
    next_start = get_next_game_start_time()
    cache = ParlayCacheEntry(parlays, now, next_start)
    
    return parlays
```

### 3. WebSocket Push Updates

Instead of polling, push updates when new games start:

```python
# When a game starts, push notification to connected clients
async def on_game_start(game_id):
    await websocket.send_json({
        'type': 'game_started',
        'game_id': game_id,
        'action': 'refresh_recommendations'
    })
```

**Decision:** None of these are needed yet. Start simple, add complexity only when necessary.

---

## Related Architecture Decisions

This decision connects to:
- [Trust ML Model Uniformly](#trust-ml-model-uniformly-april-30-2026) - Filtering happens before parlay building
- [Raw Coverage Signals](#raw-coverage-signals-april-29-2026) - ML features come from scored_legs table
- [Game Time Filtering](#game-time-filtering-is-critical-april-29-2026) - Applied at multiple points, including /api/build-parlays

---

**Decision Status:** ✅ Implemented and deployed (pending final commit)

**Expected Impact:** Zero stale recommendations, always current parlays, no additional API costs

**Review Date:** May 1, 2026 (after first full day of production use)

---

## Trust ML Model Uniformly - Remove Directional Bias (April 30, 2026)

**Decision:** Stop overriding ML model predictions with hand-coded directional thresholds. Apply uniform ML score filter to all legs regardless of over/under direction.

**Context:**
- Old system required ML score ≥65% for overs, ≥55% for unders
- This blocked 84% of overs (16 out of 19 legs)
- ML model trained on 77K samples with 0.85 AUC and Platt calibration
- Model learned direction bias automatically (77% feature importance)
- We were essentially saying: "ML, score this leg... now ignore your score if it's an over"

**The Problem:**

If the ML model is properly calibrated:
- **A 58% prediction should mean 58% win rate**
- Whether it's an over or under shouldn't require different thresholds
- The model already learned that unders hit 79% and overs hit 22% from training data
- Adding a hand-coded filter on top of that is redundant and contradictory

**Old Filtering Logic (REMOVED):**
```python
# Universal coverage threshold
if composite_score < 55:
    continue

# Risky over threshold - overs need higher score
if direction == "over" and composite_score < 65:
    continue
```

**New Filtering Logic (CURRENT):**
```python
# Universal ML score threshold - same for all legs
if composite_score < 55:
    continue

# Only exception: genuinely high-variance stats
if direction == "over" and stat in ["homeRuns", "stolenBases"]:
    if composite_score < 70:
        continue
```

**What Changed:**
1. **Removed `RISKY_OVER_THRESHOLD = 65.0`** constant entirely
2. **Renamed `_POISON_OVER_STATS` → `_HIGH_VARIANCE_OVER_STATS`**
   - Old: `{"rbi", "walks", "homeRuns", "stolenBases"}` (hard blocked)
   - New: `{"homeRuns", "stolenBases"}` (require 70% ML score)
   - RBIs and walks now allowed at standard 55% threshold
3. **Removed `MAX_RISKY_OVERS = 1`** constraint from Branch-and-Bound
4. **Applied uniform 55% threshold** to hits overs, strikeout overs, etc.

**Impact:**
- Before: 15 eligible legs (12 unders + 3 risky overs)
- After: 25-30 eligible legs (balanced mix)
- Parlays building: 5-leg combinations at +1400-1500 odds

**Rationale:**

We spent the entire day:
1. Training an ML model on 77K samples
2. Calibrating it with Platt Scaling
3. Verifying calibration curve (76% predicted → 72% actual, only 4pp error)

If we're going to override the model with arbitrary direction-based thresholds, **we're wasting all that work.**

The model already learned that unders hit more often (direction = 77% feature importance). We don't need to hand-code that bias on top of it.

**Trust the calibrated ML predictions.**

**Alternative Considered:** Keep dual thresholds but lower risky over to 60%

**Rejected Because:** Still arbitrary. If calibration works, 58% should mean 58% regardless of direction. Either we trust the model or we don't.

**File Modified:** `src/engine/parlay_builder.py` (+34 lines, -59 lines)

**Commit:** `a38467f` - feat: trust ML model uniformly - remove risky over threshold

---

## ML Model Replaces Heuristic Scoring (April 29, 2026 - Evening)

**Decision:** Migrate from hand-coded composite scoring to machine learning-based predictions.

**Context:**
- Heuristic scoring used arbitrary weights (40% overall + 30% vs_hand + 30% recent for hitters)
- No way to validate if these weights were optimal
- 77K training samples sitting unused while heuristics guessed at patterns
- Claude's analysis critiqued ML-generated parlays as "weak" - suggested model wasn't using data

**The Shift:**

**Old System (Heuristic):**
```python
# For hitters
composite_score = (
    coverage_overall × 0.40 +
    coverage_vs_hand × 0.30 +
    coverage_recent_10 × 0.30
)

# For pitchers  
composite_score = (
    coverage_overall × 0.35 +
    coverage_recent_5 × 0.25 +
    pitcher_quality × 0.20 +
    opponent_offense × 0.20
)
```

**New System (ML):**
```python
# Load trained model
model = pickle.load(open('models/leg_scorer_v2.pkl'))

# Extract 19 features per leg
features = extract_features(leg)

# Predict P(hit) using learned patterns from 77K outcomes
prob_hit = model.predict_proba([features])[0][1]

# Set composite score
composite_score = prob_hit × 100
```

**Why ML is Better:**

1. **Data-Driven:** Learns from 77K actual outcomes, not assumptions
2. **Adaptive:** Weights adjust automatically as data changes
3. **Feature Discovery:** Model learned direction (over/under) is 78% of signal - we didn't know that!
4. **No Bias:** Doesn't assume which stats are "poison" - learns from outcomes
5. **Measurable:** AUC of 0.8532 means 85% discrimination ability

**Implementation:**

**Created:**
- `scripts/train_ml_model.py` - Training pipeline
- `src/engine/ml_leg_scorer.py` - Inference module
- `/api/train-model` endpoint - Browser-triggered training
- `USE_ML_SCORING` environment variable - Feature flag

**Modified:**
- `src/engine/parlay_builder.py` - Routes to ML scorer when flag is true

**Feature Set (19 features):**
- **Numeric (7):** coverage_overall, coverage_vs_hand, coverage_recent_10, coverage_recent_5, pitcher_quality, opponent_offense, line
- **Categorical (12):** direction (over/under), stat one-hots (hits, strikeouts, rbi, etc.)

**Model Details:**
- **Algorithm:** GradientBoostingClassifier
- **Hyperparameters:** 200 trees, max depth 5, learning rate 0.1
- **Training:** 49,296 samples (64% of 77K total)
- **Calibration:** 12,324 samples (16%)
- **Test:** 15,405 samples (20%)

**Result:** Production now uses ML predictions. Heuristic scoring preserved in code but unused.

**Alternative considered:** Hybrid approach (ML + heuristic ensemble)

**Rejected because:** Pure ML performed better and is simpler to maintain

---

## Platt Scaling for Probability Calibration (April 29, 2026 - Evening)

**Decision:** Add Platt Scaling to calibrate ML probability predictions.

**Context:**
- Initial ML model had ROC AUC 0.8538 (excellent discrimination)
- But probabilities were **overconfident**
- Predictions of 70% actually hit ~60% of the time (10pp error)
- This made edge calculations unreliable
- Claude's analysis said "weak parlay" despite ML saying "+105% edge"

**The Problem: Discrimination vs Calibration**

**ROC AUC measures discrimination:** Can the model separate hits from misses?
- AUC 0.8538 = model is very good at ranking legs by likelihood of hitting

**But this doesn't mean probabilities are accurate:**
- Model might say 70% for legs that actually hit 60%
- Or say 50% for legs that actually hit 45%
- Probabilities need **calibration**

**The Solution: Platt Scaling**

Platt Scaling fits a logistic regression on top of model predictions to map them to true probabilities.

**How it works:**

1. Split training data: 64% train / 16% calibration / 20% test
2. Train GradientBoostingClassifier on 64% split
3. Get predictions on 16% calibration set
4. Fit LogisticRegression: `calibrated_prob = sigmoid(a × raw_prob + b)`
5. Wrap both models in `CalibratedModel` class
6. Use calibrated probabilities in production

**Implementation:**

```python
# In scripts/train_ml_model.py

# Train base model
gbc = GradientBoostingClassifier(...)
gbc.fit(X_train_final, y_train_final)

# Get predictions on calibration set
uncal_probs = gbc.predict_proba(X_cal)[:, 1]

# Fit Platt scaler
from sklearn.linear_model import LogisticRegression
platt_model = LogisticRegression()
platt_model.fit(uncal_probs.reshape(-1, 1), y_cal)

# Wrap in calibrated model
class CalibratedModel:
    def __init__(self, base_model, calibrator):
        self.base_model = base_model
        self.calibrator = calibrator
    
    def predict_proba(self, X):
        base_probs = self.base_model.predict_proba(X)[:, 1].reshape(-1, 1)
        cal_probs = self.calibrator.predict_proba(base_probs)[:, 1]
        return np.column_stack([1 - cal_probs, cal_probs])

calibrated_model = CalibratedModel(gbc, platt_model)
```

**Why Manual Implementation?**

Initially tried `sklearn.calibration.CalibratedClassifierCV` with `cv='prefit'`, but:
- Newer sklearn versions don't support `cv='prefit'` parameter
- API changed between versions
- Manual implementation works across all sklearn versions
- Also gives us full control over the calibration process

**Critical Detail: Module-Level Class**

`CalibratedModel` must be defined at **module level**, not inside `train()` function:
- Pickle saves class reference: `scripts.train_ml_model.CalibratedModel`
- If defined inside function: `train.<locals>.CalibratedModel` (unpicklable)
- `ml_leg_scorer.py` loads model → needs to find the class

**Results:**

**Before Calibration:**
- ML predicts 70% → Actually hits 60% (10pp error)
- ML predicts 55% → Actually hits 50% (5pp error)

**After Calibration:**
- ML predicts 76.1% → Actually hits 72.1% (4pp error)
- ML predicts 15.6% → Actually hits 17.6% (2pp error)

**Calibration Curve (10 bins):**
- Low probs (15-20%): Slightly underconfident (+2pp)
- Mid probs (40-60%): Well calibrated (±1pp)
- High probs (70-80%): Slightly overconfident (-4pp)

**Trade-off:**
- Uncalibrated AUC: 0.8538
- Calibrated AUC: 0.8532 (tiny drop expected)
- **Worth it:** Accurate probabilities > raw discrimination for betting

**Alternative considered:** Isotonic regression (non-parametric calibration)

**Rejected because:** Platt Scaling is simpler and works well for tree-based models

---

## Game Time Filtering is Critical (April 29, 2026 - Evening, EXTENDED April 30)

**Decision:** Filter out started/finished games in both regenerate endpoint and scheduled pipeline.

**Context (April 29):**
- User reported: "Recommendations include players from games that already started"
- Critical bug: betting on finished games is nonsensical
- Previous sessions supposedly addressed this, but implementation was missing

**Root Cause:**
- `get_scored_legs()` fetches all legs for today's date
- No filter on `game_start_time` field
- Parlay builder was including legs from 1PM games at 5PM

**Implementation (April 29):**

**Two filter points added:**

**1. Regenerate Endpoint (`src/web/server.py`):**
```python
# After fetching legs
et_tz = pytz.timezone("America/New_York")
now_et = datetime.now(et_tz)
cutoff = now_et - timedelta(minutes=5)

active_legs = []
for leg in legs:
    gst = leg.get("game_start_time")
    if not gst:
        active_legs.append(leg)  # Keep if no time
        continue
    
    try:
        gt = datetime.strptime(gst, "%Y-%m-%d %H:%M:%S")
        if et_tz.localize(gt) > cutoff:
            active_legs.append(leg)
    except Exception:
        active_legs.append(leg)  # Keep if parse fails

# Use active_legs for parlay building
```

**2. Scheduled Pipeline (`main.py`):**
```python
# After Step 6 (enrich legs), before Step 7 (trend signals)
et_tz = pytz.timezone("America/New_York")
now_et = datetime.now(et_tz)
cutoff = now_et - timedelta(minutes=5)

upcoming_legs = []
for leg in enriched_legs:
    gst = leg.get("game_start_time")
    if not gst:
        upcoming_legs.append(leg)
        continue
    
    try:
        gt = datetime.strptime(gst, "%Y-%m-%d %H:%M:%S")
        gt_et = et_tz.localize(gt)
        
        if gt_et > cutoff:
            upcoming_legs.append(leg)
    except Exception:
        upcoming_legs.append(leg)

print(f"[filter_started] {len(enriched_legs)} legs → {len(upcoming_legs)} upcoming")
enriched_legs = upcoming_legs
```

**Key Design Decisions:**

**5-minute grace period:**
- `cutoff = now - 5 minutes`
- Prevents edge cases where game starts exactly at filter time
- User has 5 minutes after first pitch to regenerate

**Keep legs with no game_start_time:**
- Don't silently drop legs if field is missing
- Safer to include than exclude without certainty
- Logs will show how many have missing times

**Field name: `game_start_time` (not `game_time`):**
- Verified via database query
- Set by enrichment step in pipeline
- Format: `"YYYY-MM-DD HH:MM:SS"` in ET timezone

**Logging:**
```
[regenerate] 61 legs → 43 upcoming after filtering started games
[filter_started] 87 legs → 61 upcoming (filtered 26 started)
```

**Why This Wasn't Caught Earlier:**
- Testing done during morning hours when all games were upcoming
- Bug only surfaces in afternoon/evening when early games finish
- Manual testing didn't cover multi-time-slot scenarios

**EXTENSION - April 30 Evening:**

**New Bug Discovered:** Recommendations generation (Step 9) doesn't filter by game time.

**Root Cause:** `generate_recommendations()` re-queries database without applying game_start_time filter.

**Fix In Progress:**
- Add same game time filtering logic to `generate_recommendations()` before building parlays
- Ensures scheduled pipeline AND regenerate endpoint both filter correctly

**FINAL EXTENSION - April 30 End of Day:**

**Ultimate Solution:** Rebuilt Picks tab to be dynamic - filtering now happens in `/api/build-parlays` endpoint before every display. No stored recommendations means no stale data.

**Alternative considered:** Frontend-only filtering

**Rejected because:** Backend must enforce this - can't trust frontend alone

---

## Complete System Rebuild (April 29, 2026 - Morning)

**Decision:** Rebuild coverage calculation, composite scoring, and delivery system from scratch based on validation data showing complete formula failure.

**Context:**
- Validation queries revealed scoring completely broken (70%+ predicted → 46.7% actual)
- User frustrated: "system completely broken", "garbage legs", "further from working than at start"
- Two environments (Discord + web) created confusion
- Training data had 10K unresolved backlog blocking analysis

**Root causes identified:**
1. Coverage formula smooshed all signals together with arbitrary penalties
2. Database CHECK constraint rejected 'void' results → transaction aborts
3. Player IDs were NULL → resolver couldn't match box scores
4. Composite scoring used non-predictive factors (trend, EV, PA stability)

**Rebuild strategy:**
1. Fix data pipeline first (unblock training data)
2. Rewrite coverage to provide raw signals (no smooshing)
3. Rewrite scoring to use only predictive factors
4. Add pitcher quality signals for pitcher props
5. Build recommendations system (backend + frontend)
6. Remove Discord bot entirely (single source of truth)

**Result:**
- Data pipeline: ✅ Fixed
- Coverage: ✅ Rebuilt (3 signals for hitters, 2 for pitchers)
- Scoring: ✅ Rebuilt (pure coverage-based, then replaced by ML)
- Recommendations: ✅ Built (5 parlays per day)
- Discord: ✅ Removed
- System status: Went from "completely broken" to "fully functional" in one session

---

## Raw Coverage Signals (April 29, 2026 - Morning)

**Decision:** Replace smooshed coverage formula with separate raw signals that can be independently validated and weighted.

**Old system (REMOVED):**
```python
coverage = (
    base_coverage × 
    sample_size_penalty × 
    recency_weight × 
    trend_penalty × 
    opponent_penalty
)
```

**Problems:**
- All signals smooshed into one number
- Arbitrary penalties (where did 0.85 come from?)
- Recency weighting (0.6 recent + 0.4 career) was guesswork
- Validation impossible (can't test individual signals)
- Result: 28pp error (70% predicted → 46.7% actual)

**New system (CURRENT - used as ML features):**

**For hitters:**
- `coverage_overall` — Season hit rate (no adjustments)
- `coverage_vs_hand` — Hit rate vs RHP/LHP split (log-odds adjustment for hits/TB/walks only)
- `coverage_recent_10` — Last 10 games hit rate (no adjustments)

**For pitchers:**
- `coverage_overall` — Season hit rate (no adjustments)
- `coverage_recent_5` — Last 5 starts hit rate (user specified 5 not 4)

**Benefits:**
1. Each signal can be validated independently against training data
2. Weights are explicit (either in composite scoring or as ML features)
3. No arbitrary penalties or multipliers
4. Raw % values match what user expects to see

**Validation plan:**
- Query training data: does vs_hand signal actually predict better than overall?
- Query training data: does recent_10 add signal beyond overall?
- Adjust weights in composite scoring based on actual predictive power

**Implementation:**
- `src/engine/coverage.py` - complete rewrite
- Separate functions: `_hitter_coverage()` and `_pitcher_coverage()`
- Minimum 10 games vs hand for split, else NULL (fallback to overall)

**Alternative considered:** Keep smooshed formula, add more penalties

**Rejected because:** Validation data showed it was fundamentally broken, not just poorly tuned

**NOTE:** This system was used for heuristic scoring initially, then became ML features when we switched to ML model on April 29 evening.

---

## Recommendations System Architecture (April 29, 2026 - Morning)

**Decision:** Build persistent storage for 5 daily parlay recommendations with on-demand Claude analysis.

**Context:**
- User wanted AI to "pick the best parlays for me"
- Discord bot posting to channel felt disconnected from web app
- Claude analysis on every parlay wastes API credits

**Design choice: Persistent vs Ephemeral**

**Persistent (INITIALLY CHOSEN, LATER DEPRECATED):**
- Recommendations stored in `mlb_parlay_recommendations` table
- Tracks which parlays won/lost over time
- Enables historical analysis of recommendation quality
- Claude analysis cached (only generated once per parlay)

**Ephemeral (REJECTED INITIALLY, ADOPTED LATER):**
- Generate recommendations on-demand when user visits tab
- No database storage
- Regenerate Claude analysis every time
- Can't track historical performance

**REVERSAL (April 30 End of Day):**

After discovering that stored recommendations became stale as games started, we reversed this decision and adopted the ephemeral approach with dynamic generation from `mlb_scored_legs`.

**Database schema (NOW DEPRECATED):**
```sql
CREATE TABLE mlb_parlay_recommendations (
  id SERIAL PRIMARY KEY,
  recommendation_date DATE NOT NULL,
  pipeline_run_time TIMESTAMP NOT NULL,
  rank INT NOT NULL CHECK (rank BETWEEN 1 AND 5),
  leg_odd_ids TEXT[] NOT NULL,
  combined_odds INT NOT NULL,
  win_probability FLOAT NOT NULL,
  edge_pct FLOAT NOT NULL,
  analysis TEXT,
  bet_status TEXT DEFAULT 'pending',
  UNIQUE (recommendation_date, rank)
);
```

**Generation algorithm (NOW REPLACED BY /api/build-parlays):**
1. Branch-and-Bound finds top 20 parlay combinations (5-8 legs, +1000 to +1500 odds)
2. Calculate `win_probability = product(coverage/100 for each leg)`
3. Calculate `edge_pct = (win_prob × decimal_odds - 1) × 100`
4. Sort by edge_pct descending
5. Apply diversity filter: each leg max 2 appearances across top 5
6. Save top 5 to database, rank 1-5

**API endpoints (DEPRECATED):**
- `GET /api/recommendations` → Hydrates legs from mlb_scored_legs, returns JSON
- `POST /api/analyze-recommendation` → Calls Claude API (300 tokens max), caches result

**Frontend display:**
- Picks tab shows 5 cards (rank 1 highlighted as "BEST BET")
- Each card: combined odds, win %, edge %, all legs with coverage
- "Analyze Parlay" button → Claude generates 2-3 sentence explanation
- "Regenerate Now" button → Triggers on-demand generation

**Claude analysis prompt:**
- Kept simple: analyze strengths/weaknesses of leg combination
- Budget: 300 tokens max
- Cached in database to avoid repeated API calls

**Alternative considered:** Live recommendations (no storage)

**Initially Rejected:** Can't track performance, loses historical context

**Later Adopted (April 30):** Dynamic generation proved necessary to avoid stale data

**NOTE:** With ML model deployed (April 29 evening), recommendations now use ML predictions instead of heuristic scores. The persistent storage architecture was later deprecated in favor of dynamic generation.

---
