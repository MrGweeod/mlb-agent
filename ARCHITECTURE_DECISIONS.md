# MLB Parlay Agent — Architecture Decisions

**Last Updated:** April 29, 2026 (Evening)

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
ML predicts 70% → Actually hits 60% (10pp error)
ML predicts 55% → Actually hits 50% (5pp error)

**After Calibration:**
ML predicts 76.1% → Actually hits 72.1% (4pp error)
ML predicts 15.6% → Actually hits 17.6% (2pp error)

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

## Game Time Filtering is Critical (April 29, 2026 - Evening)

**Decision:** Filter out started/finished games in both regenerate endpoint and scheduled pipeline.

**Context:**
- User reported: "Recommendations include players from games that already started"
- Critical bug: betting on finished games is nonsensical
- Previous sessions supposedly addressed this, but implementation was missing

**Root Cause:**
- `get_scored_legs()` fetches all legs for today's date
- No filter on `game_start_time` field
- Parlay builder was including legs from 1PM games at 5PM

**Implementation:**

**Two filter points needed:**

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
        if et_tz.localize(gt) > cutoff:
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
[regenerate] 61 legs → 43 upcoming after filtering started games
[filter_started] 87 legs → 61 upcoming (filtered 26 started)

**Why This Wasn't Caught Earlier:**
- Testing done during morning hours when all games were upcoming
- Bug only surfaces in afternoon/evening when early games finish
- Manual testing didn't cover multi-time-slot scenarios

**Alternative considered:** Frontend-only filtering
**Rejected because:** Backend must enforce this - can't trust frontend alone

---

## "Regenerate Now" On-Demand Parlay Generation (April 29, 2026 - Evening)

**Decision:** Add button to generate fresh parlays without waiting for scheduled pipeline runs.

**Context:**
- Scheduled pipeline runs at 9AM/12PM/5:30PM only
- Users want to see parlays at other times (e.g., 3PM before late games)
- Original Picks tab showed "wait for next pipeline run" message

