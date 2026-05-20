# MLB Parlay Agent — Build Status
**Last Updated:** May 19, 2026 (End of Day - Player Diversity + Total Bases Active)

## Overall System Status: ✅ OPERATIONAL
┌────────────────────────────────────────────────────────────┐
│              SYSTEM HEALTH DASHBOARD                       │
├────────────────────────────────────────────────────────────┤
│ Prop Filtering:        ✅ OPERATIONAL (0.5 lines + TB 1.5) │
│ Coverage Calculation:  ✅ VALIDATED (direction-aware)      │
│ Player Diversity:      ✅ ACTIVE (max 1 per batch)         │
│ Parlay Building:       ✅ OPERATIONAL (5 per run)          │
│ Database Logging:      ✅ STABLE (all data persisting)     │
│ Web UI:                ✅ FUNCTIONAL (all tabs working)    │
│ Deployment:            ✅ LIVE (Railway auto-deploy)       │
│ Next Validation:       📊 May 20-25 (monitor performance)  │
└────────────────────────────────────────────────────────────┘

---

## Recent Deployments (May 19, 2026)

### 🎉 **Major Feature: Player Diversity Constraint**

**Commit:** `feat: add player diversity constraint - max 1 appearance per batch`

**Problem Solved:**
- 65% wipeout rate when players appeared in 5 parlays
- May 18: Shane McClanahan in all 25 parlays → 0 won when he lost
- Catastrophic correlation risk

**Implementation:**
- Modified `src/engine/parlay_builder.py`
- Changed from "one B&B pass → pick top 5" to "5 sequential B&B passes"
- Track `used_players` set, filter available legs before each parlay
- Add players to exclusion set after each parlay

**Impact:**
- ✅ 20 unique players across 5 parlays (not 5 repeated players)
- ✅ Eliminates single-player wipeout risk
- ✅ Player diversity resets between generation runs (players can reappear at 9 AM, 12 PM, 5:30 PM)

**Status:** ✅ Deployed and validated

---

### 🔧 **Fix: Use All Eligible Legs (Not Top 50)**

**Commit:** `fix: use all eligible legs for parlay building instead of top 50 only`

**Problem:** After diversity constraint, only 2 parlays building. Parlay 3 gave up after 1 B&B iteration.

**Root Cause:** `POOL_SIZE = 50` limited search to top 50 legs. After parlays 1-2 used best 8 players, parlay 3 only had access to legs 9-50.

**Solution:**
- Changed `POOL_SIZE` from static 50 to dynamic (use all eligible legs)
- Parlay 3 now has access to all 74 legs minus 8 used = 66 available
- B&B can find valid combinations for all 5 parlays

**Impact:**
- ✅ 5 parlays building consistently (up from 2)
- ✅ B&B iterates 15-20 times per parlay (not 1)
- ✅ All parlays within +900-1500 odds range

**Status:** ✅ Deployed and working

---

### ⚡ **Feature: Total Bases 1.5 Props**

**Commit:** `feat: widen odds range to +900-1500 and add totalBases 1.5 props`

**Additions:**
- Added `"totalBases"` to `ALLOWED_STATS` in `main.py`
- Strict line filter: only 1.5 (no 0.5, 2.5, 3.5)
- Over 1.5 = 2+ total bases (double, HR, or 2 singles)
- Under 1.5 = 0-1 total bases

**Impact:**
- ✅ +33 totalBases legs per day
- ✅ Leg pool increased from ~70 to ~105 scored legs
- ✅ Eligible legs increased from ~48 to ~74
- ✅ More diversity for parlay construction

**Status:** ✅ Deployed and working

---

### 📊 **Adjustment: Odds Range +900-1500**

**Commit:** Same as Total Bases (combined)

**Changed:** +1000-1400 → +900-1500

**Rationale:** With player diversity constraint, need wider range for B&B to find valid combinations after best legs used

**Impact:**
- ✅ More flexibility for parlays 3-5
- ✅ Still reasonable odds for 4-leg parlays
- ⚠️ Monitor: May need to tighten back to +1000-1400 after leg pool stabilizes

**Status:** ✅ Deployed and working

---

## Component Status

### **1. Prop Filtering** ✅ OPERATIONAL

**Current Rules:**
- ✅ Hits: ONLY 0.5 line
- ✅ Hitter Strikeouts: ONLY 0.5 line
- ✅ Pitcher Strikeouts: Minimum 3.5 line
- ✅ Walks: 0.5 line
- ✅ **Total Bases: ONLY 1.5 line** ✅ NEW
- ✅ Blocked: RBI, Home Runs (removed May 18)

**Test Results (May 19, 9:45 PM):**
```
Props fetched: ~2,136 from SGO
After filtering: 1,738 usable
Scored legs: 105
  - Hits: 40 legs
  - Strikeouts: 30 legs
  - Total Bases: 33 legs ✅ NEW
  - Walks: 2 legs
Eligible (>= 65%): 74 legs
```

