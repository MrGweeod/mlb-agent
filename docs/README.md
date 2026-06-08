# MLB Parlay Agent 🤖⚾

**Last Updated:** June 8, 2026
**Status:** ✅ Operational — Manual Regen Diversity + Full Signal Pipeline
**Structure:** 4-leg parlays, +400 to +700 target
**Latest Output:** 2-5 parlays/day (thin slate: 2, full slate: 4-5)

An intelligent MLB parlay recommendation system that analyzes player performance data, calculates direction-aware coverage percentages, and builds optimized 4-leg parlays targeting +400 to +700 combined odds. A shadow enriched pipeline runs alongside production to evaluate additional scoring signals before promotion. Manual regeneration now excludes players from the prior run to deliver genuinely fresh picks.

---

## 🎯 What It Does

1. **Fetches MLB Props** — Pulls 1,000+ player props daily from SportsGameOdds API
2. **Prop Whitelist** — Keeps only `hits over 0.5`, `hits under 0.5`, `strikeouts over 0.5` (hitter only)
3. **Coverage Gate** — 65% minimum `coverage_overall` (70% for hits under); checked before scoring
4. **Odds Cap** — Blocks any leg priced worse than -250; max +150
5. **Calculates Coverage** — Direction-aware: "How often does this player go OVER/UNDER this line?"
6. **Attaches Pitcher Signals** — Opposing pitcher ERA rank, K9 rank, WHIP rank on all hitter legs
7. **Scores with Multi-Signal Scorer** — Coverage + consistency + K9 rank + ERA + lineup stability
8. **Shadow Scores** — Parallel enriched scorer with park factor, opponent coverage split, blended ERA rank
9. **Builds 4-Leg Parlays** — Single flat pool, score-sorted B&B search, +400 to +700 target
10. **Manual Regen Diversity** — Regenerate Now excludes prior-run players; auto runs use full pool
11. **Logs Everything** — Production and shadow data to Supabase for tracking and analysis
12. **Resolves Outcomes** — Updates legs, parlays, and shadow table with win/loss results each morning

---

## 📊 Why These Props

Based on 60-day analysis across 90,000+ resolved leg outcomes:

| Prop | Win Rate at 65%+ Coverage | Avg Odds | Edge Above Breakeven |
|---|---|---|---|
| **hits over 0.5** | 67.2% | -214 | +6pp at 75%+ coverage |
| **SO over 0.5** (hitter) | 69.0% | -199 | **+7pp** |
| **hits under 0.5** | 66.7% | -127 | **+10.7pp** |

Coverage IS predictive for hits over and SO over. For everything else (totalBases under, rbi under, pitcher SO), the signal is flat or the book has priced it away.

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
| Player diversity (intra) | 1 player per parlay |
| Player diversity (manual regen) | Excludes prior-run players |

### **Score-Sorted Parlay Builder (June 5, 2026)**

Pool sorted by `composite_score` DESC before branch-and-bound search. Highest-quality legs explored first. `MAX_CANDIDATES = 50` ensures meaningful pool exploration. B&B pruning via `suffix_dec_sorted` valid under any sort order.

### **Manual Regen Player Exclusion (June 8, 2026)**

When you hit **Regenerate Now**, the pipeline queries the most recent batch's players and removes them from the eligible pool before building parlays. This ensures each press of Regenerate returns a genuinely different set of picks.

```
Press Regenerate (run 1) → full pool → picks players A, B, C, D, E
Press Regenerate (run 2) → excludes A, B, C, D, E → picks from remaining pool
Press Regenerate (run 3) → excludes run 2's players → picks from remaining pool
```

Fallback: if fewer than 4 legs remain after exclusion, the full pool is used (logged as `[manual_regen] Pool too thin`).

Automated pipeline runs (9am, 12pm, 5:30pm) are unaffected — they always use the full eligible pool.

---

### **Pitcher Signal Pipeline (June 5, 2026)**

All hitter legs receive opposing pitcher rank signals:

```
get_pitcher_ranks(season)           → 192 qualified starters (3+ starts, 3.0+ IP/start)
    ↓
_attach_pitcher_rank_signals()      → attaches opp_pitcher_era_rank, opp_pitcher_k9_rank,
                                      opp_pitcher_whip_rank to ALL hitter legs
    ↓
simple_scorer.calculate_score()     → uses opp_pitcher_k9_rank for SO props (±5)
                                      uses pitcher_era for hits props (±5)
```

**Previously broken (fixed June 5):**
- Batter strikeout legs classified as pitcher props due to `stat in _PITCHER_STATS` → NULL pitcher data
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
`coverage_vs_hand` = delta adjustment at 30% weight, capped ±3 points.

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

Runs after every production pipeline. Writes to separate shadow tables for A/B comparison. Resolution wired — shadow outcomes updated after every morning resolution.

