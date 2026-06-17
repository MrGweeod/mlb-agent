# MLB Parlay Agent — Session Handoff
**Last Updated:** June 16, 2026 (Session 13 — CLV Activation, Shadow Resolution Fix, Pitcher Signal Overhaul, Player Cap)

## Current Status
✅ **OPERATIONAL — SESSION 13 DEPLOYED**
✅ **clv_tracker.py committed — CLV checks firing for first time tonight**
✅ **Shadow resolution direction bug fixed — hits/under and TB/under now resolving correctly**
✅ **resolve_all_enriched_legs() added — full shadow pool resolution daily (not just parlay legs)**
✅ **June 4–15 shadow legs backfilled — 128 June 15 null legs resolved**
✅ **Enriched scorer pitcher signal overhaul — SO/over K/9 inverted, hits/over vulnerability penalty, hits/under pitcher signal removed**
✅ **Cross-run 2x player cap added to shadow pipeline**
⚠️ **Production player cap pool-thinning bug discovered — 0 parlays built on late manual regen — fix next session**

---

## What Happened on June 16, 2026 (Session 13)

### Fix 1 — clv_tracker.py Missing Module (Critical)

**Problem:** Every pipeline run since June 15 was logging:
```
[log_slate_start_times] CLV scheduling failed (non-fatal): No module named 'src.apis.clv_tracker'
```
`src/apis/clv_tracker.py` existed locally but was never committed. Same class of bug as `lineup_scheduler.py` from Session 12.

**Fix:** Committed `src/apis/clv_tracker.py` (324 lines). Pushed with all other untracked Session 10–12 files in one cleanup commit — 15 files, 3,263 insertions.

**Also committed in same cleanup push:**
- `src/apis/lineup_confirmation.py`
- `src/engine/simple_scorer.py` (modified)
- `src/tracker/parlay_outcome_resolver.py` (modified)
- `src/web/server.py` (modified)
- All `scripts/` backfill scripts
- All `sql/` migration files
- `verify_clv.py`, `verify_lineup_layer.py`

**Manual CLV backfill:** 11 CLV rows manually inserted into `mlb_pending_lineup_checks` for tonight's slate (June 16), since `log_slate_start_times()` only runs at 9AM and CLV rows were missing. Will fire T-1 before each game group tonight.

**Commits:** `50cc5a9` — clv_tracker | `d9eb7f1` — all untracked session 10–12 files

---

### Fix 2 — Shadow Resolution Direction Bug

**Problem:** `mlb_scored_legs_enriched.result` was NULL for all hits/under (48 legs) and totalBases/under (73 legs) from June 15. hits/over and strikeouts/over resolved correctly.

**Root cause:** In `resolve_enriched_parlays()`, the SELECT from `mlb_scored_legs` matched on `(player_name, stat, run_date)` but NOT `direction`. For players with both an over and under leg scored on the same day, `LIMIT 1` returned the wrong direction's result or found nothing.

**Fix:** Added `direction` to three places in `resolve_enriched_parlays()`:
1. Initial `pending_legs` SELECT from `mlb_parlay_legs_enriched` — added `l.direction`
2. `mlb_scored_legs` lookup — added `AND direction = %s`
3. `mlb_scored_legs_enriched` mirror UPDATE — added `AND direction = %s`

**Backfill:** June 13–14 under legs synced via direct SQL UPDATE JOIN from `mlb_parlay_legs_enriched`. June 13: 227/227 resolved, June 14: 248/248 resolved.

**Commit:** `(outcome_resolver fix)`

---

### Fix 3 — resolve_all_enriched_legs() Added (Full Shadow Pool Resolution)

**Problem:** Shadow resolution only flowed through the parlay leg mirror — meaning only ~20 legs/day that made it into shadow parlays ever got results. The other ~140 legs/day stayed null permanently. This made signal validation queries across the full scored pool useless.

**Fix:** Added `resolve_all_enriched_legs(run_date)` to `outcome_resolver.py`. Mirrors `resolve_all_legs()` exactly, targeting `mlb_scored_legs_enriched`. Uses box score path (one `statsapi.boxscore_data()` call per game). Updates keyed on `(run_date, odd_id)` — never `id` (which is NULL for all rows in this table).

