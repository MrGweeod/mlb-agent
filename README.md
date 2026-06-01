# MLB Parlay Agent 🤖⚾

**Last Updated:** June 1, 2026
**Status:** ✅ Operational — Single Flat Pool + Validated Prop Whitelist Live
**Structure:** 4-leg parlays, +400 to +700 target
**June 1 Output:** 3 parlays (+613, +447, +419)

An intelligent MLB parlay recommendation system that analyzes player performance data, calculates direction-aware coverage percentages, and builds optimized 4-leg parlays targeting +400 to +700 combined odds. A shadow enriched pipeline runs alongside production to evaluate 3 additional scoring signals before promotion.

---

## 🎯 What It Does

1. **Fetches MLB Props** — Pulls 1,000+ player props daily from SportsGameOdds API
2. **Prop Whitelist** — Keeps only `hits over 0.5`, `hits under 0.5`, `strikeouts over 0.5` (hitter only)
3. **Coverage Gate** — 65% minimum `coverage_overall` (70% for hits under); checked before any scoring adjustments
4. **Odds Cap** — Blocks any leg priced worse than -250; max +150
5. **Calculates Coverage** — Direction-aware: "How often does this player go OVER/UNDER this line?"
6. **Scores with Consistency Signal** — Coverage + consistency gap penalty/boost + contextual adjustments
7. **Shadow Scores** — Parallel enriched scorer with 3 additional signals
8. **Builds 4-Leg Parlays** — Single flat pool, branch-and-bound search, +400 to +700 target
9. **Logs Everything** — Production and shadow data to Supabase for tracking and analysis
10. **Resolves Outcomes** — Updates legs and parlays with win/loss results each morning

---

## 📊 Why These Props

Based on 60-day analysis across 90,000+ resolved leg outcomes:

| Prop | Win Rate at 65%+ Coverage | Avg Odds | Edge Above Breakeven |
|---|---|---|---|
| **hits over 0.5** | 67.2% | -214 | +0pp avg, +6pp at 75%+ |
| **SO over 0.5** (hitter) | 69.0% | -199 | **+2.4pp** |
| **hits under 0.5** | 66.7% | -127 | **+10.7pp** |

**Removed props (with reasons):**

| Prop | Win Rate | Why Removed |
|---|---|---|
| `totalBases under 1.5` | 57-63% flat | No coverage signal at any bucket (1,000+ appearances) |
| `rbi under 0.5` | 67-77% flat | Book prices edge away — avg -348 at 85%+ coverage |
| Pitcher SO (all lines) | 30-52% | Coverage missing 55%+ of legs; win rates unreliable |
| `walks`, `homeRuns`, `stolenBases` | — | Insufficient sample / negative edge |

Coverage IS predictive for hits over and SO over. For everything else, the signal is flat or the book has already priced it away.

---

## 🚀 Key Architecture

### **Single Flat Pool (Since June 1, 2026)**

Replaced the anchor/swing two-pool system. With only 3 validated prop types all priced similarly (-250 to +150), a single pool is simpler and more robust.

| Parameter | Value |
|---|---|
| Coverage floor | 65% `coverage_overall` |
| Odds range | -250 to +150 per leg |
| Legs per parlay | 4 |
| Target combined odds | +400 to +700 |
| Max legs per game | 2 |
| Player diversity | 1 player per parlay, 1 per batch |

**Why single pool over anchor/swing:** Anchor/swing caused parlay starvation on thin slates — 1 swing leg available → 1 parlay maximum. With a uniform prop set, the distinction added no value.

**Why +400 to +700:** 4-leg math at 70% per leg = 24% win probability. Profitable above ~17% win rate at +500 average. Previous +900-+1100 target required 14% win rate — near-breakeven ROI.

---

### **Direction-Aware Coverage**

```python
# OVER props
coverage_pct = (games_over / total_games) * 100

# UNDER props
coverage_pct = (games_under / total_games) * 100

# Handedness split (scoring signal, not gate)
coverage_vs_hand = log-odds adjusted for pitcher handedness
```

`coverage_overall` gates eligibility. `coverage_vs_hand` ranks among eligible legs. These serve different purposes.

---

### **Consistency Signal**

Penalizes cold-streak legs and rewards hot streaks:

```python
gap = coverage_overall - coverage_recent_10

if gap >= 20:    adj = -6   # severe cold streak
elif gap >= 12:  adj = -4   # moderate cold streak
elif gap >= 6:   adj = -2   # mild cooling
elif gap <= -10: adj = +2   # meaningfully hot
elif gap <= -5:  adj = +1   # slightly warm
else:            adj =  0   # neutral
```

---

### **Shadow Enriched Pipeline (3 Signals)**

Runs after every production pipeline. Writes to separate shadow tables for A/B comparison.

**Signal 1 — Blended ERA Rank:**
Season ERA rank (50%) + pitcher's last-3-start ERA rank (50%). Applies to `hits` props only.

