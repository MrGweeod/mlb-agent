# MLB Parlay Agent 🤖⚾

**Last Updated:** June 5, 2026
**Status:** ✅ Operational — Full Signal Pipeline Fixed + Parlay Builder Corrected
**Structure:** 4-leg parlays, +400 to +700 target
**Latest Output:** 2-5 parlays/day (thin slate: 2, full slate: 4-5)

An intelligent MLB parlay recommendation system that analyzes player performance data, calculates direction-aware coverage percentages, and builds optimized 4-leg parlays targeting +400 to +700 combined odds. A shadow enriched pipeline runs alongside production to evaluate additional scoring signals before promotion.

---

## 🎯 What It Does

1. **Fetches MLB Props** — Pulls 1,000+ player props daily from SportsGameOdds API
2. **Prop Whitelist** — Keeps only `hits over 0.5`, `hits under 0.5`, `strikeouts over 0.5` (hitter only)
3. **Coverage Gate** — 65% minimum `coverage_overall` (70% for hits under); checked before any scoring adjustments
4. **Odds Cap** — Blocks any leg priced worse than -250; max +150
5. **Calculates Coverage** — Direction-aware: "How often does this player go OVER/UNDER this line?"
6. **Attaches Pitcher Signals** — Opposing pitcher ERA rank, K9 rank, WHIP rank attached to all hitter legs
7. **Scores with Multi-Signal Scorer** — Coverage + consistency + K9 rank + ERA + lineup stability
8. **Shadow Scores** — Parallel enriched scorer with park factor, opponent coverage split, blended ERA rank
9. **Builds 4-Leg Parlays** — Single flat pool, score-sorted B&B search, +400 to +700 target
10. **Logs Everything** — Production and shadow data to Supabase for tracking and analysis
11. **Resolves Outcomes** — Updates legs, parlays, and shadow table with win/loss results each morning

---

## 📊 Why These Props

Based on 60-day analysis across 90,000+ resolved leg outcomes:

| Prop | Win Rate at 65%+ Coverage | Avg Odds | Edge Above Breakeven |
|---|---|---|---|
| **hits over 0.5** | 67.2% | -214 | +6pp at 75%+ coverage |
| **SO over 0.5** (hitter) | 69.0% | -199 | **+7pp** |
| **hits under 0.5** | 66.7% | -127 | **+10.7pp** |

Coverage IS predictive for hits over and SO over. For everything else (totalBases under, rbi under, pitcher SO), the signal is flat or the book has already priced it away.

---

## 🚀 Key Architecture

### **Single Flat Pool (June 1, 2026)**

| Parameter | Value |
|---|---|
| Coverage floor | 65% `coverage_overall` |
| Odds range | -250 to +150 per leg |
| Legs per parlay | 4 |
| Target combined odds | +400 to +700 |
| Max legs per game | 2 |
| Player diversity | 1 player per parlay, 1 per batch |

### **Score-Sorted Parlay Builder (June 5, 2026)**

Pool is sorted by `composite_score` descending before the branch-and-bound search. The B&B explores the highest-quality legs first. `MAX_CANDIDATES = 50` ensures the search explores enough of the pool to find diverse combinations. B&B pruning bounds use `suffix_dec_sorted` to remain valid under any sort order.

**Why this matters:** Previously the pool was sorted by odds for pruning efficiency. This caused cheap-odds, low-quality legs to be explored before expensive-odds, high-quality legs. Oneil Cruz (score 59, -148 odds) was explored before Ryan Waldschmidt (score 78, -176 odds). Fixed.

---

### **Pitcher Signal Pipeline (June 5, 2026)**

All hitter legs now receive opposing pitcher rank signals:

```
get_pitcher_ranks(season)          → 192 qualified starters (3+ starts, 3.0+ IP/start)
    ↓
_attach_pitcher_rank_signals()     → attaches opp_pitcher_era_rank, opp_pitcher_k9_rank,
                                     opp_pitcher_whip_rank to ALL hitter legs
    ↓
simple_scorer.calculate_score()    → uses opp_pitcher_k9_rank for SO props (±5)
                                     uses pitcher_era for hits props (±5)
```

**Previously broken (fixed June 5):**
- Batter strikeout legs were classified as pitcher props due to `stat in _PITCHER_STATS`, receiving NULL pitcher data
- `_attach_pitcher_rank_signals()` only processed pitcher prop legs, skipping all hitter legs
- IP threshold of 50 innings excluded Ohtani, Cole, Harrison from ranking pool

---

### **Direction-Aware Coverage**

```python
# OVER props: % of games where stat >= line
# UNDER props: % of games where stat < line
# coverage_vs_hand: log-odds adjusted for pitcher handedness (delta adjustment only)
```

`coverage_overall` = always the base signal and gate signal.
`coverage_vs_hand` = delta adjustment at 30% weight, capped ±3 points. Validated: produces values within 0.5 points of overall, identical win rates with vs without.

