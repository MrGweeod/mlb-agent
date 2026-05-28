# MLB Parlay Agent 🤖⚾

**Last Updated:** May 28, 2026
**Status:** ✅ Operational — Anchor/Swing Structure + Signal 4 Live
**Win Rate:** ~11% parlay win rate (target 18–22%, anchor/swing + consistency signal under evaluation)

An intelligent MLB parlay recommendation system that analyzes player performance data, calculates direction-aware coverage percentages, and builds optimized 5-leg anchor/swing parlays with +900 to +1100 combined odds. A shadow enriched pipeline runs alongside production to evaluate 4 additional scoring signals before promotion.

---

## 🎯 What It Does

1. **Fetches MLB Props** — Pulls 2000+ player props daily from SportsGameOdds API
2. **Gate 1: `coverage_overall` Floor** — Hard 65% floor on season coverage before any adjustments (raised to 75% for anchor pool)
3. **Gate 2: Prop-Specific Floors** — 80% floor for TB under 1.5, 72% floor for SO over 5.5
4. **Calculates Coverage** — Direction-aware: "How often does this player go OVER/UNDER this line?"
5. **Scores with Consistency Signal** — Coverage + consistency gap penalty/boost + contextual adjustments
6. **Shadow Scores** — Runs enriched scorer in parallel with 4 signals
7. **Blocks Toxic Props** — Removes categories with poor in-parlay win rates
8. **Caps Extreme Juice** — Blocks props with odds worse than -300 from parlays
9. **Builds Anchor/Swing Parlays** — 3 high-confidence anchors + 2 odds-boosting swings = 5-leg parlay
10. **Logs Everything** — Production and shadow data to Supabase for tracking and comparison
11. **Resolves Outcomes** — Updates legs and parlays with win/loss results each morning

---

## 🚀 Key Features

### **Anchor/Swing Parlay Structure (NEW — May 28)**

Replaced the single-pool 4-leg system with a two-pool 5-leg structure that separates high-confidence foundation legs from odds-boosting swing legs.

| Pool | Coverage Floor | Odds Range | Role | Count |
|------|---------------|------------|------|-------|
| **Anchor** | 75% `coverage_overall` | -300 to -150 | High-probability foundation | 3 |
| **Swing** | 55% `coverage_overall` | -150 to +150 | Payout multipliers | 2 |

**Target odds:** +900 to +1100 combined

**Why two pools?** A single pool forces a tradeoff: use high-juice legs (great win rate, kills odds) or plus-money legs (hit the odds target, worse win rate). Anchor/swing separates the two concerns — anchors maximize hit probability, swings add payout without requiring marginal quality.

---

### **Consistency Signal (NEW — May 28)**

Penalizes cold-streak legs and rewards hot streaks based on the gap between season coverage and recent-10-game coverage.

```python
gap = coverage_overall - coverage_recent_10

if gap >= 20:    adj = -6   # severe cold streak
elif gap >= 12:  adj = -4   # moderate cold streak
elif gap >= 6:   adj = -2   # mild cooling off
elif gap <= -10: adj = +2   # meaningfully hot
elif gap <= -5:  adj = +1   # slightly warm
else:            adj =  0   # neutral
```

Live in both production (`simple_scorer.py`) and shadow (`enriched_scorer.py`).

---

### **Two-Gate Coverage System**

**Gate 1 — `coverage_overall` floor (65%):**
All legs must have season-long `coverage_overall` of at least 65%, checked before any handedness splits or adjustments. Prevents adjustments from rescuing marginal players.

**Gate 2 — Prop-specific floors:**
- `totalBases under 1.5` requires **80%** (7-day in-parlay rate was 50.4%)
- `strikeouts over 5.5` requires **72%** (cliff edge — all losses were ≤70%)

**Scoring still uses best available signal:** After both gates pass, `coverage_vs_hand` is preferred over `coverage_overall` for the actual score. Gates and scoring are separate concerns.

---

### **Shadow Enriched Pipeline (4 Signals)**

A parallel scoring pipeline runs after every production run, writing to separate shadow tables. All four signals now operational.

**Signal 1 — Blended ERA Rank:**
Season ERA rank (50%) + pitcher's last-3-start ERA rank (50%). Captures pitcher current form.

**Signal 2 — Opponent-Specific Coverage:**
Batter's hit rate vs tonight's specific opponent (min 3 games, 25% delta, ±8 cap).

**Signal 3 — Ballpark Factor:**
30-row `ballpark_factors` table (Coors 115 → Petco 94). Hitters ±5, pitchers ±3.

**Signal 4 — Opposing Team SO Rank (NEW — May 28):**
Adjusts pitcher SO prop scores based on how K-prone the opposing lineup is.

```python
# Season rank → primary adjustment (±5)
# Recent rank (14-day window) → modifier (±2)
# Net capped at ±6
# Sign-flipped for unders (high-K lineup = penalty for SO unders)

# Example: Jack Flaherty SO under vs LAA (rank 1 team Ks)
# team_so_adjustment = -6.0  (correctly penalized)
```

Applies **only** to pitcher SO props — no effect on batter props.

