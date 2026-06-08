# MLB Parlay Agent — Architecture Decisions
**Last Updated:** June 8, 2026 (Session 6 — Performance Review + Manual Regen Diversity Fix)

---

## Table of Contents
1. [Core Philosophy](#core-philosophy)
2. [Scoring System Evolution](#scoring-system-evolution)
3. [Prop Selection — Data-Driven Whitelist](#prop-selection--data-driven-whitelist)
4. [Coverage Gating Architecture](#coverage-gating-architecture)
5. [Parlay Construction Evolution](#parlay-construction-evolution)
6. [Manual Regen Player Diversity](#manual-regen-player-diversity)
7. [Odds Cap Decision](#odds-cap-decision)
8. [Coverage Signal Architecture](#coverage-signal-architecture)
9. [Pitcher Signal Pipeline](#pitcher-signal-pipeline)
10. [Shadow Pipeline Strategy](#shadow-pipeline-strategy)
11. [Enriched Scoring Signals](#enriched-scoring-signals)
12. [Outcome Resolution](#outcome-resolution)
13. [Database Design](#database-design)
14. [Pipeline Architecture](#pipeline-architecture)
15. [Lessons Learned](#lessons-learned)
16. [Future Considerations](#future-considerations)

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
score = coverage_overall          # always the base
     + coverage_vs_hand_delta     # ±3 max (30% weight of delta from overall)
     + consistency_adjustment     # gap-based ±6/±4/±2/+2/+1
     + era_adjustment             # ±5 for hits props (raw pitcher_era — pending revalidation)
     + k9_rank_adjustment         # ±5 for SO props (opp_pitcher_k9_rank, raw fallback)
     + lineup_stability           # -5 if lineup_consistency < 0.50
```

### **Key Scoring Decision: `coverage_overall` Always Base (June 5, 2026)**

`coverage_vs_hand` produces values within 0.5 points of `coverage_overall` on average, with identical win rates (62.0% vs 62.3%). Demoted to delta adjustment at 30% weight, capped ±3. All legs stay on a comparable scale regardless of handedness data availability.

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

**Removed props and reasons:**

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

Gates use `coverage_overall` (unbiased season rate). Scoring uses `coverage_vs_hand` only as a delta adjustment. These serve different roles.

---

## Parlay Construction Evolution

### **Phase 1: ML-based (April–May 2026) — ABANDONED**
ML composite score drove selection. Inverted signal caused high-score legs to lose more.

### **Phase 2: Anchor/Swing Two-Pool (May 28, 2026) — REPLACED**
3-anchor + 2-swing, 5-leg parlays. Eliminated June 1 — with only 3 validated prop types all priced -250 to +150, two-pool added no value.

### **Phase 3: Single Flat Pool 4-Leg +400–+700 (June 1, 2026)**
Eliminated two-pool system. All legs compete in one pool sorted by composite score.

### **Phase 3.1: Score-Sort + MAX_CANDIDATES 50 (June 5, 2026) — CURRENT**

**Problem:** B&B was sorted by decimal odds descending for pruning efficiency. Cheap-odds, low-quality legs (Cruz score 59, -148 odds) were explored before expensive-odds, high-quality legs (Waldschmidt score 78, -176 odds). MAX_CANDIDATES=15 meant the builder stopped after 15 near-identical combinations.

**Fix:**
1. Sort pool by `composite_score` DESC — highest quality legs explored first
2. MAX_CANDIDATES 15→50 — find 50 valid combinations before stopping
3. B&B pruning bounds via `suffix_dec_sorted` — valid under any sort order

**Why `build_hybrid_parlays()` retained:** Backward-compat wrapper for enriched pipeline and external callers.

---

## Manual Regen Player Diversity

### **Decision: Exclude Prior-Run Players from Manual Regenerate (June 8, 2026)**

**Problem observed on June 4:** Matt Olson appeared in 5 of 7 manual parlays. When Olson went 0-for-day on hits, all 5 parlays lost. Hitting Regenerate Now was returning the same high-score players from the most recent prior run (automated or manual), offering no meaningful diversification.

**Options considered:**

| Option | Description | Decision |
|---|---|---|
| A — Global daily dedup | Player appears once anywhere today | Rejected — burns best players in 9am, starves later runs |
| B — One per batch | Player appears once per automated run | Already implemented at intra-batch level |
| C — Cap appearances per run | Max N parlays per player per run | Deferred — too complex for unclear benefit |
| **Manual-only exclusion** | **Regen excludes players from prior run; auto runs unaffected** | **Chosen** |

**Implementation:** In `run_pipeline()` when `source == "manual"`:
1. Query `mlb_parlay_legs_v2` for distinct player names from the most recent `batch_id` today
2. Filter those players out of `qualifying_legs` before `build_parlays()`
3. Fallback to full pool if fewer than 4 legs remain after filtering

**Key behaviors:**
- Automated pipeline runs (9am, 12pm, 5:30pm): no exclusion, full pool always
- First manual regen of the day: no prior batch → full pool (correct)
- Subsequent manual regens: excludes players from the immediately preceding run
- Each Regenerate press gives genuinely fresh picks from a different player set

**Fallback threshold:** Currently 4 legs (absolute minimum). Monitor Railway logs for `[manual_regen] Pool too thin` — if this fires regularly on thin slates, raise to 8-10.

**Commit:** `cd52b3a`

---

## Odds Cap Decision

### **Decision: -250 Hard Cap Per Leg (June 1, 2026)**

At -250, breakeven is 71.4%. Validated hits over win rate at 75-79% coverage is 75.4%. Edge exists. At -300, breakeven is 75.0% — edge disappears for most legs. Pool size at -250: ~18-22 legs on typical weekday, 30-45 on full weekend slates.

---

## Coverage Signal Architecture

### **Decision: `coverage_vs_hand` as Delta, Not Base (June 5, 2026)**

Validation on 30 days / 1,831 hits over appearances: win rates identical with vs without `coverage_vs_hand` (62.0% vs 62.3%). Log-odds adjustment produces values within 0.5 points of `coverage_overall` on average.

**Architecture:** `coverage_overall` = gate and base. `coverage_vs_hand` = delta at 30% weight, ±3 cap.

**Note:** `coverage_vs_hand` is correctly NULL for strikeout props — no equivalent rate stat for batter strikeout rate vs handedness in the statSplits API endpoint.

---

## Pitcher Signal Pipeline

### **Decision: Per-Start IP Filter (June 5, 2026)**

Season total IP filter (`ip < 50`) excluded Ohtani, Arrighetti, Harrison from ranking pool early in the season. Fixed to per-start filter: 3+ starts, 3.0+ IP/start. Pool: ~20-25 → 192 qualified starters.

### **Decision: Position-First Pitcher Prop Detection (June 5, 2026)**

`enrich_legs.py` used `stat in _PITCHER_STATS` which included `"strikeouts"`, misrouting all batter SO legs to the pitcher prop branch (NULL pitcher data). Fixed to `position in ("SP", "RP", "P")` — position is the authoritative discriminator.

### **Decision: Opposing Pitcher Ranks on Hitter Legs (June 5, 2026)**

`_attach_pitcher_rank_signals()` was only processing pitcher prop legs. Fixed to also attach `opp_pitcher_era_rank`, `opp_pitcher_k9_rank`, `opp_pitcher_whip_rank` to all hitter legs via `opposing_pitcher_id`.

### **Decision: K9 Rank Signal for Batter Strikeout Props**

Use `opp_pitcher_k9_rank` (normalized 1-30 rank) rather than raw `pitcher_k9` float with hardcoded thresholds. Fallback to raw when rank unavailable. 10-point spread: elite K pitcher (rank ≤8) → +5, weak (rank ≥23) → -5.

### **Decision: ERA Rank Removed from Enriched Scorer (Pending Revalidation)**

ERA rank signal was directionally unreliable in shadow data, confounded by the 50 IP threshold contaminating the pool. With threshold fixed, needs 7+ days clean data. Still computed and stored for analysis.

---

## Shadow Pipeline Strategy

### **Decision: Shadow Before Promoting**

Significant scoring changes run as shadow pipeline for 5-7 days before production promotion. Shadow tables mirror production schema plus enriched signal columns. `production_batch_id` links shadow parlays to production for A/B comparison.

### **Decision: Resolution Must Be Wired to Shadow Table**

`mlb_scored_legs_enriched.result` was NULL for all rows since pipeline inception. Fixed June 5 — resolver now writes outcomes to `mlb_scored_legs_enriched` at all 5 resolution paths. Note: `id` column is NULL in enriched table — all writes use natural key `(player_name, stat, direction, run_date, line)`.

---

## Enriched Scoring Signals

### **Signal 1: Blended ERA Rank (Computed — NOT applied to score)**
Season ERA rank × 0.5 + last-3-start ERA rank × 0.5. Stored on all hits legs. Pending revalidation after IP threshold fix.

### **Signal 2: Opponent-Specific Coverage (Active — thin data)**
Batter's hit rate vs tonight's specific opponent (min 3 games, 25% delta weight, ±8 cap). ~20-35% population rate early season.

### **Signal 3: Ballpark Factor (Active — validated)**
30-row `ballpark_factors` static table. Validated: 30-point win rate spread between pitcher parks (40%) and hitter parks (70%). Strongest validated enriched signal.

---

## Outcome Resolution

### **Decision: Fail-Safe EEP with Explicit Presence Check (June 1, 2026)**
EEP fires only when `plateAppearances`/`battersFaced` explicitly present in API response. `game_not_found` defers parlay rather than voiding leg.

### **Decision: Shadow Table Resolution Parity (June 5, 2026)**
All 5 void/won/lost paths write to both `mlb_scored_legs` and `mlb_scored_legs_enriched`.

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
-- WRONG
SELECT ... ORDER BY x
UNION ALL
SELECT ... ORDER BY x;

-- CORRECT — single ORDER BY at the end
SELECT ...
UNION ALL
SELECT ...
ORDER BY x;
```

---

## Pipeline Architecture

### **3× Daily + Shadow After Every Run**
- 9:00 AM ET — Resolution + fresh parlays (shadow runs after)
- 12:00 PM ET — Midday refresh (shadow runs after)
- 5:30 PM ET — Evening refresh (shadow runs after)
- Manual Regenerate — excludes prior-run players, shadow runs after

---

## Lessons Learned

1. **Coverage alone is not edge.** The book also knows historical coverage rates. Edge exists only where predicted win probability exceeds the book's implied probability.
2. **Flat coverage signals mean cut, not raise the floor.** Flat win rate across all coverage buckets with 500+ appearances = signal doesn't exist.
3. **Pool size determines parlay structure.** Design around what the data actually provides daily.
4. **Sort order determines parlay quality, not just efficiency.** Sorting by odds for B&B pruning caused systematic selection of low-quality cheap-odds legs.
5. **Candidate limit determines search depth.** MAX_CANDIDATES=15 caused B&B to stop after finding 15 combinations built from the same top legs.
6. **IP thresholds can silently exclude the best data.** 50-inning season minimum excluded Ohtani, Cole, Harrison from the pitcher ranking pool.
7. **Function names can mislead.** `_attach_pitcher_rank_signals()` only attached to pitcher prop legs, not hitter legs facing pitchers.
8. **Shadow pipeline must have outcome resolution.** Shadow scoring data without resolved outcomes is completely unvalidatable.
9. **Resolution bugs compound quickly.** The `id=NULL` issue caused 1,240 rows to silently not update.
10. **stat-name-based routing is fragile.** Using `stat in _PITCHER_STATS` for pitcher prop detection misrouted all batter strikeout legs.
11. **API defaults can silently corrupt logic.** Use `is not None` guards for boolean conditions.
12. **High-score player saturation kills manual parlays.** Without per-run exclusion, the same players dominate every Regenerate run. One bad day from a saturated player cascades across all manual parlays.
13. **Automated and manual runs need different diversity rules.** Auto runs want the best available players on every run. Manual regens want fresh picks — different goals require different logic.

---

## Future Considerations

### **1. Lineup Confirmation Gate (High Priority)**
Anthony Volpe voided June 4 because he wasn't in the lineup. A player not in the confirmed lineup card should be excluded from the pool entirely. Blueprint Phase 3 item — now demonstrated impact justifies prioritizing.

### **2. Manual Regen Fallback Threshold**
Current fallback is 4 legs (absolute minimum). If `[manual_regen] Pool too thin` logs fire regularly on thin slates, raise to 8-10 to ensure meaningful parlay diversity within the filtered pool.

### **3. SO Enrichment NaN Investigation**
~60% of strikeout legs have `pitcher_name = NaN`. If timing/ordering issue, fix the enrichment sequence. If game_pk mismatch, fix the lookup key.

### **4. ERA Rank Re-Evaluation (June 12+)**
With 192 qualified starters now ranked, re-run ERA tier win rate analysis. If ace ERA correlates with lower hits over win rates, add back to enriched scorer.

### **5. Promote Enriched to Production**
After 7-day shadow comparison confirms enriched scoring improves win rates. Target: June 12-15.

### **6. Learning Loop**
Once 500+ resolved legs exist under the new prop set and scoring system, run regression on coverage signals vs outcomes. Recalibrate signal weights from data rather than principled priors.

### **7. Gate 3 — Minimum `coverage_recent_10` Floor**
Block legs where `coverage_recent_10 < 50%` regardless of `coverage_overall`. Prevents cold-streak legs sneaking through on strong season averages. Deferred pending consistency signal validation.

---

**Architecture Status:** ✅ STABLE
**Last Major Change:** June 8, 2026 (Manual regen player exclusion)
**Next Architecture Review:** June 2026 (After ERA rank revalidation + shadow comparison)
