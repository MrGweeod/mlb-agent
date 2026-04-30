# MLB Parlay Agent — Session Handoff
**Last Updated:** April 30, 2026 (Evening Session)

## Current Status
✅ **ML model trusted uniformly** — No more directional bias in filtering
✅ **Parlays building successfully** — 5-leg combinations at +1400-1500 odds
⚠️ **Critical bug in progress** — Started games appearing in recommendations (fix in flight)
⚠️ **Timestamp bug in progress** — Shows +5 hours ahead (UTC vs ET issue)

---

## What Was Built This Session (April 30, 2026 - Full Day)

### PHASE 1: Fix "Regenerate Now" Button (COMPLETE - Morning)

**Initial Problem:**
- Button rendered but returned empty recommendations
- Auto-refresh timer conflict overwrote regenerated parlays
- Only 12 legs total in system

**Root Causes:**
- 5-minute setInterval timer reset page state immediately after regeneration
- Parlay builder using wrong parameters (4-6 legs vs 5-8)
- ML model pickle deserialization error
- Strikeout filter only in parlay builder, not at fetch time

**Fixes Implemented:**
- Wrapped auto-refresh in `startRecsRefreshTimer()` with `clearInterval()`
- Updated `_tier_params()`: min_legs 4→5 for Tiers 1&2
- Created `/api/refresh` endpoint with 3-hour SGO time filter
- Added `_valid_strikeout_line()` validator before database save
- Moved `CalibratedModel` class to `ml_leg_scorer.py` for pickle compatibility

**Files Modified:**
- `src/web/static/index.html` (+257 lines)
- `src/engine/parlay_builder.py` (+15 lines)
- `src/web/server.py` (+147 lines)
- `src/apis/sportsgameodds.py` (+22 lines)
- `main.py` (+22 lines)
- `src/engine/ml_leg_scorer.py` (+62 lines)
- `scripts/train_ml_model.py` (-45 lines)

**Commits:**
- `6906f63` - Refresh button + strikeout filter
- `bf4ed60` - Parlay builder params
- `05a6e1d` - ML model pickle fix
- `8f328c6` - GitHub Actions weekly retraining
- `7318b4a` - ML model v2 committed to git

---

### PHASE 2: Trust the ML Model (COMPLETE - Afternoon)

**Decision:** Remove all directional bias filtering and trust ML predictions uniformly.

**Context:**
- Old system blocked 84% of overs (16/19) with "risky over threshold" at 65%
- ML model already learned direction bias (77% feature importance)
- Calibrated predictions should be trusted: 58% means 58%, regardless of direction

**Changes:**
1. **Removed `RISKY_OVER_THRESHOLD = 65.0`** constant entirely
2. **Renamed `_POISON_OVER_STATS` → `_HIGH_VARIANCE_OVER_STATS`**
   - Old: `{"rbi", "walks", "homeRuns", "stolenBases"}` (hard block)
   - New: `{"homeRuns", "stolenBases"}` (require ML score ≥70)
   - RBIs and walks now allowed at standard 55% threshold
3. **Removed `MAX_RISKY_OVERS = 1`** constraint from Branch-and-Bound
4. **Applied uniform ML score threshold** (55%) to all legs

**Result:**
- Before: 15 eligible legs (12 unders + 3 risky overs)
- After: 25-30 eligible legs (balanced mix)
- Parlays building: 5-leg combinations at +1400-1500 odds ✅

**File Modified:**
- `src/engine/parlay_builder.py` (+34 lines, -59 lines)

**Commit:**
- `a38467f` - Trust ML model uniformly

---

### PHASE 3: Critical Bug Fixes (IN PROGRESS - Evening)

**Bug 1: Timestamp Shows +5 Hours Ahead**
- Symptom: "Updated: 09:09 PM ET" when actual time is 4:09 PM ET
- Cause: Frontend using UTC `new Date()` instead of ET timezone
- Fix: Convert to ET in JavaScript (in flight)

**Bug 2: Started Games in Recommendations**
- Symptom: Jung Hoo Lee (SF @ PHI game started at 4:05 PM) in 4:09 PM recommendations
- Cause: `generate_recommendations()` doesn't filter by `game_start_time`
- Fix: Add game time filter before building parlays (in flight)

**Files Being Modified:**
- `src/web/static/index.html` - ET timezone conversion
- `main.py` - Game time filter in `generate_recommendations()`

---

## Current Architecture

### **Data Flow:**
Daily Pipeline (9AM/12PM/5:30PM ET):
├─ Step 1: Fetch transactions (IL placements)
├─ Step 2: Build schedule + pitcher maps
├─ Step 3: Fetch props from SGO (150 raw props)
├─ Step 4: Compute coverage (31 qualifying at ≥55%)
├─ Step 5: Filter blocked players
├─ Step 6: Enrich with pitcher matchup profiles
├─ Step 6.5: Filter started games ✅
├─ Step 7: Compute trend signals
├─ Step 8: Build parlays (uses ML scorer, trusts uniformly) ✅
└─ Step 9: Generate recommendations ⚠️ NEEDS GAME TIME FILTER

