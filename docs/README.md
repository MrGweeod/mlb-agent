# MLB Parlay Agent 🤖⚾

**Last Updated:** June 12, 2026
**Status:** ✅ Operational — Lineup Confirmation + CLV Tracking Live | Correlation Stack Spec Ready
**Structure:** 4-leg parlays, +400 to +700 target
**Latest Output:** 2-5 parlays/day (thin slate: 2, full slate: 4-5)

An intelligent MLB parlay recommendation system that analyzes player performance data, calculates direction-aware coverage percentages, and builds optimized 4-leg parlays targeting +400 to +700 combined odds. An event-driven lineup confirmation layer annotates all scored legs with batting order and lineup status before first pitch. A CLV tracking layer captures closing odds for every scored leg to validate edge. A shadow enriched pipeline runs alongside production for A/B signal evaluation.

---

## 🎯 What It Does

1. **Fetches MLB Props** — Pulls 1,000+ player props daily from SportsGameOdds API
2. **Prop Whitelist** — Keeps only `hits over 0.5`, `hits under 0.5`, `strikeouts over 0.5` (hitter only)
3. **Coverage Gate** — 65% minimum `coverage_overall` for overs, 40% for unders; checked before scoring
4. **Odds Cap** — Blocks any leg priced worse than -250; max +150
5. **Calculates Coverage** — Direction-aware: "How often does this player go OVER/UNDER this line?"
6. **Attaches Pitcher Signals** — ERA rank, K9 rank, WHIP rank on all hitter legs (85.5% population rate)
7. **Scores with Multi-Signal Scorer** — Coverage + consistency + pitcher ranks + lineup stability + slot penalty
8. **Lineup Confirmation** — At T-45 per game group: annotates all legs with batting order slot and 4-state lineup status. Rebuilds parlays via CONFIRMED_LINEUP_RESOLUTION if a selected player is scratched.
9. **CLV Snapshot** — At T-1 per game group: captures closing odds from SGO for every scored leg.
10. **Shadow Scores** — Parallel enriched scorer with park factor, opponent coverage split, blended ERA rank, prop-specific pitcher routing
11. **Builds 4-Leg Parlays** — Single flat pool, score-sorted B&B search, +400 to +700 target
12. **Manual Regen Diversity** — Regenerate Now excludes prior-run players
13. **Logs Everything** — Production and shadow data to Supabase for tracking and analysis
14. **Resolves Outcomes** — Updates legs, parlays, and shadow tables with win/loss results each morning

---

## 📊 Performance (June 1–10 Clean Window)

| Prop | Legs | Win Rate | Avg Odds | Breakeven | Edge |
|---|---|---|---|---|---|
| **hits over 0.5** | 349 | 59.9% | -202 | 66.9% | **-7.0pp** ⚠️ |
| **SO over 0.5** (hitter) | 184 | 65.2% | -166 | 62.4% | **+2.8pp** ✅ |
| Parlay (4-leg) | 191 | 22.5% | +458 | 17.9% | **+4.6pp** |

**Note:** Hits/over edge is reassessed as negative on clean June data. SO/over is the confirmed edge prop. CLV tracking (started June 12) will provide a cleaner verdict within 2 weeks.

**Key diagnostic finding (June 12):** Same-game parlay pairs win at 20.0% vs 12.6% for distinct-game pairs. Positive correlation is net favorable — the offense stack bonus (shadow pipeline) is the next change targeting this.

---

## 🚀 Key Architecture

### **Single Flat Pool (June 1, 2026)**

| Parameter | Value |
|---|---|
| Coverage floor | 65% `coverage_overall` (overs), 40% (unders) |
| Odds range | -250 to +150 per leg |
| Legs per parlay | 4 |
| Target combined odds | +400 to +700 |
| Max legs per game | 2 |
| Player diversity (intra) | 1 player per parlay |
| Player diversity (manual regen) | Excludes prior-run players |

### **Event-Driven Lineup Confirmation (June 12, 2026)**

After the 9 AM pipeline logs the day's game start times, one lineup check is scheduled per start-time group at `game_start_time − 45 minutes`. A 1-minute drain cron polls the `mlb_pending_lineup_checks` table and fires checks as they come due.

**Four annotation states:**

