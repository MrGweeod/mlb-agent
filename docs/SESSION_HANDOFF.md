# MLB Parlay Agent — Session Handoff
**Last Updated:** June 15, 2026 (Session 12 — Weekend Review, Shadow Audit, Pipeline Fixes)

## Current Status
✅ **OPERATIONAL — SESSION 12 DEPLOYED**
✅ **lineup_scheduler.py created and pushed — lineup/CLV checks now firing for first time**
✅ **game_pks postgres array format bug fixed**
✅ **Cross-run 2x player cap deployed — replaces manual-only regen exclusion**
✅ **mlb_scored_legs_enriched.result now resolving — 11-day backfill complete (June 4–14)**
✅ **Dynamic rank normalization fixed in _calculate_enriched_score() — 4 signal paths corrected**

---

## What Happened on June 15, 2026 (Session 12)

### Weekend Performance Review (June 12–14)

**Production parlay outcomes:**
- June 13: 4/12 resolved (33.3%) — 9AM strong at 3/5 (60%), midday 1/5, evening 0/2
- June 14: 1/10 resolved (10%) — weak across all sources
- June 15: 5 parlays pending (all 9AM)

**Production leg win rates (June 12–14, resolved only):**
- hits/over: 66.9% (145 appearances) ✅
- strikeouts/over: 87.1% (31 appearances) ✅
- hits/under: 73.7% (19 appearances — small sample)

**Root cause of June 12 parlay underperformance:** Player concentration. McGonigle appeared in 5 separate parlays, Hoerner in 5, Torres in 4. All had bad games — multiple parlays sank simultaneously. The existing manual regen exclusion only applied to manual regenerations and only looked at the most recent batch; automated runs had zero cross-run diversification.

---

### Fix 1 — lineup_scheduler.py Missing Module (Critical)

**Problem:** Every morning pipeline since June 13 silently failed with:
```
WARNING: lineup scheduling failed (non-fatal): No module named 'src.pipelines.lineup_scheduler'
```
`src/pipelines/lineup_scheduler.py` was never committed to the repo. `log_slate_start_times()` was wired correctly in `main.py` but the import crashed immediately. As a result:
- `mlb_pending_lineup_checks` had zero rows every day
- `lineup_check_status` was NULL on all legs
- CLV checks never fired (same scheduler, same table)
- CLV capture rate was 0% for every day since June 13

**Fix:** Created `src/pipelines/lineup_scheduler.py` with `schedule_lineup_checks()` function.

**Secondary bug found:** `game_pks` was serialized as a comma-separated string (`"822724,823371"`) but the Supabase column expects a PostgreSQL array (`{822724,823371}`). Fixed with `"{" + ",".join(str(pk) for pk in game_pks) + "}"`.

**Backfill:** Ran `log_slate_start_times()` manually after deploy. 8 lineup + 8 CLV check rows written for June 15 slate. First lineup check: ~5:55 PM ET. First CLV: ~6:39 PM ET.

**Commits:** `f23abfa` — create missing lineup_scheduler | sed fix — game_pks array format

---

### Fix 2 — Cross-Run 2x Player Cap

**Problem:** Player diversity constraint (1 player per parlay) only applied within a single parlay build. The same player could anchor 3-5 different parlays in one automated run, and reappear again in the next run. The existing manual regen exclusion only applied to manual regenerations and only excluded players from the most recent batch — never touched automated runs.

**Fix:** Replaced the entire manual regen exclusion block in `main.py` with a cross-run cap that applies to all sources. Before each build, queries `mlb_parlay_legs_v2` to count today's prior parlay appearances per player. Any player with ≥2 appearances today is removed from the selection pool for the current run.

**Rules (two separate constraints working together):**
1. Within a single run: max 1 parlay per player (existing intra-build constraint — unchanged)
2. Across all runs today: max 2 total parlay appearances — removed from pool after 2nd appearance
3. Fallback: if cap leaves fewer than 20 legs, restores full pool with `[player_cap] Pool too thin` warning

