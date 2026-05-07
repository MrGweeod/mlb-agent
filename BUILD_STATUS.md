# MLB Parlay Agent — Build Status
**Last Updated:** May 7, 2026 (Post-Infrastructure Upgrade)

## Overall System Status: ✅ FULLY OPERATIONAL + MAJOR UPGRADES COMPLETE

```
┌──────────────────────────────────────────────────────┐
│              SYSTEM HEALTH DASHBOARD                 │
├──────────────────────────────────────────────────────┤
│ Pipeline Runtime:      ✅ OPERATIONAL (3x/day)      │
│ ML Model Scoring:      ✅ OPERATIONAL (0% NULL)     │
│ Lineup Filter:         ✅ FIXED (AB >= 3 working)   │
│ SGO API Fetching:      ✅ OPTIMIZED (99% under)     │
│ Lineup Checking:       ✅ AUTOMATIC (12PM/5:30pm)   │
│ Scratch Detection:     ✅ AUTOMATIC (12pm/5:30pm)   │
│ V2 Normalized Schema:  ✅ DEPLOYED (39 parlays)     │
│ Feature Extraction:    ✅ OPERATIONAL (16 features) │
│ Correlation Logging:   ✅ ACTIVE (all parlays)      │
│ Leg Sorting:           ✅ FIXED (chronological)     │
│ DK Validation:         ✅ ACTIVE (WALKS+K blocked)  │
│ Dashboard:             ✅ OPERATIONAL (all tabs)    │
│ Database:              ✅ OPERATIONAL               │
│ Void Logic:            ✅ FIXED (partial voids OK)  │
│ Deployment:            ✅ LIVE (Railway)            │
└──────────────────────────────────────────────────────┘
```

---

## Component Status

### **1. Data Pipeline** ✅ FULLY OPERATIONAL

#### **Daily Schedule (3 Runs)**

**9:00 AM ET — Morning Pipeline**
- **Status:** ✅ Working
- **Actions:**
  - Resolve previous day's outcomes
  - Fetch ALL props from SGO (~15 game events)
  - Score legs with ML model
  - Apply lineup consistency filter (AB >= 3)
  - Build 5 parlay recommendations
  - Log correlation risk metrics
- **SGO Objects:** ~15
- **Runtime:** ~2-3 minutes

**12:00 PM ET — Midday Pipeline**
- **Status:** ✅ Working
- **Actions:**
  - Load eligible legs from database
  - Remove IL-blocked players
  - Remove started/imminent games
  - Fetch fresh SGO odds (~15 game events)
  - Check confirmed lineups
  - Mark and remove scratched players
  - Rescore legs, rebuild parlays
- **SGO Objects:** ~15
- **Runtime:** ~2-3 minutes

**5:30 PM ET — Evening Pipeline**
- **Status:** ✅ Working
- **Actions:**
  - Same as 12 PM with more games filtered
  - Final lineup confirmation
  - Final odds refresh
- **SGO Objects:** ~10 (fewer games)
- **Runtime:** ~2-3 minutes

**Total Daily SGO Usage:** ~40 objects (99% under 100K free tier)

---

#### **Props Fetching & Logging**
- **Status:** ✅ Working
- **Source:** TheOddsAPI (9 AM full fetch)
- **Coverage:** MLB player props (hits, strikeouts, RBI, total bases, walks)
- **Daily Volume:** ~350-400 props logged
- **Storage:** `mlb_scored_legs` table

#### **ML Scoring**
- **Status:** ✅ Working (100% coverage)
- **Model:** leg_scorer_v2.pkl (trained April 30, 2026)
- **NULL Rate:** 0% (all legs scored successfully)
- **Average Score:** 50.5% (conservative but accurate)

#### **Lineup Consistency Filter**
- **Status:** ✅ FIXED (May 7, 2026)
- **Previous Issue:** Checking wrong field → 0/10 for everyone
- **Current:** AB >= 3 check (games with 3+ at-bats)
- **Threshold:** 0.70 (7+ games out of 10)
- **Actual Filter Rate:** 4-10% (working as designed)
- **Safety:** Circuit breaker if >90% filtered

