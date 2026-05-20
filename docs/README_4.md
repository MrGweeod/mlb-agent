# MLB Parlay Agent 🤖⚾

**Last Updated:** May 19, 2026  
**Status:** ✅ Operational - Generating 5 Parlays Daily with Player Diversity

An intelligent MLB parlay recommendation system that analyzes player performance data, calculates coverage percentages, and builds optimized 4-leg parlays with +900 to +1500 combined odds.

---

## 🎯 What It Does

1. **Fetches MLB Props** — Pulls 2000+ player props daily from SportsGameOdds API
2. **Filters Strategically** — Only keeps hits 0.5, hitter SO 0.5, pitcher SO 3.5+, walks 0.5, totalBases 1.5
3. **Calculates Coverage** — Direction-aware analysis: "How often does this player go OVER/UNDER this line?"
4. **Enriches Context** — Adds opponent pitcher stats, handedness matchups, lineup consistency
5. **Scores Legs** — Combines coverage + opponent adjustments into composite score
6. **Builds Parlays** — Branch-and-bound search for optimal 4-leg combinations with player diversity
7. **Logs Everything** — Saves all legs and parlays to Supabase for tracking and analysis
8. **Resolves Outcomes** — Updates legs and parlays with win/loss results each morning

---

## 🚀 Key Features

### **Player Diversity Constraint (NEW - May 19)**
- **Max 1 appearance per player per generation batch**
- Eliminates catastrophic single-player wipeout risk (previously 65% of batches)
- Forces exploration of deeper leg pool
- Diversity resets between generation runs (9 AM, 12 PM, 5:30 PM)

**Example:**
```
Before: Shane McClanahan in all 25 parlays → all lost when he lost
After:  20 unique players across 5 parlays → no single-player wipeouts
```

### **Total Bases Props (NEW - May 19)**
- Added `totalBases 1.5` to expand leg pool
- Over 1.5 = player gets 2+ total bases (double, HR, or 2 singles)
- Under 1.5 = player gets 0-1 total bases
- +33 legs per day, bringing total from ~70 to ~105

### **Surgical Prop Filtering**
- ✅ Hits: ONLY 0.5 line
- ✅ Hitter Strikeouts: ONLY 0.5 line
- ✅ Pitcher Strikeouts: Minimum 3.5 line
- ✅ Walks: 0.5 line
- ✅ Total Bases: ONLY 1.5 line
- ❌ Blocked: RBI, Home Runs, Stolen Bases

### **Direction-Aware Coverage**
- Not "how often does player get hits" (ambiguous)
- But "how often does player get OVER 0.5 hits" (precise)
- Handedness splits: Batter vs RHP/LHP tracked separately
- Uses 10-game rolling window, last 50 games of data

### **Intelligent Parlay Construction**
- 4 legs per parlay (fixed)
- Combined odds: +900 to +1500
- Max 2 legs per game (correlation limit)
- **Max 1 leg per player per batch** (NEW - diversity constraint)
- 5 parlays per generation run
- Branch-and-bound search over all eligible legs

### **Daily Pipeline (3x per day)**
- **9 AM ET:** Resolution + fetch/score/build
- **12 PM ET:** Fresh props refresh (diversity resets)
- **5:30 PM ET:** Final refresh before games (diversity resets)
- **Manual:** Regenerate button in web UI

---

## 📊 Current Performance

### **Latest Run (May 19, 2026, 9:45 PM ET)**

**Parlay Generation:**
```
✅ Built 5 parlays (20 unique players used)

Parlay 1: +1344 | 4 legs | avg coverage 76.3%
Parlay 2: +1030 | 4 legs | avg coverage 75.0%
Parlay 3: +1205 | 4 legs | avg coverage 73.8%
Parlay 4: +1156 | 4 legs | avg coverage 72.5%
Parlay 5: +949  | 4 legs | avg coverage 71.2%
```

**Leg Pool Quality:**
```
Total scored legs: 105
  - Hits: 40 legs
  - Strikeouts: 30 legs
  - Total Bases: 33 legs ✅ NEW
  - Walks: 2 legs

Eligible legs (>= 65% coverage): 74
Odds distribution: 45 overs + 29 unders
```

