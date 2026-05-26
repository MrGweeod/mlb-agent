# MLB Parlay Agent — Build Status
**Last Updated:** May 26, 2026 (Shadow Enriched Pipeline Operational)

## Overall System Status: ✅ OPERATIONAL — SHADOW PIPELINE ACTIVE
```
┌────────────────────────────────────────────────────────────────┐
│                  SYSTEM HEALTH DASHBOARD                       │
├────────────────────────────────────────────────────────────────┤
│ Scoring System:          ✅ PHASE 1 SIMPLE SCORER LIVE        │
│ Shadow Enriched Pipeline:✅ FULLY OPERATIONAL                 │
│ Enriched Data Integrity: ✅ IDs, timestamps, links all valid  │
│ Prop Filtering:          ✅ BLOCKING UNPROFITABLE PROPS       │
│ Coverage Calculation:    ✅ VALIDATED (80-100% pass rate)     │
│ Parlay Odds Range:       ✅ +700 TO +1000                     │
│ Juice Cap:               ✅ ACTIVE (blocks odds < -300)       │
│ RBI Props:               ✅ UNBLOCKED (523 available)         │
│ Player Diversity:        ✅ ACTIVE (max 1 per batch)          │
│ Database Logging:        ✅ STABLE (all data persisting)      │
│ Training Data:           ✅ PRESERVED (94K+ rows)             │
│ Web UI:                  ✅ FUNCTIONAL (all tabs working)     │
│ Deployment:              ✅ LIVE (Railway auto-deploy)        │
│ 9AM Pipeline:            ✅ PRODUCING PARLAYS (fixed)         │
│ Next Review:             📊 June 1-2 (shadow comparison)      │
└────────────────────────────────────────────────────────────────┘
```

---

## Recent Deployments

### 🔬 **May 26, 2026: Shadow Enriched Pipeline — Full Data Integrity Fix**

**Problem:** Shadow pipeline was saving parlays but legs had `parlay_id = NULL`, `id = NULL`, and `created_at = NULL`, making comparison analysis impossible.

**Root cause:** `CREATE TABLE AS SELECT` copies column structure but not sequences or defaults. Enriched tables had no auto-increment on `id`, so `RETURNING id` returned NULL, which cascaded to `parlay_id = NULL` on all legs.

**Fixes applied:**
1. Created dedicated sequences: `mlb_parlay_recommendations_enriched_id_seq`, `mlb_parlay_legs_enriched_id_seq`
2. Set `created_at DEFAULT NOW()` on both enriched tables
3. Added `production_batch_id TEXT` column to `mlb_parlay_recommendations_enriched`
4. Threaded `production_batch_id` through `main.py` → `run_enriched_pipeline()` → `_save_enriched_parlays()`
5. Captured return value of `save_parlay_recommendations_v2()` in `main.py` as `_prod_batch_id`

**Verified working:**
```
p.id=1, batch_id=2026-05-26_19:37:19, created_at=2026-05-26 19:37:19, 
production_batch_id=2026-05-26_19:37:19, parlay_id=1, player_name=Chase Burns
```

**Status:** ✅ All 4 critical columns non-null. Shadow pipeline fully operational.

---

### 🔬 **May 26, 2026: Shadow Enriched Pipeline — Initial Build**

**Commits:** `a0c7219`

**New files:**
- `src/engine/enriched_scorer.py` — three signals on top of simple_scorer.py
- `src/pipelines/run_enriched_pipeline.py` — shadow pipeline writing to enriched tables

**New Supabase tables:**
- `ballpark_factors` — 30 rows, run/HR factors per MLB park
- `mlb_scored_legs_enriched` — mirrors production + 6 enriched columns
- `mlb_parlay_recommendations_enriched` — mirrors production + `production_batch_id`
- `mlb_parlay_legs_enriched` — mirrors production + 6 enriched columns

**Three enriched signals:**
1. **Blended ERA rank** — season ERA rank × 0.5 + last-3-start ERA rank × 0.5
2. **Opponent-specific coverage** — batter hit rate vs tonight's opponent (min 3 games, 25% delta, ±8 cap)
3. **Ballpark factor** — park run/HR factor from `ballpark_factors` table

**Status:** ✅ Collecting shadow data every pipeline run

---

### 🎯 **May 21, 2026: Parlay Strategy Optimization**
- Lowered parlay odds to +700–+1000 (from +900–+1500)
- Added juice cap (blocks odds < -300)
- Unblocked RBI props (66.5% win rate)
- Unblocked Total Bases under (80% win rate post-May-15)

---

### 🎉 **May 20, 2026: Phase 1 Simple Scorer**
- Replaced ML model with coverage-based scoring
- Blocked hitter K under 0.5 (36.7% win rate)
- Validated 69% accuracy on 7,895 resolved legs

---

## Component Status