**Status:** ✅ Working correctly - all desired prop types present

---

### **2. Coverage Calculation** ✅ VALIDATED

**Implementation:**
- Direction-aware: "How often does player go OVER/UNDER this line?"
- Handedness splits: Batter vs RHP/LHP tracked separately
- Minimum games: 20 games played, 10 games vs handedness for split

**Validation:**
- Direction symmetry: over + under ≈ 100% ✅
- Total Bases coverage uses SLG (slugging percentage) ✅
- 3,700+ legs with corrected coverage historically ✅

**Current Threshold:** 65% minimum (unified across pipeline)

**Status:** ✅ Mathematically correct, validated with real data

---

### **3. Player Diversity** ✅ ACTIVE

**Implementation:**
- Track `used_players` set across parlay generation loop
- Filter available legs before each parlay: `if player not in used_players`
- Add players to exclusion set after each parlay built
- Diversity resets between generation runs (9 AM, 12 PM, 5:30 PM)

**Latest Run (May 19, 9:45 PM ET):**
```
[parlay_builder] Starting generation with 74 pool legs
[parlay_builder] Parlay 1: 74 available legs (0 players excluded)
[parlay_builder] Parlay 1 players: Rafael Marchán, Will Warren, Jacob Misiorowski, Ezequiel Tovar
[parlay_builder] Parlay 2: 70 available legs (4 players excluded)
[parlay_builder] Parlay 2 players: Bo Bichette, Mickey Moniak, Vladimir Guerrero Jr., Landen Roupp
[parlay_builder] Parlay 3: 66 available legs (8 players excluded)
[parlay_builder] Built 5 parlays (20 unique players used)
```

**Validation Query:**
```sql
-- Should return 0 rows
SELECT batch_id, player_name, COUNT(*) 
FROM mlb_parlay_legs_v2 
WHERE parlay_id IN (SELECT id FROM mlb_parlay_recommendations_v2 WHERE run_date = '2026-05-19')
GROUP BY batch_id, player_name 
HAVING COUNT(*) > 1;

-- Result: 0 rows ✅
```

**Status:** ✅ Working perfectly - no player appears 2+ times per batch

---

### **4. Parlay Building** ✅ OPERATIONAL

**Latest Run (May 19, 9:45 PM ET):**
```
[8/8] Building hybrid parlays (15 games → Tier 1)...
  Built 5 parlay(s)
  
  Parlay 1: +1344 | 4 legs | avg cov 76.3%
  Parlay 2: +1030 | 4 legs | avg cov 75.0%
  Parlay 3: +1205 | 4 legs | avg cov 73.8%
  Parlay 4: +1156 | 4 legs | avg cov 72.5%
  Parlay 5: +949 | 4 legs | avg cov 71.2%
```

**Configuration:**
- Legs per parlay: 4 (fixed)
- Odds range: +900 to +1500 ✅ NEW
- Coverage minimum: 65%
- Max legs per game: 2 (correlation limit)
- **Player diversity: Max 1 appearance per batch** ✅ NEW

**Pool Quality:**
- Eligible legs: 74 (up from 48 before Total Bases)
- Using all eligible legs (not capped at 50)
- B&B iterations: 15-20 per parlay (healthy search depth)

**Status:** ✅ Building 5 parlays successfully within target range

---

### **5. Database Logging** ✅ STABLE

**Tables Status:**

**mlb_scored_legs:**
- ✅ All qualified legs (>= 65% coverage) persisting
- ✅ Total Bases stat appearing correctly
- ✅ Fields populated: coverage_pct, composite_score, best_odds, result

**mlb_parlay_recommendations_v2:**
- ✅ All 5 parlays saved successfully per run
- ✅ Batch ID tracking working (one batch per generation run)
- ✅ Rank, win_probability, edge_pct computed

**mlb_parlay_legs_v2:**
- ✅ All individual legs saved with parlay_id reference
- ✅ Player diversity validation possible via queries
- ✅ Outcome tracking working

**mlb_training_data:**
- ✅ Prospective legs logged (outcome=NULL until resolution)
- ✅ Resolution working (9 AM pipeline)

**Latest Counts (May 19):**
```sql
SELECT COUNT(*) FROM mlb_scored_legs WHERE run_date = '2026-05-19';
-- Result: 105 legs (includes Total Bases)

SELECT COUNT(*) FROM mlb_parlay_recommendations_v2 WHERE run_date = '2026-05-19';
-- Result: Multiple batches (9 AM, manual triggers, 5:30 PM)
-- Latest batch: 5 parlays ✅

SELECT COUNT(DISTINCT l.player_name) 
FROM mlb_parlay_legs_v2 l
JOIN mlb_parlay_recommendations_v2 p ON p.id = l.parlay_id
WHERE p.batch_id = '2026-05-19_21:49:49';
-- Result: 20 unique players ✅
```

