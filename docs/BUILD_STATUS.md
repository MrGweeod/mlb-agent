# MLB Parlay Agent — Build Status
**Last Updated:** May 18, 2026 (End of Day - System Operational, Generating Parlays)

## Overall System Status: ✅ OPERATIONAL
┌────────────────────────────────────────────────────────────┐
│              SYSTEM HEALTH DASHBOARD                       │
├────────────────────────────────────────────────────────────┤
│ Prop Filtering:        ✅ OPERATIONAL (0.5 lines only)     │
│ Coverage Calculation:  ✅ VALIDATED (direction-aware)      │
│ Parlay Building:       ✅ OPERATIONAL (4-5 per run)        │
│ Database Logging:      ✅ STABLE (all data persisting)     │
│ Web UI:                ✅ FUNCTIONAL (all tabs working)    │
│ Deployment:            ✅ LIVE (Railway auto-deploy)       │
│ Next Validation:       📊 May 19-23 (monitor hit rates)    │
└────────────────────────────────────────────────────────────┘

---

## Recent Deployments (May 18, 2026)

### 🎉 **Critical Fixes Deployed - System Operational**

#### **1. Best Odds Field Fix**
**Commit:** `f8a2c1d`

**Problem:** Redundant "bridge" mapping was overwriting correctly-set `best_odds` with `None`.

**Solution:** Removed lines 847-851 that were clobbering the field.

**Impact:** 
- ✅ 480 legs now have valid `best_odds` values
- ✅ Parlay builder can filter and rank legs correctly
- ✅ Parlays building successfully

**Status:** ✅ Deployed and working

---

#### **2. Surgical Prop Type Filters**
**Commit:** `3d9b2f5`

**Changes:**
- **Fix 1:** Hits filtered to ONLY 0.5 line
- **Fix 2:** Hitter strikeouts filtered to ONLY 0.5 line
- **Fix 3:** Removed RBI, Total Bases, Home Runs props
- **Fix 4:** Unified coverage threshold to 65%

**Solution:** Added filters in `_find_qualifying_legs()` before leg creation.

**Impact:**
- ✅ Leg pool reduced from 480+ to ~300 (cleaner)
- ✅ Only desired bet types: hits 0.5, SO (0.5/3.5+), walks 0.5
- ✅ Better odds distribution enabling parlay construction
- ✅ No more heavily juiced unders polluting pool

**Status:** ✅ Deployed and working

---

#### **3. Claude Analysis Removal**
**Commit:** `9c4e7f2`

**Changes:**
- Removed `analyze_parlays()` call from main pipeline
- Removed `/api/analyze` and `/api/analyze-recommendation` endpoints
- Removed "Analyze Parlay" buttons from web UI
- Removed Anthropic API client initialization

**Impact:**
- ✅ Saves ~$0.01-0.02 per pipeline run
- ✅ Pipeline 5-10 seconds faster
- ✅ Cleaner logs (no lengthy analysis output)
- ✅ Simpler UI (no buttons for disconnected analysis)

**Status:** ✅ Deployed and working

---

## Component Status

### **1. Prop Filtering** ✅ OPERATIONAL

**Current Rules:**
- ✅ Hits: ONLY 0.5 line (no 1.5, 2.5, etc.)
- ✅ Hitter Strikeouts: ONLY 0.5 line
- ✅ Pitcher Strikeouts: Minimum 3.5 line (correct for starters)
- ✅ Walks: 0.5 line (all lines allowed)
- ✅ Blocked Stats: RBI, Total Bases, Home Runs

**Test Results (May 18, 3:08 PM):**
```
Props fetched: ~600 from SGO
After filtering: ~300 qualifying legs
Stat breakdown:
  - Hits 0.5: ~140 legs
  - Strikeouts: ~70 legs (0.5 hitters + 3.5+ pitchers)
  - Walks 0.5: ~90 legs
```

**Status:** ✅ Working correctly - no unwanted props in pool

---

### **2. Coverage Calculation** ✅ VALIDATED