### **1. Production Scoring System** ✅ PHASE 1 LIVE

```python
score = base_coverage + adjustments
# base_coverage = coverage_vs_hand (preferred) or coverage_overall
# adjustments = handedness (+3) + form (±4) + pitcher (±5) + K-rate (±5) + stability (-5)
```

### **2. Shadow Enriched Scorer** ✅ OPERATIONAL

```python
score = base_score (mirrors simple_scorer)
      + blended ERA rank adjustment (±5)      # Signal 1
      + opponent coverage delta × 0.25 (±8)   # Signal 2
      + park factor adjustment (±3 to ±7.5)   # Signal 3
```

**Enriched avg score vs production:** 71.2 vs 73.7 — enriched is applying downward pressure on some legs, which may indicate tighter quality filtering.

### **3. Coverage Calculation** ✅ VALIDATED
- Direction-aware (over/under calculated separately)
- Handedness splits (72% of props have split data)
- 65% minimum threshold
- 80–100% pass rate across all stat types

### **4. Prop Filtering** ✅ OPTIMIZED

| Prop | Status | Win Rate |
|---|---|---|
| Hits over/under | ✅ Allowed | 69–72% |
| Pitcher K over | ✅ Allowed | 57% |
| Pitcher K under ≥5.5 | ✅ Allowed | ~65%+ |
| RBI under | ✅ Allowed | 66.5% |
| Total Bases under | ✅ Allowed | 75–80% |
| Hitter K under 0.5 | ❌ Blocked | 36.7% |
| Pitcher K under <5.5 | ⚠️ Pending block | ~45% |
| Extreme juice (<-300) | ❌ Blocked from parlays | — |

**Pending:** Pitcher K under line threshold (≥5.5 minimum) — next Claude Code session.

### **5. Parlay Builder** ✅ OPTIMIZED
- 4 legs per parlay
- +700 to +1000 combined odds
- Juice cap: props < -300 excluded
- Max 2 legs per game
- Max 1 leg per player per batch

### **6. Shadow Pipeline Tables** ✅ FULLY WIRED

| Table | Rows Today | ID Sequence | created_at | production_batch_id |
|---|---|---|---|---|
| mlb_parlay_recommendations_enriched | 3 | ✅ | ✅ | ✅ |
| mlb_parlay_legs_enriched | 12 | ✅ | ✅ | ✅ (via parlay join) |
| mlb_scored_legs_enriched | 62 | — | ✅ | — |
| ballpark_factors | 30 (static) | — | — | — |

### **7. Pipeline Scheduler** ✅ RELIABLE
- 9:00 AM ET — Morning (resolution + fresh parlays) ✅ NOW PRODUCING PARLAYS
- 12:00 PM ET — Midday refresh
- 5:30 PM ET — Evening refresh

### **8. Database Logging** ✅ STABLE

| Table | Purpose | Status |
|---|---|---|
| mlb_scored_legs | Daily production legs | ✅ Active |
| mlb_parlay_recommendations_v2 | Production parlays | ✅ Active |
| mlb_parlay_legs_v2 | Production legs per parlay | ✅ Active |
| mlb_training_data | Historical (94K+ rows) | ✅ Active |
| mlb_scored_legs_enriched | Shadow scored legs | ✅ Active |
| mlb_parlay_recommendations_enriched | Shadow parlays | ✅ Active |
| mlb_parlay_legs_enriched | Shadow legs per parlay | ✅ Active |
| ballpark_factors | Park run/HR factors | ✅ Static |

---

## Performance Metrics

### **May 22–25 Results (Post-Strategy-Change)**

| Metric | Value | Target |
|---|---|---|
| Parlay win rate | ~11% | 18–22% |
| Weighted avg leg win rate | ~63.6% | 67%+ |
| Total Bases under win rate | 75.0% | ✅ |
| Hits over win rate | 71.4% | ✅ |
| Hits under win rate | 69.0% | ✅ |
| Strikeouts over win rate | 56.9% | ⚠️ |
| Strikeouts under win rate | 53.7% | ❌ |
| Juice cap violations | 0 | ✅ |

### **Gap Analysis**
- Expected parlay win rate (63.6% per leg, 4 legs): 16.3%
- Actual: ~11%
- Delta likely explained by same-game correlation on 2-leg-per-game parlays

---

## Pending Code Changes

| Item | File | Priority | Type |
|---|---|---|---|
| Pitcher K under line ≥5.5 | `main.py` | High | Claude Code |
| `won_with_void` outcome tracking | `parlay_outcome_resolver.py` | Medium | Claude Code |
| Promote enriched to production | Multiple | After analysis | Claude Code |

---

**Build Status:** ✅ HEALTHY — Shadow Pipeline Collecting Data  
**Last Deployment:** May 26, 2026  
**Next Review:** June 1–2, 2026 (Shadow Pipeline Comparison Analysis)
