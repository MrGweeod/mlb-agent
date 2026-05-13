# MLB Parlay Agent — Session Handoff
**Last Updated:** May 12, 2026 (End of Day - All Critical Systems Operational)

## Current Status
✅ **All Critical Systems OPERATIONAL**
- Pipeline Runtime: Fully functional (3x daily + manual trigger)
- ML Scoring: Operational with temporary adjustments
- coverage_overall: Populating correctly (96.8%)
- Pitcher Data: Populating (45% from pre-fix runs, 100% expected tomorrow)
- Database: All tables operational
- Deployment: Live on Railway
- Dashboard: Fully functional with real-time updates
- Regenerate Button: Working with polling UI

---

## What Was Accomplished Today (May 12, 2026)

### **Phase 1: Critical Bug Fixes (Morning)**

**1. Fixed game_start_time Filter**
- **Problem**: Filter treated ALL valid datetime objects as "missing" due to `datetime.strptime()` type error
- **Root Cause**: `isinstance(gst, datetime.datetime)` when datetime was imported as class, not module
- **Fix**: Changed to `isinstance(gst, datetime)` and handle both string/datetime types
- **Result**: Filter now correctly identifies upcoming games vs started games

**2. Fixed Lineup Check**
- **Problem**: All 24 players marked "SCRATCHED" even though they were starting
- **Root Cause**: `boxscore_data()` returns empty `battingOrder` for future games where lineups haven't been officially submitted
- **Fix**: Skip lineup check if `starters` set is empty (lineups not announced yet)
- **Result**: Only actual scratches are filtered (2-5 players typically)

**3. Added Manual Pipeline Trigger**
- **Problem**: No way to test pipeline changes without waiting for scheduled runs
- **Fix**: Added `/api/admin/run_pipeline` endpoint that runs `run_targeted_pipeline()` in background thread
- **Result**: On-demand testing capability for immediate validation

**4. Fixed Player ID Resolution**
- **Problem**: SGO props returning 0 matches because MLB player ID lookup failing for all 450 props
- **Root Cause**: `statsapi.lookup_player()` calls timing out/failing, all props had `player_id=None`
- **Fix**: Hybrid resolution system:
  - Primary: Use database name→ID mapping (fast, reliable, covers known players)
  - Fallback: Call `statsapi.lookup_player()` only for NEW players not in DB
- **Result**: 25/25 props matched, odds updating correctly

---

### **Phase 2: Schema & Data Flow Fixes (Afternoon)**

**5. Fixed coverage_overall Persistence**
- **Problem**: 100% NULL across 2,014+ rows (7 days of data)
- **Root Cause**: `db.py` INSERT statement missing `coverage_overall` in column list
- **Fix**: Added to INSERT + ON CONFLICT backfill clause
- **Result**: 96.8% populated (333/344 legs) - 11 NULL from pre-fix 12 PM run
- **Historical Gap**: May 5-11 (~1,820 legs) remain NULL permanently (accepted limitation)

**6. Fixed UI Stale Parlays (v1 Batch Shadowing)**
- **Problem**: UI showing old v1 parlays despite new v2 parlays being generated
- **Root Cause**: `ORDER BY batch_id DESC` sorted lexicographically - "v1_2026-05-12_2" > "2026-05-12_20:45:50" because 'v' > '2'
- **Fix**: Changed to `ORDER BY MAX(created_at) DESC` - sorts by actual timestamp
- **Result**: UI now shows latest v2 batch correctly

**7. Populated Pitcher Data Fields**
- **Problem**: All pitcher columns (pitcher_id, pitcher_hand, batter_hand, pitcher_era, etc.) were NULL
- **Root Causes**:
  - Gap 1: `mlb_player_positions` table empty → `batter_hand` always None
  - Gap 2: `enrich_legs.py` unconditionally overwrote `pitcher_hand` with None for hitter legs
  - Gap 3: Pitcher profile data fetched but never attached to leg dicts
- **Fixes**:
  - Gap 1: Added `set_player_position()` call in main.py after fetching player info
  - Gap 2: Only set `pitcher_hand` for pitcher props, not hitter legs
  - Gap 3: Attached pitcher_id, pitcher_name, pitcher_era, pitcher_k9, pitcher_whip to leg dicts in enrich_legs.py