---

### **Direction-Aware Coverage**
```python
# OVER props
coverage_pct = (games_over / total_games) * 100

# UNDER props
coverage_pct = (games_under / total_games) * 100

# Handedness split (scoring signal, not gate)
coverage_vs_RHP = games_over_vs_RHP / total_games_vs_RHP * 100
```

---

### **In-Parlay Win Rates (Last 7 Days)**

| Prop | Direction | Win Rate | Status |
|---|---|---|---|
| Strikeouts under | 5.5 line | 85.7% | ✅ Prioritize |
| Hits | Under 0.5 | 71.1% | ✅ Keep |
| Strikeouts over | 6.5 line | 68.4% | ✅ Keep |
| Strikeouts under | 4.5 line | 63.0% | ✅ Keep |
| Hits | Over 0.5 | 60.0% | ✅ Keep |
| Strikeouts over | 4.5 line | 60.0% | ✅ Keep |
| Strikeouts over | 0.5 line | 57.6% | ⚠️ Monitor |
| RBI | Under 0.5 | 58.3% | ⚠️ Monitor |
| Total Bases under | 1.5 line | 50.4% | ⚠️ 80% floor |
| Strikeouts over | 5.5 line | 50.0% | ⚠️ 72% floor |
| Pitcher SO under | < 6.5 line | ~45% | 🚫 Blocked |
| Pitcher SO | < 4.5 line | 47.8% | 🚫 Blocked |
| Hitter K under | 0.5 line | 36.7% | 🚫 Blocked |
| Any prop | Either | — | 🚫 Blocked if odds < -300 |

---

### **Daily Pipeline (3× per day)**
- **9 AM ET:** Resolution + fetch/score/build (shadow runs after)
- **12 PM ET:** Fresh props refresh (shadow runs after)
- **5:30 PM ET:** Final refresh before games (shadow runs after)
- **Manual:** Regenerate button in web UI (shadow runs after)

---

## 📊 Current Performance

### **Pre-Anchor/Swing Baseline (May 22–25)**

| Metric | Value | Target |
|---|---|---|
| Parlay win rate | ~11% | 18–22% |
| In-parlay leg win rate | 57.6% | 67%+ |
| Anchor pool leg win rate (75%+ coverage) | 73–78% | ≥75% |
| Swing pool leg win rate (55–75% coverage) | 61–68% | ≥60% |

### **Expected Performance (Target)**
- 3 anchors at 75%: 0.75^3 = 42.2%
- 2 swings at 62%: 0.62^2 = 38.4%
- Combined 5-leg: 42.2% × 38.4% = **16.2% win rate**
- At +1000 odds: +$162 per $100 → **ROI 162%**

---

## 🗄️ Database Tables

| Table | Purpose | Status |
|---|---|---|
| `mlb_scored_legs` | Daily production legs | ✅ Active |
| `mlb_parlay_recommendations_v2` | Production parlays | ✅ Active |
| `mlb_parlay_legs_v2` | Production parlay legs | ✅ Active |
| `mlb_training_data` | Historical (94K+ rows) | ✅ Active |
| `mlb_scored_legs_enriched` | Shadow scored legs (4 signal columns) | ✅ Active |
| `mlb_parlay_recommendations_enriched` | Shadow parlays | ✅ Active |
| `mlb_parlay_legs_enriched` | Shadow parlay legs | ✅ Active |
| `ballpark_factors` | Park run/HR factors (30 rows) | ✅ Static |

---

## 🛠️ Tech Stack

- **Language:** Python 3.11
- **Framework:** Flask (Web UI + API)
- **Database:** Supabase (PostgreSQL)
- **Hosting:** Railway (auto-deploy from GitHub)
- **Data Sources:** SportsGameOdds API, MLB Stats API
- **Scheduler:** APScheduler (3× daily runs)

---

## 📁 Project Structure

```
mlb-agent/
├── src/
│   ├── engine/
│   │   ├── simple_scorer.py          # Phase 1 production scorer (consistency signal live)
│   │   ├── enriched_scorer.py        # Phase 2 shadow scorer (4 signals)
│   │   ├── coverage.py               # Direction-aware coverage calculation
│   │   ├── parlay_builder.py         # Anchor/swing parlay construction
│   │   └── resolver.py               # Outcome resolution
│   ├── apis/
│   │   ├── mlb_stats.py              # MLB Stats API wrapper (incl. team SO stats)
│   │   └── pitcher_stats.py          # Pitcher ERA/K9/WHIP ranks
│   ├── pipelines/
│   │   └── run_enriched_pipeline.py  # Shadow pipeline (writes to enriched tables)
│   ├── web/
│   │   ├── server.py                 # Flask web server
│   │   └── static/                   # Web UI
│   └── db/
│       └── db.py                     # Supabase connection
├── main.py                           # Pipeline orchestrator + shadow pipeline hook
├── bot.py                            # Discord bot
├── requirements.txt
└── Dockerfile
```

---

## 🚦 System Status

