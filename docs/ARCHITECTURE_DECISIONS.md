# MLB Parlay Agent — Architecture Decisions
**Last Updated:** June 1, 2026 (Session 4 — Performance Diagnosis + Full System Refactor)

---

## Table of Contents
1. [Core Philosophy](#core-philosophy)
2. [Scoring System Evolution](#scoring-system-evolution)
3. [Prop Selection — Data-Driven Whitelist](#prop-selection--data-driven-whitelist)
4. [Coverage Gating Architecture](#coverage-gating-architecture)
5. [Parlay Construction Evolution](#parlay-construction-evolution)
6. [Odds Cap Decision](#odds-cap-decision)
7. [Coverage Calculation](#coverage-calculation)
8. [Shadow Pipeline Strategy](#shadow-pipeline-strategy)
9. [Enriched Scoring Signals](#enriched-scoring-signals)
10. [Outcome Resolution](#outcome-resolution)
11. [Database Design](#database-design)
12. [Pipeline Architecture](#pipeline-architecture)
13. [Lessons Learned](#lessons-learned)
14. [Future Considerations](#future-considerations)

---

## Core Philosophy

### **Decision: Optimize for Validated Edge, Not Feature Complexity**

The system exists to find props where historical coverage rate predicts actual outcomes, and combine them into parlays with positive expected value. Every design decision should be evaluated against this goal.

**Key insight from 60-day analysis (June 2026):** Coverage is a necessary but not sufficient condition for parlay selection. The book prices high-coverage props expensively (e.g. RBI under at -348 for 85%+ coverage), eliminating the edge. True edge exists only where coverage predicts outcomes AND the book underprices that prediction.

**Validated as of June 2026:**
- `hits over 0.5` at 65%+ coverage: genuine +6pp edge above breakeven
- `SO over 0.5` (hitter) at 65%+ coverage: genuine +7pp edge above breakeven
- `hits under 0.5` at 70%+ coverage: +11pp edge (thin sample — 24 appearances)

---

## Scoring System Evolution

### **Phase 0: ML Model (April–May 2026) — ABANDONED**
GradientBoostingClassifier, 77K samples, direction feature at 77% importance. Score-outcome correlation was inverted — high scores had lower win rates. Parlay win rate: 7.6%.

**Why it failed:** Model learned that unders historically "covered" due to low prop lines, not because they were good bets. Direction feature dominated everything else.

### **Phase 1: Simple Coverage-Based Scoring (May 20, 2026) — CURRENT PRODUCTION**

```python
score = base_coverage + adjustments
# base = coverage_vs_hand (preferred) or coverage_overall
# adjustments:
#   consistency: gap-based ±6/±4/±2/+2/+1 (coverage_overall vs coverage_recent_10)
#   pitcher K9: ±5 for SO over props (hitter only)
#   lineup stability: -5 if lineup_consistency < 0.50
```

**Parlay win rate (old prop set):** ~7.9%
**Expected parlay win rate (new prop set):** ~20-25% (per data-driven 4-leg math)

---

## Prop Selection — Data-Driven Whitelist

### **Decision: Strict Whitelist Based on 60-Day Outcome Analysis (June 1, 2026)**

**The analysis:** Queried `mlb_scored_legs` across 60 days and 90K+ resolved legs, bucketing by coverage rate and measuring actual win rates per bucket. Only props showing a monotonically increasing coverage-to-win-rate relationship were kept.

**Results:**

| Prop | Coverage Predictive? | Finding |
|---|---|---|
| `hits over 0.5` | ✅ Yes | 50% → 75% win rate as coverage rises from <60% to 75-79% |
| `SO over 0.5` (hitter) | ✅ Yes | 41% → 91% win rate across buckets |
| `hits under 0.5` | ⚠️ Limited | 67% at 65%+ but only 24 appearances — included with stricter gate |
| `totalBases under 1.5` | ❌ No | Flat 57-63% across ALL coverage buckets (1,000+ appearances) |
| `rbi under 0.5` | ❌ No | Flat 67-77% — book prices edge away (avg -280 to -348) |
| Pitcher SO (all) | ❌ No | Coverage missing 55%+ of legs; win rates 30-52% |
| `walks over 0.5` | ❌ Insufficient | 63% at 60-64% but only 66 total appearances |

**Current whitelist:**
```python
ALLOWED_PROPS = {
    ("hits",       "over",  0.5),
    ("hits",       "under", 0.5),   # 70% gate
    ("strikeouts", "over",  0.5),   # hitter only
}
```

**Design principle:** Never add a prop type to the whitelist without 200+ resolved appearances showing monotonically increasing coverage-to-win-rate. Sample size is the primary constraint — not intuition.

---

## Coverage Gating Architecture

### **Decision: Two-Gate System on `coverage_overall` (May 27, 2026)**

Gate 1 (`coverage_overall >= 65%`) runs before any scoring adjustments, ensuring adjustments rank eligible legs against each other but cannot rescue ineligible ones.

Gate 2 applies prop-specific floors where the data demands it:
- `hits under 0.5`: 70% minimum (thin sample, require higher confidence)

**Design principle:** Gates use `coverage_overall` (unbiased season rate). Scoring uses `coverage_vs_hand` (more specific). These must not be conflated — using `coverage_vs_hand` for gating was the root cause of the "chronic bad actor" problem diagnosed in May.

---

## Parlay Construction Evolution

### **Phase 1: Single Pool +700–+1000 (Pre-May 28)**
- 4-6 legs, single pool
- Problem: pool flooded with RBI unders at -280 to -300, killing parlay quality

### **Phase 2: Anchor/Swing 3-Leg +900–+1100 (May 28)**
- 3 anchors (75%+ coverage, -300 to -150) + 2 swings (55%+ coverage, -150 to +150)
- Problem: swing pool starvation on thin slates (only 1 swing leg available); anchor floor 75% excluded most legs

### **Phase 3: Single Flat Pool 4-Leg +400–+700 (June 1, 2026) — CURRENT**

**Why anchor/swing was eliminated:**
- With only 3 validated prop types all priced -250 to +150, the two-pool distinction added no value
- Swing pool starvation halted parlay generation entirely on June 1 (1 swing leg → 1 parlay maximum)
- Analysis showed the odds/coverage distinction was artificial given the narrow prop set

**Current structure:**
```
Single pool: coverage_overall >= 65%, odds -250 to +150
4 legs per parlay
Target: +400 to +700 combined
Constraints: max 2 legs/game, max 1 leg/player/parlay, max 1 player/batch
```

**Why +400 to +700:**
- 4-leg math at 70% per leg: 0.70^4 = 24% win probability
- Profitable above ~17% win rate at +500 average
- Previous +900–+1100 target required 5+ legs → 14% win probability → near-breakeven ROI
- Lower odds, more wins, better ROI

### **Decision: `build_hybrid_parlays()` retained as backward-compat wrapper**
The enriched pipeline and any external callers still use `build_hybrid_parlays(anchor_legs, swing_legs)`. The wrapper merges pools and calls `build_parlays()`, requiring no changes to callers.

---

## Odds Cap Decision

### **Decision: -250 Hard Cap Per Leg (June 1, 2026)**

**Analysis:** The -200 cap introduced in the refactor was cutting ~50% of eligible legs daily:
- Typical day: 22 legs at 65%+ coverage, but only 10-12 in the -200 range
- May 31 example: 28 legs above 65% coverage, only 10 within -200 range (18 blocked)

**Why -250 specifically:**
- Hits over 0.5 at 75-79% coverage wins 75.4%; avg odds in that bucket is -225
- At -250, breakeven is 71.4%. We're hitting 75%. Edge exists.
- At -300, breakeven is 75.0%. Edge disappears for most legs.
- -250 recovers most blocked legs while maintaining positive expected value

**Pool size impact at -250 cap:** ~18-22 eligible legs on typical weekday, 30-45 on full weekend slates.

---

## Coverage Calculation

### **Decision: Direction-Aware Coverage with Handedness Splits**

```python
# OVER props: % of games where stat >= line
# UNDER props: % of games where stat < line
# coverage_vs_hand: log-odds adjusted for pitcher handedness (scoring only)
```

`coverage_overall` = gate signal (unbiased season rate, uses full game log)
`coverage_vs_hand` = scoring signal (more specific, used to rank among eligible legs)

These serve different purposes and must not be conflated.

---

## Shadow Pipeline Strategy

### **Decision: Shadow Before Promoting**

Significant scoring changes run as a shadow pipeline for 5-7 days before production promotion. Shadow tables mirror production schema plus enriched signal columns. `production_batch_id` links shadow parlays to production parlays for direct A/B comparison.

**Current shadow signals (3 active, 1 removed):**
1. Blended ERA Rank — season ERA × 0.5 + last-3-start ERA × 0.5. Applies to `hits` props.
2. Opponent-specific Coverage Split — batter hit rate vs tonight's specific opponent (min 3 games).
3. Ballpark Factor — 30-row static table, Coors 115 → Petco 94.
4. ~~Team SO Rank~~ — **REMOVED June 1** (pitcher SO props cut from whitelist).

---

## Enriched Scoring Signals

### **Signal 1: Blended ERA Rank (Active — hits props only)**
Season ERA rank blended with pitcher's last-3-start ERA rank. Captures pitcher current form vs season baseline. Applies only to `hits` props (the only hitter prop where ERA is relevant after whitelist narrowing).

### **Signal 2: Opponent-Specific Coverage Split (Active — all hitter props)**
Batter's hit rate vs tonight's specific opponent (min 3 games, 25% delta weight, ±8 cap). More specific than overall coverage but requires sample.

### **Signal 3: Ballpark Factor (Active — all hitter props)**
30-row `ballpark_factors` static table. Hitter props: ±5 based on run_factor.

### **Signal 4: Team SO Rank (REMOVED June 1)**
Pitcher SO props cut from whitelist made this signal irrelevant. Removed from `enriched_scorer.py`, `run_enriched_pipeline.py`, and related DB writes.

---

## Outcome Resolution

### **Decision: Fail-Safe EEP with Explicit Presence Check (June 1, 2026)**

Early Exit Protection was voiding every batter leg due to `plateAppearances` defaulting to 0 when `boxscore_data()` returned empty stats dict.

**Rule:** EEP only fires when the API explicitly returns a value for `plateAppearances` (batters) or `battersFaced` (pitchers). If the key is absent, assume the player played normally.

```python
# Batter EEP
plate_appearances = batting.get("plateAppearances")  # None if absent
if plate_appearances is not None and plate_appearances < 2:
    # genuine early exit

# Pitcher EEP
batters_faced = pitching.get("battersFaced")  # None if absent
if batters_faced is not None and batters_faced < 5:
    # genuine early exit
```

### **Decision: game_not_found defers parlay, not void**
When a game's box score is unavailable, the parlay is deferred (kept pending) rather than the leg being voided. We can't distinguish "game postponed" from "API not yet populated" — voiding was incorrect.

---

## Database Design

### **Critical Type Rules**
- `mlb_scored_legs.run_date`: TEXT — use string comparisons
- `mlb_scored_legs.odds`: TEXT — cast to numeric for math: `odds::numeric`
- `mlb_parlay_recommendations_v2.run_date`: DATE — no cast needed
- `mlb_training_data.result`: `'hit'/'miss'/'void'` — different from parlay tables' `'won'/'lost'`

### **Shadow Tables Mirror Production + Enriched Columns**
`mlb_scored_legs_enriched` has all production columns plus: `coverage_vs_opponent`, `games_vs_opponent`, `park_factor`, `park_adjustment`, `blended_era_rank`, `recent_form_rank`.
`team_so_adjustment` column exists in DB but no longer populated (signal removed).

---

## Pipeline Architecture

### **3× Daily + Shadow After Every Run**
- 9:00 AM ET — Resolution + fresh parlays
- 12:00 PM ET — Midday refresh
- 5:30 PM ET — Evening refresh
- Manual Regenerate also triggers shadow

Shadow pipeline adds ~2-3 seconds per run and never touches production tables.

---

## Lessons Learned

1. **Coverage alone is not edge.** The book also knows historical coverage rates. Edge exists only where your predicted win probability exceeds the book's implied probability. Always check avg_odds alongside win_rate.
2. **Flat coverage signals mean cut, not raise the floor.** If win rate is flat across all coverage buckets with 500+ appearances, the signal doesn't exist. Raising the threshold doesn't help.
3. **Pool size determines parlay structure.** Design around what the data actually provides daily, not what would be theoretically ideal. 4-leg +400-+700 is achievable with 15+ eligible legs. 5-leg +900-+1100 requires 25+ and fails on thin slates.
4. **Two-pool systems require genuinely different leg types.** Anchor/swing only makes sense when anchors and swings have meaningfully different odds profiles. When all props price similarly, a single pool is simpler and more robust.
5. **Sample size before tuning.** Every threshold change in June was made on 90K+ resolved legs. Changes before that were made on 200 parlays. The lesson: don't tune until you can measure.
6. **API defaults can silently corrupt logic.** `batting.get("plateAppearances", 0)` looks safe but causes catastrophic false-voids when the API returns an empty dict. Always use `is not None` guards for boolean conditions on API data.
7. **Data-driven prop selection beats intuition.** Total Bases and RBI unders seemed like solid props — lots of batters don't get TB or RBIs. But 1,000+ appearances proved the coverage signal was flat. The data was right, the intuition was wrong.
8. **Test the unhappy paths in resolution.** The EEP bug existed for days before discovery because void cases are rare in normal operation. Explicitly test: all legs void, some legs void, game not found.
9. **Backward-compat wrappers enable safe refactors.** Keeping `build_hybrid_parlays()` as a wrapper meant the enriched pipeline needed zero changes despite a complete rewrite of the underlying builder.

---

## Future Considerations

### **1. EV Gate for Parlay Selection**
Several legs in June 1 parlays show negative EV (`ev_per_unit < 0`). The composite score selects by coverage/consistency, not EV. After 30+ days of data on the new system, evaluate whether adding a minimum EV threshold (-5% or better) improves parlay quality without over-restricting the pool.

### **2. Promote Enriched to Production**
After 5-7 days of shadow data with all 3 remaining signals confirms enriched scoring improves win rates vs production. Target: June 8-10 comparison analysis.

### **3. `hits under 0.5` Validation**
Only 24 appearances above 65% coverage in 60-day dataset. Included with 70% gate but not trusted. Re-evaluate after 100+ appearances in the new system.

### **4. `walks over 0.5` Monitoring**
63% win rate at 60-64% coverage (66 appearances). Promising but insufficient sample. Monitor passively — if it reaches 200+ appearances with sustained win rate, add to whitelist.

### **5. Health Check Threshold Update**
Current health check flags `hit rate > 58%` as anomalous. With the new prop set (65%+ coverage gate, validated 67-75% win rates), the expected range should be updated to 63-75%. Low priority but causes misleading log warnings.

### **6. Gate 3 — Minimum `coverage_recent_10` Floor**
Block legs where `coverage_recent_10 < 50%` regardless of `coverage_overall`. Prevents cold-streak legs sneaking through on strong season averages. Deferred — accumulate data on consistency signal effectiveness first.

### **7. Learning Loop**
Once 500+ resolved legs exist under the new prop set and scoring system, run regression on `coverage_overall`, `coverage_vs_hand`, `coverage_recent_10`, `pitcher_k9`, `lineup_consistency` vs actual outcomes. Recalibrate signal weights from data rather than principled priors.

---

**Architecture Status:** ✅ STABLE — Single Pool + Validated Prop Whitelist
**Last Major Change:** June 1, 2026 (Single flat pool, prop whitelist, EEP fix)
**Next Architecture Review:** June 2026 (After shadow comparison analysis + 30 days of outcome data)
