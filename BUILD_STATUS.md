# MLB Parlay Agent — Build Status

**Last Updated:** 2026-04-30 (Evening)
**Blueprint Version:** v1.0 (OUTDATED - needs v2.0 with ML architecture)
**Repo:** github.com/MrGweeod/mlb-agent

## Infrastructure Status
| Component | Status | Notes |
|-----------|--------|-------|
| Railway Deployment | ✅ Live | Auto-deploys on git push, commit a38467f |
| Discord Bot | ❌ Removed | Deleted April 29 - web app is single source |
| Web App | ✅ Production | 4 tabs, ML-powered, password protected |
| Supabase PostgreSQL | ✅ Active | All mlb_* tables operational |
| ML Model | ✅ Deployed | leg_scorer_v2.pkl (681 KB, AUC 0.8532) |
| GitHub Actions | ✅ Active | Weekly retraining every Sunday 2 AM ET |

## Build Progress

### ✅ Phase 1 — Direct NBA Agent Copies (Complete)
All modules copied and working. No changes needed.

### ✅ Phase 2 — MLB Adaptations (Complete - REBUILT April 29-30)

**Coverage Calculation - COMPLETE REWRITE (April 29):**
- Old: Single smooshed coverage with penalties → REMOVED
- New: 3 separate signals for hitters, 2 for pitchers
- Hitter signals: coverage_overall, coverage_vs_hand, coverage_recent_10
- Pitcher signals: coverage_overall, coverage_recent_5
- File: `src/engine/coverage.py` (218 lines added, 266 removed)

**Composite Scoring - COMPLETE REWRITE (April 29, then REPLACED April 30):**
- April 29: Rebuilt heuristic (40% overall + 30% vs_hand + 30% recent)
- April 30: **Replaced entirely with ML model predictions**
- Current: `composite_score = ML_model.predict_proba(features) × 100`
- File: `src/engine/leg_scorer.py` (heuristic code preserved but unused)

**Pitcher Quality Module - ADDED (April 29):**
- `src/apis/pitcher_stats.py` - ERA/K9/WHIP rankings (142 lines)
- `src/apis/team_stats.py` - Team K%/BA/RPG rankings (128 lines)
- Used as ML features (pitcher_quality, opponent_offense)

### ✅ Phase 3 — New Modules (Complete - ENHANCED)

**Recommendations System - BUILT (April 29):**
- Backend: `generate_recommendations()` in `main.py` (Step 9)
- Database: `mlb_parlay_recommendations` table schema
- API: `/api/recommendations` (GET), `/api/analyze-recommendation` (POST)
- Frontend: Picks tab with Claude analysis integration
- **Known Bug:** Includes started games (fix in progress)

**Refresh Button - BUILT (April 30):**
- Endpoint: `POST /api/refresh` with 3-hour SGO time filter
- Frontend: Button wired to regenerate parlays on-demand
- Auto-refresh timer resets after regeneration
- **Known Bug:** Timestamp shows +5 hours ahead (fix in progress)

**Data Pipeline - FIXED (April 29-30):**
- Database CHECK constraint fixed (allows 'void')
- Player ID lookup added (SGO string IDs → MLB numeric IDs)
- Strikeout validator added (hitter SO 0.5, pitcher SO ≥3.5)
- Game time filtering added (removes started games)
- 10K unresolved backlog cleared

**Discord Bot - REMOVED (April 29):**
- `bot.py` deleted
- `src/bot/*` deleted
- Pipeline scheduler moved to `src/web/server.py`

### ✅ Phase 4 — ML Training Data Collection (Complete - April 27)
- Historical backfill: 66,174 samples (March 28 - April 22)
- Gap fill: 2,053 samples (April 23-27)
- Prospective collection: ✅ DEPLOYED (~150-200 props/day automatically)
- Outcome resolver: ✅ EXTENDED (resolves both scored_legs and training_data)
- Database: mlb_training_data table fully populated (77,025+ rows)
- Date coverage: March 28 - April 30, 2026 (34 days continuous)