Wired into `main.py` immediately after `resolve_all_legs()` in the daily morning resolution block.

**Backfill:** `scripts/backfill_enriched_scored_legs_resolution.py` run for June 4–15. June 4–14 already resolved (from prior parlay mirror). June 15: 74 won / 50 lost / 4 void (128 legs).

**Commits:** `(resolve_all_enriched_legs + backfill script)`

---

### Analysis — Pitcher Vulnerability Signal Validation (June 15 Clean Data)

With full shadow pool resolution now working, ran first meaningful individual-leg signal validation using June 15 data (first clean day with correct pitcher rank normalization).

**hits/over vulnerability gradient (16 legs with pitcher data):**
| Vulnerability | W-L | Win Rate |
|---|---|---|
| ≥0.50 | 6-1 | 86% |
| 0.25–0.49 | 5-2 | 71% |
| <0.25 | 0-3 | 0% |

Wheeler (0.190, ERA 2.22) and Burns (0.070, ERA 2.14) accounted for all 3 losses below 0.25. These two pitchers appeared in 6 shadow parlays combined — every one lost.

**SO/over finding:** Burns (K/9 ~14) was actually favorable for SO/over — the batter Marcus Semien struck out. Confirms vulnerability penalty should NOT apply to SO/over.

**TB/under finding:** Wheeler and Burns legs went 3-2 for TB/under — no penalty warranted. WHIP-based scoring remains appropriate.

**Conclusion:** Vulnerability penalty applies exclusively to hits/over. Signal is prop-specific.

---

### Fix 4 — Enriched Scorer Pitcher Signal Overhaul

**Changes to `src/engine/enriched_scorer.py`:**

**1. SO/over — K/9 direction inverted**
Old: `(k9_rank - midpoint) / (midpoint - 1) * 5.0` — rank 1 (elite K pitcher) gave -5 penalty to SO/over. Wrong direction.
New: `(midpoint - k9_rank) / (midpoint - 1) * 5.0` — rank 1 (elite K pitcher) gives +5 boost to SO/over. Facing an elite strikeout pitcher means a batter is MORE likely to strikeout.

**2. hits/over — Replace ERA+K9+WHIP composite with vulnerability penalty**
Removed the 37-line ERA + K9 + WHIP composite block (±2 each, ±6 max) for hits props.
Replaced with:
```python
if stat == "hits" and direction == "over":
    vuln = pitcher_vulnerability(leg, max_era_rank, max_k9_rank, max_whip_rank)
    if vuln is not None:
        if vuln < 0.15:   score -= 10
        elif vuln < 0.25: score -= 6
```
Note: `pitcher_vulnerability` is computed after `score_legs()` in `run_enriched_pipeline.py`, so it's recomputed inline using `max_ranks` derived from `pitcher_ranks` already in scope.

**3. hits/under — Pitcher signal removed entirely**
The inverted ERA+K9+WHIP composite for hits/under is removed. No replacement. Data showed hits/under has no consistent pitcher quality signal.

**4. TB/over and TB/under — Untouched**
WHIP rank ±5 with direction inversion remains. Correct per June 15 data.

**Effect observed on June 16 manual regen:** hits/over legs with elite pitchers correctly deprioritized. Wheeler/Burns-class legs no longer anchoring shadow parlays. TB/under and SO/over now dominate pool.

**Commit:** `(enriched_scorer overhaul)`

---

### Fix 5 — Cross-Run 2x Player Cap in Shadow Pipeline

**Problem:** Shadow pipeline had no cross-run player cap. The same fix applied to production in Session 12 was never mirrored to shadow. Result: Nolan Arenado, Salvador Perez, Xander Bogaerts, Dansby Swanson, Jo Adell each appeared in all 5 shadow batches on June 16.

**Fix:**
1. Added `get_enriched_players_used_today(run_date)` to `src/utils/db.py` — queries `mlb_parlay_legs_enriched JOIN mlb_parlay_recommendations_enriched`, HAVING COUNT(*) >= 2
2. Applied cap filter in `run_enriched_pipeline.py` before `build_hybrid_parlays()` call
3. Fallback: restore full pool if fewer than 20 legs remain

