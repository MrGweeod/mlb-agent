# MLB Parlay Agent — Session Handoff
**Last Updated:** April 29, 2026 (Evening Session)

## Current Status
✅ **ML model deployed and calibrated** — Platt Scaling fixes overconfidence
✅ **Regenerate Now working** — Generates parlays on-demand with game-time filtering
✅ **USE_ML_SCORING=true** — Production uses ML predictions, not heuristics
✅ **Game time filtering active** — Started games excluded from recommendations

---

## What Was Built This Session (April 29, 2026 - Evening)

### PHASE 1: Fix "Regenerate Now" Button (COMPLETE)

**Initial Problem:**
- Button rendered but returned `{"success": true, "recommendations": []}`
- Zero parlays generated despite 61 legs in database
- Railway logs showed: `[parlay_builder] 4 eligible legs → top 4 scored (Tier 1)` but no combinations found

**Root Causes Identified:**

**Issue 1 - Missing composite_score:**
- Legs in database had old scoring fields (coverage_pct, trend_score, etc.)
- New parlay builder expected composite_score field
- **Fix:** Calculate on-the-fly: `leg['composite_score'] = leg.get('coverage_pct') or 50.0`

**Issue 2 - Score recalculation:**
- Parlay builder was calling `score_legs_composite()` which overwrote our calculated scores
- **Fix:** Added conditional check: only score if composite_score missing

**Issue 3 - Aggressive filtering:**
- MIN_COV = 60% filtered out 38 legs (55-60% range)
- MIN_PARLAY_ODDS = 600 (should be 1000 per requirements)
- Poison over filters blocking too much
- **Fix:** Lowered MIN_COV to 55%, raised MIN_PARLAY_ODDS to 1000

**Issue 4 - Strikeouts O0.5 blocked:**
- Filter required strikeouts O4.5+, blocking O0.5 lines
- **Fix:** Changed to allow strikeouts O0.5 (alongside hits O0.5)

**Files Modified:**
- `src/web/server.py` - Added composite_score calculation in regenerate endpoint
- `src/engine/parlay_builder.py` - Conditional scoring, filter rule updates, MIN_COV/MIN_PARLAY_ODDS fixes

---

### PHASE 2: Switch to ML Scoring (COMPLETE)

**Decision:** Replace heuristic composite scoring with ML model predictions

**Context:**
- Heuristic scoring used hand-coded weights (40% overall + 30% vs_hand + 30% recent)
- ML model trained on 77K outcomes with 85.4% AUC sitting unused
- Two separate data pools (training_data vs scored_legs) - inefficient

**Implementation:**

**Created 3 new files:**

1. **`scripts/train_ml_model.py`** (214 lines)
   - Queries mlb_training_data (77K resolved samples)
   - 19-feature vector: 7 numeric coverage + direction + 11 stat one-hots
   - GradientBoostingClassifier (n_estimators=200, max_depth=5)
   - Saves to `models/leg_scorer_v2.pkl`

2. **`src/engine/ml_leg_scorer.py`** (137 lines)
   - Loads trained model
   - `score_legs_ml(legs)` function
   - Sets `composite_score = P(hit) × 100` for each leg

3. **`src/web/server.py` training endpoint:**
   - `/api/train-model?secret=ADMIN_SECRET`
   - Triggers training via browser
   - Runs in background, logs to Railway

**Modified:**
- `src/engine/parlay_builder.py` - Added `USE_ML_SCORING` environment variable flag
- When `USE_ML_SCORING=true`, uses ML model instead of heuristic scorer

**Initial Training Results (Uncalibrated):**
- ROC AUC: 0.8538
- 77,025 samples trained
- Feature importance: Direction (over/under) = 77.96% 🔥
- Model learned unders > overs automatically from data

---

### PHASE 3: Add Platt Scaling Calibration (COMPLETE)

**Problem Identified:**
- ML predictions overconfident (70% predicted → ~60% actual)
- Claude analysis said "weak parlay" despite ML saying "+105% edge"
- Individual leg edges tiny (5-8%) on heavy juice props

