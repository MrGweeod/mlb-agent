# MLB Parlay Agent — Architecture Decisions
**Last Updated:** May 13, 2026

## Document Purpose
This document records key architectural decisions, their rationale, and outcomes. Each decision follows the format: Context → Decision → Rationale → Outcome.

---

## Table of Contents
1. [Data Architecture](#data-architecture)
2. [ML Model Design](#ml-model-design)
3. [Pipeline Design](#pipeline-design)
4. [Coverage System](#coverage-system)
5. [Critical Bug Fixes](#critical-bug-fixes)

---

## Data Architecture

### Decision 1: Supabase for Backend (Nov 2024)

**Context:** Needed cloud database with real-time capabilities, good Python SDK, and free tier.

**Decision:** Use Supabase (PostgreSQL) for all persistent data.

**Rationale:**
- PostgreSQL provides ACID compliance for financial data
- Supabase offers generous free tier (500MB, 2GB bandwidth)
- Excellent Python SDK (`supabase-py`)
- Built-in auth if needed later
- Real-time subscriptions available

**Outcome:** ✅ Working well
- Zero database-related incidents
- Fast queries (<100ms typical)
- Easy to query via SQL
- Room to grow (currently using ~50MB)

**Alternative Considered:** SQLite (rejected - harder to deploy, no real-time)

---

### Decision 2: Denormalized Leg Storage (Jan 2025)

**Context:** Each leg needs player stats, game context, odds, scores, enrichment data. Should we normalize across tables or denormalize?

**Decision:** Store legs in single denormalized table (`mlb_scored_legs`) with JSON-like columns.

**Rationale:**
- Single query to fetch all data for a leg
- Faster reads (no joins needed)
- Easier to iterate on schema (add columns vs restructure)
- Data is write-once, read-many (denormalization cost is low)
- ~300 legs/day = trivial storage cost

**Outcome:** ✅ Working extremely well
- Simple queries: `SELECT * FROM mlb_scored_legs WHERE run_date = '2026-05-13'`
- No join complexity
- Easy to add new enrichment fields
- Performance excellent

**Trade-off Accepted:** Some data duplication (player names, team names) - negligible impact

---

### Decision 3: Separate Parlay Tables (v2) (Apr 2025)

**Context:** Original single-table design made it hard to track parlay metadata vs individual legs.

**Decision:** Split into two tables:
- `mlb_parlay_recommendations_v2` - Parlay metadata (odds, batch_id, outcome)
- `mlb_parlay_legs_v2` - Individual legs in parlays (references both parlay and scored_leg)

**Rationale:**
- Proper relational design for 1-to-many relationship
- Easy to query "all parlays" vs "all legs in parlay X"
- Enables parlay-level analytics (hit rate by leg count, odds)
- Avoids data duplication in parlay outcomes

**Outcome:** ✅ Clean and maintainable
- Queries are straightforward
- Easy to join for full parlay + legs data
- Good for future analytics

---

## ML Model Design

### Decision 4: Scikit-Learn RandomForest (Dec 2024)

**Context:** Needed fast, interpretable model for binary classification (hit/miss prediction).

**Decision:** Use scikit-learn's RandomForestClassifier with 100 trees.

**Rationale:**
- Fast training (~5 seconds on 80K samples)
- Good feature importance for debugging
- Handles missing values reasonably
- Non-linear decision boundaries
- No GPU required
- Easy to serialize/deploy

**Outcome:** ✅ Strong performance
- AUC: 0.85 (excellent discrimination)
- Accuracy: 77%
- Fast inference (<1ms per leg)
- 673KB model size (easily deployable)

**Alternatives Considered:**
- XGBoost: Slightly better AUC but 10x training time
- Neural networks: Overkill for tabular data, harder to debug
- Logistic regression: Too simple, poor feature interactions

---

### Decision 5: Feature Engineering Strategy (Jan 2025)

**Context:** What features should go into the model?

**Decision:** Three categories of features:
1. **Core stats:** coverage_overall, historical performance
2. **Context:** opponent quality (pitcher_era), handedness matchups
3. **Meta:** stat type, direction (over/under), odds

**Rationale:**
- Coverage is the strongest signal when available
- Context features improve edge cases
- Meta features capture sport-specific patterns (hits_over easier than hits_under)

**Outcome:** ⚠️ Mixed results
- **Good:** Model learned strong patterns (AUC 0.85)
- **Issue:** Direction became dominant feature (70% importance)
- **Root cause:** Coverage was bugged, correlated with direction
- **Status:** Fixed May 13 (coverage calculation), monitoring improvement

**Key Learning:** Even simple bugs in feature engineering cascade into model bias

---

### Decision 6: Scoring Threshold Strategy (Feb 2025)

**Context:** Not all ML-scored legs should be bet. What threshold to use?

**Decision:** Multi-stage filtering:
1. ML composite_score >= 55 (top 30-40% of legs)
2. Manual adjustments (OVER_BOOST, UNDER_PENALTY, etc.)
3. Final eligibility filter before parlay building

**Rationale:**
- Threshold too low → bad legs included
- Threshold too high → insufficient pool for parlays
- Manual adjustments compensate for known ML biases
- Flexibility to tune without retraining

**Outcome:** ⚠️ Needs tuning
- Current adjustments too aggressive (avg score dropped 50→31)
- Forces selection of longer parlays (5-6 legs vs 4)
- Will adjust in next iteration

**Recommended changes:**
- OVER_BOOST: 18 → 8
- UNDER_PENALTY: -26 → -12
- Target avg score: 42-45

---

## Pipeline Design

### Decision 7: Three Daily Pipeline Runs (Mar 2025)

**Context:** When should we fetch data and build parlays?

**Decision:** Three scheduled runs:
- **9 AM ET:** Full pipeline (resolution + fetch + score + build)
- **12 PM ET:** Targeted refresh (SGO odds + lineups)
- **5:30 PM ET:** Targeted refresh (SGO odds + lineups)

**Rationale:**
- **9 AM:** Resolve yesterday's bets, fetch full slate for today
- **12 PM:** Catch lineup changes, odds movements before afternoon games
- **5:30 PM:** Final refresh for evening games
- **Gap before 7 PM:** Most games start, avoid betting on started games

**Outcome:** ✅ Working well
- Catches 95%+ of eligible betting windows
- Resolves bets promptly (9 AM next day)
- No wasted API calls on started games

**Alternative Considered:** Hourly runs (rejected - excessive API usage, little benefit)

---

### Decision 8: Targeted vs Full Refresh (Apr 2025)

**Context:** Should midday/evening runs re-fetch everything or only update existing legs?

**Decision:** Implement "targeted refresh":
- Use existing scored_legs from DB
- Only fetch fresh SGO odds for those specific players
- Check lineups for scratches
- Re-filter for game starts

**Rationale:**
- Saves API quota (15 calls vs 300)
- Faster execution (8 seconds vs 60)
- Most legs don't change between runs
- Still catches critical changes (scratches, odds shifts)

**Outcome:** ✅ Excellent efficiency
- API usage: 223 objects (midday/evening) vs 2000+ (full)
- Speed: 8 sec vs 60 sec
- Catches scratches reliably (Max Muncy, Tyler Soderstrom examples)

---

### Decision 9: Game Start Buffer (15 minutes) (Feb 2025)

**Context:** How close to game start should we allow bets?

**Decision:** Hard cutoff at 15 minutes before scheduled start.

**Rationale:**
- Lineup changes can happen up to 10 minutes before
- SGO odds may not update in final 5 minutes
- User needs time to place bet
- Late scratches are rare but devastating

**Outcome:** ✅ Effective safety net
- Zero instances of betting on scratched player
- Minimal false positives (maybe 1-2 legs/day excluded)
- User feedback: "Better safe than sorry"

---

## Coverage System

### Decision 10: Coverage Calculation Design (Nov 2024)

**Context:** How to quantify "how often does this player go over this line?"

**Decision:** Calculate coverage as:
```
coverage = (games where stat >= line) / (total games with 3+ AB)
```

**Rationale:**
- Simple to understand
- Directly maps to bet outcome
- Filters for meaningful games (3+ AB)
- Adjusts for handedness matchups

**Outcome:** ⚠️ **MAJOR BUG FOUND MAY 13**
- **Critical flaw:** Did not account for OVER vs UNDER direction
- **Impact:** UNDER props had inverted coverage (counted overs, not unders)
- **Result:** Selected wrong players for UNDER bets → 38% hit rate vs expected 70%+
- **Fix:** Added direction parameter (May 13, 2026)

**Key Learning:** Always validate assumptions with real examples (Daylen Lile case revealed bug)

---

### Decision 11: Coverage Inversion Fix (May 13, 2026) 🎉

**Context:** Coverage calculation was counting "times player went OVER" for both OVER and UNDER props.

**Decision:** Add direction awareness to coverage calculation:
```python
if direction == "over":
    coverage = times_went_over / total_games
elif direction == "under":
    coverage = times_stayed_under / total_games
```

**Rationale:**
- UNDER prop bet wins when player stays UNDER the line
- Must count opposite events for opposite bet directions
- Example: Player with 0 hits in 12/40 games → UNDER coverage = 30%, not 70%

**Outcome:** 🚀 **MAJOR BREAKTHROUGH**
- Fixed in 4 files (80 lines of code)
- Backfilled 4,599 historical legs
- Retrained ML model on corrected data
- **Expected impact:** 52% → 65%+ leg hit rate

**Validation:** May 14, 9 AM pipeline run

---

### Decision 12: Minimum Games for Coverage (20 games) (Dec 2024)

**Context:** How many games needed before coverage is reliable?

**Decision:** Require 20+ games with 3+ AB for coverage calculation.

**Rationale:**
- <10 games: Too small sample, high variance
- 10-20 games: Marginal, but still noisy
- 20+ games: Law of large numbers starts to apply
- Trade-off: Fewer players have coverage early in season

**Outcome:** ✅ Appropriate threshold
- ~7% of legs have coverage (early May)
- Coverage improves through season
- Quality of coverage is high when available

**Alternative Considered:** 10 games (rejected - too noisy, false confidence)

---

## Critical Bug Fixes

### Bug Fix 1: Pitcher Props Had Wrong Data (May 13, 2026)

**Problem:** Pitcher strikeout props were enriched with opponent pitcher's data.

**Root Cause:** Enrichment code set pitcher_hand=None but didn't clear pitcher_id/era.

**Fix:** Explicitly clear ALL pitcher fields for pitcher props:
```python
leg["pitcher_id"] = None
leg["pitcher_name"] = None
leg["pitcher_era"] = None
leg["pitcher_k9"] = None
leg["pitcher_whip"] = None
```

**Outcome:** ✅ Fixed
- Pitcher props now correctly have NULL pitcher data
- Batter props still have full pitcher context

---

### Bug Fix 2: Parlay Save/Display Disconnect (May 13, 2026)

**Problem:** Built 5 parlays, but only 2 showed in web app.

**Root Cause:** 
1. Diversity filter in `generate_recommendations()` capped legs at 2 appearances
2. Source detection used UTC instead of ET timezone

**Fix:**
1. Removed diversity filter
2. Fixed timezone to ET for auto-detection
3. Added explicit source parameter to pipeline

**Outcome:** ✅ Fixed
- All 5 parlays now save and display
- Correct source attribution
- No data loss

---

### Bug Fix 3: Coverage Inversion for UNDER Props (May 13, 2026)

**Problem:** hits_under 38% hit rate when should be 70%+.

**Root Cause:** Coverage calculation counted "times player went OVER" for all props, regardless of direction.

**Fix:** Added direction parameter to all coverage functions, inverted logic for UNDER:
```python
if direction == "under":
    hit = val < line  # Stayed under
else:
    hit = val >= line  # Went over
```

**Outcome:** 🚀 **MAJOR FIX**
- Most impactful bug fix to date
- Affects entire system performance
- Expected to improve leg hit rate by 10-15 percentage points

**Validation:** Awaiting May 14, 9 AM data

---

## Lessons Learned

### Lesson 1: Test Edge Cases with Real Data
**Context:** Coverage bug went undetected for 6 months.

**What we learned:** 
- Unit tests passed (both directions showed "high" coverage)
- Only real player data (Daylen Lile) revealed the inversion
- Always verify with concrete examples

**Action:** 
- Add test cases with real player game logs
- Manually verify calculated coverage matches expectation

---

### Lesson 2: Monitoring Hit Rates by Subgroup is Critical
**Context:** 52% overall hit rate masked 38% hits_under and 62% hits_over.

**What we learned:**
- Aggregate metrics hide important patterns
- Need to slice by stat, direction, coverage, etc.
- Diagnostic queries should be run routinely

**Action:**
- Created diagnostic query library
- Schedule weekly performance reviews by segment

---

### Lesson 3: Feature Engineering Bugs Cascade into Model Bias
**Context:** Coverage bug caused direction to become 70% of model's decision.

**What we learned:**
- Model learns whatever patterns exist in training data
- If coverage is correlated with direction (due to bug), model will learn that
- Data quality matters more than model complexity

**Action:**
- Validate all features before training
- Check feature correlations
- Test with held-out segments

---

### Lesson 4: Simple Fixes Can Have Massive Impact
**Context:** 5 lines of code (direction check) may improve system by 10-15 percentage points.

**What we learned:**
- Don't always reach for complex solutions
- Sometimes the bug is in data, not model
- Root cause analysis > model tuning

**Action:**
- Always check data quality first
- Question assumptions
- Use real examples to validate

---

## Future Architecture Considerations

### Consideration 1: Real-time Odds Tracking
**Opportunity:** Track SGO odds changes throughout day, bet on favorable movements.

**Trade-offs:**
- (+) Could capture better lines
- (-) Much higher API usage
- (-) More complex betting logic
- (-) May not move needle vs current approach

**Decision:** Not pursuing yet - validate current system first

---

### Consideration 2: Multi-Model Ensemble
**Opportunity:** Train separate models for each stat type (hits, strikeouts, etc.).

**Trade-offs:**
- (+) Better specialization
- (-) 5x training time
- (-) More complex deployment
- (-) Need sufficient data per stat type

**Decision:** Defer until after coverage fix validated

---

### Consideration 3: Live In-Game Betting
**Opportunity:** Bet on props during games based on live updates.

**Trade-offs:**
- (+) More betting opportunities
- (-) Requires real-time data stream (expensive)
- (-) Much more complex logic
- (-) Higher risk (less time to research)

**Decision:** Out of scope - pre-game focus is sufficient

---

## Decision Review Cadence

**Monthly:** Review major architectural decisions, validate outcomes
**Quarterly:** Consider new capabilities, evaluate alternatives
**Annually:** Full system architecture review

**Next Review:** June 1, 2026 (post-coverage fix validation)

---

## Key Principles Going Forward

1. **Data Quality First:** No amount of ML can fix bad features
2. **Test with Real Data:** Unit tests aren't enough, use actual player examples
3. **Monitor Subgroups:** Aggregate metrics hide issues
4. **Simple Solutions:** Check for data bugs before adding model complexity
5. **Validate Assumptions:** User questions (Matt Olson example) led to breakthrough

---

**Last Updated:** May 13, 2026  
**Major Milestone:** Coverage inversion bug fixed - first true data quality breakthrough  
**Next Checkpoint:** May 14, 9 AM validation run