**Commit:** `a538fd0`

---

### Bug Discovered — Production Player Cap Pool-Thinning (Not Fixed Yet)

**Problem found in 18:58 UTC Railway logs:**
```
[player_cap] 38 player(s) at 2-parlay cap — removed 66 leg(s)
[filter_legs] Blocked 44 low score + 0 out-of-range odds | Kept 0 overs + 29 unders = 29 total eligible
[parlay_builder] ⚠  0 parlays built for rank 1 — check odds range (+400–+700)
```

After 5+ pipeline runs, 38 players were at the 2x cap, removing 66 legs. The remaining 29 legs were all unders with heavy juice — no combination reached +400.

**Root cause:** The fallback threshold (`< 20 legs`) was met (29 legs remain) but all 29 were unders that can't combine to target odds. The fallback should check whether eligible overs remain, not just total leg count.

**Impact:** Production built 0 parlays on the 18:00 manual regen. The 17:08 batch is the last valid production output for June 16.

**Fix needed next session:** Update fallback logic in `main.py` to restore full pool if fewer than N over legs remain after cap (not just total legs). Same fix needed in `run_enriched_pipeline.py` for shadow.

---

## Pending Items — Next Session

### 1. Fix Player Cap Pool-Thinning Fallback (PRIORITY — First Fix Next Session)

**Problem:** Fallback `if len(pool) < 20: restore_full_pool` doesn't account for prop type composition. 29 under-only legs pass the fallback but can't build a +400 parlay.

**Fix needed in `main.py` and `run_enriched_pipeline.py`:**
```python
# Instead of just checking total leg count:
over_legs_remaining = [l for l in pool_for_parlays if l.get("direction") == "over"]
if len(pool_for_parlays) < 20 or len(over_legs_remaining) < 10:
    print("[player_cap] Pool too thin — restoring full pool")
    pool_for_parlays = all_legs
```
Threshold for over legs (10) is a starting point — calibrate based on typical over pool size.

### 2. Verify CLV Fired Tonight (June 16)

Check Railway logs tomorrow morning for `[clv_tracker]` lines. Then verify:
```sql
SELECT check_type, status, result_note, completed_at
FROM mlb_pending_lineup_checks
WHERE run_date = '2026-06-16'
  AND check_type = 'clv'
ORDER BY trigger_at;
```
Expected: 11 rows, status='completed', result_note like "CLV snapshot: X/Y legs captured"

### 3. Verify lineup_scheduler and CLV Auto-Schedule Tomorrow (June 17)

Tomorrow's 9AM pipeline should auto-schedule both lineup and CLV rows without manual backfill. Verify:
```sql
SELECT check_type, COUNT(*), MIN(trigger_at), MAX(trigger_at)
FROM mlb_pending_lineup_checks
WHERE run_date = '2026-06-17'
GROUP BY check_type;
```

### 4. 84% Coverage Ceiling (Still Not Implemented)

One-line fix in `main.py`. Trap confirmed (hits/over drops from 71.8% to 31.5% above 84%). Quick win. Has been deferred since Session 9.

### 5. Vulnerability Penalty Calibration Review (~June 22)

June 15 is only clean day. Need 5–7 more days before confirming penalty thresholds (<0.15 = -10, <0.25 = -6). Run the full hits/over vulnerability bucket analysis again on June 22+ data.

```sql
SELECT
    CASE
        WHEN pitcher_vulnerability < 0.15 THEN '1_elite (<0.15)'
        WHEN pitcher_vulnerability < 0.25 THEN '2_very_low (0.15-0.24)'
        WHEN pitcher_vulnerability < 0.50 THEN '3_low (0.25-0.49)'
        WHEN pitcher_vulnerability < 0.75 THEN '4_mid (0.50-0.74)'
        ELSE '5_high (>=0.75)'
    END as vulnerability_bucket,
    COUNT(*) FILTER (WHERE result IN ('won','lost')) as resolved,
    COUNT(*) FILTER (WHERE result = 'won') as won,
    (COUNT(*) FILTER (WHERE result = 'won') * 100.0 /
     NULLIF(COUNT(*) FILTER (WHERE result IN ('won','lost')), 0))::numeric(5,1) as win_rate
FROM mlb_scored_legs_enriched
WHERE run_date >= '2026-06-15'
  AND stat = 'hits' AND direction = 'over'
  AND result IN ('won','lost')
GROUP BY vulnerability_bucket
ORDER BY vulnerability_bucket;
```

