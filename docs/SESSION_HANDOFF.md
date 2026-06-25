# MLB Parlay Agent — Session Handoff
**Last Updated:** June 25, 2026 (Session 15 — Comprehensive Performance Review + Scoring Overhaul)

## Current Status
✅ **OPERATIONAL — SESSION 15 DEPLOYED**
✅ **WHIP rank removed from production hits scorer — was creating false 80+ bucket at 47.4% win rate**
✅ **hits/under gate raised from 40% to 65% in main.py and parlay_builder.py**
✅ **Starter-only pitcher rank pool added — eliminates reliever contamination**
✅ **TB/under enriched signals fixed — park_factor and opp_coverage now populating**
✅ **Vulnerability thresholds recalibrated — symmetric penalties, weak pitcher penalty added**
✅ **Player cap fallback fixed — now checks production-eligible (non-TB) legs not total pool**
✅ **All changes deployed across 3 commits: b7b1038, 97fbcb2, 9eed486**
⚠️ **hits/over ~80% coverage ceiling — data confirmed, not yet implemented**
⚠️ **K/9 and WHIP signals need re-evaluation after starter-only ranks accumulate data (~2 weeks)**
⚠️ **TB/under enriched signals now firing — promotion decision pending shadow data validation**

---

## What Happened on June 25, 2026 (Session 15)

### Comprehensive Performance Review (June 18–24)

Full data analysis across production and shadow pipelines. Key findings:

**Production parlay win rate:** 15.2% on 33 resolved (breakeven ~18.2%) — slightly below, with 59 voided parlays.

**Scored leg win rates (June 18–24):**
- SO/over: 64.9% win rate, +32.1pp above breakeven ✅
- hits/over: 59.9% win rate, −7.0pp below breakeven ⚠️
- hits/under: 50.1% win rate, −6.3pp below breakeven ❌
- TB/under (shadow only): 55.7% win rate, +16.6pp above breakeven

**CLV first read (June 18–24):**
- SO/over: +1.05% CLV — confirmed genuine edge
- hits/over: +0.46% CLV — weakly positive
- hits/under: −0.45% CLV — confirmed negative edge
- TB/under: −0.51% CLV — book pricing it in

**Shadow vs production (June 18–24):** Shadow 12.4% vs production 15.2% — shadow underperformed due to TB/under with broken enriched signals taking 41% of selections.

**Score inversion finding:** hits/over legs scoring 80+ won at only 47.4% (20pp below 66.9% breakeven). Root cause: WHIP rank boost was pushing legs with weak opposing pitchers into the 80+ bucket. This was the primary production harm fixed this session.

---

### Fixes Implemented

#### Fix 1 — WHIP Rank Removed from Production Hits Scorer
**File:** `src/engine/simple_scorer.py`
**Problem:** WHIP rank signal was applying a positive adjustment for high-WHIP (weak) pitchers on hits/over legs. Data showed weak WHIP pitchers (rank 161+) allowed the fewest actual hits (0.77 avg). The rank pool is contaminated by relievers with inflated season WHIPs. This was creating false 80+ composite scores that the parlay builder was prioritizing — those legs won at 47.4%.
**Fix:** Removed the entire WHIP rank block (~15 lines). Added rationale comment. WHIP remains a component of pitcher_vulnerability in enriched_scorer.

#### Fix 2 — hits/under Gate Raised from 40% to 65%
**Files:** `main.py`, `src/engine/parlay_builder.py`
**Problem:** 411 hits/under legs at 40% gate averaged 48.8% coverage at 50.1% win rate vs 56.4% breakeven (−6.3pp). 1,832 legs below 55% coverage averaged 39.3% win rate.
**Fix:** Gate raised to 65% in both `_find_qualifying_legs()` and `MIN_COV_POOL_UNDER`. The 14 legs that made it into parlays already averaged 66.0% coverage — they all pass the new gate.

