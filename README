# MLB Parlay Agent 🔥⚾

**Intelligent MLB player prop parlay builder using statistical coverage analysis**

[![Status](https://img.shields.io/badge/status-operational-brightgreen)]()
[![Python](https://img.shields.io/badge/python-3.11+-blue)]()
[![License](https://img.shields.io/badge/license-MIT-green)]()

> **Current Status (May 18, 2026):** ✅ Operational - Generating 4-5 parlays daily at +1000-1400 odds

---

## What It Does

The MLB Parlay Agent builds **4-leg MLB player prop parlays** by:

1. **Fetching player props** from SportsGameOdds (hits, strikeouts, walks)
2. **Calculating coverage** — "How often does this player hit this line?" (direction-aware)
3. **Scoring legs** based on coverage + opponent pitcher quality + trends
4. **Building parlays** that combine high-probability legs within target odds (+1000-1400)
5. **Refreshing 3x daily** (9 AM, 12 PM, 5:30 PM ET) to capture odds movement

**Example Output:**
```
Parlay 1: +1398 | 4 legs | avg coverage 77.1%
  - Walbert Ureña (LAA) strikeouts u4.5 @ -125 | 71.4% coverage
  - Freddy Fermin (SD) hits u0.5 @ +110 | 74.3% coverage
  - Shane McClanahan (TB) strikeouts u5.5 @ -115 | 75.0% coverage
  - Bo Naylor (CLE) walks o0.5 @ +130 | 87.9% coverage
```

---

## Quick Start

### **Prerequisites**
- Python 3.11+
- PostgreSQL database (Supabase recommended)
- SportsGameOdds API key (free tier: 100K objects/month)

### **Installation**

```bash
# Clone repository
git clone https://github.com/MrGweeod/mlb-agent.git
cd mlb-agent

# Install dependencies
pip install -r requirements.txt

# Set environment variables
export DATABASE_URL="postgresql://..."
export SPORTSGAMEODDS_API_KEY="your_key_here"
export WEB_APP_PASSWORD="your_password_here"

# Initialize database tables
python -c "from src.db.setup import init_db; init_db()"

# Run pipeline manually
python main.py

# Or start web server (includes scheduler)
python src/web/server.py
```

### **Access Web UI**
```
http://localhost:8080?password=your_password_here
```

---

## Features

### **🎯 Core Pipeline**
- ✅ **Direction-Aware Coverage:** Calculates "How often player goes OVER/UNDER this line"
- ✅ **Handedness Splits:** Tracks batter performance vs RHP/LHP separately
- ✅ **Opponent Adjustments:** Elite pitchers reduce coverage, poor pitchers increase it
- ✅ **Prop Filtering:** Only 0.5 hits, 0.5 hitter SO, 3.5+ pitcher SO, 0.5 walks
- ✅ **DraftKings Rules:** No walks + strikeouts from same player
- ✅ **Correlation Limits:** Max 2 legs per game

### **📊 Web Interface**
- **Legs Tab:** Browse all scored legs, filter by stat/team, see coverage %
- **Picks Tab:** View parlay recommendations with full leg details
- **Dashboard:** System metrics, trends, performance tracking
- **Training Tab:** Data health metrics (future ML features)
- **Regenerate Button:** Manually trigger pipeline refresh

### **🔄 Automated Scheduling**
- **9 AM ET:** Resolve yesterday's outcomes, build today's parlays
- **12 PM ET:** Refresh with latest odds/lineups
- **5:30 PM ET:** Final refresh before games start

### **💾 Data Persistence**
- All scored legs logged to `mlb_scored_legs`
- Parlay recommendations saved to `mlb_parlay_recommendations_v2`
- Training data collected in `mlb_training_data` (future ML model)

---

## How It Works

### **Pipeline Flow**

```
┌─────────────────────────────────────────────────────────────┐
│ 1. Data Collection (30-60 sec)                             │
│    - Fetch today's MLB schedule (14 games)                 │
│    - Fetch player props from SportsGameOdds (~600 props)   │
│    - Fetch player game logs (last 100 games via MLB API)   │
└─────────────────────────────────────────────────────────────┘
                           ↓
┌─────────────────────────────────────────────────────────────┐
│ 2. Prop Filtering (instant)                                │
│    - Only: hits 0.5, hitter SO 0.5, pitcher SO 3.5+, walks│
│    - Remove: RBI, Total Bases, Home Runs                   │
└─────────────────────────────────────────────────────────────┘
                           ↓
┌─────────────────────────────────────────────────────────────┐
│ 3. Coverage Calculation (60-90 sec)                        │
│    - Direction-aware: "How often OVER/UNDER this line?"    │
│    - Handedness splits: vs RHP/LHP tracked separately      │
│    - Minimum: 20 games total, 10 vs handedness             │
└─────────────────────────────────────────────────────────────┘
                           ↓
┌─────────────────────────────────────────────────────────────┐
│ 4. Coverage Gate (instant)                                 │
│    - Filter: Only legs >= 65% coverage                     │
│    - Typical output: 250-350 qualifying legs               │
└─────────────────────────────────────────────────────────────┘
                           ↓
┌─────────────────────────────────────────────────────────────┐
│ 5. Lineup Consistency Filter (5-10 sec)                    │
│    - Hitters: 3+ AB in 7 of last 10 games                 │
│    - Pitchers: 4+ IP in 7 of last 10 starts               │
└─────────────────────────────────────────────────────────────┘
                           ↓
┌─────────────────────────────────────────────────────────────┐
│ 6. Opponent Enrichment (10-15 sec)                         │
│    - Fetch pitcher ranks (K%, WHIP, ERA)                   │
│    - Fetch team offensive ranks (OPS, wOBA)                │
│    - Attach opponent data to each leg                       │
└─────────────────────────────────────────────────────────────┘
                           ↓
┌─────────────────────────────────────────────────────────────┐
│ 7. Scoring (instant)                                       │
│    composite_score = coverage_pct                           │
│                    + opponent_pitcher_adjustment            │
│                    + trend_consistency_bonus                │
│                                                             │
│    - Elite pitcher (top 10%): -20 to -30%                  │
│    - Poor pitcher (bottom 10%): +20 to +30%                │
└─────────────────────────────────────────────────────────────┘
                           ↓
┌─────────────────────────────────────────────────────────────┐
│ 8. Parlay Construction (<1 sec)                            │
│    - Branch-and-bound algorithm                             │
│    - DraftKings rules enforced                              │
│    - Max 2 legs per game                                    │
│    - Target odds: +1000 to +1400                            │
│    - Output: 4-5 parlays                                    │
└─────────────────────────────────────────────────────────────┘
                           ↓
┌─────────────────────────────────────────────────────────────┐
│ 9. Persistence & Display                                    │
│    - Save legs to mlb_scored_legs                           │
│    - Save parlays to mlb_parlay_recommendations_v2          │
│    - Display in web UI                                      │
└─────────────────────────────────────────────────────────────┘
```

**Total Time:** ~2-3 minutes (morning with resolution), ~2 minutes (refresh without resolution)

---

## Key Concepts

### **Coverage (Direction-Aware)**

**Definition:** "How often does this player go OVER/UNDER this line based on last 100 games?"

**Example:**
- **Trea Turner hits over 0.5:** 63.8% (gets 1+ hits in 64 of 100 games)
- **Trea Turner hits under 0.5:** 36.2% (gets 0 hits in 36 of 100 games)
- **Validation:** over + under ≈ 100% ✅

**Why Direction Matters:**
- Non-directional coverage ("how often 1+ hits") gives same % for both over and under → WRONG
- Direction-aware calculates separately for each side → CORRECT

---

### **Opponent Pitcher Adjustment**

**Rationale:** A hitter's coverage vs an elite pitcher (Gerrit Cole) should be lower than vs a poor pitcher (5+ ERA).

**Implementation:**
```python
if opponent_pitcher_rank_pct < 10:  # Elite (top 10%)
    adjustment = -25
elif opponent_pitcher_rank_pct < 30:  # Above average
    adjustment = -15
elif opponent_pitcher_rank_pct < 70:  # Average
    adjustment = 0
else:  # Below average / poor
    adjustment = +15 to +25
```

**Example:**
- Julio Rodríguez hits over 0.5 vs Gerrit Cole: 68% → 68% - 25% = **43%** (adjusted)
- Julio Rodríguez hits over 0.5 vs poor pitcher: 68% → 68% + 20% = **88%** (adjusted)

---

### **Composite Score**

**Formula:**
```
composite_score = coverage_pct + opponent_adjustment + trend_bonus
```

**Example Leg:**
- **Player:** Freddy Fermin
- **Prop:** hits under 0.5 @ +110
- **Coverage:** 74.3% (gets 0 hits in 74 of 100 games)
- **Opponent:** Facing average pitcher → adjustment = 0%
- **Trend:** Consistent 0-hit games recently → bonus = +3%
- **Composite Score:** 74.3 + 0 + 3 = **77.3%**

---

### **Parlay Construction**

**Branch-and-Bound Algorithm:**
1. Sort all legs by composite_score descending
2. Start with highest-scoring leg as anchor
3. Greedily add legs that:
   - Don't violate DraftKings rules (walks + SO same player)
   - Don't exceed correlation limits (max 2 legs per game)
   - Keep parlay odds in +1000-1400 range
4. Once 4 legs assembled, save parlay and continue
5. Generate top 5 distinct parlays

**Why This Works:**
- Fast: Completes in <1 second for 300 legs
- Deterministic: Same inputs → same outputs
- Respects constraints: DK rules, correlation limits, odds range

**Known Issue:** High overlap (same 3 legs in all parlays)
- **Why:** Algorithm anchors on best legs naturally
- **Fix:** Add diversity constraint in Phase 1 if needed

---

## Prop Type Filtering

### **Included Props**

| Stat | Line(s) | Rationale |
|------|---------|-----------|
| Hits | 0.5 only | Clean yes/no, reasonable odds (-120 to +120) |
| Hitter Strikeouts | 0.5 only | Most hitters strike out 0-1 times per game |
| Pitcher Strikeouts | 3.5+ | Starters face 20-30 batters, 3.5 is median |
| Walks | 0.5 | Less common but clean outcome |

### **Excluded Props**

| Stat | Why Excluded |
|------|--------------|
| Hits 1.5+ | Heavily juiced unders (-300+) or risky overs |
| Hitter SO 1.5+ | Betting hitter strikes out 2+ times - too rare |
| RBI | Too volatile, dependent on team offense |
| Total Bases | Complex, dependent on hit type (single vs HR) |
| Home Runs | Extremely low probability, not suitable for parlays |

---

## Database Schema

### **mlb_scored_legs**
All legs that passed coverage threshold (>= 65%).

```sql
CREATE TABLE mlb_scored_legs (
    id SERIAL PRIMARY KEY,
    run_date TEXT,
    player_name TEXT,
    stat TEXT,
    line REAL,
    direction TEXT,  -- 'over' or 'under'
    odds TEXT,
    coverage_pct REAL,
    composite_score REAL,
    result TEXT,  -- 'hit', 'miss', NULL (pending)
    -- ... additional metadata
);
```

### **mlb_parlay_recommendations_v2**
Daily parlay recommendations displayed in web UI.

```sql
CREATE TABLE mlb_parlay_recommendations_v2 (
    id SERIAL PRIMARY KEY,
    recommendation_date DATE,
    run_date TEXT,
    rank INTEGER,
    legs JSONB,  -- Array of leg objects
    combined_odds INTEGER,  -- American odds (+1398)
    win_probability REAL,  -- 0.0-1.0
    edge_pct REAL,
    result TEXT,  -- 'won', 'lost', NULL (pending)
    -- ... additional metadata
);
```

### **mlb_training_data**
All legs with full metadata for future ML model training.

```sql
CREATE TABLE mlb_training_data (
    id SERIAL PRIMARY KEY,
    prediction_date DATE,
    player_name TEXT,
    stat TEXT,
    line REAL,
    direction TEXT,
    coverage_pct REAL,
    outcome TEXT,  -- 'hit', 'miss', NULL (pending)
    -- ... extensive metadata for ML features
);
```

---

## API Usage

### **SportsGameOdds**
- **Endpoint:** `/mlb/odds/player-props`
- **Rate Limit:** 100K objects/month (free tier)
- **Current Usage:** ~54K/month (600 props × 3 runs × 30 days)
- **Cost:** $0/month ✅

### **MLB-StatsAPI**
- **Purpose:** Game logs, transactions, schedule
- **Rate Limit:** Reasonable (no strict limit)
- **Cost:** $0/month (no API key required) ✅

### **Anthropic Claude API**
- **Status:** ❌ Removed May 18, 2026
- **Previous Usage:** Parlay analysis after generation
- **Reason for Removal:** Cost optimization, analysis disconnected from scoring
- **Savings:** ~$1/month

---

## Configuration

### **Environment Variables**

```bash
# Required
DATABASE_URL="postgresql://user:pass@host:5432/db"
SPORTSGAMEODDS_API_KEY="your_key_here"

# Optional
WEB_APP_PASSWORD="your_password"  # Default: ""
PORT="8080"  # Default: 8080
ODDS_API_KEY=""  # Fallback odds provider (not used currently)
DISCORD_BOT_TOKEN=""  # Future feature
```

### **Pipeline Configuration (main.py)**

```python
# Coverage threshold
MIN_COVERAGE_PCT = 65.0  # Only legs >= 65% coverage

# Consistency thresholds
MIN_HITTER_CONSISTENCY_PCT = 70.0  # 7 of 10 games with 3+ AB
MIN_PITCHER_CONSISTENCY_PCT = 70.0  # 7 of 10 starts with 4+ IP

# Parlay construction
TARGET_ODDS_MIN = 1000  # +1000
TARGET_ODDS_MAX = 1400  # +1400
LEGS_PER_PARLAY = 4
MAX_LEGS_PER_GAME = 2

# Strikeout filters
MIN_PITCHER_SO_LINE = 3.5  # Only pitcher SO >= 3.5
```

---

## Deployment

### **Railway (Current)**

**Setup:**
1. Connect GitHub repo to Railway
2. Set environment variables in Railway dashboard
3. Railway auto-deploys on push to `master`
4. Scheduler runs 3x daily automatically

**Cost:** $5/month (Hobby plan)

**URL:** https://mlb-agent.up.railway.app

---

### **Local Development**

```bash
# Run pipeline once
python main.py

# Run web server with scheduler
python src/web/server.py

# Access UI
open http://localhost:8080?password=your_password
```

---

## Monitoring

### **Daily Checklist**

**Morning (After 9 AM run):**
1. Check Railway logs: `railway logs --follow`
2. Verify parlays built: Should see "Built 4-5 parlay(s)"
3. Check web UI: https://mlb-agent.up.railway.app?password=...

**Evening (After games complete):**
- No action needed - resolution happens next morning

**Next Morning:**
1. Check resolution: How many legs/parlays hit?
2. Track hit rates vs predicted coverage

### **Key Metrics**

**System Health:**
- ✅ Parlays built per run: 4-5 expected
- ✅ Qualified legs per day: 250-350 expected
- ✅ Pipeline execution time: 2-3 minutes expected
- ⚠️ 0 parlays built: Investigate immediately

**Performance:**
- 🎯 Leg hit rate: Should match coverage % (±5%)
- 🎯 4-leg parlay win rate: 15-25% target
- 🎯 Core leg hit rate: Monitor top 3-5 most-used legs

### **Validation Queries**

**Check today's parlays:**
```sql
SELECT * FROM mlb_parlay_recommendations_v2 
WHERE run_date = CURRENT_DATE 
ORDER BY rank;
```

**Check today's legs:**
```sql
SELECT player_name, stat, direction, line, coverage_pct, composite_score
FROM mlb_scored_legs
WHERE run_date = CURRENT_DATE::text
ORDER BY composite_score DESC
LIMIT 20;
```

**Check prop type distribution:**
```sql
SELECT stat, direction, COUNT(*) as count
FROM mlb_scored_legs
WHERE run_date = CURRENT_DATE::text
GROUP BY stat, direction
ORDER BY stat, direction;
-- Expected: Only hits 0.5, SO (0.5/3.5+), walks 0.5
```

---

## Known Issues

### **⚠️ High Overlap (Same 3 Legs in All Parlays)**

**Current State:** Same core legs appear in all 5 parlays (e.g., Ureña, Fermin, McClanahan)

**Why It Happens:** Branch-and-bound naturally selects highest-scoring legs as anchors.

**Is It Bad?** 
- ✅ If core legs are truly the best, this might be optimal strategy
- ❌ If any core leg misses, all 5 parlays lose

**Resolution:** Monitor May 19-23. If core legs hit >70%, keep strategy. If <60%, add diversity constraint.

---

### **⚠️ Negative EV Legs**

**Current State:** Some legs have high coverage but negative EV (e.g., -9.7% for Ureña SO u4.5)

**Why It Happens:** System optimizes for "most likely to hit" (coverage), not "best value" (EV).

**Is It Bad?** No - this is working as designed. Parlays multiply probabilities, so hit rate > value.

**Resolution:** Track actual win rates vs predicted. If system is profitable despite negative EV, continue.

---

### **⚠️ Same-Game Correlation**

**Current State:** Some parlays have 2 legs from same game (e.g., both pitchers from LAA vs ATH)

**Why It Happens:** Max 2 legs per game rule allows this. Opposing pitchers both betting unders is reasonable (defensive duel thesis).

**Is It Bad?** Unclear - need to quantify actual correlation impact.

**Resolution:** Track same-game parlay outcomes. If significantly underperforming, add correlation penalties.

---

## Roadmap

### **Phase 1: Diversity Improvements (4-6 hours)**
- Add "max appearances per player" constraint (e.g., max 3 parlays per player)
- Implement parlay diversity score to avoid near-identical parlays
- **Trigger:** If core legs hit <60% over May 19-23

### **Phase 2: Correlation Handling (3-4 hours)**
- Add same-game pitcher correlation penalty (-5 to -10 points)
- Weight EV as tiebreaker when coverage is similar
- **Trigger:** After quantifying same-game correlation impact

### **Phase 3: Learning Loop (1-2 days)**
- After 500+ resolved legs: regression analysis on coverage accuracy
- Recalibrate coverage calculation weights
- Implement dynamic threshold adjustment
- **Trigger:** After 50+ days of operation

### **Future Features**
- Discord bot for push notifications
- Mobile app (if user base grows)
- Advanced analytics dashboard
- Backtesting framework (if historical odds data available)

---

## Contributing

This is a personal project, but contributions are welcome!

**Areas for Contribution:**
- Improved correlation detection
- Alternative scoring algorithms
- ML model for leg predictions
- Better web UI design
- Backtesting framework

**Before Contributing:**
1. Read `ARCHITECTURE_DECISIONS.md` to understand design choices
2. Check `SESSION_HANDOFF.md` for current status
3. Open an issue to discuss your idea
4. Submit a PR with clear description and tests

---

## FAQ

### **Q: Why only 0.5 hit lines?**
**A:** Lines above 0.5 (1.5, 2.5) are either heavily juiced unders (-300+) or risky overs. 0.5 is a clean yes/no outcome with reasonable odds.

### **Q: Why not use machine learning?**
**A:** Simple additive scorer working well so far. Will revisit after 500+ resolved legs for reliable training data.

### **Q: Why 4 legs instead of 3 or 5?**
**A:** 3 legs don't reach +1000 odds. 5 legs push parlay win rate too low (<10%). 4 legs is the sweet spot.

### **Q: Why remove Claude analysis?**
**A:** Cost optimization ($1/month) + analysis was disconnected from scoring logic. Scoring breakdown more useful than LLM text.

### **Q: How accurate is coverage?**
**A:** Validated May 14 with direction-aware fix. Expecting 65-70% actual hit rate for 65% coverage legs (±5% is acceptable).

### **Q: What's the expected ROI?**
**A:** Unknown - system is optimized for hit probability, not ROI. Monitoring will determine profitability.

### **Q: Can I use this for betting?**
**A:** This is for educational/entertainment purposes. Bet responsibly and within your means. Not financial advice.

---

## License

MIT License - see LICENSE file for details.

---

## Acknowledgments

- **MLB-StatsAPI:** Free game logs and stats
- **SportsGameOdds:** Comprehensive player props data
- **Railway:** Simple deployment platform
- **Supabase:** Reliable PostgreSQL hosting

---

## Contact

- **GitHub Issues:** For bugs, feature requests, questions
- **Email:** [Your email if you want to include]

---

**Last Updated:** May 18, 2026  
**System Status:** ✅ Operational  
**Current Version:** 1.0.0 (Post-Surgical Fixes)  
**Next Milestone:** May 23, 2026 (5-day monitoring review)