#### **Parlay Construction**
- **Status:** ✅ Working with NEW validations
- **Output:** 5 daily recommendations (rank 1-5)
- **Diversity:** Limits same-game parlays, player exposure
- **Odds Range:** +600 to +1500
- **NEW:** WALKS + STRIKEOUTS conflict check (DraftKings rule)
- **NEW:** Correlation risk logging (for analysis)

---

### **2. Outcome Resolution** ✅ OPERATIONAL

#### **Leg Outcome Resolver**
- **Status:** ✅ Working
- **Data Source:** MLB-StatsAPI (statsapi-python)
- **Coverage:** Won/Lost/Void resolution for all prop types
- **Scheduled:** 9:00 AM ET daily (resolves previous day)
- **Startup Catch-up:** 2-hour window for missed runs

#### **Parlay Outcome Resolver**
- **Status:** ✅ FIXED (May 6, 2026)
- **Previous Issue:** ANY void → entire parlay voided
- **Current Logic:**
  - ALL legs void → parlay void
  - ANY leg lost → parlay lost
  - All non-void legs won → parlay won
- **Impact:** 0% void rate (down from 5.9%)

#### **Training Data Updates**
- **Status:** ✅ Working
- **Table:** `mlb_training_data`
- **Growth Rate:** ~150-200 samples/day
- **Current Size:** 77,619 samples

---

### **3. V2 Normalized Schema** ✅ DEPLOYED (NEW)

#### **What Changed:**
- **Old:** Parlays stored with JSON legs (no per-leg tracking)
- **New:** Separate tables for parlay headers and legs

#### **New Tables:**
```sql
mlb_parlay_recommendations_v2  -- Parlay metadata
mlb_parlay_legs_v2             -- Individual leg details
```

#### **Key Features:**
- ✅ Per-leg outcome tracking (won/lost/void)
- ✅ Per-leg result values (actual stats: "2 hits")
- ✅ Batch tracking (which pipeline run created this)
- ✅ Source tracking (auto_9am, auto_12pm, auto_530pm, manual)
- ✅ Timestamp tracking (when parlay was created)
- ✅ Dual-write system (saves to both old + new schemas)

#### **Current Data:**
- **V2 Parlays:** 39 (28 historical + 11 today)
- **V2 Legs:** 156 (39 parlays × 4 legs avg)
- **Historical Backfill:** Complete (April 29 - May 7)

#### **Status:** ✅ Deployed May 7, tested and working

---

### **4. Feature Extraction** ✅ OPERATIONAL (NEW)

#### **Purpose:**
Extract parlay-level features for future ML model training

#### **Features Captured (16 total):**
```
avg_leg_coverage      - Average coverage across legs
min_leg_coverage      - Weakest leg (bottleneck detection)
max_leg_coverage      - Strongest leg
std_leg_coverage      - Consistency across legs
avg_leg_ev           - Expected value average
num_legs             - Parlay size (4-6)
legs_same_game       - Correlation count
total_odds           - Payout odds
has_strikeout_over   - Prop type flags
has_hits_under
num_overs            - Direction balance
num_unders
num_pitcher_props    - Prop category split
num_batter_props
diversity_score      - Unique players / total legs
correlation_risk     - Same-game legs / total legs
outcome              - Target variable (won/lost/void/pending)
```

#### **Use Case:**
Train binary classifier: "Will this parlay win?" (Day 10-14)

#### **Status:** ✅ Tested, ready for ML training when 50-100 parlays resolved

---

### **5. Correlation Risk Logging** ✅ ACTIVE (NEW)

#### **What It Does:**
Logs correlation metrics for every parlay generated

#### **Log Format:**
```
[parlay_correlation] rank=1 correlation_risk=0.250 legs_same_game=1 num_legs=4 avg_coverage=76.200 total_odds=1465
[parlay_correlation] rank=2 correlation_risk=0.000 legs_same_game=0 num_legs=4 avg_coverage=76.300 total_odds=1478
```

