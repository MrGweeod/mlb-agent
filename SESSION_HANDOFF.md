# MLB Parlay Agent — Session Handoff
**Last Updated:** May 12, 2026 (End of Day - Schema Cleanup + Filter Fixes)

## Current Status
✅ **Phase 1+2 COMPLETE** - Schema cleanup + coverage_overall fix deployed
⏳ **Filter Fixes IN PROGRESS** - game_start_time + lineup check being fixed
⏳ **Verification PENDING** - Awaiting next pipeline run to confirm coverage_overall populates

---

## What Was Accomplished Today (May 12, 2026)

### **ACHIEVEMENT 1: V1 → V2 Schema Migration**

**Problem Solved:**
Dual-schema complexity (v1 flat + v2 normalized) causing maintenance burden and potential double-counting in analytics.

**Solution Implemented:**
- Created migration script: `scripts/migrate_v1_to_v2.py`
- Migrated **50 v1 parlays** to v2 normalized schema (not 35 as estimated)
- Deprecated v1 tables with 30-day safety net:
  - `mlb_recommendations` → `mlb_recommendations_deprecated_20260512`
  - `mlb_parlay_legs` → `mlb_parlay_legs_deprecated_20260512`
- Updated dashboard to query **v2 tables exclusively** (removed v1 UNION queries)

**Results:**
- ✅ Total v2 parlays: 185 (50 migrated + 135 native)
- ✅ Migration errors: 0
- ✅ Dashboard loads without errors
- ✅ V1 tables safe to drop after June 11, 2026

**Commits:** a93e74d, e683147  
**Status:** ✅ Complete and deployed

---

### **ACHIEVEMENT 2: Database Schema Expansion**

**Problem Solved:**
Missing columns for coverage signals and pitcher matchup data blocked ML model from using trained features.

**Solution Implemented:**

**Added to mlb_scored_legs:**
- `coverage_overall` - Primary coverage signal (was 100% NULL)
- `coverage_vs_hand` - Handedness-split coverage
- `coverage_recent_10` - 10-game rolling coverage
- `coverage_recent_5` - 5-game rolling coverage
- `pitcher_id`, `pitcher_name`, `pitcher_team` - Pitcher identification
- `pitcher_era`, `pitcher_k9`, `pitcher_whip` - Pitcher stats
- `batter_hand` - Batter handedness (L/R/S)
- `pitcher_vs_batter_hand_era` - Handedness-split ERA

**Extended pitcher_profiles table:**
- `pitcher_name` - Full name for display
- `vs_rhb_era`, `vs_lhb_era` - Handedness-split ERA
- `vs_rhb_k9`, `vs_lhb_k9` - Handedness-split strikeout rates

**Results:**
- ✅ 13 new columns added successfully
- ✅ Indexes created on pitcher_id and coverage_overall
- ✅ No ALTER TABLE errors

**Commits:** a93e74d  
**Status:** ✅ Schema changes deployed

---

### **ACHIEVEMENT 3: Fixed coverage_overall Persistence**

**Problem Identified:**
coverage_overall was NULL for 100% of rows (2,014+ legs over last 7 days). Root cause analysis revealed:
- ✅ main.py line 298 was ALWAYS setting coverage_overall in leg dict
- ❌ db.py INSERT statement was NOT including it in column list
- Result: Data calculated but never saved

**Solution Implemented:**
Updated `src/utils/db.py` `log_scored_legs()` function:
- Added coverage_overall to INSERT column list
- Added all 13 new columns to value tuple
- Updated ON CONFLICT clause to backfill NULLs:
```sql
coverage_overall = COALESCE(mlb_scored_legs.coverage_overall, EXCLUDED.coverage_overall)
```

**Timeline:**
- 12:00 PM ET: Pipeline ran, inserted 194 legs WITHOUT coverage_overall (pre-fix)
- 12:38 PM ET: Fix committed (e683147)
- 12:39 PM ET: Railway deployed fix
- **Next run:** coverage_overall will populate for all new legs

**Results:**
- ✅ Fix deployed and verified in code
- ⏳ Awaiting next pipeline run for data verification
- ⚠️ Historical data (May 5-11, ~1,820 legs) remains NULL permanently

**Commits:** e683147  
**Status:** ✅ Code fixed, ⏳ Data verification pending

---

### **ACHIEVEMENT 4: Critical Filter Bugs Identified**

**Problem Discovered:**
Post-deployment logs showed 0 parlays generated despite schema fixes:
[regenerate] 194 legs → 0 upcoming (filtered 0 started, 194 missing time)
SCRATCHED: 24 player(s) marked as scratched
Result: No legs after lineup check. Exiting.

**Root Causes Identified:**

**Bug 1: game_start_time Filter**
- Filter treats ALL valid game_start_time values as "missing"
- Contradictory log: "All 194 legs have game_start_time" then "194 missing time"
- Likely issue: Datetime parsing error or timezone mismatch

**Bug 2: Lineup Check**
- ALL 24 eligible players marked as "scratched" (including star players)
- Likely issues:
  - API timing out or returning empty
  - Player name mismatch (e.g., "Bobby Witt Jr." vs "Robert Witt Jr.")
  - Wrong game_pk being checked

**Solution In Progress:**
Claude Code implementing fixes now:
- Add debug logging to trace filter logic
- Fix datetime parsing in game_start_time filter
- Add fuzzy name matching to lineup check
- Add manual pipeline trigger endpoint for testing

**Status:** ⏳ Fixes in development

---

## Current System Metrics

### **Database Status**
```sql
-- mlb_scored_legs (May 12)
Total legs: 194
coverage_overall populated: 0 (awaiting next run)
pitcher_id populated: 0 (Phase 3 work)
game_start_time populated: 194 (100%)

-- mlb_parlay_recommendations_v2
Total parlays: 185 (50 v1_migrated + 135 v2_native)
Pending parlays: 4
```