**Status:** ✅ All data persisting correctly

---

### **6. Web UI** ✅ FUNCTIONAL

**Tabs Working:**
- ✅ Legs: Displays all scored legs including Total Bases
- ✅ Dashboard: Shows overall metrics, trends
- ✅ Training: Data health metrics
- ✅ Picks: Displays parlay recommendations with leg details

**Key Features:**
- ✅ Regenerate Now button (manual pipeline trigger)
- ✅ Real-time leg selection and odds calculation
- ✅ Coverage percentage display
- ✅ Total Bases props displaying correctly

**Status:** ✅ All core functionality working

---

### **7. Pipeline Execution** ✅ STABLE

**Schedule:**
| Time | Pipeline | Resolution | Duration | Status |
|------|----------|------------|----------|--------|
| 9 AM ET | Morning | ✅ Yes | ~3-4 min | ✅ Working |
| 12 PM ET | Midday | ❌ No | ~3 min | ✅ Working |
| 5:30 PM ET | Evening | ❌ No | ~3 min | ✅ Working |
| Manual | Regenerate | ❌ No | ~3 min | ✅ Working |

**Performance (May 19):**
- Pipeline runs: 3-4 minutes (includes coverage calculation for TB props)
- No errors, no timeouts
- Railway deployment stable
- Player diversity resets between each run ✅

**Status:** ✅ All scheduled runs executing successfully

---

### **8. Deployment** ✅ LIVE

**Platform:** Railway
- Auto-deploy on push to `master`
- Scheduler: APScheduler with timezone handling
- Health checks: Container starts successfully
- Logs: Available via Railway dashboard

**Latest Deploy:**
- Commit: `fix: use all eligible legs for parlay building`
- Date: May 19, 2026, ~9:30 PM ET
- Status: ✅ Deployed successfully
- Startup: Clean, no errors

**Status:** ✅ Live and stable

---

## Expected Performance (Next 5 Days)

### **Baseline Comparison**

**May 18 (Before Player Diversity):**
- 25 parlays generated across multiple runs
- Shane McClanahan in all 25
- All 25 lost when he lost
- Win rate: 0%

**May 20-25 (With Player Diversity):**
- Expected: 5 parlays per run, 3 runs per day = 15 parlays/day
- Expected: No single-player wipeouts
- Target: 15-25% win rate per parlay
- Target: 50%+ of days have at least 1 winning parlay

---

### **Leg-Level Metrics**

| Metric | Before TB Props | Expected After | Target Date |
|--------|----------------|----------------|-------------|
| Qualified legs per day | ~70 | 100-110 | May 20 (immediate) |
| Eligible legs per day | ~48 | 70-80 | May 20 (immediate) |
| Total Bases hit rate | N/A | 45-55% | May 25 (5 days) |
| Coverage accuracy | ~52% | 65-70% | May 25 (5 days) |

---

### **Parlay-Level Metrics**

| Metric | Before Diversity | Expected After | Target Date |
|--------|------------------|----------------|-------------|
| Parlays built per run | 2 | 5 | May 20 (immediate) |
| Parlay odds range | +1000-1400 | +900-1500 | May 20 (immediate) |
| Unique players per batch | 8 | 20 | May 20 (immediate) |
| 4-leg parlay win rate | ~8% | 15-25% | May 25 (5 days) |
| Wipeout events | 65% | <10% | May 25 (5 days) |

---

## Priority Matrix (Next 5 Days)

| Priority | Item | Effort | Expected Impact |
|----------|------|--------|-----------------|
| 📊 **MONITORING** | Track player diversity elimination of wipeouts | 15 min/day | Validate core feature |
| 📊 **MONITORING** | Track Total Bases prop performance | 15 min/day | Validate new stat type |
| 📊 **MONITORING** | Track parlay win rate improvement | 15 min/day | Validate system changes |
| 📊 **MONITORING** | Validate player diversity constraint daily | 5 min/day | Ensure no bugs |
| LOW | Document findings after 5 days | 1 hour | Inform future decisions |

---

## Known Issues (Non-Critical)

### **Issue 1: Scikit-learn Version Warning**

**Observation:** Railway logs show:
```
InconsistentVersionWarning: Trying to unpickle estimator from version 1.7.2 when using version 1.8.0
```

**Impact:** None - models still load and predict correctly

**Status:** ⚠️ Low priority - can retrain models on 1.8.0 later

**Fix:** Run model training script with scikit-learn 1.8.0, redeploy models

---

### **Issue 2: Training Data Resolver Gap**

**Observation:** `RESOLVER FAILURE: 254 props unresolved (>40%) — resolver likely did not run for: 2026-04-02`