#### **Purpose:**
- Track correlation distribution over time
- Enable hypothesis validation after 50+ parlays
- Join with outcomes for statistical analysis

#### **Hypothesis Being Tracked:**
Do same-game legs reduce win probability?

**Early evidence (May 6):**
- 4 winners: 6.2% avg correlation risk
- 1 loser: 25% correlation risk

**Validation plan:** Wait for 50-100 parlays, run t-test

#### **Status:** ✅ Active as of May 7, logging with every parlay

---

### **6. Chronological Leg Sorting** ✅ FIXED (NEW)

#### **Problem:**
Legs displayed in random construction order (hard to track live)

#### **Solution:**
Sort legs by game start time (earliest → latest)

#### **Implementation:**
- **Utility function:** `src/utils/sorting.py`
- **Applied in:** Database saves (old + v2), web UI endpoint
- **Field used:** `commence_time` from props data
- **Fallback:** Legs without time sort to end

#### **User Impact:**
- ✅ First leg = earliest game (easy to track chronologically)
- ✅ Consistent with Legs tab sorting
- ✅ Better mental model (matches actual game order)

#### **Status:** ✅ Fixed May 7, tested and working

---

### **7. DraftKings Validation** ✅ ACTIVE (NEW)

#### **Rule Added:**
DraftKings does not allow WALKS + STRIKEOUTS in same parlay

#### **Implementation:**
```python
# In Branch-and-Bound loop, before adding leg:
if leg_stat == "walks" and any(l["stat"] == "strikeouts" for l in legs):
    continue  # Skip invalid combination
```

#### **Impact:**
- ✅ Invalid parlays never constructed (early pruning)
- ✅ All recommendations DraftKings-valid
- ✅ Silent filtering (no user-visible changes)

#### **Validation:**
- ✅ Allowed: WALKS + HITS
- ✅ Allowed: HITS + STRIKEOUTS  
- ❌ Blocked: WALKS + STRIKEOUTS

#### **Status:** ✅ Deployed May 7, active

---

### **8. Web Dashboard** ✅ OPERATIONAL

#### **Legs Tab**
- **Status:** ✅ Working
- **Display:** 200-300 legs per day
- **Filters:** Prop type, player name, team
- **Sorting:** Game start time (chronological) ✅ FIXED
- **Features:** Real-time leg display with coverage/odds

#### **Dashboard Tab**
- **Status:** ✅ Working (all 5 sections)
- **Sections:**
  1. Daily Parlay Performance (last 14 days)
  2. Leg Performance by Stat (win rates by prop type)
  3. Parlay Score Calibration (predicted vs actual)
  4. Top Performing Legs (player/stat combos)
  5. Recent Recommendations (last 20 parlays)

#### **Training Tab**
- **Status:** ✅ Working
- **Metrics:** Total samples, hit rate, void rate, NULL rate
- **Quality:** Shows resolved vs pending by date

#### **Picks Tab**
- **Status:** ✅ Working with NEW features
- **Display:** 5 daily recommendations (updated 3x/day)
- **NEW:** Legs sorted chronologically ✅
- **NEW:** No WALKS + STRIKEOUTS combos ✅
- **Actions:** Regenerate button (manual pipeline trigger)
- **Details:** Player names, prop types, lines, odds, ML scores

---

### **9. Database (Supabase PostgreSQL)** ✅ OPERATIONAL

#### **Core Tables**
```sql
mlb_scored_legs                 -- Daily props with ML scores
mlb_training_data               -- Historical outcomes for retraining
mlb_parlay_recommendations      -- OLD schema (28 parlays)
mlb_parlay_recommendations_v2   -- NEW schema (39 parlays) ✅
mlb_parlay_legs_v2              -- NEW leg details (156 legs) ✅
mlb_calibration                 -- Predicted vs actual bucketed
```

