# MLB Parlay Agent — Architecture Decisions

**Last Updated:** April 30, 2026 (Evening)

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

**Persistent (CHOSEN):**
- Recommendations stored in `mlb_parlay_recommendations` table
- Tracks which parlays won/lost over time
- Enables historical analysis of recommendation quality
- Claude analysis cached (only generated once per parlay)

**Ephemeral (REJECTED):**
- Generate recommendations on-demand when user visits tab
- No database storage
- Regenerate Claude analysis every time
- Can't track historical performance

**Database schema:**
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

**Generation algorithm:**
1. Branch-and-Bound finds top 20 parlay combinations (5-8 legs, +1000 to +1500 odds)
2. Calculate `win_probability = product(coverage/100 for each leg)`
3. Calculate `edge_pct = (win_prob × decimal_odds - 1) × 100`
4. Sort by edge_pct descending
5. Apply diversity filter: each leg max 2 appearances across top 5
6. Save top 5 to database, rank 1-5

**API endpoints:**
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

**Rejected because:** Can't track performance, loses historical context

**NOTE:** With ML model deployed (April 29 evening), recommendations now use ML predictions instead of heuristic scores. The persistent storage architecture remains unchanged.

**KNOWN BUG (April 30):** Recommendations include started games - game time filter missing from `generate_recommendations()` function. Fix in progress.
