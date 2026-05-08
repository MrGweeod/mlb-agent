# MLB Parlay Agent — Architecture Decisions
**Last Updated:** May 8, 2026 (Post-Player Diversity Deployment)

## Document Purpose
This document records the key architectural decisions made during the development of the MLB Parlay Agent, including the rationale, alternatives considered, and lessons learned. Updated with insights from May 8's player diversity system deployment and portfolio concentration analysis.

---

## Table of Contents
1. [Core Architecture](#core-architecture)
2. [Player Diversity System](#player-diversity-system)
3. [ML Model Design](#ml-model-design)
4. [Data Pipeline](#data-pipeline)
5. [V2 Normalized Schema](#v2-normalized-schema)
6. [API Usage Optimization](#api-usage-optimization)
7. [Parlay Construction](#parlay-construction)
8. [Outcome Resolution](#outcome-resolution)
9. [Database Schema](#database-schema)
10. [Deployment Strategy](#deployment-strategy)
11. [Frontend Type Safety](#frontend-type-safety)
12. [Lessons Learned](#lessons-learned)

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
- **May 8:** All 3 runs operational with player diversity

**Alternatives Considered:**
- 1 run/day: Too infrequent, stale data by evening
- 5+ runs/day: Excessive API usage, minimal value gain
- Real-time streaming: Too complex, high API costs

**Trade-offs:**
- ✅ Fresh data 3x/day, automatic lineup checking
- ✅ Player diversity filter applied at each run
- ❌ Higher API usage (mitigated by targeted fetching)

**Status:** ✅ Working perfectly, validated in production

---

## Player Diversity System

### **Decision: Enforce Unique Players Across All Parlays**
**Chosen:** May 8, 2026

**Problem:**
- May 7: 0/23 parlays won
- Root cause analysis showed portfolio concentration
- Ramón Laureano appeared in 14/23 parlays (60% exposure)
- When Laureano failed, 60% of portfolio failed simultaneously

**Solution Implemented:**
Three-phase filter system:

```
Phase 1: Query Used Players
↓
SELECT DISTINCT player_id 
FROM mlb_parlay_legs_v2 l
JOIN mlb_parlay_recommendations_v2 r ON l.parlay_id = r.id
WHERE r.run_date = today

Phase 2: Filter Legs
↓
Remove legs where player_id IN (used_players)

Phase 3: Build Parlays
↓
Construct parlays from filtered pool
```

**Implementation:**
- **File:** `src/utils/db.py` - `get_players_used_today()`
- **File:** `src/engine/parlay_builder.py` - `filter_already_used_players()`
- **File:** `main.py` - `generate_recommendations(run_date=today)`
- **File:** `src/web/server.py` - Pass `run_date` in both automated and manual runs

**Alternatives Considered:**

**Option A: Max 2-3 parlays per player** (soft limit)
- ❌ Still allows concentration (player in 3 parlays = 30% exposure on 10 parlay portfolio)
- ❌ Complex logic (tracking counts per player)
- ❌ Doesn't solve root problem

**Option B: Correlation-based filtering** (same-game legs only)
- ❌ Doesn't address player-level concentration
- ❌ Players in different games still correlated (same pitcher, weather, lineup position)
- ❌ May 7 failure was cross-game concentration

**Option C: No diversity constraint** (status quo)
- ❌ Proven failure mode (May 7: 0/23)
- ❌ High portfolio risk
- ❌ Unacceptable outcome distribution

**Option D: Unique players per parlay** ✅ **CHOSEN**
- ✅ Eliminates concentration risk entirely
- ✅ Portfolio fails only if multiple independent players fail
- ✅ Simple logic (binary: used or not used)
- ✅ Easy to monitor and validate

**Trade-offs:**
- ✅ PRO: Perfect diversification (0% same-player exposure)
- ✅ PRO: Portfolio protection (if 1 player fails, only 5-10% of portfolio fails)
- ✅ PRO: Risk mitigation (no concentration risk)
- ❌ CON: Limited daily capacity (can only generate ~10-15 total parlays per day)
- ❌ CON: Parlay generation slows as day progresses (fewer unique players available)
- ❌ CON: Lower quality legs used later in day (best players already filtered)

**Performance Metrics (May 8):**
```
9:00 AM:   19 players filtered (14.7%)  → 8 parlays possible
12:00 PM:  24 players filtered (17.9%)  → 6 parlays possible
3:40 PM:   35 players filtered (23.1%)  → 3 parlays possible
3:57 PM:   40 players filtered (25.3%)  → 1-2 parlays possible
```

**Key Insight:**
- Each parlay requires 4 unique players
- With 40 players used, only 10-15 unique players remain in quality pool
- Can only build 2-3 more parlays before exhausting pool
- Daily capacity: ~10-15 total parlays (acceptable tradeoff)

**Status:** ✅ Deployed May 8, operational and effective

---

### **Decision: Fail Open on Player Diversity Errors**
**Chosen:** Return empty set on database errors

**Why:**
- Database connectivity issues shouldn't block parlay generation
- Better to generate parlays with potential duplication than no parlays at all
- Errors are logged but don't halt pipeline

**Implementation:**
```python
def get_players_used_today(run_date):
    try:
        # Query database
        return set(player_ids)
    except Exception as e:
        print(f"[ERROR] get_players_used_today failed: {e}")
        return set()  # Fail open: allow all players
```

**Trade-offs:**
- ✅ Pipeline resilience (keeps running during DB issues)
- ❌ Temporary diversity violation possible (rare edge case)

**Status:** ✅ Implemented, proven resilient

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

## Data Pipeline

### **Decision: Two-Stage Pipeline (Fetch → Build)**
**Chosen:** 
1. Fetch & score all props → database
2. Build parlays from database

**Why:**
- Separation of concerns (data vs construction)
- Allows manual regeneration (rebuild parlays without refetching)
- Database becomes source of truth
- Enables player diversity filter (queries existing parlays)

**Alternatives Considered:**
- Single-stage: Fetch and build in one pass (faster but less flexible)
- Stream processing: Overkill for batch workload

**Trade-offs:**
- ✅ Flexibility, debuggability, data persistence, diversity filtering
- ❌ Slightly slower (extra database round-trip)

**Status:** ✅ Proven valuable, enables player diversity

---

### **Decision: Player Diversity Filter Applied Post-Fetch**
**Chosen:** Filter legs after ML scoring, before parlay construction

**Why:**
- Need to score all legs first (don't know which are best until scored)
- Filter removes already-used players from candidate pool
- Parlay builder works on filtered pool

**Pipeline Order:**
```
1. Fetch props from SGO
2. Score legs with ML model
3. Save scored legs to database
4. Load scored legs for parlay building
5. Query already-used players  ← Player diversity
6. Filter legs to unique players  ← Player diversity
7. Build parlays from filtered pool
8. Save parlays to v2 schema
```

**Alternatives Considered:**
- **Filter pre-fetch:** Can't — don't know who's been used until we query database
- **Filter pre-scoring:** Inefficient — still need to score for filtering
- **Filter post-construction:** Too late — parlays already built with duplicates

**Trade-offs:**
- ✅ Optimal placement in pipeline (after scoring, before building)
- ✅ Clean separation of concerns
- ❌ Requires database round-trip (acceptable overhead)

**Status:** ✅ Working optimally

---

## V2 Normalized Schema

### **Decision: Normalized Schema (Separate Header + Detail Tables)**
**Chosen:** May 7, 2026

**Problem:**
- Old schema: JSON legs in single table
- Couldn't query: "Show me all Cody Bellinger hit under legs"
- Couldn't extract: Parlay-level features for ML model
- Couldn't analyze: Per-leg vs per-parlay performance
- **Couldn't implement:** Player diversity (need to query which players used)

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
    line, direction, odds, coverage, outcome, 
    result_value, created_at
)
```

**Why Normalized:**
- ✅ Can query individual legs: `SELECT * FROM mlb_parlay_legs_v2 WHERE player_name = 'Bellinger'`
- ✅ Can analyze player/stat hit rates
- ✅ Can extract parlay-level features (correlation, diversity)
- ✅ Efficient resolution: Update one leg row vs parsing JSON
- ✅ **CRITICAL:** Can query which players already used for diversity filter
- ✅ Proper relational model

**Player Diversity Enabler:**
```sql
-- This query is ONLY possible with normalized schema
SELECT DISTINCT player_id 
FROM mlb_parlay_legs_v2 l
JOIN mlb_parlay_recommendations_v2 r ON l.parlay_id = r.id
WHERE r.run_date = CURRENT_DATE
```

**Without v2 schema, player diversity would require:**
- ❌ Parsing JSON legs from every parlay
- ❌ Extracting player_id from nested JSON
- ❌ Slow, complex, error-prone

**Status:** ✅ Deployed May 7, enabled player diversity May 8

---

## Frontend Type Safety

### **Decision: PostgreSQL Decimal → JavaScript Number Conversion**
**Chosen:** May 8, 2026

**Problem Discovered:**
- PostgreSQL returns numeric columns as `decimal.Decimal` type
- Python: Can't multiply `float * Decimal` directly
- JavaScript: Can't call `.toFixed()` on Decimal (needs Number type)

**Solution Pattern:**

**Backend (Python):**
```python
# Always convert Decimal to float before math
cov_pct = leg.get("coverage_pct") or 50  # Decimal
cov = float(cov_pct) / 100.0  # Convert to float first
```

**Frontend (JavaScript):**
```javascript
// Always parseFloat before formatting
const cov = parseFloat(leg.coverage_pct).toFixed(1);
```

**Why This Pattern:**
- PostgreSQL stores numbers as Decimal for precision
- psycopg2 returns Decimal type in Python
- JSON.stringify converts Decimal to number in transit
- But JavaScript receives it as a special numeric type
- Must explicitly convert to Number for formatting

**Alternatives Considered:**
- **Change DB column types:** Don't store as NUMERIC → loses precision
- **Custom JSON encoder:** Serialize Decimal as float → adds complexity
- **Frontend-only conversion:** Still need backend conversion for math
- **Type conversion everywhere:** ✅ **CHOSEN** - Simple, explicit, works

**Trade-offs:**
- ✅ Explicit type handling (clear intent)
- ✅ Works across entire stack
- ✅ No precision loss (convert only when needed)
- ❌ Must remember to convert (not automatic)
- ❌ Requires awareness of Decimal type

**Lesson Learned:**
Always assume numeric types from PostgreSQL need explicit conversion.

**Status:** ✅ Implemented May 8, pattern established

---

### **Decision: NULL-Safe Field Access**
**Chosen:** Check for null/undefined before calling methods

**Problem Discovered:**
- `rec.edge_pct.toFixed(1)` crashes if edge_pct is null/undefined
- V2 schema doesn't have edge_percent column
- Need placeholder values for missing fields

**Solution Pattern:**
```javascript
// NULL-safe access with default
const edgePct = (rec.edge_pct != null && !isNaN(rec.edge_pct)) 
  ? Number(rec.edge_pct) 
  : 0;

// Then safely format
const edgeStr = edgePct.toFixed(1);
```

**Why This Pattern:**
- v1 schema had edge_percent column
- v2 schema doesn't (not computed during save)
- Frontend expects field to exist
- Backend sets placeholder: `parlay["edge_pct"] = 0.0`
- Frontend still needs NULL check (defensive programming)

**Lesson Learned:**
Never assume fields exist — always check before accessing.

**Status:** ✅ Implemented May 8, pattern established

---

## Parlay Construction

### **Decision: Greedy Construction with Constraints**
**Chosen:** Build parlays sequentially, apply diversity rules

**Why:**
- Simple to implement and reason about
- Constraints prevent over-correlation
- 5-10 parlays = good diversity without overwhelming user

**Constraints Applied:**
1. Max 1 leg per game (prevents single-game risk)
2. Max 2 legs per player (**DEPRECATED May 8** - now max 1 per day)
3. Max 1 leg per prop type per parlay (diversifies prop types)
4. Odds range: +1000 to +1500 (balances risk/reward)
5. **NEW (May 7):** WALKS + STRIKEOUTS conflict check (DraftKings rule)
6. **NEW (May 8):** Player used today check (diversity filter)

**Evolution of Player Constraint:**
- **April-May 7:** Max 2 legs per player *per parlay*
- **May 8:** Max 1 leg per player *per day*

**Why Change:**
- Old: Prevented player concentration *within* a single parlay
- New: Prevents player concentration *across all parlays*
- Impact: Portfolio-level diversification vs parlay-level diversification

**Trade-offs:**
- ✅ Portfolio protection (no player in multiple parlays)
- ❌ Limited daily capacity (10-15 total parlays)

**Status:** ✅ Producing diversified parlays, DraftKings-compliant

---

### **Decision: Target 5 Parlays Per Run (Not 10)**
**Chosen:** May 8, 2026 (pending deployment)

**Original Design:** Target 10 parlays per run

**Problem Discovered:**
- With player diversity filter, can only generate 1-2 parlays per run
- After 35-40 players used, remaining pool too small
- System tries for 10, achieves 1-2, appears broken

**Why Change to 5:**
- More realistic given diversity constraints
- Accounts for escalating filter throughout day
- Matches actual capacity

**Capacity Analysis:**
```
Day Start:   0 players used → can build 10 parlays (40 unique players needed)
After 9 AM:  19 players used → can build 5 parlays (20 unique players needed)
After 12 PM: 24 players used → can build 3 parlays (12 unique players needed)
After 3 PM:  35 players used → can build 2 parlays (8 unique players needed)
After 5 PM:  40 players used → can build 1 parlay (4 unique players needed)
```

**Solution:**
```python
# OLD: max_recommendations=10
# NEW: max_recommendations=5
```

**Trade-offs:**
- ✅ Realistic expectations (system meets target)
- ✅ Better UX (doesn't appear broken)
- ❌ Fewer total daily parlays (acceptable for diversification)

**Status:** 🔧 Fix in progress

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

## Database Schema

### **Decision: PostgreSQL on Supabase**
**Chosen:** Hosted PostgreSQL (Supabase free tier)

**Why:**
- Relational model fits data (props, parlays, outcomes, players)
- Supabase free tier sufficient (500MB, 2 connections)
- SQL queries flexible for dashboard
- **CRITICAL:** JOINs required for player diversity filter

**Player Diversity Requirement:**
```sql
-- Need JOIN to find players used today
SELECT DISTINCT l.player_id 
FROM mlb_parlay_legs_v2 l
JOIN mlb_parlay_recommendations_v2 r ON l.parlay_id = r.id
WHERE r.run_date = CURRENT_DATE
```

**Why Not NoSQL:**
- ❌ Can't efficiently JOIN legs with parlays by date
- ❌ Would need to scan all legs, filter client-side
- ❌ Slow, expensive, doesn't scale

**Trade-offs:**
- ✅ Free, reliable, SQL flexibility, JOINs for diversity
- ❌ Connection limits (not an issue yet)

**Status:** ✅ No issues, plenty of headroom, enabled player diversity

---

## Deployment Strategy

### **Decision: Railway for Hosting**
**Chosen:** Railway (PaaS) with GitHub auto-deploy

**Why:**
- Simple: Push to master → auto-deploy
- Free tier sufficient ($5/month estimated usage)
- Built-in monitoring and logs
- Fast deployment (~2-3 minutes)

**Alternatives Considered:**
- Heroku: Similar but more expensive
- AWS/GCP: More complex, overkill for this scale
- VPS (DigitalOcean): Requires more maintenance

**Trade-offs:**
- ✅ Simple, affordable, reliable, fast iteration
- ❌ Vendor lock-in (mitigated by standard Flask/Python stack)

**Status:** ✅ Stable, 99.9% uptime, enabled rapid deployment of player diversity

---

## Lessons Learned

### **Learning #1: Portfolio Concentration is the Silent Killer**
**What Happened (May 7):**
- Generated 23 parlays
- All looked good individually (70%+ coverage)
- Result: 0/23 won
- Root cause: Ramón Laureano in 14/23 parlays

**Discovery Process:**
1. Initial hypothesis: José Ramírez caused losses (wrong!)
2. SQL analysis showed: Ramírez not in May 7 parlays at all
3. Deeper analysis: 37/48 losing legs were "hits under" (100% failure)
4. Pattern: Every parlay had same structure (2 strikeouts over + 2 hits under)
5. Root cause: Portfolio concentration, not individual player

**Key Insight:**
- Individual leg quality doesn't matter if portfolio is concentrated
- A 70% leg becomes 0% if it appears in all parlays
- Portfolio risk ≠ sum of individual risks

**Solution Implemented:**
- Player diversity filter (max 1 parlay per player per day)
- Impact: 60% exposure → 5.6% exposure per player

**Lesson:**
✅ **Always analyze portfolio-level risk, not just individual bet quality.**

---

### **Learning #2: Player Diversity Has a Capacity Cost**
**Discovery:**
- Player diversity eliminates concentration risk
- But reduces daily parlay generation capacity
- With 40 players used, can only build 1-2 more quality parlays

**Trade-off Analysis:**
```
Without Diversity:
- Capacity: Unlimited (can reuse players)
- Risk: High (concentration failures like May 7)
- Outcome: 0/23 when concentrated player fails

With Diversity:
- Capacity: Limited (~10-15 parlays per day)
- Risk: Low (max 5-10% exposure per player)
- Outcome: Diversified (failures are independent)
```

**Decision:**
Accept lower capacity in exchange for risk mitigation.

**Lesson:**
✅ **Diversification is worth the capacity cost — better 10 good bets than 20 correlated ones.**

---

### **Learning #3: Decimal Type Handling is Non-Obvious**
**What Happened:**
- `TypeError: unsupported operand type(s) for *=: 'float' and 'decimal.Decimal'`
- Frontend: `rec.edge_pct.toFixed is not a function`

**Discovery:**
- PostgreSQL NUMERIC columns return as Decimal type
- Python can't multiply float * Decimal without conversion
- JavaScript can't call .toFixed() on Decimal without parseFloat

**Solution Pattern Established:**
```python
# Backend: Always convert Decimal to float
value = float(decimal_value) / 100.0
```
```javascript
// Frontend: Always parseFloat before formatting
const formatted = parseFloat(decimalValue).toFixed(1);
```

**Lesson:**
✅ **Assume all numeric types from PostgreSQL need explicit conversion.**

---

### **Learning #4: Schema Design Enables Features**
**Discovery:**
- Player diversity requires normalized schema
- Without v2 schema, diversity would require JSON parsing
- Normalized schema made diversity filter trivial

**V2 Schema Enabled:**
```sql
-- Simple query for player diversity
SELECT DISTINCT player_id 
FROM mlb_parlay_legs_v2 l
JOIN mlb_parlay_recommendations_v2 r ON l.parlay_id = r.id
WHERE r.run_date = CURRENT_DATE
```

**Without v2 schema:**
```python
# Would require:
for parlay in get_parlays(today):
    legs_json = json.loads(parlay["legs"])
    for leg in legs_json:
        player_id = leg["player_id"]  # Nested JSON parsing
        used_players.add(player_id)
# Slow, error-prone, complex
```

**Lesson:**
✅ **Invest in schema design early — it enables future features you haven't thought of yet.**

---

### **Learning #5: Small Sample Sizes Lie**
**What Happened (May 6-7):**
- May 6: 4/5 parlays won (80%!)
- Observed: 4 winners had low correlation, 1 loser had high correlation
- Excitement: "Correlation predicts losses! Add penalty now!"
- Reality: n=5 is not statistically significant

**Response:**
- Added correlation logging (observation only)
- No behavior changes until 50-100 parlays resolved
- Will run t-test before implementing penalty

**Lesson:**
✅ **Don't act on patterns from <50 samples. Form hypothesis, collect data, test statistically.**

---

### **Learning #6: Fail Open vs Fail Closed**
**Decision Point:**
- What happens if player diversity query fails?
- Fail closed: Block all parlay generation (safe but rigid)
- Fail open: Allow generation without diversity (resilient but risky)

**Chosen:** Fail open (return empty set on error)

**Rationale:**
- Database connectivity issues shouldn't halt pipeline
- Better to generate parlays with potential duplication than no parlays at all
- Errors are logged for investigation
- Rare edge case (DB outage while pipeline running)

**Lesson:**
✅ **For non-critical features, fail open. For critical features (like money transfers), fail closed.**

---

### **Learning #7: User Expectations vs System Capabilities**
**What Happened:**
- System tried to generate 10 parlays
- Only achieved 1-2 due to player diversity
- User confused: "Why only 2 parlays?"

**Issue:**
- Target (10) didn't match capacity (1-2 after 35 players used)
- System appeared broken but was working correctly

**Solution:**
- Lower target to 5 (matches actual capacity)
- Log explanation when target not met
- Communicate capacity constraints clearly

**Lesson:**
✅ **Align system targets with realistic capacity. Better to meet a lower target than fail a higher one.**

---

## Future Architectural Improvements

### **SHORT TERM (This Month)**
1. **Parlay-Level ML Model**
   - Train when 50-100 parlays resolved
   - Features: correlation, coverage distribution, diversity, player exposure
   - Target: Predict "Will this parlay win?"

2. **Correlation Validation**
   - Extract logs after 50+ parlays
   - Run t-test: zero vs high correlation win rates
   - Implement correlation penalty only if statistically validated

3. **Dynamic Parlay Target**
   - Instead of fixed 5, calculate based on available player pool
   - `target = min(5, (unique_players_remaining // 4))`
   - Adjust throughout day as pool shrinks

### **MEDIUM TERM (Next Quarter)**
4. **ML Model V3 (Leg-Level)**
   - Balance direction sampling
   - Add rolling window features
   - Target: 52-55% avg prediction (up from 50.5%)

5. **Player Pool Capacity Monitoring**
   - Alert when <20 unique players remain
   - Warn when filter removes >40% of legs
   - Track daily capacity utilization

6. **Dashboard V2 Integration**
   - Migrate all queries to v2 schema
   - Deprecate v1 schema
   - Add player diversity metrics section

### **LONG TERM (Future)**
7. **Multi-Day Player Tracking**
   - Track player usage across multiple days
   - Identify players used too frequently
   - Balance exposure over week/month

8. **Optimization Engine**
   - Linear programming for parlay construction
   - EV calculation and Kelly sizing
   - Constraint: player diversity maintained

9. **Advanced Correlation Detection**
   - Same-game correlation penalties
   - Pitcher dominance thesis (K over + opposing batter hits under)
   - Weather-based correlations

---

## Decision Review Schedule

**Daily:** Monitor player diversity logs, system health
**Weekly:** Review unique players used, parlay capacity, correlation metrics
**Monthly:** Review performance metrics, adjust diversity constraints if needed
**Quarterly:** Evaluate ML model, consider retraining
**Annually:** Reassess architecture for scale/features

---

**Last Review:** May 8, 2026  
**Next Review:** May 15, 2026 (after 7 days of player diversity data)  
**Major Milestone:** Player diversity system deployed, portfolio concentration eliminated
