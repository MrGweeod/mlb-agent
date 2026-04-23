# MLB Parlay Agent — Build Status

**Last Updated:** 2026-04-23
**Blueprint Version:** v1.0
**Repo:** github.com/MrGweeod/mlb-agent

## Infrastructure Status
| Component | Status | Notes |
|-----------|--------|-------|
| Railway Deployment | ✅ Running | Production pipeline 3×/day |
| Discord Bot | ✅ Connected | Scheduled runs: 9AM/12PM/5:30PM ET |
| Web App | ✅ Fully Functional | Dashboard, position filters, analyze button |
| Supabase PostgreSQL | ✅ Live | mlb_scored_legs (614 rows) + mlb_training_data (73,942 rows) |

## Build Progress

### ✅ Phase 1 — Direct NBA Agent Copies (Complete)
All modules copied and working.

### ✅ Phase 2 — MLB Adaptations (Complete)
All modules adapted for MLB including pitcher K props (Poisson model).

### ✅ Phase 3 — New Modules (Complete)
All modules built and deployed.

### ✅ Phase 4 — ML Training Data Collection (NEW — Complete)
- Historical backfill script built and tested
- 66,174 resolved training samples collected (March 28 - April 22)
- Database table `mlb_training_data` created and populated
- Ready for feature engineering + model training

## Training Data Status (NEW)

### Backfill Results
| Metric | Count |
|--------|-------|
| Total props logged | 73,942 |
| Resolved (hit/miss) | 66,174 (89.5%) |
| Hits | 31,450 (47.5%) |
| Misses | 34,724 (52.5%) |
| NULL (DNP/scratched) | 7,768 (10.5%) |

### Date Coverage
- **Start:** March 28, 2026 (Opening Day)
- **End:** April 22, 2026
- **Days:** 26 days
- **Avg props/day:** ~2,850

### Sample Distribution by Stat
| Stat | Count | Notes |
|------|-------|-------|
| Hits | ~40,000 | Largest category |
| Strikeouts | ~15,000 | Pitcher + batter combined |
| Total Bases | ~8,000 | |
| RBI | ~3,000 | |
| Walks | ~2,500 | |
| Other | ~5,000 | Runs, HRs, stolen bases |

## Production Pipeline Status (Unchanged)

### ✅ Core Pipeline
- 8-step daily pipeline (9AM/12PM/5:30PM ET)
- SGO props fetch (MLB-specific)
- Coverage calculation with handedness splits (log-odds transformation)
- Pitcher K props via Poisson model
- Composite leg scoring (coverage 70%, opponent 20%, stability 10%)
- Branch-and-Bound parlay builder
- Automated outcome resolution

### ✅ Web App
- Interactive parlay builder
- Performance analytics dashboard (6 sections)
- Position filters (All / Hitters / Pitchers)
- Stat filters
- Real-time combined odds calculation
- Analyze button → Claude API (statistical analysis)

### ✅ Database & Resolution
- 614 production legs (April 17-22)
- 66,174 training legs (March 28 - April 22)
- Daily automated resolution at 9AM ET
- Calibration tracking

## Calibration Results (614 Production Legs, April 17-21)

### Coverage Accuracy
| Bucket | Predicted | Actual | Error | Assessment |
|--------|-----------|--------|-------|------------|
| <55% | 47.0% | 40.7% | -6.3pp | ✅ Good |
| 55-60% | 57.3% | 40.4% | -16.9pp | ❌ Worst |
| 60-65% | 62.6% | 50.0% | -12.6pp | ⚠️ Overconfident |
| 65-70% | 67.7% | 44.6% | -23.1pp | ❌ Very overconfident |
| 70%+ | 77.4% | 55.1% | -22.3pp | ❌ Overconfident |

**Overall:** 47.7% win rate (293/614)

### Prop Type Performance
| Stat | Total | Win Rate |
|------|-------|----------|
| Strikeouts | 122 | 53.3% ✅ |
| Total Bases | 53 | 47.2% |
| RBI | 32 | 46.9% |
| Hits | 386 | 46.4% |
| Walks | 21 | 42.9% |

### Known Issues
- ❌ Coverage systematically overconfident (12-23pp errors)
- ⚠️ Under direction underperforms (44.3% vs 50.0% overs)

## What's Built and Working

### ✅ Training Data Infrastructure (NEW)
- `scripts/backfill_training_data.py` — Historical data collection script
- `mlb_training_data` table — 73,942 rows with props + outcomes
- Idempotent backfill (safe to re-run, won't duplicate)
- Three modes: full, props-only, resolve-only

## What's NOT Built

### ML Model Training (Phase 5 — Next)
- Feature calculation module (populate NULL columns in training_data)
- Gradient boosting classifier training script
- ML-based leg scorer (`ml_scorer.py` to replace `leg_scorer.py`)
- A/B testing framework (ML vs heuristic scoring)

### Prospective Collection (Phase 4.5 — Next)
- Add training data logging to daily 9AM pipeline
- Automated feature calculation for new props
- Growing dataset: +300 samples/day

### Advanced Features (Roadmap)
- Ballpark factors
- Weather data integration
- Line movement tracking
- Parlay-level ML optimizer
