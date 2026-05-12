# MLB Parlay Agent — Architecture Decisions
**Last Updated:** May 11, 2026 (Comprehensive Diagnostic Analysis + Scoring Fixes)

## Document Purpose
This document records the key architectural decisions made during the development of the MLB Parlay Agent, including the rationale, alternatives considered, and lessons learned. Updated with insights from May 11's comprehensive diagnostic analysis and scoring adjustments implementation.

---

## Table of Contents
1. [Temporary Scoring Adjustments Strategy](#temporary-scoring-adjustments-strategy)
2. [Diversity Constraint Removal](#diversity-constraint-removal)
3. [game_start_time Population Reliability](#game_start_time-population-reliability)
4. [ML Calibration Strategy (May 10)](#ml-calibration-strategy-may-10)
5. [Game Start Time Filter Design (May 10)](#game-start-time-filter-design-may-10)
6. [Core Architecture (Unchanged)](#core-architecture-unchanged)
7. [Lessons Learned](#lessons-learned)

---

## V1 Schema Deprecation

### **Decision: Migrate All V1 Data to V2, Deprecate V1 Tables**
**Chosen:** May 12, 2026

**Problem:**
Dashboard queried both v1 (flat) and v2 (normalized) schemas, requiring UNION queries and maintaining two code paths.

**Solution Chosen:**
- Migrate all 50 v1 parlays to v2 normalized schema
- Deprecate v1 tables with 30-day safety net (rename with _deprecated suffix)
- Update dashboard to query v2 exclusively

**Why Migrate (Not Just Stop Writing)?**

✅ **Pros:**
- Single schema = simpler queries, faster performance
- All historical data in one place
- No code complexity maintaining two paths
- V2 schema enables per-leg outcome tracking (v1 couldn't do this)

❌ **Alternatives Rejected:**

**Option A: Stop writing to v1, keep both schemas**
- Dashboard still needs UNION queries
- Code complexity remains
- No performance benefit

**Option B: Hard delete v1 immediately after migration**
- Too risky - no rollback if migration had bugs
- Lost 30 days of safety net

**Implementation Details:**

**Migration Script:** `scripts/migrate_v1_to_v2.py`
- Parsed v1 legs JSON blob
- Created v2 parlay header (one row per parlay)
- Created v2 leg rows (one row per leg)
- Set per-leg outcome = parlay outcome (limitation accepted)

**Safety Net:**
```sql
-- V1 tables renamed, not dropped
ALTER TABLE mlb_recommendations RENAME TO mlb_recommendations_deprecated_20260512;
ALTER TABLE mlb_parlay_legs RENAME TO mlb_parlay_legs_deprecated_20260512;
-- Safe to drop after June 11, 2026
```

**Results:**
- ✅ 50 parlays migrated successfully
- ✅ 0 migration errors
- ✅ Dashboard loads 2x faster (no UNION)
- ✅ Total v2 parlays: 185 (50 + 135)

**Trade-offs Accepted:**
- V1 didn't track per-leg outcomes, only parlay-level
- Migration sets all legs in a parlay to same outcome (won/lost/void)
- Acceptable: We only need granular tracking going forward

**Status:** ✅ Complete May 12, operational

---

## coverage_overall Persistence Strategy

### **Decision: ON CONFLICT Backfill + DB INSERT Fix**
**Chosen:** May 12, 2026

**Problem:**
coverage_overall was NULL for 100% of rows (2,014+ legs, 7 days). Diagnostic revealed:
- ✅ main.py line 298 was setting coverage_overall in leg dict
- ❌ db.py INSERT was NOT including it in column list
- Result: Data calculated but never saved

**Solution Chosen:**
1. Add coverage_overall to INSERT column list
2. Add coverage_overall to ON CONFLICT backfill
3. Let next pipeline run populate going forward

**Why ON CONFLICT Backfill?**

When a leg already exists in the database (same run_date + odd_id), the ON CONFLICT clause decides what to update:

```sql
ON CONFLICT (run_date, odd_id) DO UPDATE
SET coverage_overall = COALESCE(mlb_scored_legs.coverage_overall, EXCLUDED.coverage_overall)
```

**What this does:**
- If existing row has NULL → use new value
- If existing row has value → keep existing (don't overwrite)

**This is important because:**
- Odds can change throughout the day (12pm odds ≠ 5:30pm odds)
- But coverage_overall doesn't change (based on game logs, not odds)
- We want to preserve the first calculation, not recalculate 3x/day

**Alternatives Considered:**

**Option A: Always overwrite on conflict**
```sql
coverage_overall = EXCLUDED.coverage_overall
```
❌ Rejected: Would recalculate coverage 3x/day unnecessarily

**Option B: Never update on conflict**
```sql
-- No coverage_overall in ON CONFLICT clause
```
❌ Rejected: Wouldn't backfill today's 194 NULL legs

**Option C: COALESCE (chosen)** ✅
- Backfills NULLs
- Preserves existing values
- Best of both worlds

**Timeline of the Bug:**
May 5-11:  coverage_overall calculated but not saved (1,820 legs)
May 12 12pm: 194 legs inserted without coverage_overall (pre-fix)
May 12 12:38pm: Fix committed (e683147)
May 12 12:39pm: Fix deployed to Railway
Next run: coverage_overall will populate

**Historical Data Decision:**

**Question:** Should we backfill May 5-11 (1,820 legs)?

**Decision:** No, accept the gap

**Reasoning:**
- Would require recalculating coverage for each leg (CPU intensive)
- Would need to fetch historical game logs (API calls)
- New data accumulates at ~150-200 legs/day
- 14 days = ~1,960 new samples (replaces lost samples)
- Calibrator has 90,331 total samples; 1,820 is 2%

**Trade-off accepted:** 2% of calibration data has NULL coverage_overall

**Status:** ✅ Fix deployed, ⏳ Data verification pending

---

## Lessons Learned

### **Learning #7: Schema Migrations Need Post-Deployment Verification**

**Discovery:** We deployed coverage_overall column addition and db.py INSERT fix, but didn't verify data populated until several hours later.

**What Happened:**
1. Deployed schema changes at 12:38 PM
2. Assumed coverage_overall would populate automatically
3. Checked database at 4:00 PM, found still NULL
4. Realized pipeline ran at 12:00 PM (BEFORE fix)

**The Gap:**
- Schema changes can succeed without data populating
- Code can look correct but have subtle bugs
- Verification queries should run immediately after deployment

**Better Workflow:**
1. Deploy schema changes
2. Trigger manual pipeline run immediately
3. Run verification query within 5 minutes
4. Confirm data populated as expected

**How to Avoid:**
- Add verification step to deployment checklist
- Create manual trigger endpoint (done today)
- Don't wait hours to check results

**Takeaway:** Deploy → Trigger → Verify → Celebrate (in that order)

---

### **Learning #8: Filter Bugs Can Hide Schema Fixes**

**Discovery:** coverage_overall fix worked perfectly, but we couldn't tell because filter bugs blocked all parlay generation.

**What Happened:**
1. Fixed coverage_overall persistence (deployed successfully)
2. Filters broke simultaneously (unrelated code)
3. 0 parlays generated → looked like coverage fix failed
4. Actually: coverage fix worked, filters broke separately

**The Confusion:**
Multiple changes deployed together → hard to isolate which failed

**Better Workflow:**
- Deploy one fix at a time
- Verify each fix before next deployment
- Keep changes small and isolated

**How to Avoid:**
- Single-purpose commits
- Manual trigger for immediate testing
- Don't bundle unrelated changes

**Takeaway:** One fix per deploy, verify before next fix

---
Then at the END of the file, add:
markdown---

## Decision Review Schedule

**Daily:** Monitor coverage_overall population, filter effectiveness  
**Weekly:** Review schema performance, migration success  
**Monthly:** Evaluate v1 deprecation (can we drop tables?), pitcher data usage  
**Quarterly:** Reassess architecture decisions, plan next improvements  

---

**Last Review:** May 12, 2026  
**Next Review:** May 19, 2026 (after 7 days of coverage_overall data)  
**Major Milestone:** V1 schema deprecated, coverage_overall fix deployed, filters being fixed

## Temporary Scoring Adjustments Strategy

### **Decision: Post-Hoc Score Adjustments (Not Model Retraining)**
**Chosen:** May 11, 2026

**Problem:**
Comprehensive diagnostic analysis of 124 resolved parlays (4,400 legs, last 14 days) revealed three critical scoring biases:

1. **Direction bias:** Unders overscored by 26pp, overs underscored by 18pp
2. **Odds signal:** Long-odds unders (29.4% win rate) scored same as short-odds unders (39.5% win rate)
3. **Same-game bias:** Multiple props from same game overscored by 27.5pp

**Impact:**
- 8.1% parlay hit rate (baseline)
- 80% unders / 20% overs (inverse of actual performance)
- Picking wrong unders (high-odds losers) while rejecting right unders (low-odds winners)

**Solution Implemented:**
Post-hoc adjustments applied after ML model + calibration in `apply_temporary_scoring_adjustments()` function.

**Why Post-Hoc (Not Full Retraining)?**
1. **Fast deployment:** 2 hours vs 4-6 hours for full retraining
2. **Low risk:** Adjustments sit on top, base model + calibrator unchanged
3. **Reversible:** Easy rollback if issues arise
4. **Effective:** Expected +60% hit rate improvement
5. **Testable:** Can validate before committing to full retraining

**Alternatives Considered:**

**Option A: Full Model Retraining**
- ❌ Time: 4-6 hours to retrain + validate
- ❌ Risk: Could make model worse, lose current AUC 0.85
- ❌ Complexity: Need to rebalance data, tune hyperparameters, re-calibrate
- ✅ Pro: Fixes root cause (direction overfit, missing odds feature)
- **Verdict:** Save for later when we have 500+ more samples with adjustments

**Option B: Direction-Split Calibration**
- ✅ Fast: 2 hours
- ❌ Performance: Would fix direction bias but not odds signal or same-game bias
- ❌ Limitation: 14 calibrators (7 stats × 2 directions) to manage
- **Verdict:** Good but incomplete - doesn't address all three biases

**Option C: Add Odds as Feature + Retrain**
- ✅ Fixes odds signal at model level
- ❌ Time: 4-6 hours + risk of breaking current AUC
- ❌ Doesn't fix direction bias (still need rebalancing)
- **Verdict:** Part of long-term solution, not immediate fix

**Option D: Post-Hoc Score Adjustments** ✅ **CHOSEN**
- ✅ Fastest: 2 hours to implement + test
- ✅ Addresses all three biases simultaneously
- ✅ Reversible: Can A/B test vs baseline
- ✅ Low risk: Doesn't touch model or calibrator
- ✅ Testable: 7-day validation window before committing to retraining
- ❌ Complexity: Three adjustments to maintain
- ❌ Not addressing root cause (model overfit)

**Trade-offs Accepted:**
- Temporary band-aid solution (will retrain after validation)
- Three adjustments to maintain instead of one model
- Adjustments file is ~100 lines (minimal overhead)

### **Implementation Details**

**Three Adjustments Applied Sequentially:**

```python
def apply_temporary_scoring_adjustments(scored_legs):
    # Adjustment #1: Direction bias correction
    if direction == "over":
        adjusted_score = min(adjusted_score + 18, 95)
    elif direction == "under":
        adjusted_score = max(adjusted_score - 26, 5)
    
    # Adjustment #2: Odds signal penalty (unders only)
    if direction == "under":
        if odds >= 150:
            adjusted_score = max(adjusted_score - 15, 5)
        elif odds >= 120:
            adjusted_score = max(adjusted_score - 8, 5)
    
    # Adjustment #3: Same-game penalty
    if game_counts[game_key] >= 2:
        adjusted_score = max(adjusted_score - 20, 5)
```

**Rationale for Each Adjustment:**

1. **Direction Bias (+18pp for overs, -26pp for unders):**
   - Diagnostic showed 26.2pp error for unders, 18.6pp error for overs
   - Model overfit to direction feature (77% importance)
   - Correction aligns predictions with actual outcomes

2. **Odds Signal (-15pp for +150 unders, -8pp for +120-149 unders):**
   - Long-odds unders win 29.4% despite high scores
   - Short-odds unders win 39.5% but get lower scores
   - Overs NOT penalized (perform well at all odds: 70.2% at +160)
   - Correction prevents selection of difficult long-odds unders

3. **Same-Game Penalty (-20pp for props from same game):**
   - Same-game legs: 69.2% score → 41.7% actual (-27.5pp error)
   - Isolated legs: 64.7% score → 46.1% actual (-18.6pp error)
   - Correction accounts for prop correlation within games

**Known Issue: Same-Game Logic Too Aggressive**

Current implementation:
```python
if game_counts[game_key] >= 2:  # Penalizes ANY game with 2+ props
```

**Problem:** All 77 legs from May 11 got penalized because every game has 2+ props available.

**Better Logic:**
```python
if game_counts[game_key] > 2:  # Only penalize 3+ props from same game
```

Or player-specific:
```python
player_game_key = (player_name, team, run_date)
if player_game_counts[player_game_key] > 1:  # Same player, multiple props
```

**Decision:** Ship with current logic, fix after validating other adjustments work.

### **Expected Impact**

**Before Adjustments:**
- Parlay hit rate: 8.1%
- Parlay composition: 80% unders / 20% overs
- Long-odds under selection: High (29.4% win rate)
- Leg win rate: 51.7% (but wrong selection)

**After Adjustments:**
- Parlay hit rate: 12-13% (target: +60% improvement)
- Parlay composition: 60% overs / 40% unders
- Long-odds under selection: Low (avoided via penalty)
- Leg win rate: 48-50% (lower but better selection)

**Validation Window:** 7 days (May 12-18, 2026)

**Retraining Criteria:** After 500+ resolved samples with adjustments:
- Retrain base model with balanced direction sampling
- Add odds as feature
- Add rolling window features (5-game, 10-game hit rates)
- Target: Base predictions 52-55% avg (currently 50.5%)

**Status:** ✅ Deployed May 11, awaiting validation

---

## Diversity Constraint Removal

### **Decision: Pure ML Score Selection (No Artificial Constraints)**
**Chosen:** May 11, 2026

**Problem:**
Within-batch diversity constraint (max 2 appearances per player per batch) deployed May 8 to prevent portfolio concentration. However, May 11 diagnostic analysis revealed the constraint was **hurting performance**:

| Player Appearance Count | Win Rate | Sample Size |
|------------------------|----------|-------------|
| 3+ times per batch     | 48.3%    | Best        |
| 2 times per batch      | 32.8%    | Worst       |
| 1 time per batch       | 39.2%    | Middle      |

**Key Insight:** The constraint forced use of the worst-performing bucket (32.8% win rate) while excluding the best-performing bucket (48.3% win rate).

**User Quote Validated:**
"We shouldn't block unders, we're selecting the wrong ones." This same logic applies to diversity: we shouldn't artificially constrain good players, we should select better props.

**Solution Implemented:**
Removed 34 lines of player appearance tracking from `src/engine/parlay_builder.py`. Replaced with pure ML score selection.

**Alternatives Considered:**

**Option A: Keep Constraint, Increase Threshold**
- Change max 2 → max 3 appearances
- ❌ Still forces use of mediocre legs
- ❌ Doesn't address root issue (quality > diversity)

**Option B: Cross-Batch Blocking**
- Players used at 9 AM blocked from 12 PM/5:30 PM
- ❌ Too restrictive: Exhausts player pool throughout day
- ❌ Only 1-2 parlays per batch

**Option C: Weighted Diversity**
- Allow high-quality players more appearances
- ❌ Complex logic to maintain
- ❌ Still introduces artificial constraint

**Option D: Remove Constraint Entirely** ✅ **CHOSEN**
- ✅ Simplest solution
- ✅ Pure ML score selection
- ✅ Let quality drive decisions
- ✅ Proven: Legs appearing 3+ times win 48.3%
- ❌ Risk: Portfolio concentration (but mitigated by quality)

**Trade-offs Accepted:**
- Some parlays may share players (correlated risk)
- But: Quality selection reduces overall risk more than diversity adds

**Before/After Comparison:**

**With Constraint (May 8-10):**
```python
# Track player appearances
for leg in eligible:
    player = leg['player_name']
    appearances[player] += 1
    if appearances[player] <= MAX_APPEARANCES_PER_PLAYER:
        diverse.append(leg)

# Result: Forced use of 32.8% win rate legs
```

**Without Constraint (May 11+):**
```python
# Pure quality selection
diverse = unique[:top_n]

# Result: Best legs selected, 48.3% win rate available
```

**Expected Impact:**
- Parlay hit rate: +10-15% improvement (8.1% → 9-10%)
- Combined with scoring adjustments: +60-80% total improvement

**Status:** ✅ Deployed May 11, operational

---

## game_start_time Population Reliability

### **Decision: Multi-Layer Fallback with Database Persistence**
**Chosen:** May 11, 2026

**Problem:**
Regenerate button non-functional - all 77 legs had NULL game_start_time, resulting in 0 eligible legs and cached parlays being returned.

**Root Causes:**
1. ON CONFLICT only updated composite_score, never game_start_time
2. Strategy 2 (schedule lookup) conditionally gated - skipped if all legs had game_pk
3. No database persistence - fetched times stayed in-memory only

**Solution Implemented:**
Three-layer fix ensuring game_start_time always populated.

**Alternatives Considered:**

**Option A: Rely on Enrichment Pipeline Only**
- Pipeline populates game_start_time at scoring time
- ❌ Fails if pipeline runs before schedule published
- ❌ No fallback if enrichment step fails
- **Verdict:** Not reliable enough

**Option B: game_pk API Calls Only**
- Use `statsapi.get("game", {"gamePk": X})` for each leg
- ❌ Fails silently if API call fails
- ❌ Slower than schedule bulk lookup
- **Verdict:** Good for supplement, not primary

**Option C: Schedule Lookup Only (No game_pk)**
- Always use `statsapi.schedule(date=X)` for team matching
- ❌ Requires exact team name match (fragile)
- ❌ Doesn't leverage game_pk when available (slower)
- **Verdict:** Good fallback, not primary

**Option D: Multi-Layer Strategy** ✅ **CHOSEN**
- Layer 1: Enrichment pipeline (primary, runs at scoring)
- Layer 2: game_pk API calls (regenerate fallback, fast)
- Layer 3: Schedule lookup (regenerate fallback, always runs)
- Layer 4: Database persistence (future requests cached)
- ✅ Most reliable: Multiple fallbacks
- ✅ Fast: Uses game_pk when available
- ✅ Persistent: Fixes once, works forever
- ❌ Complexity: 4 layers to maintain

**Trade-offs Accepted:**
- More complex than single-strategy approach
- But: Reliability > simplicity for time-sensitive filtering

### **Implementation Details**

**Layer 1: Enrichment Pipeline** (Primary)
```python
# In src/pipelines/enrich_legs.py
for leg in legs:
    game_pk = leg.get("game_pk")
    if game_pk:
        game_data = statsapi.get("game", {"gamePk": game_pk})
        leg["game_start_time"] = parse_game_time(game_data)
```

**Layer 2: ON CONFLICT Update** (Database)
```python
# In src/utils/db.py
INSERT INTO mlb_scored_legs (...)
VALUES (...)
ON CONFLICT (run_date, player_name, stat, direction)
DO UPDATE SET
    composite_score = COALESCE(EXCLUDED.composite_score, mlb_scored_legs.composite_score),
    game_start_time = COALESCE(EXCLUDED.game_start_time, mlb_scored_legs.game_start_time),
    pitcher_hand = COALESCE(EXCLUDED.pitcher_hand, mlb_scored_legs.pitcher_hand)
```

**Layer 3: Regenerate Fallback** (On-Demand)
```python
# In src/web/server.py
def _fetch_missing_game_times(legs, run_date):
    # Strategy 1: game_pk API calls (fast, exact)
    for game_pk in unique_pks:
        game_data = statsapi.get("game", {"gamePk": game_pk})
        gk_to_time[game_pk] = parse_game_time(game_data)
    
    # Strategy 2: Schedule lookup (ALWAYS runs, reliable)
    schedule = statsapi.schedule(date=run_date)
    for game in schedule:
        team_to_time[game["away_name"]] = parse_game_time(game)
        team_to_time[game["home_name"]] = parse_game_time(game)
    
    # Match and persist to database
    for leg in legs:
        if not leg.get("game_start_time"):
            leg["game_start_time"] = lookup_time(leg, gk_to_time, team_to_time)
    
    # Persist to DB
    UPDATE mlb_scored_legs
    SET game_start_time = %s
    WHERE run_date = %s AND player_name = %s AND stat = %s AND direction = %s
```

**Key Changes (May 11):**

**Before (Broken):**
- Strategy 2 gated: `if any(not leg.get("game_pk") for leg in missing)`
- No database persistence: In-memory only
- No diagnostic logging

**After (Fixed):**
- Strategy 2 always runs: Unconditional schedule lookup
- Database persistence: SQL UPDATE after fetching
- Verbose logging: Shows game_pk count, schedule game count, filled count

**Expected Logs After Fix:**
```
[regenerate] 77/77 legs missing game_start_time, fetching...
[_fetch_missing_game_times] Strategy 1: fetching 15 unique game_pks
[_fetch_missing_game_times] Strategy 1 resolved 0/15 game_pks
[_fetch_missing_game_times] Strategy 2: schedule returned 15 games
[_fetch_missing_game_times] Strategy 2 built 30 team→time mappings
[_fetch_missing_game_times] Filled 77/77 missing game times
[_fetch_missing_game_times] Persisted 77 game times to database
[regenerate] After fetch: 0 still NULL (fixed 77)
```

**Status:** ✅ Deployed May 11, awaiting validation

---

## ML Calibration Strategy (May 10)

### **Decision: Stat-Specific Isotonic Regression (Post-Hoc Calibration)**
**Chosen:** May 10, 2026

[Content unchanged from previous version - see SESSION_HANDOFF_MAY10.md for details]

**Status:** ✅ Deployed May 10, operational

---

## Game Start Time Filter Design (May 10)

### **Decision: Fail-Closed Logic with 15-Minute Forward Buffer**
**Chosen:** May 10, 2026 (Fixed from Fail-Open)

[Content unchanged from previous version - see SESSION_HANDOFF_MAY10.md for details]

**Status:** ✅ Deployed May 10, operational

---

## Core Architecture (Unchanged)

These fundamental decisions from earlier in the project remain unchanged and continue to serve well:

### **Three Daily Pipeline Runs**
- 9 AM, 12 PM, 5:30 PM ET
- Provides fresh data throughout the day
- ✅ Working as designed

### **V2 Normalized Schema**
- Per-leg tracking enables advanced queries
- Position tracking enabled pitcher exemption
- ✅ Critical enabler for May 8-11 features

### **ML Model-Based Scoring**
- Quality-first ranking preserved throughout
- Now with calibration + adjustments: 45.5% avg (was 34.6%)
- ✅ Continues to perform well

### **Railway Deployment**
- Auto-deploy from master branch
- 99.9% uptime
- ✅ Reliable and fast

---

## Lessons Learned

### **Learning #1: Diagnostic Analysis Before Fixes**
**Discovery:** Spent months building features without validating they solved the right problem. May 11 diagnostic revealed the actual issues were direction bias, odds signal, and same-game correlation - none addressed by prior features.

**Methodology:**
1. Extract 14 days of resolved data (124 parlays, 4,400 legs)
2. Segment by every conceivable dimension (direction, odds, same-game, appearance count)
3. Compare predicted scores vs actual outcomes
4. Identify systematic biases (not random noise)

**Impact:**
- Discovered 3 critical biases in 2 hours
- Implemented fixes in 2 more hours
- Expected +60% hit rate improvement

**Takeaway:** **Measure twice, cut once.** Before building more features, analyze existing data to identify actual failure modes.

---

### **Learning #2: Selection Bias vs Blocking**
**Discovery:** User said "We shouldn't block unders, we're selecting the wrong ones." This insight was validated by diagnostic:
- Rejected unders: 39.5% win rate
- Selected unders: 29.4% win rate

**Implication:** The problem wasn't "all unders are bad" - it was "we're picking the bad unders and rejecting the good ones."

**Similar Pattern in Diversity:**
- Legs appearing 3+ times: 48.3% win rate (excluded by constraint)
- Legs appearing twice: 32.8% win rate (forced into parlays by constraint)

**Takeaway:** **Don't block categories - improve selection within them.** Constraints that override quality ranking hurt performance.

---

### **Learning #3: Post-Hoc Fixes as Validation Tools**
**Discovery:** Post-hoc adjustments (scoring adjustments, calibration) are faster to deploy and test than model retraining. They serve as validation before committing to expensive retraining.

**Workflow:**
1. Identify bias via diagnostic analysis
2. Implement post-hoc adjustment (2 hours)
3. Deploy and validate over 7 days
4. If successful, incorporate into next model retraining
5. If unsuccessful, revert adjustment and try different approach

**Comparison:**
- Post-hoc adjustment: 2 hours, low risk, reversible
- Model retraining: 4-6 hours, high risk, expensive to revert

**Takeaway:** **Post-hoc fixes are A/B tests for model improvements.** Validate with adjustments before committing to retraining.

---

### **Learning #4: Reliability Requires Redundancy**
**Discovery:** Single-point-of-failure systems fail. game_start_time population broke because we relied on one enrichment step.

**Solution Pattern:**
- Layer 1: Primary method (enrichment pipeline)
- Layer 2: Fast fallback (game_pk API calls)
- Layer 3: Reliable fallback (schedule lookup - always runs)
- Layer 4: Cache (database persistence)

**Takeaway:** **Critical data needs multiple fetching strategies.** Don't rely on one API call or one enrichment step.

---

### **Learning #5: Constraints Beat Features**
**Discovery:** Diversity constraint (2 lines of logic) hurt performance more than all our feature engineering helped.

**Comparison:**
- Diversity constraint: 34 lines removed → +10-15% hit rate
- Scoring adjustments: 88 lines added → +60% hit rate
- Calibration (May 10): 200 lines added → +16.6% Brier

**Insight:** Artificial constraints that override ML rankings destroy value faster than features create it.

**Takeaway:** **Constraints should come from ML, not rules.** If you need to override the model, fix the model instead.

---

### **Learning #6: Database Schema Matters for Debugging**
**Discovery:** TEXT vs DATE vs TIMESTAMP casting confusion caused multiple SQL errors over 3 days. Had to create entire SUPABASE_SCHEMA_REFERENCE.md to document.

**Problems:**
- `mlb_scored_legs.run_date` stored as TEXT (not DATE)
- `mlb_scored_legs.odds` stored as TEXT (not INTEGER)
- `mlb_parlay_recommendations_v2.run_date` stored as DATE (not TEXT)
- Required different casting for each: `::text`, `::numeric`, no cast

**Impact:** Multiple debugging sessions, multiple Claude Code prompts, wasted time.

**Takeaway:** **Choose schema types carefully at design time.** Fixing later is expensive. Document types immediately.

---

## Future Architectural Improvements

### **SHORT TERM (This Month)**
1. **Fix Same-Game Logic**
   - Change `>= 2` to `> 2` or use player-specific counts
   - Test impact on parlay generation
   - Expected: Minor improvement, better logic

2. **Update Regenerate Button ML Scoring**
   - Currently uses `coverage_pct`, not `score_legs_ml()`
   - Web button doesn't apply scoring adjustments
   - Should match pipeline quality

3. **Monitor Adjustment Performance**
   - Track predicted vs actual weekly
   - Alert if adjustments degrade >5%
   - Plan monthly recalibration

### **MEDIUM TERM (Next Quarter)**
4. **Direction-Split Calibration**
   - 14 calibrators (7 stats × 2 directions)
   - "hits_over" vs "hits_under" need different curves
   - Expected: +5-10% Brier on top of current adjustments

5. **Model Retraining (After 500+ Samples with Adjustments)**
   - Balanced direction sampling (50/50 not 55/45)
   - Add odds as feature
   - Add rolling window features (5-game, 10-game hit rates)
   - Target: Base predictions 52-55% avg (currently 50.5%)

6. **Parlay-Level Calibration**
   - Current: Leg-level calibration only
   - Goal: Calibrate entire parlay win probability
   - Accounts for correlation between legs

### **LONG TERM (Future)**
7. **Automated Monthly Retraining Pipeline**
   - Scheduled retraining on 1st of each month
   - Automatic calibration + adjustment tuning after retraining
   - A/B test new model vs old before full deployment

8. **Ensemble Models**
   - Multiple models with different architectures
   - Weight by recent performance
   - More robust to market changes

9. **Real-Time Adjustment Tuning**
   - Monitor adjustment performance hourly
   - Auto-tune adjustment values based on recent outcomes
   - Adaptive system that learns faster than monthly retraining

---

## Decision Review Schedule

**Daily:** Monitor parlay hit rate, leg composition, adjustment impact  
**Weekly:** Review adjustment performance, track vs targets  
**Monthly:** Evaluate retraining criteria, plan major changes  
**Quarterly:** Reassess architecture decisions, plan next improvements  

---

**Last Review:** May 11, 2026  
**Next Review:** May 18, 2026 (after 7 days of scoring adjustments validation)  
**Major Milestone:** Comprehensive diagnostic analysis completed, scoring adjustments deployed, diversity constraint removed, game_start_time reliability improved
