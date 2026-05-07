# MLB Parlay Agent — Architecture Decisions
**Last Updated:** May 7, 2026 (Post-Infrastructure Upgrade)

## Document Purpose
This document records the key architectural decisions made during the development of the MLB Parlay Agent, including the rationale, alternatives considered, and lessons learned. Updated with insights from May 7's major infrastructure upgrade and yesterday's 4/5 parlay win.

---

## Table of Contents
1. [Core Architecture](#core-architecture)
2. [ML Model Design](#ml-model-design)
3. [Data Pipeline](#data-pipeline)
4. [V2 Normalized Schema](#v2-normalized-schema)
5. [API Usage Optimization](#api-usage-optimization)
6. [Parlay Construction](#parlay-construction)
7. [Outcome Resolution](#outcome-resolution)
8. [Database Schema](#database-schema)
9. [Deployment Strategy](#deployment-strategy)
10. [Validation & Filtering](#validation--filtering)
11. [Lessons Learned](#lessons-learned)

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

**Status:** ✅ Working perfectly, validated in production

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

**Problem Discovered:**
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

**Status:** ✅ Critical for debugging, proven valuable

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

**Status:** ✅ Proven valuable, enables manual regeneration

---

### **Decision: Lineup Consistency Filter**
**Chosen:** Filter props where player's lineup consistency <70%

**Why:**
- Reduces void rate (players ruled out after props logged)
- Improves parlay reliability
- Uses publicly available data (MLB-StatsAPI)

**Evolution:**
- **April Design:** Check `batting_order` field (1-9 = starter)
- **April-May 6:** Broken (field doesn't exist reliably)
- **May 7 Fix:** Check `ab >= 3` via correct MLB-StatsAPI path

**Implementation Challenges:**
- Original field (`batting_order`) unreliable
- Switched to `ab >= 3` as starter proxy (at-bats field)
- Had to navigate nested MLB-StatsAPI structure

**Lessons Learned:**
- ✅ Filter concept works (removes bench players)
- ❌ MLB-StatsAPI documentation incomplete, requires experimentation
- ✅ Conservative error handling prevents catastrophic filtering
- 🔄 Circuit breaker at 90% critical for safety

**Status:** ✅ Fixed May 7, working correctly

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

**Optimization Applied:**
- 9 AM: Fetch full slate (wide net)
- 12 PM: Fetch targeted (eligible players only)
- 5:30 PM: Fetch targeted (upcoming games only)

**Trade-offs:**
- ✅ Fresh odds 3x/day, automatic lineup checks
- ✅ Still under API quota (40 objects/day vs 100K/month limit)

**Status:** ✅ Working perfectly

---

## V2 Normalized Schema

### **Decision: Normalized Schema (Separate Header + Detail Tables)**
**Chosen:** May 7, 2026

**Problem:**
- Old schema: JSON legs in single table
- Couldn't query: "Show me all Cody Bellinger hit under legs"
- Couldn't extract: Parlay-level features for ML model
- Couldn't analyze: Per-leg vs per-parlay performance

**Solution:**
```sql
-- Parlay header (one row per parlay)
mlb_parlay_recommendations_v2 (
    id, run_date, rank, total_odds, avg_coverage, 
    num_legs, outcome, source, batch_id, created_at
)

-- Parlay legs (one row per leg)
mlb_parlay_legs_v2 (
    id, parlay_id, player_id, player_name, stat, 
    line, direction, odds, composite_score, coverage, 
    outcome, result_value, created_at
)
```

**Why Normalized:**
- ✅ Can query individual legs: `SELECT * FROM mlb_parlay_legs_v2 WHERE player_name = 'Bellinger'`
- ✅ Can analyze player/stat hit rates
- ✅ Can extract parlay-level features (correlation, diversity)
- ✅ Efficient resolution: Update one leg row vs parsing JSON
- ✅ Proper relational model

**Alternatives Considered:**

**Option A: Modify existing table** (add columns to old schema)
- ❌ Still has JSON legs (can't query individual legs)
- ❌ No per-leg outcome tracking

**Option B: New table, same JSON structure** (clean slate but same design)
- ❌ Still can't answer leg-level questions
- ❌ No per-leg analytics

**Option C: Normalized schema** ✅ **CHOSEN**
- ✅ Per-leg tracking
- ✅ SQL aggregations
- ✅ Parlay-level features
- ❌ More complex queries (JOINs required)
- ❌ Bigger refactor (worth it)

**Migration Strategy:**
- Dual-write system (save to both old + new)
- Backfill 28 historical parlays
- Keep old table for historical reference
- No data loss, rollback possible

**Status:** ✅ Deployed May 7, 39 parlays + 156 legs tracked

---

### **Decision: Dual-Write System**
**Chosen:** Save parlays to BOTH old and new schemas

**Why:**
- Backward compatibility (old queries still work)
- Safety net (can rollback if issues)
- Gradual migration (validate new schema first)

**Implementation:**
```python
# Save to old schema (existing logic)
save_recommendations(parlays, run_date)

# Save to new v2 schema (new logic)
save_recommendations_v2(parlays, run_date, source='auto_9am')
```

**Trade-offs:**
- ✅ Zero downtime, zero risk
- ✅ Old system continues working
- ❌ Double writes (minimal overhead)
- ❌ Schema divergence over time (acceptable)

**Status:** ✅ Working perfectly, no issues

---

## API Usage Optimization

### **Decision: Targeted SGO Fetching**
**Chosen:** Fetch all games, filter props locally to eligible players

**Why:**
- SGO API charges per game-event, not per prop
- No per-player endpoint exists
- Fetching 15 games = 15 objects (regardless of props parsed)
- Filtering locally saves processing time

**Discovery:**
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

**Status:** ✅ Working perfectly, API usage optimized

---

### **Decision: Automatic Lineup Checking**
**Chosen:** Check confirmed lineups at 12 PM and 5:30 PM via MLB-StatsAPI

**Why:**
- Late scratches are common in MLB
- Manual checking not scalable
- `statsapi.boxscore_data()` provides confirmed lineups
- Integrates naturally into targeted pipeline runs

**Implementation:**
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

**Status:** ✅ Working reliably

---

## Parlay Construction

### **Decision: Greedy Construction with Constraints**
**Chosen:** Build parlays sequentially, apply diversity rules

**Why:**
- Simple to implement and reason about
- Constraints prevent over-correlation
- 5 parlays = good diversity without overwhelming user

**Constraints Applied:**
1. Max 1 leg per game (prevents single-game risk)
2. Max 2 legs per player (prevents over-exposure)
3. Max 1 leg per prop type per parlay (diversifies prop types)
4. Odds range: +600 to +1500 (balances risk/reward)
5. **NEW (May 7):** WALKS + STRIKEOUTS conflict check (DraftKings rule)

**Alternatives Considered:**
- Optimization (linear programming): Overkill, harder to debug
- Random sampling: Less consistent quality
- User-defined constraints: More flexible but complex UX

**Trade-offs:**
- ✅ Simple, consistent, explainable
- ❌ May miss optimal combinations (good enough > perfect)

**Status:** ✅ Producing valid parlays, DraftKings-compliant

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
- **NEW (being tested):** Correlation-adjusted score

**Trade-offs:**
- ✅ Simple, interpretable
- ❌ Doesn't account for correlation risk (testing hypothesis)

**Status:** ✅ Working, pending correlation validation

---

### **Decision: WALKS + STRIKEOUTS Conflict Check**
**Chosen:** May 7, 2026

**Problem:** DraftKings doesn't allow WALKS + STRIKEOUTS in same parlay

**Solution:** Add validation during parlay construction

**Implementation:**
```python
# In Branch-and-Bound loop:
if leg_stat == "walks" and any(l["stat"] == "strikeouts" for l in legs):
    continue  # Skip invalid combination
if leg_stat == "strikeouts" and any(l["stat"] == "walks" for l in legs):
    continue  # Skip invalid combination
```

**Why Early Pruning (Not Post-Filtering):**
- More efficient (prunes invalid branches early)
- Consistent with other constraints (same-game, same-player)
- No logging needed (silent filtering like other constraints)

**Trade-offs:**
- ✅ All parlays DraftKings-valid
- ✅ Early pruning = faster construction
- ❌ Slightly reduces candidate pool (acceptable)

**Status:** ✅ Deployed May 7, active

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

**Status:** ✅ Fixed, tested, validated (0% void rate)

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

## Validation & Filtering

### **Decision: Chronological Leg Sorting**
**Chosen:** May 7, 2026

**Problem:** Legs displayed in random construction order

**Solution:** Sort by game start time (earliest → latest)

**Why:**
- Better user experience (track games chronologically)
- Consistent with Legs tab sorting
- Easier mental model (matches actual game order)

**Implementation:**
```python
def sort_legs_by_game_time(legs):
    """Sort legs by game start time."""
    # Uses commence_time field from props
    # Handles missing times (sorts to end)
    # Works across old + new schemas
```

**Applied in:**
- Database saves (old + v2)
- Web UI endpoint (before display)

**Field Used:**
- `commence_time` from SGO props data (not `game_start_time`)
- Had to investigate actual field name (API exploration)

**Lessons Learned:**
- ✅ Field naming varies by API (test before assuming)
- ✅ Sorting improves UX significantly
- 🔄 Applied in 3 places for consistency

**Status:** ✅ Fixed May 7, working perfectly

---

### **Decision: Correlation Risk Logging**
**Chosen:** May 7, 2026

**Problem:** No way to track correlation hypothesis

**Solution:** Log correlation metrics for every parlay

**Why:**
- Enables post-hoc analysis (after 50+ parlays)
- Grep-friendly format for extraction
- No behavior change (observation only)

**Implementation:**
```python
[parlay_correlation] rank=1 correlation_risk=0.250 legs_same_game=1 num_legs=4 avg_coverage=76.200
```

**What NOT to Do:**
- ❌ Don't add correlation penalty without validation
- ❌ Don't act on 5 data points (wait for 50+)
- ✅ Log now, validate later

**Lessons Learned:**
- ✅ Logging enables future validation without behavior change
- ✅ Observational data is valuable
- 🔄 Wait for statistical significance before acting

**Status:** ✅ Active, collecting data

---

## Lessons Learned

### **1. API Documentation is Incomplete — Experiment!**
**What Happened:**
- MLB-StatsAPI docs didn't clarify field structure
- `batting_order` field assumed to exist (didn't reliably)
- `commence_time` vs `game_start_time` naming confusion

**Lesson:**
- ✅ Budget time for API experimentation
- ✅ Add conservative error handling
- ✅ Add circuit breakers for critical filters
- 🔄 Document API quirks in code comments

**Applied:**
- Switched `batting_order` → `ab >= 3` check via correct path
- Discovered `commence_time` is actual field name
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

### **4. Small Sample Sizes Lie — Wait for Statistical Significance**
**What Happened (May 6-7):**
- Observed: 4 winners had low correlation, 1 loser had high correlation
- Excitement: "Correlation predicts losses! Add penalty now!"
- Reality: n=5 is not statistically significant

**Lesson:**
- ✅ Don't act on patterns from <50 samples
- ✅ Form hypothesis, collect data, test statistically
- ✅ Observational logging enables future validation
- ❌ Curve-fitting to noise is dangerous

**Applied:**
- Added correlation logging (observation only)
- No behavior changes until 50-100 parlays resolved
- Will run t-test before implementing penalty
- User kept system disciplined (thank you!)

**Status:** 🧪 Hypothesis formed, data collection in progress

---

### **5. Normalized Schema Enables Analytics**
**What Happened:**
- Old schema: JSON legs, no per-leg queries
- Couldn't answer: "Does Cody Bellinger hit under win?"
- Couldn't extract: Parlay-level features

**Lesson:**
- ✅ Normalized data unlocks SQL analytics
- ✅ Per-leg tracking enables player/stat analysis
- ✅ Dual-write enables safe migration
- 🔄 Worth the upfront refactor cost

**Applied:**
- Deployed v2 normalized schema May 7
- 39 parlays + 156 legs tracked
- Feature extraction working
- Analytics ready for ML model training

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

### **7. Silent Validation (DraftKings Rules)**
**What Happened (May 7):**
- DraftKings doesn't allow WALKS + STRIKEOUTS
- System was generating invalid parlays
- Added validation during construction (not post-filtering)

**Lesson:**
- ✅ Early pruning is more efficient
- ✅ Silent filtering consistent with other constraints
- ✅ Validate against real-world rules early
- 🔄 Test with actual sportsbook before assuming rules

**Applied:**
- WALKS + STRIKEOUTS check in Branch-and-Bound loop
- Early pruning (skip invalid branches)
- No logging (consistent with other constraints)
- All parlays now DraftKings-valid

---

### **8. Chronological Sorting Improves UX**
**What Happened:**
- Legs displayed in random order (construction order)
- User requested chronological sorting
- Discovered field name was `commence_time` not `game_start_time`

**Lesson:**
- ✅ Small UX improvements matter
- ✅ Test actual field names (don't assume)
- ✅ Apply consistently across system
- 🔄 User feedback drives valuable improvements

**Applied:**
- Sorted legs by `commence_time` (earliest → latest)
- Applied in database saves + web UI
- Consistent with Legs tab
- Better tracking experience

---

## Future Architectural Improvements

### **SHORT TERM (This Month)**
1. **Parlay-Level ML Model**
   - Train when 50-100 parlays resolved
   - Features: correlation, coverage distribution, diversity
   - Target: Predict "Will this parlay win?"
   - Validate vs baseline (bet all >75% avg coverage)

2. **Correlation Validation**
   - Extract logs after 50+ parlays
   - Run t-test: zero vs high correlation win rates
   - If p < 0.05, implement correlation penalty
   - Document findings

3. **Dashboard Enhancement (5th Tab)**
   - Parlay History with expandable legs
   - Click to expand/collapse leg details
   - Per-leg outcomes visible
   - Filter by date, outcome, correlation risk

### **MEDIUM TERM (Next Quarter)**
4. **ML Model V3 (Leg-Level)**
   - Balance direction sampling
   - Add rolling window features
   - Target: 52-55% avg prediction (up from 50.5%)
   - Retrain when 500+ more samples

5. **Monitoring & Alerts**
   - Daily health check email
   - SGO quota tracking
   - Model drift detection
   - Data quality alerts

6. **Schema Migration**
   - Change `run_date` from TEXT to DATE
   - Add indexes for common queries
   - Consider partitioning by date

### **LONG TERM (Future)**
7. **Multi-Sport Expansion**
   - Generalize architecture for NBA, NFL, etc.
   - Shared pipeline, sport-specific resolvers

8. **Optimization Engine**
   - Linear programming for parlay construction
   - EV calculation and Kelly sizing

9. **Advanced Correlation Detection**
   - Same-game correlation penalties
   - Pitcher dominance thesis (K over + opposing batter hits under)
   - Weather-based correlations

---

## Decision Review Schedule

**Daily:** Monitor pipeline runs, system health
**Weekly:** Review correlation logging, SGO usage
**Monthly:** Review performance metrics, adjust thresholds
**Quarterly:** Evaluate ML model, consider retraining
**Annually:** Reassess architecture for scale/features

---

**Last Review:** May 7, 2026  
**Next Review:** May 14, 2026 (after 7 days of v2 schema validation)  
**Major Milestone:** V2 normalized schema deployed, correlation hypothesis formed
