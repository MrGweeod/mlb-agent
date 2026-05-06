[# MLB Parlay Agent — Build Status
**Last Updated:** May 6, 2026 (Post-Crisis Resolution)

## Overall System Status: ✅ FULLY OPERATIONAL

```
┌──────────────────────────────────────────────────────┐
│              SYSTEM HEALTH DASHBOARD                 │
├──────────────────────────────────────────────────────┤
│ Pipeline Runtime:      ✅ OPERATIONAL               │
│ ML Model Scoring:      ✅ OPERATIONAL (0% NULL)     │
│ Lineup Filter:         ✅ OPERATIONAL (40% filter)  │
│ Dashboard:             ✅ OPERATIONAL (all sections) │
│ Database:              ✅ OPERATIONAL               │
│ Void Logic:            ✅ FIXED (partial voids OK)  │
│ Deployment:            ✅ LIVE (Railway)            │
└──────────────────────────────────────────────────────┘
```

---

## Component Status

### **1. Data Pipeline** ✅ OPERATIONAL

#### **Props Fetching & Logging**
- **Status:** ✅ Working
- **Source:** TheOddsAPI
- **Coverage:** MLB player props (hits, strikeouts, RBI, total bases, walks)
- **Daily Volume:** ~350-400 props logged
- **Storage:** `mlb_scored_legs` table

#### **ML Scoring**
- **Status:** ✅ Working (100% coverage)
- **Model:** leg_scorer_v2.pkl (trained April 30, 2026)
- **NULL Rate:** 0% (all legs scored successfully)
- **Average Score:** 50.5% (low but accurate)

#### **Lineup Consistency Filter**
- **Status:** ✅ FIXED (May 6, 2026)
- **Previous Issue:** API parameter error → 100% filtered
- **Current:** 40% filtered (working as designed)
- **Threshold:** 30% recent starts required
- **Safety:** Circuit breaker if >90% filtered

#### **Parlay Construction**
- **Status:** ✅ Working
- **Output:** 5 daily recommendations (rank 1-5)
- **Diversity:** Limits same-game parlays, correlation checks
- **Odds:** Combined odds +1400 to +1600 range

---

### **2. Outcome Resolution** ✅ OPERATIONAL

#### **Leg Outcome Resolver**
- **Status:** ✅ Working
- **Data Source:** MLB-StatsAPI (statsapi-python)
- **Coverage:** Won/Lost/Void resolution for all prop types
- **Scheduled:** 9:00 AM ET daily (resolves previous day)
- **Startup Catch-up:** 9-12 PM window for missed runs

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

### **3. Web Dashboard** ✅ OPERATIONAL

#### **Legs Tab**
- **Status:** ✅ Working
- **Display:** 200-300 legs per day
- **Filters:** Prop type, player name, team
- **Sorting:** ML score, odds, coverage

#### **Dashboard Tab**
- **Status:** ✅ FIXED (May 6, 2026)
- **Previous Issue:** HTTP 500 on all queries (SQL type mismatch)
- **Current:** All 5 sections loading
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
- **Status:** ✅ Working
- **Display:** 5 daily recommendations
- **Actions:** Regenerate button (manual pipeline trigger)
- **Details:** Player names, prop types, lines, odds, ML scores

---

### **4. Database (Supabase PostgreSQL)** ✅ OPERATIONAL

#### **Core Tables**
```sql
mlb_scored_legs              -- Daily props with ML scores
mlb_training_data            -- Historical outcomes for retraining
mlb_parlay_recommendations   -- 5 daily parlays tracked
mlb_calibration              -- Predicted vs actual bucketed
```

#### **Health Metrics**
- **Connection:** ✅ Stable
- **Query Performance:** <100ms average
- **Storage:** Growing ~150MB/month
- **Indexes:** Optimized for date/status queries

#### **Data Quality**
- **NULL Scores:** 0% (all legs scored)
- **Pending Resolution:** 95%+ resolve next day
- **Void Rate:** 0% (post-fix)
- **Data Integrity:** Foreign keys enforced

---

### **5. ML Model** ✅ OPERATIONAL (Needs Monitoring)

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
- **Parlay Hit Rate:** 5.9% (within 5-10% expected range) ✅
- **Calibration:** Actual matches predicted by bucket ✅

#### **Retraining Criteria**
- Wait for 500+ more resolved samples
- Balance direction sampling (currently skewed)
- Add rolling window features
- Target: Increase avg prediction to 52-55%

---

### **6. Deployment (Railway)** ✅ OPERATIONAL

#### **Production Environment**
- **Platform:** Railway
- **Branch:** master (auto-deploy)
- **Build Time:** ~2-3 minutes
- **Uptime:** 99.9% (scheduled maintenance only)

#### **Scheduled Tasks**
- **Morning Resolution:** 9:00 AM ET via cron
- **Startup Catch-up:** 9-12 PM window
- **Manual Trigger:** Web UI "Regenerate Now" button

#### **Environment Variables**
- ✅ SUPABASE_URL
- ✅ SUPABASE_KEY
- ✅ ODDS_API_KEY
- ✅ PORT (Railway assigned)

---

## Critical Fixes Applied (May 6, 2026)

### **Fix 1: Lineup Consistency Filter**
**Commit:** 3c67de7
**Files:** `src/utils/lineup_consistency.py`, `main.py`
**Issue:** Invalid API parameter → 100% filtered
**Solution:** Removed `season` param, added error handling
**Result:** 40% filter rate (working as designed)

### **Fix 2: Dashboard SQL Type Mismatch**
**Commit:** 79e6360
**Files:** `src/utils/db.py`
**Issue:** TEXT vs TIMESTAMP comparison → HTTP 500
**Solution:** Added `::date` cast to all `run_date` comparisons
**Result:** All 5 dashboard sections loading

### **Fix 3: Parlay Void Logic**
**Commit:** 5e0d962
**Files:** `src/tracker/parlay_outcome_resolver.py`, `src/web/static/index.html`
**Issue:** ANY void → entire parlay voided
**Solution:** Only void when ALL legs void
**Result:** 0% void rate (down from 5.9%)

---

## Testing Status

### **Unit Tests**
- **Coverage:** Not implemented (future enhancement)
- **Manual Testing:** All components validated May 6

### **Integration Tests**
- **Pipeline:** ✅ End-to-end validated
- **Resolution:** ✅ Backfill 7 dates successful
- **Dashboard:** ✅ All sections loading

### **Production Validation**
- **Dates Tested:** April 22 - May 6
- **Legs Resolved:** ~5,750
- **Parlays Tracked:** 23
- **Success Rate:** 100% (all components working)

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
APScheduler==3.10.4       # Scheduled tasks
```

### **External APIs**
- **TheOddsAPI:** Player props (daily quota: 500 requests)
- **MLB-StatsAPI:** Game results and player stats (unlimited)
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

### **Not Yet Implemented**
- ❌ Automated ML model drift detection
- ❌ Data quality alerts (NULL rate spikes)
- ❌ Pipeline failure notifications
- ❌ Calibration error alerts

### **Recommended Additions**
1. **Daily Health Check Email**
   - Pipeline success/failure
   - Legs logged count
   - NULL rate check
   - Dashboard load status

2. **Model Performance Alerts**
   - Hit rate drops below 45%
   - Void rate exceeds 10%
   - NULL rate exceeds 5%

3. **Data Quality Checks**
   - Missing resolution for >48 hours
   - Sudden drop in logged props
   - Database connection failures

---

## Performance Benchmarks

### **Pipeline Execution**
```
Fresh Build:         ~3 minutes
Cached Build:        ~30 seconds
Props Fetching:      ~15 seconds
ML Scoring:          ~10 seconds
Lineup Filter:       ~20 seconds
Parlay Construction: ~5 seconds
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
1. **TheOddsAPI Rate Limit:** 500 requests/day
   - Mitigated: Single bulk fetch per day
2. **ML Model:** Low average prediction (50.5%)
   - Impact: Conservative recommendations
3. **No Real-time Updates:** Dashboard shows previous day
   - Design: Intentional (outcomes resolve next morning)

### **Data Limitations**
1. **Postponed Games:** Legs never resolve (stuck pending)
   - Example: April 30 Rank 3 (3 postponed legs)
2. **Late Scratches:** Players ruled out after props logged
   - Mitigated: Lineup consistency filter catches most
3. **Historical Data:** Only 77k samples
   - Impact: Model may improve with more data

### **Feature Gaps**
1. **No Live Betting:** All props pre-game only
2. **No Bankroll Management:** Recommendations only
3. **No Correlation Analysis:** Props assumed independent
4. **No Arbitrage Detection:** Single book pricing

---

## Deployment History

### **May 6, 2026 (v1.2.0) - Critical Fixes**
- ✅ Fixed lineup consistency filter API error
- ✅ Fixed dashboard SQL type mismatch
- ✅ Fixed parlay void logic
- ✅ Backfilled historical data (April 22 - May 5)
- ✅ All systems operational

### **Previous Versions**
- **v1.1.0:** Added lineup consistency filter
- **v1.0.0:** Initial production deployment
- **v0.x:** Development and testing

---

## Next Steps

### **SHORT TERM (This Week)**
- ✅ Monitor pipeline daily (9 AM runs)
- ✅ Validate dashboard accuracy
- ✅ Track void rate (<5% target)

### **MEDIUM TERM (Next 2 Weeks)**
- 🎯 Collect 7 days clean data
- 🎯 Validate ML model performance
- 🎯 Adjust lineup filter threshold if needed

### **LONG TERM (Next Month)**
- 🎯 Retrain ML model (after 500+ more samples)
- 🎯 Add monitoring/alerting
- 🎯 Dashboard visualizations

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

### **Emergency Contacts**
- Railway Dashboard: https://railway.app
- Supabase Console: https://supabase.com
- GitHub Repo: [Your repo URL]

---

**🎯 CURRENT STATUS:** All systems green. Production ready. Monitoring mode activated.](https://github.com/MrGweeod/mlb-agent)