**Player Diversity:**
- ✅ 20 unique players across 5 parlays
- ✅ Zero players appearing in multiple parlays per batch
- ✅ Eliminates 65% wipeout rate from May 18

---

## 🏗️ Architecture

### **Tech Stack**
- **Backend:** Python 3.12 + Flask
- **Database:** Supabase PostgreSQL (4 tables)
- **APIs:** SportsGameOdds (props), MLB-StatsAPI (game logs)
- **Deployment:** Railway (auto-deploy from `master`)
- **Scheduler:** APScheduler (3x daily runs)
- **Frontend:** HTML/CSS/JS (tabs interface)

### **Data Flow**

```
┌─────────────────────────────────────────────────────────────┐
│  1. Fetch Props (SportsGameOdds)                            │
│     → ~2,000 player props from today's MLB slate            │
└─────────────────┬───────────────────────────────────────────┘
                  │
┌─────────────────▼───────────────────────────────────────────┐
│  2. Filter Props                                             │
│     → Only: hits 0.5, SO (0.5/3.5+), walks 0.5, TB 1.5     │
│     → Result: ~1,700 props                                  │
└─────────────────┬───────────────────────────────────────────┘
                  │
┌─────────────────▼───────────────────────────────────────────┐
│  3. Calculate Coverage (direction-aware)                     │
│     → "How often does player go OVER this line?"            │
│     → Handedness splits, lineup consistency                 │
│     → Result: ~105 scored legs                              │
└─────────────────┬───────────────────────────────────────────┘
                  │
┌─────────────────▼───────────────────────────────────────────┐
│  4. Coverage Gate (>= 65%)                                   │
│     → Result: ~74 eligible legs                             │
└─────────────────┬───────────────────────────────────────────┘
                  │
┌─────────────────▼───────────────────────────────────────────┐
│  5. Enrich with Context                                      │
│     → Opponent pitcher stats                                │
│     → Handedness matchups                                   │
└─────────────────┬───────────────────────────────────────────┘
                  │
┌─────────────────▼───────────────────────────────────────────┐
│  6. Score Legs                                               │
│     → Coverage + opponent adjustments                       │
│     → Composite score (0-100)                               │
└─────────────────┬───────────────────────────────────────────┘
                  │
┌─────────────────▼───────────────────────────────────────────┐
│  7. Build 5 Parlays (Branch-and-Bound + Player Diversity)   │
│     → 4 legs each                                           │
│     → +900 to +1500 combined odds                           │
│     → Max 1 player appearance per batch                     │
│     → Max 2 legs per game                                   │
│     → Result: 5 parlays, 20 unique players                  │
└─────────────────┬───────────────────────────────────────────┘
                  │
┌─────────────────▼───────────────────────────────────────────┐
│  8. Save to Database                                         │
│     → mlb_scored_legs (all qualified legs)                  │
│     → mlb_parlay_recommendations_v2 (5 parlays)             │
│     → mlb_parlay_legs_v2 (20 individual legs)               │
│     → mlb_training_data (for future ML)                     │
└─────────────────────────────────────────────────────────────┘
```

---

## 🗄️ Database Schema

### **mlb_scored_legs**
Stores all qualified legs (>= 65% coverage) with scoring details.

| Column | Type | Description |
|--------|------|-------------|
| id | bigint | Primary key |
| run_date | text | Date props were fetched (YYYY-MM-DD) |
| player_name | text | Player full name |
| stat | text | hits, strikeouts, walks, totalBases |
| line | numeric | Prop line (0.5, 1.5, 3.5, etc.) |
| direction | text | 'over' or 'under' |
| odds | int | American odds (-150, +120, etc.) |
| coverage_pct | numeric | How often player clears line (0-100) |
| composite_score | numeric | Final score including adjustments |
| result | text | 'hit', 'miss', or null (pending) |

### **mlb_parlay_recommendations_v2**
Stores daily parlay recommendations.

| Column | Type | Description |
|--------|------|-------------|
| id | bigint | Primary key |
| recommendation_date | text | Date (YYYY-MM-DD) |
| run_date | text | Date props were fetched |
| batch_id | text | Unique batch identifier |
| rank | int | Parlay rank (1-5) |
| legs | jsonb | Array of leg objects |
| total_odds | int | Combined American odds |
| outcome | text | 'won', 'lost', or null |

