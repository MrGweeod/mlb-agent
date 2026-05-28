# MLB Parlay Agent — Build Status
**Last Updated:** May 28, 2026 (Session 2 — Team SO Signal + Anchor/Swing Architecture)

## Overall System Status: ✅ OPERATIONAL — SESSION 2 DEPLOYED
```
┌────────────────────────────────────────────────────────────────────┐
│                    SYSTEM HEALTH DASHBOARD                         │
├────────────────────────────────────────────────────────────────────┤
│ Scoring System:            ✅ PHASE 1 SIMPLE SCORER LIVE          │
│ Anchor/Swing Structure:    ✅ 3 ANCHORS + 2 SWINGS (5-LEG)       │
│ Coverage Gate 1:           ✅ coverage_overall >= 65% ENFORCED    │
│ Coverage Gate 2 (TB under):✅ 80% coverage_overall MINIMUM        │
│ Coverage Gate 2 (SO 5.5):  ✅ 72% coverage_overall MINIMUM        │
│ Consistency Signal:        ✅ LIVE (production + shadow)          │
│ Shadow Enriched Pipeline:  ✅ 4 SIGNALS FULLY OPERATIONAL         │
│ Signal 1 (Blended ERA):    ✅ ACTIVE                              │
│ Signal 2 (Opp Coverage):   ✅ ACTIVE                              │
│ Signal 3 (Ballpark Factor):✅ ACTIVE                              │
│ Signal 4 (Team SO Rank):   ✅ ACTIVE (deployed May 28)            │
│ Pitcher SO Line Filter:    ✅ MIN 4.5, UNDERS BLOCKED < 6.5      │
│ Juice Cap:                 ✅ ACTIVE (blocks odds < -300)         │
│ Player Diversity:          ✅ ACTIVE (max 1 per batch)            │
│ Database Logging:          ✅ STABLE (all tables persisting)      │
│ Training Data:             ✅ PRESERVED (94K+ rows)               │
│ Web UI:                    ✅ FUNCTIONAL (all tabs working)       │
│ Deployment:                ✅ LIVE (Railway auto-deploy)          │
│ 9AM Pipeline:              ✅ PRODUCING PARLAYS                   │
│ Next Validation:           📊 May 29 (fresh data post-cache)      │
└────────────────────────────────────────────────────────────────────┘
```

---

## Recent Deployments

### 🎯 **May 28, 2026: Signal 4 — Team SO Rank (Shadow Pipeline)**

**Files modified:**
- `src/apis/mlb_stats.py` — `get_team_strikeout_stats(season)` added
- `src/engine/enriched_scorer.py` — `_compute_team_so_adjustment()` added + neutral consistency bug fixed
- `src/pipelines/run_enriched_pipeline.py` — team SO stats fetched and wired into scorer
- Supabase: `team_so_adjustment numeric` column added to `mlb_scored_legs_enriched`

**Motivation:** Jack Flaherty SO under 6.5 — 70% season coverage, but facing LAA (league-leading K lineup). Accumulated 7 Ks in 5.2 IP. Scorer had zero awareness of opposing lineup K-proneness.

**How it works:**
- `get_team_strikeout_stats()` fetches season SO rank + 14-day recent rank for all 30 teams
- Season rank → primary adjustment: rank 1–8 = ±5, rank 9–15 = ±2, rank 16–22 = ∓2, rank 23–30 = ∓5
- Recent rank → modifier: rank 1–8 = +2, rank 23–30 = -2, else = 0
- Net capped at ±6
- Sign-flipped for unders (high-K lineup penalizes SO unders)
- Applies only to pitcher SO props — no effect on batter props

**Implementation note:** `lastXGames` API param `limit=N` filters team count (not game count). Used `byDateRange` with 14-day window instead — returns all 30 teams correctly.

**Test results:**
- LAA (rank 1 season): SO under adjustment = **-6.0**, SO over = **+6.0**
- Batter prop: **None** (correctly scoped)

**Also in this commit:** Fixed neutral consistency branch bug in `enriched_scorer.py` (`score += 1` → `score += 0` for neutral/consistent legs).

---

### 🔧 **May 28, 2026: Anchor/Swing Architecture + Scoring Fixes**

**Commits:** `9f49aa3`, `5ff62f6`, `0883f65`, `4747588`

**Anchor/Swing parlay structure:**
- Replaced 4-leg +700–+1000 with 3-anchor + 2-swing 5-leg +900–+1100
- Anchor: `coverage_overall >= 75%`, odds `-300 to -150`
- Swing: `coverage_overall >= 55%`, odds `-150 to +150`

**Consistency signal:**
- `gap = coverage_overall - coverage_recent_10`
- gap ≥ 20 → -6, gap ≥ 12 → -4, gap ≥ 6 → -2, gap ≤ -10 → +2, gap ≤ -5 → +1, else → 0
- Live in both `simple_scorer.py` and `enriched_scorer.py`

**Pitcher SO filters:**
- Minimum line raised from 3.5 → 4.5 (3.5 line: 47.8%/44.7% win rate)
- SO unders blocked below 6.5 line

**Data fix:** `get_scored_legs()` now partitions by `player_name, stat, direction` ordered by `logged_at DESC`

---

### 🔧 **May 27, 2026: Session 1 — Coverage Floor Fixes**

**Commit:** `9f49aa3` (rebased)

- Gate 1: `coverage_overall >= 65%` checked before any signal or adjustment
- Gate 2: 80% floor for `totalBases under 1.5` (7-day win rate was 50.4%)
- Gate 2: 72% floor for `strikeouts over 5.5` (cliff edge at 70% confirmed in data)
- Chronic bad actors eliminated: Mookie Betts, José Ramírez, Josh Naylor, Braxton Ashcraft