---

### **Consistency Signal**

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

### **Shadow Enriched Pipeline (3 Signals Active)**

Runs after every production pipeline. Writes to separate shadow tables for A/B comparison. Resolution now wired up — shadow outcomes updated after every morning resolution.

**Signal 1 — Blended ERA Rank:** Season ERA rank (50%) + pitcher's last-3-start ERA rank (50%). Computed and stored on all hits legs. NOT applied to score pending revalidation after pitcher IP fix.

**Signal 2 — Opponent-Specific Coverage:** Batter's hit rate vs tonight's specific opponent (min 3 games, 25% delta, ±8 cap). ~20-35% population rate early season.

**Signal 3 — Ballpark Factor:** 30-row `ballpark_factors` static table (Coors 115 → Petco 94). Validated: 30-point win rate spread between pitcher parks (40%) and hitter parks (70%). Strongest validated enriched signal.

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
| 80%+ | 64.0% | 78.4% |

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
| `mlb_scored_legs` | Daily production legs with all coverage + pitcher signals |
| `mlb_parlay_recommendations_v2` | Production parlays |
| `mlb_parlay_legs_v2` | Production parlay legs with outcomes |
| `mlb_training_data` | Historical resolved legs (94K+ rows) |
| `mlb_scored_legs_enriched` | Shadow scored legs + enriched signal columns |
| `mlb_parlay_recommendations_enriched` | Shadow parlays |
| `mlb_parlay_legs_enriched` | Shadow parlay legs |
| `ballpark_factors` | Park run/HR factors (30 rows, static) |

**Critical type notes:**
- `mlb_scored_legs.run_date`: TEXT — use string comparisons
- `mlb_scored_legs_enriched.id`: NULL for all rows — use natural key `(player_name, stat, direction, run_date, line)` for all writes

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
│   │   ├── simple_scorer.py          # Production scorer
│   │   ├── enriched_scorer.py        # Shadow scorer (3 signals)
│   │   ├── coverage.py               # Direction-aware coverage calculation
│   │   ├── parlay_builder.py         # Score-sorted 4-leg parlay builder
│   │   └── resolver.py               # Outcome resolution
│   ├── apis/
│   │   ├── mlb_stats.py              # MLB Stats API wrapper
│   │   ├── pitcher_stats.py          # Pitcher ERA/K9/WHIP ranks (192 qualified)
│   │   └── team_stats.py             # Team offensive ranks
│   ├── pipelines/
│   │   ├── run_enriched_pipeline.py  # Shadow pipeline
│   │   ├── enrich_legs.py            # Pitcher matchup enrichment (Bug 1 fixed)
│   │   └── trend_analysis.py         # Trend/consistency signals
│   ├── tracker/
│   │   ├── parlay_outcome_resolver.py # Resolution (writes to both prod + shadow)
│   │   └── outcome_resolver.py        # Leg resolution
│   ├── web/
│   │   ├── server.py                 # Flask web server
│   │   └── static/                   # Web UI
│   └── utils/
│       └── db.py                     # Supabase connection
├── scripts/
│   ├── backfill_shadow_resolution.py # Shadow resolution backfill
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
- Full pitcher signal pipeline (IP fix + Bug 1 fix + rank attachment to hitter legs)
- K9 rank signal for batter strikeout props
- Score-sorted parlay builder with MAX_CANDIDATES 50
- Single flat pool parlay construction
- Validated prop whitelist (hits over/under 0.5, SO over 0.5 hitter)
- -250 odds cap
- Direction-aware coverage calculation
- Consistency signal
- Park factor signal (validated — 30pp spread)
- Shadow enriched pipeline (3 signals, resolution now wired)
- EEP false-void bug fixed
- Player diversity constraint
- Pipeline scheduler (3× daily)
- Morning resolution correct for both prod and shadow

