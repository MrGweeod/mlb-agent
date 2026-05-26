# MLB Parlay Agent — Architecture Decisions
**Last Updated:** May 26, 2026 (Shadow Enriched Pipeline)

This document captures key architectural and design decisions made during development, along with reasoning and lessons learned.

---

## Table of Contents
1. [Core Philosophy](#core-philosophy)
2. [Scoring System Evolution](#scoring-system-evolution)
3. [Coverage Calculation](#coverage-calculation)
4. [Prop Type Filtering](#prop-type-filtering)
5. [Parlay Construction Strategy](#parlay-construction-strategy)
6. [Juice Cap Decision](#juice-cap-decision)
7. [Player Diversity Constraint](#player-diversity-constraint)
8. [Shadow Pipeline Strategy](#shadow-pipeline-strategy) ← **NEW**
9. [Enriched Scoring Signals](#enriched-scoring-signals) ← **NEW**
10. [Database Design](#database-design)
11. [Pipeline Architecture](#pipeline-architecture)
12. [Lessons Learned](#lessons-learned)
13. [Future Considerations](#future-considerations)

---

## Core Philosophy

### **Decision: Optimize for Hit Probability, Not Expected Value**

Parlays multiply probabilities — each leg's hit rate is paramount. A 75% coverage leg at -150 is better than a 65% leg at +120 for parlay construction.

**Validation:** ✅ May 20, 2026 — 69% accuracy on coverage-based leg selection confirmed.

---

## Scoring System Evolution

### **Phase 0: ML Model (April–May 2026) — ABANDONED**
GradientBoostingClassifier with 19 features. Direction feature absorbed 77% of importance. Score-outcome correlation was **inverted** — high scores (70–100) had 43.7% win rate, low scores (<55) had 55.1% win rate. Temporary adjustments (±26/±18) caused floor abuse (all unders → 5.0).

**Parlay win rate:** 7.6%

### **Phase 1: Simple Coverage-Based Scoring (May 20, 2026) — CURRENT PRODUCTION**

```python
score = base_coverage + contextual_adjustments
# base = coverage_vs_hand (preferred) or coverage_overall
# adjustments = handedness (+3) + form (±4) + pitcher ERA (±5) + K-rate (±5) + stability (-5)
```

**Parlay win rate:** ~11% (target 18–22%, gap under investigation)

### **Phase 2: Enriched Scoring (May 26, 2026) — SHADOW TESTING**

Three additional signals layered on top of Phase 1:
1. **Blended ERA rank** — season ERA × 0.5 + last-3-start ERA × 0.5
2. **Opponent coverage split** — batter's hit rate vs tonight's opponent (min 3 games)
3. **Ballpark factor** — park run/HR factor from `ballpark_factors` table

**Status:** Shadow pipeline collecting data. Production promotion after 5–7 day comparison analysis.

**Key design decision:** Run enriched scoring as a shadow pipeline for 5–7 days before promoting to production. This allows apples-to-apples comparison (same legs, same days, two scoring systems) without risking production stability.

---

## Coverage Calculation

### **Decision: Direction-Aware Coverage with Handedness Splits**

```python
# OVER props
coverage_pct = (games_over / total_games) * 100

# UNDER props
coverage_pct = (games_under / total_games) * 100
```

**The Bug (May 13–14):** Original code calculated OVER coverage for UNDER props. Fixed and backfilled all historical data.

**Validation (May 21):** 100% of props calculate coverage successfully, 80–100% pass ≥65% threshold.

---

## Prop Type Filtering

### **Decision: Block Unprofitable Prop Types**

| Prop | Win Rate | Status |
|---|---|---|
| Hits over | 69.4% | ✅ Allowed |
| Hits under | 71.9% | ✅ Allowed |
| Pitcher K over | 56.9% | ✅ Allowed |
| RBI under | 66.5% | ✅ Allowed (unblocked May 21) |
| Total Bases under | 75–80% | ✅ Allowed (unblocked May 21) |
| Hitter K under 0.5 | 36.7% | ❌ Blocked |
| Pitcher K under <5.5 | ~45% | ⚠️ Pending block |

### **Pitcher K Under Line Threshold — Pending Decision (May 26)**

Analysis of May 22–25 data showed pitcher K under losses concentrated at lines 4.5 and below:
- **Losers:** Ureña 4.5 (0/2), Gallen 4.5 (0/1), Gausman 6.5 (0/1), Taillon 4.5 (0/1), Houser 3.5 (0/1)
- **Winners:** McClanahan 5.5 (2/2), King 6.5 (2/2), Gray 5.5 (1/1), Sasaki 5.5 (1/1)

**Decision:** Add `line ≥ 5.5` minimum for pitcher K unders. Pending Claude Code implementation.

---

## Parlay Construction Strategy

### **Decision: +700 to +1000 Odds Range (Updated May 21)**

**Old range (+900–+1500):** Forced selection of plus-money props with lower win rates. Heavy juice props (best win rates) couldn't reach +900.

**New range (+700–+1000):** Allows using best props regardless of juice. Aligns strategy with data.

**Math:** 4 legs at 67% per-leg = 0.67^4 = **20.2% expected win rate** at +800 avg odds.

---

## Juice Cap Decision

### **Decision: Block Props with Odds < -300 from Parlays (May 21)**

12 RBI props at avg -386 odds were poisoning the pool — 4-leg combinations after using them couldn't reach +700.

**Impact:** Pool avg odds improved from -233 → -210, making +700–+1000 combinations achievable.

---

## Player Diversity Constraint

### **Decision: Maximum 1 Prop Per Player Per Parlay Batch**

Eliminates correlated wipeout risk. Resets between scheduled runs (9AM/12PM/5:30PM).

---

## Shadow Pipeline Strategy

### **Decision: Shadow Before Promoting (May 26)**

When introducing significant scoring changes, run as a shadow pipeline writing to separate tables before promoting to production.

**Rationale:**
- Current pipeline is stable and generating clean performance data
- New signals touch coverage, scorer, and enrichment simultaneously — meaningful surface area
- Shadow approach allows apples-to-apples comparison: same legs, same days, two scoring systems
- Production never at risk — try/except wrapper in `main.py` ensures enriched failures never block production

**Implementation:**
```python
# main.py — after production pipeline completes
try:
    from src.pipelines.run_enriched_pipeline import run_enriched_pipeline
    run_enriched_pipeline(qualifying_legs, production_batch_id=_prod_batch_id)
except Exception as _enr_err:
    print(f"[ENRICHED PIPELINE] Failed — production unaffected: {_enr_err}")
```

**Comparison framework:** `production_batch_id` on enriched tables links every enriched run to the exact production batch it shadowed, enabling precise side-by-side comparison.

**Promotion criteria:** After 5–7 days of shadow data, compare:
1. Leg selection differences (what does enriched pick that production doesn't?)
2. Win rates by pipeline (do enriched legs win more often?)
3. Parlay win rates (do enriched parlays win more often?)

---

## Enriched Scoring Signals

### **Signal 1: Blended ERA Rank**

**Problem with season ERA rank alone:** A pitcher with 3.20 ERA who's given up 14 runs in last 3 starts is completely different from his season line.

**Solution:** Blend season ERA rank (50%) with last-3-start ERA rank (50%).

```python
blended_era_rank = (era_rank * 0.5) + (recent_era_rank * 0.5)
```

Edge cases: fewer than 3 starts → use available starts; reliever (0 starts) → use season ERA only; zero IP → treat as ERA 9.0.

### **Signal 2: Opponent-Specific Coverage Split**

**Problem:** Generic coverage ("how often does this batter get a hit") ignores matchup-specific patterns.

**Solution:** Calculate batter's direction-aware hit rate vs tonight's specific opponent.

```python
coverage_vs_opponent = (games_over_vs_opponent / total_games_vs_opponent) * 100
delta = coverage_vs_opponent - coverage_overall
opp_adj = max(-8.0, min(8.0, delta * 0.25))  # 25% of delta, ±8 cap
```

**Minimum threshold:** 3 games vs that opponent required. Below threshold: NULL, no adjustment.

**Design decision:** 25% weight and ±8 cap prevent small samples from dominating. Signal supplements overall coverage rather than replacing it.

### **Signal 3: Ballpark Factor**

**Problem:** A TB under in Coors Field is a fundamentally different bet than the same prop at Petco Park.

**Solution:** One-time 30-row `ballpark_factors` table (Coors 115 → Petco 94 run factor). Applied per-leg based on home team.

```python
# Hitter props
park_adjustment = (run_factor - 100) / 100 * 5   # range: -3 to +7.5

# Pitcher props (inverted)
park_adjustment = (100 - run_factor) / 100 * 3   # smaller magnitude for K props
```

**Design decision:** Separate run_factor and hr_factor — home run props use hr_factor which has more variance (Yankee Stadium 112 vs Oracle Park 92).

---

## Database Design

### **Decision: Separate Production and Shadow Tables**

Production tables (`mlb_scored_legs`, `mlb_parlay_recommendations_v2`, `mlb_parlay_legs_v2`) are never touched by the shadow pipeline.

Shadow tables mirror production structure with additional enriched columns. Key addition: `production_batch_id` links every enriched run to its production counterpart.

### **Lesson: CREATE TABLE AS SELECT Doesn't Copy Sequences**

Shadow tables created with `CREATE TABLE AS SELECT` don't get auto-increment sequences or column defaults. Requires explicit:
```sql
CREATE SEQUENCE table_enriched_id_seq;
ALTER TABLE table_enriched ALTER COLUMN id SET DEFAULT nextval('table_enriched_id_seq');
ALTER TABLE table_enriched ALTER COLUMN created_at SET DEFAULT NOW();
```

---

## Pipeline Architecture

### **Decision: 3x Daily + Shadow After Every Run**

- **9:00 AM ET** — Resolution + fresh parlays (shadow runs after)
- **12:00 PM ET** — Midday refresh (shadow runs after)
- **5:30 PM ET** — Evening refresh (shadow runs after)
- **Manual Regenerate Now** — Also triggers shadow pipeline

Shadow pipeline adds ~2–3 seconds per run (negligible).

---

## Lessons Learned

1. **Trust the data, not the model** — Raw coverage (69% accuracy) outperformed complex ML model (43.7% on high scores)
2. **Direction matters for coverage** — Over and under must be calculated separately
3. **Selection bias from odds filters** — +900–+1500 forced low-win-rate props; +700–+1000 uses best coverage props
4. **Shadow before promoting** — Major scoring changes need A/B comparison, not blind promotion
5. **CREATE TABLE AS SELECT doesn't copy sequences** — Always create explicit sequences for shadow tables
6. **`production_batch_id` is the comparison key** — Without it, you can't match enriched runs to their production counterpart
7. **Void wins are not real wins** — 5/24 looked like a 4/9 day but 2 wins required voided legs to survive
8. **Pitcher K under is line-dependent** — 5.5+ is a different bet than 4.5 and below

---

## Future Considerations

### **1. Promote Enriched to Production (June 2026)**
After 5–7 days of shadow data confirms enriched scoring improves win rates.

### **2. `won_with_void` Outcome Tracking**
Distinguish clean 4/4 wins from 3/3 wins that needed a void to survive. Prevents inflating win rate metrics.

### **3. Pitcher K Under Line Threshold**
Block pitcher K unders below line 5.5 in `main.py`. Pending next Claude Code session.

### **4. Direction-Split Calibrators (Longer Term)**
If/when ML model is revisited, train 14 calibrators (7 stats × 2 directions) instead of 7.

### **5. Weather Integration**
Flag outdoor game total legs when wind > 15 mph out or temp < 45°F. Low priority — weather rarely decisive.

---

**Architecture Status:** ✅ STABLE — Phase 1 Production + Phase 2 Shadow Testing  
**Last Major Change:** May 26, 2026 (Shadow enriched pipeline fully operational)  
**Next Architecture Review:** June 2026 (After shadow comparison analysis)