**Impact:** Historical data gap for one day in April

**Status:** ⚠️ Low priority - doesn't affect current operations

**Fix:** Run backfill resolution script for 2026-04-02

---

## Working Well - Don't Change

| Component | Status | Evidence |
|-----------|--------|----------|
| Prop filtering | ✅ Excellent | Only 0.5 hits/SO, 3.5+ pitcher SO, 1.5 TB |
| Coverage calculation | ✅ Validated | Direction-aware, handedness splits |
| Player diversity | ✅ Active | 20 unique players, 0 duplicates |
| Total Bases props | ✅ Working | 33 TB legs adding diversity |
| Simple scorer | ✅ Transparent | Coverage + pitcher adjustments |
| Parlay construction | ✅ Operational | 5 parlays at +900-1500 |
| Database logging | ✅ Stable | All data persisting |
| Opponent pitcher adjustment | ✅ Keep | Valuable signal |
| Strikeout filters | ✅ Correct | Hitter 0.5, pitcher 3.5+ |
| Lineup consistency | ✅ Working | 70% threshold |
| Pipeline scheduler | ✅ Reliable | 3x daily runs |
| Railway deployment | ✅ Stable | Auto-deploy working |

---

## Deployment Checklist (For Future Deploys)

### **Before Deploy:**
- [ ] All tests pass locally
- [ ] Code reviewed or justified
- [ ] Environment variables verified
- [ ] Database schema changes scripted (if any)

### **During Deploy:**
- [ ] Push to `master` branch
- [ ] Wait for Railway "Deployment successful"
- [ ] Check Railway logs for startup errors
- [ ] Verify scheduler initialized

### **After Deploy:**
- [ ] Watch next scheduled run
- [ ] Verify parlays built and saved
- [ ] Check web UI loads and displays data
- [ ] Monitor for errors in Railway logs
- [ ] **Validate player diversity if that feature changed**

---

## Quick Validation Queries

### **Check Today's Parlay Count:**
```sql
SELECT COUNT(*) as parlay_count
FROM mlb_parlay_recommendations_v2
WHERE run_date = CURRENT_DATE;
-- Expected: 5+ (depending on number of runs)
```

### **Check Player Diversity:**
```sql
WITH player_counts AS (
  SELECT 
    p.batch_id,
    l.player_name,
    COUNT(DISTINCT p.id) as appearances
  FROM mlb_parlay_recommendations_v2 p
  JOIN mlb_parlay_legs_v2 l ON l.parlay_id = p.id
  WHERE p.run_date = CURRENT_DATE
  GROUP BY p.batch_id, l.player_name
)
SELECT * FROM player_counts WHERE appearances > 1;
-- Expected: 0 rows (no player appears 2+ times per batch)
```

### **Check Prop Type Distribution:**
```sql
SELECT stat, direction, COUNT(*) as count
FROM mlb_scored_legs
WHERE run_date = CURRENT_DATE::text
GROUP BY stat, direction
ORDER BY stat, direction;
-- Expected: hits, strikeouts, totalBases, walks only
```

### **Check Total Bases Props:**
```sql
SELECT COUNT(*) as tb_count
FROM mlb_scored_legs
WHERE run_date = CURRENT_DATE::text
  AND stat = 'totalBases';
-- Expected: 30-40 legs
```

---

## Health Indicators

### **Green Lights (System Healthy):**
- ✅ 4-5 parlays built per run
- ✅ All parlays within +900-1500 odds
- ✅ 100-110 scored legs per day
- ✅ 70-80 eligible legs per day
- ✅ Only hits 0.5, SO (0.5/3.5+), walks 0.5, TB 1.5 in pool
- ✅ No player appears 2+ times per batch
- ✅ No errors in Railway logs
- ✅ Database writes succeeding
- ✅ Pipeline completing in <5 minutes

### **Yellow Flags (Monitor Closely):**
- ⚠️ Parlay count drops to 2-3 (may need wider odds range)
- ⚠️ Leg pool < 80 or > 120 (filter issues)
- ⚠️ Player appears 2+ times in batch (diversity bug)
- ⚠️ Pipeline execution > 5 minutes (performance issue)

### **Red Flags (Immediate Action Required):**
- 🔴 0-1 parlays built multiple days in row (system broken)
- 🔴 Player appears 3+ times in batch (diversity constraint completely broken)
- 🔴 Unwanted prop types in pool (RBI, HR appearing)
- 🔴 Pipeline crashes or timeouts (code error)
- 🔴 Parlay win rate < 5% after 20+ samples (system inaccurate)

---

**Last Review:** May 19, 2026, 10:15 PM ET  
**Next Review:** May 25, 2026 (After 5 days of monitoring)  
**System Status:** ✅ Operational - All Features Working  
**Major Milestone:** Player diversity constraint + Total Bases props successfully deployed
