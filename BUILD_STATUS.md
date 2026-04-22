# MLB Parlay Agent — Build Status

**Last Updated:** 2026-04-22
**Blueprint Version:** v1.0
**Repo:** github.com/MrGweeod/mlb-agent

## Infrastructure Status
| Component | Status | Notes |
|-----------|--------|-------|
| Railway Deployment | ✅ Running | Commit: 41be85d |
| Discord Bot | ✅ Connected | Scheduled runs: 9AM/12PM/5:30PM ET |
| Web App | ✅ Fully Functional | Dashboard tab, position filters, analyze button |
| Supabase PostgreSQL | ✅ Live | mlb_* tables active, 614 clean resolved legs |

## Build Progress

### ✅ Phase 1 — Direct NBA Agent Copies (Complete)
All modules copied and working.

### ✅ Phase 2 — MLB Adaptations (Complete)
All modules adapted for MLB including pitcher K props (Poisson model).

### ✅ Phase 3 — New Modules (Complete)
All modules built and deployed.

### ✅ April 22 Improvements (Complete)
- Coverage model fixed (log-odds transformation — no more 100% clipping)
- Performance analytics dashboard built (6 sections)
- Historical legs rescored (618/639 updated with new model)
- Database deduplicated (614 clean legs from 673 raw)

## Calibration Results (614 Deduplicated Legs, April 17-21)

### Coverage Accuracy (After Log-Odds Fix)
| Bucket | Avg Predicted | Count | Won | Actual Rate | Error | Assessment |
|--------|--------------|-------|-----|-------------|-------|------------|
| <55%   | 47.0%        | 135   | 55  | 40.7%       | -6.3pp | ✅ Good |
| 55-60% | 57.3%        | 52    | 21  | 40.4%       | -16.9pp | ❌ Worst bucket |
| 60-65% | 62.6%        | 128   | 64  | 50.0%       | -12.6pp | ⚠️ Overconfident |
| 65-70% | 67.7%        | 112   | 50  | 44.6%       | -23.1pp | ❌ Most overconfident |
| 70%+   | 77.4%        | 187   | 103 | 55.1%       | -22.3pp | ❌ Overconfident |

**Overall win rate:** 47.7% (293/614)

### Prop Type Performance
| Stat       | Total | Win Rate | Notes |
|------------|-------|----------|-------|
| Strikeouts | 122   | 53.3%    | Best performer ✅ |
| Total Bases| 53    | 47.2%    | |
| RBI        | 32    | 46.9%    | |
| Hits       | 386   | 46.4%    | |
| Walks      | 21    | 42.9%    | |

### Direction Bias
| Direction | Count | Win Rate |
|-----------|-------|----------|
| Over      | 368   | 50.0%    |
| Under     | 246   | 44.3%    |

### EV Signal Status
**Status:** Still inverted — investigation needed
- Strong -EV legs: 55.3% hit rate (should be worst bucket) ❌
- Strong +EV legs: lower win rate ❌
- Root cause: April 21 EV formula fix not yet generating enough new data (< 50 legs)

## What's Built and Working

### ✅ Core Pipeline
- 8-step daily pipeline (9AM/12PM/5:30PM ET)
- SGO props fetch (MLB-specific)
- Coverage calculation with handedness splits (log-odds transformation)
- Pitcher K props via Poisson model
- Composite leg scoring (5 factors)
- Branch-and-Bound parlay builder
- Automated outcome resolution (box-score-based, 1 call per game)

### ✅ Web App
- Interactive parlay builder
- Performance analytics dashboard (6 sections, auto-refresh 60s)
- Position filters (All / Hitters / Pitchers)
- Stat filters (hits, strikeouts, totalBases, etc.)
- Real-time combined odds calculation
- Correlation blocking (max 1 leg per player, max 3 per game)
- Analyze button → Claude API (10-20s, statistical analysis only)
- Trend (HOT/COLD) + Matchup (Favorable/Tough) pills on cards
- Mobile-responsive design

### ✅ Database & Resolution
- 614 clean deduplicated resolved legs (April 17-21)
- Daily automated resolution at 9AM ET
- Per-odd_id deduplication (allows pitcher K props in afternoon runs)
- DEDUP_CTE in all dashboard queries (eliminates NULL odd_id duplication)
- Calibration tracking (coverage, EV, trend, direction validation)

## Known Issues

### Critical
- ❌ **EV signal inverted** — Strong -EV legs winning at 55.3%. Root cause under investigation. EV weight currently 0%.
- ❌ **Coverage systematically overconfident** — 12-23pp errors in upper buckets despite log-odds fix. Model still overpredicts.

### High Priority
- ⚠️ **Opponent adjustment distribution unknown** — Worth querying whether it systematically discounts coverage
- ⚠️ **55-60% bucket worst calibrated** (-16.9pp) — May need a separate penalty for this range
- ⚠️ **Under direction underperforms** — 44.3% vs 50.0% overs; consider raising under eligibility threshold

### Medium Priority
- Apply global coverage deflation factor (0.85×) to reduce systematic overconfidence
- Monitor April 22+ legs (first scored with log-odds model, no old linear coverage)

## What's NOT Built

**Bet Tracking System (Optional):**
- `mlb_placed_bets` table schema exists but not wired to web app
- Manual bet logging via DraftKings → spreadsheet → outcome resolver

**Advanced Features (Roadmap):**
- Learning loop (regression-based weight recalibration)
- Weather adjustment (wind/temp for outdoor games)
- Same-game parlay correlation detection