### **✅ Working Well**
- Anchor/swing parlay structure (Session 2)
- Two-gate coverage system (Session 1)
- Consistency signal (production + shadow)
- Shadow enriched pipeline (4 signals)
- Team SO rank signal (Signal 4, May 28)
- Direction-aware coverage calculation
- Pitcher SO line filters (min 4.5, unders blocked below 6.5)
- Juice cap (no props < -300 in parlays)
- Player diversity constraint
- Pipeline scheduler (3× daily)
- 9 AM morning pipeline producing parlays

### **📊 Under Evaluation (May 28 – June 2)**
- Anchor/swing impact on parlay win rate
- Consistency signal impact on per-leg win rate
- Enriched vs production comparison (all 4 signals)

### **⚠️ Pending Implementation**
- Gate 3: minimum `coverage_recent_10` floor (deferred pending validation)
- `won_with_void` outcome tracking
- Dead ERA/pitcher adjustment cleanup in `simple_scorer.py`
- Promote enriched scorer to production (June, after A/B comparison)

---

## 🔄 Recent Changes

### **May 28, 2026: Signal 4 — Team SO Rank**
- `get_team_strikeout_stats()` in `mlb_stats.py` (season rank + 14-day recent rank, 24hr cache)
- `_compute_team_so_adjustment()` in `enriched_scorer.py` (pitcher SO props only, ±6 cap)
- `team_so_adjustment` column added to `mlb_scored_legs_enriched`
- Fixed neutral consistency branch bug in `enriched_scorer.py`

### **May 28, 2026: Anchor/Swing + Consistency Signal**
- 3-anchor + 2-swing 5-leg structure replacing single-pool 4-leg
- Consistency gap signal live in production and shadow
- Pitcher SO line minimum raised to 4.5, unders blocked below 6.5
- `get_scored_legs()` deduplication fix (latest `logged_at` per player/stat/direction)

### **May 27, 2026: Session 1 — Coverage Floor Fixes**
- Gate 1: `coverage_overall >= 65%` before `coverage_vs_hand`
- Gate 2: 80% floor for `totalBases under 1.5`
- Gate 2: 72% floor for `strikeouts over 5.5`
- Chronic bad actors eliminated from pool

---

## 📈 Performance Monitoring

```sql
-- Parlay win rate (last 7 days)
SELECT
    COUNT(*) as parlays,
    (COUNT(*) FILTER (WHERE outcome = 'won') * 100.0 /
     COUNT(*) FILTER (WHERE outcome IN ('won','lost')))::numeric(5,1) as win_rate
FROM mlb_parlay_recommendations_v2
WHERE run_date >= CURRENT_DATE - 7 AND outcome IS NOT NULL;

-- In-parlay leg win rate by stat/direction (last 7 days)
SELECT
    l.stat, l.direction, l.line::numeric(4,1) as line,
    COUNT(*) FILTER (WHERE l.outcome IN ('won','lost')) as appearances,
    COUNT(*) FILTER (WHERE l.outcome = 'won') as won,
    (COUNT(*) FILTER (WHERE l.outcome = 'won') * 100.0 /
     NULLIF(COUNT(*) FILTER (WHERE l.outcome IN ('won','lost')), 0))::numeric(5,1) as win_rate
FROM mlb_parlay_legs_v2 l
JOIN mlb_parlay_recommendations_v2 p ON p.id = l.parlay_id
WHERE p.run_date >= CURRENT_DATE - 7
GROUP BY l.stat, l.direction, l.line::numeric(4,1)
ORDER BY win_rate ASC;

-- Team SO adjustment validation (enriched pipeline)
SELECT player_name, stat, direction, line,
       coverage_overall, team_so_adjustment, composite_score
FROM mlb_scored_legs_enriched
WHERE run_date = CURRENT_DATE
  AND stat = 'strikeouts'
  AND team_so_adjustment IS NOT NULL
ORDER BY team_so_adjustment DESC;

-- Production vs enriched comparison (after 5-7 days)
SELECT 'production' as pipeline, p.rank, p.total_odds, p.outcome,
       l.player_name, l.stat, l.direction, l.outcome as leg_outcome
FROM mlb_parlay_recommendations_v2 p
JOIN mlb_parlay_legs_v2 l ON l.parlay_id = p.id
WHERE p.batch_id IN (
    SELECT DISTINCT production_batch_id
    FROM mlb_parlay_recommendations_enriched
    WHERE run_date >= CURRENT_DATE - 7
)
UNION ALL
SELECT 'enriched' as pipeline, p.rank, p.total_odds, p.outcome,
       l.player_name, l.stat, l.direction, l.outcome as leg_outcome
FROM mlb_parlay_recommendations_enriched p
JOIN mlb_parlay_legs_enriched l ON l.parlay_id = p.id
WHERE p.run_date >= CURRENT_DATE - 7
ORDER BY pipeline DESC, rank, player_name;
```

---

**Last Updated:** May 28, 2026
**System Status:** ✅ Operational — Anchor/Swing Live, Shadow Pipeline at 4 Signals
**Next Review:** May 29, 2026 (Validate pitcher coverage_recent_10 + consistency signal on fresh data)
