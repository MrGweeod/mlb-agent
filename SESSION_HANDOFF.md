# MLB Parlay Agent — Session Handoff
**Last Updated:** April 24, 2026

## Current Status
✅ **ML model trained** — GradientBoostingClassifier, 86.5% AUC, 49K samples
✅ **Smart parlay filter deployed** — blocks poison overs, max 1 risky over
✅ **Web app UI enhanced** — team names, pitcher handedness, game time filtering
✅ **Dashboard updated** — shows 66K training data samples (March 28 - April 22)

---

## What Was Built This Session (April 24, 2026)

### 1. Training Data Deep Dive Analysis

**Ran 3 critical queries to validate hypotheses:**

**Query 1: Parlay probability by composite score tier**
- 65+ score: 7.77% 4-leg parlay win rate (profitable at +1500)
- 55-65 score: 6.27% (barely breakeven)
- <45 score: 3.71% (disaster)

**Key insight:** Only use 65+ composite score legs in parlays

**Query 2: Direction bias by score tier**
- High-score overs (50+): 42.2% hit rate (still bad)
- Low-score overs (<50): 16.4% hit rate (catastrophic)
- High-score unders (50+): 65.4% hit rate (good)
- Low-score unders (<50): 83.0% hit rate (amazing)

**Key insight:** Even high-score overs underperform; unders dominate regardless of score

**Query 3: Golden stat+direction combinations**
- RBI under: 85.4% hit rate (best)
- Walks under: 80.5% hit rate
- TotalBases under: 74.0% hit rate
- Hits under: 69.6% hit rate
- ---
- RBI over: 14.6% hit rate (worst - poison)
- Walks over: 19.4% hit rate (poison)
- HR over: 6.1% hit rate (poison)

**Key insight:** Specific stat+direction combos have massive performance gaps

**Query 4: Hits over breakdown (user request)**
- Hits over 0.5 with 65+ score: 44.4% hit rate (372 samples)
- Hits over 0.5 with <65 score: 32-34% hit rate (2,767 samples)

**Decision:** Allow hits over 0.5 with 65+ score, but limit to max 1 per parlay

---

### 2. ML Model Training (Phase 3A)

**File:** `src/engine/ml_scorer.py` (298 lines)

**Model:** GradientBoostingClassifier + IsotonicCalibration
- Training samples: 49,222 (with features)
- Test samples: 9,845 (20% holdout)
- ROC AUC: 0.8648
- Accuracy: 80%

**Feature Importance:**
1. direction: 76.6% ← Model learned over/under bias is dominant!
2. composite_score: 6.9%
3. opponent_adjustment: 4.9%
4. coverage_pct: 3.9%
5. line: 2.2%

**Smoke test results:**
- Under hits 0.5: 61.5% predicted ✅
- Over hits 0.5: 38.4% predicted ✅
- Over HR 0.5: 16.4% predicted ✅ (poison)
- Under RBI 0.5: 88.3% predicted ✅ (golden)

**Status:** Model trained and saved to `models/leg_scorer_v1.pkl`, ready for A/B testing

---

### 3. Smart Parlay Filter (Phase 3B)

**File:** `src/engine/parlay_builder.py`

**New function:** `filter_and_tag_legs()`

**Poison overs (BLOCKED entirely):**
- RBI overs: 14.6% hit rate
- Walks overs: 19.4% hit rate
- Home runs overs: 6.1% hit rate

**Risky overs (ALLOWED, max 1 per parlay):**
- Hits over 0.5 with 65+ composite score: 44.4% hit rate
- Pitcher strikeouts over 4.5+ with 65+ score: 44.6% hit rate

**All other overs:** BLOCKED (includes low-score hits overs, ambitious lines)

**Branch-and-Bound constraint added:**
- Max 1 leg with `is_risky_over=True` per parlay
- Tracked via counter that naturally reverts on backtrack

**Integration:** Runs automatically inside `build_hybrid_parlays()` before pool selection

**Expected impact:** Win rate improvement from 47.7% to 52-58%

---

### 4. Web App UI Improvements

**Files modified:**
- `src/pipelines/enrich_legs.py` (added game time + pitcher handedness lookup)
- `src/utils/db.py` (added 2 columns to insert)
- `src/web/server.py` (return current_time_est)
- `src/web/static/index.html` (display format, sorting, filtering)