#### Fix 3 — Starter-Only Pitcher Rank Pool
**Files:** `src/apis/pitcher_stats.py`, `main.py`, `src/pipelines/run_enriched_pipeline.py`
**Problem:** Full-season rank pool mixes starters and relievers. Rank 161+ is contaminated by relievers with inflated WHIPs/K9s from small samples, causing anomalous signal at both extremes.
**Fix:** New `get_starter_ranks_for_today()` function builds ERA/K9/WHIP ranks restricted to tonight's confirmed starters only (1–N where N = starters with available stats). Used as primary source for `opp_pitcher_whip_rank` and `opp_pitcher_k9_rank` with full-pool fallback. Log line: `[pitcher_stats] Today's starter ranks: 18 pitchers | ERA/K9/WHIP ranks 1–18`.

#### Fix 4 — TB/under Enriched Signals (3 bugs)
**File:** `src/engine/enriched_scorer.py`
**Bug 1:** `"totalBases"` missing from `_PROP_STAT_MAP` → opponent-specific coverage always None. Fixed: added `"totalBases": "totalBases"`.
**Bug 2:** `_compute_park_adjustment()` had no `totalBases` branch → park factor always None for 619 TB/under legs. Fixed: added `elif stat == "totalBases"` branch with same formula as hits.
**Bug 3:** Park adjustment applied without direction inversion → hitter parks boosted hits/under and TB/under scores incorrectly. Fixed: `score -= park_adjustment` for `direction == "under"`, `score += park_adjustment` for overs.

#### Fix 5 — Vulnerability Threshold Recalibration
**File:** `src/engine/enriched_scorer.py`
**Problem:** Only penalized elite pitchers (vuln < 0.25). Data showed weak pitchers (≥0.65) won at only 50.6% — 11.8pp below the 0.20–0.49 sweet spot (64–68%). The −10 threshold at vuln < 0.15 had only 19 legs supporting it.
**Fix:** Symmetric penalties around the 0.20–0.49 sweet spot:
- vuln < 0.20 → −6 (elite pitcher)
- vuln < 0.30 → −3 (good pitcher)
- vuln ≥ 0.65 → −6 (weak pitcher — book prices it in)
- vuln ≥ 0.50 → −3 (below-avg pitcher)

#### Fix 6 — Player Cap Fallback (Production-Eligible Legs)
**File:** `main.py`
**Problem (Bug A):** `"orig_qualifying_legs" in dir()` is always False — `dir()` checks module attributes not local variables. Fallback never fired. Fixed in commit `97fbcb2`.
**Problem (Bug B, root cause):** Even with Bug A fixed, the fallback checked total qualifying_legs (41 legs looked healthy) but 31 of those were TB/under excluded from production parlays in Step 8, leaving only 3 usable legs — not enough for a 4-leg parlay.
**Fix (commit 9eed486):** Fallback now simulates TB exclusion before checking thresholds. Computes `production_eligible` (non-TB legs) and `production_overs`. Triggers if `< 12 non-TB legs` or `< 6 production overs`. Confirmed working: `[player_cap] Production pool too thin after cap (11 non-TB legs, 11 overs) — restoring full pool`.

---

## Session 15 Commits

| Commit | Message |
|--------|---------|
| `b7b1038` | fix: scoring overhaul — remove WHIP from production hits scorer, raise hits/under gate, fix TB/under enriched signals, recalibrate vulnerability thresholds, add starter-only rank pool |
| `97fbcb2` | fix: remove dead conditional in player cap fallback — orig_qualifying_legs always defined |
| `9eed486` | fix: player cap fallback checks production-eligible legs not total pool |

---

## Pending Items — Next Session

### 1. Add hits/over Coverage Ceiling at ~80% (High Priority)
Data confirmed: win rate peaks at 75–80% (71.9%), drops to 61.4% at 80–84% (44 legs), 50.0% at 84–90%. Add simple filter in `main.py` `_find_qualifying_legs()`:
```python
if stat == "hits" and direction == "over" and coverage_overall_raw > 80.0:
    continue
```
Do NOT apply universally — SO/over is monotonically improving through 84%+.

### 2. Re-evaluate K/9 and WHIP Signals After Starter-Only Data Accumulates (~July 9)
The starter-only rank pool started June 25. Give it 2 weeks of data before evaluating whether the signals now show correct gradients. Key query to run:
```sql
SELECT
    CASE WHEN pitcher_k9_rank <= 6 THEN '1_elite'
         WHEN pitcher_k9_rank <= 12 THEN '2_good'
         WHEN pitcher_k9_rank <= 15 THEN '3_avg'
         ELSE '4_weak' END as k9_bucket,
    COUNT(*) FILTER (WHERE result IN ('won','lost')) as resolved,
    (COUNT(*) FILTER (WHERE result='won') * 100.0 /
     NULLIF(COUNT(*) FILTER (WHERE result IN ('won','lost')), 0))::numeric(5,1) as win_rate