- **Result**: 45% of current legs have pitcher data (from afternoon runs post-fix), 100% expected after tomorrow's 9 AM run

**8. Fixed Regenerate Button**
- **Problem 1**: Returned same 2 parlays every time (deterministic from same DB legs)
- **Problem 2**: No loading state, required manual tab switching to see results
- **Fix 1**: Changed from loading pre-scored DB legs to calling `run_targeted_pipeline()` which fetches fresh SGO odds
- **Fix 2**: Added `source="manual"` parameter so manual runs are properly tagged
- **Fix 3**: Added polling UI - shows "Regenerating Recommendations..." spinner, polls every 2s for new `generated_at`, auto-updates when complete
- **Result**: Fresh odds → different parlays, smooth UX with loading state and auto-refresh

---

## Current System Metrics

### **Database Status (as of 5:00 PM ET)**
```sql
-- mlb_scored_legs (May 12)
Total legs: 344
coverage_overall populated: 333 (96.8%)
pitcher_id populated: 93 (27.0%) - will reach 100% tomorrow
game_start_time populated: 344 (100%)

-- mlb_parlay_recommendations_v2
Total parlays: 210+ (50 v1_migrated + 160+ v2_native)
Pending parlays: 2
Source distribution: manual, auto_530pm, auto_12pm
```

### **Pipeline Performance**
- Last successful run: 5:30 PM ET (auto_530pm)
- Legs processed: 207
- Fresh odds fetched: 25/25 players
- Parlays built: 2 (rank 1-2, +1496/+1491 odds)
- Regenerate button: Fully functional with ~25s runtime

---

## Known Issues

### **Issue 1: Pitcher Data Incomplete (Temporary)**
**Status:** Expected to resolve tomorrow
**Current:** 45% of legs have pitcher data (93/207)
**Why:** Legs in DB are from 12:00 PM run before pitcher data fixes deployed
**Resolution:** Tomorrow's 9:00 AM pipeline run will score fresh legs with all pitcher data
**Next Check:** May 13, 9:30 AM ET - query pitcher field coverage

### **Issue 2: ML Scoring Not Using Pitcher Data (Phase 3 Incomplete)**
**Status:** In progress
**Current:** `pitcher_quality` and `opponent_offense` features hardcoded to 50.0 (placeholders)
**Impact:** ML model not benefiting from pitcher matchup intelligence yet
**Next Step:** Wire pitcher_profiles data into `_extract_features()` in ml_leg_scorer.py
**ETA:** 2-3 hours of work remaining

### **Issue 3: Scoring Adjustments Still Aggressive (From Diagnostic)**
**Status:** Not yet addressed
**Current:** OVER_BOOST = +18, UNDER_PENALTY = -26 (too large)
**Impact:** Some score distributions are binary (floor/ceiling abuse)
**Recommended:** Reduce to +8/-12 based on diagnostic analysis
**Priority:** Address after Phase 3 complete

---

## Next Session Priorities

### **IMMEDIATE (Next Session Start)**
1. **Verify Pitcher Data Population**
   - Wait for 9:00 AM pipeline run (May 13)
   - Run query to confirm 100% pitcher field coverage
   - Check debug logs for sample leg with all fields

2. **Complete Phase 3: Wire Pitcher Data Into ML Scoring**
   - Modify `ml_leg_scorer.py` `_extract_features()` function
   - Replace `pitcher_quality = 50.0` with actual ERA rank from pitcher_profiles
   - Replace `opponent_offense = 50.0` with actual team offense metrics
   - Test with manual pipeline trigger
   - Expected impact: Improved accuracy on batter props

### **SHORT TERM (This Week)**
3. **Address ML Scoring Issues (From Diagnostic)**
   - Reduce scoring adjustment magnitudes (C2 from diagnostic)
   - Consider blocking hits/under temporarily (H3 from diagnostic)
   - Or begin direction-split calibration (H2 from diagnostic)

4. **Dashboard Redesign**
   - Original goal before discovering tech debt
   - Rebuild Legs, Dashboard, Training, Picks tabs
   - Focus on utility and actionable insights

### **MEDIUM TERM (Next 30 Days)**
5. **Model Retraining with Pitcher Features**
   - After 1-2 weeks of pitcher data accumulation
   - Add pitcher_era, pitcher_k9, pitcher_vs_batter_hand_era as features
   - Expected: Significant accuracy improvement

