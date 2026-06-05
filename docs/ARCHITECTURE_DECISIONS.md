# MLB Parlay Agent — Architecture Decisions
**Last Updated:** June 5, 2026 (Session 5 — Full System Diagnostic + Signal Pipeline Fixes)

---

## Table of Contents
1. [Core Philosophy](#core-philosophy)
2. [Scoring System Evolution](#scoring-system-evolution)
3. [Prop Selection — Data-Driven Whitelist](#prop-selection--data-driven-whitelist)
4. [Coverage Gating Architecture](#coverage-gating-architecture)
5. [Parlay Construction Evolution](#parlay-construction-evolution)
6. [Odds Cap Decision](#odds-cap-decision)
7. [Coverage Signal Architecture](#coverage-signal-architecture)
8. [Pitcher Signal Pipeline](#pitcher-signal-pipeline)
9. [Shadow Pipeline Strategy](#shadow-pipeline-strategy)
10. [Enriched Scoring Signals](#enriched-scoring-signals)
11. [Outcome Resolution](#outcome-resolution)
12. [Database Design](#database-design)
13. [Pipeline Architecture](#pipeline-architecture)
14. [Lessons Learned](#lessons-learned)
15. [Future Considerations](#future-considerations)

---

## Core Philosophy

### **Decision: Optimize for Validated Edge, Not Feature Complexity**

The system exists to find props where historical coverage rate predicts actual outcomes, and combine them into parlays with positive expected value. Every design decision should be evaluated against this goal.

**Validated as of June 2026:**
- `hits over 0.5` at 65%+ coverage: genuine +6pp edge above breakeven
- `SO over 0.5` (hitter) at 65%+ coverage: genuine +7pp edge above breakeven
- `hits under 0.5` at 70%+ coverage: +11pp edge (thin sample — 24 appearances)
- Park factor: 30-point win rate spread between pitcher parks (40%) and hitter parks (70%)

---

## Scoring System Evolution

### **Phase 0: ML Model (April–May 2026) — ABANDONED**
GradientBoostingClassifier, 77K samples, direction feature at 77% importance. Score-outcome correlation was inverted. Parlay win rate: 7.6%.

### **Phase 1: Simple Coverage-Based Scoring (May 20, 2026) — CURRENT PRODUCTION**

```python
score = coverage_overall  # always the base
     + coverage_vs_hand_delta  # ±3 max (30% weight of delta from overall)
     + consistency_adjustment  # gap-based ±6/±4/±2/+2/+1
     + era_adjustment          # ±5 for hits props (raw pitcher_era — pending revalidation)
     + k9_rank_adjustment      # ±5 for SO props (opp_pitcher_k9_rank, with raw fallback)
     + lineup_stability        # -5 if lineup_consistency < 0.50
```

### **Key Scoring Decision: `coverage_overall` Always Base (June 5, 2026)**

`coverage_vs_hand` was previously used as the base signal replacement when available (54% of hits legs). Validated on 30 days / 1,831 appearances: win rates are identical with vs without `coverage_vs_hand` (62.0% vs 62.3%), and the log-odds adjustment produces values within 0.5 points of `coverage_overall` on average.

**Decision:** `coverage_overall` is always the base. `coverage_vs_hand` is a delta adjustment at 30% weight capped ±3 points. This keeps all legs on a comparable scale regardless of data availability.

---

## Prop Selection — Data-Driven Whitelist

### **Decision: Strict Whitelist Based on 60-Day Outcome Analysis (June 1, 2026)**

Only props showing monotonically increasing coverage-to-win-rate relationship are included.

**Current whitelist:**
```python
ALLOWED_PROPS = {
    ("hits",       "over",  0.5),
    ("hits",       "under", 0.5),   # 70% gate
    ("strikeouts", "over",  0.5),   # hitter only — pitchers skipped by position check
}
```

**Removed props:**
| Prop | Reason |
|---|---|
| `totalBases under 1.5` | Flat 57-63% win rate at ALL coverage levels (1,000+ appearances) |
| `rbi under 0.5` | Flat signal — book prices edge away (avg -280 to -348) |
| Pitcher SO (all) | Coverage missing for most legs; win rates 30-52% |
| `walks`, `homeRuns`, `stolenBases` | Insufficient sample / negative edge |

**Design principle:** Never add a prop type without 200+ resolved appearances showing monotonically increasing coverage-to-win-rate.

---

## Coverage Gating Architecture

### **Decision: Two-Gate System on `coverage_overall`**

Gate 1 (`coverage_overall >= 65%`) runs before scoring. Gate 2 applies prop-specific floors:
- `hits under 0.5`: 70% minimum (thin sample, require higher confidence)

**Critical distinction:** Gates use `coverage_overall` (unbiased season rate). Scoring uses `coverage_vs_hand` as a delta adjustment. These are different roles for different signals.

---

## Parlay Construction Evolution

### **Phase 3: Single Flat Pool 4-Leg +400–+700 (June 1, 2026)**
Eliminated anchor/swing two-pool system. With only 3 validated prop types all priced -250 to +150, two-pool distinction added no value.

### **Phase 3.1: Score-Sort + MAX_CANDIDATES 50 (June 5, 2026) — CURRENT**

**Problem identified:** B&B was sorted by decimal odds descending for pruning efficiency. With today's pool, Oneil Cruz (score 59, odds -148) was explored before Ryan Waldschmidt (score 78, odds -176) purely because cheaper odds appear higher in the sort order. The first 15 combinations found all featured the same cheap-odds, low-quality legs. `avg_composite` tiebreaker between 15 near-identical combinations was effectively random.

**Fix:**
1. Sort pool by `composite_score` DESC — highest quality legs explored first
2. Raise `MAX_CANDIDATES` 15→50 — find 50 combinations before stopping
3. Fix B&B pruning bounds — original UB/LB relied on odds-sorted order. Fixed via `suffix_dec_sorted[i]` precomputing the sorted `_dec` values from `pool[i:]` so bounds remain valid under any sort order

**Result:** Waldschmidt (78), Rice (76.8), Turner (76.6) now lead parlay 1. Cruz (59), Andujar (59) only appear when no better combination exists.

**Why `build_hybrid_parlays()` retained:** Backward-compat wrapper for enriched pipeline and external callers. Merges pools and delegates to `build_parlays()`.

---

## Odds Cap Decision

### **Decision: -250 Hard Cap Per Leg (June 1, 2026)**

At -250, breakeven is 71.4%. Validated hits over win rate at 75-79% coverage is 75.4%. Edge exists. At -300, breakeven is 75.0% — edge disappears for most legs. Pool size at -250: ~18-22 legs on typical weekday, 30-45 on full weekend slates.

---

## Coverage Signal Architecture

### **Decision: `coverage_vs_hand` as Delta, Not Base (June 5, 2026)**

**Validation data (30 days, 1,831 hits over appearances):**
- Has vs_hand: 62.0% win rate, avg coverage_vs_hand = 66.4, avg coverage_overall = 66.0
- No vs_hand: 62.3% win rate, avg coverage_overall = 67.7

The log-odds adjustment via batting rate stats (avg/slg/obp vs pitcher handedness) is technically correct and varies meaningfully by pitcher hand per player. However it produces values within 0.5 points of overall on average and doesn't improve win rates.

**Architecture:** `coverage_overall` = gate and base signal. `coverage_vs_hand` = delta adjustment at 30% weight, capped ±3. Preserves the signal without allowing a single split to swing a score by 7 points.

**Note:** `coverage_vs_hand` is correctly NULL for strikeout props — `SPLIT_RATIO_STAT` only maps `hits`, `totalBases`, `walks` to rate stats. There is no equivalent rate stat for batter strikeout rate vs handedness in the statSplits API endpoint.

---

## Pitcher Signal Pipeline

### **Decision: Per-Start IP Filter (June 5, 2026)**

**Problem:** `pitcher_stats.py` was filtering `if ip < 50` (season total IP). At this point in the season, pitchers with 5-8 starts had ERAs of 0.73-1.77 (Ohtani, Arrighetti, Harrison) but were classified as `no_era_data` alongside true relievers. The 50 IP filter was systematically excluding the best pitchers.

**Fix:** `if starts < 3 or ip_per_start < 3.0` — requires 3+ starts averaging 3.0+ IP/start. This captures any legitimate starter regardless of total IP, while filtering true relievers (1-2 IP/appearance).

**Result:** 192 qualified starters (was ~20-25). ERA/K9/WHIP ranks now meaningful.

### **Decision: Bug 1 Fix — Position-First Pitcher Prop Detection (June 5, 2026)**

**Problem:** `enrich_legs.py` used `is_pitcher_prop_leg = position in ("SP", "RP", "P") or stat in _PITCHER_STATS`. Since `_PITCHER_STATS` included `"strikeouts"`, every batter strikeout leg was routed to the pitcher prop branch, receiving `pitcher_era=None`, `pitcher_k9=None`, and being skipped.

**Fix:** `is_pitcher_prop_leg = position in ("SP", "RP", "P")` — position is the authoritative discriminator.

### **Decision: Opposing Pitcher Ranks on Hitter Legs (June 5, 2026)**

**Problem:** `_attach_pitcher_rank_signals()` in `main.py` only attached `era_rank`, `k9_rank`, `whip_rank` to pitcher prop legs (SP/RP/P positions). All hitter legs were skipped with `continue`. The ranked signals computed from 192 qualified starters were never available to the scorer for any hitter leg.

**Fix:** Added hitter leg branch that attaches `opp_pitcher_era_rank`, `opp_pitcher_k9_rank`, `opp_pitcher_whip_rank` via `opposing_pitcher_id` (falls back to `pitcher_id`).

### **Decision: K9 Rank Signal for Batter Strikeout Props**

Use `opp_pitcher_k9_rank` (normalized rank 1-30) rather than raw `pitcher_k9` float with hardcoded thresholds. Rank signal is normalized across all 192 qualified starters; raw float thresholds (10.0/7.0) were not. Fallback to raw `pitcher_k9` when rank unavailable.

Unit test: elite K pitcher (rank ≤8) → +5, weak K pitcher (rank ≥23) → -5, no rank → 0. 10-point spread.

### **Decision: ERA Rank Removed from Enriched Scorer Scoring (Pending Revalidation)**

ERA rank signal for hits props was validated as directionally unreliable in shadow data. However the analysis was confounded by the 50 IP threshold contaminating the ranking pool. With IP threshold fixed, ERA rank needs re-evaluation after 7+ days of clean data before being re-added to scoring.

ERA rank is still computed and stored on every leg for analysis purposes.

---

## Shadow Pipeline Strategy

### **Decision: Shadow Before Promoting**

Significant scoring changes run as shadow pipeline for 5-7 days before production promotion. Shadow tables mirror production schema plus enriched signal columns. `production_batch_id` links shadow parlays to production parlays for direct A/B comparison.

### **Decision: Resolution Must Be Wired to Shadow Table**

`mlb_scored_legs_enriched.result` was NULL for all rows since pipeline inception — the morning resolver was only updating `mlb_scored_legs`. Fixed June 5: `parlay_outcome_resolver.py` now writes outcomes to `mlb_scored_legs_enriched` at all 5 resolution paths (4 void branches + won/lost). Without resolution, shadow signal validation is impossible.

---

## Enriched Scoring Signals

### **Signal 1: Blended ERA Rank (Active — computed, NOT applied to score)**
Season ERA rank blended with pitcher's last-3-start ERA rank. Computed and stored on every enriched leg. Not applied to score pending revalidation with clean data post IP-fix.

### **Signal 2: Opponent-Specific Coverage Split (Active — thin data)**
Batter's hit rate vs tonight's specific opponent (min 3 games, 25% delta weight, ±8 cap). Only 20-35% population rate — most batters haven't faced the same team 3 times yet. Will grow through the season.

### **Signal 3: Ballpark Factor (Active — validated)**
30-row `ballpark_factors` static table. Hitter props ±5. Validated: 30-point win rate spread between pitcher parks (40%) and hitter parks (70%). Strongest validated enriched signal.

### **Signal 4: Team SO Rank (REMOVED June 1)**
Pitcher SO props cut from whitelist made this signal irrelevant.

---

## Outcome Resolution

### **Decision: Fail-Safe EEP with Explicit Presence Check (June 1, 2026)**
EEP only fires when `plateAppearances` / `battersFaced` explicitly present in API response. `game_not_found` defers parlay rather than voiding leg.

### **Decision: Shadow Table Resolution Parity (June 5, 2026)**
All 5 void/won/lost paths in `parlay_outcome_resolver.py` now write to both `mlb_scored_legs` (production) and `mlb_scored_legs_enriched` (shadow). Join key: `(player_name, stat, direction, run_date, line)`. Note: `id` column is NULL in enriched table — all writes use natural key, not `id`.

---

## Database Design

### **Critical Type Rules**
- `mlb_scored_legs.run_date`: TEXT — use string comparisons
- `mlb_scored_legs.odds`: TEXT — cast to numeric for math: `odds::numeric`
- `mlb_parlay_recommendations_v2.run_date`: DATE — no cast needed
- `mlb_training_data.result`: `'hit'/'miss'/'void'` — different from parlay tables' `'won'/'lost'`
- `mlb_scored_legs_enriched.id`: NULL for all rows — use natural key for all writes

### **Anti-Pattern: ORDER BY before UNION ALL**
```sql
-- WRONG — causes syntax error
SELECT ... FROM table_a GROUP BY x ORDER BY x
UNION ALL
SELECT ... FROM table_b GROUP BY x ORDER BY x;

-- CORRECT — single ORDER BY at the very end
SELECT ... FROM table_a GROUP BY x
UNION ALL
SELECT ... FROM table_b GROUP BY x
ORDER BY x;

-- ALSO CORRECT — combine date ranges on same table with WHERE/OR
SELECT ... FROM mlb_scored_legs
WHERE (run_date >= '2026-05-26' AND run_date < '2026-05-29')
   OR run_date >= '2026-06-01'
GROUP BY ... ORDER BY ...;
```

---

## Pipeline Architecture

### **3× Daily + Shadow After Every Run**
- 9:00 AM ET — Resolution + fresh parlays (shadow runs after)
- 12:00 PM ET — Midday refresh (shadow runs after)
- 5:30 PM ET — Evening refresh (shadow runs after)
- Manual Regenerate also triggers shadow

---

## Lessons Learned

1. **Coverage alone is not edge.** The book also knows historical coverage rates. Edge exists only where predicted win probability exceeds the book's implied probability.
2. **Flat coverage signals mean cut, not raise the floor.** If win rate is flat across all coverage buckets with 500+ appearances, the signal doesn't exist.
3. **Pool size determines parlay structure.** Design around what the data actually provides daily.
4. **Sort order determines parlay quality, not just efficiency.** Sorting by odds for B&B pruning efficiency caused systematic selection of low-quality cheap-odds legs over high-quality expensive-odds legs.
5. **Candidate limit determines search depth.** MAX_CANDIDATES=15 caused the B&B to stop exploring after finding 15 combinations built from the same top-of-sorted-list legs. 50 candidates forces genuine pool exploration.
6. **IP thresholds can silently exclude the best data.** A 50-inning season minimum excluded Ohtani, Cole, Harrison from the pitcher ranking pool. Always validate that filtering logic isn't systematically biasing against edge cases.
7. **Function names can mislead.** `_attach_pitcher_rank_signals()` sounds like it attaches pitcher signals — but it was only attaching signals to pitcher prop legs, not to hitter legs facing pitchers. Always verify which legs a function actually processes.
8. **Shadow pipeline must have outcome resolution.** Shadow scoring data without resolved outcomes is completely unvalidatable. Resolution must be wired to shadow tables from day one.
9. **Resolution bugs compound quickly.** The `id=NULL` issue in the enriched table caused 1,240 rows to silently not update despite reporting success. Always verify rowcount after bulk updates.
10. **stat-name-based routing is fragile.** Using `stat in _PITCHER_STATS` to detect pitcher props caused all batter strikeout legs to be misrouted. Position is the authoritative discriminator for prop type.
11. **API defaults can silently corrupt logic.** `batting.get("plateAppearances", 0)` looks safe but causes false-voids when API returns empty dict. Use `is not None` guards for boolean conditions.

---

## Future Considerations

### **1. ERA Rank Re-Evaluation (June 12+)**
With 192 qualified starters now ranked, re-run ERA tier win rate analysis on shadow data. If ace ERA (rank ≤8) correlates with lower hit over win rates (as theoretically expected), add ERA rank back to enriched scorer for hits props.

### **2. K9 Rank Validation for Strikeout Props**
First clean measurement of K9 rank signal effectiveness. Before Session 5, Bug 1 meant `pitcher_k9` was NULL for all strikeout legs — K9 signal never fired. After June 5, collect 2+ weeks of outcome data and run K9 tier win rate analysis.

### **3. Hits Under Investigation**
0 hits under legs in today's pool. Either the 70% coverage gate is too strict for this prop or there simply aren't enough qualifying legs on typical slates. Re-evaluate after 2 weeks.

### **4. Promote Enriched to Production**
After 7-day shadow comparison confirms enriched scoring improves win rates vs production. Target: June 12-15 comparison analysis.

### **5. Learning Loop**
Once 500+ resolved legs exist under the new prop set and scoring system, run regression on coverage signals vs outcomes. Recalibrate signal weights from data rather than principled priors.

### **6. Gate 3 — Minimum `coverage_recent_10` Floor**
Block legs where `coverage_recent_10 < 50%` regardless of `coverage_overall`. Prevents cold-streak legs from sneaking through on strong season averages. Deferred — validate consistency signal effectiveness first.

---

**Architecture Status:** ✅ STABLE — Full Signal Pipeline Operational
**Last Major Change:** June 5, 2026 (Pitcher signal pipeline fixes, parlay builder sort order)
**Next Architecture Review:** June 2026 (After ERA rank revalidation + shadow comparison)