**Database schema:**
```sql
ALTER TABLE mlb_scored_legs 
ADD COLUMN game_start_time TIMESTAMP,
ADD COLUMN pitcher_hand TEXT;
```

**New features:**
1. **Team abbreviations:**
   - Hitters: `Gunnar Henderson (BAL)`
   - Pitchers: `Luis Severino (ATH, RHP)`

2. **Game time sorting:**
   - New "Time" button in sort bar
   - Sorts earliest games first (1pm at top, 10pm at bottom)

3. **Auto-filter started games:**
   - Compares `game_start_time > current_time_est` (both EST)
   - Legs disappear when game starts
   - Can't accidentally bet on started games

4. **Game time display:**
   - Shows below player name: `1:05 PM EST`

5. **Auto-refresh:**
   - Changed from 5 minutes to 60 seconds
   - Keeps list fresh as games start

**URL:** https://mlb-agent.up.railway.app/

---

## Next Session Priorities

### HIGH PRIORITY
1. **Monitor production performance** (3-5 days)
   - Track win rate with new filter (baseline: 47.7%)
   - Expected: 52-58% with smart filtering
   - Verify no poison overs in Discord recommendations

2. **A/B test ML vs heuristic scoring**
   - After filter proves out, enable ML scoring
   - Compare parlay quality over 5-7 days
   - Roll out ML to production if superior

3. **Add prospective training data collection**
   - Wire 12PM props into `mlb_training_data` table
   - Adds ~300 samples/day going forward
   - Growing dataset for continuous ML improvement

### MEDIUM PRIORITY
- Build Smart Builder Mode 2 (live P(win), replacement suggestions)
- Add ballpark factors to training data features
- Investigate coverage overconfidence (12-23pp errors still present)

### LOW PRIORITY
- Parlay-level ML optimizer (learns which leg combinations work)
- Dashboard enhancements (more detailed analytics)

---

## Key Files Modified Today

| File | Changes |
|------|---------|
| `src/engine/ml_scorer.py` | NEW — 298 lines, ML model training + inference |
| `models/leg_scorer_v1.pkl` | NEW — Trained model artifact |
| `src/engine/parlay_builder.py` | Added filter_and_tag_legs(), risky over constraint |
| `src/pipelines/enrich_legs.py` | Added game time + pitcher handedness lookup |
| `src/utils/db.py` | Added 2 columns to log_scored_legs insert |
| `src/web/server.py` | Return current_time_est in /api/legs |
| `src/web/static/index.html` | Player display format, game time sort/filter |
| `.gitignore` | Added __pycache__/ exclusion |

---

## Database Changes

| Table | Action |
|-------|--------|
| `mlb_scored_legs` | ADDED columns: game_start_time, pitcher_hand |

---

## Git Status

**Latest commits:**
- 5c7af46: chore: ignore __pycache__ files
- b507867: feat: web app UI improvements
- 4992524: feat: add ML scorer and parlay over-filter
- 59c43a5: (previous session)

**Branch:** master  
**Remote:** origin/master (up to date)

---

## Environment
- Repository: github.com/MrGweeod/mlb-agent
- Deployment: Railway (mlb-agent project) — production pipeline running 3×/day
- Web app: https://mlb-agent.up.railway.app/
- Database: Supabase PostgreSQL (mlb_training_data: 73,942 rows, mlb_scored_legs: 614+ rows)
- Python: 3.10 in venv (WSL2 Ubuntu)

---

## Key Learnings & Principles

**Direction bias is the dominant signal:**
- ML model learned direction (over/under) is 76.6% of predictive power
- Books systematically shade over lines too high (79.2% under win rate vs 21.9% over)
- This is a real, exploitable market inefficiency

**Composite score matters, but has a threshold:**
- 65+ score: Profitable for parlays (7.77% 4-leg win rate)
- 55-65 score: Breakeven to slightly losing
- <55 score: Losing proposition

**Stat+direction interactions are massive:**
- RBI under (85.4%) vs RBI over (14.6%) = 71pp delta
- Can't treat "RBI" as a single category — direction completely changes the bet

**High-score overs are marginal, not strong:**
- Hits over 0.5 with 65+ score: 44.4% (viable but not dominant)
- Should be used sparingly (max 1 per parlay)
- Unders should be the foundation of every parlay

**User intuition was partially correct:**
- Hits over 0.5 DOES improve with high composite score (44.4% vs 30.4% avg)
- But it's still not profitable enough to build parlays around
- Solution: Allow them, but constrain their usage