**Signal 2 — Opponent-Specific Coverage:**
Batter's hit rate vs tonight's specific opponent (min 3 games, 25% delta, ±8 cap).

**Signal 3 — Ballpark Factor:**
30-row `ballpark_factors` table (Coors 115 → Petco 94). Hitters ±5.

---

### **Daily Pipeline (3× per day)**
- **9 AM ET:** Resolution + fetch/score/build (shadow runs after)
- **12 PM ET:** Fresh props refresh (shadow runs after)
- **5:30 PM ET:** Final refresh before games (shadow runs after)
- **Manual:** Regenerate button in web UI

---

## 📈 Expected Performance

### **Per-Leg Win Rates (Validated, 60-Day Data)**

| Coverage Bucket | Hits Over Win Rate | SO Over Win Rate |
|---|---|---|
| 60-64% | 64.3% | 61.3% |
| 65-69% | 65.3% | 64.7% |
| 70-74% | 67.0% | 69.1% |
| 75-79% | **75.4%** | **73.7%** |
| 80-84% | 64.0% | 78.4% |

### **4-Leg Parlay Math**

| Scenario | Per-Leg Rate | Win Probability | At +500 Odds | ROI |
|---|---|---|---|---|
| Conservative (65% legs) | 65% | 17.9% | +$89.50/100 | **+89%** |
| Expected (70% legs) | 70% | 24.0% | +$120/100 | **+120%** |
| Strong (75% legs) | 75% | 31.6% | +$158/100 | **+158%** |

---

## 🗄️ Database Tables

| Table | Purpose |
|---|---|
| `mlb_scored_legs` | Daily production legs with coverage signals |
| `mlb_parlay_recommendations_v2` | Production parlays |
| `mlb_parlay_legs_v2` | Production parlay legs with outcomes |
| `mlb_training_data` | Historical resolved legs (94K+ rows) |
| `mlb_scored_legs_enriched` | Shadow scored legs + 3 signal columns |
| `mlb_parlay_recommendations_enriched` | Shadow parlays |
| `mlb_parlay_legs_enriched` | Shadow parlay legs |
| `ballpark_factors` | Park run/HR factors (30 rows, static) |

---

## 🛠️ Tech Stack

- **Language:** Python 3.10
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
│   │   ├── simple_scorer.py          # Production scorer (consistency signal)
│   │   ├── enriched_scorer.py        # Shadow scorer (3 signals)
│   │   ├── coverage.py               # Direction-aware coverage calculation
│   │   ├── parlay_builder.py         # Single-pool 4-leg parlay builder
│   │   └── resolver.py               # Outcome resolution
│   ├── apis/
│   │   ├── mlb_stats.py              # MLB Stats API wrapper
│   │   ├── pitcher_stats.py          # Pitcher ERA/K9/WHIP ranks
│   │   └── team_stats.py             # Team offensive ranks
│   ├── pipelines/
│   │   ├── run_enriched_pipeline.py  # Shadow pipeline
│   │   ├── enrich_legs.py            # Pitcher matchup enrichment
│   │   └── trend_analysis.py         # Trend/consistency signals
│   ├── tracker/
│   │   ├── parlay_outcome_resolver.py # Parlay resolution (EEP-fixed)
│   │   └── outcome_resolver.py        # Leg resolution
│   ├── web/
│   │   ├── server.py                 # Flask web server
│   │   └── static/                   # Web UI
│   └── utils/
│       └── db.py                     # Supabase connection
├── scripts/
│   ├── backfill_resolution_eep_fix.py # Re-resolve EEP-affected dates
│   └── sync_parlay_leg_outcomes.py    # Sync historical mismatches
├── main.py                           # Pipeline orchestrator
├── bot.py                            # Discord bot
├── requirements.txt
└── Dockerfile
```

---

## 🚦 System Status

### **✅ Working Well**
- Single flat pool parlay construction
- Validated prop whitelist (hits over/under 0.5, SO over 0.5 hitter)
- -250 odds cap (recovering previously excluded legs)
- Direction-aware coverage calculation
- Consistency signal (production + shadow)
- Shadow enriched pipeline (3 signals)
- EEP false-void bug fixed (June 1)
- Player diversity constraint
- Pipeline scheduler (3× daily)
- Morning resolution producing correct outcomes

### **📊 Under Evaluation**
- New prop set win rates (June 2026 — first 30 days)
- Shadow vs production comparison (target June 8+)
- `hits under 0.5` viability (thin sample — 24 appearances at 65%+)

### **⚠️ Known Issues / Pending**
- Health check threshold stale (flags 65%+ hit rate as anomalous — expected with new gate)
- Negative EV legs appearing in parlays (selection by score, not EV)
- `won_with_void` outcome not tracked separately

---

## 🔄 Recent Changes

### **June 1, 2026: Single Flat Pool + 4-Leg Parlays** (`1ebbb24`)
- Eliminated anchor/swing two-pool system
- 4-leg parlays, +400 to +700, -250 odds cap
- `build_parlays()` primary function; `build_hybrid_parlays()` backward-compat wrapper

### **June 1, 2026: Prop Whitelist** (`885a4a7`)
- Hits over/under 0.5 + SO over 0.5 (hitter) only
- Removed: totalBases, rbi, walks, pitcher SO, homeRuns, stolenBases
- Removed dead signals: pitcher ERA block, Signal 4 (team SO), `calculate_pitcher_k_coverage()`

### **June 1, 2026: EEP False-Void Fix** (`928b6c6`)
- `plateAppearances` and `battersFaced` now use `is not None` guard
- `game_not_found` defers parlay instead of voiding leg
- Backfilled May 29–June 1: 3 parlays recovered as wins

---

## 📋 Performance Monitoring Queries

```sql
-- Parlay win rate last 7 days
SELECT
    run_date,
    COUNT(*) FILTER (WHERE outcome IN ('won','lost')) as resolved,
    COUNT(*) FILTER (WHERE outcome = 'won') as won,
    (COUNT(*) FILTER (WHERE outcome = 'won') * 100.0 /
     NULLIF(COUNT(*) FILTER (WHERE outcome IN ('won','lost')), 0))::numeric(5,1) as win_rate
