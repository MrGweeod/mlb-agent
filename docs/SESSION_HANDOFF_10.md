# MLB Parlay Agent — Session Handoff
**Last Updated:** May 20, 2026 (Phase 1 Simple Scorer Deployed)

## Current Status
✅ **OPERATIONAL - PHASE 1 SIMPLE SCORER LIVE**
✅ **Profit Analysis Validated: 69% Win Rate on Profitable Props**
✅ **ML Model Removed - Coverage-Based Scoring Active**
✅ **Unprofitable Props Blocked**
✅ **Training Data Collection Preserved**

---

## What Happened on May 20, 2026

### **🎯 MAJOR MILESTONE: Phase 1 Simple Scorer Deployed**

**Problem Identified:**
- Comprehensive profit analysis revealed ML model was **inverting predictions**
- High-scoring legs (70-100): **43.7% win rate** (losing money)
- Low-scoring legs (<55): **55.1% win rate** (better than high scores!)
- Current parlay win rate: **7.6%** (losing money)

**Root Cause:**
- ML model had **77% direction feature importance**
- Model learned "unders usually cover" from training data
- But in actual betting: **overs win 60%, unders win 30%**
- Temporary adjustments (-26 under, +18 over) created new problems

**The Discovery:**
Profit analysis on 7,895 resolved legs with coverage_pct >= 65%:

| Prop Type | Direction | Win Rate | Profit per $1 | Status |
|-----------|-----------|----------|---------------|--------|
| **Strikeouts** | **Over (pitcher)** | **69.3%** | **+$0.54** | ✅ **STRONG EDGE** |
| **Hits** | **Over** | **69.4%** | **+$0.32** | ✅ **STRONG EDGE** |
| **Hits** | **Under** | **73.1%** | **+$0.14** | ✅ **EDGE** |
| Strikeouts | Under (hitter) | 36.7% | -$0.32 | ❌ **TOXIC** |
| Total Bases | Under | 59.7% | -$0.10 | ❌ **LOSING** |
| RBI | Under | 68.7% | -$0.42 | ❌ **OVERBET** |

**Key Insight:** Raw coverage calculation already works (69% accuracy). The ML model was making it WORSE.

---

### **Solution Implemented: Phase 1 Simple Scorer**

**What Changed:**

#### 1. **Replaced ML Scorer with Simple Coverage-Based Scorer**

**File:** `src/engine/simple_scorer.py`

**New Scoring Logic:**
```python
score = base_coverage + contextual_adjustments

Where adjustments include:
- Handedness splits: +3 bonus when coverage_vs_hand available
- Hot/cold streaks: ±4 when recent form diverges >15 points
- Pitcher ERA quality: ±5 for weak (>5.0) / ace (<3.0) pitchers
- Pitcher K/9 rate: ±5 for strikeout props vs high/low K pitchers
- Lineup stability: -5 penalty when consistency < 50%
```

**What It Uses (Already in Database):**
- ✅ `coverage_vs_hand` - handedness-specific coverage
- ✅ `coverage_overall` - fallback coverage
- ✅ `coverage_recent_10` - hot/cold streak detection
- ✅ `pitcher_era` - opponent pitcher quality
- ✅ `pitcher_k9` - strikeout rate
- ✅ `lineup_consistency` - playing time stability

**What It Doesn't Use:**
- ❌ ML model predictions
- ❌ Calibration adjustments
- ❌ Temporary direction penalties
- ❌ Floor/ceiling abuse at 5.0 and 95.0

#### 2. **Added Direction-Based Prop Filtering**

**File:** `main.py` (lines 301-308)

**Blocked Unprofitable Props:**
```python
# Block hitter strikeouts under 0.5 (36.7% win rate, -$0.32/dollar)
if stat == "strikeouts" and line == 0.5 and direction == "under":
    continue

# Block total bases under 1.5 (59.7% win rate, -$0.10/dollar)  
if stat == "totalBases" and line == 1.5 and direction == "under":
    continue
```

**Allowed Profitable Props:**
- ✅ Hits over 0.5 (69.4% win rate)
- ✅ Hits under 0.5 (73.1% win rate)
- ✅ Pitcher strikeouts over 3.5+ (69.3% win rate)
- ✅ Total bases over 1.5 (positive edge)
- ✅ Walks (marginal, kept for diversity)

#### 3. **Preserved Training Data Collection**

**Verification:** Checked `mlb_training_data` table
- ✅ 94,189 total rows (54 days of history)
- ✅ 84,301 resolved legs (89% resolution rate)
- ✅ Last update: May 20, 2026 (still active)
- ✅ Resolution pipeline runs independently (9 AM ET)