Refresh Endpoint:
├─ Fetch games starting >3 hours from now (reduces API usage)
├─ Run Steps 1-7 with time override
├─ Build parlays with filtered legs
└─ Return to frontend

Regenerate Recommendations:
├─ Fetch scored_legs from database
├─ Filter by game_start_time ⚠️ NOT IMPLEMENTED YET
├─ Build parlays via Branch-and-Bound
├─ Save top 5 to mlb_parlay_recommendations
└─ Return to frontend

---

## ML Model Architecture

**Training (via /api/train-model):**
- Query: 77,025 samples from mlb_training_data
- Features: 19 total (7 numeric coverage + direction + 11 stat one-hots)
- Split: 64% train / 16% calibration / 20% test
- Algorithm: GradientBoostingClassifier (200 trees, max_depth 5)
- Calibration: Platt Scaling (manual implementation)
- Output: `models/leg_scorer_v2.pkl` (681 KB)

**Performance:**
- Uncalibrated AUC: 0.8532
- Calibrated AUC: 0.8532
- Accuracy: 78%
- Hit rate: 45.4%

**Feature Importance (Top 5):**
1. Direction (over/under): 77.2% 🔥
2. Strikeouts: 5.6%
3. Stolen Bases: 3.4%
4. Line: 2.5%
5. Hits: 1.7%

**Inference (daily pipeline):**
- Load `models/leg_scorer_v2.pkl`
- Extract 19 features per leg
- Call `model.predict_proba(features)`
- Set `composite_score = P(hit) × 100`
- Parlay builder ranks by composite_score

---

## Current Blockers

### HIGH PRIORITY (In Progress)
1. **Started games in recommendations** - Fix being deployed
2. **Timestamp +5 hours ahead** - Fix being deployed

### MEDIUM PRIORITY (Not Started)
3. **Low leg count on some slates** - Only 31/150 props qualify (21% pass rate)
4. **Season minimum threshold too strict?** - 20 games required, many players filtered early season

### LOW PRIORITY (Future)
5. **No parlay-level outcome tracking** - Can't measure which recommendations won/lost
6. **Manual Supabase cleanup needed** - Invalid strikeout props from earlier runs still in DB

---

## Next Session Priorities

### IMMEDIATE (After Current Fixes Deploy)
1. **Verify timestamp displays correctly** in ET timezone
2. **Verify recommendations exclude started games** (only 7:05 PM+ games at 4:09 PM)
3. **Monitor 5:30 PM pipeline run** - Full 11-game slate, should produce better parlays
4. **Test Regenerate Now** with evening games only

### HIGH PRIORITY (Tomorrow)
5. **Track ML performance** - Compare win rates over next 7 days
6. **Investigate 21% pass rate** - Why only 31/150 props qualify?
7. **Lower season minimum?** - 20 games → 15 games for early season
8. **Supabase cleanup** - Remove invalid strikeout props from run_date='2026-04-30'

### MEDIUM PRIORITY (Next Week)
9. **Outcome resolver for recommendations** - Track which parlays won/lost
10. **Weekly model retraining schedule** - Verify GitHub Actions works Sunday 2 AM ET
11. **A/B testing framework** - ML vs heuristic comparison
12. **Feature engineering** - Add ballpark factors, weather, line movement

### LOW PRIORITY (Future)
13. **Create Blueprint v2.0** - Current blueprint predates ML architecture
14. **Parlay-level ML optimizer** - Predict combination success, not just individual legs
15. **Dashboard enhancements** - Charts, visualizations, export functionality

---

## Key Files Modified This Session

| File | Changes | Lines | Commits |
|------|---------|-------|---------|
| `src/web/static/index.html` | Auto-refresh timer, Refresh button, timestamp | +257 | 6906f63, (pending) |
| `src/engine/parlay_builder.py` | 5-8 legs, trust ML uniformly, remove risky over | +49, -60 | bf4ed60, a38467f |
| `src/web/server.py` | /api/refresh endpoint, regenerate fixes | +147 | 6906f63 |
| `src/engine/ml_leg_scorer.py` | CalibratedModel class (pickle fix) | +62 | 05a6e1d |
| `scripts/train_ml_model.py` | Import CalibratedModel from ml_leg_scorer | -45 | 05a6e1d |
| `main.py` | Strikeout validator, game time filter, refresh override | +44 | 6906f63, (pending) |
| `src/apis/sportsgameodds.py` | starts_after_override parameter | +22 | 6906f63 |
| `.github/workflows/retrain-model.yml` | Weekly Sunday 2 AM ET cron job | NEW | 8f328c6 |
| `models/leg_scorer_v2.pkl` | Trained ML model (681 KB) | NEW | 7318b4a |

**Total (Full Day):** ~600 lines added, ~200 lines deleted, net +400 lines

---

## Git Commits This Session

1. `6906f63` - Refresh button + 3-hour SGO filter + strikeout validator + auto-refresh timer
2. `bf4ed60` - Parlay builder params: 5-8 legs, +1000-1500 odds
3. `05a6e1d` - ML model pickle fix: CalibratedModel to ml_leg_scorer
4. `8f328c6` - GitHub Actions weekly retraining workflow
5. `7318b4a` - Commit trained ML model v2 to git
6. `a38467f` - Trust ML model uniformly: remove risky over threshold
7. **(pending)** - Fix timestamp ET conversion + started games filter