---

## Component Status

### **1. Production Scoring (simple_scorer.py)** ✅ LIVE

```python
score = base_coverage + adjustments
# base = coverage_vs_hand (preferred) or coverage_overall
# adjustments:
#   consistency: gap-based ±6/±4/±2/+2/+1/0
#   pitcher ERA: ±5 (note: opponent_adjustment returning 0 for 100% of legs — under review)
#   pitcher K/9: ±5 for SO props
#   lineup stability: -5 if < 50%
```

**Known issue:** ERA/pitcher adjustments are effectively dead (`opponent_adjustment = 0` for 100% of legs over 14 days). Not causing harm but adds noise. Cleanup deferred.

### **2. Shadow Enriched Scorer (enriched_scorer.py)** ✅ 4 SIGNALS ACTIVE

| Signal | Status | Description |
|--------|--------|-------------|
| Base (consistency) | ✅ | Same as production — gap-based ±6 to +1 |
| 1: Blended ERA rank | ✅ | Season ERA × 0.5 + last-3-start ERA × 0.5 |
| 2: Opponent coverage | ✅ | Batter hit rate vs tonight's opponent (min 3 games, ±8 cap) |
| 3: Ballpark factor | ✅ | 30-row static table, Coors 115 → Petco 94 |
| 4: Team SO rank | ✅ NEW | Opposing team K-proneness, pitcher SO props only, ±6 cap |

### **3. Coverage Gating (main.py)** ✅ TWO-GATE SYSTEM

| Gate | Threshold | Applies To |
|------|-----------|------------|
| Gate 1 | `coverage_overall >= 65%` | All legs — checked before any signal |
| Gate 2 | `coverage_overall >= 80%` | `totalBases under 1.5` only |
| Gate 2 | `coverage_overall >= 72%` | `strikeouts over 5.5` only |

### **4. Parlay Construction** ✅ ANCHOR/SWING

| Pool | Coverage Floor | Odds Range | Legs Per Parlay |
|------|---------------|------------|-----------------|
| Anchor | 75% overall | -300 to -150 | 3 |
| Swing | 55% overall | -150 to +150 | 2 |

- 5 legs total per parlay
- Target: +900 to +1100 combined odds
- Max 2 legs per game (correlation limit)
- Max 1 leg per player per batch

### **5. Prop Filtering** ✅ CURRENT

| Prop | Floor | 7-Day Win Rate | Status |
|---|---|---|---|
| `strikeouts under 5.5` | 65% overall | 85.7% | ✅ Prioritize |
| `hits under 0.5` | 65% overall | 71.1% | ✅ Keep |
| `strikeouts over 6.5` | 65% overall | 68.4% | ✅ Keep |
| `strikeouts under 4.5` | 65% overall | 63.0% | ✅ Keep |
| `hits over 0.5` | 65% overall | 60.0% | ✅ Keep |
| `strikeouts over 4.5` | 65% overall | 60.0% | ✅ Keep |
| `strikeouts over 0.5` | 65% overall | 57.6% | ✅ Monitor |
| `rbi under 0.5` | 65% overall | 58.3% | ✅ Monitor |
| `totalBases under 1.5` | **80% overall** | 50.4% → improving | ✅ Floor raised |
| `strikeouts over 5.5` | **72% overall** | 50.0% → improving | ✅ Floor raised |
| `pitcher SO under < 6.5` | — | ~45% | ❌ Blocked |
| `pitcher SO < 4.5 line` | — | 47.8% | ❌ Blocked |
| `hitter K under 0.5` | — | 36.7% | ❌ Blocked |
| Any prop < -300 | — | — | ❌ Blocked from parlays |

### **6. Shadow Pipeline Tables** ✅ FULLY WIRED

| Table | Signal Columns | Status |
|---|---|---|
| `mlb_parlay_recommendations_enriched` | production_batch_id | ✅ |
| `mlb_parlay_legs_enriched` | blended_era_rank, park_adjustment, coverage_vs_opponent | ✅ |
| `mlb_scored_legs_enriched` | coverage_vs_opponent, games_vs_opponent, park_factor, park_adjustment, blended_era_rank, recent_form_rank, **team_so_adjustment** | ✅ |
| `ballpark_factors` | 30 rows (static) | ✅ |

---

## Performance Metrics

### **Pre-Session 1 Baseline (May 22–25)**
- Parlay win rate: ~11%
- In-parlay leg win rate: 57.6%

### **Post-Session 1 Target**
- Improved per-leg win rate toward 63–65%
- Expected parlay win rate: ~16–18%
- Under evaluation — Sessions 1+2 changes live since May 27–28

### **Expected Post-Session 2 (June Analysis)**
- Team SO signal should eliminate SO under props vs top-K lineups from shadow parlays
- Anchor pool filtering should increase per-leg win rate in production

---

## Pending Code Changes

| Item | File | Priority | Session |
|---|---|---|---|
| Validate pitcher `coverage_recent_10` | — (query only) | High | Next morning |
| Validate consistency signal on pitchers | — (query only) | High | Next morning |
| Validate `team_so_adjustment` populating | — (query only) | High | Next pipeline |
| Gate 3 (min `coverage_recent_10` floor) | `main.py` | Medium | After validation |
| `won_with_void` outcome tracking | `parlay_outcome_resolver.py` | Medium | Claude Code |
| Dead ERA adjustment cleanup | `simple_scorer.py` | Low | Future session |
| Promote enriched to production | Multiple | After analysis | June |

---

**Build Status:** ✅ HEALTHY — Signal 4 Deployed, All Systems Operational
**Last Deployment:** May 28, 2026 (Team SO rank signal)
**Next Review:** May 29, 2026 (Post-9AM validation queries)