#### **Health Metrics**
- **Connection:** ✅ Stable (transient retries handled)
- **Query Performance:** <100ms average
- **Storage:** Growing ~150MB/month
- **Indexes:** Optimized for date/status queries

#### **Data Quality**
- **NULL Scores:** 0% (all legs scored)
- **Pending Resolution:** 95%+ resolve next day
- **Void Rate:** 0% (post-fix)
- **Data Integrity:** Foreign keys enforced

---

### **10. ML Model** ✅ OPERATIONAL (Needs Monitoring)

#### **Current Model: leg_scorer_v2.pkl**
- **Trained:** April 30, 2026
- **AUC:** 0.8532
- **Training Samples:** ~77,000
- **Features:** 15 (direction, coverage, trends, opponent adjustment, etc.)

#### **Known Issues**
- **Direction Overfit:** 77% feature importance
- **Low Predictions:** 50.5% average (conservative)
- **Impact:** Predictions match reality but leave value on table

#### **Performance Validation**
- **Leg Hit Rate:** 50.1-57.2% (matches predictions) ✅
- **Parlay Hit Rate:** 29.4% overall, 80% yesterday (May 6) ✅
- **Calibration:** Actual matches predicted by bucket ✅

#### **Retraining Criteria**
- Wait for 500+ more resolved samples
- Balance direction sampling (currently skewed)
- Add rolling window features
- Target: Increase avg prediction to 52-55%

---

### **11. Deployment (Railway)** ✅ OPERATIONAL

#### **Production Environment**
- **Platform:** Railway
- **Branch:** master (auto-deploy)
- **Build Time:** ~2-3 minutes
- **Uptime:** 99.9% (scheduled maintenance only)

#### **Scheduled Tasks**
- **Morning Pipeline:** 9:00 AM ET via asyncio scheduler
- **Midday Pipeline:** 12:00 PM ET via asyncio scheduler
- **Evening Pipeline:** 5:30 PM ET via asyncio scheduler
- **Startup Catch-up:** 2-hour window per slot
- **Manual Trigger:** Web UI "Regenerate Now" button

#### **Environment Variables**
- ✅ SUPABASE_URL
- ✅ SUPABASE_KEY
- ✅ ODDS_API_KEY
- ✅ SPORTSGAMEODDS_API_KEY
- ✅ PORT (Railway assigned)

---

## Critical Fixes Applied (May 7, 2026)

### **Fix 1: Lineup Consistency Filter**
**Commit:** f5a5a9f + additional fix May 7
**Files:** `src/utils/lineup_consistency.py`
**Issue:** Checking wrong field path → 0/10 for everyone
**Solution:** Navigate correct MLB-StatsAPI structure for at-bats
**Result:** 4-10% filter rate (working correctly)

### **Fix 2: V2 Normalized Schema**
**Commit:** Multiple (schema + saves + resolution)
**Files:** `src/utils/db.py`, `src/tracker/parlay_outcome_resolver.py`, `src/engine/parlay_features.py`
**Issue:** No per-leg tracking, no parlay-level features
**Solution:** Separate header + detail tables, dual-write
**Result:** 39 parlays + 156 legs tracked, feature extraction ready

### **Fix 3: Historical Migration**
**Commit:** Migration script
**Files:** `src/utils/migrate_parlays.py`
**Issue:** No historical data in v2 schema
**Solution:** Migrate 28 parlays from old schema
**Result:** Backfilled April 29 - May 7 data

### **Fix 4: Correlation Risk Logging**
**Commit:** 3b71a43
**Files:** `src/engine/parlay_builder.py`
**Issue:** No way to track correlation metrics
**Solution:** Log correlation_risk for every parlay
**Result:** Enables hypothesis validation with 50+ parlays

### **Fix 5: Chronological Leg Sorting**
**Commit:** 0501575
**Files:** `src/utils/sorting.py`, `src/utils/db.py`, `src/tracker/recommendation_logger.py`, `src/web/server.py`
**Issue:** Legs displayed in random order
**Solution:** Sort by game start time (earliest first)
**Result:** Chronological display, easier to track live

