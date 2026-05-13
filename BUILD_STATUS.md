# MLB Parlay Agent — Build Status
**Last Updated:** May 12, 2026 (End of Day - All Systems Operational)

## Overall System Status: ✅ FULLY OPERATIONAL
┌──────────────────────────────────────────────────────────┐
│              SYSTEM HEALTH DASHBOARD                     │
├──────────────────────────────────────────────────────────┤
│ Pipeline Runtime:      ✅ OPERATIONAL (3x daily)         │
│ ML Scoring:            ✅ OPERATIONAL                    │
│ coverage_overall:      ✅ POPULATING (96.8%)             │
│ Pitcher Data:          ⏳ PARTIAL (100% expected tmrw)   │
│ Database:              ✅ OPERATIONAL                    │
│ Deployment:            ✅ LIVE (Railway)                 │
│ Dashboard:             ✅ OPERATIONAL                    │
│ Regenerate Button:     ✅ OPERATIONAL (with polling)     │
└──────────────────────────────────────────────────────────┘

---

## Component Status

### **1. Pipeline Execution** ✅ OPERATIONAL

#### **Daily Schedule (3 Runs)**
- **9:00 AM ET** - Morning pipeline (resolution + full fetch/score/build)
- **12:00 PM ET** - Midday pipeline (targeted SGO fetch + lineup check)
- **5:30 PM ET** - Evening pipeline (targeted SGO fetch + lineup check)

#### **Latest Run Performance (5:30 PM ET, May 12)**
Props fetched:           1,856 available
Legs scored:             207
Legs after filters:      88 eligible
Fresh odds updated:      25/25 players (100%)
Player ID resolution:    25 via DB, 0 via API
Parlays built:           2 (rank 1-2)
Average ML score:        77.1% (top 20), 73.8% (top 50)
Build time:              <1 second

**Status:** ✅ All three daily runs executing successfully

---

### **2. Data Sources** ✅ OPERATIONAL

#### **TheOddsAPI (Primary Props Source)**
- Status: ✅ Connected
- Last fetch: May 12, 5:30 PM ET
- Props returned: 1,856
- Rate limit: 500 req/month (shared across features)
- Usage: ~15 requests/day

#### **MLB-StatsAPI (Game Logs, Stats, Schedules)**
- Status: ✅ Connected
- No API key required
- Transaction wire polling: Working
- Box score retrieval: Working
- Player lookup: Working with hybrid fallback

#### **Supabase PostgreSQL (Database)**
- Status: ✅ Connected
- Tables: All operational (v1 deprecated, v2 active)
- Connection pool: Stable
- Last schema update: May 12, 2026

---

### **3. Database Schema** ✅ OPERATIONAL (V2 Only)

#### **mlb_scored_legs** (Daily scored props)
**New columns added May 12:**
✅ coverage_overall      - Primary coverage signal (96.8% populated)
✅ coverage_vs_hand      - Handedness-split coverage
✅ coverage_recent_10    - 10-game rolling coverage
✅ coverage_recent_5     - 5-game rolling coverage
⏳ pitcher_id            - Pitcher MLB ID (27% populated, 100% tmrw)
⏳ pitcher_name          - Pitcher full name (27%)
⏳ pitcher_team          - Pitcher team abbreviation (27%)
⏳ pitcher_era           - Pitcher ERA (27%)
⏳ pitcher_k9            - Pitcher K/9 rate (27%)
⏳ pitcher_whip          - Pitcher WHIP (27%)
⏳ pitcher_hand          - Pitcher throwing hand (26%)
⏳ batter_hand           - Batter hitting hand (27%)
⏳ pitcher_vs_batter_hand_era - Handedness-split ERA (0%)

**Current data status:**
- Total legs (May 12): 344
- coverage_overall: 333/344 (96.8%) ✅
- game_start_time: 344/344 (100%) ✅
- pitcher fields: 93/344 (27%) ⏳ - Expected 100% after 9 AM run tomorrow

