# MLB Parlay Agent — Build Status

**Last Updated:** 2026-04-27
**Blueprint Version:** v1.0
**Repo:** github.com/MrGweeod/mlb-agent

## Infrastructure Status
| Component | Status | Notes |
|-----------|--------|-------|
| Railway Deployment | ✅ Running | Production pipeline 3×/day + web app |
| Discord Bot | ✅ Connected | Scheduled runs: 9AM/12PM/5:30PM ET |
| Web App | ✅ Fully Functional | https://mlb-agent.up.railway.app/ |
| Supabase PostgreSQL | ✅ Live | mlb_scored_legs, mlb_training_data tables |

## Build Progress

### ✅ Phase 1 — Direct NBA Agent Copies (Complete)
All modules copied and working.

### ✅ Phase 2 — MLB Adaptations (Complete)
All modules adapted for MLB including pitcher K props (Poisson model).

### ✅ Phase 3 — New Modules (Complete)
All modules built and deployed.

### ✅ Phase 4 — ML Training Data Collection (Complete - April 27)
- **Historical backfill:** 66,174 resolved samples (March 28 - April 22)
- **Gap fill:** 2,053 samples (April 23-27)
- **Prospective collection:** ✅ DEPLOYED — logs ~150-200 props daily automatically
- **Outcome resolver:** ✅ EXTENDED — resolves both mlb_scored_legs and mlb_training_data
- **Database:** mlb_training_data table fully populated (76,000+ rows)
- **Date coverage:** March 28 - April 27, 2026 (31 days continuous)

### ✅ Phase 5 — ML Model Training (Complete - April 24)
- Gradient boosting classifier trained on 49,222 samples
- ROC AUC: 0.8648 (target was 0.60+)
- Model saved: models/leg_scorer_v1.pkl
- Ready for A/B testing vs heuristic scoring

### ✅ Phase 5.5 — Training Data Analytics (Complete - April 27)
- **SQL views:** 4 views for ad-hoc analysis in Supabase
- **Health check script:** Automated monitoring with daily alerts
- **Web app tab:** Live analytics dashboard with 5 sections
- **Pipeline integration:** Health check runs after every 12PM pipeline

## Production Pipeline Status

### ✅ Core Pipeline (Enhanced - April 27)
- 8-step daily pipeline (9AM/12PM/5:30PM ET)
- SGO props fetch (MLB-specific)
- Coverage calculation with handedness splits
- Pitcher K props via Poisson model
- Composite leg scoring (coverage 70%, opponent 20%, stability 10%)
- **Smart parlay filter (April 24):** Blocks poison overs, max 1 risky over
- **Coverage threshold raised (April 27):** 60% minimum (was 55%)
- Branch-and-Bound parlay builder
- Automated outcome resolution
- **Prospective training data logging (April 27):** All scored legs logged automatically
- **Health check monitoring (April 27):** Runs after 12PM pipeline

### ✅ Web App (Enhanced - April 27)
- Interactive parlay builder with real-time odds
- Team abbreviations (BAL, NYY, LAD, etc.)
- Pitcher handedness display (RHP, LHP)
- Game time sorting (earliest games first)
- Auto-filter started games (60-second refresh)
- Performance analytics dashboard (6 sections, 66K training samples)
- **NEW: Training Data tab (April 27):** 5 analytical sections
- Position filters (All / Hitters / Pitchers)
- Stat filters
- Analyze button → Claude API

**URL:** https://mlb-agent.up.railway.app/

### ✅ Database & Resolution
- mlb_scored_legs: 614+ production legs (growing daily)
- mlb_training_data: **76,000+ props** (March 28 - April 27, growing ~150-200/day)
- Daily automated resolution at 9AM ET
- **NEW: Training data resolution (April 27):** mlb_training_data resolved alongside mlb_scored_legs
- Calibration tracking
- **NEW: SQL analytics views (April 27):** 4 views for instant metrics

## Training Data Analytics Dashboard (NEW - April 27)

### SQL Views (Supabase)
Created in `sql/training_data_views.sql`:

| View | Purpose |
|------|---------|
| `training_data_daily_health` | Last 14 days collection volume + resolution status |
| `training_data_feature_health` | Feature completeness % by date (last 14 days) |
| `training_data_direction_analysis` | Hit rates by stat+direction (last 30 days, ≥20 samples) |
| `training_data_calibration` | Predicted coverage vs actual hit rate by bucket |

**To activate:** Run `sql/training_data_views.sql` in Supabase SQL Editor

### Health Check Script
File: `scripts/training_health_check.py`

**Checks:**
1. Daily collection volume (flags missing days)
2. Resolver failures (>40% unresolved = broken resolver)
3. Feature completeness (prospective rows only)
4. Hit rate validation (40-58% range)

**Current status:**
Status: 1 ISSUE(S) DETECTED
Hit rate (7d): 45.2%
RESOLVER FAILURE: 254 props unresolved (>40%) —
resolver likely did not run for: 2026-04-02

**Runs:** Automatically after every 12PM pipeline (appears in Railway logs)

### Web App Training Tab
**Sections:**

1. **Summary Cards:** Total props, days covered, hit rate, unresolved
2. **Daily Collection Health:** Last 14 days with color-coded status
3. **Direction Bias Heatmap:** Over vs under hit rates by stat
4. **Coverage Calibration:** Predicted vs actual with error tracking
5. **Feature Health Timeline:** ML feature completeness over time

**Access:** https://mlb-agent.up.railway.app/ → Training tab

## Next Milestones

### Immediate (Next Session)
1. Run validation queries on training data
2. Interpret results (direction bias, coverage accuracy)
3. Adjust strategy if needed (deflation, all-unders, etc.)

### Short-term (Next 3-5 Days)
4. Monitor 60% threshold performance
5. Verify win rate improvement from 47.7% baseline
6. Create SQL views in Supabase

### Medium-term (Next 1-2 Weeks)
7. A/B test ML vs heuristic scoring
8. Roll out ML to production if superior
9. Add charts to web app analytics

### Long-term (Future)
10. Parlay-level ML optimizer
11. Advanced features (ballpark, weather, line movement)