---

## Success Criteria (Next Pipeline Run - May 13, 9:00 AM)

| Metric | Current | Target | How to Check |
|--------|---------|--------|--------------|
| pitcher_id populated | 27% | 100% | SQL query on run_date = '2026-05-13' |
| pitcher_hand populated | 26% | 100% | Same query |
| batter_hand populated | 27% | 100% | Same query |
| Parlays generated | 2 | 4-5 | Check mlb_parlay_recommendations_v2 |
| Regenerate button | Working | Working | Manual test |

**Verification Query:**
```sql
SELECT 
    COUNT(*) as total_legs,
    COUNT(pitcher_id) as have_pitcher_id,
    COUNT(pitcher_hand) as have_pitcher_hand,
    COUNT(batter_hand) as have_batter_hand,
    AVG(coverage_overall) as avg_coverage
FROM mlb_scored_legs 
WHERE run_date = '2026-05-13';
```

Expected: All counts = total_legs (100%)

---

## Common Operations

### **Trigger Manual Pipeline Run**
```bash
curl -X POST https://mlb-agent.up.railway.app/api/admin/run_pipeline \
  -H "Authorization: Bearer MLBparlays"
```

### **Check Pitcher Data Status**
```sql
SELECT 
    run_date,
    COUNT(*) as total,
    COUNT(pitcher_id) as have_pitcher,
    COUNT(batter_hand) as have_batter_hand
FROM mlb_scored_legs 
WHERE run_date >= CURRENT_DATE::text
GROUP BY run_date
ORDER BY run_date DESC;
```

### **Check Latest Parlays**
```sql
SELECT 
    batch_id,
    source,
    COUNT(*) as parlay_count,
    MAX(created_at) as latest
FROM mlb_parlay_recommendations_v2
WHERE run_date = CURRENT_DATE
GROUP BY batch_id, source
ORDER BY MAX(created_at) DESC
LIMIT 5;
```

---

## Key Files Modified Today

### **Core Pipeline**
- `main.py` - Added batter_hand population, pitcher data wiring, source parameter
- `src/pipelines/enrich_legs.py` - Fixed pitcher_hand overwrite, attached profile data
- `src/utils/db.py` - Fixed coverage_overall INSERT, added debug error handling

### **Web Interface**
- `src/web/server.py` - Fixed timezone, batch query, regenerate logic, added polling
- `src/web/static/index.html` - Added polling UI with loading state

### **API Integration**
- `src/apis/sportsgameodds.py` - Added player_names fallback for SGO filtering

---

## Critical Reminders

### **Pitcher Data Flow**
1. Morning pipeline (9 AM) scores legs → populates all pitcher fields
2. Targeted pipelines (12 PM, 5:30 PM) load pre-scored legs → pitcher data already there
3. Regenerate button calls targeted pipeline → loads pre-scored legs
4. **Tomorrow's 9 AM run is critical** for full pitcher data coverage

### **Coverage Fields**
- `coverage_overall` - Primary coverage signal (now populating correctly)
- `coverage_vs_hand` - Handedness-split coverage (computed but may be NULL if <10 games vs that handedness)
- `coverage_recent_10` - 10-game rolling coverage
- `coverage_recent_5` - 5-game rolling coverage (pitchers only)

### **Regenerate Button**
- Triggers `run_targeted_pipeline(source="manual")`
- Fetches fresh SGO odds for all scored legs
- Updates composite_scores based on new odds
- Builds new parlays (not deterministic anymore!)
- UI polls every 2s, auto-updates when complete

---

## Contact & Resources

### **Monitoring**
- Railway Dashboard: https://railway.app
- Supabase Console: https://supabase.com
- GitHub Repo: github.com/MrGweeod/mlb-agent

### **Current Blockers**
- None! All systems operational

---

**🎯 BOTTOM LINE:** All critical systems operational after full day of fixes. Pitcher data infrastructure complete, waiting for tomorrow's 9 AM run to verify 100% population. Phase 3 (wire pitcher data into ML scoring) is ~2-3 hours from completion. System is stable and ready for continued development.

**Next check-in:** May 13, 2026 (after 9 AM pipeline verifies pitcher data)
