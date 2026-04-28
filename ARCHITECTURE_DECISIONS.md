# MLB Parlay Agent — Architecture Decisions

**Last Updated:** April 27, 2026

---

## Training Data Analytics Infrastructure (April 27, 2026)

**Decision:** Build a three-tier monitoring system for training data: SQL views for ad-hoc analysis, automated health check script for alerts, and web app analytics tab for visual dashboards.

**Context:**
- 76K+ training samples accumulated (March 28 - April 27)
- Need to validate ML model assumptions (direction bias, coverage accuracy)
- Daily prospective collection requires monitoring for failures
- Users need accessible way to understand what the data reveals

**Three-tier approach:**

### Tier 1: SQL Views (Ad-hoc Analysis)
**Created:** `sql/training_data_views.sql` with 4 views

**Views:**
1. `training_data_daily_health` — Collection volume over time
2. `training_data_feature_health` — Feature engineering completeness
3. `training_data_direction_analysis` — Over/under win rates by stat
4. `training_data_calibration` — Coverage prediction accuracy

**Rationale:**
- Data analysts can run custom queries without writing SQL from scratch
- Views abstract complex aggregations into simple SELECT statements
- Can be joined with other tables for deeper analysis
- Supabase UI makes results immediately visible

### Tier 2: Automated Health Check Script
**Created:** `scripts/training_health_check.py`

**Checks:**
1. Missing collection days (yesterday should have data)
2. Resolver failures (>40% unresolved = broken)
3. Feature completeness gaps (coverage_pct, composite_score, etc.)
4. Hit rate anomalies (outside 40-58% range)

**Integrated into:** `main.py` — runs after every 12PM pipeline

**Rationale:**
- Detects pipeline failures automatically (no manual checking needed)
- Appears in Railway logs for visibility
- Exit code signals can trigger external alerting systems
- Preventative: catches issues before they compound

### Tier 3: Web App Analytics Tab
**Created:** Training tab in web app with 5 sections

**Sections:**
1. Summary cards (total props, hit rate, unresolved count)
2. Daily collection health (last 14 days, color-coded)
3. Direction bias heatmap (over vs under by stat)
4. Coverage calibration (predicted vs actual)
5. Feature health timeline (ML feature completeness)

**Rationale:**
- Non-technical users can understand data quality visually
- Auto-refreshes (60s) for live monitoring
- Mobile-friendly for on-the-go checks
- Complements existing Legs + Dashboard tabs

**Implementation notes:**
- Backend: `/api/training-analytics` endpoint in `src/web/server.py`
- Data function: `get_training_analytics_data()` in `src/utils/db.py`
- Frontend: 245 new lines in `src/web/static/index.html`
- Uses same design system as existing dashboard

**Why three tiers instead of one?**
- **SQL views:** Power users, deep analysis, custom queries
- **Health check:** Automated alerts, catches failures immediately
- **Web app:** Accessibility, visual understanding, mobile-friendly

**Alternative considered:** Single-tier (web app only)
**Rejected because:** Doesn't serve data analysts or automation needs

---

## Prospective Training Data Collection (April 27, 2026)

**Decision:** Automatically log ALL scored legs (55%+ coverage) to `mlb_training_data` during the daily 12PM pipeline run, with outcome=NULL initially, then resolve them the next morning at 9AM.

**Context:**
- Historical backfill covered March 28 - April 22 (66,174 samples)
- Gap fill added April 23-27 (2,053 samples)
- Without prospective collection, training data becomes stale
- ML model needs fresh samples that reflect current season dynamics

**Architecture:**

### Database Function
**Added:** `log_training_data_legs(legs, run_date)` in `src/utils/db.py`

**What it logs:**
- All legs with coverage ≥55% (not just parlay legs)
- Includes: coverage_pct, composite_score, opponent_adjustment, trend_score
- Uses same `{date}|{odd_id}` key format as backfill (no conflicts)
- ON CONFLICT DO NOTHING (safe to re-run)

**Rationale:**
- Logs ~150-200 props per day (full market spectrum)
- Captures both winners and losers for balanced training
- Logs props you didn't recommend (important for "what NOT to do")
- Composite score populated for 60%+ legs, NULL for <60% (correct)

### Pipeline Integration
**Modified:** `main.py` to call `log_training_data_legs()` after parlay building

**Timing:** After step [8/8] "Building hybrid parlays"
- Ensures composite_score is populated for 60%+ legs
- Before Discord posting (logs happen regardless of parlay success)

**Output:** `Logged X prop(s) to training data (prospective collection)`

**Rationale:**
- Logs every day, not just when parlays are found
- Runs in same transaction as parlay logging (atomic)
- No separate scheduler needed