| State | Meaning |
|---|---|
| `MISSING_LINEUP_CONFIRMATION` | Lineup not yet posted — no action |
| `LINEUP_CONFIRMED` | In lineup, favorable batting slot |
| `BATTING_ORDER_OUT_OF_RANGE` | In lineup, unfavorable slot — triggers resolution |
| `SCRATCHED` | Not in posted lineup — triggers resolution |

**CONFIRMED_LINEUP_RESOLUTION:** when a selected player is SCRATCHED or OUT_OF_RANGE, affected parlays are voided and rebuilt from upcoming-games-only legs. A scratched 7 PM player is never replaced by a 1 PM leg whose game has already started.

```
9 AM Pipeline
  └── log_slate_start_times()
  └── schedule_lineup_checks()  → mlb_pending_lineup_checks (check_type='lineup', T-45)
  └── schedule_clv_checks()     → mlb_pending_lineup_checks (check_type='clv', T-1)

1-minute drain cron
  └── drain_due_lineup_checks()
        ├── check_type='lineup' → run_lineup_check()  → annotate legs → CLR if needed
        └── check_type='clv'   → run_clv_snapshot()  → capture closing_odds
```

### **CLV Tracking (June 12, 2026)**

At `game_start_time − 1 minute`, the CLV worker re-fetches current SGO odds for all scored legs in the game group and writes `closing_odds` to `mlb_scored_legs`. CLV is then computable at query time:

```sql
-- Positive avg_clv_pct = beating the close = real edge
implied(closing_odds) − implied(selection_odds)
```

Expected: SO/over positive CLV, hits/over near zero. First meaningful read ~June 26.

### **Batting Order Slot Gate (Soft, June 12, 2026)**

When a player's `batting_order` is confirmed unfavorable for the bet type, a −8 point scoring penalty is applied. Unfavorable slot does not hard-exclude — absence of data never penalizes. Ranges are tunable hypotheses:

```python
BATTING_ORDER_FAVORABLE = {
    ("hits",       "over"):  range(1, 6),   # slots 1-5
    ("strikeouts", "over"):  range(1, 7),   # slots 1-6
    ("totalBases", "under"): range(1, 10),  # all slots
    ("hits",       "under"): range(1, 10),  # all slots
}
```

**Note:** Backtest showed slots 6-9 outperformed slots 1-5 on current sample — hypothesis unconfirmed. Keep annotation, monitor outcomes before adjusting ranges.

### **Score-Sorted Parlay Builder**

Pool sorted by `composite_score` DESC before branch-and-bound search. `MAX_CANDIDATES = 50`. B&B pruning via `suffix_dec_sorted`.

### **Shadow Enriched Pipeline (3 Signals Active + Stack Bonus Pending)**

| Signal | Status |
|---|---|
| Blended ERA Rank | Computed, not applied — pending revalidation |
| Opponent-Specific Coverage | Active (~20-35% population early season) |
| Ballpark Factor | Active — validated 30pp spread |
| Prop-Specific Pitcher Routing | Active — WHIP→TB, K9→SO, ERA+K9+WHIP→hits |
| Offense Stack Bonus | Specced — not yet built |

### **Backtest Findings (June 12)**

Backtest harness (`scripts/run_backtest.py`) tested EV-sort and slot gate on clean 533-leg June 1-10 production pool.

| Variant | Leg Δ | Parlay Δ | Parlays Built | Verdict |
|---|---|---|---|---|
| EV-sort | +0.0pp | -6.2pp | 49 vs 191 | **Discard** |
| Slot gate | -0.0pp | -9.7pp | 47 vs 191 | **Discard** |
| Combined | -0.1pp | -8.6pp | 43 vs 191 | **Discard** |

Root cause: pool-thinning. Both changes are revisited after pool expands (TB under promotion or new prop type).

---

## 🗄️ Database Tables

| Table | Purpose |
|---|---|
| `mlb_scored_legs` | Daily production legs — coverage, pitcher signals, batting_order, lineup_check_status, closing_odds |
| `mlb_parlay_recommendations_v2` | Production parlays — includes superseded_by_batch_id for CLR tracking |
| `mlb_parlay_legs_v2` | Production parlay legs — batting_order, lineup_check_status |
| `mlb_pending_lineup_checks` | Persisted scheduler — lineup (T-45) and CLV (T-1) checks |
| `mlb_training_data` | Historical resolved legs (94K+ rows) |
| `mlb_scored_legs_enriched` | Shadow scored legs + enriched signals |
| `mlb_parlay_recommendations_enriched` | Shadow parlays |
| `mlb_parlay_legs_enriched` | Shadow parlay legs |
| `ballpark_factors` | Park run/HR factors (30 rows, static) |

