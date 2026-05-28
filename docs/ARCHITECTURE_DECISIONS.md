# MLB Parlay Agent — Architecture Decisions
**Last Updated:** May 28, 2026 (Session 2 — Team SO Signal + Anchor/Swing)

This document captures key architectural and design decisions made during development, along with reasoning and lessons learned.

---

## Table of Contents
1. [Core Philosophy](#core-philosophy)
2. [Scoring System Evolution](#scoring-system-evolution)
3. [Coverage Gating Architecture](#coverage-gating-architecture)
4. [Prop-Specific Coverage Floors](#prop-specific-coverage-floors)
5. [Anchor/Swing Parlay Structure](#anchorswing-parlay-structure) ← **UPDATED**
6. [Coverage Calculation](#coverage-calculation)
7. [Prop Type Filtering](#prop-type-filtering)
8. [Juice Cap Decision](#juice-cap-decision)
9. [Player Diversity Constraint](#player-diversity-constraint)
10. [Shadow Pipeline Strategy](#shadow-pipeline-strategy)
11. [Enriched Scoring Signals](#enriched-scoring-signals) ← **UPDATED**
12. [Database Design](#database-design)
13. [Pipeline Architecture](#pipeline-architecture)
14. [Lessons Learned](#lessons-learned) ← **UPDATED**
15. [Future Considerations](#future-considerations)

---

## Core Philosophy

### **Decision: Optimize for Hit Probability, Not Expected Value**

Parlays multiply probabilities — each leg's hit rate is paramount. A 75% coverage leg at -150 is better than a 65% leg at +120 for parlay construction.

**Validation:** ✅ May 20, 2026 — 69% accuracy on coverage-based leg selection confirmed.

---

## Scoring System Evolution

### **Phase 0: ML Model (April–May 2026) — ABANDONED**
GradientBoostingClassifier, 77K samples, direction feature at 77% importance. Score-outcome correlation was inverted — high scores had lower win rates. Parlay win rate: 7.6%.

### **Phase 1: Simple Coverage-Based Scoring (May 20, 2026) — CURRENT PRODUCTION**

```python
score = base_coverage + adjustments
# base = coverage_vs_hand (preferred) or coverage_overall
# adjustments:
#   consistency: gap-based ±6/±4/±2/+2/+1/0
#   pitcher ERA: ±5 (NOTE: returning 0 for 100% of legs — effectively dead, cleanup pending)
#   pitcher K/9: ±5 for SO props
#   lineup stability: -5 if < 50%
```

**Parlay win rate:** ~11% pre-anchor/swing (target 18–22%, under evaluation post-May 28)

**Known issue:** Lost parlay legs score slightly higher (75.5) than won legs (74.2). ERA/K-rate adjustments may be adding noise. Under review — cleanup deferred pending consistency signal validation.

### **Phase 2: Enriched Scoring (May 26–28, 2026) — SHADOW TESTING**

Four additional signals on top of Phase 1 consistency logic. All 4 signals now operational.

---

## Coverage Gating Architecture

### **Decision: Two-Gate System on `coverage_overall` (May 27, 2026)**

**The problem:** The original single gate ran against `coverage_vs_hand or coverage_overall`. A player with 55% season coverage but 70% vs right-handers would pass, then receive ERA/pitcher boosts into parlay-eligible territory.

**The fix — two explicit gates in `_find_qualifying_legs()` in `main.py`:**

```python
# Gate 1: coverage_overall is a hard requirement
coverage_overall_raw = coverage.get("coverage_overall") or 0.0
if coverage_overall_raw < MIN_COVERAGE_PCT:  # 65%
    continue

# Gate 2: prop-specific floors
if stat == "totalBases" and direction == "under" and line == 1.5:
    if coverage_overall_raw < 80.0:
        continue
if stat == "strikeouts" and direction == "over" and line == 5.5:
    if coverage_overall_raw < 72.0:
        continue

# Scoring uses best available signal
coverage_pct = coverage.get("coverage_vs_hand") or coverage_overall_raw
```

**Design principle:** Gates filter eligibility using `coverage_overall` (unbiased season rate). Scoring uses the best available signal. Adjustments rank eligible legs against each other but cannot rescue ineligible ones.

---

## Prop-Specific Coverage Floors

### **Decision: 80% floor for `totalBases under 1.5` (May 27)**

135 appearances in 7 days, 50.4% win rate. Winners cluster tightly at 80%+. Below 80% the prop is essentially a coin flip regardless of coverage score.

### **Decision: 72% floor for `strikeouts over 5.5` (May 27)**

Clean cliff edge — every loss in 7 days came from players at ≤70% coverage. Braxton Ashcraft at exactly 70% appeared 13 times and went 1/13.

---

## Anchor/Swing Parlay Structure

### **Decision: Replace Single-Pool 4-Leg with 3-Anchor + 2-Swing 5-Leg (May 28, 2026)**

**The problem:** A single pool targeting +700–+1000 forced a tradeoff — either use high-confidence high-juice legs (great win rate, kills odds) or low-confidence plus-money legs (hit the odds target, bad win rate).

**The solution:** Two explicit pools with different jobs.

| Pool | Coverage Floor | Odds Range | Legs Per Parlay |
|------|---------------|------------|-----------------|
| Anchor | 75% overall | -300 to -150 | Foundation — maximize hit probability | 3 |
| Swing | 55% overall | -150 to +150 | Odds multipliers — add payout without killing quality | 2 |

**Target odds:** +900 to +1100 combined (5-leg)

**Rationale for 75% anchor floor:** Data showed anchor pool win rates of 77.9% (SO over), 73.4% (hits under), 72.8% (hits over) at 75%+ threshold — well above the 67%+ needed to drive parlay win rates toward 18–22%.

**Rationale for swing odds range:** Plus-money props DO exist at scale in the swing range (-150 to +150). Requiring ≥-150 prevents the swing legs from being high-juice anchors in disguise.

**All 4 call sites updated:** `main.py` (×2), `server.py`, `run_enriched_pipeline.py`

---

## Coverage Calculation

### **Decision: Direction-Aware Coverage with Handedness Splits**

```python
# OVER props
coverage_pct = (games_over / total_games) * 100

# UNDER props
coverage_pct = (games_under / total_games) * 100

# Handedness split (scoring only, not gating)
coverage_vs_RHP = games_over_vs_RHP / total_games_vs_RHP * 100
```

`coverage_overall` = gate signal (unbiased season rate)
`coverage_vs_hand` = scoring signal (more specific, used to rank among eligible legs)

These must not be conflated. Using `coverage_vs_hand` for gating was the root cause of the chronic bad actor problem (May 27 diagnosis).

---

## Prop Type Filtering

### **Decision: Block Unprofitable Prop Types (Updated May 28)**

Based on 7-day in-parlay win rates:

| Prop | 7-Day In-Parlay Win Rate | Action |
|---|---|---|
| `strikeouts under 5.5` | 85.7% | ✅ Prioritize |
| `hits under 0.5` | 71.1% | ✅ Keep |
| `strikeouts over 6.5` | 68.4% | ✅ Keep |
| `strikeouts under 4.5` | 63.0% | ✅ Keep |
| `hits over 0.5` | 60.0% | ✅ Keep |
| `strikeouts over 4.5` | 60.0% | ✅ Keep |
| `strikeouts over 0.5` | 57.6% | ✅ Monitor |
| `rbi under 0.5` | 58.3% | ✅ Monitor |
| `totalBases under 1.5` | 50.4% | ⚠️ 80% floor |
| `strikeouts over 5.5` | 50.0% | ⚠️ 72% floor |
| `pitcher SO under < 6.5` | ~45% | ❌ Blocked |
| `pitcher SO < 4.5 line` | 47.8% | ❌ Blocked |
| `hitter K under 0.5` | 36.7% | ❌ Blocked |
| Any prop < -300 | — | ❌ Blocked from parlays |

---

## Juice Cap Decision

### **Decision: Block Props with Odds < -300 from Parlays (May 21)**

High-juice props (-300 to -460) have high win rates but make it impossible to reach +900 target odds. Blocking them forces the builder to use lower-juice props that can contribute to the target range without sacrificing too much per-leg quality.

---

## Player Diversity Constraint

### **Decision: Maximum 1 Prop Per Player Per Parlay Batch**

Eliminates correlated wipeout risk. If a player has a bad game, they ruin one parlay per batch instead of all of them.

---

## Shadow Pipeline Strategy

### **Decision: Shadow Before Promoting**

Run significant scoring changes as a shadow pipeline for 5–7 days before promoting to production. Allows apples-to-apples comparison via `production_batch_id`.

Shadow pipeline now has 4 signals. Production comparison analysis planned for June 1–2.

---

## Enriched Scoring Signals

### **Signal 1: Blended ERA Rank**
Season ERA rank × 0.5 + last-3-start ERA rank × 0.5. Captures pitcher current form vs season baseline. Applied to hits/TB/RBI/runs props (hitters only).

### **Signal 2: Opponent-Specific Coverage Split**
Batter's hit rate vs tonight's specific opponent (min 3 games, 25% delta weight, ±8 cap). More specific than overall coverage but requires sample.

### **Signal 3: Ballpark Factor**
30-row `ballpark_factors` static table. Hitter props: ±5 based on run_factor. Pitcher props: ±3 (inverted). HR props: ±5 based on hr_factor.

### **Signal 4: Opposing Team Strikeout Rank (May 28, 2026)**

**Motivation:** Pitcher SO props have no awareness of how K-prone the opposing lineup is. Jack Flaherty SO under 6.5 vs LAA (rank 1 in team Ks) is a fundamentally different bet than the same prop vs a low-K lineup. Season coverage alone doesn't capture this.

**Data source:** `mlb_stats.get_team_strikeout_stats(season)`
- Season rank: `/api/v1/teams/stats?stats=season&group=hitting` — total SO ranked 1–30
- Recent rank: `/api/v1/teams/stats?stats=byDateRange&group=hitting` with 14-day window

**API implementation note:** The `lastXGames` endpoint's `limit` parameter filters the number of teams returned, not the number of games per team. Use `byDateRange` for windowed team stats.

**Adjustment logic:**

| Season Rank | Season Adj | Recent Rank | Recent Modifier | Net (capped ±6) |
|-------------|-----------|-------------|-----------------|-----------------|
| 1–8 (most Ks) | +5 | 1–8 | +2 | up to +6 |
| 1–8 | +5 | 9–22 | 0 | +5 |
| 1–8 | +5 | 23–30 | -2 | +3 |
| 9–15 | +2 | varies | ±2/0 | +4 to 0 |
| 16–22 | -2 | varies | ±2/0 | 0 to -4 |
| 23–30 (fewest Ks) | -5 | varies | ±2/0 | -3 to -6 |

Sign-flipped for unders: high-K opponent = penalty for SO unders (Flaherty case).

**Scope:** Pitcher SO props only (`position in _PITCHER_POSITIONS` and `stat == 'strikeouts'`). Returns `None` for all other props.

**Cache TTL:** 24 hours, refreshed at 9 AM pipeline run.

---

## Database Design

### **Decision: Two-Gate Filtering in Application Layer**
Coverage gates enforced in `main.py` before legs reach the scorer or database. Keeps the database as a clean log of what was eligible.

### **Decision: Shadow Tables Mirror Production Schema + Enriched Columns**
`mlb_scored_legs_enriched` has all production columns plus: `coverage_vs_opponent`, `games_vs_opponent`, `park_factor`, `park_adjustment`, `blended_era_rank`, `recent_form_rank`, `team_so_adjustment`.

### **Critical Type Rules**
- `mlb_scored_legs.run_date` is TEXT — use string comparisons
- `mlb_scored_legs.odds` is TEXT — cast to numeric for math
- `mlb_parlay_recommendations_v2.run_date` is DATE — no cast needed
- `mlb_training_data.result` uses `'hit'/'miss'/'void'` — different from parlay tables' `'won'/'lost'`

---

## Pipeline Architecture

### **Decision: 3× Daily + Shadow After Every Run**
- 9:00 AM ET — Resolution + fresh parlays
- 12:00 PM ET — Midday refresh
- 5:30 PM ET — Evening refresh
- Manual Regenerate also triggers shadow

Shadow pipeline adds ~2–3 seconds per run and never touches production tables.

---

## Lessons Learned

1. **The headline hit rate is not the in-parlay hit rate.** High-juice props drive the headline but can't enter parlays. Always measure in-parlay performance separately.
2. **Adjustments can rescue bad legs.** ERA/K-rate adjustments were lifting marginal players over the gate threshold. Gates must run on raw coverage before any adjustments.
3. **Score-outcome correlation is the health check.** If lost legs score higher than won legs, the scoring system is broken. Check weekly.
4. **In-parlay win rates by line matter.** `strikeouts over 5.5` has a completely different profile than `strikeouts over 6.5`. Line-level granularity is essential.
5. **Shadow before promoting.** Major scoring changes need A/B comparison, not blind promotion.
6. **Chronic bad actors are a symptom.** Repeated bad performers are a signal the gate is running on the wrong field, not an argument for player-specific blocks.
7. **All-time data is contaminated.** Pre-May-20 data includes the broken ML model era. Always segment analysis to post-strategy-change periods.
8. **Read the API docs before assuming parameter behavior.** `lastXGames` with `limit=10` returns 10 teams, not 10 games. Test the endpoint shape before building on it.
9. **Two pools solve the odds/quality tradeoff.** A single pool forces a compromise between win rate and payout. Anchor/swing separates the two concerns cleanly.

---

## Future Considerations

### **1. Promote Enriched to Production (June 2026)**
After 5–7 days of shadow data with all 4 signals confirms enriched scoring improves win rates vs production.

### **2. Gate 3 — Minimum `coverage_recent_10` Floor**
Block any leg where `coverage_recent_10 < 50%` regardless of `coverage_overall`. Prevents cold-streak legs sneaking through on strong season averages. Deferred — validate consistency signal data first.

### **3. Remove Dead ERA/Pitcher Adjustments from simple_scorer.py**
`opponent_adjustment` returns 0 for 100% of legs. Not harmful but adds noise to the scoring logic. Clean up once shadow comparison data confirms the enriched signals are sufficient.

### **4. `won_with_void` Outcome Tracking**
Distinguish clean 4/4 wins (now 5/5) from wins that needed a void. Prevents inflating win rate metrics.

### **5. Pitcher K Under Line ≥ 6.5 Threshold**
Already blocked below 6.5, but worth monitoring 6.5u win rate data specifically now that lower lines are gone.

### **6. Weather Integration**
Flag outdoor game total legs when wind > 15 mph out or temp < 45°F. Low priority.

---

**Architecture Status:** ✅ STABLE — Session 2 Complete, Shadow Pipeline at 4 Signals
**Last Major Change:** May 28, 2026 (Team SO rank signal + anchor/swing structure)
**Next Architecture Review:** June 2026 (After shadow comparison analysis)