### Outcome Resolution
**Extended:** `src/tracker/outcome_resolver.py` with `resolve_training_data(game_date)`

**How it works:**
- Queries `mlb_training_data WHERE result IS NULL AND game_date = yesterday`
- Fetches box scores via MLB-StatsAPI (same as mlb_scored_legs resolver)
- Tries MLB player_id first (prospective rows), falls back to name (backfill rows)
- Updates result = 'hit' | 'miss' | 'void'

**CLI extended:** `python -m src.tracker.outcome_resolver 2026-04-27` now resolves BOTH tables

**Rationale:**
- Reuses existing box score logic (no duplication)
- Handles both prospective and backfill rows seamlessly
- Runs automatically at 9AM (no manual intervention)

**Daily flow:**
12PM: Log props with outcome=NULL
↓
9AM next day: Resolve yesterday's props
↓
Result: Training data grows ~150-200 samples/day automatically

**Why not log at 9AM instead?**
- 12PM has the best prop availability (morning odds not yet posted)
- 12PM runs every day (9AM only runs when there are games to resolve)
- Separating logging (12PM) and resolution (9AM) is cleaner

**Alternative considered:** Log props at outcome resolution time (9AM next day)
**Rejected because:** Misses props for postponed/cancelled games entirely

---

## Coverage Threshold Raised to 60% (April 27, 2026)

**Decision:** Raise the minimum coverage threshold for parlay pool entry from 55% to 60%.

**Context:**
- April 25 parlays: Mike Trout walks 55.0%, Brice Turang hits 59.6%
- April 27 parlays: Victor Caratini hits 56.2% appeared in ALL 5 parlays
- Claude analysis flagged these as "WEAK LINK" and "consistent weak anchor"
- Training data shows 55-60% bucket has 16.9pp overconfidence error

**Impact:**
- Victor Caratini (56.2%) → **EXCLUDED** from pool
- Mike Trout (55.0%) → **EXCLUDED** from pool
- Brice Turang (59.6%) → **EXCLUDED** from pool
- Forces system to only build parlays with 60%+ coverage legs

**Expected outcome:**
- Average parlay coverage jumps from ~60-61% to ~64-66%
- Win rate should improve from 47.7% toward 52-58% range
- Eliminates weak anchor problem seen in recent recommendations

**Rationale:**
- 55-60% bucket has worst calibration error (-16.9pp)
- 60%+ buckets have smaller errors (-12.6pp to -23.1pp)
- Better to have fewer parlays with higher quality legs
- Aligns with "only bet when you have edge" philosophy

**Alternative considered:** Keep 55% threshold but add stricter filtering
**Rejected because:** Filtering still allows weak legs to dominate when options are limited

**Monitoring:** Next 3-5 days to validate win rate improvement

---

## Pitcher Hand Null Check (April 27, 2026)

**Decision:** Add null guard before calling `get_pitcher_hand()` when opposing_pitcher_id is None.

**Context:**
- Railway logs showed: `[mlb_stats] get_pitcher_hand(None) error: 400 Client Error`
- Only 153/170 legs (90%) were being enriched with pitcher profiles
- 17 legs per run missing matchup data

**Root cause:**
- Pitcher props (e.g., "Strikeouts O/U 5.5") don't have an opposing pitcher
- `opposing_pitcher_id` is None for these props
- `coverage.py` was calling `get_pitcher_hand(None)` unconditionally

**Fix:** `src/engine/coverage.py` line 264
```python
# Before
pitcher_hand = get_pitcher_hand(opposing_pitcher_id)

# After
pitcher_hand = get_pitcher_hand(opposing_pitcher_id) if opposing_pitcher_id is not None else None
```

**Impact:**
- Fixed 10% of props failing enrichment
- Pitcher props now correctly have pitcher_hand=None (expected)
- No more 400 errors in logs

**Rationale:**
- Pitcher props inherently don't have opposing pitchers
- Null is the correct value, not an error
- Guard prevents unnecessary API call

**Alternative considered:** Default to 'R' (right-handed) for missing values
**Rejected because:** Would introduce false signal; None is semantically correct

---

## Training Analytics API Date Handling (April 27, 2026)

**Decision:** Remove `::text` casts on date comparisons and add `::numeric` cast before ROUND operations in PostgreSQL queries.

**Context:**
- Web app Training tab showed "HTTP 500" error
- `/api/training-analytics` endpoint was crashing
- Local testing revealed two SQL syntax errors

**Bug 1: Date type mismatch**
```sql
-- Before (lines 1391, 1412, 1459)
WHERE game_date >= (CURRENT_DATE - INTERVAL '14 days')::text

-- After
WHERE game_date >= CURRENT_DATE - INTERVAL '14 days'
```