**Critical type notes:**
- `mlb_scored_legs.run_date`: TEXT — string comparisons
- `mlb_scored_legs.odds`, `closing_odds`: TEXT — cast `::numeric` for math
- `mlb_parlay_recommendations_v2.run_date`: DATE — no cast needed
- `mlb_training_data.result`: `'hit'/'miss'/'void'` — different from `'won'/'lost'`
- Never `ROUND()` — use `::numeric(p,s)`

---

## 🛠️ Tech Stack

- **Language:** Python 3.10
- **Framework:** Flask / aiohttp (Web UI + API)
- **Database:** Supabase (PostgreSQL)
- **Hosting:** Railway (auto-deploy from GitHub)
- **Data Sources:** SportsGameOdds API, MLB Stats API
- **Scheduler:** APScheduler (3× daily) + async drain cron (1-min, event-driven)

---

## 📁 Project Structure

```
mlb-agent/
├── src/
│   ├── engine/
│   │   ├── simple_scorer.py          # Production scorer (slot gate penalty added)
│   │   ├── enriched_scorer.py        # Shadow scorer (4 signals)
│   │   ├── coverage.py               # Direction-aware coverage calculation
│   │   ├── parlay_builder.py         # Score-sorted 4-leg parlay builder
│   │   └── resolver.py               # Outcome resolution
│   ├── apis/
│   │   ├── mlb_stats.py              # MLB Stats API wrapper
│   │   ├── pitcher_stats.py          # Pitcher ERA/K9/WHIP ranks (192 qualified)
│   │   ├── team_stats.py             # Team offensive ranks
│   │   ├── lineup_confirmation.py    # Lineup annotation + CLR + drain dispatcher [NEW]
│   │   └── clv_tracker.py            # CLV closing odds snapshot worker [NEW]
│   ├── pipelines/
│   │   ├── run_enriched_pipeline.py  # Shadow pipeline
│   │   ├── lineup_scheduler.py       # Game-group scheduler [NEW]
│   │   ├── enrich_legs.py            # Pitcher matchup enrichment
│   │   └── trend_analysis.py         # Trend/consistency signals
│   ├── tracker/
│   │   ├── parlay_outcome_resolver.py # Resolution (prod + shadow)
│   │   └── outcome_resolver.py        # Leg resolution
│   ├── web/
│   │   ├── server.py                 # Flask/aiohttp web server + drain cron
│   │   └── static/                   # Web UI
│   └── utils/
│       └── db.py                     # Supabase connection
├── scripts/
│   ├── backfill_batting_order.py     # June 1-10 slot backfill [NEW]
│   ├── run_backtest.py               # Backtest harness (read-only) [NEW]
│   ├── backfill_shadow_resolution.py
│   └── sync_parlay_leg_outcomes.py
├── sql/
│   ├── lineup_confirmation_migration.sql  # [NEW — APPLIED]
│   ├── clv_tracking_migration.sql         # [NEW — APPLIED]
│   └── stack_bonus_migration.sql          # [PENDING — not yet built]
├── reports/
│   └── backtest_june1_10_v2.txt      # Clean-pool backtest results [NEW]
├── verify_lineup_layer.py            # Lineup layer verification [NEW]
├── verify_clv.py                     # CLV layer verification [NEW]
├── main.py                           # Pipeline orchestrator
├── bot.py                            # Discord bot
├── requirements.txt
└── Dockerfile
```

---

## 🚦 System Status

### **✅ Working Well**
- Event-driven lineup confirmation (all 5 phases built, 19/19 spot-check verified)
- CLV tracking (built, migrated, verified — clock started June 12)
- Database-backed scheduler (restart-safe, stateless drain)
- Batting order backfill (881/1031, 85.5%)
- Backtest harness (built — correctly discarded EV-sort and slot gate on clean data)
- SGO CLV reuse (get_player_props() verbatim import, natural-key match confirmed)
- Full pitcher signal pipeline (192 qualified starters, 85.5% rank population)
- K9 rank signal for batter SO props
- WHIP rank signal for hits props
- Score-sorted parlay builder with MAX_CANDIDATES 50
- Manual regen player exclusion
- Direction-aware coverage calculation
- Consistency signal
- Park factor signal (validated — 30pp spread)
- Shadow enriched pipeline (4 signals, resolution wired)
- Player diversity constraint
- Pipeline scheduler (3× daily + event-driven)
- Morning resolution correct

