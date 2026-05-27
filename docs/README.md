# MLB Parlay Agent 🤖⚾

**Last Updated:** May 27, 2026
**Status:** ✅ Operational — Session 1 Coverage Fixes Live
**Win Rate:** ~11% parlay win rate (target 18–22%, Session 1 fixes under evaluation)

An intelligent MLB parlay recommendation system that analyzes player performance data, calculates direction-aware coverage percentages, and builds optimized 4-leg parlays with +700 to +1000 combined odds. A shadow enriched pipeline runs alongside production to evaluate new scoring signals before promotion.

---

## 🎯 What It Does

1. **Fetches MLB Props** — Pulls 2000+ player props daily from SportsGameOdds API
2. **Gates on `coverage_overall`** — Hard 65% floor on season coverage before any adjustments applied (NEW May 27)
3. **Applies Prop-Specific Floors** — 80% floor for TB under 1.5, 72% floor for SO over 5.5 (NEW May 27)
4. **Calculates Coverage** — Direction-aware: "How often does this player go OVER/UNDER this line?"
5. **Scores Intelligently** — Coverage + 5 contextual adjustments (Phase 1 simple scorer)
6. **Shadow Scores** — Runs enriched scorer in parallel with 4 signals (Phase 2, Signal 4 pending)
7. **Blocks Toxic Props** — Removes categories with poor in-parlay win rates
8. **Caps Extreme Juice** — Blocks props with odds worse than -300 from parlays
9. **Builds Parlays** — Branch-and-bound search for optimal 4-leg combinations
10. **Logs Everything** — Production and shadow data to Supabase for tracking and comparison
11. **Resolves Outcomes** — Updates legs and parlays with win/loss results each morning

---

## 🚀 Key Features

### **Two-Gate Coverage System (NEW — May 27)**

The coverage filtering system now enforces two explicit gates before a leg enters the parlay pool:

**Gate 1 — `coverage_overall` floor:**
All legs must have a season-long `coverage_overall` of at least 65%, checked before any handedness splits or contextual adjustments are applied. This prevents adjustments from rescuing marginal players.

**Gate 2 — Prop-specific floors:**
Higher floors for categories with demonstrated poor in-parlay performance:
- `totalBases under 1.5` requires **80% `coverage_overall`** (7-day in-parlay win rate was 50.4%)
- `strikeouts over 5.5` requires **72% `coverage_overall`** (cliff edge — all losses were ≤70%)

**Scoring still uses best available signal:** After both gates pass, `coverage_vs_hand` is preferred over `coverage_overall` for the actual score computation. Gates and scoring are separate concerns.

---

### **Shadow Enriched Pipeline (May 26)**

A parallel scoring pipeline runs after every production run writing to separate shadow tables. Four signals being evaluated:

**Signal 1 — Blended ERA Rank:**
Season ERA rank (50%) + pitcher's last 3-start ERA rank (50%).

**Signal 2 — Opponent-Specific Coverage:**
Batter's hit rate vs tonight's specific opponent (min 3 games, 25% delta, ±8 cap).

**Signal 3 — Ballpark Factor:**
30-row `ballpark_factors` table (Coors 115 → Petco 94).

**Signal 4 — Consistency (Pending May 29):**
`coverage_overall - coverage_recent_10` gap. Penalizes cold streaks, rewards hot streaks.

---

### **Phase 1 Simple Scorer (May 20)**

```python
score = base_coverage + adjustments
# base = coverage_vs_hand (preferred) or coverage_overall
# adjustments:
#   +3  handedness split available
#   ±4  recent form (10-game rolling window)
#   ±5  opponent pitcher ERA quality
#   ±5  pitcher K/9 rate (for strikeout props)
#   -5  lineup stability < 50%
```

**Note:** Score-outcome correlation analysis (May 27) shows lost legs scoring slightly higher than won legs (75.5 vs 74.2), suggesting ERA/K-rate adjustments may be adding noise. Under review.

---

### **In-Parlay Win Rates (Last 7 Days)**

| Prop | Direction | Win Rate | Status |
|---|---|---|---|
| Strikeouts under | 5.5 line | 85.7% | ✅ Prioritize |
| Strikeouts over | 3.5 line | 76.9% | ✅ Keep |
| Hits | Under 0.5 | 71.1% | ✅ Keep |
| Strikeouts over | 6.5 line | 68.4% | ✅ Keep |
| Strikeouts under | 4.5 line | 63.0% | ✅ Keep |
| Hits | Over 0.5 | 60.0% | ✅ Keep |
| Strikeouts over | 4.5 line | 60.0% | ✅ Keep |
| Strikeouts over | 0.5 line | 57.6% | ⚠️ Monitor |
| RBI | Under 0.5 | 58.3% | ⚠️ Monitor |
| Total Bases under | 1.5 line | 50.4% | ⚠️ 80% floor |
| Strikeouts over | 5.5 line | 50.0% | ⚠️ 72% floor |
| Pitcher K under | <5.5 line | ~45% | 🚫 Pending block |
| Hitter K under | 0.5 line | 36.7% | 🚫 Blocked |
| Any prop | Either | — | 🚫 Blocked if odds < -300 |

---

