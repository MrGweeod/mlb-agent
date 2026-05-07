# MLB Parlay Agent — Session Handoff
**Last Updated:** May 7, 2026 (End of Day - Major Schema Upgrade & Validation Framework Complete)

## Current Status
✅ **ALL SYSTEMS OPERATIONAL + MAJOR UPGRADES COMPLETE**
- ✅ Lineup consistency filter fixed (AB >= 3 check working)
- ✅ V2 normalized parlay schema deployed and tested
- ✅ Historical migration complete (28 parlays backfilled)
- ✅ Feature extraction operational (16 parlay-level features)
- ✅ Correlation risk logging active (for hypothesis validation)
- ✅ Chronological leg sorting implemented
- ✅ WALKS + STRIKEOUTS conflict check added
- 🎯 **System ready for 7-10 day data collection phase**

---

## What Was Accomplished Today (May 7, 2026)

### **MAJOR ACHIEVEMENT 1: V2 Normalized Parlay Schema**

#### **Problem Solved:**
- Old schema stored parlays with JSON legs (no per-leg analytics)
- Couldn't answer: "Does Cody Bellinger hit under win more often?"
- Couldn't extract parlay-level features for ML model

#### **Solution Implemented:**
**New normalized schema with two tables:**

```sql
-- Parlay header table
CREATE TABLE mlb_parlay_recommendations_v2 (
    id BIGSERIAL PRIMARY KEY,
    run_date DATE NOT NULL,
    rank SMALLINT NOT NULL,
    total_odds NUMERIC(8,3),
    avg_coverage NUMERIC(6,3),
    num_legs SMALLINT NOT NULL,
    outcome VARCHAR(10) NOT NULL DEFAULT 'pending',
    source VARCHAR(30),  -- auto_9am, auto_12pm, auto_530pm, manual
    batch_id VARCHAR(60),
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- Parlay leg detail table
CREATE TABLE mlb_parlay_legs_v2 (
    id BIGSERIAL PRIMARY KEY,
    parlay_id BIGINT NOT NULL REFERENCES mlb_parlay_recommendations_v2(id),
    player_id INTEGER,
    player_name VARCHAR(100),
    team VARCHAR(10),
    stat VARCHAR(40),
    line NUMERIC(6,2),
    direction VARCHAR(10),
    odds VARCHAR(10),
    composite_score NUMERIC(7,4),
    coverage NUMERIC(6,3),
    ev NUMERIC(7,4),
    game_id INTEGER,
    outcome VARCHAR(10) NOT NULL DEFAULT 'pending',
    result_value NUMERIC(8,2),
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
```

**Impact:**
- ✅ Per-leg outcome tracking
- ✅ Player/stat hit rate analysis
- ✅ Parlay-level feature extraction
- ✅ All recommendations logged (not just top 5)
- ✅ Dual-write system (old + new schemas)

**Status:** ✅ Deployed, tested with 39 parlays + 156 legs

---

### **MAJOR ACHIEVEMENT 2: Historical Migration**

**Migrated:** 28 historical parlays (April 29 - May 7)
**Hydrated:** 59 unique legs from `mlb_scored_legs`
**Outcomes preserved:** Won/lost/void/pending

**Key Historical Data:**
- **May 6 (Yesterday):** 4 wins, 1 loss (80% hit rate!) 🔥
- **May 7 (Today):** 11 parlays pending (testing correlation hypothesis)
- **April 29 - May 5:** 13 parlays (mostly losses, learning period)

**Status:** ✅ Complete, ready for analysis

---

### **MAJOR ACHIEVEMENT 3: Feature Extraction for ML Model**

**Built:** 16 parlay-level features for future ML model training

**Features captured:**
```python
{
    'avg_leg_coverage': 76.250,      # Average coverage across legs
    'min_leg_coverage': 65.500,      # Weakest leg (potential bottleneck)
    'max_leg_coverage': 87.900,      # Strongest leg
    'std_leg_coverage': 8.013,       # Consistency (low = better)
    'avg_leg_ev': -0.031,            # Expected value average
    'num_legs': 4,                   # Parlay size
    'legs_same_game': 1,             # Correlation count
    'total_odds': 1471,              # Payout odds
    'has_strikeout_over': 1,         # Prop type flags
    'has_hits_under': 1,
    'num_overs': 2,
    'num_unders': 2,
    'num_pitcher_props': 2,
    'num_batter_props': 2,
    'diversity_score': 1.0,          # Unique players / total legs
    'correlation_risk': 0.25,        # Same-game legs / total legs
    'outcome': 'pending'             # Target variable for ML
}
```

**Use case:** Train binary classifier "Will this parlay win?" when 50-100 parlays resolved

**Status:** ✅ Working, tested on latest parlay

---

