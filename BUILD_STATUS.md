# MLB Parlay Agent — Build Status

**Last Updated:** 2026-04-29
**Blueprint Version:** v1.0 (OUTDATED - needs v2.0)
**Repo:** github.com/MrGweeod/mlb-agent

## Infrastructure Status
| Component | Status | Notes |
|-----------|--------|-------|
| Railway Deployment | ⚠️ Needs Fix | ModuleNotFoundError - add PYTHONPATH=/app |
| Discord Bot | ❌ Removed | Deleted entirely - web app is single source |
| Web App | ✅ Built | 4 tabs complete, pending deployment fix |
| Supabase PostgreSQL | ⚠️ Partial | mlb_parlay_recommendations table not created yet |

## Build Progress

### ✅ Phase 1 — Direct NBA Agent Copies (Complete)
All modules copied and working.

### ✅ Phase 2 — MLB Adaptations (Complete - REBUILT)
**Coverage calculation completely rewritten (April 29):**
- Old system: smooshed coverage with penalties → REMOVED
- New system: 3 separate signals for hitters, 2 for pitchers
- Hitter signals: coverage_overall, coverage_vs_hand, coverage_recent_10
- Pitcher signals: coverage_overall, coverage_recent_5

**Composite scoring completely rewritten (April 29):**
- Removed: EV factor, trend factor, opponent factor (for hitters), PA stability
- New hitter formula: 40% overall + 30% vs_hand + 30% recent_10
- New pitcher formula: 35% overall + 25% recent_5 + 20% pitcher_quality + 20% opponent_offense

**Pitcher quality module added (April 29):**
- `src/apis/pitcher_stats.py` - ERA/K9/WHIP rankings
- `src/apis/team_stats.py` - Team K%/BA/RPG rankings
- 24-hour cache, rank-based normalization

### ✅ Phase 3 — New Modules (Complete - ENHANCED)
**Data pipeline fixes (April 29):**
- Database CHECK constraint fixed (now allows 'void')
- Player ID lookup added to SGO fetcher (MLB-StatsAPI integration)
- 10K backlog resolved

**Recommendations system built (April 29):**
- Backend: `generate_recommendations()` in `main.py` (Step 9)
- Database: `mlb_parlay_recommendations` table schema created ⚠️ not run yet
- API: `/api/recommendations` (GET), `/api/analyze-recommendation` (POST)
- Frontend: Picks tab in web app with Claude analysis integration

**Discord bot removed (April 29):**
- `bot.py` deleted
- `src/bot/*` deleted
- Pipeline scheduler moved to `src/web/server.py`
- Runs 9AM/12PM/5:30PM ET via asyncio background task

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
- **NOTE:** Heuristic scoring was completely rebuilt April 29 - ML may need retraining

### ✅ Phase 5.5 — Training Data Analytics (Complete - April 27)
- **SQL views:** 4 views for ad-hoc analysis in Supabase
- **Health check script:** Automated monitoring with daily alerts
- **Web app tab:** Live analytics dashboard with 5 sections
- **Pipeline integration:** Health check runs after every 12PM pipeline

### ⚠️ Phase 6 — Recommendations System (NEEDS TABLE CREATION)
- Backend complete
- Frontend complete
- Claude analysis integration complete
- **BLOCKER:** User must run `sql/create_recommendations_table.sql` in Supabase

## Production Pipeline Status

### ✅ Core Pipeline (REBUILT - April 29)
- 8-step daily pipeline (9AM/12PM/5:30PM ET) - now runs from web server, not Discord bot
- SGO props fetch (MLB-specific) - enhanced with player ID lookup
- **Coverage calculation with 3/2 signals (NEW)** - complete rewrite
- **Pitcher quality + opponent offense (NEW)** - 2 new modules
- **Pure coverage-based scoring (NEW)** - composite formula rebuilt
- Branch-and-Bound parlay builder - unchanged
- **Recommendations generation (NEW)** - Step 9 added
- Automated outcome resolution - working
- **Prospective training data logging** - working
- **Health check monitoring** - working

### ✅ Web App (4 TABS COMPLETE)
- **Legs tab:** Interactive parlay builder with real-time odds
- **Dashboard tab:** Performance analytics (6 sections, 66K training samples)
- **Training tab:** 5 analytical sections for ML data quality
- **Picks tab (NEW):** 5 daily parlay recommendations with Claude analysis