FROM mlb_parlay_recommendations_v2
WHERE run_date >= CURRENT_DATE - 7
GROUP BY run_date
ORDER BY run_date DESC;

-- In-parlay leg win rate by prop
SELECT
    l.stat, l.direction, l.line::numeric(4,1) as line,
    COUNT(*) FILTER (WHERE l.outcome IN ('won','lost')) as appearances,
    COUNT(*) FILTER (WHERE l.outcome = 'won') as won,
    (COUNT(*) FILTER (WHERE l.outcome = 'won') * 100.0 /
     NULLIF(COUNT(*) FILTER (WHERE l.outcome IN ('won','lost')), 0))::numeric(5,1) as win_rate,
    AVG(CASE WHEN l.odds ~ '^-?[0-9]+(\.[0-9]+)?$' THEN l.odds::numeric END)::numeric(6,1) as avg_odds
FROM mlb_parlay_legs_v2 l
JOIN mlb_parlay_recommendations_v2 p ON p.id = l.parlay_id
WHERE p.run_date >= CURRENT_DATE - 7
GROUP BY l.stat, l.direction, l.line::numeric(4,1)
ORDER BY appearances DESC;

-- Coverage bucket performance (all-time, for signal validation)
SELECT
    stat, direction,
    CASE
        WHEN coverage_overall < 65 THEN '< 65%'
        WHEN coverage_overall < 70 THEN '65-69%'
        WHEN coverage_overall < 75 THEN '70-74%'
        WHEN coverage_overall < 80 THEN '75-79%'
        ELSE '80%+'
    END as coverage_bucket,
    COUNT(*) FILTER (WHERE result IN ('won','lost')) as appearances,
    (COUNT(*) FILTER (WHERE result = 'won') * 100.0 /
     NULLIF(COUNT(*) FILTER (WHERE result IN ('won','lost')), 0))::numeric(5,1) as win_rate
FROM mlb_scored_legs
WHERE result IN ('won', 'lost')
  AND coverage_overall IS NOT NULL
  AND stat IN ('hits', 'strikeouts') AND line = 0.5
GROUP BY stat, direction, coverage_bucket
HAVING COUNT(*) >= 20
ORDER BY stat, direction, coverage_bucket;

-- Shadow vs production comparison
SELECT
    'production' as pipeline,
    COUNT(*) FILTER (WHERE outcome = 'won') as won,
    COUNT(*) FILTER (WHERE outcome IN ('won','lost')) as resolved,
    (COUNT(*) FILTER (WHERE outcome = 'won') * 100.0 /
     NULLIF(COUNT(*) FILTER (WHERE outcome IN ('won','lost')), 0))::numeric(5,1) as win_rate
FROM mlb_parlay_recommendations_v2
WHERE run_date >= '2026-06-01'
UNION ALL
SELECT
    'shadow' as pipeline,
    COUNT(*) FILTER (WHERE outcome = 'won') as won,
    COUNT(*) FILTER (WHERE outcome IN ('won','lost')) as resolved,
    (COUNT(*) FILTER (WHERE outcome = 'won') * 100.0 /
     NULLIF(COUNT(*) FILTER (WHERE outcome IN ('won','lost')), 0))::numeric(5,1) as win_rate
FROM mlb_parlay_recommendations_enriched
WHERE run_date >= '2026-06-01';
```

---

**Last Updated:** June 1, 2026
**System Status:** ✅ Operational — Single Pool + Validated Prop Whitelist Live
**Next Review:** June 2, 2026 (Morning resolution validation + first full-day output)