### **MAJOR ACHIEVEMENT 4: Correlation Hypothesis Formation**

#### **Observation from May 6 (4/5 Win):**

**Winners (4 parlays):**
- Average correlation risk: **6.2%**
- Legs same game: 0-1 (mostly zero)

**Loser (1 parlay):**
- Correlation risk: **25%**
- Legs same game: 1

#### **Today's Test (May 7 - 11 parlays):**
- Zero-correlation parlays: 5 (0% risk)
- High-correlation parlays: 6 (25% risk each)

**Hypothesis:** Same-game legs reduce win probability due to correlation

**Validation plan:** 
- ⏳ Wait for 50-100 resolved parlays
- ⏳ Run statistical significance test (t-test, p < 0.05)
- ⏳ Only implement changes if validated

**Status:** 🧪 Observational (NOT actionable yet, need more data)

---

### **ACHIEVEMENT 5: Lineup Consistency Filter - FIXED**

#### **Problem:**
Filter was returning `0/10 games with 3+ AB = 0.000` for every player

#### **Root Cause:**
MLB-StatsAPI returns at-bats in nested structure, not top-level `ab` field

#### **Fix Applied:**
```python
# Navigate correct path to at-bats field
ab = game_log.get('stat', {}).get('batting', {}).get('atBats', 0)
qualified = sum(1 for g in recent if get_ab(g) >= 3)
```

**Impact:**
- ✅ Now shows realistic ratios (0.800, 1.000 for regular starters)
- ✅ Filters 4-10% of legs (bench/platoon players removed)
- ✅ Circuit breaker working (disables if >90% filtered)

**Status:** ✅ Fixed and validated in production

---

### **ACHIEVEMENT 6: Correlation Risk Logging**

**Added logging to track correlation metrics:**

```python
[parlay_correlation] rank=1 correlation_risk=0.250 legs_same_game=1 num_legs=4 avg_coverage=76.200 total_odds=1465
[parlay_correlation] rank=2 correlation_risk=0.000 legs_same_game=0 num_legs=4 avg_coverage=76.300 total_odds=1478
```

**Purpose:** Enable post-hoc analysis after 50+ parlays resolve

**Grep-friendly format:** Easy to extract and join with outcomes

**Status:** ✅ Active, logging with every parlay generation

---

### **ACHIEVEMENT 7: Chronological Leg Sorting**

**Problem:** Legs displayed in random construction order

**Solution:** Sort by game start time (earliest first)

**Implementation:**
```python
def sort_legs_by_game_time(legs):
    """Sort parlay legs by game start time."""
    # Uses commence_time field from props data
    # Handles missing times (sorts to end)
    # Works across old + new schemas
```

**Applied in:**
- Database saves (old + v2 schemas)
- Web UI endpoint (before display)

**Status:** ✅ Deployed and working

---

### **ACHIEVEMENT 8: WALKS + STRIKEOUTS Conflict Check**

**Problem:** DraftKings doesn't allow WALKS + STRIKEOUTS in same parlay (correlation rule)

**Solution:** Added validation during parlay construction

**Implementation:**
```python
# In Branch-and-Bound loop, before adding leg:
if leg_stat == "walks" and any(l["stat"] == "strikeouts" for l in legs):
    continue  # Skip invalid combination
if leg_stat == "strikeouts" and any(l["stat"] == "walks" for l in legs):
    continue  # Skip invalid combination
```

**Impact:**
- ✅ Invalid parlays never constructed (early pruning)
- ✅ All recommendations DraftKings-valid
- ✅ No user-visible changes (silent filtering)

**Status:** ✅ Deployed and active

---

## Current System Metrics

### **Production Performance (May 4-7)**
```
Total Parlays Recommended: 39
Resolved: 17 (44%)
Won: 5 (29.4% hit rate) 🔥 (includes yesterday's 4/5)
Lost: 12 (70.6%)
Void: 0 (0% - fixed!)
Pending: 22 (today's 11 + others)
```

### **Yesterday's Extraordinary Performance (May 6)**
```
Parlays: 5
Won: 4 (80% hit rate!) 🎉
Lost: 1 (20%)
```

**Observed pattern:**
- 4 winners had low correlation risk (0-6.2%)
- 1 loser had high correlation risk (25%)

### **Leg Performance (Last 7 Days)**
```
Stat Type          Total   Won    Hit%    Void%
─────────────────────────────────────────────────
Strikeouts          402    230    57.2%   0%
Hits                871    436    50.1%   2.3%
RBI                  48     24    50.0%   4.2%
Total Bases          75     37    49.3%   5.3%
Walks                59     28    47.5%   3.4%
```

### **ML Model Status**
- **Model:** leg_scorer_v2.pkl (trained April 30, 2026)
- **AUC:** 0.8532
- **Average Prediction:** 50.5%
- **Known Issues:** Direction overfit (77% feature importance)