### **📊 Under Evaluation**
- ERA rank signal for hits props (needs 7+ days clean data post IP-fix)
- K9 rank signal for SO props (first clean measurement after Bug 1 fix)
- Shadow vs production comparison (target June 12+)
- `hits under 0.5` viability (0 legs in today's pool — investigate)

### **⚠️ Known Issues / Pending**
- Health check hit rate threshold stale (flags 65%+ as anomalous — expected with new gate)
- Negative EV legs appearing in parlays (selection by score, not EV)
- `won_with_void` outcome not tracked separately
- Raw `pitcher_era` adjustment in `simple_scorer.py` hits props — pending revalidation

---

## 🔄 Recent Changes

### **June 5, 2026: Opposing Pitcher Ranks → Hitter Legs + K9 Rank in Scorer** (`e67896e`)
- `_attach_pitcher_rank_signals()` now attaches `opp_pitcher_era_rank`, `opp_pitcher_k9_rank`, `opp_pitcher_whip_rank` to all hitter legs
- `simple_scorer.py` batter SO props use `opp_pitcher_k9_rank` (±5) with raw K9 fallback
- Unit test: 75 (elite K9) > 70 (no rank) > 65 (weak K9) ✅

### **June 5, 2026: Full Signal Pipeline + Parlay Builder Corrections** (`1ab63c2`)
- Pitcher IP threshold: 50 IP → per-start (3+ starts, 3.0 IP/start) — pool 20-25 → 192
- Bug 1: batter SO legs now fully enriched (pitcher_era, pitcher_k9, pitcher_hand)
- Enriched scorer: base signal standardized, +3 bonus removed, ERA scoring removed, K9 rank added
- Parlay builder: score-sort + MAX_CANDIDATES 50 + suffix_dec_sorted pruning fix

### **June 5, 2026: Shadow Resolution Backfill**
- 1,240 rows backfilled via bulk SQL UPDATE
- Morning resolver now writes to `mlb_scored_legs_enriched` ongoing

### **June 1, 2026: Single Flat Pool + 4-Leg Parlays** (`1ebbb24`)
- Eliminated anchor/swing two-pool system
- 4-leg parlays, +400 to +700, -250 odds cap

### **June 1, 2026: EEP False-Void Fix** (`928b6c6`)
- `plateAppearances` and `battersFaced` use `is not None` guard
- Backfilled May 29–June 1

---

## 📋 Key Monitoring Queries

```sql
-- Parlay win rate last 7 days
SELECT run_date,
    COUNT(*) FILTER (WHERE outcome IN ('won','lost')) as resolved,
    COUNT(*) FILTER (WHERE outcome = 'won') as won,
    (COUNT(*) FILTER (WHERE outcome = 'won') * 100.0 /
     NULLIF(COUNT(*) FILTER (WHERE outcome IN ('won','lost')), 0))::numeric(5,1) as win_rate
FROM mlb_parlay_recommendations_v2
WHERE run_date >= CURRENT_DATE - 7
GROUP BY run_date ORDER BY run_date DESC;

-- Strikeout leg score spread (validate K9 rank signal)
SELECT player_name, stat, pitcher_name, pitcher_k9, coverage_overall, composite_score
FROM mlb_scored_legs
WHERE run_date = (CURRENT_DATE)::text
  AND stat = 'strikeouts' AND line = 0.5
  AND position NOT IN ('SP','RP','P')
ORDER BY composite_score DESC;

-- Shadow vs production comparison
SELECT 'production' as pipeline,
    COUNT(*) FILTER (WHERE outcome = 'won') as won,
    COUNT(*) FILTER (WHERE outcome IN ('won','lost')) as resolved,
    (COUNT(*) FILTER (WHERE outcome = 'won') * 100.0 /
     NULLIF(COUNT(*) FILTER (WHERE outcome IN ('won','lost')), 0))::numeric(5,1) as win_rate
FROM mlb_parlay_recommendations_v2 WHERE run_date >= '2026-06-05'
UNION ALL
SELECT 'shadow' as pipeline,
    COUNT(*) FILTER (WHERE outcome = 'won') as won,
    COUNT(*) FILTER (WHERE outcome IN ('won','lost')) as resolved,
    (COUNT(*) FILTER (WHERE outcome = 'won') * 100.0 /
     NULLIF(COUNT(*) FILTER (WHERE outcome IN ('won','lost')), 0))::numeric(5,1) as win_rate
FROM mlb_parlay_recommendations_enriched WHERE run_date >= '2026-06-05';

-- Coverage bucket performance (signal validation)
SELECT stat, direction,
    CASE WHEN coverage_overall < 65 THEN '< 65%'
         WHEN coverage_overall < 70 THEN '65-69%'
         WHEN coverage_overall < 75 THEN '70-74%'
         WHEN coverage_overall < 80 THEN '75-79%'
         ELSE '80%+' END as coverage_bucket,
    COUNT(*) FILTER (WHERE result IN ('won','lost')) as appearances,
    (COUNT(*) FILTER (WHERE result = 'won') * 100.0 /
     NULLIF(COUNT(*) FILTER (WHERE result IN ('won','lost')), 0))::numeric(5,1) as win_rate
FROM mlb_scored_legs
WHERE result IN ('won','lost') AND coverage_overall IS NOT NULL
  AND stat IN ('hits','strikeouts') AND line = 0.5
GROUP BY stat, direction, coverage_bucket
HAVING COUNT(*) >= 20
ORDER BY stat, direction, coverage_bucket;
```

---

**Last Updated:** June 5, 2026
**System Status:** ✅ Operational — Full Signal Pipeline Fixed + Score-Sorted Builder Live
**Next Review:** June 6, 2026 (Morning resolution + K9 rank validation)