**Implementation:**
- Direction-aware: "How often does player go OVER/UNDER this line?"
- Handedness splits: Batter vs RHP/LHP tracked separately
- Minimum games: 20 games played, 10 games vs handedness for split

**Validation (May 14):**
- Trea Turner hits_under: 81% → 35.7% ✅ (corrected)
- Direction symmetry: hits_over + hits_under ≈ 100% ✅
- 3,727 legs with corrected coverage ✅

**Current Threshold:** 65% minimum (unified across pipeline)

**Status:** ✅ Mathematically correct, validated with real data

---

### **3. Parlay Building** ✅ OPERATIONAL

**Latest Run (May 18, 3:08 PM ET):**
```
[8/8] Building hybrid parlays (14 games → Tier 1)...
  Built 5 parlay(s)
  
  Parlay 1: +1398 | 4 legs | avg cov 77.1%
  Parlay 2: +1219 | 4 legs | avg cov 77.4%
  Parlay 3: +1116 | 4 legs | avg cov 72.2%
  Parlay 4: +1258 | 4 legs | avg cov 75.2%
  Parlay 5: +1150 | 4 legs | avg cov 73.1%
```

**Configuration:**
- Legs per parlay: 4 (fixed)
- Odds range: +1000 to +1400
- Coverage minimum: 65%
- Max legs per game: 2 (correlation limit)

**Pool Quality:**
- Eligible legs: 294 (after 65% filter)
- Top 50 avg score: 88.3%
- Quality drop: 4.2% (healthy)

**Status:** ✅ Building parlays successfully within target range

---

### **4. Database Logging** ✅ STABLE

**Tables Status:**

**mlb_scored_legs:**
- ✅ All qualified legs (>= 65% coverage) persisting
- ✅ Fields populated: coverage_pct, composite_score, best_odds, result
- ✅ No NULL issues with best_odds field

**mlb_parlay_recommendations_v2:**
- ✅ All 5 parlays saved successfully
- ✅ Hydrated leg details included
- ✅ Rank, win_probability, edge_pct computed

**mlb_training_data:**
- ✅ Prospective legs logged (outcome=NULL until resolution)
- ✅ Resolution working (9 AM pipeline)

**Latest Counts (May 18):**
```sql
SELECT COUNT(*) FROM mlb_scored_legs WHERE run_date = '2026-05-18';
-- Result: 300+ legs

SELECT COUNT(*) FROM mlb_parlay_recommendations_v2 WHERE run_date = '2026-05-18';
-- Result: 5 parlays
```

**Status:** ✅ All data persisting correctly

---

### **5. Web UI** ✅ FUNCTIONAL

**Tabs Working:**
- ✅ Legs: Displays all scored legs, filterable, selectable
- ✅ Dashboard: Shows overall metrics, trends (placeholder)
- ✅ Training: Data health metrics (future feature)
- ✅ Picks: Displays parlay recommendations with leg details

**Removed Features:**
- ❌ "Analyze Parlay" button (removed May 18 - cost optimization)
- ❌ Claude analysis display (removed - disconnected from scoring)

**Key Features:**
- ✅ Regenerate Now button (manual pipeline trigger)
- ✅ Real-time leg selection and odds calculation
- ✅ Coverage percentage display
- ✅ Trend indicators (HOT/COLD/NEUTRAL)

**Status:** ✅ All core functionality working

---

### **6. Pipeline Execution** ✅ STABLE

**Schedule:**
| Time | Pipeline | Resolution | Duration | Status |
|------|----------|------------|----------|--------|
| 9 AM ET | Morning | ✅ Yes | ~3 min | ✅ Working |
| 12 PM ET | Midday | ❌ No | ~2 min | ✅ Working |
| 5:30 PM ET | Evening | ❌ No | ~2 min | ✅ Working |
| Manual | Regenerate | ❌ No | ~2 min | ✅ Working |