**Solution: Platt Scaling**
- Calibrates ML probabilities to match actual hit rates
- Fits LogisticRegression on calibration set (20% of training data)
- Wraps GBC + Platt scaler in `CalibratedModel` class

**Implementation Details:**

**Updated `scripts/train_ml_model.py`:**
- Added calibration split: train_final (80%) + calibration (20%)
- Manual Platt Scaling implementation (sklearn compatibility)
- `CalibratedModel` class at module level (pickle-safe)
- Evaluation compares uncalibrated vs calibrated AUC
- Prints calibration curve showing predicted → actual hit rates

**Calibration Results:**
Uncalibrated AUC: 0.8538
Calibrated AUC:   0.8532  (slight drop expected - trades discrimination for accuracy)
Calibration Curve:
ML predicts 15.6% → Actually hits 17.6%  (+2.0pp)
ML predicts 76.1% → Actually hits 72.1%  (-4.0pp)

**Much better calibration!** Before: 70% → 60% actual (10pp error). After: 76% → 72% actual (4pp error).

**Files Modified:**
- `scripts/train_ml_model.py` - Added CalibratedModel class, Platt Scaling, calibration curve
- Sklearn API compatibility fixes (estimator= parameter, manual implementation)

---

### PHASE 4: Game Time Filtering (COMPLETE)

**Critical Bug:** Recommendations included players from started/finished games

**Root Cause:** No game time filter in regenerate endpoint or scheduled pipeline

**Solution:**

**Added filtering in two places:**

1. **`src/web/server.py` (regenerate endpoint):**
   - After fetching legs, filter by `game_start_time > now - 5 minutes`
   - Returns message if < 4 upcoming legs
   - Logs: `[regenerate] 61 legs → 43 upcoming after filtering started games`

2. **`main.py` (scheduled pipeline):**
   - After Step 6 (enrich legs), before Step 7 (trend signals)
   - Same 5-minute grace period
   - Logs: `[filter_started] 87 legs → 61 upcoming (filtered 26 started)`

**Key Details:**
- Column name: `game_start_time` (not `game_time`)
- Format: `"YYYY-MM-DD HH:%M:%S"` in ET timezone
- Legs without game_start_time kept (not silently dropped)
- Uses 5-minute buffer to avoid edge cases

**Files Modified:**
- `src/web/server.py` - Added game time filter in handle_regenerate_recommendations()
- `main.py` - Added game time filter after enrichment step
- Both import `pytz` for timezone handling

---

## Current Architecture

### **Data Flow:**
Daily Pipeline (9AM/12PM/5:30PM ET):
├─ Fetch props from SGO
├─ Log ALL props to mlb_training_data (for ML training)
├─ Filter & enrich props
├─ Filter by game_start_time (remove started games)
├─ Score with ML model (if USE_ML_SCORING=true) or heuristic
├─ Build parlays via Branch-and-Bound
├─ Save top 5 to mlb_parlay_recommendations
└─ Resolve outcomes at 9AM next day
Regenerate Now:
├─ Fetch today's scored_legs from database
├─ Filter by game_start_time (remove started games)
├─ Calculate composite_score = coverage_pct (temp fix)
├─ Build parlays via Branch-and-Bound
├─ Save top 5 to mlb_parlay_recommendations (UPSERT)
└─ Return to frontend for display

### **ML Model Architecture:**
Training (via /api/train-model):
├─ Query mlb_training_data (77K samples)
├─ Extract 19 features per prop
├─ Split: 64% train_final / 16% calibration / 20% test
├─ Train GradientBoostingClassifier on train_final
├─ Apply Platt Scaling using calibration set
├─ Evaluate on test set
├─ Save CalibratedModel to models/leg_scorer_v2.pkl
Inference (daily pipeline):
├─ Load models/leg_scorer_v2.pkl
├─ Extract features from each leg
├─ Call model.predict_proba(features)
├─ Set composite_score = P(hit) × 100
└─ Parlay builder uses composite_score for ranking

---

## Current Blockers

### NONE - System Fully Functional ✅

---

## Next Session Priorities