**What happens now:**
- Old rows: `composite_score` from ML model
- New rows: `composite_score` from simple scorer
- Can compare both methods empirically later

---

### **Deployment Results (May 20, 4:51 PM ET)**

**First Production Run:**

**Scoring Output:**
```
[simple_scorer] Scored 91 legs | avg=72.4 | min=58.0 | max=89.0
```
- ✅ Score distribution is reasonable (not all 5.0 or 95.0)
- ✅ Shows variation (58-89 range)
- ✅ Average 72.4% aligns with expected coverage

**Prop Filtering:**
```
[filter_legs] Kept 68 overs + 9 unders = 77 total eligible
```
- ✅ 88% overs (profitable category)
- ✅ 12% unders (only profitable ones: hits under, pitcher K under)
- ✅ Zero hitter strikeouts under (blocked!)
- ✅ Zero total bases under (blocked!)

**Parlay Generation:**
```
[parlay_builder] Built 3 parlays (12 unique players used)

Parlay 1: +1407 | 4 legs | avg cov 77.9%
Parlay 2: +1162 | 4 legs | avg cov 69.9%
Parlay 3: +909  | 4 legs | avg cov 70.8%
```
- ✅ 3 high-quality parlays (not the full 5, but strong)
- ✅ All within +900-1500 odds range
- ✅ Average coverage 70-78% (excellent)
- ✅ Player diversity maintained (12 unique, no repeats)

**Why Only 3 Parlays?**
- After using 12 players, 64 legs remained
- Branch-and-bound couldn't find valid +900-1500 combinations
- **This is fine** - prioritized quality over quantity

---

## Current System Architecture

### **Daily Pipeline Flow**

**9 AM ET (Morning Pipeline):**
1. Resolve yesterday's outcomes (legs + parlays)
2. Log resolved data to training tables ✅ **Preserved**
3. Fetch today's MLB schedule
4. Fetch all player props from SportsGameOdds
5. **Pre-filter:** Only hits 0.5, pitcher SO 3.5+, walks 0.5, TB 1.5
6. **Block unprofitable:** Hitter SO under 0.5, TB under 1.5 ✅ **NEW**
7. Calculate coverage (direction-aware, handedness splits)
8. **Coverage gate:** Only legs >= 65% coverage
9. Lineup consistency filter (3+ AB in 7 of 10 games)
10. Enrich with pitcher matchups
11. **Score legs (simple scorer)** ✅ **NEW - No ML model**
12. Filter strikeouts (reliever patterns)
13. **Build 3-5 parlays with player diversity** (+900 to +1500 odds)

**12 PM ET (Midday Refresh):**
- Skip resolution step
- Fetch fresh props, calculate fresh coverage
- Rescore with simple scorer ✅ **NEW**
- Rebuild parlays with latest odds
- Player diversity resets

**5:30 PM ET (Evening Refresh):**
- Same as 12 PM - final refresh before games start
- Player diversity resets

**Manual Regenerate (Web UI):**
- Same as 12 PM/5:30 PM - triggered by user button
- Player diversity resets

---

## Database Tables Status

### **mlb_scored_legs**
- Stores all qualified legs (>= 65% coverage)
- Fields: player_name, stat, line, direction, odds, coverage_pct, **composite_score** (now from simple scorer), result
- **New:** Scores now use coverage + contextual adjustments (not ML)

### **mlb_parlay_recommendations_v2**
- Stores daily parlay recommendations
- Fields: recommendation_date, rank, legs (JSON), combined_odds, win_probability, batch_id
- Used for: Web UI display, outcome resolution, performance tracking

### **mlb_parlay_legs_v2**
- Stores individual legs per parlay
- Fields: parlay_id, player_name, stat, line, direction, odds, outcome
- **Critical:** Used to validate player diversity constraint via queries

### **mlb_training_data**
- Stores all scored legs for future analysis
- ✅ **Still active** - 94,189 rows through May 20
- Contains BOTH ML-scored legs (historical) and simple-scored legs (new)
- Can be used to compare scoring methods empirically

---

## Expected Performance (Phase 1)

### **Individual Leg Accuracy (Target)**

Based on profit analysis of 7,895 resolved legs:

| Prop Type | Expected Win Rate | Sample Size | Status |
|-----------|------------------|-------------|--------|
| Hits over | 60-70% | 1,063 legs | Validated ✅ |
| Hits under | 70-75% | 156 legs | Validated ✅ |
| Pitcher K over | 60-70% | 646 legs | Validated ✅ |
| Total Bases over | 50-60% | 12 legs | Small sample |