**Performance (May 18):**
- Morning run: 3 min 15 sec (includes resolution)
- Midday/evening: ~2 min (skip resolution)
- No errors, no timeouts
- Railway deployment stable

**Status:** ✅ All scheduled runs executing successfully

---

### **7. Deployment** ✅ LIVE

**Platform:** Railway
- Auto-deploy on push to `master`
- Scheduler: APScheduler with timezone handling
- Health checks: Container starts successfully
- Logs: Available via Railway dashboard

**Latest Deploy:**
- Commit: `9c4e7f2` (Claude analysis removal)
- Date: May 18, 2026, ~3:00 PM ET
- Status: ✅ Deployed successfully
- Startup: Clean, no errors

**Environment Variables:**
```
ANTHROPIC_API_KEY     → [REMOVED - no longer needed]
DATABASE_URL          → Supabase PostgreSQL
SPORTSGAMEODDS_API_KEY → Props/odds data
ODDS_API_KEY          → Fallback (unused currently)
DISCORD_BOT_TOKEN     → [Not implemented yet]
```

**Status:** ✅ Live and stable

---

## Expected Performance (Next 5 Days)

### **Leg-Level Metrics**

| Metric | Baseline | Expected After Fixes | Target Date |
|--------|----------|---------------------|-------------|
| Qualified legs per day | 480+ | 250-350 | May 19 (immediate) |
| Coverage accuracy | 52% | 65-70% | May 23 (5 days) |
| hits_over hit rate | 63.8% | 63-68% | May 23 |
| hits_under hit rate | 36.7% | 35-40% | May 23 |

### **Parlay-Level Metrics**

| Metric | Before | Expected After | Target Date |
|--------|--------|----------------|-------------|
| Parlays built per run | 0 | 4-5 | May 19 (immediate) |
| Parlay odds range | N/A | +1000-1400 | May 19 (immediate) |
| 4-leg parlay win rate | 7% | 15-25% | May 23 (5 days) |
| Core leg overlap | N/A | Monitor | May 23 |

---

## Priority Matrix (Next 5 Days)

| Priority | Item | Effort | Expected Impact |
|----------|------|--------|-----------------|
| 📊 **MONITORING** | Track hit rates daily | 15 min/day | Validate system accuracy |
| 📊 **MONITORING** | Track core leg performance | 15 min/day | Assess overlap strategy |
| 📊 **MONITORING** | Track parlay win rate | 15 min/day | Validate target metrics |
| LOW | Document hit rate findings | 1 hour | Inform future optimizations |

---

## Known Issues (Non-Critical)

### **Issue 1: High Core Leg Overlap**
- **Observation:** Same 3 legs appear in all 5 parlays (Ureña, Fermin, McClanahan)
- **Impact:** If core 3 hit → win all 5; if any miss → lose all 5
- **Status:** ⚠️ Monitor over next 5 days
- **Decision Point:** If core legs hit >70%, keep strategy; if <60%, add diversity constraint

### **Issue 2: Negative EV Legs**
- **Observation:** Some legs have high coverage but negative EV (-9.7% for Ureña)
- **Impact:** System optimizes for hit probability, not value
- **Status:** ⚠️ Working as designed per requirements
- **Decision Point:** If win rate is good, EV is acceptable; if not, reconsider weighting

### **Issue 3: Same-Game Correlation**
- **Observation:** Some parlays have 2 legs from same game (opposing pitchers)
- **Impact:** Correlated outcomes if game is high/low scoring
- **Status:** ⚠️ Monitor correlation impact
- **Decision Point:** Quantify actual impact before adding penalties

---

## Working Well - Don't Change