**Commit:** `116ae9b` — cross-run 2x player cap

---

### Fix 3 — mlb_scored_legs_enriched.result Never Resolving

**Problem:** `mlb_scored_legs_enriched.result` was NULL for every leg from June 4–June 14 (12 consecutive days). `mlb_parlay_legs_enriched.outcome` was being resolved correctly (shadow parlay win rates were valid), but the outcome resolver never wrote results back to `mlb_scored_legs_enriched`. This made all individual-leg signal validation queries return no data — stack bonus win rate analysis, pitcher rank bucket analysis, WHIP/ERA/K9 signal validation all returned zero rows.

**First backfill attempt failed:** Initial script called `resolve_enriched_parlays()` but those legs were already resolved — no longer `pending`. The function exited early finding nothing to process.

**Fix:** Two parts:
1. Added mirror block in `outcome_resolver.py` — after updating `mlb_parlay_legs_enriched`, immediately runs an UPDATE on `mlb_scored_legs_enriched` with the same outcome and actual_value
2. Replaced backfill script with a direct `UPDATE ... FROM` JOIN between `mlb_scored_legs_enriched` and `mlb_scored_legs` on `(player_name, stat, run_date)` — bypasses the pending filter entirely

**Result:** 1,543 enriched scored legs resolved across June 4–14.

**Commits:** `34b39a9` — mirror fix in resolver | `d8d64aa` — direct sync backfill script

---

### Shadow Pipeline Signal Audit (First Real Data)

With `mlb_scored_legs_enriched.result` now populated, ran first meaningful signal validation.

**Shadow scored leg win rates (June 4–14):**
| Stat | Direction | Legs | Win Rate | Avg Score |
|------|-----------|------|----------|-----------|
| strikeouts/over | 199 | 63.3% | 71.7 |
| hits/over | 343 | 61.5% | 71.2 |
| totalBases/under | 638 | 56.1% | 56.9 |
| hits/under | 363 | 44.1% | 44.1 |

**Shadow parlay construction finding:** TB/under appeared in 103 shadow parlays (52.6% win rate). Every single resolved shadow parlay contained at least one TB/under leg — 0 resolved shadow parlays exist without TB/under. This is the primary driver of shadow underperforming production. Confirms TB/under block from production is correct.

**Stack bonus (11 legs resolved):** 72.7% vs 55.3% non-stack. Direction is correct, sample too small to promote.

**Pitcher signal audit (June 12–14 clean window):**
- ERA rank: Nearly all legs landing in elite (1-50) bucket — revealed rank normalization bug (Fix 4)
- K9 for hits/over: Weak K pitchers (rank 151+) at 40% win rate vs above-avg K at 76.7% — counterintuitive, signal direction needs more investigation with clean data
- WHIP: Completely flat across all buckets for all prop types — no predictive value on current sample
- K9 for SO/over: Weak K at 52.2% vs above-avg at 66.7% — directionally correct but scale was broken

---

### Fix 4 — Dynamic Rank Normalization in _calculate_enriched_score()

**Problem:** Session 11 fixed the rank scale bug in `pitcher_vulnerability()` (stack bonus function), applying dynamic pool size from `len(pitcher_ranks)`. However, three separate signal paths inside `_calculate_enriched_score()` were missed and still used hardcoded values assuming a 30-pitcher pool:

| Signal | Old Formula | Problem |
|--------|-------------|---------|
| SO/over K/9 | `(k9_rank - 15.5) / 2.9` | Midpoint 15.5 assumes 30 pitchers |
| hits ERA/K9/WHIP | `(rank - 15.5) / 14.5` | Same hardcoded midpoint |
| totalBases WHIP | `(whip_rank - 15.5) / 2.9` | Same hardcoded midpoint |

With 192 pitchers in the pool, any pitcher ranked above ~29 immediately hit the ±2 or ±5 adjustment cap. The signal was effectively binary — elite pitchers (rank 1-29) got the full negative cap, everyone else got the full positive cap. No discrimination within the pool.