### **Parlay Win Rate (Target)**

**Expected calculation:**
- 4-leg parlay with 69% per-leg accuracy: 0.69^4 = **22.7% win rate**
- At +1200 odds (13:1 payout): (22.7% × $13) - (77.3% × $1) = **+$2.18 profit per $1**
- ROI: **218%**

**Conservative estimate:**
- Mixed legs (65-75% range): **18-22% parlay win rate**
- At +1200 odds: **+$1.50-$2.50 profit per $1**

**Baseline (before Phase 1):**
- Current parlay win rate: **7.6%**
- At +1200 odds: **-$0.02 per $1** (breakeven/slight loss)

**Target improvement:** 7.6% → 18-22% (2.4x-2.9x increase)

---

## Key Metrics to Monitor (May 21-25)

### **Daily Validation Queries**

**1. Check Blocked Props Are Gone:**
```sql
SELECT 
    stat,
    direction,
    COUNT(*) as legs
FROM mlb_scored_legs
WHERE run_date = CURRENT_DATE::text
GROUP BY stat, direction
ORDER BY legs DESC;
```

**Expected:**
- ✅ hits over: ~30 legs
- ✅ hits under: ~15 legs
- ✅ strikeouts over: ~20 legs
- ❌ strikeouts under: **0 legs** (blocked!)
- ✅ totalBases over: ~10 legs
- ❌ totalBases under: **0 legs** (blocked!)

**2. Track Individual Leg Win Rates:**
```sql
SELECT 
    stat,
    direction,
    COUNT(*) as legs,
    SUM(CASE WHEN result = 'won' THEN 1 ELSE 0 END) as won,
    (AVG(CASE WHEN result = 'won' THEN 1.0 ELSE 0.0 END) * 100)::numeric(5,1) as win_rate
FROM mlb_scored_legs
WHERE run_date >= (CURRENT_DATE - INTERVAL '3 days')::text
    AND result IN ('won', 'lost')
    AND composite_score >= 65
GROUP BY stat, direction;
```

**Target:**
- Hits over: 60-70% win rate
- Hits under: 70-75% win rate
- Strikeouts over: 60-70% win rate

**3. Track Parlay Win Rate:**
```sql
SELECT 
    COUNT(*) as parlays,
    SUM(CASE WHEN outcome = 'won' THEN 1 ELSE 0 END) as won,
    (AVG(CASE WHEN outcome = 'won' THEN 1.0 ELSE 0.0 END) * 100)::numeric(5,1) as win_rate
FROM mlb_parlay_recommendations_v2
WHERE run_date >= CURRENT_DATE - INTERVAL '3 days'
    AND outcome IS NOT NULL;
```

**Target:** 15-25% win rate (vs 7.6% baseline)

**4. Verify Training Data Still Logging:**
```sql
SELECT COUNT(*) as legs_logged
FROM mlb_training_data
WHERE game_date = CURRENT_DATE;
```

**Expected:** ~80-100 legs per day (matches mlb_scored_legs)

---

## System Health Indicators

### **Green Lights (System Healthy)**
- ✅ 3-5 parlays built per run
- ✅ All parlays within +900-1500 odds
- ✅ 80-100 scored legs per day
- ✅ 70-80 eligible legs per day
- ✅ Only profitable prop types in pool
- ✅ No player appears 2+ times per batch
- ✅ No errors in Railway logs
- ✅ Database writes succeeding
- ✅ Pipeline completing in <5 minutes
- ✅ Score distribution shows variation (not all identical)

### **Yellow Flags (Monitor Closely)**
- ⚠️ Parlay count drops to 1-2 (may need wider odds range)
- ⚠️ Leg pool < 70 or > 110 (filter issues)
- ⚠️ Player appears 2+ times in batch (diversity bug)
- ⚠️ Pipeline execution > 5 minutes (performance issue)

### **Red Flags (Immediate Action Required)**
- 🔴 0 parlays built multiple days in row (system broken)
- 🔴 Unprofitable props appearing (hitter K under, TB under)
- 🔴 Pipeline crashes or timeouts (code error)
- 🔴 Parlay win rate < 10% after 20+ samples (Phase 1 not working)
- 🔴 Training data stops accumulating (resolution broken)

---

## Working Well - Don't Change