FROM mlb_scored_legs_enriched
WHERE run_date >= '2026-06-25'
  AND stat = 'strikeouts' AND direction = 'over'
GROUP BY k9_bucket ORDER BY k9_bucket;
```
Note: with 18 starters/night, ranks now run 1–18, so bucket thresholds should reflect ~6/12/15 splits not 40/80/120.

### 3. TB/under Production Promotion Decision (~July 9)
Shadow edge: 67.4% win rate (89 legs), +8.9pp above breakeven. Now that park_factor and opp_coverage signals are fixed, let shadow accumulate 2 weeks of clean enriched data before promotion decision. Recheck ~July 9.

### 4. Vulnerability Calibration Check (~July 2)
Run hits/over vulnerability gradient query with June 25+ data to validate the recalibrated thresholds are working. Specifically check the ≥0.65 bucket is now being correctly penalized.

### 5. Stack Bonus Evaluation (~July 1)
Last data: 72.7% vs 55.3% on only 11 legs. Recheck after July 1.

### 6. CLV Second Read (~July 5)
First clean CLV read was June 18–24. Run the full CLV query again after July 5 for a larger window:
```sql
SELECT stat, direction,
    COUNT(*) FILTER (WHERE closing_odds IS NOT NULL) AS captured,
    (AVG(CASE WHEN closing_odds IS NULL OR odds IS NULL THEN NULL
         ELSE (CASE WHEN closing_odds::numeric < 0
               THEN ABS(closing_odds::numeric)/(ABS(closing_odds::numeric)+100)
               ELSE 100/(closing_odds::numeric+100) END)
            - (CASE WHEN odds::numeric < 0
               THEN ABS(odds::numeric)/(ABS(odds::numeric)+100)
               ELSE 100/(odds::numeric+100) END)
         END) * 100)::numeric(5,2) AS avg_clv_pct
FROM mlb_scored_legs
WHERE run_date >= '2026-06-18' AND closing_odds IS NOT NULL
GROUP BY stat, direction ORDER BY avg_clv_pct DESC;
```

### 7. Project File Cleanup
Retire stale files from Project Knowledge:
- `SYSTEM_DIAGNOSTIC_REPORT_2026-05-12.md`
- `CHAT_HANDOFF_2026-05-28.md`
- `MLB_Scored_Legs_Table_Schema.csv`
- `README_10.md` (superseded by BUILD_STATUS.md)

---

## System Health Indicators

### Green Lights
✅ All 3 commits deployed and verified on Railway
✅ Starter-only rank pool firing (18 pitchers ranked tonight)
✅ TB/under enriched signals confirmed populating (park_factor, opp_coverage no longer null)
✅ Player cap fallback confirmed firing correctly
✅ Parlay built after fallback: +586 (Kevin McGonigle, Juan Soto, Carson Benge SO, Pavin Smith)
✅ CLV tracking live — SO/over at +1.05%, confirmed genuine edge
✅ SO/over confirmed edge prop — monotonically improving through 84%+ coverage
✅ Shadow resolution and enriched pipeline running correctly

### Yellow Flags
⚠️ hits/over ~80% coverage ceiling pending implementation
⚠️ K/9 and WHIP signals need re-evaluation with starter-only data (2 weeks)
⚠️ TB/under promotion pending 2 weeks of clean shadow signal data
⚠️ Vulnerability recalibration needs validation with June 25+ data
⚠️ hits/over -7.0pp below breakeven on June 18–24 — CLV weakly positive (+0.46%), monitoring
⚠️ Void rate still elevated (59 voided vs 33 resolved June 18–24) — CLR pool exhaustion on thin slates

### Red Flags
None currently

---

**Last Review:** June 25, 2026
**System Status:** ✅ Operational — Scoring Overhaul Deployed
**Next Review:** July 2, 2026 — vulnerability calibration, stack bonus, starter-only rank first read
**Pending Decisions:** hits/over ceiling (next session), TB/under promotion (~July 9), K/9/WHIP re-evaluation (~July 9)
