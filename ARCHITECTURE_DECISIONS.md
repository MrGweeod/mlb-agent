# MLB Parlay Agent — Architecture Decisions
**Last Updated:** May 6, 2026 (Post-Optimization)

## Document Purpose
This document records the key architectural decisions made during the development of the MLB Parlay Agent, including the rationale, alternatives considered, and lessons learned. Updated with insights from production deployment and May 6 optimization work.

---

## Table of Contents
1. [Core Architecture](#core-architecture)
2. [ML Model Design](#ml-model-design)
3. [Data Pipeline](#data-pipeline)
4. [API Usage Optimization](#api-usage-optimization)
5. [Parlay Construction](#parlay-construction)
6. [Outcome Resolution](#outcome-resolution)
7. [Database Schema](#database-schema)
8. [Deployment Strategy](#deployment-strategy)
9. [Lessons Learned](#lessons-learned)

---

## Core Architecture

### **Decision: Three Daily Pipeline Runs**
**Chosen:** 9 AM (full), 12 PM (targeted), 5:30 PM (targeted)

**Why:**
- Props/odds change throughout the day
- Lineups confirm between 12-5 PM
- Late scratches happen before first pitch
- 3 runs provide comprehensive daily coverage

**Timeline:**
- **Originally:** 3 runs designed in Blueprint (April 2026)
- **April-May:** Reduced to 1 run (9 AM) when Discord bot removed
- **May 6:** Restored to 3 runs with optimization

**Alternatives Considered:**
- 1 run/day: Too infrequent, stale data by evening
- 5+ runs/day: Excessive API usage, minimal value gain
- Real-time streaming: Too complex, high API costs

**Trade-offs:**
- ✅ Fresh data 3x/day, automatic lineup checking
- ❌ Higher API usage (mitigated by targeted fetching)

**Status:** ✅ Implemented and tested May 6

---

### **Decision: Scheduled Batch Processing**
**Chosen:** Daily pipeline at fixed times (not real-time)

**Why:**
- Props don't change after games start
- Outcomes resolve next morning (official stats available)
- Reduces API costs (scheduled fetches vs continuous polling)
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
**Chosen:** Single Flask app with asyncio scheduler

**Why:**
- Simple deployment (one Railway service)
- Shared state (ML model, database connection)
- Easy debugging (single log stream)

**Alternatives Considered:**
- Microservices: Overkill for this scale, adds complexity
- Separate workers: Requires message queue, more infrastructure
- APScheduler: Originally used, switched to asyncio for better control

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

**Status:** ✅ Proven valuable during May 6 optimization

---

### **Decision: Lineup Consistency Filter**
**Chosen:** Filter props where player's lineup consistency <70%

**Why:**
- Reduces void rate (players ruled out after props logged)
- Improves parlay reliability
- Uses publicly available data (MLB-StatsAPI)

**Evolution:**
- **April Design:** Check `batting_order` field (1-9 = starter)
- **April-May 5:** Broken (field doesn't exist reliably)
- **May 6 Fix:** Check `ab >= 3` (at-bats proxy for starter)

**Implementation Challenges (May 6):**
- Original field (`batting_order`) unreliable
- Switched to `ab >= 3` as starter proxy
- Threshold: 0.70 (7+ games out of 10)

**Lessons Learned:**
- ✅ Filter concept works (reduces voids)
- ❌ MLB-StatsAPI field names require experimentation
- 🔄 Conservative error handling prevents catastrophic filtering

**Status:** ✅ Fixed and operational

---

### **Decision: Single Daily Props Fetch → Three Daily Fetches**
**Evolution:**

**Original (April):** 3 fetches/day (9 AM / 12 PM / 5:30 PM)
**April-May 5:** 1 fetch/day (9 AM only)
**May 6:** 3 fetches/day with targeted optimization

**Why the change back:**
- Odds move throughout the day
- Lineups confirm between 12-5 PM
- Late scratches happen before games
- User requested full day coverage

**Optimization Applied (May 6):**
- 9 AM: Fetch full slate (wide net)
- 12 PM: Fetch targeted (eligible players only)
- 5:30 PM: Fetch targeted (upcoming games only)

**Trade-offs:**
- ✅ Fresh odds 3x/day, automatic lineup checks
- ✅ Still under API quota (40 objects/day vs 100K/month limit)

**Status:** ✅ Implemented May 6

---

## API Usage Optimization

### **Decision: Targeted SGO Fetching**
**Chosen:** Fetch all games, filter props locally to eligible players

**Why:**
- SGO API charges per game-event, not per prop
- No per-player endpoint exists
- Fetching 15 games = 15 objects (regardless of props parsed)
- Filtering locally saves processing time

**Discovery (May 6):**
- Original concern: "3 full fetches = 4500 objects/day = 135K/month (35% over)"
- Actual reality: "3 fetches = 40 objects/day = 1.2K/month (99% under!)"
- Key insight: SGO embeds props in game-event objects

**Implementation:**
```python
def fetch_props_for_players(date_str, player_ids=None):
    games = get_todays_games(date=date_str)  # 15 games = 15 objects
    all_props = [get_player_props(g) for g in games]  # Parse locally
    if player_ids:
        return [p for p in all_props if p['player_id'] in player_ids]
    return all_props
```

**Alternatives Considered:**
- Per-player API endpoint: Doesn't exist in SGO
- Caching games across runs: Complex state management
- Reducing to 2 runs/day: Less fresh data

**Trade-offs:**
- ✅ 99% under free tier (1.2K vs 100K limit)
- ✅ Fresh odds 3x/day
- ❌ Can't reduce below ~15 objects per fetch

**Status:** ✅ Implemented and validated May 6

---

### **Decision: Automatic Lineup Checking**
**Chosen:** Check confirmed lineups at 12 PM and 5:30 PM via MLB-StatsAPI

**Why:**
- Late scratches are common in MLB
- Manual checking not scalable
- `statsapi.boxscore_data()` provides confirmed lineups
- Integrates naturally into targeted pipeline runs

**Implementation (May 6):**
```python
boxscore = statsapi.boxscore_data(game_pk)
starters = set(boxscore['away']['battingOrder'] + boxscore['home']['battingOrder'])
for leg in legs:
    if leg['player_id'] not in starters:
        leg['lineup_status'] = 'scratched'
```

**Edge Cases Handled:**
- Pitcher props skip lineup check (not in batting order)
- API failures → mark 'unknown', include conservatively
- Game postponed → still shows in lineup

**Alternatives Considered:**
- Manual checking: Not scalable
- Third-party lineup APIs: Additional cost, complexity
- Wait for post-game resolution: Too late (bets already placed)

**Trade-offs:**
- ✅ Automatic scratch detection
- ✅ Free API (MLB-StatsAPI)
- ❌ Requires game to be "live" (lineups posted)

**Status:** ✅ Implemented May 6

---

### **Decision: Game Start Filtering**
**Chosen:** Exclude games starting within next 15 minutes

**Why:**
- Prevents recommendations for imminent games
- Gives user time to review and place bets
- Integrates with targeted pipeline (12 PM / 5:30 PM)

**Implementation (May 6):**
```python
cutoff = now_et + timedelta(minutes=15)
upcoming = [leg for leg in legs if leg['game_start_time'] > cutoff]
```

**Bug Fixed (May 6):**
- Original: `cutoff = now_et - buffer_minutes` (backwards!)
- Fixed: `cutoff = now_et + buffer_minutes`

**Alternatives Considered:**
- No buffer: Risk recommending games about to start
- Longer buffer (30-60 min): Removes too many legs
- Per-user buffer: Complex, unnecessary

**Trade-offs:**
- ✅ Gives user time to act
- ❌ Reduces leg pool slightly (minimal impact)

**Status:** ✅ Fixed and working

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
4. Odds range: +600 to +1500 (balances risk/reward)

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
- Error messages cryptic (`season` param issue in lineup filter)
- Field names inconsistent (`batting_order` unreliable)

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

### **Decision: No New Tables for Lineup Status**
**Chosen:** Add columns to existing `mlb_scored_legs` table

**Why:**
- Simple schema (no new tables)
- Lineup status tied to specific leg instance
- Query performance sufficient

**Columns NOT Added (May 6):**
- Initially planned: `lineup_status`, `game_status` columns
- Actual: Computed on-the-fly in pipeline, not persisted
- Reason: Status changes during day, database updates complex

**Alternative (Chosen):**
- Compute status in memory during pipeline runs
- Filter before parlay construction
- Don't persist transient state

**Trade-offs:**
- ✅ Simple, no schema changes needed
- ❌ Can't query historical lineup statuses (acceptable)

**Status:** ✅ Working without database changes

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

### **Decision: Asyncio Scheduler (Not APScheduler)**
**Chosen:** Custom asyncio-based scheduler in Flask app

**Why:**
- Better control over startup catch-up logic
- Timezone-aware (ET for MLB)
- No external dependencies (APScheduler removed)

**Implementation:**
```python
async def _pipeline_scheduler():
    # Startup catch-up within 2-hour window per slot
    # Main loop: calculate next run, sleep, execute
    while True:
        next_run = find_next_scheduled_time()
        await asyncio.sleep(seconds_until(next_run))
        await run_pipeline_for_slot()
```

**Challenges:**
- Timezone handling (ET vs UTC)
- Startup catch-up: Only runs if within 2-hour window

**Lessons Learned:**
- ✅ Works reliably for daily jobs
- ✅ Startup catch-up crucial for Railway redeploys
- 🔄 2-hour window chosen empirically (works well)

**Status:** ✅ Working reliably, no missed runs

---

### **Decision: Environment Variables for Secrets**
**Chosen:** Railway environment variables + python-dotenv

**Why:**
- Security: No secrets in code
- Flexibility: Different values per environment (dev/prod)

**Variables Used:**
- `SUPABASE_URL`, `SUPABASE_KEY` (database)
- `ODDS_API_KEY` (morning props fetch)
- `SPORTSGAMEODDS_API_KEY` (all SGO fetches)
- `PORT` (Railway assigned)

**Status:** ✅ No issues

---

## Lessons Learned

### **1. API Documentation is Incomplete — Experiment!**
**What Happened:**
- MLB-StatsAPI docs didn't clarify field availability
- `batting_order` field assumed to exist (didn't reliably)
- `season` + `type='gameLog'` parameter combo caused errors

**Lesson:**
- ✅ Budget time for API experimentation
- ✅ Add conservative error handling (return None vs crash)
- ✅ Add circuit breakers for critical filters
- 🔄 Document API quirks in code comments

**Applied:**
- Switched `batting_order` → `ab >= 3` check
- Added error handling in lineup consistency filter
- Circuit breaker disables filter if >90% removed

---

### **2. Understand API Pricing Models Before Optimization**
**What Happened:**
- Assumed SGO charged per prop (~1500 objects per fetch)
- Discovered SGO charges per game-event (~15 objects per fetch)
- "Optimization" already achieved by API design!

**Lesson:**
- ✅ Read pricing docs carefully
- ✅ Test API to understand actual object consumption
- ✅ Don't over-optimize based on assumptions

**Applied:**
- Validated SGO charges per game-event, not per prop
- Realized 3 fetches/day = 40 objects (not 4500)
- Moved forward with confidence (99% under quota)

---

### **3. Edge Cases Matter (Void Logic)**
**What Happened:**
- Assumed ANY void → parlay void (seemed logical)
- Didn't account for partial voids (common in MLB)
- Resulted in inflated void rate (5.9% → 0%)

**Lesson:**
- ✅ Test edge cases early (partial voids, all voids, no voids)
- ✅ Validate against expected outcomes (sportsbook behavior)
- 🔄 Write unit tests for resolution logic (future)

**Applied:**
- Fixed void logic to match sportsbook standard
- Backfilled historical data to correct
- Documented edge cases in code

---

### **4. Conservative Defaults Prevent Catastrophic Failures**
**What Happened:**
- Lineup filter API errors → include player conservatively
- Circuit breaker: Disable filter if >90% filtered
- Prevented 100% filtering from blocking production

**Lesson:**
- ✅ "Include when uncertain" better than "exclude when uncertain"
- ✅ Circuit breakers catch systemic issues
- ✅ Logging helps diagnose (shows individual player results)

**Applied:**
- Error handling includes player (doesn't filter)
- Circuit breaker at 90% threshold
- Detailed logging for debugging

---

### **5. Separation of Concerns Enables Debugging**
**What Happened:**
- Two-stage pipeline (fetch → build) allowed regeneration without refetching
- Separate resolution (legs → parlays) allowed independent testing

**Lesson:**
- ✅ Modularity pays off during debugging
- ✅ Database as source of truth enables auditing
- ✅ Idempotent operations (safe to re-run) are valuable

**Applied:**
- Maintained two-stage pipeline structure
- Kept resolution phases separate
- All operations idempotent (can re-run safely)

---

### **6. User Product Vision Trumps Technical Assumptions**
**What Happened:**
- Removed 12 PM and 5:30 PM runs (assumed 1 run sufficient)
- User expected 3 runs with fresh odds throughout day
- Gap between implementation and user expectations

**Lesson:**
- ✅ Clarify product requirements before optimizing
- ✅ Don't assume efficiency = better user experience
- ✅ Ask "what does the user want" not "what's simplest"

**Applied:**
- Restored 3 daily runs with user's vision
- Implemented targeted fetching to balance cost/freshness
- Product requirements drove technical solution

---

### **7. Optimization Reveals Hidden Efficiency**
**What Happened:**
- Designed "targeted fetching" to reduce API usage
- Discovered SGO already optimized (charges per game, not prop)
- "Optimization" validated API was efficient all along

**Lesson:**
- ✅ Optimization exercises reveal system behavior
- ✅ Sometimes "optimizing" means discovering it's already optimal
- ✅ Validation is as valuable as optimization

**Applied:**
- Documented SGO pricing model in code
- Moved forward with 3 runs/day confidently
- Removed API usage as a concern

---

### **8. Type Safety Prevents Silent Bugs**
**What Happened:**
- `run_date` stored as TEXT, queries compared to TIMESTAMP
- SQL failed silently → HTTP 500 errors

**Lesson:**
- ✅ Use correct types from schema design (DATE not TEXT)
- ✅ Type casting (`::date`) works but adds overhead
- 🔄 Consider schema migration tools (Alembic) for future

**Applied:**
- Fixed with ::date casts in all queries
- Documented issue for future schema review
- Working but not ideal (future migration candidate)

---

## Future Architectural Improvements

### **SHORT TERM (This Month)**
1. **Add Unit Tests**
   - Void logic (all cases)
   - Lineup filter (error handling)
   - Parlay construction (constraints)

2. **Monitoring & Alerts**
   - Daily health check email
   - SGO quota tracking
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

5. **Schema Migration**
   - Change `run_date` from TEXT to DATE
   - Add indexes for common queries
   - Consider partitioning by date

### **LONG TERM (Future)**
6. **Multi-Sport Expansion**
   - Generalize architecture for NBA, NFL, etc.
   - Shared pipeline, sport-specific resolvers

7. **Optimization Engine**
   - Linear programming for parlay construction
   - EV calculation and Kelly sizing

8. **Manual Button Improvements**
   - "Refresh" fetches fresh odds on-demand
   - "Regenerate Now" triggers mini-pipeline
   - User-configurable buffer times

---

## Decision Review Schedule

**Weekly:** Review SGO usage, pipeline success rate
**Monthly:** Review performance metrics, adjust thresholds
**Quarterly:** Evaluate ML model, consider retraining
**Annually:** Reassess architecture for scale/features

---

**Last Review:** May 6, 2026  
**Next Review:** June 6, 2026 (after 1 month of 3-run production)  
**Reviewer:** Development Team


**Last Review:** May 6, 2026  
**Next Review:** June 6, 2026 (after 1 month production)  
**Reviewer:** Development Team