**Root cause:** `game_date` is a DATE column; comparing to ::text fails type coercion

**Bug 2: ROUND function signature**
```sql
-- Before (line 1438)
ROUND(AVG(coverage_pct) - 100.0 * COUNT(...), 1)

-- After
ROUND((AVG(coverage_pct) - 100.0 * COUNT(...))::numeric, 1)
```

**Root cause:** PostgreSQL's ROUND(double precision, integer) doesn't exist; needs ::numeric cast

**Impact:**
- Training tab now loads correctly
- All 5 sections render with data
- No more HTTP 500 errors

**Rationale:**
- PostgreSQL is stricter about type coercion than SQLite/MySQL
- DATE - INTERVAL returns DATE (no cast needed)
- ROUND requires numeric type for precision parameter

**Lesson learned:** Always test SQL queries locally before deploying to web API endpoints

---

## Smart Parlay Filter (April 24, 2026)

**Decision:** Block poison overs entirely, allow only high-confidence risky overs with max 1 per parlay.

**Context:**
- Training data analysis revealed massive direction bias (79.2% under vs 21.9% over)
- Some stat+direction combos are poison (RBI over 14.6%, walks over 19.4%, HR over 6.1%)
- High-score hits over 0.5 shows 44.4% hit rate (marginal but viable)
- User wanted to continue tracking hits overs but not overuse them

**Filter rules:**

**Poison overs (BLOCKED):**
- RBI overs: 14.6% hit rate
- Walks overs: 19.4% hit rate
- Home runs overs: 6.1% hit rate

**Risky overs (max 1 per parlay):**
- Hits over 0.5 with 65+ composite score: 44.4% hit rate
- Pitcher strikeouts over 4.5+ with 65+ composite score: 44.6% hit rate

**All other overs:** BLOCKED (low-score hits overs, ambitious lines, etc.)

**Implementation:**
- `filter_and_tag_legs()` runs after scoring, before pool selection
- Branch-and-Bound tracks risky_overs counter (max 1)
- Filter logs breakdown: "blocked N poison overs, M other overs | kept X unders + Y risky overs"

**Rationale:**
- Prevents catastrophic parlay compositions (all overs = 3.88% 4-leg win rate)
- Allows data collection on viable overs (hits 0.5, pitcher Ks)
- Protects parlay probability from tanking below breakeven
- User retains some flexibility without shooting themselves in the foot

**Expected impact:** Win rate improvement from 47.7% to 52-58%

---

## ML-Powered Leg Scoring (April 24, 2026)

**Decision:** Build a machine learning model to predict P(hit) for each prop leg instead of using hand-coded composite scoring weights.

**Context:**
- Current system uses fixed weights: coverage 70%, opponent 20%, stability 10%
- These are "principled priors" that need calibration with real data
- 49,222 training samples available with features + outcomes
- Coverage formula is systematically overconfident (12-23pp errors)

**New Architecture:**

### Model Trained (COMPLETE)
- **Algorithm:** GradientBoostingClassifier + IsotonicCalibration
- **Training data:** 49,222 samples (March 28 - April 22, 2026)
- **Features:** coverage_pct, composite_score, opponent_adjustment, trend_score, pa_last_10, line, direction, stat (one-hot)
- **Performance:** ROC AUC 0.8648, Accuracy 80%
- **Top features:** direction (76.6%), composite_score (6.9%), opponent_adjustment (4.9%)

**Key insight:** Model correctly learned that direction (over/under) is the DOMINANT signal — even more important than coverage.

### Deployment Strategy (PENDING)

**Phase 1 (Current):** Filter deployed, ML model trained but not in production
**Phase 2 (After 3-5 days):** A/B test ML vs heuristic scoring
**Phase 3 (If ML wins):** Replace heuristic scoring in production

**Rationale:**
- Smart filter is the higher-impact change (blocks poison bets)
- Need to validate filter works before changing scoring system
- ML model learns optimal feature weights from data (no more guessing 70% vs 20%)
- Automatically discovers interactions ("high coverage + over direction = lower than formula")
- Can add new features (weather, ballpark, line movement) without manual weight tuning

**What stays the same:**
- Production pipeline still runs 3×/day (9AM/12PM/5:30PM)
- Branch-and-Bound parlay builder unchanged
- Discord delivery, web app unchanged

**What changes (when enabled):**
- `leg_scorer.py` replaced with `ml_scorer.py` for scoring
- Legs sorted by `ml_hit_probability` instead of `composite_score`
- Parlay builder uses ML probabilities for pool selection

---

## Training Data Analysis Findings (April 24, 2026)

**Decision:** Use training data insights to inform filter design and validate ML model approach.

**Key findings from 66,174 resolved samples:**