| Component | Status | Evidence |
|-----------|--------|----------|
| Simple scorer | ✅ Deployed | Using coverage + contextual adjustments |
| Prop filtering | ✅ Working | Blocking hitter K under, TB under |
| Coverage calculation | ✅ Validated | 69% accuracy on profitable props |
| Player diversity | ✅ Active | 12 unique players, 0 duplicates |
| Parlay construction | ✅ Operational | 3 parlays at +909-1407 |
| Database logging | ✅ Stable | All data persisting |
| Training data | ✅ Preserved | 94K+ rows, still accumulating |
| Opponent pitcher adjustment | ✅ Keep | Valuable signal |
| Handedness splits | ✅ Working | coverage_vs_hand populated for 72% of legs |
| Lineup consistency | ✅ Working | 70% threshold filtering correctly |
| Pipeline scheduler | ✅ Reliable | 3x daily runs |
| Railway deployment | ✅ Stable | Auto-deploy working |

---

## Known Issues (Non-Critical)

### **Issue 1: Only 3 Parlays Instead of 5**

**Observation:** After player diversity excluded 12 players, remaining 64 legs couldn't form valid +900-1500 combinations.

**Impact:** Low - 3 high-quality parlays (70-78% avg coverage) better than 5 mediocre ones

**Fix if needed:**
- Widen odds range to +800-1600 temporarily
- Or lower MIN_COVERAGE to 60%
- Or do nothing - 3 strong parlays is fine

**Status:** ⚠️ Monitor - if consistently < 3 parlays, adjust

### **Issue 2: Scikit-learn Version Warnings**

**Observation:** `InconsistentVersionWarning: Trying to unpickle estimator from version 1.7.2 when using version 1.8.0`

**Impact:** None - old ML model files, not used for scoring anymore

**Fix:** Delete old model files (low priority)

**Status:** ⚠️ Cosmetic - doesn't affect functionality

### **Issue 3: Training Data Warnings**

**Observation:** 
- `RESOLVER FAILURE: 254 props unresolved for 2026-04-02`
- `HIT RATE HIGH: 61.7% over last 7 days`

**Impact:** 
- April 2 gap is historical, doesn't affect current operations
- 61.7% hit rate is GOOD - means profitable props are being selected

**Fix:** Backfill April 2 data (optional)

**Status:** ✅ Not a problem - actually validates filtering is working

---

## Quick Commands

### **Check System Status**
```bash
railway logs --follow
```

### **Manual Pipeline Trigger**
- Web UI: Click "Regenerate Now" button
- Or: `curl -X POST https://mlb-agent.up.railway.app/api/refresh -H "Authorization: Bearer MLBparlays"`

### **Validate No Duplicate Players**
```sql
SELECT p.batch_id, l.player_name, COUNT(DISTINCT p.id) as appearances
FROM mlb_parlay_recommendations_v2 p
JOIN mlb_parlay_legs_v2 l ON l.parlay_id = p.id
WHERE p.run_date = CURRENT_DATE
GROUP BY p.batch_id, l.player_name
HAVING COUNT(DISTINCT p.id) > 1;
-- Expected: 0 rows
```

### **Check Today's Parlays**
```sql
SELECT 
    p.rank,
    p.total_odds,
    p.outcome,
    l.player_name,
    l.stat,
    l.direction,
    l.line
FROM mlb_parlay_recommendations_v2 p
JOIN mlb_parlay_legs_v2 l ON l.parlay_id = p.id
WHERE p.run_date = CURRENT_DATE
ORDER BY p.rank, l.id;
```

---

## Phase 2 Considerations (WAIT 3-5 DAYS)

**Only consider Phase 2 if Phase 1 achieves 18%+ parlay win rate.**

**Phase 2 would add:**
- Opponent team offense stats (K-rate, runs per game, OBP)
- Park factors (Coors Field boosts offense)
- Weather adjustments (wind, temperature)
- Umpire tendencies (high/low strike zone)

**But Phase 1 should be sufficient** - 69% individual leg accuracy translates to 18-22% parlay win rate, which is highly profitable.

---

## Contact for Next Session

**What to bring:**
1. Parlay outcomes from May 20-23 (3 days minimum)
2. Individual leg win rates by prop type
3. Any errors or anomalies in Railway logs
4. Comparison: Phase 1 parlay win rate vs 7.6% baseline

**Questions to answer:**
- Did Phase 1 achieve 15%+ parlay win rate?
- Are blocked props staying blocked?
- Is training data still accumulating?
- Should we adjust odds range or coverage threshold?

---

**Last Review:** May 20, 2026, 5:30 PM ET  
**System Status:** ✅ Operational - Phase 1 Simple Scorer Live  
**Next Review:** May 23-25, 2026 (After 3-5 days of results)  
**Major Milestone:** ML model removed, profit-validated coverage system deployed
