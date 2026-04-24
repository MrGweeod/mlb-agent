# MLB Parlay Agent — Build Status

**Last Updated:** 2026-04-24
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

### ✅ Phase 4 — ML Training Data Collection (Complete)
- Historical backfill: 66,174 resolved samples (March 28 - April 22)
- Feature engineering: 49,222 samples with calculated features
- Database: mlb_training_data table fully populated

### ✅ Phase 5 — ML Model Training (Complete - April 24)
- Gradient boosting classifier trained on 49,222 samples
- ROC AUC: 0.8648 (target was 0.60+)
- Model saved: models/leg_scorer_v1.pkl
- Ready for A/B testing vs heuristic scoring

## Production Pipeline Status

### ✅ Core Pipeline (Enhanced - April 24)
- 8-step daily pipeline (9AM/12PM/5:30PM ET)
- SGO props fetch (MLB-specific)
- Coverage calculation with handedness splits
- Pitcher K props via Poisson model
- Composite leg scoring (coverage 70%, opponent 20%, stability 10%)
- **NEW:** Smart parlay filter (blocks poison overs, max 1 risky over)
- Branch-and-Bound parlay builder
- Automated outcome resolution

### ✅ Web App (Enhanced - April 24)
- Interactive parlay builder with real-time odds
- **NEW:** Team abbreviations (BAL, NYY, LAD, etc.)
- **NEW:** Pitcher handedness display (RHP, LHP)
- **NEW:** Game time sorting (earliest games first)
- **NEW:** Auto-filter started games (60-second refresh)
- Performance analytics dashboard (6 sections, 66K training samples)
- Position filters (All / Hitters / Pitchers)
- Stat filters
- Analyze button → Claude API

**URL:** https://mlb-agent.up.railway.app/

### ✅ Database & Resolution
- mlb_scored_legs: 614+ production legs (growing daily)
- mlb_training_data: 73,942 historical props (66,174 resolved)
- Daily automated resolution at 9AM ET
- Calibration tracking

## Smart Parlay Filter (NEW - April 24)

**Poison overs (BLOCKED entirely):**
- RBI overs: 14.6% hit rate
- Walks overs: 19.4% hit rate  
- Home runs overs: 6.1% hit rate

**Risky overs (max 1 per parlay):**
- Hits over 0.5 with 65+ composite score: 44.4% hit rate
- Pitcher strikeouts over 4.5+ with 65+ score: 44.6% hit rate

**All other overs:** BLOCKED

**Expected impact:** Win rate improvement from 47.7% to 52-58%

## ML Model Status (NEW - April 24)

**Model:** GradientBoostingClassifier + IsotonicCalibration
- Training samples: 49,222
- ROC AUC: 0.8648
- Accuracy: 80%
- Top feature: direction (76.6% importance)

**Status:** Trained and saved, ready for production
**Next step:** A/B test vs heuristic scoring (after filter proves out)

## Calibration Results (614 Production Legs, April 17-22)

### Overall Performance
- Win rate: 47.7% (293/614)
- **Expected after filter:** 52-58%

### Coverage Accuracy (Known Issue)
| Bucket | Predicted | Actual | Error |
|--------|-----------|--------|-------|
| <55% | 47.0% | 40.7% | -6.3pp |
| 55-60% | 57.3% | 40.4% | -16.9pp |
| 60-65% | 62.6% | 50.0% | -12.6pp |
| 65-70% | 67.7% | 44.6% | -23.1pp |
| 70%+ | 77.4% | 55.1% | -22.3pp |

**Note:** Coverage formula still overconfident; ML model should correct this

### Prop Type Performance
| Stat | Total | Win Rate |
|------|-------|----------|
| Strikeouts | 122 | 53.3% ✅ |
| Total Bases | 53 | 47.2% |
| RBI | 32 | 46.9% |
| Hits | 386 | 46.4% |
| Walks | 21 | 42.9% |

### Direction Performance
| Direction | Total | Win Rate |
|-----------|-------|----------|
| Over | 307 | 50.0% |
| Under | 307 | 44.3% |

**Note:** This was BEFORE the smart filter. Direction bias should flip with new filter.

## Training Data Summary

### Backfill (Historical)
| Metric | Count |
|--------|-------|
| Total props logged | 73,942 |
| Resolved (hit/miss) | 66,174 (89.5%) |
| Hits | 30,090 (45.5%) |
| Misses | 36,084 (54.5%) |
| NULL (DNP/scratched) | 7,768 (excluded) |

### Feature Engineering
| Feature | Populated | Coverage |
|---------|-----------|----------|
| opponent_adjustment | 66,174 | 100.0% |
| coverage_pct | 49,222 | 74.4% |
| composite_score | 49,222 | 74.4% |
| trend_score | 63,092 | 95.3% |
| pa_last_10 | 63,092 | 95.3% |

**Date range:** March 28 - April 22, 2026 (26 days, Opening Day through yesterday)

### Market Insights (from 66K samples)
- **Overall hit rate:** 45.5%
- **Direction bias:** Overs 21.9%, Unders 79.2%
- **Golden combos:** RBI under (85.4%), Walks under (80.5%)
- **Poison combos:** RBI over (14.6%), Walks over (19.4%), HR over (6.1%)

## What's Built and Working

### ✅ ML Infrastructure (NEW)
- `src/engine/ml_scorer.py` — Model training + inference
- `models/leg_scorer_v1.pkl` — Trained model artifact
- Feature engineering pipeline (backfill complete)

### ✅ Smart Filtering (NEW)
- `filter_and_tag_legs()` in parlay_builder.py
- Branch-and-Bound risky over constraint
- Integrated into production pipeline

### ✅ Web App Enhancements (NEW)
- Team abbreviations + pitcher handedness
- Game time sorting
- Auto-filter started games
- 60-second auto-refresh

### ✅ Training Data Infrastructure
- `scripts/backfill_training_data.py` — Historical data collection
- `mlb_training_data` table — 73,942 rows with props + outcomes
- `scripts/backfill_features.py` — Feature calculation (49,222 rows)

## What's NOT Built

### Prospective Training Data Collection (Phase 4.5 — Next)
- Add 12PM props to mlb_training_data daily
- Automated feature calculation for new props
- Growing dataset: +300 samples/day

### ML Scorer in Production (Phase 5.5 — After Filter Validation)
- Replace heuristic composite_score with ml_hit_probability
- A/B test framework (ML vs heuristic)
- Rollout after 3-5 days of validation

### Smart Builder Mode 2 (Phase 6 — Future)
- Live P(win) calculator
- Warning flags (over concentration, poison combos)
- Suggested replacements
- ML probability per leg

### Advanced Features (Roadmap)
- Ballpark factors
- Weather data integration
- Line movement tracking
- Parlay-level ML optimizer

## Recent Deployments

| Date | Feature | Status |
|------|---------|--------|
| 2026-04-24 | Web app UI improvements | ✅ Deployed |
| 2026-04-24 | Smart parlay filter | ✅ Deployed |
| 2026-04-24 | ML model training | ✅ Complete |
| 2026-04-23 | Historical backfill | ✅ Complete |
| 2026-04-23 | Dashboard overhaul | ✅ Deployed |