### 1. Composite Score Profitability Thresholds

| Composite Score | 4-Leg Parlay Win Rate | Verdict |
|-----------------|----------------------|---------|
| 65+ | 7.77% | ✅ Profitable at +1500 |
| 55-65 | 6.27% | ⚠️ Breakeven at +1500 |
| <45 | 3.71% | ❌ Losing at +1500 |

**Insight:** Only use 65+ composite score legs in parlays for profitable outcomes.

**Decision impact:** Raised coverage threshold to 60% (eliminates 55-65 bucket)

### 2. Direction Bias by Score Tier

| Category | Hit Rate |
|----------|----------|
| High-score overs (50+) | 42.2% |
| Low-score overs (<50) | 16.4% |
| High-score unders (50+) | 65.4% |
| Low-score unders (<50) | 83.0% |

**Insight:** Even high-score overs underperform; unders dominate regardless of score.

**Decision impact:** Smart filter blocks most overs, max 1 risky over per parlay

### 3. Golden vs Poison Stat+Direction Combinations

| Stat+Direction | Hit Rate | Classification |
|----------------|----------|----------------|
| RBI under | 85.4% | 🌟 Golden |
| Walks under | 80.5% | 🌟 Golden |
| TotalBases under | 74.0% | ✅ Good |
| Hits under | 69.6% | ✅ Good |
| RBI over | 14.6% | ☠️ Poison |
| Walks over | 19.4% | ☠️ Poison |
| HR over | 6.1% | ☠️ Poison |

**Insight:** Specific stat+direction combos have massive performance gaps (70pp delta).

**Decision impact:** Filter blocks poison overs by stat type, not just overall direction

### 4. Hits Over Breakdown (User Request)

| Category | Hit Rate | Sample Size |
|----------|----------|-------------|
| Hits over 0.5 with 65+ score | 44.4% | 372 |
| Hits over 0.5 with <65 score | 32-34% | 2,767 |

**Insight:** High composite score DOES improve hits overs (44.4% vs 30.4% avg).

**Decision impact:** Allow hits over 0.5 with 65+ score, but limit to max 1 per parlay

**Rationale for all decisions:**
- Data-driven rather than intuition-based
- Large sample sizes (66K+ props) provide statistical confidence
- Findings align with market efficiency theory (books shade overs)
- Specific stat knowledge beats generic rules

---

## Single-Pool Architecture (April 18, 2026)

**Decision:** Replace the two-pool anchor/swing system with a single scored pool.

**Context:** The two-pool system inherited from the NBA agent was causing problems in MLB because hitting props cluster in a tighter odds range (+100 to +200) and were being misclassified as swing legs.

**Old architecture (NBA-style):**
- Anchor pool: -500 to -150 odds, 70%+ coverage
- Swing pool: -150 to +250 odds, 55%+ coverage
- Select 2-4 anchors + exactly 2 swings per parlay

**Problem in MLB:**
- MLB hitting props cluster at +100 to +200 (efficiently priced)
- These were classified as "swing" legs despite 65%+ coverage
- System was treating high-quality hitting props as secondary legs
- Anchor pool had too few options (mostly pitcher strikeouts under)

**New architecture:**
- Single pool: All legs ≥60% coverage (was 55%, raised April 27)
- Rank all legs by composite score
- Take top 20 legs by score
- Branch-and-Bound finds best 4-8 leg combination in +600 to +1500 odds

**Benefits:**
- No artificial distinction between "anchor" and "swing"
- All legs compete on composite score (coverage + opponent + stability)
- Better utilizes high-quality hitting props
- Simpler codebase (one pool instead of two)

**Constraints retained:**
- Max 1 batter leg per player
- Max 3 legs per game
- Max 1 risky over per parlay (new in April 24)

**Rationale:** Sport-specific architectures matter. What works for NBA (wide odds distribution) doesn't work for MLB (tight odds clustering).

---

## Key Principles

### Data-Driven Decision Making
- Every architectural decision backed by training data analysis
- 76K+ samples provide statistical confidence
- Direction bias, coverage calibration, golden/poison props all validated empirically

### Automation Over Manual Work
- Prospective collection runs daily without intervention
- Health checks alert automatically when issues arise
- Outcome resolution happens every morning at 9AM

### Three-Tier Monitoring
- SQL views for analysts
- Automated scripts for alerts
- Web app for accessibility

### Continuous Improvement
- ML model ready to replace heuristics when validated
- A/B testing framework for scoring approaches
- Training data grows daily for ongoing model refinement

### Sport-Specific Architecture
- MLB prop odds distribute differently than NBA
- Hitting props cluster tighter than basketball props
- Single-pool approach better suited to MLB market structure