### **📊 Under Evaluation**
- CLV capture rate — first live slate pending
- Lineup annotation mix — first live slate T-45 posting time unvalidated
- Shadow vs production comparison (offense stack bonus pending build)
- TB under WHIP signal (~June 26 first read)

### **⚠️ Known Issues / Pending**
- 85%+ coverage ceiling not implemented (trap confirmed)
- Offense stack bonus spec ready but not yet built
- No lineup confirmation observed live yet (LINEUP_CHECK_SECOND_PASS available if needed)
- Hits/over at or below breakeven on clean data — reassess after CLV
- verify_common.py refactor pending
- Negative EV legs still possible (CLV will identify which legs to address)

---

## 🔄 Recent Changes

### **June 12, 2026: Lineup Confirmation Layer + CLV Tracking + Backtest**
- Full event-driven lineup confirmation layer (5 phases)
- CLV tracking layer reusing lineup scheduler with check_type discriminator
- Batting order backfill 881/1031 June 1-10 legs
- Backtest harness: EV-sort and slot gate both discard on clean 533-leg pool
- Correlation restructure spec written — offense stack bonus ready for Claude Code
- verify_lineup_layer.py: 9/9 migration + 19/19 spot-check
- verify_clv.py: 10/10 (2 skipped expected)

### **June 9, 2026 (Session 9): Training Data Gaps + TB Under + Bug Fixes**
See SESSION_HANDOFF.md for full detail.

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

-- CLV by stat/direction (run ~June 26 for first meaningful read)
SELECT stat, direction,
    COUNT(*) FILTER (WHERE closing_odds IS NOT NULL) AS captured,
    (AVG(
        CASE WHEN closing_odds IS NULL OR odds IS NULL THEN NULL
        ELSE
            (CASE WHEN closing_odds::numeric < 0
                  THEN ABS(closing_odds::numeric)/(ABS(closing_odds::numeric)+100)
                  ELSE 100/(closing_odds::numeric+100) END)
          - (CASE WHEN odds::numeric < 0
                  THEN ABS(odds::numeric)/(ABS(odds::numeric)+100)
                  ELSE 100/(odds::numeric+100) END)
        END
    ) * 100)::numeric(5,2) AS avg_clv_pct
FROM mlb_scored_legs
WHERE run_date >= '2026-06-12'
  AND closing_odds IS NOT NULL
GROUP BY stat, direction ORDER BY avg_clv_pct DESC;

-- Lineup annotation mix (run after T-45 checks fire)
SELECT lineup_check_status, COUNT(*)
FROM mlb_scored_legs WHERE run_date = (CURRENT_DATE)::text
GROUP BY lineup_check_status;

-- Shadow vs production comparison
SELECT 'production' as pipeline,
    COUNT(*) FILTER (WHERE outcome = 'won') as won,
    COUNT(*) FILTER (WHERE outcome IN ('won','lost')) as resolved,
    (COUNT(*) FILTER (WHERE outcome = 'won') * 100.0 /
     NULLIF(COUNT(*) FILTER (WHERE outcome IN ('won','lost')), 0))::numeric(5,1) as win_rate
FROM mlb_parlay_recommendations_v2 WHERE run_date >= '2026-06-12'
UNION ALL
SELECT 'shadow' as pipeline,
    COUNT(*) FILTER (WHERE outcome = 'won') as won,
    COUNT(*) FILTER (WHERE outcome IN ('won','lost')) as resolved,
    (COUNT(*) FILTER (WHERE outcome = 'won') * 100.0 /
     NULLIF(COUNT(*) FILTER (WHERE outcome IN ('won','lost')), 0))::numeric(5,1) as win_rate
FROM mlb_parlay_recommendations_enriched WHERE run_date >= '2026-06-12';
```

---

**Last Updated:** June 12, 2026
**System Status:** ✅ Operational — Lineup + CLV Layers Live | Correlation Spec Ready
**Next Review:** June 13, 2026 (First live CLV capture + lineup annotation mix)
**Pending Decisions:** Offense stack build (next session), TB under promotion (late June), hits/over reassessment (after CLV)