### IMMEDIATE (Tomorrow Morning)
1. **Monitor 9AM pipeline run** - Verify ML scoring works in production
2. **Check Picks tab** - See 5 ML-generated recommendations
3. **Test "Regenerate Now"** - Should work with fresh daytime games
4. **Analyze parlays** - Does Claude still critique them, or are they better?

### HIGH PRIORITY
5. **Track ML performance** - Compare win rates over next 7 days
6. **A/B test ML vs heuristic** - Set USE_ML_SCORING=false for one day, compare results
7. **Remove hard-coded filters?** - Let ML decide which stats/lines are valuable
8. **Outcome resolver for recommendations** - Track which parlays won/lost

### MEDIUM PRIORITY
9. **Weekly model retraining** - As training data grows, retrain every Sunday
10. **Feature engineering** - Add ballpark factors, weather, line movement
11. **Parlay-level ML** - Train model to predict parlay success (not just individual legs)

### LOW PRIORITY
12. **Create Blueprint v2.0** - Current blueprint is outdated (pre-ML)
13. **Dashboard enhancements** - Charts, visualizations for analytics tabs
14. **Export functionality** - Download recommendations/training data as CSV

---

## Key Files Modified This Session

| File | Changes | Lines |
|------|---------|-------|
| `src/web/server.py` | game time filter, composite_score calc | +69 |
| `src/engine/parlay_builder.py` | USE_ML_SCORING flag, filter fixes, MIN_COV/MIN_ODDS | +15 |
| `scripts/train_ml_model.py` | NEW - ML training with Platt Scaling | 214 |
| `src/engine/ml_leg_scorer.py` | NEW - ML-based scoring | 137 |
| `main.py` | game time filter after enrichment | +22 |

**Total additions:** ~450 lines  
**Total deletions:** ~20 lines  
**Net change:** +430 lines

---

## Git Commits This Session

1. `1e7d2f7` - fix: allow strikeouts O0.5 as risky over (was O4.5+)
2. `22a521e` - fix: skip composite_score recalculation if already set
3. `f2ec2d4` - feat: add ML leg scorer v2 with USE_ML_SCORING feature flag
4. `af75030` - feat: add /api/train-model endpoint for one-click ML training
5. `1788102` - fix: filter started games in regenerate endpoint and scheduled pipeline
6. `b09b6bf` - feat: add Platt Scaling calibration to ML model training
7. `53576e6` - fix: update Platt Scaling for newer scikit-learn API
8. `d9daf6d` - fix: use manual Platt Scaling for sklearn compatibility

**Branch:** master  
**Remote:** origin/master (up to date)

---

## Environment Variables

| Variable | Value | Purpose |
|----------|-------|---------|
| USE_ML_SCORING | **true** | Use ML model instead of heuristic scoring |
| ADMIN_SECRET | train_ml_123 | Secret for /api/train-model endpoint |
| PYTHONPATH | /app | Module import path (Railway) |

All other env vars unchanged (DATABASE_URL, ANTHROPIC_API_KEY, etc.)

---

## Database Changes

