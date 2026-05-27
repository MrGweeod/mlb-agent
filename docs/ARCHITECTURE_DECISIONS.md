# MLB Parlay Agent — Architecture Decisions
**Last Updated:** May 27, 2026 (Session 1 — Coverage Floor Fixes)

This document captures key architectural and design decisions made during development, along with reasoning and lessons learned.

---

## Table of Contents
1. [Core Philosophy](#core-philosophy)
2. [Scoring System Evolution](#scoring-system-evolution)
3. [Coverage Gating Architecture](#coverage-gating-architecture) ← **UPDATED**
4. [Prop-Specific Coverage Floors](#prop-specific-coverage-floors) ← **NEW**
5. [Coverage Calculation](#coverage-calculation)
6. [Prop Type Filtering](#prop-type-filtering)
7. [Parlay Construction Strategy](#parlay-construction-strategy)
8. [Juice Cap Decision](#juice-cap-decision)
9. [Player Diversity Constraint](#player-diversity-constraint)
10. [Shadow Pipeline Strategy](#shadow-pipeline-strategy)
11. [Enriched Scoring Signals](#enriched-scoring-signals)
12. [Database Design](#database-design)
13. [Pipeline Architecture](#pipeline-architecture)
14. [Lessons Learned](#lessons-learned)
15. [Future Considerations](#future-considerations)

---

## Core Philosophy

### **Decision: Optimize for Hit Probability, Not Expected Value**

Parlays multiply probabilities — each leg's hit rate is paramount. A 75% coverage leg at -150 is better than a 65% leg at +120 for parlay construction.

**Validation:** ✅ May 20, 2026 — 69% accuracy on coverage-based leg selection confirmed.

---

## Scoring System Evolution

### **Phase 0: ML Model (April–May 2026) — ABANDONED**
GradientBoostingClassifier, 77K samples, direction feature at 77% importance. Score-outcome correlation was **inverted** — high scores had lower win rates. Parlay win rate: 7.6%.

### **Phase 1: Simple Coverage-Based Scoring (May 20, 2026) — CURRENT PRODUCTION**

```python
score = base_coverage + contextual_adjustments
# base = coverage_vs_hand (preferred) or coverage_overall
# adjustments = handedness (+3) + form (±4) + pitcher ERA (±5) + K-rate (±5) + stability (-5)
```

**Parlay win rate:** ~11% (target 18–22%)

**Known issue:** Lost parlay legs are scoring slightly higher (75.5) than won legs (74.2), suggesting the contextual adjustments (ERA ±5, K/9 ±5) are adding noise rather than signal. Under review.

### **Phase 2: Enriched Scoring (May 26, 2026) — SHADOW TESTING**

Three additional signals layered on top of Phase 1 in shadow pipeline. Signal 4 (consistency) being added May 29.

---

## Coverage Gating Architecture

### **Decision: Two-Gate System on `coverage_overall` (May 27, 2026)**

**The problem:** The original single gate ran against `coverage_vs_hand or coverage_overall` — the best available signal. This allowed `coverage_vs_hand` to rescue players whose `coverage_overall` was below threshold. A player with 55% season coverage but 70% vs right-handers would pass, then receive additional ERA/pitcher boosts, ending up in parlays with fundamentally weak underlying coverage.

**Diagnosis:** José Ramírez (62–64% coverage_overall, 0/8 in parlays), Mookie Betts (67–70%, 0/10), Josh Naylor (67–70%, 4/17) were all passing the gate and losing consistently. The contextual adjustments were turning marginal selections into parlay legs.

**The fix — two explicit gates in `_find_qualifying_legs()` in `main.py`:**

```python
# Gate 1: coverage_overall is a hard requirement, checked before any signal
coverage_overall_raw = coverage.get("coverage_overall") or 0.0
if coverage_overall_raw < MIN_COVERAGE_PCT:  # 65%
    continue

# Gate 2: prop-specific floors (checked after Gate 1)
if stat == "totalBases" and direction == "under" and line == 1.5:
    if coverage_overall_raw < 80.0:
        continue
if stat == "strikeouts" and direction == "over" and line == 5.5:
    if coverage_overall_raw < 72.0:
        continue

# Scoring still uses best available signal
coverage_pct = coverage.get("coverage_vs_hand") or coverage_overall_raw
```

**Design principle:** Gates filter eligibility based on `coverage_overall` (the unbiased season-long rate). Scoring uses the best available signal (vs-hand if available). These are separate concerns. Adjustments can rank eligible legs against each other but cannot rescue ineligible ones.

---

## Prop-Specific Coverage Floors

### **Decision: 80% floor for `totalBases under 1.5` (May 27)**

**Data:** 135 appearances in the last 7 days, 50.4% win rate. At coverage thresholds up to 78%, win rate never exceeded 42.9%. The leg is fundamentally noisy — one single ruins the under, so season coverage of 70–75% doesn't reliably translate to same-day performance.

**Winners cluster tightly at 80%+:** Ha-Seong Kim (100%), Will Smith (84% — one win), Kyle Higashioka (82.5%), Tyler Freeman (80.4%), J.P. Crawford (80.4–80.8%). Below 80%, the prop is essentially a coin flip regardless of coverage score.

**Effect:** Eliminates ~70% of the previous TB under pool. Parlays now only use TB under when there's genuine strong evidence.

### **Decision: 72% floor for `strikeouts over 5.5` (May 27)**

**Data:** Every loss in the last 7 days came from players at ≤70% coverage. Every win came from ≥72% coverage. Clean cliff edge — Braxton Ashcraft at exactly 70% appeared 13 times and went 1/13. Cam Schlittler at 81.8% went 10/10.

**Effect:** Eliminates all low-coverage pitcher K props on the 5.5 line. The 5.5 line is a meaningful threshold — it requires a starting pitcher to go deep and miss bats, and only pitchers with demonstrated consistency at that line should be included.

---

## Coverage Calculation

### **Decision: Direction-Aware Coverage with Handedness Splits**

```python
# OVER props
coverage_pct = (games_over / total_games) * 100

# UNDER props
coverage_pct = (games_under / total_games) * 100
```

**Validated May 21:** 100% of props calculate successfully. **Validated May 27:** `coverage_overall` at 100% population, `coverage_recent_10` at 95–97% population — both reliable enough for consistency signal logic.

---

## Prop Type Filtering

### **Decision: Block Unprofitable Prop Types (Updated May 27)**

Based on in-parlay win rates over the last 7 days (not all-time — recent filters changed the composition significantly):

| Prop | 7-Day In-Parlay Win Rate | Action |
|---|---|---|
| `strikeouts under 5.5` | 85.7% | ✅ Prioritize |
| `strikeouts over 3.5` | 76.9% | ✅ Keep |
| `hits under 0.5` | 71.1% | ✅ Keep |
| `strikeouts over 6.5` | 68.4% | ✅ Keep |
| `strikeouts under 4.5` | 63.0% | ✅ Keep |
| `hits over 0.5` | 60.0% | ✅ Keep |
| `strikeouts over 4.5` | 60.0% | ✅ Keep |
| `strikeouts over 0.5` | 57.6% | ✅ Monitor |
| `rbi under 0.5` | 58.3% | ✅ Monitor |
| `totalBases under 1.5` | 50.4% | ⚠️ 80% floor added |
| `strikeouts over 5.5` | 50.0% | ⚠️ 72% floor added |
| `pitcher K under <5.5` | ~45% | ⚠️ Pending block |
| `hitter K under 0.5` | 36.7% | ❌ Blocked |
| Any prop < -300 | — | ❌ Blocked from parlays |

**Key insight:** The all-time win rates in training data are not predictive of in-parlay performance. The legs that can reach +700–+1000 target odds are a subset of the total pool, and that subset has meaningfully different win rates than the full pool.

---

## Parlay Construction Strategy

### **Decision: +700 to +1000 Odds Range**

Allows using best-coverage props regardless of juice. Math: 4 legs at 67% = 0.67^4 = 20.2% expected win rate at +800 avg odds. **Actual in-parlay leg win rate is ~57.6%**, which implies ~10.7% parlay win rate — consistent with observed ~11%.

Improving per-leg win rate to 65%+ (via better filtering and consistency signal) would push parlay win rate to ~18%.

---

## Juice Cap Decision

### **Decision: Block Props with Odds < -300 from Parlays (May 21)**

High-juice props (-300 to -460) have high win rates (66–80%) but kill the odds combination — using them makes it impossible to reach +700. Blocking them forces the builder to use lower-juice props that can contribute to the target range.

**May 27 validation:** 72 legs blocked by juice cap in today's run out of 217 eligible. Cap is working as designed.

---

## Player Diversity Constraint

### **Decision: Maximum 1 Prop Per Player Per Parlay Batch**

Eliminates correlated wipeout risk. If a player has a bad game, they can only ruin one parlay per batch instead of all of them.

---

## Shadow Pipeline Strategy

### **Decision: Shadow Before Promoting**

Run significant scoring changes as a shadow pipeline for 5–7 days before promoting to production. Allows apples-to-apples comparison via `production_batch_id`.

**May 27 update:** Shadow pipeline now inherits Session 1 production filters automatically because it receives `qualifying_legs` directly from `main.py` post-filtering. No separate implementation needed in shadow tables.

---

## Enriched Scoring Signals

### **Signal 1: Blended ERA Rank**
Season ERA rank × 0.5 + last-3-start ERA rank × 0.5. Captures pitcher form.

### **Signal 2: Opponent-Specific Coverage Split**
Batter's hit rate vs tonight's specific opponent (min 3 games, 25% delta weight, ±8 cap).

### **Signal 3: Ballpark Factor**
30-row `ballpark_factors` table. Hitter props use run_factor; pitcher K props use inverted and smaller magnitude.

### **Signal 4: Consistency (Pending — May 29)**
```python
gap = coverage_overall - coverage_recent_10
# Penalties for cold streaks (gap > 0), boosts for hot streaks (gap < 0)
```
`coverage_recent_10` confirmed at 95–97% population rate. Ready to build.

---

## Database Design

### **Decision: Two-Gate Filtering in Application Layer**
Coverage gates are enforced in `main.py` before legs reach the scorer or database. This keeps the database as a clean log of what was eligible, not a mix of eligible and blocked legs.

### **Lesson: `coverage_overall` vs `coverage_vs_hand` are different signals for different purposes**
- `coverage_overall`: eligibility gate — unbiased season rate, hard requirement
- `coverage_vs_hand`: scoring input — more specific signal, used to rank among eligible legs
- These must not be conflated. A player passing on `coverage_vs_hand` alone was the root cause of the chronic bad actor problem.

---

## Pipeline Architecture

### **Decision: 3x Daily + Shadow After Every Run**
- 9:00 AM ET — Resolution + fresh parlays
- 12:00 PM ET — Midday refresh
- 5:30 PM ET — Evening refresh
- Manual Regenerate Now also triggers shadow

Shadow pipeline adds ~2–3 seconds per run.

---

## Lessons Learned

1. **The headline hit rate is not the in-parlay hit rate** — 66.7% pool hit rate vs 57.6% in-parlay rate. High-juice props drive the headline but can't enter parlays. Always measure in-parlay performance separately.
2. **Adjustments can rescue bad legs** — ERA/K-rate adjustments were lifting marginal players over the gate threshold. Gates must run on raw coverage before any adjustments are applied.
3. **Score-outcome correlation is the health check** — If lost legs score higher than won legs, the scoring system is broken. Check this weekly.
4. **In-parlay win rates by line matter** — `strikeouts over 5.5` has a completely different win rate profile than `strikeouts over 6.5`. Line-level granularity is essential when setting thresholds.
5. **Shadow before promoting** — Major scoring changes need A/B comparison, not blind promotion.
6. **Chronic bad actors are a symptom** — Mookie Betts and José Ramírez appearing repeatedly wasn't the problem itself; it was the symptom of the gate running on the wrong field.
7. **All-time data is contaminated** — Pre-May-20 data includes the broken ML model era. Always segment analysis to post-strategy-change periods.

---

## Future Considerations

### **1. Reduce or Remove ERA/K-rate Scoring Adjustments**
Score-outcome correlation shows adjustments adding noise. After consistency signal is evaluated in shadow, consider running production with reduced or zero ERA/K-rate adjustments to test if leg quality improves.

### **2. Promote Enriched to Production (June 2026)**
After 5–7 days of shadow data confirms enriched scoring improves win rates.

### **3. `won_with_void` Outcome Tracking**
Distinguish clean 4/4 wins from 3/3 wins that needed a void. Prevents inflating win rate metrics.

### **4. Pitcher K Under Line Threshold**
Block pitcher K unders below line 5.5 in `main.py`. Data shows losses concentrated at 4.5 and below.

### **5. Direction-Split Calibrators (If ML Model Revisited)**
Train 14 calibrators (7 stats × 2 directions) instead of 7.

### **6. Weather Integration**
Flag outdoor game total legs when wind > 15 mph out or temp < 45°F. Low priority.

---

**Architecture Status:** ✅ STABLE — Session 1 Fixes Live, Phase 2 Shadow Testing
**Last Major Change:** May 27, 2026 (Two-gate coverage system)
**Next Architecture Review:** June 2026 (After shadow comparison analysis)