**Requirements:**
1. Generate 5 parlays using today's legs from database
2. Use same parlay builder logic as scheduled pipeline
3. Filter out started games (critical!)
4. Update recommendations table (don't duplicate)
5. Show timestamp of last regeneration

**Implementation:**

**Backend Endpoint (`src/web/server.py`):**
```python
@routes.post("/api/recommendations/regenerate")
async def handle_regenerate_recommendations(request):
    # Fetch today's scored legs
    today = datetime.now(_ET).date()
    legs = get_scored_legs(str(today))
    
    # Filter started games
    active_legs = [leg for leg in legs if game_not_started(leg)]
    
    # Calculate composite_score from coverage_pct
    # (Temp fix until pipeline populates it)
    for leg in active_legs:
        leg["composite_score"] = leg.get("coverage_pct") or 50.0
    
    # Build parlays using same logic as pipeline
    qualifying_legs = [
        {**leg, "best_odds": leg["odds"], "best_line": leg["line"]}
        for leg in active_legs if leg.get("coverage_pct", 0) >= 55
    ]
    
    recommendations = generate_recommendations(qualifying_legs)
    
    # Save to database (UPSERT on date+rank)
    for rec in recommendations:
        save_parlay_recommendation(rec)
    
    return {"success": True, "recommendations": recommendations}
```

**Database UPSERT:**
```sql
INSERT INTO mlb_parlay_recommendations (...)
VALUES (...)
ON CONFLICT (recommendation_date, rank)
DO UPDATE SET
    leg_odd_ids = EXCLUDED.leg_odd_ids,
    combined_odds = EXCLUDED.combined_odds,
    ...
```

**Frontend Button (`src/web/static/index.html`):**
```javascript
async function regenerateRecommendations() {
    const btn = document.getElementById('regenerate-btn');
    btn.disabled = true;
    btn.textContent = 'Generating...';
    
    const resp = await fetch('/api/recommendations/regenerate', {
        method: 'POST'
    });
    
    const data = await resp.json();
    
    if (data.success) {
        await loadRecommendations();  // Refresh display
        updateTimestamp();
    }
    
    btn.disabled = false;
    btn.textContent = 'Regenerate Now';
}
```

**Timestamp Display:**
```javascript
function updateTimestamp() {
    const now = new Date();
    const elem = document.getElementById('rec-timestamp');
    elem.textContent = `Updated: ${now.toLocaleTimeString()} ET`;
    
    // Color-code freshness
    const age = Date.now() - lastUpdateTime;
    if (age < 5 * 60 * 1000) {
        elem.className = 'fresh';  // Green
    } else if (age < 30 * 60 * 1000) {
        elem.className = 'stale';  // Yellow
    } else {
        elem.className = 'old';    // Red
    }
}
```

**Key Decisions:**

**UPSERT instead of INSERT:**
- Recommendations table has UNIQUE constraint on (recommendation_date, rank)
- Multiple regenerations per day overwrite previous recommendations
- Tracks the "current best 5 parlays" not historical versions

**Composite score from coverage_pct:**
- Database legs don't have composite_score populated yet
- Temporary workaround: `composite_score = coverage_pct`
- **Not ideal but functional** - scheduled pipeline will populate it properly
- Prevents parlay builder from recalculating scores

**Skip score recalculation in parlay builder:**
```python
if not all(leg.get("composite_score") for leg in eligible):
    # Only score if missing
    score_legs_composite(eligible, ...)
```

**Why This Matters:**
- Without this check, parlay builder overwrites our coverage_pct values
- Recalculation uses full heuristic formula (pitcher quality, trend, etc.)
- We want to preserve the simple coverage_pct → composite_score mapping for regeneration

**Alternative considered:** Always run full pipeline for regeneration
**Rejected because:** Too slow (~2 minutes), overkill for simple refresh

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
- Scoring: ✅ Rebuilt (pure coverage-based)
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

**New system (CURRENT - but replaced by ML):**

**For hitters:**
- `coverage_overall` — Season hit rate (no adjustments)
- `coverage_vs_hand` — Hit rate vs RHP/LHP split (log-odds adjustment for hits/TB/walks only)
- `coverage_recent_10` — Last 10 games hit rate (no adjustments)

**For pitchers:**
- `coverage_overall` — Season hit rate (no adjustments)
- `coverage_recent_5` — Last 5 starts hit rate (user specified 5 not 4)

**Benefits:**
1. Each signal can be validated independently against training data
2. Weights are explicit in composite scoring (not hidden in coverage calc)
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

**NOTE:** This heuristic system was replaced by ML model (April 29 evening), but the raw coverage signals are still used as ML features.

---

## Pure Coverage-Based Composite Scoring (April 29, 2026 - Morning)

**Decision:** Remove all non-predictive factors from composite scoring and use only coverage signals.

**Old system (REMOVED):**
- Coverage: 70%
- EV (odds value): 25%
- Trend: 15%
- Opponent: 15%
- PA stability: 5%

**Validation results:**
- Coverage: predictive but overconfident
- EV: no correlation with outcomes (removed entirely in earlier session)
- Trend: INVERTED signal (COLD 67%, HOT 46%)
- Opponent: no correlation (46.5% across all buckets)
- PA stability: never tested, likely noise

**New system (CURRENT - but replaced by ML):**

**Hitters (3 factors):**
```python
composite_score = (
    coverage_overall × 0.40 +
    coverage_vs_hand × 0.30 +
    coverage_recent_10 × 0.30
)
```

**Pitchers (4 factors):**
```python
composite_score = (
    coverage_overall × 0.35 +
    coverage_recent_5 × 0.25 +
    pitcher_quality × 0.20 +
    opponent_offense × 0.20
)
```

**Weight redistribution when signals missing:**
- If `vs_hand` is NULL → `overall` gets 0.70 (was 0.40)
- If `recent_10` is NULL → `overall` gets 0.70
- If both missing → `overall` gets 1.00

**Rationale:**
- Only use signals that actually predict outcomes
- Coverage is the ONLY factor with proven predictive power
- Separate signals (overall, vs_hand, recent) allow flexible weighting
- Pitcher quality added for pitcher props (different dynamic than hitters)

**Implementation:**
- `src/engine/leg_scorer.py` - complete rewrite
- New functions: `_score_hitter_leg()`, `_score_pitcher_leg()`
- Router: `score_leg()` detects pitcher vs hitter by position/stat
- All 7 tests passing

**Next step:** Validate with training data
- Does vs_hand actually improve predictions?
- Should weights be 40/30/30 or something else?
- Recalibrate after collecting outcomes with new scoring

**Alternative considered:** Keep all 5 factors, retune weights
**Rejected because:** Trend/opponent/PA showed zero or negative correlation - no amount of tuning fixes that

**NOTE:** This heuristic system was entirely replaced by ML model (April 29 evening). The coverage signals are now used as ML features instead of being weighted manually.

---

## Pitcher Quality Signals (April 29, 2026 - Morning)

**Decision:** Add pitcher ERA/K9/WHIP rankings and opponent team offensive rankings as factors for pitcher prop scoring.

**Context:**
- Pitcher props scored poorly with pure coverage (no opponent context)
- Validation showed pitcher props need different signals than hitter props
- User wanted "pitcher-aware matchup logic" per original blueprint

**New modules created:**

**`src/apis/pitcher_stats.py`:**
- Ranks all qualified starters (min 50 IP) by ERA/K9/WHIP
- 24-hour cache (refreshes daily)
- Returns `{pitcher_id: {"era_rank": N, "k9_rank": N, "whip_rank": N}}`
- Rank 1 = best (lowest ERA), Rank 30 = worst (highest ERA)

**`src/apis/team_stats.py`:**
- Ranks all 30 teams by strikeout rate, batting average, runs per game
- 24-hour cache
- For ranking: lower K% = better (rank 1), higher BA = better (rank 1)

**Scoring routes by stat:**
- Strikeouts → K9 rank (70%) + opponent K% inverted (30%)
  - High K/9 pitcher + high K% team = favorable for strikeouts over
- Hits Allowed → WHIP rank (70%) + opponent BA inverted (30%)
  - Low WHIP pitcher + low BA team = favorable for hits allowed under
- Earned Runs → ERA rank (70%) + opponent RPG inverted (30%)
  - Low ERA pitcher + low RPG team = favorable for earned runs under

**Normalization:**
- Ranks 1-30 normalized to [0, 100] scale
- `normalized = 100 × (31 - rank) / 30`
- Rank 1 → 100 (best), Rank 30 → 0 (worst)
- For inverted signals (opponent K%), flip: `100 - normalized`

**Integration:**
- `main.py` fetches ranks once per pipeline run (Step 4.5)
- `_attach_pitcher_rank_signals()` adds 6 rank fields to pitcher legs before scoring
- Scorer uses rank values in pitcher composite formula (20% each)

**Result:**
- Web app showed 36 legs (was 18 garbage legs)
- Mix of hits/strikeouts, 62-73% coverage
- No more poison-stat monopoly

**Alternative considered:** Use raw ERA/K9/WHIP values instead of ranks
**Rejected because:** Ranks are more stable across season (ERA 3.50 in April ≠ ERA 3.50 in September)

**NOTE:** These signals are now used as ML features (pitcher_quality, opponent_offense) rather than being manually weighted in heuristic scoring.

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
1. Branch-and-Bound finds top 20 parlay combinations (4-8 legs, +1000 to +1500 odds)
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
- "Regenerate Now" button → Triggers on-demand generation (added April 29 evening)

**Claude analysis prompt:**
- Kept simple: analyze strengths/weaknesses of leg combination
- Budget: 300 tokens max
- Cached in database to avoid repeated API calls

**Alternative considered:** Live recommendations (no storage)
**Rejected because:** Can't track performance, loses historical context

**NOTE:** With ML model deployed (April 29 evening), recommendations now use ML predictions instead of heuristic scores. The persistent storage architecture remains unchanged.

---