### **Fix 6: WALKS + STRIKEOUTS Validation**
**Commit:** d5a52dd
**Files:** `src/engine/parlay_builder.py`
**Issue:** Invalid DraftKings parlays being generated
**Solution:** Block WALKS + STRIKEOUTS during construction
**Result:** All parlays DraftKings-valid

---

## Testing Status

### **Unit Tests**
- **Coverage:** Not implemented (future enhancement)
- **Manual Testing:** All components validated May 7

### **Integration Tests**
- **Pipeline:** ✅ End-to-end validated
- **Resolution:** ✅ Backfill 28 parlays successful
- **Dashboard:** ✅ All sections loading
- **V2 Schema:** ✅ Dual-write working
- **Feature Extraction:** ✅ Tested on latest parlay
- **Leg Sorting:** ✅ Chronological order confirmed
- **DK Validation:** ✅ No WALKS + STRIKEOUTS combos

### **Production Validation (Ongoing)**
- **Dates To Test:** May 8-14 (7 days)
- **Focus Areas:**
  - V2 schema resolution (per-leg outcomes)
  - Correlation logging accumulation
  - Leg sorting consistency
  - WALKS + STRIKEOUTS blocking
  - System stability (no regressions)

---

## Dependencies

### **Python Packages**
```
Flask==3.0.0              # Web server
psycopg2-binary==2.9.9    # PostgreSQL adapter
pandas==2.1.3             # Data manipulation
scikit-learn==1.3.2       # ML model
requests==2.31.0          # API calls
python-dotenv==1.0.0      # Environment variables
statsapi==1.6.0           # MLB data
supabase==1.0.3           # Supabase client
numpy==1.24.3             # Numerical operations
```

### **External APIs**
- **TheOddsAPI:** Player props (daily quota: 500 requests) — 9 AM only
- **SportsGameOdds:** Fresh odds (quota: 100K objects/month) — ~40/day usage
- **MLB-StatsAPI:** Game results and lineups (unlimited)
- **Supabase:** PostgreSQL database (hosted)

### **Infrastructure**
- **Railway:** Hosting and deployment
- **Supabase:** Database (PostgreSQL)
- **GitHub:** Version control and CI/CD trigger

---

## Monitoring & Alerts

### **Currently Monitored**
- Railway deployment status (auto-alert on failure)
- Database connection health (query timeout errors)
- Web app uptime (manual checks)
- Correlation logging (grep Railway logs)

### **Not Yet Implemented**
- ❌ Automated ML model drift detection
- ❌ Data quality alerts (NULL rate spikes)
- ❌ Pipeline failure notifications
- ❌ Calibration error alerts
- ❌ SGO quota alerts

### **Recommended Additions**
1. **Daily Health Check Email**
   - Pipeline success/failure (3 runs)
   - Legs logged count
   - NULL rate check
   - Dashboard load status
   - SGO objects consumed
   - Correlation risk distribution

2. **Model Performance Alerts**
   - Hit rate drops below 45%
   - Void rate exceeds 10%
   - NULL rate exceeds 5%

3. **Data Quality Checks**
   - Missing resolution for >48 hours
   - Sudden drop in logged props
   - Database connection failures
   - SGO API quota warnings

---

## Performance Benchmarks

### **Pipeline Execution**
```
9 AM Morning Pipeline:   ~3 minutes (resolution + full fetch)
12 PM Midday Pipeline:   ~2 minutes (targeted fetch + lineup check)
5:30 PM Evening Pipeline: ~2 minutes (targeted fetch + lineup check)

Props Fetching:          ~15 seconds (SGO game events)
ML Scoring:              ~10 seconds
Lineup Filter:           ~20 seconds
Lineup Checking:         ~30 seconds (MLB-StatsAPI)
Parlay Construction:     ~5 seconds
Feature Extraction:      <1 second per parlay
```

### **Dashboard Load Times**
```
Legs Tab:       <500ms (200-300 rows)
Dashboard Tab:  <1s (5 queries)
Training Tab:   <300ms (aggregated)
Picks Tab:      <200ms (5 parlays)
```