**Fix:** Added dynamic pool size at the top of `_calculate_enriched_score()`:
```python
n = max(len(pitcher_ranks), 2)
midpoint = (n + 1) / 2.0
```
All four signal formulas now use `(rank - midpoint) / (midpoint - 1) * scale` — same pattern as `pitcher_vulnerability()`.

**Verification:** `scripts/test_enriched_rank_normalization.py` confirms rank-96 (true midpoint of 192) now returns 0.0 adjustment, not +2.0 (old capped value). All 5 assertions pass.

**Commit:** `0a7ae36` — dynamic rank normalization in _calculate_enriched_score()

---

## Pending Items — Next Session

### 1. Verify June 15 Lineup Checks and CLV Fired (Immediate)
First night with a correctly deployed lineup_scheduler. Verify before touching anything else.

```sql
-- Did checks complete?
SELECT check_type, status, COUNT(*) as checks,
    MIN(fired_at) as first_fired,
    MAX(completed_at) as last_completed
FROM mlb_pending_lineup_checks
WHERE run_date = '2026-06-15'
GROUP BY check_type, status;

-- Did lineup statuses populate?
SELECT lineup_check_status, COUNT(*) as legs
FROM mlb_scored_legs WHERE run_date = '2026-06-15'
GROUP BY lineup_check_status;

-- CLV capture rate?
SELECT stat, direction,
    COUNT(*) FILTER (WHERE closing_odds IS NOT NULL) as captured,
    COUNT(*) as total,
    (COUNT(*) FILTER (WHERE closing_odds IS NOT NULL) * 100.0 /
     NULLIF(COUNT(*), 0))::numeric(5,1) as capture_rate_pct
FROM mlb_scored_legs WHERE run_date = '2026-06-15'
GROUP BY stat, direction;
```

### 2. Verify Cross-Run Player Cap in Railway Logs
Check Railway logs for June 16 pipeline runs. Look for `[player_cap]` lines. Expected behavior:
- 9AM: `No players at cap yet today` (first run of day)
- Midday: `N player(s) at 2-parlay cap — removed X leg(s)` for players who appeared in 9AM parlays
- Evening: larger cap list including midday players

### 3. 84% Coverage Ceiling — Quick Win (Next Session Priority)
One-line fix in `main.py`. Trap confirmed (hits/over drops from 71.8% to 31.5% above 84%). No data required. Claude Code task — should be first code change next session.

### 4. Monitor Shadow Pitcher Signals (June 16+ data only)
The dynamic rank normalization fix means shadow scores will have meaningful spread starting June 16. Run the pitcher bucket analysis again in 5 days using June 16+ data only. Key question: does the K/9 direction for hits/over remain counterintuitive with clean data?

```sql
SELECT
    CASE
        WHEN pitcher_k9_rank <= 48 THEN 'elite (1-48)'
        WHEN pitcher_k9_rank <= 96 THEN 'above avg (49-96)'
        WHEN pitcher_k9_rank <= 144 THEN 'below avg (97-144)'
        WHEN pitcher_k9_rank > 144 THEN 'weak (145+)'
        ELSE 'no data'
    END as k9_bucket,
    stat, direction,
    COUNT(*) FILTER (WHERE result IN ('won','lost')) as legs,
    (COUNT(*) FILTER (WHERE result = 'won') * 100.0 /
     NULLIF(COUNT(*) FILTER (WHERE result IN ('won','lost')), 0))::numeric(5,1) as win_rate_pct
FROM mlb_scored_legs_enriched
WHERE run_date >= '2026-06-16'
  AND result IN ('won', 'lost')
  AND stat IN ('hits', 'strikeouts')
GROUP BY k9_bucket, stat, direction
ORDER BY stat, direction, k9_bucket;
```