### **mlb_parlay_legs_v2**
Stores individual legs per parlay (for player diversity validation).

| Column | Type | Description |
|--------|------|-------------|
| id | bigint | Primary key |
| parlay_id | bigint | FK to mlb_parlay_recommendations_v2 |
| player_name | text | Player full name |
| stat | text | hits, strikeouts, walks, totalBases |
| line | numeric | Prop line |
| direction | text | 'over' or 'under' |
| odds | int | American odds |
| outcome | text | 'hit', 'miss', or null |

### **mlb_training_data**
Stores all scored legs for future ML model training.

| Column | Type | Description |
|--------|------|-------------|
| id | bigint | Primary key |
| run_date | text | Date (YYYY-MM-DD) |
| player_name | text | Player full name |
| stat | text | Prop type |
| line | numeric | Prop line |
| direction | text | 'over' or 'under' |
| odds | int | American odds |
| outcome | text | 'hit', 'miss', or null |

---

## 🚦 System Health Indicators

### **Green Lights (System Healthy)**
- ✅ 4-5 parlays built per run
- ✅ All parlays within +900-1500 odds
- ✅ 100-110 scored legs per day
- ✅ 70-80 eligible legs per day
- ✅ Only allowed prop types in pool (hits 0.5, SO, walks 0.5, TB 1.5)
- ✅ No player appears 2+ times per batch
- ✅ Pipeline completing in <5 minutes
- ✅ Database writes succeeding

### **Yellow Flags (Monitor Closely)**
- ⚠️ Parlay count drops to 2-3
- ⚠️ Leg pool < 80 or > 120
- ⚠️ Pipeline execution > 5 minutes
- ⚠️ Coverage accuracy drifting from historical baseline

### **Red Flags (Immediate Action Required)**
- 🔴 0-1 parlays built multiple days in row
- 🔴 Player appears 3+ times in batch (diversity broken)
- 🔴 Unwanted prop types in pool (RBI, HR appearing)
- 🔴 Pipeline crashes or timeouts
- 🔴 Parlay win rate < 5% after 20+ samples

---

## 📈 Monitoring & Validation

### **Daily Validation Query**
Check player diversity constraint (should return 0 rows):

```sql
WITH player_counts AS (
  SELECT 
    p.batch_id,
    l.player_name,
    COUNT(DISTINCT p.id) as appearances
  FROM mlb_parlay_recommendations_v2 p
  JOIN mlb_parlay_legs_v2 l ON l.parlay_id = p.id
  WHERE p.run_date = CURRENT_DATE
  GROUP BY p.batch_id, l.player_name
)
SELECT * FROM player_counts WHERE appearances > 1;
```

### **Check Today's Parlays**
```sql
SELECT 
  p.rank,
  p.total_odds,
  p.outcome,
  l.player_name,
  l.stat,
  l.direction,
  l.line,
  l.odds
FROM mlb_parlay_recommendations_v2 p
JOIN mlb_parlay_legs_v2 l ON l.parlay_id = p.id
WHERE p.run_date = CURRENT_DATE
ORDER BY p.rank, l.id;
```

### **Prop Type Distribution**
```sql
SELECT 
  stat,
  direction,
  COUNT(*) as count
FROM mlb_scored_legs
WHERE run_date = CURRENT_DATE::text
GROUP BY stat, direction
ORDER BY stat, direction;
```

---

## 🛠️ Local Development

### **Prerequisites**
- Python 3.12+
- PostgreSQL access (Supabase)
- API keys: SportsGameOdds

### **Setup**

1. **Clone the repo:**
```bash
git clone https://github.com/MrGweeod/mlb-agent.git
cd mlb-agent
```

2. **Create virtual environment:**
```bash
python -m venv venv
source venv/bin/activate  # On Windows: venv\Scripts\activate
```

3. **Install dependencies:**
```bash
pip install -r requirements.txt
```

4. **Configure environment variables:**
```bash
cp .env.example .env
# Edit .env with your credentials:
# - DATABASE_URL (Supabase connection string)
# - SGO_API_KEY (SportsGameOdds API key)
```

5. **Run the pipeline:**
```bash
python main.py
```

6. **Start web server:**
```bash
python main.py
# Visit: http://localhost:10000
```