#### **mlb_parlay_recommendations_v2** (Parlay headers)
Total parlays: 210+

50 v1_migrated (from May 12 migration)
160+ v2_native (generated since May 7)
Pending parlays: 2
Latest batch: 2026-05-12_21:42:22 (source: manual)


#### **mlb_parlay_legs_v2** (Per-leg tracking)
Total legs: 800+
Outcome tracking: ✅ Per-leg outcomes recorded
Position tracking: ✅ Pitcher exemption working

#### **V1 Schema Deprecated** (May 12)
mlb_recommendations → mlb_recommendations_deprecated_20260512
mlb_parlay_legs → mlb_parlay_legs_deprecated_20260512
Safe to drop after: June 11, 2026

**Status:** ✅ V2 schema fully operational, dashboard queries v2 only

---

### **4. Filter System** ✅ OPERATIONAL

#### **game_start_time Filter**
- Status: ✅ Fixed (May 12)
- Logic: Exclude games starting within 15 minutes
- Type handling: Both datetime objects and strings supported
- Fail-closed: NULL times excluded
- Latest result: 0 started, 0 missing time

#### **Lineup Check**
- Status: ✅ Fixed (May 12)
- Logic: Skip check if batting order empty (lineups not announced)
- Latest result: 2 scratched (Ryan O'Hearn, Trea Turner)
- False positive rate: 0% (was 100%)

#### **Coverage Gate**
- Status: ✅ Working
- Threshold: 55% minimum for candidate pool
- ML gate in parlay builder: 65% minimum
- Latest result: 88 eligible legs from 207 total

---

### **5. ML Scoring System** ✅ OPERATIONAL (With Known Limitations)

#### **Base Model**
Model: leg_scorer_v2.pkl
Type: GradientBoostingClassifier (calibrated)
Training date: April 30, 2026
Training samples: ~77,000
AUC: 0.8532
Known issue: Direction feature 77% importance (overfit)

#### **Calibrator**
Type: Stat-specific isotonic regression (7 calibrators)
Training date: May 10, 2026
Training samples: 52,583 resolved legs
Brier improvement: +16.6% (0.2826 → 0.2341)
Average prediction: 45.5% (matches actual hit rate)

#### **Temporary Adjustments** (Active)
Direction: Overs +18pp, Unders -26pp
Odds signal: Long-odds unders -15pp (≥150), -8pp (≥120)
Same-game: Correlated props -20pp
Floor: 5.0, Ceiling: 95.0
Status: Temporary until model retraining (H1 from diagnostic)

#### **Feature Status**
✅ coverage_overall      - Now populating correctly (was 100% NULL)
✅ coverage_vs_hand      - Computed (may be NULL if <10 games)
✅ coverage_recent_10    - Working
✅ coverage_recent_5     - Working (pitchers only)
⚠️  pitcher_quality      - Hardcoded to 50.0 (Phase 3 in progress)
⚠️  opponent_offense     - Hardcoded to 50.0 (Phase 3 in progress)
✅ line                  - Working
✅ direction             - Working

**Status:** ✅ Operational with temporary adjustments, Phase 3 incomplete

---

### **6. Web Dashboard** ✅ OPERATIONAL

#### **Legs Tab**
- Status: ✅ Working
- Shows: 207 legs from May 12
- Filters: By stat, player, team
- Coverage display: ✅ Now showing coverage_overall values

#### **Dashboard Tab**
- Status: ✅ Working
- Queries: V2 schema only (no v1 UNION)
- Shows: 210+ total parlays
- Performance: <500ms load time (2x faster than v1+v2 UNION)

#### **Training Tab**
- Status: ✅ Working
- Shows: 90,331 training samples
- Quality metrics: Displayed correctly

#### **Picks Tab**
- Status: ✅ Working
- Latest recommendations: 2 parlays (manual, 9:42 PM)
- Regenerate button: ✅ Fully functional with polling UI
- History: Shows all 23 batches from May 12
- Auto-refresh: ✅ Polls every 2s, updates when new batch ready

**Status:** ✅ All tabs operational, Regenerate button working with smooth UX

---

### **7. Regenerate Button** ✅ OPERATIONAL (Major Upgrade)

#### **Old Behavior (Before May 12)**
❌ Loaded pre-scored legs from DB
❌ Built parlays from stale data
❌ Returned same 2 parlays every time
❌ No loading state
❌ Required manual tab switching to see results

#### **New Behavior (After May 12)**
✅ Triggers run_targeted_pipeline(source="manual")
✅ Fetches fresh SGO odds for all legs
✅ Updates composite_scores with new odds
✅ Builds new parlays (non-deterministic)
✅ Shows "Regenerating Recommendations..." with spinner
✅ Polls every 2s for new generated_at timestamp
✅ Auto-updates UI when complete (~25s runtime)
✅ Displays "New parlays ready!" toast
✅ 60s timeout with helpful message

**Latest Test (May 12, 9:42 PM):**
- Trigger: ✅ Success
- Fresh odds: ✅ 25/25 players updated
- Parlays built: ✅ 2 new parlays
- UI update: ✅ Auto-refreshed after 25s
- User experience: Smooth, no manual intervention needed

**Status:** ✅ Fully operational with professional UX

---

### **8. Deployment (Railway)** ✅ OPERATIONAL

#### **Recent Deployments**
May 12, 9:42 PM - Regenerate button polling UI (commit 41e1b11)
May 12, 9:30 PM - Source parameter for manual runs (commit 1d073ae)
May 12, 8:50 PM - Batch query fix for v1 shadowing (commit d4a9c3e)
May 12, 4:30 PM - Pitcher data population (commit b71cca5)
May 12, 3:15 PM - Player ID resolution (commit a8f2d1c)
May 12, 2:00 PM - Filter fixes (commit e683147)

**Status:** ✅ Auto-deploy working, all deployments successful today

**Resources:**
Plan: Hobby ($5/month)
Projects: 2 (NBA agent, MLB agent)
Uptime: 99.9%
Build time: ~2-3 minutes per deploy

---

## Performance Benchmarks

### **Database Operations**
Schema migrations:       ✅ 3 migrations executed successfully (May 12)
V1→V2 migration:         ✅ 50 parlays migrated in ~30 seconds
Dashboard queries:       ✅ <500ms (v2 only, 2x faster than v1+v2 UNION)
Coverage query:          ✅ <100ms for 344 legs

### **Pipeline Execution**
Full morning pipeline:   ~5-8 minutes (score 200-400 legs)
Targeted refresh:        ~25-30 seconds (update odds for ~25 legs)
Parlay building:         <1 second (Branch-and-Bound with 88 legs)
Manual trigger:          ~25 seconds (same as targeted refresh)

### **API Performance**
SGO props fetch:         ~20 seconds for full slate
MLB player lookup:       ~100ms per player (cached 24hr)
Pitcher profile fetch:   ~200ms per pitcher (cached 24hr)
Box score resolution:    ~500ms per game

---

## Known Issues

### **CRITICAL: None!** 🎉

All critical issues from this morning have been resolved:
- ✅ game_start_time filter working
- ✅ Lineup check working
- ✅ Player ID resolution working
- ✅ coverage_overall populating
- ✅ UI showing latest parlays
- ✅ Regenerate button functional

---

### **HIGH PRIORITY**

**Issue 1: Pitcher Data Incomplete (Temporary)**
- **Status:** ⏳ Awaiting tomorrow's 9 AM run
- **Current:** 27% of legs have pitcher data (93/344)
- **Why:** Legs in DB from 12:00 PM run (before pitcher fixes deployed at 4:30 PM)
- **Resolution:** Tomorrow's 9:00 AM pipeline will score fresh legs with 100% pitcher data
- **Impact:** Phase 3 blocked until full pitcher data available
- **Next Check:** May 13, 9:30 AM ET

**Issue 2: ML Scoring Not Using Pitcher Data (Phase 3 Incomplete)**
- **Status:** ⏳ In progress (2-3 hours remaining)
- **Current:** `pitcher_quality` and `opponent_offense` hardcoded to 50.0
- **Impact:** ML model not leveraging pitcher matchup intelligence
- **Next Step:** Wire pitcher_profiles into `_extract_features()` function
- **Blocked By:** Issue 1 (need 100% pitcher data to verify it works)

---

### **MEDIUM PRIORITY (From Diagnostic Report)**

**Issue 3: Scoring Adjustments Too Aggressive**
- **Status:** Not yet addressed
- **Current:** OVER_BOOST = +18, UNDER_PENALTY = -26
- **Impact:** Some distributions binary (floor/ceiling abuse)
- **Recommendation:** Reduce to +8/-12 (from diagnostic analysis)
- **Priority:** After Phase 3 complete

**Issue 4: Direction Overfit in Base Model**
- **Status:** Known limitation
- **Current:** Direction feature has 77% importance (overfit)
- **Impact:** Inverted score signal (higher scores lose more in some cases)
- **Recommendation:** Retrain with direction-balanced sampling or remove direction feature
- **Priority:** After 500+ new samples with current adjustments

**Issue 5: Direction-Agnostic Calibrators**
- **Status:** Working but suboptimal
- **Current:** 7 stat-specific calibrators (hits_over and hits_under use same calibrator)
- **Impact:** Can't calibrate 62.3% hits_over separately from 26.8% hits_under
- **Recommendation:** Train 14 calibrators (7 stats × 2 directions)
- **Priority:** Medium (after model retraining)

---

### **LOW PRIORITY**

**Issue 6: Historical Coverage Gap**
- **Status:** Permanent gap accepted
- **Details:** May 5-11 legs (~1,820 samples) have coverage_overall = NULL
- **Impact:** 2% of calibration training data missing coverage signal
- **Mitigation:** New data accumulates at ~150-200 legs/day; gap replaced in 14 days

**Issue 7: Schema Type Inconsistencies**
- **Status:** Working but fragile
- **Details:** `run_date` is TEXT in some tables, DATE in others; `odds`/`line` are TEXT but used numerically
- **Impact:** Requires explicit casting in queries (minor annoyance)
- **Mitigation:** Use SUPABASE_SCHEMA_REFERENCE.md for correct casting patterns

---

## Recent Milestones

### **May 12, 2026 - All Critical Systems Operational** ✅
- ✅ Fixed game_start_time filter (datetime type handling)
- ✅ Fixed lineup check (empty batting order handling)
- ✅ Added manual pipeline trigger endpoint
- ✅ Fixed player ID resolution (hybrid DB/API approach)
- ✅ Fixed coverage_overall persistence (96.8% populated)
- ✅ Fixed UI stale parlays (v1 batch shadowing)
- ✅ Populated pitcher data fields (infrastructure complete)
- ✅ Fixed Regenerate button (fresh odds + polling UI)

### **May 11, 2026 - Comprehensive Diagnostic + Adjustments**
- ✅ Ran diagnostic analysis (124 parlays, 4,400 legs)
- ✅ Identified three scoring biases (direction, odds, same-game)
- ✅ Implemented scoring adjustments (+60% expected improvement)
- ✅ Removed diversity constraint (+10-15% expected improvement)
- ✅ Fixed game_start_time reliability

### **May 10, 2026 - ML Calibration + Game Filter**
- ✅ Deployed stat-specific calibrator (+16.6% Brier improvement)
- ✅ Fixed game start time filter (fail-closed logic)
- ✅ Verified 100% game_start_time population

### **May 7, 2026 - V2 Schema**
- ✅ V2 normalized schema deployed
- ✅ Per-leg outcome tracking operational
- ✅ Position tracking added (pitcher exemption)

---

## Success Criteria (Next Run - May 13, 9:00 AM)

| Component | Current | Target | Verification |
|-----------|---------|--------|--------------|
| pitcher_id populated | 27% | 100% | SQL query on run_date = '2026-05-13' |
| pitcher_hand populated | 26% | 100% | Same query |
| batter_hand populated | 27% | 100% | Same query |
| coverage_overall populated | 96.8% | 100% | Same query |
| Parlays generated | 2 | 4-5 | Database count |
| Regenerate button | ✅ Working | ✅ Working | Manual test |
| Fresh odds on regenerate | ✅ Working | ✅ Working | Check logs for "Updated odds" |

**Verification Query:**
```sql
SELECT 
    COUNT(*) as total_legs,
    COUNT(pitcher_id) as have_pitcher_id,
    COUNT(pitcher_hand) as have_pitcher_hand,
    COUNT(batter_hand) as have_batter_hand,
    COUNT(coverage_overall) as have_coverage,
    AVG(coverage_overall) as avg_coverage
FROM mlb_scored_legs 
WHERE run_date = '2026-05-13';
```

**Expected Result:** All counts = total_legs (100% coverage)

---

## System Health Checklist

### **Daily Checks**
- [ ] Morning pipeline (9 AM) executed successfully
- [ ] Midday pipeline (12 PM) executed successfully  
- [ ] Evening pipeline (5:30 PM) executed successfully
- [ ] Parlays generated (4-5 per run expected)
- [ ] No errors in Railway logs
- [ ] Dashboard loads without errors

### **Weekly Checks**
- [ ] Pitcher data at 100% coverage
- [ ] coverage_overall populating consistently
- [ ] Parlay hit rates within expected range (12-15%)
- [ ] No database connection issues
- [ ] Regenerate button functional

### **Monthly Checks**
- [ ] Review scoring adjustment performance
- [ ] Check calibrator accuracy (predicted vs actual)
- [ ] Monitor API rate limits (TheOddsAPI, MLB-StatsAPI)
- [ ] Review database storage usage
- [ ] Plan model retraining if 500+ new samples available

---

## Quick Diagnostic Commands

### **Check Current Pipeline Status**
```bash
# Railway logs (last 100 lines)
railway logs --tail 100

# Manual trigger
curl -X POST https://mlb-agent.up.railway.app/api/admin/run_pipeline \
  -H "Authorization: Bearer MLBparlays"
```

### **Database Health**
```sql
-- Today's legs with field coverage
SELECT 
    run_date,
    COUNT(*) as total,
    COUNT(coverage_overall) as coverage_ok,
    COUNT(pitcher_id) as pitcher_ok,
    COUNT(game_start_time) as game_time_ok
FROM mlb_scored_legs 
WHERE run_date = CURRENT_DATE::text
GROUP BY run_date;

-- Today's parlays
SELECT 
    batch_id,
    source,
    COUNT(*) as count
FROM mlb_parlay_recommendations_v2
WHERE run_date = CURRENT_DATE
GROUP BY batch_id, source
ORDER BY MAX(created_at) DESC;
```

### **Feature Verification**
```sql
-- Verify pitcher data flowing through
SELECT 
    player_name,
    stat,
    direction,
    pitcher_id,
    pitcher_name,
    pitcher_hand,
    batter_hand,
    coverage_overall
FROM mlb_scored_legs
WHERE run_date = CURRENT_DATE::text
  AND pitcher_id IS NOT NULL
LIMIT 5;
```

---

## Decision Review Schedule

**Daily:** Monitor pipeline execution, parlay generation, filter effectiveness  
**Weekly:** Review pitcher data coverage, coverage_overall population, UI functionality  
**Monthly:** Evaluate Phase 3 completion, model retraining criteria, adjustment performance  
**Quarterly:** Reassess architecture, plan major improvements  

---

**Last Review:** May 12, 2026  
**Next Review:** May 13, 2026 (after 9 AM pipeline validates pitcher data)  
**Major Milestone:** All critical systems operational, Phase 3 infrastructure complete