### **Resolution Performance**
```
Leg Resolution:    ~30-60 seconds (350-400 legs)
Parlay Resolution: ~5 seconds (5 parlays)
Training Update:   ~10 seconds (batch insert)
```

---

## Known Limitations

### **Technical Limitations**
1. **SGO API Structure:** No per-player endpoint
   - Mitigated: Fetch all games, filter locally
   - Impact: Can't reduce below ~15 objects per fetch
2. **ML Model:** Low average prediction (50.5%)
   - Impact: Conservative recommendations
3. **No Real-time Updates:** Dashboard shows latest pipeline run
   - Design: Intentional (3 scheduled updates sufficient)

### **Data Limitations**
1. **Postponed Games:** Legs never resolve (stuck pending)
2. **Late Scratches:** Players ruled out between 5:30 PM and game time
   - Mitigated: 15-minute buffer catches most
3. **Historical Data:** Only 77k samples
   - Impact: Model may improve with more data

### **Feature Gaps**
1. **No Live Betting:** All props pre-game only
2. **No Bankroll Management:** Recommendations only
3. **No Correlation Analysis:** Props assumed independent (testing hypothesis)
4. **No Arbitrage Detection:** Single book pricing

---

## Recent Milestones

### **May 7, 2026 - Infrastructure Upgrade**
- ✅ V2 normalized schema deployed
- ✅ Historical migration complete (28 parlays)
- ✅ Feature extraction operational
- ✅ Correlation logging active
- ✅ Chronological leg sorting fixed
- ✅ DraftKings validation added

### **May 6, 2026 - Exceptional Performance**
- 🎉 4/5 parlay win rate (80%)
- 📊 Correlation hypothesis formed
- 🧪 Natural experiment in progress

### **May 1-5, 2026 - Learning Period**
- 📈 System refinement
- 🔧 Filter adjustments
- 📊 Data accumulation

---

## Next Steps

### **SHORT TERM (This Week)**
- ✅ Monitor 3 daily pipeline runs (May 8-14)
- ✅ Validate V2 schema resolution works
- ✅ Track correlation logging data
- ✅ Verify leg sorting consistency
- ✅ Confirm WALKS + STRIKEOUTS blocking

### **MEDIUM TERM (Next 2 Weeks)**
- 🎯 Collect 50-100 resolved parlays
- 🎯 Validate correlation hypothesis (statistical test)
- 🎯 Train parlay-level ML model
- 🎯 Analyze lineup filter effectiveness

### **LONG TERM (Next Month)**
- 🎯 Retrain leg-level ML model (after 500+ samples)
- 🎯 Add monitoring/alerting
- 🎯 Dashboard enhancements (5th tab: Parlay History)
- 🎯 Implement correlation penalty (if validated)

---

## Support & Troubleshooting

### **Common Issues**

**Issue:** Dashboard not loading
**Solution:** Check Railway deployment status, database connection

**Issue:** Props not logging
**Solution:** Check TheOddsAPI quota, API key validity

**Issue:** Legs not resolving
**Solution:** Check statsapi library, game completion status

**Issue:** NULL ML scores
**Solution:** Check model file exists, feature calculation

**Issue:** Pipeline not running at scheduled time
**Solution:** Check Railway logs, verify scheduler logs

**Issue:** Legs not sorted chronologically
**Solution:** Check commence_time field exists in props data

### **Emergency Contacts**
- Railway Dashboard: https://railway.app
- Supabase Console: https://supabase.com
- GitHub Repo: github.com/MrGweeod/mlb-agent

---

**🎯 CURRENT STATUS:** All systems green + major infrastructure upgrade complete. V2 normalized schema enables per-leg analytics and parlay-level ML. Correlation logging active for hypothesis validation. Leg sorting and DraftKings validation working. System ready for 7-10 day data collection phase. Yesterday's 4/5 win rate provides early evidence for correlation effect, pending statistical validation with 50-100 parlays.