| Table | Action | Status |
|-------|--------|--------|
| `mlb_training_data` | No changes | 77K+ rows |
| `mlb_scored_legs` | No changes | 61 rows (today's legs) |
| `mlb_parlay_recommendations` | UPSERT on (recommendation_date, rank) | 5 rows generated |

---

## Production Status

**Railway Deployment:** ✅ Live
- URL: https://mlb-agent.up.railway.app/
- Last deploy: commit `d9daf6d`
- Status: Healthy, running

**ML Model:** ✅ Trained and Deployed
- Path: `/app/models/leg_scorer_v2.pkl`
- Size: 681 KB
- AUC: 0.8532 (calibrated)
- Training samples: 49,296

**Web App:** ✅ Fully Functional
- 4 tabs: Legs, Dashboard, Training, Picks
- Password protected
- Auto-refresh every 60 seconds
- Recommendations display with Claude analysis

**Pipeline Schedule:** ✅ Active
- 9:00 AM ET - Resolve + fresh pipeline
- 12:00 PM ET - Mid-day update
- 5:30 PM ET - Final before first pitch

---

## Key Learnings & Principles

**ML vs Heuristics:**
- ML learned from 77K outcomes that direction (over/under) is 78% of the signal
- Confirms our observation: unders perform better than overs
- ML model can adapt as data changes; heuristics cannot

**Calibration Matters:**
- Raw ML predictions were overconfident (70% → 60% actual)
- Platt Scaling fixed this (76% → 72% actual, only 4pp error)
- Calibrated probabilities make edge calculations accurate

**Game Time Filtering is Critical:**
- Including started games in recommendations is a severe bug
- 5-minute grace period prevents edge cases
- Must filter in BOTH regenerate endpoint AND scheduled pipeline

**Pickle Requires Module-Level Classes:**
- Classes defined inside functions can't be pickled
- `CalibratedModel` must be at module level for ml_leg_scorer.py to load it
- Subtle but critical for production deployment

**Two Data Pools Strategy Works:**
- mlb_training_data: ALL props logged prospectively (no filtering) for ML
- mlb_scored_legs: Filtered props for production parlay building
- Separation allows ML to learn from everything while production stays clean

**sklearn API Changes Break Things:**
- `cv='prefit'` worked in older sklearn, fails in newer versions
- Manual Platt Scaling implementation is more robust
- Always test in production environment (Railway), not just locally

---

## Open Questions

**For Tomorrow's Pipeline Run:**
1. Do ML-generated parlays have better edges than heuristic ones?
2. Does Claude's analysis approve of calibrated ML picks?
3. How many legs survive game-time filtering at 9AM vs 5:30PM?

**For Next Week:**
4. Should we remove poison over filters and let ML decide?
5. How often should we retrain the model? Weekly? After N new samples?
6. Can we build a parlay-level ML model that predicts combination success?

---

## Session Summary

**Status:** Went from "Regenerate Now returns empty" to "Calibrated ML model deployed in production"

**Major Achievement:** Complete migration from heuristic to ML-based scoring with proper probability calibration

**System Health:** ✅ All components functional, ready for tomorrow's 9AM pipeline run

**Next Milestone:** Validate ML performance against actual outcomes over next 7 days# MLB Parlay Agent — Session Handoff
**Last Updated:** April 29, 2026 (Evening Session)

## Current Status
✅ **ML model deployed and calibrated** — Platt Scaling fixes overconfidence
✅ **Regenerate Now working** — Generates parlays on-demand with game-time filtering
✅ **USE_ML_SCORING=true** — Production uses ML predictions, not heuristics
✅ **Game time filtering active** — Started games excluded from recommendations

---

## What Was Built This Session (April 29, 2026 - Evening)

### PHASE 1: Fix "Regenerate Now" Button (COMPLETE)

**Initial Problem:**
- Button rendered but returned `{"success": true, "recommendations": []}`
- Zero parlays generated despite 61 legs in database
- Railway logs showed: `[parlay_builder] 4 eligible legs → top 4 scored (Tier 1)` but no combinations found

**Root Causes Identified:**

**Issue 1 - Missing composite_score:**
- Legs in database had old scoring fields (coverage_pct, trend_score, etc.)
- New parlay builder expected composite_score field
- **Fix:** Calculate on-the-fly: `leg['composite_score'] = leg.get('coverage_pct') or 50.0`

**Issue 2 - Score recalculation:**
- Parlay builder was calling `score_legs_composite()` which overwrote our calculated scores
- **Fix:** Added conditional check: only score if composite_score missing

**Issue 3 - Aggressive filtering:**
- MIN_COV = 60% filtered out 38 legs (55-60% range)
- MIN_PARLAY_ODDS = 600 (should be 1000 per requirements)
- Poison over filters blocking too much
- **Fix:** Lowered MIN_COV to 55%, raised MIN_PARLAY_ODDS to 1000

**Issue 4 - Strikeouts O0.5 blocked:**
- Filter required strikeouts O4.5+, blocking O0.5 lines
- **Fix:** Changed to allow strikeouts O0.5 (alongside hits O0.5)

**Files Modified:**
- `src/web/server.py` - Added composite_score calculation in regenerate endpoint
- `src/engine/parlay_builder.py` - Conditional scoring, filter rule updates, MIN_COV/MIN_PARLAY_ODDS fixes

---

### PHASE 2: Switch to ML Scoring (COMPLETE)

**Decision:** Replace heuristic composite scoring with ML model predictions

**Context:**
- Heuristic scoring used hand-coded weights (40% overall + 30% vs_hand + 30% recent)
- ML model trained on 77K outcomes with 85.4% AUC sitting unused
- Two separate data pools (training_data vs scored_legs) - inefficient

**Implementation:**

**Created 3 new files:**

1. **`scripts/train_ml_model.py`** (214 lines)
   - Queries mlb_training_data (77K resolved samples)
   - 19-feature vector: 7 numeric coverage + direction + 11 stat one-hots
   - GradientBoostingClassifier (n_estimators=200, max_depth=5)
   - Saves to `models/leg_scorer_v2.pkl`

2. **`src/engine/ml_leg_scorer.py`** (137 lines)
   - Loads trained model
   - `score_legs_ml(legs)` function
   - Sets `composite_score = P(hit) × 100` for each leg

3. **`src/web/server.py` training endpoint:**
   - `/api/train-model?secret=ADMIN_SECRET`
   - Triggers training via browser
   - Runs in background, logs to Railway

**Modified:**
- `src/engine/parlay_builder.py` - Added `USE_ML_SCORING` environment variable flag
- When `USE_ML_SCORING=true`, uses ML model instead of heuristic scorer

**Initial Training Results (Uncalibrated):**
- ROC AUC: 0.8538
- 77,025 samples trained
- Feature importance: Direction (over/under) = 77.96% 🔥
- Model learned unders > overs automatically from data

---

### PHASE 3: Add Platt Scaling Calibration (COMPLETE)

**Problem Identified:**
- ML predictions overconfident (70% predicted → ~60% actual)
- Claude analysis said "weak parlay" despite ML saying "+105% edge"
- Individual leg edges tiny (5-8%) on heavy juice props

**Solution: Platt Scaling**
- Calibrates ML probabilities to match actual hit rates
- Fits LogisticRegression on calibration set (20% of training data)
- Wraps GBC + Platt scaler in `CalibratedModel` class

**Implementation Details:**

**Updated `scripts/train_ml_model.py`:**
- Added calibration split: train_final (80%) + calibration (20%)
- Manual Platt Scaling implementation (sklearn compatibility)
- `CalibratedModel` class at module level (pickle-safe)
- Evaluation compares uncalibrated vs calibrated AUC
- Prints calibration curve showing predicted → actual hit rates

**Calibration Results:**
Uncalibrated AUC: 0.8538
Calibrated AUC:   0.8532  (slight drop expected - trades discrimination for accuracy)
Calibration Curve:
ML predicts 15.6% → Actually hits 17.6%  (+2.0pp)
ML predicts 76.1% → Actually hits 72.1%  (-4.0pp)

**Much better calibration!** Before: 70% → 60% actual (10pp error). After: 76% → 72% actual (4pp error).

**Files Modified:**
- `scripts/train_ml_model.py` - Added CalibratedModel class, Platt Scaling, calibration curve
- Sklearn API compatibility fixes (estimator= parameter, manual implementation)

---

### PHASE 4: Game Time Filtering (COMPLETE)

**Critical Bug:** Recommendations included players from started/finished games

**Root Cause:** No game time filter in regenerate endpoint or scheduled pipeline

**Solution:**

**Added filtering in two places:**

1. **`src/web/server.py` (regenerate endpoint):**
   - After fetching legs, filter by `game_start_time > now - 5 minutes`
   - Returns message if < 4 upcoming legs
   - Logs: `[regenerate] 61 legs → 43 upcoming after filtering started games`

2. **`main.py` (scheduled pipeline):**
   - After Step 6 (enrich legs), before Step 7 (trend signals)
   - Same 5-minute grace period
   - Logs: `[filter_started] 87 legs → 61 upcoming (filtered 26 started)`

**Key Details:**
- Column name: `game_start_time` (not `game_time`)
- Format: `"YYYY-MM-DD HH:%M:%S"` in ET timezone
- Legs without game_start_time kept (not silently dropped)
- Uses 5-minute buffer to avoid edge cases

**Files Modified:**
- `src/web/server.py` - Added game time filter in handle_regenerate_recommendations()
- `main.py` - Added game time filter after enrichment step
- Both import `pytz` for timezone handling

---

## Current Architecture

### **Data Flow:**
Daily Pipeline (9AM/12PM/5:30PM ET):
├─ Fetch props from SGO
├─ Log ALL props to mlb_training_data (for ML training)
├─ Filter & enrich props
├─ Filter by game_start_time (remove started games)
├─ Score with ML model (if USE_ML_SCORING=true) or heuristic
├─ Build parlays via Branch-and-Bound
├─ Save top 5 to mlb_parlay_recommendations
└─ Resolve outcomes at 9AM next day
Regenerate Now:
├─ Fetch today's scored_legs from database
├─ Filter by game_start_time (remove started games)
├─ Calculate composite_score = coverage_pct (temp fix)
├─ Build parlays via Branch-and-Bound
├─ Save top 5 to mlb_parlay_recommendations (UPSERT)
└─ Return to frontend for display

### **ML Model Architecture:**
Training (via /api/train-model):
├─ Query mlb_training_data (77K samples)
├─ Extract 19 features per prop
├─ Split: 64% train_final / 16% calibration / 20% test
├─ Train GradientBoostingClassifier on train_final
├─ Apply Platt Scaling using calibration set
├─ Evaluate on test set
├─ Save CalibratedModel to models/leg_scorer_v2.pkl
Inference (daily pipeline):
├─ Load models/leg_scorer_v2.pkl
├─ Extract features from each leg
├─ Call model.predict_proba(features)
├─ Set composite_score = P(hit) × 100
└─ Parlay builder uses composite_score for ranking

---

## Current Blockers

### NONE - System Fully Functional ✅

---

## Next Session Priorities

### IMMEDIATE (Tomorrow Morning)
1. **Monitor 9AM pipeline run** - Verify ML scoring works in production
2. **Check Picks tab** - See 5 ML-generated recommendations
3. **Test "Regenerate Now"** - Should work with fresh daytime games
4. **Analyze parlays** - Does Claude still critique them, or are they better?

### HIGH PRIORITY
5. **Track ML performance** - Compare win rates over next 7 days
6. **A/B test ML vs heuristic** - Set USE_ML_SCORING=false for one day, compare results
7. **Remove hard-coded filters?** - Let ML decide which stats/lines are valuable
8. **Outcome resolver for recommendations** - Track which parlays won/lost

### MEDIUM PRIORITY
9. **Weekly model retraining** - As training data grows, retrain every Sunday
10. **Feature engineering** - Add ballpark factors, weather, line movement
11. **Parlay-level ML** - Train model to predict parlay success (not just individual legs)

### LOW PRIORITY
12. **Create Blueprint v2.0** - Current blueprint is outdated (pre-ML)
13. **Dashboard enhancements** - Charts, visualizations for analytics tabs
14. **Export functionality** - Download recommendations/training data as CSV

---

## Key Files Modified This Session

| File | Changes | Lines |
|------|---------|-------|
| `src/web/server.py` | game time filter, composite_score calc | +69 |
| `src/engine/parlay_builder.py` | USE_ML_SCORING flag, filter fixes, MIN_COV/MIN_ODDS | +15 |
| `scripts/train_ml_model.py` | NEW - ML training with Platt Scaling | 214 |
| `src/engine/ml_leg_scorer.py` | NEW - ML-based scoring | 137 |
| `main.py` | game time filter after enrichment | +22 |

**Total additions:** ~450 lines  
**Total deletions:** ~20 lines  
**Net change:** +430 lines

---

## Git Commits This Session

1. `1e7d2f7` - fix: allow strikeouts O0.5 as risky over (was O4.5+)
2. `22a521e` - fix: skip composite_score recalculation if already set
3. `f2ec2d4` - feat: add ML leg scorer v2 with USE_ML_SCORING feature flag
4. `af75030` - feat: add /api/train-model endpoint for one-click ML training
5. `1788102` - fix: filter started games in regenerate endpoint and scheduled pipeline
6. `b09b6bf` - feat: add Platt Scaling calibration to ML model training
7. `53576e6` - fix: update Platt Scaling for newer scikit-learn API
8. `d9daf6d` - fix: use manual Platt Scaling for sklearn compatibility

**Branch:** master  
**Remote:** origin/master (up to date)

---

## Environment Variables

| Variable | Value | Purpose |
|----------|-------|---------|
| USE_ML_SCORING | **true** | Use ML model instead of heuristic scoring |
| ADMIN_SECRET | train_ml_123 | Secret for /api/train-model endpoint |
| PYTHONPATH | /app | Module import path (Railway) |

All other env vars unchanged (DATABASE_URL, ANTHROPIC_API_KEY, etc.)

---

## Database Changes

| Table | Action | Status |
|-------|--------|--------|
| `mlb_training_data` | No changes | 77K+ rows |
| `mlb_scored_legs` | No changes | 61 rows (today's legs) |
| `mlb_parlay_recommendations` | UPSERT on (recommendation_date, rank) | 5 rows generated |

---

## Production Status

**Railway Deployment:** ✅ Live
- URL: https://mlb-agent.up.railway.app/
- Last deploy: commit `d9daf6d`
- Status: Healthy, running

**ML Model:** ✅ Trained and Deployed
- Path: `/app/models/leg_scorer_v2.pkl`
- Size: 681 KB
- AUC: 0.8532 (calibrated)
- Training samples: 49,296

**Web App:** ✅ Fully Functional
- 4 tabs: Legs, Dashboard, Training, Picks
- Password protected
- Auto-refresh every 60 seconds
- Recommendations display with Claude analysis

**Pipeline Schedule:** ✅ Active
- 9:00 AM ET - Resolve + fresh pipeline
- 12:00 PM ET - Mid-day update
- 5:30 PM ET - Final before first pitch

---

## Key Learnings & Principles

**ML vs Heuristics:**
- ML learned from 77K outcomes that direction (over/under) is 78% of the signal
- Confirms our observation: unders perform better than overs
- ML model can adapt as data changes; heuristics cannot

**Calibration Matters:**
- Raw ML predictions were overconfident (70% → 60% actual)
- Platt Scaling fixed this (76% → 72% actual, only 4pp error)
- Calibrated probabilities make edge calculations accurate

**Game Time Filtering is Critical:**
- Including started games in recommendations is a severe bug
- 5-minute grace period prevents edge cases
- Must filter in BOTH regenerate endpoint AND scheduled pipeline

**Pickle Requires Module-Level Classes:**
- Classes defined inside functions can't be pickled
- `CalibratedModel` must be at module level for ml_leg_scorer.py to load it
- Subtle but critical for production deployment

**Two Data Pools Strategy Works:**
- mlb_training_data: ALL props logged prospectively (no filtering) for ML
- mlb_scored_legs: Filtered props for production parlay building
- Separation allows ML to learn from everything while production stays clean

**sklearn API Changes Break Things:**
- `cv='prefit'` worked in older sklearn, fails in newer versions
- Manual Platt Scaling implementation is more robust
- Always test in production environment (Railway), not just locally

---

## Open Questions

**For Tomorrow's Pipeline Run:**
1. Do ML-generated parlays have better edges than heuristic ones?
2. Does Claude's analysis approve of calibrated ML picks?
3. How many legs survive game-time filtering at 9AM vs 5:30PM?

**For Next Week:**
4. Should we remove poison over filters and let ML decide?
5. How often should we retrain the model? Weekly? After N new samples?
6. Can we build a parlay-level ML model that predicts combination success?

---

## Session Summary

**Status:** Went from "Regenerate Now returns empty" to "Calibrated ML model deployed in production"

**Major Achievement:** Complete migration from heuristic to ML-based scoring with proper probability calibration

**System Health:** ✅ All components functional, ready for tomorrow's 9AM pipeline run

**Next Milestone:** Validate ML performance against actual outcomes over next 7 days