### **Today's Parlays (May 7)**
```
Total generated: 11
Zero-correlation: 5 (45%)
High-correlation: 6 (55%)
Average coverage: 76.15% - 76.53% (highest ever!)
```

**Natural experiment:** Will resolve tomorrow, test correlation hypothesis

---

## Infrastructure Status

### **Railway Deployment**
- ✅ Live at production URL
- ✅ Auto-deploys from master branch
- ✅ Three daily scheduled pipelines active:
  - 9:00 AM ET (resolution + full fetch)
  - 12:00 PM ET (targeted refresh + lineup check)
  - 5:30 PM ET (final refresh + lineup check)
- ✅ Startup catch-up resolution (2-hour window per slot)

### **Database (Supabase PostgreSQL)**
```
Table                          Rows        Status
───────────────────────────────────────────────────────
mlb_scored_legs                ~2,500      ✅ Active
mlb_training_data              77,619      ✅ Growing
mlb_parlay_recommendations     28          ✅ Active (old)
mlb_parlay_recommendations_v2  39          ✅ Active (new)
mlb_parlay_legs_v2             156         ✅ Active (new)
mlb_calibration                Aggregated  ✅ Active
```

### **Web App**
- ✅ All 4 tabs functional
- ✅ Legs tab: Real-time leg display (sorted by game time)
- ✅ Dashboard: 5 sections loading
- ✅ Training: Data quality monitoring
- ✅ Picks: 5 daily recommendations (legs sorted chronologically)

### **Scheduled Tasks**
- ✅ Morning pipeline: 9:00 AM ET (daily)
- ✅ Midday pipeline: 12:00 PM ET (daily)
- ✅ Evening pipeline: 5:30 PM ET (daily)
- ✅ Startup catch-up: Active (2-hour window per slot)

---

## Git History (May 7, 2026)

| Commit | Description | Files |
|--------|-------------|-------|
| d5a52dd | feat: add WALKS + STRIKEOUTS conflict check | parlay_builder.py |
| 0501575 | feat: sort parlay legs by game start time | sorting.py, db.py, recommendation_logger.py, server.py |
| 3b71a43 | feat: add correlation risk logging | parlay_builder.py |
| f5a5a9f | fix: lineup consistency filter (AB >= 3 check) | lineup_consistency.py |
| [previous] | feat: deploy v2 normalized parlay schema | db.py, parlay_outcome_resolver.py |
| [previous] | feat: add feature extraction for parlay ML | parlay_features.py |
| [previous] | feat: add historical migration script | migrate_parlays.py |

**Branch:** master
**Remote:** origin/master
**Status:** ✅ All changes pushed and deployed

---

## Outstanding Items

### **NONE - All Critical Issues Resolved** ✅

**Previously Critical (Now Fixed):**
- ✅ Lineup consistency filter (now works correctly)
- ✅ V2 schema deployed (per-leg tracking active)
- ✅ Historical migration (28 parlays backfilled)
- ✅ Leg sorting (chronological order working)
- ✅ DraftKings validation (WALKS + STRIKEOUTS blocked)

### **LOW PRIORITY (Monitoring Phase)**

1. **Data Collection (Next 7 Days)**
   - Accumulate 50-100 resolved parlays
   - Track correlation risk via logs
   - Monitor system health (no intervention)

2. **Hypothesis Validation (Day 10-14)**
   - Statistical test: Does correlation predict losses?
   - T-test on zero-correlation vs high-correlation groups
   - Only implement changes if p < 0.05

3. **ML Model Retraining (Day 10-14)**
   - Current model: 50.5% avg prediction (conservative)
   - Wait for 500+ more resolved samples
   - Retrain with balanced direction sampling

4. **Parlay-Level ML Model (Day 10-14)**
   - Train when 50-100 parlays resolved
   - Features: correlation, coverage distribution, diversity
   - Target: Predict "Will this parlay win?"

5. **Dashboard Enhancements (Nice to Have)**
   - Add 5th tab: Parlay History (expandable legs)
   - Add charts/visualizations
   - Parlay diversity analysis

---

## Key Metrics to Track (Next 7 Days)

### **Daily Pipeline Metrics**
- **9 AM props logged:** ~350-400 (baseline)
- **12 PM odds updates:** ~200 legs (track update rate)
- **5:30 PM odds updates:** ~150 legs (track update rate)
- **Correlation logging:** Track parlays by risk level
- **WALKS + STRIKEOUTS rejections:** Monitor for conflicts

### **SGO API Metrics**
- **Objects per run:** 9 AM = 15, 12 PM = 15, 5:30 PM = 10
- **Daily total:** ~40 objects (target: maintain)
- **Monthly projected:** ~1,200 objects (target: stay under 100K)