### ✅ Phase 5 — ML Model Training & Deployment (Complete - April 29-30)

**ML Infrastructure Built:**
- Training script: `scripts/train_ml_model.py` (214 lines)
- ML scorer: `src/engine/ml_leg_scorer.py` (137 lines)
- Training endpoint: `/api/train-model?secret=ADMIN_SECRET`
- Feature flag: `USE_ML_SCORING=true` (production default)

**Model Architecture:**
- Algorithm: GradientBoostingClassifier
- Hyperparameters: n_estimators=200, max_depth=5, learning_rate=0.1
- Features: 19 total (7 numeric coverage + direction + 11 stat one-hots)
- Calibration: Platt Scaling (manual implementation)
- Split: 64% train / 16% calibration / 20% test

**Training Results:**
- Samples: 77,025 total → 49,296 train / 12,324 cal / 15,405 test
- Uncalibrated AUC: 0.8532
- Calibrated AUC: 0.8532
- Accuracy: 78%
- Hit rate: 45.4%
- Model size: 681 KB

**Feature Importance (Top 5):**
1. Direction (over/under): 77.2% 🔥
2. Strikeouts: 5.6%
3. Stolen Bases: 3.4%
4. Line: 2.5%
5. Hits: 1.7%

**Calibration Curve:**
- ML predicts 15.6% → Actually hits 17.6% (+2.0pp)
- ML predicts 76.1% → Actually hits 72.1% (-4.0pp)

**Production Status:**
- ✅ Model deployed: `/app/models/leg_scorer_v2.pkl`
- ✅ USE_ML_SCORING=true in Railway
- ✅ Heuristic scoring replaced entirely
- ✅ Parlay builder uses ML predictions for composite_score
- ✅ Model committed to git (prevents Railway ephemeral storage loss)

**Key Insight:** Direction (over/under) is BY FAR the most important signal (77%), confirming unders hit more often than overs.

### ✅ Phase 6 — Trust ML Model Uniformly (Complete - April 30)

**Decision:** Remove all hand-coded directional bias and trust calibrated ML predictions.

**Changes:**
1. **Removed `RISKY_OVER_THRESHOLD = 65.0`** constant
2. **Renamed `_POISON_OVER_STATS` → `_HIGH_VARIANCE_OVER_STATS`**
   - Old: `{"rbi", "walks", "homeRuns", "stolenBases"}` (hard block)
   - New: `{"homeRuns", "stolenBases"}` (require ML score ≥70)
3. **Removed `MAX_RISKY_OVERS = 1`** B&B constraint
4. **Applied uniform ML score threshold (55%)** to all legs

**Result:**
- Before: 15 eligible legs (12 unders + 3 risky overs)
- After: 25-30 eligible legs (balanced mix)
- Parlays building: 5-leg combinations at +1400-1500 odds ✅

**File Modified:**
- `src/engine/parlay_builder.py` (+34 lines, -59 lines)

**Commit:** `a38467f` - Trust ML model uniformly

### ⚠️ Phase 7 — Critical Bug Fixes (IN PROGRESS - April 30 Evening)

**Bug 1: Timestamp +5 Hours Ahead**
- Frontend using UTC `new Date()` instead of ET timezone
- Fix: Convert to ET in JavaScript (in progress)

**Bug 2: Started Games in Recommendations**
- `generate_recommendations()` doesn't filter by game_start_time
- Parlays include players from finished games
- Fix: Add game time filter before building parlays (in progress)

**Files Being Modified:**
- `src/web/static/index.html` - ET timezone conversion
- `main.py` - Game time filter in generate_recommendations()

---

## Production Pipeline Status

