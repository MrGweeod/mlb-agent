# MLB Parlay Agent — Build Status
**Last Updated:** May 12, 2026 (End of Day - Schema Cleanup + Filter Fixes)

## Overall System Status: ⏳ FILTER FIXES IN PROGRESS

┌──────────────────────────────────────────────────────────┐
│              SYSTEM HEALTH DASHBOARD                     │
├──────────────────────────────────────────────────────────┤
│ Pipeline Runtime:      ⚠️ BLOCKED (filter bugs)          │
│ ML Scoring:            ✅ OPERATIONAL                    │
│ coverage_overall:      ⏳ FIX DEPLOYED (awaiting data)   │
│ V1 Schema:             ✅ DEPRECATED (v2 only)           │
│ V2 Schema:             ✅ OPERATIONAL (185 parlays)      │
│ Database:              ✅ OPERATIONAL                    │
│ Deployment:            ✅ LIVE (Railway)                 │
│ Dashboard:             ✅ OPERATIONAL (v2 only)          │
│ Filter Bugs:           ⏳ BEING FIXED                    │
└──────────────────────────────────────────────────────────┘

---

## Component Status

### **1. Database Schema** ✅ UPGRADED (13 New Columns)

#### **mlb_scored_legs**
**New columns added May 12:**
- `coverage_overall` - Primary coverage signal (fix deployed, data pending)
- `coverage_vs_hand` - Handedness-split coverage
- `coverage_recent_10` - 10-game rolling coverage
- `coverage_recent_5` - 5-game rolling coverage
- `pitcher_id`, `pitcher_name`, `pitcher_team` - Pitcher identification
- `pitcher_era`, `pitcher_k9`, `pitcher_whip` - Pitcher stats (Phase 3)
- `batter_hand` - Batter handedness
- `pitcher_vs_batter_hand_era` - Handedness-split ERA (Phase 3)

**Current data status:**
- game_start_time: 100% populated ✅
- coverage_overall: 0% populated ⏳ (awaiting next run)
- pitcher fields: 0% populated ⏳ (Phase 3 work)

#### **pitcher_profiles**
**Extended May 12:**
- `pitcher_name` - Full name for display
- `vs_rhb_era`, `vs_lhb_era` - Handedness-split ERA
- `vs_rhb_k9`, `vs_lhb_k9` - Handedness-split K rates

**Status:** ✅ Schema complete, awaiting Phase 3 data population

---

### **2. V2 Schema Migration** ✅ COMPLETE

#### **V1 Schema Deprecated**
- `mlb_recommendations` → `mlb_recommendations_deprecated_20260512`
- `mlb_parlay_legs` → `mlb_parlay_legs_deprecated_20260512`
- Safe to drop after: June 11, 2026

#### **Migration Results**
- ✅ 50 v1 parlays migrated to v2 (not 35 as estimated)
- ✅ 0 migration errors
- ✅ Total v2 parlays: 185 (50 migrated + 135 native)

#### **Dashboard Updated**
- ✅ Now queries v2 tables exclusively
- ✅ Removed all v1 UNION queries
- ✅ Cleaner, faster queries

**Status:** ✅ Fully operational

---

### **3. Coverage Persistence** ⏳ FIX DEPLOYED, DATA PENDING

#### **Problem Identified**
- coverage_overall was NULL for 100% of rows (2,014+ legs, 7 days)
- Root cause: db.py INSERT missing coverage_overall in column list
- main.py was ALWAYS setting it in leg dict (not the issue)

#### **Fix Deployed (Commit e683147)**
- ✅ Added coverage_overall to INSERT column list
- ✅ Added all 13 new columns to value tuple
- ✅ Updated ON CONFLICT to backfill NULLs
- ⏳ Awaiting next pipeline run for data verification

#### **Expected Next Run**
```sql
-- Before fix (May 12, 12pm):
coverage_overall: 0/194 populated (0%)

-- After fix (next run):
coverage_overall: 150-200/150-200 populated (100%)
avg_coverage: 45-55
```

**Status:** ✅ Code fixed, ⏳ Data verification pending

---

### **4. Filter System** ⚠️ BROKEN, FIXES IN PROGRESS

#### **Bug 1: game_start_time Filter**
**Problem:**
[regenerate] All 194 legs have game_start_time, skipping fetch
[regenerate] 194 legs → 0 upcoming (filtered 0 started, 194 missing time)
Contradictory - treats valid times as "missing"

**Impact:** All legs filtered out, 0 parlays possible  
**Root Cause:** Datetime parsing error or timezone mismatch  
**Status:** ⏳ Fix in development  
**ETA:** 30-60 minutes  

#### **Bug 2: Lineup Check**
**Problem:**
SCRATCHED: Bobby Witt Jr. not in lineup
SCRATCHED: Salvador Perez not in lineup
... (24/24 players marked scratched)
All eligible players removed (including star starters)

**Impact:** Even if filter 1 fixed, all legs removed  
**Root Cause:** Name mismatch or API returning empty  
**Status:** ⏳ Fix in development  
**ETA:** 30-60 minutes  

---

### **5. Pipeline Runtime** ⚠️ BLOCKED BY FILTERS