### **Direction-Aware Coverage**
```python
# OVER props
coverage_pct = (games_over / total_games) * 100

# UNDER props
coverage_pct = (games_under / total_games) * 100

# Handedness split (used for scoring, not gating)
coverage_vs_RHP = games_over_vs_RHP / total_games_vs_RHP * 100
```

---

### **Intelligent Parlay Construction**
- 4 legs per parlay
- Combined odds: **+700 to +1000**
- Juice cap: props with odds < -300 excluded from parlay pool
- Max 2 legs per game (correlation limit)
- Max 1 leg per player per batch (diversity constraint)
- Branch-and-bound search

---

### **Daily Pipeline (3x per day)**
- **9 AM ET:** Resolution + fetch/score/build (shadow runs after)
- **12 PM ET:** Fresh props refresh (shadow runs after)
- **5:30 PM ET:** Final refresh before games (shadow runs after)
- **Manual:** Regenerate button in web UI (shadow runs after)

---

## 📊 Current Performance

### **May 22–25 (Pre-Session 1)**

| Metric | Value | Target |
|---|---|---|
| Parlay win rate | ~11% | 18–22% |
| In-parlay leg win rate | 57.6% | 67%+ |
| `totalBases under 1.5` in-parlay rate | 50.4% | ≥65% |
| `strikeouts over 5.5` in-parlay rate | 50.0% | ≥65% |

**Gap analysis:** Session 1 eliminates the two largest underperforming categories. Expected improvement in per-leg win rate toward 63–65%, which implies parlay win rate of ~16–18%.

### **Expected Performance (Target)**
- 4-leg at 67%: 0.67^4 = **20.2% win rate**
- At +800 odds: +$81.60 per $100 → **ROI 81.6%**

---

## 🗄️ Database Tables

| Table | Purpose | Status |
|---|---|---|
| `mlb_scored_legs` | Daily production legs | ✅ Active |
| `mlb_parlay_recommendations_v2` | Production parlays | ✅ Active |
| `mlb_parlay_legs_v2` | Production parlay legs | ✅ Active |
| `mlb_training_data` | Historical (94K+ rows) | ✅ Active |
| `mlb_scored_legs_enriched` | Shadow scored legs | ✅ Active |
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
- **Scheduler:** APScheduler (3x daily runs)

---

## 📁 Project Structure

```
mlb-agent/
├── src/
│   ├── engine/
│   │   ├── simple_scorer.py          # Phase 1 production scorer
│   │   ├── enriched_scorer.py        # Phase 2 shadow scorer (4 signals)
│   │   ├── coverage.py               # Direction-aware coverage calculation
│   │   ├── parlay_builder.py         # Parlay construction (juice cap)
│   │   └── resolver.py               # Outcome resolution
│   ├── pipelines/
│   │   └── run_enriched_pipeline.py  # Shadow pipeline (writes to enriched tables)
│   ├── web/
│   │   ├── server.py                 # Flask web server
│   │   └── static/                   # Web UI
│   └── db/
│       └── db.py                     # Supabase connection
├── main.py                           # Pipeline orchestrator + shadow pipeline hook
├── requirements.txt
├── Dockerfile
└── docs/
    ├── SESSION_HANDOFF.md
    ├── BUILD_STATUS.md
    ├── ARCHITECTURE_DECISIONS.md
    └── README.md
```

---

## 🚦 System Status

### **✅ Working Well**
- Two-gate coverage system (Session 1 fix)
- Simple coverage-based scorer (Phase 1)
- Direction-aware coverage calculation
- Shadow enriched pipeline (3 signals computing, Signal 4 Friday)
- Prop filtering (blocking unprofitable categories)
- Juice cap (no props < -300 in parlays)
- Player diversity constraint
- Pipeline scheduler (3x daily)
- 9AM morning pipeline producing parlays

### **📊 Under Evaluation (May 27–June 2)**
- Session 1 filter impact on parlay win rate
- Enriched scoring signals vs production win rate comparison

### **⚠️ Pending Implementation**
- Pitcher K under line ≥5.5 minimum (`main.py`)
- Consistency signal in shadow enriched scorer (`enriched_scorer.py`)
- `won_with_void` outcome tracking (`parlay_outcome_resolver.py`)

---

## 🔄 Recent Changes

### **May 27, 2026: Session 1 — Coverage Floor Fixes**
- Added Gate 1: `coverage_overall >= 65%` checked before `coverage_vs_hand`
- Added Gate 2: 80% floor for `totalBases under 1.5`
- Added Gate 2: 72% floor for `strikeouts over 5.5`
- Commit `9f49aa3` deployed to Railway
- Chronic bad actors (Mookie Betts, José Ramírez, Josh Naylor, Braxton Ashcraft) eliminated from pool

### **May 26, 2026: Shadow Enriched Pipeline**
- Built `enriched_scorer.py` with 3 signals
- Full data integrity fix (sequences, `created_at`, `production_batch_id`)

### **May 21, 2026: Strategy Optimization**
- Lowered odds to +700–+1000, added juice cap

### **May 20, 2026: Phase 1 Simple Scorer**
- Replaced ML model, validated 69% accuracy on 7,895 resolved legs

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

**Last Updated:** May 27, 2026
**System Status:** ✅ Operational — Session 1 Live, Shadow Pipeline Active
**Next Review:** May 29, 2026 (Session 2 — Consistency Signal + Pitcher K Under Threshold)