### ✅ Core Pipeline (ML-POWERED - April 30)
- 8-step daily pipeline (9AM/12PM/5:30PM ET) - runs from web server
- SGO props fetch (MLB-specific) - enhanced with player ID lookup
- **ML-based scoring (PRODUCTION)** - replaces heuristic composite formula
- **Game time filtering** - removes started games before parlay building
- **Calibrated predictions** - Platt Scaling ensures accurate probabilities
- **Trust ML uniformly** - no directional bias in filtering
- Branch-and-Bound parlay builder - builds 5-8 leg combinations
- **Recommendations generation** - Step 9, needs game time filter fix
- Automated outcome resolution - working
- Prospective training data logging - working
- Health check monitoring - working

### ✅ Web App (4 TABS COMPLETE)

**Legs Tab:**
- Interactive parlay builder with real-time odds
- Position filters (All / Hitters / Pitchers)
- Stat filters
- Coverage % and composite score display
- Auto-filter started games (60-second refresh)

**Dashboard Tab:**
- Performance analytics (6 sections)
- 77K training samples analyzed
- Coverage calibration tracking
- Direction bias heatmaps
- Recent legs table

**Training Tab:**
- 5 analytical sections for ML data quality
- Daily collection health (last 14 days)
- Feature completeness tracking
- Hit rate validation
- Resolver failure detection

**Picks Tab:**
- 5 daily parlay recommendations
- "BEST BET" highlighting (rank 1)
- Combined odds, win probability, edge % display
- All legs with coverage % shown
- "Analyze Parlay" button (Claude analysis)
- "Regenerate Now" button (on-demand generation)
- Timestamp display (currently +5 hours bug)

**Common Features:**
- Team abbreviations (BAL, NYY, LAD, etc.)
- Pitcher handedness (RHP, LHP)
- Game time sorting (earliest first)
- Password protection
- Mobile-responsive design

**URL:** https://mlb-agent.up.railway.app/

### ⚠️ Database & Resolution