#### **Daily Schedule (3 Runs)**
- **9:00 AM ET** - Morning pipeline
- **12:00 PM ET** - Midday pipeline ✅ (ran at 12:39 PM)
- **5:30 PM ET** - Evening pipeline ⏳ (pending)

#### **Last Run (May 12, 12:39 PM ET)**
Props fetched: 1,856 available
Legs loaded: 194
Legs after filters: 0 (bug)
Parlays built: 0 (no legs)

**Status:** ⚠️ Blocked by filter bugs

---

### **6. Web Dashboard** ✅ OPERATIONAL (V2 Only)

#### **Legs Tab**
- ✅ Working (displays 194 legs from May 12)
- ⏳ Will show coverage_overall after next run

#### **Dashboard Tab**
- ✅ Working (queries v2 only, no v1 UNION)
- ✅ Shows 185 total parlays
- ✅ Shows 4 pending parlays

#### **Training Tab**
- ✅ Working
- Shows 90,331 training samples

#### **Picks Tab**
- ✅ Working
- Shows latest recommendations
- ⏳ Manual trigger endpoint being added

**Status:** ✅ Fully operational

---

### **7. Deployment (Railway)** ✅ OPERATIONAL

#### **Recent Deployments**
- **12:38 PM ET** - Commit e683147 (coverage_overall fix)
- **12:39 PM ET** - Commit a93e74d (v1 migration + schema)
- ⏳ **Pending** - Filter fixes + manual trigger

**Status:** ✅ Auto-deploy working, latest code live

---

## Performance Benchmarks

### **Database Operations**
Schema migrations:       ✅ 3 migrations executed successfully
V1→V2 migration:         ✅ 50 parlays migrated in ~30 seconds
Dashboard queries:       ✅ <500ms (v2 only, faster than v1+v2 UNION)

### **Pipeline Execution**
Last successful parlay generation: May 11 (before filter bugs introduced)
Current state: 0 parlays (blocked by filters)
Expected after fixes: 4-5 parlays per run

---

## Known Issues

### **CRITICAL: Filter Bugs**
- **Issue:** game_start_time filter + lineup check broken
- **Impact:** 0 parlays generated
- **Status:** Fixes in development
- **ETA:** 30-60 minutes

### **Historical Data Gap**
- **Issue:** coverage_overall NULL for May 5-11 (~1,820 legs)
- **Impact:** Calibration data missing coverage signal
- **Status:** Accepted limitation
- **Mitigation:** Let new data accumulate

### **Pitcher Data Not Wired**
- **Issue:** pitcher_id, pitcher_era, etc. are NULL
- **Impact:** Pitcher matchup logic not operational
- **Status:** Phase 3 work
- **ETA:** 3-4 hours after filters fixed

---

## Recent Milestones

### **May 12, 2026 - Schema Cleanup + coverage_overall Fix**
- ✅ V1→V2 migration complete (50 parlays, 0 errors)
- ✅ V1 tables deprecated (30-day safety net)
- ✅ 13 new columns added to mlb_scored_legs
- ✅ coverage_overall persistence fixed
- ✅ Dashboard updated to v2 only
- ⏳ Filter bugs discovered, fixes in progress

### **May 11, 2026 - Comprehensive Diagnostic + Adjustments**
- ✅ Scoring adjustments deployed
- ✅ Diversity constraint removed
- ✅ game_start_time reliability improved
- ⏳ Adjustments validation pending

### **May 10, 2026 - ML Calibration + Game Filter**
- ✅ Stat-specific calibrator deployed
- ✅ Game start time filter implemented
- ✅ 16.6% Brier improvement

---

## Success Criteria (Next Pipeline Run)

| Component | Current | Target | Status |
|-----------|---------|--------|--------|
| coverage_overall populated | 0% | 100% | ⏳ Awaiting run |
| game_start_time filter | Blocks all | Realistic | ⏳ Fix in dev |
| Lineup check | 100% scratched | 5-10% | ⏳ Fix in dev |
| Parlays generated | 0 | 4-5 | ⏳ After fixes |
| Dashboard v1 queries | Removed | Removed | ✅ Complete |

---

## Next Steps

### **IMMEDIATE**
1. ⏳ Deploy filter fixes (30-60 min)
2. ⏳ Trigger manual pipeline run
3. ⏳ Verify coverage_overall populates
4. ⏳ Verify parlays generated

### **SHORT TERM**
5. 🎯 Phase 3: Wire pitcher data into scoring
6. 🎯 Dashboard redesign (original goal)

### **MEDIUM TERM**
7. 🎯 Model retraining with pitcher features
8. 🎯 Direction-split calibration

---

**🎯 CURRENT STATUS:** Schema cleanup complete, coverage_overall fix deployed. Filter bugs blocking parlay generation are being fixed now. After fixes deploy, system should be fully operational.

**Next check-in:** After filter fixes deployed + manual pipeline run (today, ~30-60 min) game_start_time fixes deployed (awaiting validation). Expected impact: +60-80% hit rate improvement. System should generate 4-5 quality parlays per batch with 60% overs starting tomorrow. Regenerate button fix awaiting first test.

**Next check-in:** May 12, 2026 (after 9 AM pipeline validates all improvements)