### **Schema Changes**
- ✅ V1 tables deprecated
- ✅ 13 new columns added
- ✅ Dashboard queries v2 only
- ✅ Migration completed with 0 errors

---

## Known Issues

### **Issue 1: Filter Bugs Blocking Parlay Generation**
**Status:** ⏳ Being fixed now  
**Impact:** 0 parlays generated since deployment  
**ETA:** 30-60 minutes  

### **Issue 2: Historical Data Gap**
**Status:** Accepted limitation  
**Impact:** 1,820 legs (May 5-11) have coverage_overall = NULL permanently  
**Mitigation:** Let new data accumulate (14 days = ~1,960 samples)  

### **Issue 3: Pitcher Data Not Wired**
**Status:** Phase 3 work  
**Impact:** pitcher_id, pitcher_era, etc. are NULL (expected)  
**ETA:** Phase 3 (3-4 hours after filters fixed)  

---

## Next Session Priorities

### **IMMEDIATE (Next 2 Hours)**
1. **Complete Filter Fixes**
   - Deploy game_start_time filter fix
   - Deploy lineup check fix
   - Deploy manual pipeline trigger

2. **Trigger Manual Pipeline Run**
   - Use new `/api/admin/run_pipeline` endpoint
   - Watch Railway logs in real-time
   - Verify parlays generated

3. **Verify coverage_overall Populates**
```sql
   SELECT COUNT(coverage_overall) FROM mlb_scored_legs WHERE run_date = CURRENT_DATE::text;
   -- Expected: 150-200 (not 0)
```

### **SHORT TERM (Next 7 Days)**
4. **Phase 3: Wire Pitcher Data Into Scoring**
   - Fetch pitcher stats from MLB-StatsAPI
   - Cache in pitcher_profiles table
   - Add batter handedness lookup
   - Calculate handedness-split coverage
   - Use pitcher data in scoring logic

5. **Dashboard Redesign**
   - Original goal before discovering tech debt
   - Rebuild Legs, Dashboard, Training, Picks tabs
   - Focus on utility and actionable insights

### **MEDIUM TERM (Next 30 Days)**
6. **Model Retraining with Pitcher Features**
   - After 1-2 weeks of pitcher data accumulation
   - Add pitcher_era, pitcher_k9, pitcher_vs_batter_hand_era as features
   - Expected: Significant accuracy improvement

---

## Success Criteria (Next Pipeline Run)

| Metric | Current | Target | How to Check |
|--------|---------|--------|--------------|
| coverage_overall NULL rate | 100% | 0% | SQL query |
| game_start_time filter | Blocks all | Filters realistically | Railway logs |
| Lineup check scratches | 24/24 (100%) | 2-5 realistic | Railway logs |
| Parlays generated | 0 | 4-5 | Database count |
| Pitcher data populated | 0% | 0% (Phase 3) | Expected NULL |

---

## Common Operations

### **Trigger Manual Pipeline Run**
```bash
curl -X POST https://mlb-agent-production.up.railway.app/api/admin/run_pipeline
```

### **Check coverage_overall Status**
```sql
-- Run in Supabase SQL Editor
SELECT 
    COUNT(*) as total,
    COUNT(coverage_overall) as have_coverage,
    AVG(coverage_overall) as avg_coverage
FROM mlb_scored_legs
WHERE run_date = CURRENT_DATE::text;
```

### **Check Parlay Generation**
```sql
SELECT COUNT(*) as parlays_today
FROM mlb_parlay_recommendations_v2
WHERE run_date = CURRENT_DATE;
```

---

## Key Files Modified Today

### **Database Migrations**
- `migrations/add_pitcher_columns.sql` - Added 13 columns to mlb_scored_legs
- `migrations/create_pitcher_profiles.sql` - Extended pitcher_profiles table
- `migrations/deprecate_v1_tables.sql` - Renamed v1 tables with _deprecated suffix

### **Scripts**
- `scripts/migrate_v1_to_v2.py` - V1 to V2 migration script (50 parlays)

### **Core Changes**
- `src/utils/db.py` - Fixed coverage_overall persistence + dashboard v2 queries
- `src/web/server.py` - (In progress) Filter fixes + manual trigger endpoint

---

## Critical Reminders

### **coverage_overall Fix**
- ✅ Code is fixed (commit e683147)
- ⏳ Data will populate on next pipeline run
- ❌ Historical data (May 5-11) remains NULL

### **V1 Schema Deprecated**
- ✅ All 50 v1 parlays migrated to v2
- ✅ Dashboard queries v2 only
- ⚠️ V1 tables safe to drop after June 11, 2026

### **Filter Bugs**
- 🔥 Blocking all parlay generation
- ⏳ Fixes in development now
- 🎯 Must deploy before evening pipeline (5:30 PM ET)

---

## Contact & Resources

### **Monitoring**
- Railway Dashboard: https://railway.app
- Supabase Console: https://supabase.com
- GitHub Repo: github.com/MrGweeod/mlb-agent

### **Current Blockers**
- ⏳ Filter fixes (in progress, ETA 30-60 min)
- ⏳ coverage_overall verification (after next run)

---

**🎯 BOTTOM LINE:** Phase 1+2 complete - schema cleaned up, v1 deprecated, coverage_overall fix deployed. Filter bugs discovered post-deployment are being fixed now. After filter fixes deploy + manual trigger, system should be fully operational with coverage_overall populating correctly. Next milestone: Phase 3 pitcher data wiring.

**Next check-in:** After filter fixes deployed + manual pipeline triggered (today, ~30-60 min)