**Tables:**
- mlb_scored_legs: 31 production legs (today's props)
- mlb_training_data: 77,025+ props (March 28 - April 30, growing ~150-200/day)
- mlb_parlay_recommendations: 5 rows (today's picks, has started games bug)

**Daily Resolution:**
- 9AM ET automated resolution
- Training data resolved alongside scored_legs
- Calibration tracking
- SQL analytics views for instant metrics

**Cleanup Needed:**
- Invalid strikeout props from earlier runs (manual Supabase query required)

---

## Current Blockers

### HIGH PRIORITY (In Progress)
1. ⚠️ **Started games in recommendations** - Fix being deployed
2. ⚠️ **Timestamp +5 hours ahead** - Fix being deployed

### MEDIUM PRIORITY (Not Started)
3. ⚠️ **Low leg count on some slates** - Only 31/150 props qualify (21% pass rate)
4. ⚠️ **Season minimum threshold too strict?** - 20 games required, many players filtered early

### LOW PRIORITY (Future)
5. **No parlay-level outcome tracking** - Can't measure which recommendations won/lost
6. **Manual Supabase cleanup needed** - Invalid strikeout props still in DB

---

## Next Milestones

### Immediate (Tonight - April 30)
1. Deploy timestamp + started games fixes
2. Verify recommendations exclude started games
3. Test with evening games only (7:05 PM+)
4. Monitor 5:30 PM pipeline run

### Short-term (Tomorrow - May 1)
5. Track ML model performance vs actual outcomes
6. Investigate 21% prop pass rate (why only 31/150 qualify?)
7. Consider lowering season minimum (20 → 15 games)
8. Run Supabase cleanup query for invalid strikeout props

### Medium-term (Next Week)
9. Outcome resolver for recommendations table
10. Verify GitHub Actions weekly retraining (next Sunday)
11. A/B testing: ML vs heuristic comparison
12. Feature engineering: ballpark factors, weather, line movement

### Long-term (Future)
13. Create Blueprint v2.0 (current one predates ML architecture)
14. Parlay-level ML optimizer (predict combination success)
15. Advanced correlation detection
16. Dashboard enhancements: charts, visualizations, exports

---

## Architecture Changes - April 29-30

### Complete System Rebuild (April 29 Morning)
**Scope:** Coverage, scoring, delivery, data pipeline
**Reason:** Validation showed 28pp error (70% predicted → 46% actual)
**Result:** Functional system with ML foundation

**Files Rebuilt:**
- `src/engine/coverage.py` - Raw signals, no smooshing
- `src/engine/leg_scorer.py` - Pure coverage-based (later replaced by ML)
- `src/apis/pitcher_stats.py` - NEW (pitcher quality rankings)
- `src/apis/team_stats.py` - NEW (opponent offense rankings)
- `src/web/server.py` - Recommendations endpoints
- `src/web/static/index.html` - Picks tab, 4-tab layout

### ML Model Deployment (April 29 Evening)
**Scope:** Training infrastructure, inference module, feature flag
**Result:** Production uses ML predictions instead of heuristics

**Files Added:**
- `scripts/train_ml_model.py` - Training pipeline (214 lines)
- `src/engine/ml_leg_scorer.py` - Inference module (137 lines)
- `models/leg_scorer_v2.pkl` - Trained model (681 KB)
- `.github/workflows/retrain-model.yml` - Weekly automation

### Trust ML Uniformly (April 30 Afternoon)
**Scope:** Remove directional bias, trust calibrated predictions
**Result:** Parlays building at +1400-1500 odds

**Files Modified:**
- `src/engine/parlay_builder.py` - Uniform filtering (+34, -59 lines)

### Refresh Button (April 30 Morning)
**Scope:** On-demand parlay generation, SGO optimization
**Result:** Functional refresh with 3-hour time filter

**Files Modified:**
- `src/web/server.py` - /api/refresh endpoint (+147 lines)
- `src/apis/sportsgameodds.py` - starts_after_override (+22 lines)
- `main.py` - run_pipeline() time override (+22 lines)
- `src/web/static/index.html` - Refresh button, auto-refresh timer (+257 lines)

### Bug Fixes (April 30 Morning-Evening)
**Scope:** Pickle compatibility, strikeout validation, parlay params
**Result:** ML model loads, valid lines enforced, correct parlay sizes

**Files Modified:**
- `src/engine/ml_leg_scorer.py` - CalibratedModel class (+62 lines)
- `scripts/train_ml_model.py` - Import from ml_leg_scorer (-45 lines)
- `main.py` - Strikeout line validator (+22 lines)
- `src/engine/parlay_builder.py` - 5-8 legs, +1000-1500 odds (+15 lines)

**Total (Full Day):** ~600 lines added, ~200 lines deleted, net +400 lines

---

## Production Metrics

### ML Model Performance
- **AUC (Calibrated):** 0.8532
- **Accuracy:** 78%
- **Training samples:** 49,296
- **Test samples:** 15,405
- **Model file:** 681 KB
- **Feature importance:** Direction 77%, Strikeouts 5.6%

### Data Pipeline Health
- **Training data:** 77,025 rows (34 days)
- **Daily collection:** ~150-200 props/day
- **Resolution rate:** ~90% (void/unresolved 10%)
- **Hit rate:** 45.4% overall

### Parlay Building (Post-Trust ML)
- **Eligible legs:** 25-30 (from 150 raw props)
- **Pass rate:** ~20% (needs investigation)
- **Parlay sizes:** 5-8 legs
- **Odds range:** +1000-1500
- **Current output:** +1455, +1441 (5-leg parlays)

### Web App Usage
- **Uptime:** 100% (Railway)
- **Password protected:** Yes
- **Auto-refresh:** 60 seconds
- **Tabs:** 4 (Legs, Dashboard, Training, Picks)

### SGO API Usage
- **Free tier:** 100K objects/month
- **Current usage:** 265 objects (0.27%)
- **Estimated monthly:** 49.5K objects (49.5% with 3 pipelines + 5 refreshes/day)
- **Headroom:** 50.5K objects/month

---

**Last Major Update:** Trust ML model uniformly - remove all directional bias filtering

**System Status:** ✅ Production-ready, parlays building, 2 known bugs being fixed

**Next Review:** After timestamp + started games fixes deploy (tonight)