| Component | Status | Evidence |
|-----------|--------|----------|
| Prop filtering | ✅ Excellent | Only 0.5 hits/SO, clean pool |
| Coverage calculation | ✅ Validated | Direction-aware, mathematically correct |
| Simple scorer | ✅ Working | Coverage + pitcher adjustments transparent |
| Parlay construction | ✅ Operational | 4-5 parlays at +1000-1400 |
| Database logging | ✅ Stable | All data persisting correctly |
| Opponent pitcher adjustment | ✅ Keep | Valuable signal, not causing issues |
| Strikeout filters | ✅ Correct | Hitter 0.5, pitcher 3.5+ as designed |
| Lineup consistency | ✅ Working | 70% threshold filtering correctly |
| Pipeline scheduler | ✅ Reliable | 3x daily runs executing |
| Railway deployment | ✅ Stable | Auto-deploy functioning |

---

## Deployment Checklist (For Future Deploys)

### **Before Deploy:**
- [ ] All tests pass locally
- [ ] Code reviewed (or justified if solo)
- [ ] Environment variables verified in Railway
- [ ] Database schema changes scripted (if any)

### **During Deploy:**
- [ ] Push to `master` branch
- [ ] Wait for Railway "Deployment successful" message
- [ ] Check Railway logs for startup errors
- [ ] Verify scheduler initialized

### **After Deploy:**
- [ ] Watch next scheduled run (9 AM, 12 PM, or 5:30 PM)
- [ ] Verify parlays built and saved to database
- [ ] Check web UI loads and displays data
- [ ] Monitor for errors in Railway logs

---

## Quick Validation Queries

### **Check Today's Parlay Count:**
```sql
SELECT COUNT(*) as parlay_count
FROM mlb_parlay_recommendations_v2
WHERE run_date = CURRENT_DATE;
-- Expected: 5 (or 0 if before 9 AM)
```

### **Check Today's Leg Count:**
```sql
SELECT COUNT(*) as leg_count
FROM mlb_scored_legs
WHERE run_date = CURRENT_DATE::text;
-- Expected: 250-350
```

### **Check Prop Type Distribution:**
```sql
SELECT stat, direction, COUNT(*) as count
FROM mlb_scored_legs
WHERE run_date = CURRENT_DATE::text
GROUP BY stat, direction
ORDER BY stat, direction;
-- Expected: Only hits 0.5, SO (0.5/3.5+), walks 0.5
```

### **Check Core Leg Appearances:**
```sql
WITH leg_counts AS (
  SELECT 
    l->>'player_name' as player,
    COUNT(*) as appearances
  FROM mlb_parlay_recommendations_v2,
       jsonb_array_elements(legs) as l
  WHERE run_date = CURRENT_DATE
  GROUP BY l->>'player_name'
)
SELECT * FROM leg_counts
WHERE appearances >= 4
ORDER BY appearances DESC;
-- Expected: 3-4 players appearing in 4-5 parlays
```

---

## Health Indicators

### **Green Lights (System Healthy):**
- ✅ 4-5 parlays built per run
- ✅ All parlays within +1000-1400 odds
- ✅ 250-350 legs scored per day
- ✅ Only hits 0.5, SO (0.5/3.5+), walks 0.5 in pool
- ✅ No errors in Railway logs
- ✅ Database writes succeeding
- ✅ Pipeline completing in <5 minutes

### **Yellow Flags (Monitor Closely):**
- ⚠️ Parlay count drops to 0-2 (insufficient leg diversity)
- ⚠️ Leg pool < 200 or > 400 (filter too strict/loose)
- ⚠️ Core 3 legs hit rate < 60% (coverage overestimation)
- ⚠️ Pipeline execution > 5 minutes (performance degradation)

### **Red Flags (Immediate Action Required):**
- 🔴 0 parlays built multiple days in row (system broken)
- 🔴 Unwanted prop types in pool (filters not working)
- 🔴 best_odds NULL values in database (field mapping broken)
- 🔴 Pipeline crashes or timeouts (code error)
- 🔴 Parlay win rate < 5% after 20+ samples (system inaccurate)

---

**Last Review:** May 18, 2026, 3:15 PM ET  
**Next Review:** May 23, 2026 (After 5 days of monitoring)  
**System Status:** ✅ Operational - All Critical Components Working  
**Major Milestone:** System generating parlays successfully after surgical fixes