### **Parlay Quality Metrics**
- **Average coverage:** Track trend (currently 76%)
- **Correlation risk:** Track distribution (0% vs 25%)
- **Void rate:** Maintain <2%
- **Hit rate:** Track overall (currently ~29%)

### **System Health Metrics**
- **Pipeline runtime:** <3 min per run
- **Database query time:** <100ms
- **Error rate:** 0 (maintain)
- **Uptime:** 99%+

---

## Common Operations

### **Check System Health**
```bash
# Railway logs
https://railway.app → mlb-agent → Deployments → View Logs

# Database queries
Supabase → SQL Editor → Run custom queries

# Web app
https://[your-railway-url].up.railway.app
```

### **Monitor Pipeline Runs**
```bash
# Check correlation logging
grep "\[parlay_correlation\]" railway.log

# Check WALKS + STRIKEOUTS conflicts (no explicit logging, silent pruning)
# Verify by checking final parlays don't have both

# Check lineup filter performance
grep "\[lineup_consistency\]" railway.log
```

### **Extract Correlation Data (After 7 Days)**
```bash
# Download logs
railway logs > parlay_logs.txt

# Extract correlation metrics
grep "\[parlay_correlation\]" parlay_logs.txt > correlation_data.csv

# Join with outcomes from database
# Run statistical analysis
```

---

## Success Criteria (Next 7 Days)

### **Performance Goals**
- ✅ Pipeline runs successfully 3x/day (9 AM / 12 PM / 5:30 PM)
- ✅ Dashboard loads without errors
- ✅ Legs tab shows 200-300 legs daily
- ✅ Picks tab generates 5 parlays 3x/day
- ✅ Legs display in chronological order
- ✅ No WALKS + STRIKEOUTS parlays generated

### **Data Quality Goals**
- ✅ 0% NULL composite_scores maintained
- ✅ Fresh odds at 12 PM and 5:30 PM
- ✅ Correlation risk logged for all parlays
- ✅ SGO usage stays under 50 objects/day
- ✅ Void rate <2%

### **Validation Goals (After 7 Days)**
- 🎯 50-100 resolved parlays for statistical tests
- 🎯 Correlation hypothesis validated (or rejected)
- 🎯 Parlay-level ML model trained (if data sufficient)
- 🎯 System stability maintained (no regressions)

---

## Next Session Priorities

### **IMMEDIATE (Tomorrow Morning - May 8)**
1. **Validate Resolution Works with V2 Schema**
   - Check today's 11 parlays resolve correctly
   - Verify per-leg outcomes populate
   - Confirm parlay outcomes computed correctly

2. **Monitor New Features**
   - Verify legs display chronologically in UI
   - Confirm no WALKS + STRIKEOUTS parlays exist
   - Check correlation logging appears in Railway logs

### **SHORT TERM (Next 7 Days)**
3. **Data Collection Phase**
   - No code changes (let system accumulate data)
   - Monitor daily pipeline runs
   - Track correlation risk distribution
   - Ensure 50-100 parlays resolve

### **MEDIUM TERM (Day 10-14)**
4. **Statistical Validation**
   - Extract correlation data from logs
   - Join with v2 parlay outcomes
   - Run t-test: zero-correlation vs high-correlation win rates
   - Determine if correlation effect is real (p < 0.05)

5. **Parlay-Level ML Model**
   - Extract features for 50-100 parlays
   - Train binary classifier
   - Evaluate vs baseline (bet all parlays >75% avg coverage)
   - Integrate if model beats baseline

### **LOW PRIORITY (Ongoing)**
6. **Dashboard Enhancements**
   - Build 5th tab: Parlay History (expandable legs view)
   - Add visualizations for trends
   - Real-time calibration tracking

---

## Contact & Resources

### **Key Files**
- `SESSION_HANDOFF.md` - This document
- `BUILD_STATUS.md` - Component health status
- `ARCHITECTURE_DECISIONS.md` - Design rationale
- `PROJECT_INSTRUCTIONS_v2.md` - Setup and usage guide

### **Monitoring**
- Railway Dashboard: https://railway.app
- Supabase Console: https://supabase.com
- Web App: [Railway deployment URL]

### **Support**
- All critical issues resolved as of May 7, 2026
- System stable and in data collection phase
- Next check-in: May 14, 2026 (after 7 days of validation data)

---

**🎯 BOTTOM LINE:** Major infrastructure upgrade complete. V2 normalized schema enables per-leg tracking and parlay-level ML. System now collecting validation data for correlation hypothesis. Yesterday's 4/5 win rate (80%) provides early evidence for correlation effect, but requires 50-100 parlays for statistical validation. All systems green, ready for 7-day data accumulation phase.