**Branch:** master  
**Remote:** origin/master (up to date except pending commit)

---

## Environment Variables

| Variable | Value | Purpose |
|----------|-------|---------|
| USE_ML_SCORING | **true** | Use ML model instead of heuristic scoring |
| ADMIN_SECRET | train_ml_123 | Secret for /api/train-model endpoint |
| PYTHONPATH | /app | Module import path (Railway) |

All other env vars unchanged (DATABASE_URL, ANTHROPIC_API_KEY, etc.)

---

## Database Status

| Table | Action | Row Count |
|-------|--------|-----------|
| `mlb_training_data` | No changes | 77,025 rows |
| `mlb_scored_legs` | Cleanup needed (invalid SO lines) | 31 rows (today) |
| `mlb_parlay_recommendations` | Working (has started games bug) | 5 rows |

**Cleanup Query (Run in Supabase SQL Editor):**
```sql
DELETE FROM mlb_scored_legs 
WHERE run_date = '2026-04-30' 
  AND stat = 'strikeouts' 
  AND position NOT IN ('P', 'SP', 'RP') 
  AND line != 0.5;

DELETE FROM mlb_scored_legs 
WHERE run_date = '2026-04-30' 
  AND stat = 'strikeouts' 
  AND position IN ('P', 'SP', 'RP') 
  AND line < 3.5;
```

---

## Production Status

**Railway Deployment:** ✅ Live (auto-deploys on git push)
- URL: https://mlb-agent.up.railway.app/
- Last deploy: commit `a38467f` (trust ML model)
- Status: Healthy, running
- Next deploy: Pending (timestamp + started games fix)

**ML Model:** ✅ Trained and Deployed
- Path: `/app/models/leg_scorer_v2.pkl`
- Size: 681 KB
- AUC: 0.8532 (calibrated)
- Training samples: 49,296
- Feature importance: Direction 77%, Strikeouts 5.6%

**Web App:** ✅ Functional (with known bugs)
- 4 tabs: Legs, Dashboard, Training, Picks
- Password protected
- Auto-refresh every 60 seconds
- Parlays building at +1400-1500 odds

**Pipeline Schedule:** ✅ Active
- 9:00 AM ET - Resolve + fresh pipeline
- 12:00 PM ET - Mid-day update
- 5:30 PM ET - Final before first pitch

**GitHub Actions:** ✅ Configured
- Weekly model retraining: Every Sunday 2:00 AM ET
- Manual trigger available via workflow_dispatch

---

## Key Learnings & Principles

**Trust the ML Model:**
- We spent all day training and calibrating it with 77K samples
- The model learned direction bias (77% feature importance) from data
- Overriding it with arbitrary thresholds wastes that work
- Result: Removing risky over threshold enabled parlay building

**Calibration is Critical:**
- Raw ML predictions were overconfident (70% → 60% actual)
- Platt Scaling fixed this (76% → 72% actual, only 4pp error)
- Calibrated probabilities make edge calculations accurate

**Game Time Filtering Must Be Everywhere:**
- Not just in Refresh endpoint - also in recommendation generation
- 5-minute grace period prevents edge cases
- Critical for preventing bets on finished games

**Pickle Requires Module-Level Classes:**
- Classes defined inside functions can't be pickled
- `CalibratedModel` must be at module level for ml_leg_scorer.py to load it
- Moving it from train script to inference module fixed deserialization

**SGO API Optimization:**
- 3-hour time filter reduces API usage by 50% (150 → 75 props per refresh)
- Monthly impact: ~50K objects vs 100K limit (sustainable)
- Scheduled pipelines use full fetch, manual refreshes use filtered

**Frontend Timezone Handling:**
- `new Date()` returns UTC, not local time
- Must explicitly convert to ET for display
- Affects timestamps, countdowns, freshness indicators

---

## Open Questions

**For Tomorrow's 9AM Pipeline:**
1. Do recommendations now exclude started games correctly?
2. Does timestamp show correct ET time?
3. With full slate and ML trusted, how many legs qualify?
4. What's the actual win rate on today's +1455 and +1441 parlays?

**For Next Week:**
5. Should we lower season minimum from 20 → 15 games for early season?
6. Why only 31/150 props qualify (21% pass rate)?
7. Is 55% ML score threshold too strict?
8. Can we add ballpark factors or weather signals to ML features?

---

## Session Summary

**Status:** Went from "Refresh broken, no parlays building" to "ML model trusted, parlays at +1400-1500 odds"

**Major Achievement:** Complete transition to trusting ML model predictions uniformly, removing hand-coded directional bias

**Critical Bugs Found:** Started games in recommendations, timestamp timezone error (both being fixed)

**System Health:** ✅ Core pipeline functional, ML model working, parlays building successfully

**Next Milestone:** Deploy bug fixes, validate with evening games, monitor 5:30 PM pipeline run
