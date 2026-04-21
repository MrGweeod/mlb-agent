# MLB Parlay Agent — Build Status

**Last Updated:** 2026-04-21
**Blueprint Version:** v1.0
**Repo:** github.com/MrGweeod/mlb-agent

## Infrastructure Status
| Component | Status | Notes |
|-----------|--------|-------|
| Railway Deployment | ✅ Running | Commit: 4b49efd |
| Discord Bot | ✅ Connected | Scheduled runs: 9AM/12PM/5:30PM ET |
| Web App | ✅ Fully Functional | Position filters, analyze button working |
| Supabase PostgreSQL | ✅ Live | mlb_* tables active, 458+ resolved legs |

## Build Progress

### ✅ Phase 1 — Direct NBA Agent Copies (Complete)
All modules copied and working.

### ✅ Phase 2 — MLB Adaptations (Complete)
All modules adapted for MLB including pitcher K props (Poisson model).

### ✅ Phase 3 — New Modules (Complete)
All modules built and deployed.

## Calibration Results (458 Resolved Legs, April 17-20)

### Coverage Accuracy
| Bucket | Predicted | Actual | Error | Assessment |
|--------|-----------|--------|-------|------------|
| 70%+ | 74.4% | 68.3% | +6.1% | ✅ Well calibrated |
| 65-70% | 67.6% | 63.6% | +4.0% | ✅ Good |
| 60-65% | 62.8% | 60.5% | +2.3% | ✅ Excellent |
| 55-60% | 57.9% | 61.5% | -3.6% | ✅ Slightly underconfident |

### Prop Type Performance
| Prop Type | Predicted | Actual | Error | Sample | Assessment |
|-----------|-----------|--------|-------|--------|------------|
| Hits (over) | 60.4% | 58.0% | +2.4% | 150 | ✅ Well calibrated |
| Strikeouts (over) | 62.3% | 59.7% | +2.6% | 77 | ✅ Well calibrated |
| Total Bases (over) | 59.2% | 45.8% | +13.4% | 24 | ⚠️ Overconfident (penalty: 0.78x) |
| Walks (over) | 58.5% | 45.5% | +13.0% | 11 | ⚠️ Small sample |
| RBIs (over) | 57.8% | 28.6% | +29.2% | 14 | ⚠️ Small sample |

### EV Signal Status
**Historical data (April 17-20):** Still inverted (used old formula)
- Strong +EV: 42.9% hit rate ❌
- Strong -EV: 61.0% hit rate ❌

**Expected after 2-3 days:** Signal should flip positive (fixed formula deployed April 21)

## What's Built and Working

### ✅ Core Pipeline
- 8-step daily pipeline (9AM/12PM/5:30PM ET)
- SGO props fetch (MLB-specific)
- Coverage calculation with handedness splits (batter vs RHP/LHP)
- Pitcher K props via Poisson model
- Composite leg scoring (5 factors)
- Branch-and-Bound parlay builder
- Automated outcome resolution (box-score-based, 1 call per game)

### ✅ Web App
- Interactive parlay builder
- Position filters (All / Hitters / Pitchers)
- Stat filters (hits, strikeouts, totalBases, etc.)
- Real-time combined odds calculation
- Correlation blocking (max 1 leg per player, max 3 per game)
- Analyze button → Claude API (10-20s, statistical analysis only)
- Mobile-responsive design

### ✅ Database & Resolution
- 458 resolved legs (April 17-20)
- Daily automated resolution at 9AM ET
- Per-odd_id deduplication (allows pitcher K props in afternoon runs)
- Calibration tracking (coverage, EV, trend validation)

## What's NOT Built

**Bet Tracking System (Optional):**
- `mlb_placed_bets` table schema exists but not wired to web app
- Manual bet logging via DraftKings → spreadsheet → outcome resolver

**Advanced Features (Roadmap):**
- Dashboard (P&L tracking, hit rate charts)
- Learning loop (regression-based weight recalibration)
- Weather adjustment (wind/temp for outdoor games)
- Same-game parlay correlation detection