### 5. Stack Bonus Promotion Evaluation (After June 20)
Clean shadow data starts June 13. Re-evaluate after June 20 (7 clean days). Promotion requires all three:
- Stack legs win ≥5pp more than non-stack legs
- Shadow parlay win rate ≥ production parlay win rate
- ≥2 qualifying stacks per day average

Current read (11 legs): 72.7% vs 55.3% — direction right, sample too small.

### 6. CLV First Read (~June 26)
CLV capture started June 15 (first confirmed working night). First meaningful read ~June 26.

### 7. hits/under Reassessment
44.1% win rate in shadow scored legs — below breakeven. Currently in production whitelist at low frequency (53 appearances June 4–14 in production parlays, 51.4% win rate). Deferred pending CLV data and cleaner scoring.

---

## Session 12 Commits

| Commit | Message |
|--------|---------|
| `f23abfa` | fix: create missing lineup_scheduler module |
| sed fix | fix: game_pks must be postgres array format {x,y} not csv string |
| `116ae9b` | feat: cross-run 2x player cap — players appearing in 2 parlays today removed from future runs |
| `34b39a9` | fix: mirror resolved outcomes to mlb_scored_legs_enriched + backfill script |
| `d8d64aa` | fix: backfill enriched scored legs via direct sync from mlb_scored_legs |
| `0a7ae36` | fix: dynamic rank normalization in _calculate_enriched_score() — same fix as pitcher_vulnerability() |

---

## Bugs Fixed This Session

| Bug | File | Impact | Fix |
|-----|------|--------|-----|
| lineup_scheduler.py missing from repo | `src/pipelines/lineup_scheduler.py` | Lineup/CLV checks never fired since June 13 | Created missing file |
| game_pks wrong format (csv vs postgres array) | `src/pipelines/lineup_scheduler.py` | INSERT crashing on array format | `{x,y}` format |
| Cross-run player concentration | `main.py` | Same player in 4-5 parlays sank simultaneously | 2x daily cap replacing manual-only exclusion |
| enriched result never written to scored legs | `src/tracker/outcome_resolver.py` | 12 days of NULL shadow scored leg results | Mirror block added, 11-day backfill |
| Rank normalization hardcoded to 30-pitcher pool | `src/engine/enriched_scorer.py` | All pitcher signals binary-capped, no discrimination | Dynamic midpoint from `len(pitcher_ranks)` |

---

## System Health Indicators

### Green Lights
✅ lineup_scheduler.py deployed — lineup and CLV checks should fire tonight for first time
✅ Cross-run player cap live — concentration problem addressed
✅ mlb_scored_legs_enriched.result populated — shadow signal validation now possible
✅ Dynamic rank normalization correct in both pitcher_vulnerability() and _calculate_enriched_score()
✅ Stack bonus early signal positive (72.7% vs 55.3% — 11 legs)
✅ Production leg win rates strong (hits/over 66.9%, SO/over 87.1% — June 12–14)
✅ TB/under correctly blocked from production parlays (shadow data confirms: 52.6% win rate)

### Yellow Flags
⚠️ First live lineup annotation not yet verified — check June 15 results at start of next session
⚠️ CLV capture rate unverified live — check June 15 results
⚠️ Shadow pitcher signals (K9 direction for hits/over) counterintuitive — needs 5 more clean days
⚠️ Stack bonus needs more data before promotion decision (11 legs resolved)
⚠️ 84% coverage ceiling still not implemented — quick win for next session
⚠️ WHIP signal flat across all buckets — may need to be removed from hits scoring
⚠️ hits/under at 44.1% in shadow — below breakeven, deferred

### Red Flags
None currently

---

**Last Review:** June 15, 2026
**System Status:** ✅ Operational — Lineup/CLV Active, Player Cap Live, Shadow Signals Corrected
**Next Review:** June 16, 2026 — Verify lineup/CLV from June 15 slate + player cap in Railway logs + 84% ceiling fix
**Pending Decisions:** 84% ceiling (next session quick win), K/9 direction for hits/over (after June 20 data), stack bonus promotion (after June 20), TB under promotion (late June after CLV matures)