### 6. Stack Bonus Promotion Evaluation (After June 20)
Current: 72.7% vs 55.3% (11 legs — small sample). Re-evaluate after June 20.

### 7. CLV First Read (~June 26)
First meaningful read on SO/over and hits/over closing line value.

---

## Session 13 Commits

| Commit | Message |
|--------|---------|
| `50cc5a9` | feat: add clv_tracker module (was untracked) |
| `d9eb7f1` | feat: commit all untracked session 10–12 files (lineup confirmation, CLV, resolver fixes, scripts, migrations) |
| `(resolver fix)` | fix: add direction filter to shadow resolution mirror — under legs were resolving null |
| `(enriched resolver)` | feat: add resolve_all_enriched_legs() — full shadow pool resolution + daily pipeline wire-up + June 4-15 backfill script |
| `(scorer overhaul)` | feat: overhaul shadow pitcher signals — invert SO/over K9 direction, replace hits ERA+K9+WHIP with vulnerability penalty (<0.25=-6, <0.15=-10), hits/under pitcher signal removed |
| `a538fd0` | feat: add cross-run 2x player cap to shadow pipeline |

---

## Bugs Fixed This Session

| Bug | File | Impact | Fix |
|-----|------|--------|-----|
| clv_tracker.py untracked | `src/apis/clv_tracker.py` | CLV capture rate 0% since June 15 | Committed |
| 14 other files untracked | various | Session 10–12 work not deployed to Railway | Mass commit |
| Shadow resolution missing direction filter | `outcome_resolver.py` | hits/under + TB/under result = NULL | Added direction to SELECT + UPDATE |
| No full shadow pool resolution path | `outcome_resolver.py` + `main.py` | ~140 legs/day unresolved in shadow | resolve_all_enriched_legs() added |
| SO/over K/9 direction inverted in enriched scorer | `enriched_scorer.py` | SO/over anti-selected against elite K pitchers | Formula inverted |
| hits/over no pitcher quality penalty | `enriched_scorer.py` | Wheeler/Burns legs anchoring shadow parlays | Vulnerability penalty -6/-10 |
| Shadow pipeline missing cross-run player cap | `run_enriched_pipeline.py` + `db.py` | Same 5 players in every shadow batch | get_enriched_players_used_today() + filter |

---

## System Health Indicators

### Green Lights
✅ CLV tracking live — clv_tracker.py deployed, 11 rows scheduled for tonight
✅ Lineup scheduler confirmed firing (verified in yesterday's logs)
✅ Cross-run player cap live in both production and shadow
✅ Shadow resolution now covers full scored leg pool (not just parlay legs)
✅ Enriched scorer pitcher signals corrected — SO/over direction right, hits/over vulnerability penalty active
✅ Shadow scored legs fully resolved June 4–15

### Yellow Flags
⚠️ Production player cap pool-thinning bug — 0 parlays on late manual regen June 16 (fix next session)
⚠️ 84% coverage ceiling still not implemented
⚠️ Vulnerability penalty thresholds need 5+ more clean days to validate (<0.25=-6, <0.15=-10)
⚠️ Stack bonus needs more data before promotion (11 legs)
⚠️ hits/under at 44.1% in shadow — below breakeven, deferred

### Red Flags
None currently

---

**Last Review:** June 16, 2026
**System Status:** ✅ Operational — CLV Active, Shadow Signals Corrected, Player Cap Live
**Next Review:** June 17, 2026 — Fix player cap fallback + verify CLV fired + 84% ceiling
**Pending Decisions:** Player cap fallback fix (immediate), 84% ceiling (next session quick win), vulnerability penalty calibration (~June 22), stack bonus promotion (after June 20), TB under promotion (late June)