---

## 🚀 Deployment (Railway)

### **Automatic Deployment**
- Push to `master` → Railway auto-deploys
- Scheduler automatically starts: 9 AM, 12 PM, 5:30 PM ET
- Web UI available at: https://mlb-agent.up.railway.app

### **Manual Commands**

**View logs:**
```bash
railway logs --follow
```

**Force regenerate:**
```bash
curl -X POST https://mlb-agent.up.railway.app/api/refresh \
  -H "Authorization: Bearer MLBparlays"
```

**Check health:**
```bash
curl https://mlb-agent.up.railway.app/health
```

---

## 🎛️ Configuration

### **Key Parameters** (`src/engine/parlay_builder.py`)

```python
# Parlay Construction
MIN_PARLAY_ODDS = 900      # Minimum combined odds
MAX_PARLAY_ODDS = 1500     # Maximum combined odds
PARLAY_SIZE = 4            # Legs per parlay
NUM_PARLAYS = 5            # Parlays per generation

# Correlation Limits
MAX_LEGS_PER_GAME = 2      # Prevent over-concentration
MAX_PLAYER_APPEARANCES = 1  # Player diversity (per batch)

# Search Parameters
MAX_CANDIDATES = 15        # Early exit threshold for B&B
```

### **Coverage Thresholds** (`main.py`)

```python
MIN_COVERAGE_PCT = 65.0    # Minimum to qualify as "eligible"
MIN_GAMES_PLAYED = 20      # Minimum career games
MIN_HANDEDNESS_GAMES = 10  # Minimum for split reliability
```

### **Allowed Props** (`main.py`)

```python
ALLOWED_STATS = {"hits", "strikeouts", "walks", "totalBases"}

# Line filters:
# - hits: only 0.5
# - totalBases: only 1.5
# - hitter SO: only 0.5
# - pitcher SO: 3.5+ minimum
# - walks: 0.5
```

---

## 📁 Project Structure

```
mlb-agent/
├── main.py                 # Entry point, pipeline orchestration
├── requirements.txt        # Python dependencies
├── Procfile               # Railway deployment config
├── .env.example           # Environment variable template
├── src/
│   ├── data/
│   │   ├── fetchers.py    # API calls (SGO, MLB-StatsAPI)
│   │   ├── coverage.py    # Direction-aware coverage calculation
│   │   └── resolver.py    # Outcome resolution (9 AM)
│   ├── engine/
│   │   ├── parlay_builder.py  # Branch-and-bound + diversity
│   │   └── scorer.py          # Leg scoring (coverage + adjustments)
│   ├── db/
│   │   └── supabase_client.py # Database operations
│   └── utils/
│       ├── helpers.py     # Odds conversion, date handling
│       └── logger.py      # Logging configuration
├── static/
│   ├── index.html         # Web UI (tabs interface)
│   ├── styles.css         # Styling
│   └── script.js          # Frontend logic
└── docs/
    ├── SESSION_HANDOFF.md         # Daily handoff notes
    ├── BUILD_STATUS.md            # Component status
    ├── ARCHITECTURE_DECISIONS.md  # Design decisions
    └── TROUBLESHOOTING.md         # Common issues
```

---

## 🔍 Key Algorithms

### **1. Direction-Aware Coverage**

Traditional (wrong):
```python
# "How often does player get 1+ hits?"
hits_games = games_with_hits >= 1
coverage = hits_games / total_games
```

Correct (direction-aware):
```python
# "How often does player go OVER 0.5 hits?"
over_games = games_with_hits > 0.5  # Same as >= 1
coverage_over = over_games / total_games

# "How often does player go UNDER 0.5 hits?"
under_games = games_with_hits < 0.5  # Same as 0 hits
coverage_under = under_games / total_games

# Validation: over + under ≈ 100%
```

### **2. Branch-and-Bound with Player Diversity**

```python
def build_parlays_with_diversity(legs, num_parlays=5):
    used_players = set()
    parlays = []
    
    for rank in range(1, num_parlays + 1):
        # Filter: exclude already-used players
        available = [
            leg for leg in legs 
            if leg['player_name'] not in used_players
        ]
        
        # Run B&B on filtered pool
        parlay = branch_and_bound(
            available,
            target_min=900,
            target_max=1500,
            size=4
        )
        
        if parlay:
            parlays.append(parlay)
            
            # Add players to exclusion set
            for leg in parlay['legs']:
                used_players.add(leg['player_name'])
    
    return parlays
```