**Signal 1 — Blended ERA Rank:** Season ERA rank × 0.5 + last-3-start ERA rank × 0.5. Computed and stored. NOT applied to score pending revalidation after pitcher IP fix.

**Signal 2 — Opponent-Specific Coverage:** Batter's hit rate vs tonight's specific opponent (min 3 games, 25% delta, ±8 cap). ~20-35% population rate early season.

**Signal 3 — Ballpark Factor:** 30-row `ballpark_factors` static table. Validated: 30-point win rate spread between pitcher parks (40%) and hitter parks (70%). Strongest validated enriched signal.

---

### **Daily Pipeline (3× per day)**
- **9 AM ET:** Resolution + fetch/score/build (shadow runs after)
- **12 PM ET:** Fresh props refresh (shadow runs after)
- **5:30 PM ET:** Final refresh before games (shadow runs after)
- **Manual Regenerate:** Excludes prior-run players; shadow runs after

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
- Manual regen player exclusion with fallback
- Full pitcher signal pipeline (IP fix + Bug 1 fix + rank attachment to hitter legs)
- K9 rank signal for batter strikeout props
- Score-sorted parlay builder with MAX_CANDIDATES 50
- Single flat pool parlay construction
- Validated prop whitelist (hits over/under 0.5, SO over 0.5 hitter)
- -250 odds cap
- Direction-aware coverage calculation
- Consistency signal
- Park factor signal (validated — 30pp spread)
- Shadow enriched pipeline (3 signals, resolution wired)
- Player diversity constraint (intra-parlay)
- Pipeline scheduler (3× daily)
- Morning resolution correct for both prod and shadow

### **📊 Under Evaluation**
- ERA rank signal for hits props (7+ days clean data post IP-fix)
- K9 rank signal for SO props (first clean measurement post Bug 1 fix)
- Shadow vs production comparison (target June 12+)
- Manual regen fallback threshold (monitor `[manual_regen] Pool too thin` logs)

### **⚠️ Known Issues / Pending**
- ~60% of SO legs missing pitcher enrichment (NaN pitcher_name)
- No lineup confirmation gate — Volpe-style voids still possible
- `hits under 0.5`: 0 legs in recent pools — investigate coverage gate
- Health check hit rate threshold stale (flags 65%+ as anomalous)
- Negative EV legs appearing in parlays (selection by score, not EV)
- `won_with_void` outcome not tracked separately
- Raw `pitcher_era` adjustment in `simple_scorer.py` pending revalidation

---

## 🔄 Recent Changes

### **June 8, 2026: Manual Regen Player Exclusion** (`cd52b3a`)
- `run_pipeline()` in `main.py`: when `source == "manual"`, queries most recent batch's player names and filters them from `qualifying_legs` before `build_parlays()`
- Fallback: full pool used if fewer than 4 legs remain after exclusion
- Automated pipeline runs unaffected

### **June 5, 2026: Opposing Pitcher Ranks → Hitter Legs + K9 Rank in Scorer** (`e67896e`)
- `_attach_pitcher_rank_signals()` attaches `opp_pitcher_era_rank`, `opp_pitcher_k9_rank`, `opp_pitcher_whip_rank` to all hitter legs
- `simple_scorer.py` batter SO props use `opp_pitcher_k9_rank` (±5)

### **June 5, 2026: Full Signal Pipeline + Parlay Builder Corrections** (`1ab63c2`)
- Pitcher IP threshold: 50 IP → per-start (3+ starts, 3.0 IP/start) — pool 20-25 → 192
- Bug 1: batter SO legs now fully enriched
- Enriched scorer: base signal standardized, +3 bonus removed, ERA removed, K9 rank added
- Parlay builder: score-sort + MAX_CANDIDATES 50 + suffix_dec_sorted pruning fix

### **June 5, 2026: Shadow Resolution Backfill**
- 1,240 rows backfilled via bulk SQL UPDATE
- Morning resolver now writes to `mlb_scored_legs_enriched` ongoing

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

-- SO enrichment rate (how many legs have pitcher data)
SELECT
    COUNT(*) as total_so_legs,
    COUNT(pitcher_name) as with_pitcher,
    (COUNT(pitcher_name) * 100.0 / COUNT(*))::numeric(5,1) as pct_enriched
FROM mlb_scored_legs
WHERE run_date = (CURRENT_DATE)::text
  AND stat = 'strikeouts' AND line = 0.5
  AND position NOT IN ('SP','RP','P');

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

-- Manual regen exclusion working?
-- Check Railway logs for: [manual_regen] Excluding N players from last run
-- Check Railway logs for: [manual_regen] Pool too thin (fallback fired)
```

---

**Last Updated:** June 8, 2026
**System Status:** ✅ Operational — Manual Regen Diversity + Full Signal Pipeline
**Next Review:** June 9, 2026 (Monitor exclusion logs + SO enrichment rates)
