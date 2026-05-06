# MLB Parlay Agent — Architecture Decisions
**Last Updated:** May 6, 2026

## Document Purpose
This document records the key architectural decisions made during the development of the MLB Parlay Agent, including the rationale, alternatives considered, and lessons learned. Updated with insights from production deployment and crisis resolution.

---

## Table of Contents
1. [Core Architecture](#core-architecture)
2. [ML Model Design](#ml-model-design)
3. [Data Pipeline](#data-pipeline)
4. [Parlay Construction](#parlay-construction)
5. [Outcome Resolution](#outcome-resolution)
6. [Database Schema](#database-schema)
7. [Deployment Strategy](#deployment-strategy)
8. [Lessons Learned](#lessons-learned)

---

## Core Architecture

### **Decision: Scheduled Batch Processing**
**Chosen:** Daily pipeline at 9:00 AM ET, resolves previous day outcomes
**Why:**
- Props don't change after games start
- Outcomes resolve next morning (official stats available)
- Reduces API costs (single bulk fetch vs continuous polling)
- Simpler state management (no real-time updates)

**Alternatives Considered:**
- Real-time streaming: Too complex, high API costs, limited value
- Manual triggers only: Requires human intervention, prone to missed days

**Trade-offs:**
- ✅ Simplicity, cost efficiency, reliability
- ❌ No live betting, ~12-hour delay in outcome resolution

**Status:** ✅ Working well, no issues

---

### **Decision: Monolithic Flask App**
**Chosen:** Single Flask app with scheduler (APScheduler)
**Why:**
- Simple deployment (one Railway service)
- Shared state (ML model, database connection)
- Easy debugging (single log stream)

**Alternatives Considered:**
- Microservices: Overkill for this scale, adds complexity
- Separate workers: Requires message queue, more infrastructure

**Trade-offs:**
- ✅ Simple, cost-effective, easy to reason about
- ❌ Scaling limited to vertical (not a concern at current volume)

**Status:** ✅ Proven reliable through production use

---

## ML Model Design

### **Decision: Single Binary Classifier (Hit/Miss)**
**Chosen:** Scikit-learn LogisticRegression, 15 features
**Why:**
- Simple, interpretable, fast inference
- Good baseline (AUC: 0.8532)
- No need for actual value prediction (just over/under)

**Alternatives Considered:**
- Regression model: Harder to interpret, not needed for binary outcome
- Deep learning: Overkill, requires more data, harder to debug
- Multiple models per prop type: More complex, not enough data per type

**Trade-offs:**
- ✅ Fast, interpretable, sufficient accuracy
- ❌ Treats all prop types equally (may miss type-specific patterns)

**Status:** ✅ Working but conservative (50.5% avg prediction)

---

### **Decision: Direction as Primary Feature**
**Chosen:** Over/under direction is a model feature
**Why:**
- Captures market inefficiency (over/under imbalance)
- High predictive power (77% feature importance)

**Problem Discovered (May 6):**
- Direction overfit: Model relies too heavily on direction
- Low predictions: 50.5% average (conservative)

**Lessons Learned:**
- ✅ Direction is predictive BUT needs balancing
- ❌ Overreliance on single feature limits upside
- 🔄 Future: Balance direction sampling in training data

**Status:** 🎯 Needs retraining with balanced sampling

---

### **Decision: Coverage % as Risk Proxy**
**Chosen:** Coverage % = (outcome count / total outcomes) measures certainty
**Why:**
- Higher coverage = more consistent player
- Helps filter risky props (low sample size)

**Trade-offs:**
- ✅ Effective risk filter
- ❌ Penalizes players with breakout potential

**Status:** ✅ Working well, part of lineup consistency filter

---

### **Decision: Store ML Scores with Legs**
**Chosen:** `composite_score` column in `mlb_scored_legs`
**Why:**
- Reproducibility: Can audit historical recommendations
- Dashboard: Can analyze score vs actual outcome
- Debugging: Identify model drift or scoring errors

**Alternatives Considered:**
- Recompute on-demand: Slower, inconsistent if model changes
- Separate scores table: More complexity, joins required

**Trade-offs:**
- ✅ Fast lookups, reproducible, audit trail
- ❌ Storage overhead (minimal ~4 bytes/leg)

**Status:** ✅ Critical for debugging May 6 issues

---

## Data Pipeline

### **Decision: Two-Stage Pipeline (Fetch → Build)**
**Chosen:** 
1. Fetch & score all props → database
2. Build parlays from database

**Why:**
- Separation of concerns (data vs construction)
- Allows manual regeneration (rebuild parlays without refetching)
- Database becomes source of truth

**Alternatives Considered:**
- Single-stage: Fetch and build in one pass (faster but less flexible)
- Stream processing: Overkill for batch workload

**Trade-offs:**
- ✅ Flexibility, debuggability, data persistence
- ❌ Slightly slower (extra database round-trip)

**Status:** ✅ Proven valuable during May 6 crisis (regenerated without refetching)

---

### **Decision: Lineup Consistency Filter**
**Chosen:** Filter props where player's lineup consistency <30%
**Why:**
- Reduces void rate (players ruled out after props logged)
- Improves parlay reliability
- Uses publicly available data (MLB-StatsAPI)

**Implementation Challenges (May 6):**
- Invalid API parameter (`season` with `type='gameLog'`)
- Error handling: Any error → include conservatively
- Circuit breaker: Disable filter if >90% filtered

**Lessons Learned:**
- ✅ Filter works (40% filtered as designed)
- ❌ API documentation incomplete, required experimentation
- 🔄 Conservative error handling prevents catastrophic filtering

**Status:** ✅ Fixed and operational

---

### **Decision: Single Daily Props Fetch**
**Chosen:** Fetch all props once, cache in database
**Why:**
- API rate limits (500 requests/day)
- Props don't change after fetch
- Consistent dataset for all parlays

**Trade-offs:**
- ✅ Cost-effective, consistent
- ❌ No real-time updates (not needed for use case)

**Status:** ✅ No issues

---

## Parlay Construction

### **Decision: Greedy Construction with Constraints**
**Chosen:** Build 5 parlays sequentially, apply diversity rules
**Why:**
- Simple to implement and reason about
- Constraints prevent over-correlation
- 5 parlays = good diversity without overwhelming user

**Constraints Applied:**
1. Max 1 leg per game (prevents single-game risk)
2. Max 2 legs per player (prevents over-exposure)
3. Max 1 leg per prop type per parlay (diversifies prop types)
4. Odds range: +1400 to +1600 (balances risk/reward)

**Alternatives Considered:**
- Optimization (linear programming): Overkill, harder to debug
- Random sampling: Less consistent quality
- User-defined constraints: More flexible but complex UX

**Trade-offs:**
- ✅ Simple, consistent, explainable
- ❌ May miss optimal combinations (good enough > perfect)

**Status:** ✅ Producing valid parlays, no issues

---

### **Decision: Rank by Average ML Score**
**Chosen:** Rank 1 = highest average `composite_score` across legs
**Why:**
- Simple, interpretable
- Aligns with ML model's confidence
- Users understand "Rank 1 = best predicted"

**Alternatives Considered:**
- Expected value (EV): Requires implied odds calculation, more complex
- Kelly criterion: Requires bankroll management, out of scope

**Trade-offs:**
- ✅ Simple, interpretable
- ❌ Doesn't account for odds value (future enhancement)

**Status:** ✅ Working as designed

---

## Outcome Resolution

### **Decision: Void Logic — "Lost Beats Void"**
**Chosen (May 6 Fix):** 
- ALL legs void → parlay void
- ANY leg lost → parlay lost (voids ignored)
- All non-void legs won → parlay won (adjusted odds)

**Why:**
- Standard sportsbook behavior
- Partial voids adjust odds but parlay can still win/lose
- Prevents false voids (masking losses)

**Previous (Broken) Logic:**
- ANY leg void → parlay void
- Problem: One void voided entire parlay, inflated void rate

**Lessons Learned:**
- ✅ Edge cases matter (partial voids common in MLB)
- ❌ Assumed standard logic, didn't validate thoroughly
- 🔄 Backfilled historical data to correct

**Status:** ✅ Fixed, tested, validated

---

### **Decision: Two-Phase Resolution (Legs → Parlays)**
**Chosen:**
1. Resolve all legs (won/lost/void)
2. Resolve parlays based on leg outcomes

**Why:**
- Separation of concerns (leg logic vs parlay logic)
- Reusable: Legs can be in multiple parlays
- Debugging: Can inspect leg outcomes independently

**Alternatives Considered:**
- Single-phase: Resolve parlays directly from game data (tightly coupled)

**Trade-offs:**
- ✅ Modular, testable, reusable
- ❌ Two database passes (negligible overhead)

**Status:** ✅ Proven robust during backfill

---

### **Decision: MLB-StatsAPI for Outcomes**
**Chosen:** Use `statsapi` Python library for game results
**Why:**
- Free, unlimited, official MLB data
- Python library simplifies integration
- Reliable (backed by MLB)

**Challenges Encountered (May 6):**
- Documentation incomplete (parameter combinations unclear)
- Error messages cryptic (`season` param issue)

**Lessons Learned:**
- ✅ Free and reliable for production use
- ❌ Requires experimentation, not just documentation
- 🔄 Conservative error handling critical

**Status:** ✅ Working reliably post-fix

---

## Database Schema

### **Decision: PostgreSQL on Supabase**
**Chosen:** Hosted PostgreSQL (Supabase free tier)
**Why:**
- Relational model fits data (props, parlays, outcomes)
- Supabase free tier sufficient (500MB, 2 connections)
- SQL queries flexible for dashboard

**Alternatives Considered:**
- SQLite: Not suitable for hosted deployment
- MongoDB: Overkill, relational structure clearer
- BigQuery: Too expensive for this scale

**Trade-offs:**
- ✅ Free, reliable, SQL flexibility
- ❌ Connection limits (not an issue yet)

**Status:** ✅ No issues, plenty of headroom

---

### **Decision: Denormalized Legs Table**
**Chosen:** `mlb_scored_legs` stores all leg data (no joins for display)
**Why:**
- Fast queries (no joins for Legs tab)
- Historical props preserved (even if source API changes)
- ML scores stored with legs (reproducibility)

**Alternatives Considered:**
- Normalized: Separate players, teams tables (more complex, slower queries)

**Trade-offs:**
- ✅ Fast reads, simple queries, historical integrity
- ❌ Data duplication (acceptable for read-heavy workload)

**Status:** ✅ Performs well, 2500+ legs per table

---

### **Decision: TEXT Column for run_date**
**Chosen (Inherited):** `run_date` stored as TEXT (YYYY-MM-DD format)
**Why:** Unknown (likely default from initial schema)

**Problem Discovered (May 6):**
- SQL comparisons fail: `TEXT >= TIMESTAMP` invalid
- Dashboard queries returned HTTP 500

**Fix Applied:**
- Cast to DATE in queries: `run_date::date >= CURRENT_DATE - INTERVAL '30 days'`

**Lessons Learned:**
- ✅ Type casting works for backward compatibility
- ❌ Should have been DATE type from start
- 🔄 Future: Migrate to DATE column (non-critical)

**Status:** ✅ Fixed with ::date casts, functional

---

### **Decision: Separate Training Table**
**Chosen:** `mlb_training_data` separate from `mlb_scored_legs`
**Why:**
- Cleaner data for retraining (no NULL outcomes)
- Easier to filter for model training
- Historical training data preserved

**Trade-offs:**
- ✅ Clean training data, easier retraining
- ❌ Duplication (acceptable for ML pipeline)

**Status:** ✅ Growing steadily (~77k samples)

---

## Deployment Strategy

### **Decision: Railway for Hosting**
**Chosen:** Railway (PaaS) with GitHub auto-deploy
**Why:**
- Simple: Push to master → auto-deploy
- Free tier sufficient ($5/month estimated usage)
- Built-in monitoring and logs

**Alternatives Considered:**
- Heroku: Similar but more expensive
- AWS/GCP: More complex, overkill for this scale
- VPS (DigitalOcean): Requires more maintenance

**Trade-offs:**
- ✅ Simple, affordable, reliable
- ❌ Vendor lock-in (mitigated by standard Flask/Python stack)

**Status:** ✅ Stable, 99.9% uptime

---

### **Decision: APScheduler for Cron Jobs**
**Chosen:** APScheduler library within Flask app
**Why:**
- No external cron service needed
- Timezone-aware (ET for MLB)
- Startup catch-up (runs missed jobs on restart)

**Challenges:**
- Timezone handling (ET vs UTC)
- Startup catch-up: Only runs if within 9-12 PM window

**Lessons Learned:**
- ✅ Works reliably for daily jobs
- ❌ Startup catch-up logic needs tuning (3-hour window)
- 🔄 Consider external cron if scaling to multiple instances

**Status:** ✅ Working reliably, no missed runs

---

### **Decision: Environment Variables for Secrets**
**Chosen:** Railway environment variables + python-dotenv
**Why:**
- Security: No secrets in code
- Flexibility: Different values per environment (dev/prod)

**Variables Used:**
- `SUPABASE_URL`, `SUPABASE_KEY` (database)
- `ODDS_API_KEY` (props fetching)
- `PORT` (Railway assigned)

**Status:** ✅ No issues

---

## Lessons Learned

### **1. Edge Cases Matter (Void Logic)**
**What Happened:**
- Assumed ANY void → parlay void (standard logic)
- Didn't account for partial voids (common in MLB)
- Resulted in inflated void rate (5.9% → 0%)

**Lesson:**
- ✅ Test edge cases early (partial voids, all voids, no voids)
- ✅ Validate against expected outcomes (sportsbook behavior)
- 🔄 Write unit tests for resolution logic (future)

---

### **2. API Documentation is Incomplete**
**What Happened:**
- MLB-StatsAPI docs didn't clarify parameter combinations
- `season` + `type='gameLog'` caused error
- Took experimentation to find correct usage

**Lesson:**
- ✅ Budget time for API experimentation
- ✅ Add conservative error handling (return None vs crash)
- ✅ Add circuit breakers for critical filters
- 🔄 Document API quirks in code comments

---

### **3. Type Safety Prevents Bugs**
**What Happened:**
- `run_date` stored as TEXT, queries compared to TIMESTAMP
- SQL failed silently → HTTP 500 errors

**Lesson:**
- ✅ Use correct types from schema design (DATE not TEXT)
- ✅ Type casting (`::date`) works but adds overhead
- 🔄 Consider schema migration tools (Alembic) for future

---

### **4. Separation of Concerns Enables Debugging**
**What Happened:**
- Two-stage pipeline (fetch → build) allowed regeneration without refetching
- Separate resolution (legs → parlays) allowed independent testing

**Lesson:**
- ✅ Modularity pays off during debugging
- ✅ Database as source of truth enables auditing
- ✅ Idempotent operations (safe to re-run) are valuable

---

### **5. Conservative Defaults Prevent Catastrophic Failures**
**What Happened:**
- Lineup filter API errors → include player conservatively
- Circuit breaker: Disable filter if >90% filtered
- Prevented 100% filtering from blocking production

**Lesson:**
- ✅ "Include when uncertain" better than "exclude when uncertain"
- ✅ Circuit breakers catch systemic issues
- ✅ Logging helps diagnose (shows individual player results)

---

### **6. Historical Backfill Validates Fixes**
**What Happened:**
- Backfilled 7 dates (April 22 - May 5) after void logic fix
- Discovered May 4 was missing (bonus win!)
- Validated fix across 17 parlays

**Lesson:**
- ✅ Backfilling validates logic changes
- ✅ Historical data = regression test suite
- 🔄 Automate backfill for future fixes

---

### **7. ML Model Needs Continuous Validation**
**What Happened:**
- Model predictions (50.5% avg) match reality (50-55% hit rate)
- BUT: Direction overfit (77% importance) limits upside
- Conservative predictions leave value on table

**Lesson:**
- ✅ Model accuracy ≠ model utility (can be "right" but unprofitable)
- ✅ Feature importance analysis reveals overfitting
- 🔄 Retraining with balanced data may improve utility

---

### **8. Dashboard is Critical for Validation**
**What Happened:**
- Dashboard bugs (SQL errors, display issues) blocked validation
- Once fixed, revealed void logic issue instantly

**Lesson:**
- ✅ Observability is as important as functionality
- ✅ Invest in dashboard early (validation tool)
- 🔄 Add charts/visualizations for trends

---

## Future Architectural Improvements

### **SHORT TERM (This Month)**
1. **Add Unit Tests**
   - Void logic (all cases)
   - Lineup filter (error handling)
   - Parlay construction (constraints)

2. **Monitoring & Alerts**
   - Daily health check email
   - Model drift detection
   - Data quality alerts

### **MEDIUM TERM (Next Quarter)**
3. **ML Model V3**
   - Balance direction sampling
   - Add rolling window features
   - Target: 52-55% avg prediction

4. **Dashboard Enhancements**
   - Visualizations (charts, trends)
   - Parlay diversity analysis
   - Real-time calibration

### **LONG TERM (Future)**
5. **Multi-Sport Expansion**
   - Generalize architecture for NBA, NFL, etc.
   - Shared pipeline, sport-specific resolvers

6. **Optimization Engine**
   - Linear programming for parlay construction
   - EV calculation and Kelly sizing

---

## Decision Review Schedule

**Monthly:** Review performance metrics, adjust thresholds
**Quarterly:** Evaluate ML model, consider retraining
**Annually:** Reassess architecture for scale/features

---

**Last Review:** May 6, 2026  
**Next Review:** June 6, 2026 (after 1 month production)  
**Reviewer:** Development Team