### **3. Composite Scoring**

```python
def score_leg(leg, opponent_stats):
    base_score = leg['coverage_pct']  # 0-100
    
    # Opponent pitcher adjustment
    if is_hitter_prop(leg):
        opp_era = opponent_stats['era']
        
        if opp_era > 5.0:
            adjustment = +5  # Advantage vs bad pitcher
        elif opp_era < 3.0:
            adjustment = -5  # Disadvantage vs ace
        else:
            adjustment = 0
    else:
        adjustment = 0
    
    composite_score = base_score + adjustment
    return min(max(composite_score, 0), 100)  # Clamp 0-100
```

---

## 🧪 Testing

### **Unit Tests**
```bash
pytest tests/
```

### **Coverage Validation**
```python
# Check direction symmetry
over_pct + under_pct ≈ 100%

# Example:
# Player A hits over 0.5: 68%
# Player A hits under 0.5: 32%
# Total: 100% ✅
```

### **Player Diversity Validation**
```sql
-- Should return 0 rows
SELECT batch_id, player_name, COUNT(*) 
FROM mlb_parlay_legs_v2 
WHERE DATE(created_at) = CURRENT_DATE
GROUP BY batch_id, player_name 
HAVING COUNT(*) > 1;
```

---

## 📚 Additional Documentation

- [SESSION_HANDOFF.md](SESSION_HANDOFF.md) — Daily handoff notes
- [BUILD_STATUS.md](BUILD_STATUS.md) — Component health status
- [ARCHITECTURE_DECISIONS.md](ARCHITECTURE_DECISIONS.md) — Design rationale
- [TROUBLESHOOTING.md](TROUBLESHOOTING.md) — Common issues & fixes

---

## 📊 Expected Performance

### **Leg-Level (Individual Props)**
- Coverage accuracy: 65-70% (target)
- Qualified legs per day: 100-110
- Eligible legs per day: 70-80

### **Parlay-Level (4-leg combinations)**
- Win rate: 15-25% (target for +900-1500 range)
- Parlays built per run: 4-5
- Unique players per batch: 16-20

### **System-Level**
- Pipeline execution: <5 minutes
- Wipeout events: <10% (down from 65% pre-diversity)
- Days with 1+ winning parlay: 50-70% (target)

---

## 🛡️ Safety Features

### **Player Diversity Constraint**
- Max 1 appearance per player per batch
- Prevents single-player catastrophic failures
- Resets between generation runs

### **Correlation Limits**
- Max 2 legs per game (prevents over-concentration)
- No DraftKings walks + SO from same player
- Handedness-aware coverage (splits tracked)

### **Quality Gates**
- Coverage minimum: 65%
- Lineup consistency: 3+ AB in 7 of 10 games
- Strikeout filters: Hitter 0.5, pitcher 3.5+ only
- Line filters: Only 0.5 hits, 1.5 TB, etc.

---

## 🤝 Contributing

This is a personal project, but suggestions are welcome!

1. Fork the repo
2. Create a feature branch
3. Make your changes
4. Submit a pull request

**Key areas for contribution:**
- Improved coverage calculation methods
- Additional correlation detection
- Better opponent pitcher adjustments
- ML model integration

---

## 📝 License

MIT License - See [LICENSE](LICENSE) file for details

---

## 🙏 Credits

**Data Sources:**
- [SportsGameOdds API](https://sportsgameodds.com) - Player props and odds
- [MLB-StatsAPI](https://github.com/toddrob99/MLB-StatsAPI) - Game logs and player stats

**Inspiration:**
- Built to solve the "correlation problem" in parlay betting
- Player diversity constraint validated with 65% wipeout rate data

---

## 📞 Contact

**Issues:** https://github.com/MrGweeod/mlb-agent/issues  
**Discussions:** https://github.com/MrGweeod/mlb-agent/discussions

---

**Last Updated:** May 19, 2026  
**Version:** 2.0 (Player Diversity + Total Bases)  
**Status:** ✅ Operational  
**Next Review:** May 25, 2026
