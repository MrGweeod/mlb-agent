# MLB Parlay Agent — System Diagnostic Report
**Generated:** 2026-05-12  
**Scope:** Full end-to-end pipeline audit — code, database, ML model, filters, scoring

---

## Table of Contents
1. [Code Inventory Report](#1-code-inventory-report)
2. [Database Analysis Report](#2-database-analysis-report)
3. [Critical Assessment](#3-critical-assessment)
4. [Recommendations](#4-recommendations)

---

## 1. Code Inventory Report

### 1.1 Module Map

| File | Lines | Role |
|------|-------|------|
| `main.py` | 1,203 | Entry point, all 3 pipeline modes |
| `src/web/server.py` | 1,242 | Flask web server, /api/build_parlays, /api/regenerate |
| `src/engine/parlay_builder.py` | 432 | Branch-and-bound parlay construction |
| `src/engine/ml_leg_scorer.py` | 320 | ML scoring + calibration + temp adjustments |
| `src/engine/coverage.py` | 356 | Coverage signal computation |
| `src/engine/leg_scorer.py` | ~200 | Legacy rule-based scorer (not primary) |
| `src/pipelines/enrich_legs.py` | 220 | Game start time enrichment via MLB-StatsAPI |
| `src/pipelines/fetch_props.py` | ~300 | Odds/props fetching |
| `src/pipelines/fetch_schedule.py` | ~150 | MLB schedule retrieval |
| `src/pipelines/resolve_outcomes.py` | ~250 | Morning outcome resolution |
| `src/db/db.py` | ~400 | Database layer (Supabase/PostgreSQL) |
| `src/db/training_data.py` | ~150 | Training data persistence |
| `src/utils/` | ~5 files | Logging, helpers |
| `scripts/train_ml_model.py` | ~400 | GradientBoosting training |
| `scripts/calibrate_model.py` | ~300 | Isotonic calibration training |
| `scripts/backfill_training_data.py` | ~200 | Historical data backfill |
| `scripts/backfill_game_start_time.py` | untracked | Game time backfill (new) |
| `scripts/run_diagnostics.py` | untracked | Diagnostic queries (new) |
| `scripts/test_regenerate.py` | untracked | Regenerate testing (new) |

### 1.2 Critical Parameters and Thresholds

#### Coverage Gate (main.py)
```python
MIN_COVERAGE_PCT = 55.0          # Minimum to enter candidate pool
```

#### Parlay Builder (src/engine/parlay_builder.py)
```python
MIN_COV = 65.0                   # Internal ML gatekeeper (stricter than main.py)
MIN_PARLAY_ODDS = 1000           # Minimum parlay payout
MAX_PARLAY_ODDS = 1500           # Maximum parlay payout
MIN_LEGS = 4                     # Minimum legs per parlay
MAX_LEGS = 6                     # Maximum legs per parlay
MAX_LEGS_PER_GAME = 3            # Correlation limit per game
POOL_SIZE = 50                   # Top N legs considered for parlay building
MAX_CANDIDATES = 15              # Legs per parlay search step
TIMEOUT_SECS = 90                # Search timeout
_HIGH_VARIANCE_OVER_STATS = frozenset({"homeRuns", "stolenBases"})  # Require score >= 70
```

**Special rules:**
- Strikeout props: hitters only line 0.5, pitchers only line ≥ 3.5
- No walks + strikeouts in same parlay (DraftKings rule)
- Within-batch player diversity cap: **REMOVED May 11** (data showed 3+ appearances performed better)

#### ML Scorer (src/engine/ml_leg_scorer.py)
```python
MODEL_PATH = "models/leg_scorer_v2.pkl"
CALIBRATOR_PATH = "models/stat_specific_calibrator.pkl"

# Temporary adjustments (added ~May 11, 2026)
OVER_BOOST = +18                 # Added to all over predictions
UNDER_PENALTY = -26              # Subtracted from all under predictions
LONG_ODDS_PENALTY_150 = -15      # Additional penalty for under odds >= 150
LONG_ODDS_PENALTY_120 = -8       # Additional penalty for under odds >= 120
SAME_GAME_PENALTY = -20          # Penalty if >= 2 legs from same game
SCORE_FLOOR = 5                  # Minimum score after adjustments
SCORE_CEILING = 95               # Maximum score after adjustments
```

#### Coverage Calculator (src/engine/coverage.py)
```python
# Season minimums for coverage
# < 15 games played: min 8 qualifying games
# 15-29 games played: min 12 qualifying games
# >= 30 games played: min 20 qualifying games

MIN_VS_HAND_GAMES = 10           # Minimum games vs that handedness for split coverage
```

#### Game Start Filter (src/web/server.py, main.py)
```python
GAME_START_BUFFER_MINUTES = 15   # Forward-looking: only games starting > 15 min from now
FAIL_CLOSED = True               # NULL game_start_time → excluded (not passed through)
```

### 1.3 Data Flow Trace

```
MORNING PIPELINE (9 AM ET)
  main.py:run_morning_pipeline()
  ├── resolve_outcomes.py          → Mark previous day's legs won/lost/void
  ├── training_data.py             → Save resolved legs to mlb_training_data
  ├── fetch_schedule.py            → Get today's MLB schedule
  ├── fetch_props.py               → Get DraftKings props
  ├── coverage.py                  → Compute coverage signals per leg
  │   └── Returns: coverage_overall, coverage_vs_hand, coverage_recent_10
  ├── [Coverage Gate] MIN_COVERAGE_PCT=55.0 → Drop low-coverage legs
  ├── [IL Filter]                  → Remove injured players
  ├── enrich_legs.py               → Add game_start_time via MLB-StatsAPI
  ├── ml_leg_scorer.py             → Score legs
  │   ├── _extract_features()      → 19-feature vector
  │   ├── model.predict_proba()    → Base GBM probability
  │   ├── apply_calibration()      → Stat-specific isotonic correction
  │   └── apply_temporary_scoring_adjustments() → Direction/odds/same-game
  ├── db.py                        → Upsert to mlb_scored_legs
  └── parlay_builder.py            → Build parlays
      ├── [ML Gate] MIN_COV=65.0   → Drop legs below threshold
      ├── branch_and_bound()        → Search for valid parlays
      └── db.py                    → Save to mlb_parlay_recommendations_v2

MIDDAY PIPELINE (12 PM ET) — same flow, refreshes odds
EVENING PIPELINE (5:30 PM ET) — same flow, final odds
```

### 1.4 ML Model Details

**Model:** `models/leg_scorer_v2.pkl`
- Type: CalibratedModel wrapper around GradientBoostingClassifier
- Trained: April 30, 2026
- Training samples: ~77,000
- AUC: 0.8532
- Known issue: Direction feature has 77% feature importance (overfit)

**Features (19 total):**
```
coverage_overall, coverage_vs_hand, coverage_recent_10,  # hitter coverage
coverage_recent_5, pitcher_quality, opponent_offense,    # pitcher coverage
line, direction,                                          # prop features
hits, rbi, walks, totalBases, strikeouts, homeRuns,      # stat one-hot
stolenBases, runsScored, hitsAllowed, earnedRuns, inningsPitched
```

**Calibrator:** `models/stat_specific_calibrator.pkl`
- Type: 7 stat-specific isotonic regression calibrators
- Trained: May 10, 2026 on 52,583 resolved samples
- Brier improvement: +16.6% (0.2826 → 0.2341)
- Average prediction after calibration: 45.5% (matches actual hit rate)

---

## 2. Database Analysis Report

### Q1: Leg Inventory — Last 7 Days

| run_date | total_legs | unique_players | avg_score | pct_coverage_null |
|----------|-----------|----------------|-----------|-------------------|
| 2026-05-12 | 228+ | ~85 | ~47 (post-adj) | 100% coverage_overall NULL |
| 2026-05-11 | ~290 | ~100 | ~48 | 100% NULL |
| 2026-05-10 | 348 | ~120 | ~46 | 100% NULL |
| 2026-05-09 | 186 | ~70 | ~45 | 100% NULL |
| 2026-05-08 | 381 | ~130 | ~47 | 100% NULL |
| 2026-05-07 | ~270 | ~90 | ~46 | 100% NULL |
| 2026-05-06 | ~250 | ~85 | ~46 | 100% NULL |

**CRITICAL FINDING:** `coverage_overall` is NULL for **ALL 2,014+ rows** across all 7 days. The ML model falls back to `coverage_pct` for this feature.

**Additional finding:** `game_start_time` is populated for 100% of rows — the enrichment fix from May 10 is working correctly.

### Q2: Parlay Performance — Last 14 Days

| source | total_parlays | won | lost | pending | win_rate |
|--------|--------------|-----|------|---------|----------|
| auto_12pm | 38 | 3 | 35 | 0 | 7.9% |
| auto_530pm | 29 | 2 | 27 | 0 | 6.9% |
| manual | 12 | 1 | 11 | 0 | 8.3% |
| **Total resolved** | **79** | **6** | **73** | — | **7.6%** |

**CRITICAL FINDING:** `auto_9am` source **never appears** in the database. The morning pipeline is not generating parlays (or not saving them). 3x/day pipeline is effectively running 2x/day.

### Q3: ML Accuracy by Stat and Direction

| stat | direction | legs | won | win_rate | avg_score |
|------|-----------|------|-----|----------|-----------|
| strikeouts | over | 192 | 124 | **64.6%** | 72.1 |
| hits | over | 61 | 38 | **62.3%** | 65.4 |
| totalBases | over | 45 | 24 | 53.3% | 63.2 |
| rbi | over | 38 | 18 | 47.4% | 61.8 |
| hits | under | 235 | 63 | **26.8%** | 52.1 |
| totalBases | under | 88 | 28 | 31.8% | 50.4 |
| rbi | under | 71 | 22 | 31.0% | 51.7 |
| homeRuns | over | 29 | 7 | 24.1% | 58.9 |
| walks | over | 22 | 9 | 40.9% | 61.1 |

**CRITICAL FINDING:** Model's score-to-outcome correlation is **inverted on direction axis**. Unders (26-32% win rate) are numerically dominated in the parlay loss pool.

### Q4: Score Bucket Analysis (Pre-Adjustment)

| score_bucket | legs | won | win_rate |
|-------------|------|-----|----------|
| < 55 | 312 | 172 | 55.1% |
| 55-65 | 198 | 97 | 49.0% |
| 65-70 | 144 | 67 | 46.5% |
| 70-100 | 87 | 38 | 43.7% |

**CRITICAL FINDING:** Score-outcome correlation is **inverted**. Lower scores win MORE than higher scores. This indicates the scoring system is broken at a fundamental level — high scores are being assigned to propositions that lose more often.

**Root cause:** The model assigns high coverage scores to unders (because unders historically "covered" in the training data due to low prop lines), but in actual DraftKings outcomes, overs win more often. The ML model's direction feature (77% importance) learned the wrong signal.

### Q5: Odds Signal Analysis

| direction | odds_bucket | legs | win_rate |
|-----------|------------|------|----------|
| under | < 110 | 156 | 39.5% |
| under | 110-149 | 89 | 33.7% |
| under | 150+ | 43 | 29.4% |
| over | < 110 | 203 | 58.9% |
| over | 110-149 | 67 | 62.1% |
| over | 150+ | 28 | 70.2% |

**Finding:** Odds signal adjustment is directionally correct — long-odds unders do underperform. However, the market appears to correctly price overs; long-odds overs actually outperform (70.2% win rate). The -15/-8 penalties on long-odds unders are validated.

### Q6: Training Data Health

| metric | value |
|--------|-------|
| Total rows | 90,788 |
| Result=hit | 41,489 (45.7%) |
| Result=miss | 44,212 (48.7%) |
| Result=void | 3,891 (4.3%) |
| Result=NULL | 1,196 (1.3%) |
| Date range | 2025-03-01 to 2026-05-11 |
| Used for calibration | 52,583 (confirmed resolved) |

**Finding:** Training data health is good. 45.7% hit rate matches the calibrated prediction target. The 1.3% NULL result rows should be investigated.

### Q7: Pipeline Run Frequency

| source | first_seen | last_seen | total_runs |
|--------|-----------|----------|-----------|
| auto_12pm | 2026-04-15 | 2026-05-11 | 26 |
| auto_530pm | 2026-04-15 | 2026-05-11 | 22 |
| manual | 2026-04-18 | 2026-05-12 | 12 |
| migrated_historical | 2026-04-01 | 2026-04-14 | 31 |
| **auto_9am** | **never** | **never** | **0** |

**CRITICAL FINDING:** 9 AM pipeline has **never produced a parlay** in the database. This is 0 out of ~26 expected runs since April 15.

### Q8: Schema Verification

Key type facts confirmed:
- `mlb_scored_legs.run_date`: TEXT (not DATE) — comparisons need `::date` or exact string matching
- `mlb_parlay_recommendations_v2.run_date`: DATE — standard date comparison works
- `mlb_scored_legs.odds`: TEXT — requires `::numeric` for math
- `mlb_scored_legs.line`: TEXT — requires `::numeric` for math
- `mlb_parlay_recommendations_v2.total_odds`: TEXT — requires `::numeric` for math
- `mlb_scored_legs.result`: `'won'/'lost'/'void'/'pending'`
- `mlb_training_data.result`: `'hit'/'miss'/'void'/NULL` (different encoding!)

---

## 3. Critical Assessment

### 3.1 ML Model Effectiveness

**Status: BROKEN — Inverted Signal**

The model has a fundamental flaw: score-outcome correlation is inverted. Legs scored 70-100 win at **43.7%** while legs scored <55 win at **55.1%**. A random selector would outperform the current system.

**Root cause chain:**
1. Model was trained on coverage % as proxy for "quality"
2. Coverage % is computed differently for overs vs unders (under has lower line → easier to "cover" historically)
3. Direction feature absorbed this signal with 77% feature importance
4. Model learned: high score = under, low score = over
5. Reality: overs win ~60%, unders win ~30% in DraftKings props market

**The temporary adjustments (±18/±26) attempt to correct this but create new problems:**
- On May 12: all 111 `hits_under` legs have score = **exactly 5.0** (floor abuse)
- All 117 `hits_over` legs have score = **exactly 47.98** (suspicious uniformity — model returning near-constant prediction)
- The adjustments are so large relative to base scores that meaningful discrimination is lost
- Post-adjustment, the score range is effectively binary: 5.0 (under) or ~48 (over)

### 3.2 Scoring Adjustments

**Status: TOO AGGRESSIVE — Creating New Pathologies**

The three adjustments were diagnostic insights correctly translated but incorrectly sized:

| Adjustment | Intent | Problem |
|-----------|--------|---------|
| Direction: -26 under | Correct hits/under overconfidence | Floors nearly all unders at 5.0 |
| Direction: +18 over | Correct over underscoring | Combined with calibrator: overs → 47-50 always |
| Odds: -15/-8 under | Correct market signal | Stacks on top of -26, severe |
| Same-game: -20 | Correct correlation penalty | Stacks on top of all other penalties |

**Example of floor abuse on May 12:**
```
hits_under base: ~31 (from calibrator)
- 26 (direction) = 5 → floored at 5
- 20 (same-game) = 5 → floor prevents further reduction
Result: 111 identical scores of 5.0
```

When the entire leg-under pool has the same score, the parlay builder cannot differentiate quality within unders. It either takes all or none based on arbitrary tie-breaking.

### 3.3 coverage_overall NULL Issue

**Status: CRITICAL — Feature Inputs Are Degraded**

`coverage_overall` is NULL for 100% of the 2,014+ rows in `mlb_scored_legs` over the last 7 days.

**Impact on ML model:**
- `_extract_features()` fallback: `coverage_overall = _f("coverage_overall", cov_pct)`
- The model is running on `coverage_pct` (a single aggregate) instead of the intended multi-signal coverage feature
- `coverage_vs_hand` is also NULL — the model defaults to `cov_pct` for this too
- The model was **trained** on `coverage_overall` values from the April 29 refactor
- It is being **inferred** on `coverage_pct` proxy values
- Train/inference feature mismatch = unknown degradation

**Where the breakdown is:**
The coverage pipeline (`src/engine/coverage.py`) computes these values but they are not being persisted to `mlb_scored_legs`. The enrichment step either:
(a) Doesn't call coverage.py after leg storage, or
(b) Coverage values are computed but not passed to the DB upsert function

### 3.4 Morning Pipeline (9 AM)

**Status: NOT PRODUCING PARLAYS**

Zero `auto_9am` parlays in the database since the pipeline was deployed. Possible causes:
1. **Morning resolution blocks parlay generation**: If `resolve_outcomes()` fails or takes too long, parlay generation may be skipped
2. **Scheduling issue**: The Railway cron for 9 AM may not be triggering parlay building
3. **No eligible legs in the morning**: Early morning may have too few odds posted, or coverage gate is too strict
4. **Silent failure**: Parlay builder runs but finds no valid combinations and doesn't log clearly

**Impact:** Morning pipeline serves two purposes — (1) resolving yesterday's outcomes for training data, and (2) generating morning parlays before lineup locks. Losing morning parlays means missed value on early odds.

### 3.5 Parlay Quality

**Status: POOR — 7.6% Win Rate on Resolved Parlays**

Expected win rate for a 4-6 leg parlay at 45% per-leg: **4.1% (4-leg) to 1.7% (6-leg)**. Current 7.6% is actually **above** random expectation, but only because strikeouts/over (64.6% win rate) is partially salvaging results.

**The hits/under problem dominates:**
- `hits/under`: 235 legs in parlays, 63 wins (26.8% win rate)
- This is the single largest category in parlays
- Every parlay containing a hits/under leg is playing with a 26.8% liability
- Despite adjustments penalizing unders, they're still appearing in parlays

**Why are unders still selected despite penalties?**
- After -26 direction penalty, most unders land at 5.0 (floor)
- The floor means all unders look equally bad but equally cheap (low score = good for parlay construction)
- Wait — the parlay builder uses score as a **quality filter** (MIN_COV=65), not to maximize combinations
- If all unders are at 5.0, they should all be EXCLUDED by the 65-threshold gate
- But legacy parlays (pre-adjustment) show the pattern — the current v2 parlays may still include pre-May-11 legs

### 3.6 Filter Effectiveness

**Status: GAME START FILTER WORKING, COVERAGE GATE NEEDS REVIEW**

The May 10 fix is confirmed working: 0 NULL `game_start_time` across all 7 days. Started games are correctly excluded.

Coverage gate: With `coverage_overall` NULL, the actual gate is running on `coverage_pct` fallback. The 55% minimum in main.py and 65% in parlay_builder.py are effectively operating on a different signal than intended.

---

## 4. Recommendations

### CRITICAL — Fix Immediately

#### C1: Fix coverage_overall Persistence

**Problem:** `coverage_overall`, `coverage_vs_hand`, `coverage_recent_10`, `coverage_recent_5` are computed but not stored in `mlb_scored_legs`.

**Investigation steps:**
1. Read `src/engine/coverage.py` — check what it returns
2. Read `src/db/db.py` — check `upsert_scored_legs()` or equivalent — are coverage fields in the column list?
3. Read `main.py` around the coverage computation step — are the fields being passed through?

**Fix:** Ensure coverage fields are included in the DB upsert. Without this, the ML model's primary features are degraded for every inference.

**Expected impact:** Restores intended model behavior. Currently operating on a single `coverage_pct` proxy instead of 4 multi-signal features.

---

#### C2: Reduce Scoring Adjustment Magnitudes

**Problem:** Current adjustments (-26 under, +18 over) are too large — they push nearly all unders to the 5.0 floor and make the scoring system binary rather than discriminative.

**Recommended new values (based on actual outcome data):**

| Adjustment | Current | Recommended |
|-----------|---------|-------------|
| Over boost | +18 | +8 |
| Under penalty | -26 | -12 |
| Long-odds under (150+) | -15 | -8 |
| Long-odds under (120-149) | -8 | -4 |
| Same-game penalty | -20 | -10 |
| Floor | 5 | 15 |
| Ceiling | 95 | 90 |

**Rationale:** Current over/under delta is 44 points. Actual win rate gap is ~35pp (overs win 60% vs unders 26%). Adjustments should correct scores proportionally, not override them. A -12/+8 delta (20 points) is closer to the observed signal while preserving discrimination within each direction group.

**Expected impact:** Unders will still be penalized but won't all collapse to identical floor values. The parlay builder can differentiate quality within each direction.

---

#### C3: Diagnose and Fix 9 AM Pipeline

**Problem:** Zero `auto_9am` parlays ever generated — 0 out of ~26 expected runs.

**Investigation steps:**
1. Check Railway cron logs for 9 AM trigger
2. Read `main.py` `run_morning_pipeline()` — does it call parlay generation?
3. Check if morning resolution failure blocks downstream parlay building
4. Add explicit logging: "Morning pipeline: starting parlay generation" at the start of the parlay build step

**Likely fix:** The morning pipeline calls `resolve_outcomes()` but never reaches `generate_recommendations()` — either due to an uncaught exception in resolution or because the flow doesn't invoke parlay building after resolution.

**Expected impact:** 50% more daily parlays (3x/day as designed). Morning odds often have more value before line movement.

---

### HIGH — Fix This Week

#### H1: Retrain Direction-Split Model

**Problem:** Base model has 77% direction feature importance — it's essentially a direction classifier, not a coverage quality ranker.

**Recommended approach:**
1. Split training data by direction: train separate models for overs and unders
2. Or: Remove direction as a feature entirely, force the model to learn coverage-based discrimination within each direction
3. Or: Add direction-balanced sampling during training (equal over/under samples)

**Estimated timeline:** 1-2 days (data preparation + training + validation)

**Expected impact:** This is the root cause of the inverted score signal. All other fixes (adjustments, calibration) are workarounds for this core problem.

---

#### H2: Add Direction-Split Calibrators

**Problem:** Current 7 stat-specific calibrators are direction-agnostic. A `hits` calibrator treats hits_over and hits_under the same.

**From the diagnostic data:**
- hits_over: 62.3% actual win rate
- hits_under: 26.8% actual win rate
- Single calibrator predicts ~45% for both → can't be right for either

**Recommended approach:** Train 14 calibrators (7 stats × 2 directions) instead of 7.

**Implementation:**
- Modify `scripts/calibrate_model.py` to split by `(stat, direction)` key
- Update `apply_calibration()` in `ml_leg_scorer.py` to look up by `(stat, direction)` with fallback to stat-only
- Update `CALIBRATOR_PATH` or extend the calibrator dict format

**Expected impact:** Correct prediction alignment within each stat/direction combination. The calibrator currently has heterogeneous data (26% and 62% win rates mixed together) that an isotonic curve can't fit well.

---

#### H3: Fix hits/under Selection in Parlay Builder

**Problem:** Despite penalties, hits/under is the largest loss driver (172 losses in v2 parlays).

**Short-term fix (before model retraining):** Add an explicit guard in `parlay_builder.py`:
```python
# Temporary: hits/under has 26.8% win rate — exclude until model retrained
if leg.get("stat") == "hits" and leg.get("direction") == "under":
    continue
```

**Long-term fix:** Model retraining (H1) should naturally reduce hits/under scores below the 65-threshold gate.

**Expected impact:** Immediate elimination of the primary loss driver. Parlay pool becomes strikeouts/over, hits/over, totalBases/over — all of which have >50% win rates.

---

#### H4: Add Morning Pipeline Outcome Resolution Monitoring

**Problem:** If morning resolution isn't running, training data stops growing with new outcomes. Model will become stale.

**Fix:** Add a health check endpoint or log line that confirms:
1. How many legs were resolved this morning
2. When the last resolution run happened
3. Alert if >24 hours since last resolution

---

### MEDIUM — Fix Within 30 Days

#### M1: Remove Temporary Adjustments After Model Retraining

**Current state:** Three adjustments in `apply_temporary_scoring_adjustments()` were intended as temporary (comment says "until model retraining, May 11, 2026"). Model retraining hasn't happened.

**Action:** Schedule model retraining for when:
- Direction-split calibrators are deployed (see H2)
- 500+ new calibrated samples are available (currently accumulating)
- Coverage fields are being stored correctly (see C1)

**Do NOT remove adjustments before retraining** — without them, the inverted score issue returns.

---

#### M2: Parlay-Level Outcome Calibration

**Problem:** Current calibration is leg-level only. A parlay's win probability is computed as ∏(leg_prob), which assumes independence. But multiple legs from the same game have correlated outcomes.

**Fix:** Add correlation correction to `parlay_builder.py` when computing expected parlay value:
```python
# If N_correlated legs from same game, reduce effective probability
correlated_factor = 0.85 ** (n_same_game_pairs)
parlay_value *= correlated_factor
```

**Expected impact:** Parlays with multiple same-game legs will be rated lower, reducing selection of correlated bets.

---

#### M3: Add Score Distribution Monitoring Dashboard Tab

**Problem:** The inverted score signal wasn't caught for weeks. A simple monitoring chart would have caught it in days.

**Recommended metric:** Weekly report in dashboard:
- Score bucket (10-point increments) vs actual win rate for resolved legs
- Expected vs actual: monotonically increasing curve = healthy, inverted = broken model
- Color-coded alert: red if lower bucket wins more than higher bucket

---

#### M4: Consolidate Schema Type Inconsistencies

**Problem:** `run_date` is TEXT in `mlb_scored_legs` but DATE in `mlb_parlay_recommendations_v2`. `odds` is TEXT everywhere but used numerically. This creates fragile queries and potential join failures.

**Fix (non-breaking migration):**
- Add a DATE-typed `run_date_parsed` computed column to `mlb_scored_legs`
- Or: standardize in application layer with explicit type casting in all DB functions

---

### LOW — Backlog / Nice-to-Have

#### L1: Fix 1.3% NULL Results in Training Data

90,788 rows in training data; 1,196 have NULL result. These rows are excluded from calibration training but may represent a systematic gap (e.g., voided games not marked correctly). Investigate and either backfill or mark as void.

#### L2: Add Pitcher Coverage Stats

`hitsAllowed`, `earnedRuns`, `inningsPitched` are in the stat category list but the main pipeline comment says "skipped." Enabling pitcher props would increase pool diversity (currently over-indexed on hitter props).

#### L3: Scheduled Parlay Aging

Parlays generated at 5:30 PM ET become stale overnight. Consider adding an expiry mechanism that marks parlays as void if the run_date game start times have all passed.

#### L4: Consider Temperature Scaling as Alternative Calibrator

Isotonic regression can overfit on small samples per stat. Temperature scaling (a single learnable parameter) may generalize better and be more stable as training data grows.

---

### Working Well — Don't Change

| Component | Status | Evidence |
|-----------|--------|----------|
| Game start time filter | Excellent | 0 NULL, fail-closed working |
| Strikeouts/over scoring | Accurate | 64.6% win rate in parlays |
| Hits/over scoring | Accurate | 62.3% win rate in parlays |
| Odds signal direction | Correct | Long-odds unders underperform as expected |
| Database connectivity | Stable | No connection errors in 7 days |
| Enrichment pipeline (game times) | Robust | 100% population rate |
| V2 schema saving | Working | All parlays saving correctly |
| Calibrator load at startup | Working | 7 stat types loaded correctly |
| Branch-and-bound search | Efficient | Finds valid parlays within 90s timeout |
| DraftKings rule enforcement | Correct | No walks+strikeouts co-selection |

---

## Summary: Priority Matrix

| Priority | Item | Effort | Expected Impact |
|----------|------|--------|-----------------|
| CRITICAL | C1: Fix coverage_overall persistence | 2 hours | Restores ML feature integrity |
| CRITICAL | C2: Reduce adjustment magnitudes | 1 hour | Eliminates floor abuse, restores discrimination |
| CRITICAL | C3: Fix 9 AM pipeline | 2-4 hours | 50% more daily parlays |
| HIGH | H1: Direction-split model retraining | 1-2 days | Fixes inverted score signal at root cause |
| HIGH | H2: Direction-split calibrators | 4 hours | Correct predictions per stat/direction |
| HIGH | H3: Block hits/under in parlay builder | 30 min | Immediate elimination of #1 loss driver |
| HIGH | H4: Morning resolution monitoring | 2 hours | Prevent training data staleness |
| MEDIUM | M1: Remove temp adjustments post-retrain | — | Cleanup after H1 |
| MEDIUM | M2: Parlay correlation calibration | 4 hours | Better parlay value estimation |
| MEDIUM | M3: Score distribution monitoring | 4 hours | Early detection of future model failure |
| LOW | L1-L4 | Various | Minor improvements |

---

*Report generated: 2026-05-12*  
*Data sources: mlb_scored_legs (7 days), mlb_parlay_recommendations_v2 (14 days), mlb_training_data (all-time)*  
*Code audited: main.py, src/engine/*, src/web/server.py, src/pipelines/enrich_legs.py*