**Common features:**
- Team abbreviations (BAL, NYY, LAD, etc.)
- Pitcher handedness display (RHP, LHP)
- Game time sorting (earliest games first)
- Auto-filter started games (60-second refresh)
- Position filters (All / Hitters / Pitchers)
- Stat filters
- Password protection

**Picks tab features:**
- "BEST BET" highlighting (rank 1 parlay)
- Combined odds, win probability, edge % display
- All legs with coverage % shown
- "Analyze Parlay" button → Claude generates 2-3 sentence explanation
- "View in Builder" button → Coming soon

**URL:** https://mlb-agent.up.railway.app/ (currently crashing - needs PYTHONPATH fix)

### ✅ Database & Resolution
- mlb_scored_legs: 614+ production legs (growing daily)
- mlb_training_data: **76,000+ props** (March 28 - April 27, growing ~150-200/day)
- mlb_parlay_recommendations: **NOT CREATED YET** ⚠️ User must run SQL file
- Daily automated resolution at 9AM ET
- **Training data resolution** - mlb_training_data resolved alongside mlb_scored_legs
- Calibration tracking
- **SQL analytics views** - 4 views for instant metrics

## Training Data Analytics Dashboard (April 27)

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

**Runs:** Automatically after every 12PM pipeline (appears in Railway logs)

### Web App Training Tab
**Sections:**

1. **Summary Cards:** Total props, days covered, hit rate, unresolved
2. **Daily Collection Health:** Last 14 days with color-coded status
3. **Direction Bias Heatmap:** Over vs under hit rates by stat
4. **Coverage Calibration:** Predicted vs actual with error tracking
5. **Feature Health Timeline:** ML feature completeness over time

**Access:** https://mlb-agent.up.railway.app/ → Training tab

## Current Blockers

### IMMEDIATE
1. **Railway deployment** - Add PYTHONPATH=/app environment variable (user doing manually)
2. **Database table** - Run `sql/create_recommendations_table.sql` in Supabase SQL Editor (user action required)

### After Deployment
3. **Test Recommendations tab** - Wait for next pipeline run (9AM/12PM/5:30PM)
4. **Test Claude analysis** - Click "Analyze Parlay" button, verify it works

## Next Milestones

### Immediate (After deployment fix)
1. Test full recommendations flow
2. Verify pipeline scheduler works in production
3. Monitor new coverage calculation performance

### Short-term (Next 3-5 Days)
4. Build "View in Builder" functionality
5. Add outcome resolver for recommendations
6. Track win rates with new scoring system

### Medium-term (Next 1-2 Weeks)
7. A/B test ML vs new heuristic scoring
8. Retrain ML model with new feature set
9. Handle batter strikeouts overs (penalty or max-1 rule)

### Long-term (Future)
10. Create Blueprint v2.0 (current one is outdated)
11. Parlay-level ML optimizer
12. Advanced features (ballpark, weather, line movement)

## Architecture Changes This Session

### Major Rewrites
1. **Coverage calculation** - from smooshed single value to 3/2 separate signals
2. **Composite scoring** - from 5-factor weighted to pure coverage-based
3. **Pipeline delivery** - from Discord bot to web server scheduler
4. **Recommendations** - from nothing to full backend + frontend system

### New Modules
1. `src/apis/pitcher_stats.py` - Pitcher ERA/K9/WHIP rankings
2. `src/apis/team_stats.py` - Team offensive rankings
3. `sql/create_recommendations_table.sql` - Parlay storage schema

### Deleted Modules
1. `bot.py` - Discord bot entry point
2. `src/bot/runner.py` - Discord pipeline wrapper
3. `src/bot/formatter.py` - Discord message formatting
4. `src/bot/__init__.py` - Discord bot package

### Modified Modules (Major Changes)
1. `src/engine/coverage.py` - Complete rewrite (218 lines added, 266 removed)
2. `src/engine/leg_scorer.py` - Complete rewrite (158 lines added, 237 removed)
3. `src/web/server.py` - Pipeline scheduler + recommendation endpoints (+147 lines)
4. `src/web/static/index.html` - Picks tab (+257 lines)
5. `main.py` - Recommendations generation Step 9 (+126 lines)

**Total:** ~1,200 lines added, ~1,400 lines deleted, net -200 lines
