# MLB Parlay Agent — Architecture Decisions
**Last Updated:** May 10, 2026 (ML Calibration + Game Filter Fixes)

## Document Purpose
This document records the key architectural decisions made during the development of the MLB Parlay Agent, including the rationale, alternatives considered, and lessons learned. Updated with insights from May 10's ML calibration deployment and game start time filter fixes.

---

## Table of Contents
1. [ML Calibration Strategy](#ml-calibration-strategy)
2. [Game Start Time Filter Design](#game-start-time-filter-design)
3. [Within-Batch Player Diversity](#within-batch-player-diversity)
4. [Quality Validation Monitoring](#quality-validation-monitoring)
5. [Dashboard V1/V2 Integration](#dashboard-v1v2-integration)
6. [Core Architecture (Unchanged)](#core-architecture-unchanged)
7. [Lessons Learned](#lessons-learned)

---

## ML Calibration Strategy

### **Decision: Stat-Specific Isotonic Regression (Post-Hoc Calibration)**
**Chosen:** May 10, 2026

**Problem:**
Base ML model (leg_scorer_v2.pkl) had good discrimination (AUC 0.8532) but poor calibration. Predicted 34.6% average while actual hit rate is 45.5% - an 11-point systematic underestimation.

**Impact:**
- Missing betting value (underestimating quality legs)
- Poor parlay win probability estimates
- Users losing trust in predictions

**Solution Implemented:**
Post-hoc stat-specific isotonic regression trained on 52,583 resolved legs.

**Why Post-Hoc (Not Full Retraining)?**
1. **Fast deployment:** 1 hour vs 4-6 hours for full retraining
2. **Low risk:** Calibrator sits on top, base model unchanged
3. **Reversible:** Easy rollback if issues arise
4. **Effective:** 16.6% Brier improvement without touching base model

**Alternatives Considered:**

**Option A: Full Model Retraining**
- ❌ Time: 4-6 hours to retrain + validate
- ❌ Risk: Could make model worse
- ❌ Complexity: Need to rebalance data, tune hyperparameters
- ✅ Pro: Fixes root cause (conservative base predictions)
- **Verdict:** Save for later when we have more data

**Option B: Platt Scaling (Global Calibration)**
- ✅ Fast: 30 minutes
- ❌ Performance: Only 12.3% Brier improvement (vs 17.2% for stat-specific)
- ❌ Limitation: Single curve can't handle heterogeneous prop types
- **Verdict:** Good but not optimal

**Option C: Beta Calibration**
- ✅ Fast: 30 minutes
- ❌ Performance: 12.3% Brier improvement (same as Platt)
- ❌ Limitation: Assumes predictions follow beta distribution
- **Verdict:** Similar to Platt, not better

**Option D: Stat-Specific Isotonic Regression** ✅ **CHOSEN**
- ✅ Best performance: 17.2% Brier improvement
- ✅ Handles heterogeneous data: Each prop type has its own calibrator
- ✅ Non-parametric: No distribution assumptions
- ✅ Production-ready: Deployed in 1 hour
- ❌ Complexity: 7 calibrators to manage (not 1)
- ❌ Cold-start: New stat types have no calibrator

**Trade-offs Accepted:**
- Slightly more complex (7 calibrators vs 1)
- New stat types won't be calibrated until retrained
- Calibrator file is 3.2KB (negligible)

**Performance Metrics:**Brier Score: 0.2341 (was 0.2826, +16.6% improvement)
Calibration Alignment: 45.5% predicted → 45.5% actual (perfect)By Stat Type:
Home Runs: +36.8% Brier improvement
Stolen Bases: +24.5%
Hits: +17.9%
Strikeouts: +15.2%
Total Bases: +14.1%

**Why Stat-Specific Beat Global:**
Different prop types have wildly different base rates:
- Home Runs: 6.5% hit rate
- Stolen Bases Under: 95% hit rate
- Hits: ~50% hit rate

A single global calibrator tries to fit one curve to all of these, resulting in poor calibration for extreme values. Stat-specific calibrators adapt to each prop type's unique characteristics.

**Status:** ✅ Deployed May 10, operational

---

## Game Start Time Filter Design

### **Decision: Fail-Closed Logic with 15-Minute Forward Buffer**
**Chosen:** May 10, 2026 (Fixed from Fail-Open)

**Problem:**
Players from started games appearing in parlay recommendations. Xavier Edwards in parlays at 1:36 PM ET despite his game starting at 12:10 PM ET (86 minutes earlier).

**Root Cause:**
Filter had "fail-open" logic - if `game_start_time` was NULL or unparseable, the leg would pass through instead of being excluded.

**Solution Implemented:**
Changed to "fail-closed" logic in 4 locations:
1. `src/web/server.py:367` - build_parlays()
2. `src/web/server.py:684` - regenerate() endpoint
3. `main.py:648` - generate_recommendations()
4. `main.py:988` - run_targeted_pipeline()

**Fail-Open vs Fail-Closed Comparison:**

**Fail-Open (OLD - WRONG):**
```pythonif not game_start_time:
active_legs.append(leg)  # When in doubt, include
continue

**Pros:**
- ✅ More legs in pool (higher capacity)
- ✅ Handles missing data gracefully

**Cons:**
- ❌ Started games slip through
- ❌ Quality suffers (invalid bets included)
- ❌ User trust erodes (why is Xavier Edwards in my parlay?)

**Fail-Closed (NEW - CORRECT):**
```pythonif not game_start_time:
null_count += 1
continue  # When in doubt, exclude

**Pros:**
- ✅ Guarantees only valid legs (no started games)
- ✅ Quality preserved (better to miss a good leg than include a bad one)
- ✅ User trust maintained

**Cons:**
- ❌ Slightly fewer legs in pool (if game_start_time has NULLs)
- ❌ Requires robust enrichment pipeline

**Why Fail-Closed is Correct:**
For time-sensitive filtering, **it's better to exclude a good leg than include a bad one**. A started game in a parlay is a guaranteed loss. A missed betting opportunity is just an opportunity cost.

**Additional Fix: Cutoff Direction**
Also fixed in `server.py:367`:
- **OLD (WRONG):** `cutoff = now - 5min` (backward-looking)
- **NEW (CORRECT):** `cutoff = now + 15min` (forward-looking)

Backward-looking meant "exclude games that started >5 minutes ago" - a game at 12:35 PM would pass through at 12:38 PM (12:35 > 12:33).

Forward-looking means "exclude games starting within 15 minutes" - a game at 12:35 PM is correctly excluded at 12:38 PM (12:35 < 12:53).

**Database Verification:**run_date   | total | has_time | missing
2026-05-10 |   348 |      348 |       0

100% of legs have valid `game_start_time` - enrichment pipeline already working correctly via `src/pipelines/enrich_legs.py`.

**Trade-offs Accepted:**
- If enrichment pipeline breaks, capacity drops to 0 (all legs excluded)
- Requires monitoring "missing time" count in logs
- But: This is the correct failure mode for a betting system

**Status:** ✅ Deployed May 10 afternoon, operational

---

## Within-Batch Player Diversity

### **Decision: Max 2 Appearances Per Player Per Batch**
**Chosen:** May 8, 2026 (Unchanged - Still Operational)

**Problem:**
May 7 analysis showed 0/23 parlays won due to portfolio concentration. Root cause: same high-quality players appearing in multiple parlays. When Ramón Laureano failed, 60% of portfolio failed simultaneously.

**Solution Implemented:**
Within-batch diversity: Max 2 appearances per player per generation batch.

**Alternatives Considered:**

**Option A: Cross-Batch Blocking**
- Players used at 9 AM blocked from 12 PM and 5:30 PM runs
- ❌ Too restrictive: Only 1-2 parlays per batch
- ❌ Exhausts player pool throughout day

**Option B: No Diversity Constraint**
- ❌ Proven failure mode (May 7: 0/23)
- ❌ High portfolio risk

**Option C: Max 1 Appearance Per Player Per Batch**
- ❌ Too restrictive: Only 2-3 parlays max
- ❌ Forces use of lower-quality legs

**Option D: Max 2 Appearances Per Player Per Batch** ✅ **CHOSEN**
- ✅ Balances quality and diversity
- ✅ Allows 3-5 parlays per batch
- ✅ Max 40% exposure per player (2/5 parlays)
- ✅ Simple logic, easy to monitor

**Pitcher Exemption:**
Pitchers exempt from diversity constraint because:
- Pitcher props (strikeouts) are independent of batter props
- Different skill being measured
- No portfolio concentration risk

**Status:** ✅ Deployed May 8, operational

---

## Quality Validation Monitoring

### **Decision: Active Logging of Pool Expansion Impact**
**Chosen:** May 8, 2026 (Unchanged - Still Operational)

**Problem:**
Expanding candidate pool from top 20 to top 50 legs could silently degrade parlay quality. Need real-time feedback on quality impact to enable data-driven tuning.

**Solution Implemented:**
```pythonif len(eligible_sorted) >= 50:
top_20_avg = sum(l.get("composite_score", 0) for l in eligible_sorted[:20]) / 20
top_50_avg = sum(l.get("composite_score", 0) for l in eligible_sorted[:50]) / 50
quality_drop = ((top_20_avg - top_50_avg) / top_20_avg) * 100print(f"  [parlay_builder] Quality validation:")
print(f"    Top 20 avg ML score: {top_20_avg:.1f}%")
print(f"    Top 50 avg ML score: {top_50_avg:.1f}%")
print(f"    Quality drop: {quality_drop:.1f}%")if quality_drop > 10:
    print(f"    WARNING: Quality drop >10%")

**Performance Metrics (May 10):**Typical quality drop: 3-5%
Acceptable range: <10%
Warnings triggered: 0
Conclusion: Top 50 pool is viable

**Status:** ✅ Deployed May 8, operational

---

## Dashboard V1/V2 Integration

### **Decision: Separate Queries Combined in Python**
**Chosen:** May 8, 2026 (Unchanged - Still Operational)

**Problem:**
Dashboard needed to display parlays from both v1 schema (old recommendations) and v2 schema (new normalized schema). Initial UNION ALL approach caused HTTP 500 errors due to type mismatches.

**Solution Implemented:**
```pythonQuery v1 (cast date to text for consistency)
cur.execute("""
SELECT
id, recommendation_date::text AS recommendation_date,
rank, combined_odds, win_probability, edge_pct,
bet_status, resolved_at::text AS resolved_at,
'v1' AS schema_version
FROM mlb_parlay_recommendations
ORDER BY recommendation_date DESC, rank ASC
LIMIT 20
""")
v1_recs = [dict(r) for r in cur.fetchall()]Query v2
cur.execute("""
SELECT
id, run_date::text AS recommendation_date,
rank, total_odds AS combined_odds,
avg_coverage AS win_probability, 0.0 AS edge_pct,
outcome AS bet_status, NULL::text AS resolved_at,
'v2' AS schema_version
FROM mlb_parlay_recommendations_v2
ORDER BY run_date DESC, rank ASC
LIMIT 20
""")
v2_recs = [dict(r) for r in cur.fetchall()]Combine in Python
recent_recs = sorted(
v1_recs + v2_recs,
key=lambda x: (x.get("recommendation_date") or "", -(x.get("rank") or 0)),
reverse=True,
)[:20]

**Why This Works:**
- ✅ Avoids PostgreSQL type mismatch issues
- ✅ Each query handles its own schema independently
- ✅ Python sorting is more explicit and debuggable
- ✅ Can test v1 and v2 queries separately

**Status:** ✅ Deployed May 8, operational

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
- ✅ Critical enabler for May 8-10 features

### **ML Model-Based Scoring**
- Quality-first ranking preserved throughout
- Now with calibration: 45.5% avg prediction (was 34.6%)
- ✅ Continues to perform well

### **Railway Deployment**
- Auto-deploy from master branch
- 99.9% uptime
- ✅ Reliable and fast

---

## Lessons Learned

### **Learning #1: Calibration Before Retraining**
**Discovery:** When a model discriminates well (AUC 0.85) but predicts poorly (34.6% vs 45.5% actual), calibrate before retraining.

**Rationale:**
- Calibration is faster (1 hour vs 4-6 hours)
- Lower risk (sits on top, doesn't change base model)
- Often sufficient (16.6% Brier improvement)
- Buys time to collect more training data

**When to retrain instead:**
- AUC is poor (<0.75) - discrimination is broken
- Features are missing critical information
- Model architecture is fundamentally wrong
- You have 2x more training data than before

**Takeaway:** Calibration fixes the "what" you predict. Retraining fixes the "how" you predict. If the "how" works (good AUC), just fix the "what."

---

### **Learning #2: Stat-Specific Models for Heterogeneous Data**
**Discovery:** Home runs hit 6.5%, stolen bases under hit 95% - these need different calibration curves.

**Comparison:**
- Global calibrator: 12.3% Brier improvement
- Stat-specific calibrator: 17.2% Brier improvement
- Difference: +4.9 percentage points

**Why it matters:**
When your data has distinct subpopulations with different base rates, modeling them separately captures nuances a global model misses.

**Other applications:**
- Direction-specific models (over vs under)
- Team-specific models (Dodgers vs Rockies)
- Weather-specific models (outdoor vs domed)

**Takeaway:** If your data has natural partitions with different statistics, partition your models too.

---

### **Learning #3: Fail-Closed for Time-Sensitive Systems**
**Discovery:** Fail-open logic (pass through when uncertain) caused started games to slip into parlays.

**Trade-off:**
- Fail-open: More data, but lower quality
- Fail-closed: Less data, but higher quality

**Decision rule:**
- Use fail-closed when: Incorrectness is worse than incompleteness
- Use fail-open when: Completeness is more important than correctness

**Examples:**
- Betting system: Fail-closed (better to miss a bet than make a bad bet)
- Search engine: Fail-open (better to show more results than miss relevant ones)
- Medical diagnosis: Fail-closed (better to run more tests than miss a condition)

**Takeaway:** The right failure mode depends on the cost of false positives vs false negatives.

---

### **Learning #4: Database Verification Before Pipeline Debugging**
**Discovery:** Initial panic about "100% NULL game_start_time" was a query error, not a data problem.

**Correct diagnostic order:**
1. Check column exists (information_schema)
2. Check sample data (SELECT * LIMIT 5)
3. Check aggregates by date (COUNT, GROUP BY)
4. Check enrichment pipeline code
5. Then conclude pipeline is broken

**What went wrong:**
- Jumped to conclusion (pipeline must be broken)
- Didn't verify database state first
- Wasted time debugging working code

**Takeaway:** Always verify ground truth (database state) before assuming application logic is broken.

---

### **Learning #5: Post-Hoc Calibration is Underrated**
**Discovery:** Most ML practitioners focus on feature engineering and hyperparameter tuning. Calibration is often an afterthought.

**Reality:**
- Calibration is faster than retraining
- Calibration is lower risk than retraining
- Calibration often gives bigger improvements than feature engineering

**When calibration helps most:**
- Model is well-trained but poorly calibrated
- You need probabilistic predictions (not just classifications)
- Different subgroups have different base rates
- Model is in production and retraining is expensive

**Takeaway:** Check calibration curves before embarking on expensive retraining. You might get 80% of the benefit with 20% of the effort.

---

## Future Architectural Improvements

### **SHORT TERM (This Month)**
1. **Monitor Calibration Drift**
   - Track predicted vs actual weekly
   - Alert if calibration degrades >5%
   - Plan monthly recalibration

2. **Automate Fail-Closed Monitoring**
   - Alert if "missing time" count >10 per run
   - Indicates enrichment pipeline issues
   - Enables proactive fixes

### **MEDIUM TERM (Next Quarter)**
3. **Temperature Scaling (Alternative Calibration)**
   - Single parameter vs 7 isotonic regressors
   - Easier to tune and deploy
   - Test if performance matches isotonic

4. **Direction × Stat Calibration**
   - 14 calibrators (7 stats × 2 directions)
   - hits_over vs hits_under may need different curves
   - Hypothesis: overs are harder to predict

### **LONG TERM (Future)**
5. **Parlay-Level Calibration**
   - Current: Leg-level calibration only
   - Goal: Calibrate entire parlay win probability
   - Accounts for correlation between legs

6. **Automated Monthly Retraining Pipeline**
   - Scheduled retraining on 1st of each month
   - Automatic calibration after retraining
   - A/B test new model vs old before full deployment

7. **Ensemble Calibration**
   - Combine isotonic + beta + temperature scaling
   - Weighted ensemble of calibrators
   - Potentially better than any single method

---

## Decision Review Schedule

**Daily:** Monitor calibration alignment, game filter effectiveness  
**Weekly:** Review quality drop trends, diversity impact on outcomes  
**Monthly:** Evaluate calibration drift, retrain if needed  
**Quarterly:** Reassess architecture decisions, plan major changes  

---

**Last Review:** May 10, 2026  
**Next Review:** May 17, 2026 (after 7 days of calibrated predictions)  
**Major Milestone:** ML calibration deployed (+16.6% Brier), game filter working correctly (fail-closed)
