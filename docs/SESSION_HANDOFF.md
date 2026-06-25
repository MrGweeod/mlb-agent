# MLB Parlay Agent — Session Handoff
**Last Updated:** June 18, 2026 (Session 14 — CLR Bug Fix, Coverage Ceiling Analysis, Shadow Performance Review)

## Current Status
✅ **OPERATIONAL — SESSION 14 DEPLOYED**
✅ **CLR replacement pool now excludes totalBases — TB/under no longer leaking into production via CLR**
✅ **CLR cross-iteration player tracking added — same player can no longer flood replacement parlays**
✅ **Player cap fallback now checks over leg composition — 0-parlay bug fixed**
✅ **All three fixes in commit `8a4a7d7` — pushed to Railway June 18, 4:55 PM ET**
⚠️ **hits/under gate (40%) flagged as too low — avg coverage 48%, no enriched signal differentiation**
⚠️ **TB/under park_factor and opp_coverage NULL in shadow — signals not populating for this prop**
⚠️ **Coverage ceiling confirmed prop-specific — universal 84% ceiling NOT being implemented**

---

## What Happened on June 18, 2026 (Session 14)

### Investigation — Duplicate Players in Production Parlays

**Trigger:** User noticed parlays generating identical players across batches.

**Initial hypothesis (incorrect):** Player cap fallback firing and restoring all capped players. Disproved by SQL — repeated players traced almost entirely to `source = 'confirmed_lineup_resolution'`, not scheduled batch sources.

**Evidence:** SQL query showed Jared Triolo in 10 parlays (all CLR), Jackson Chourio in 9 (all CLR), multiple other players in 5-8 CLR parlays each. Scheduled batches had normal distribution.

---

### Fix 1 — CLR Replacement Pool Excluding totalBases

**File:** `src/apis/lineup_confirmation.py`

**Problem:** `main.py` excludes `totalBases` legs from production parlays via:
```python
production_legs = [l for l in qualifying_legs if l.get("stat") != "totalBases"]
```
But `run_confirmed_lineup_resolution()` built its replacement pool from `mlb_scored_legs` with no equivalent filter. TB/under legs blocked by `main.py` were leaking into every CLR replacement parlay.

**Confirmed in data:** 27 TB/under appearances in production parlays over Jun 16–17, almost entirely from `confirmed_lineup_resolution`. TB/under was shadow-only by design.

**Fix:** Added after `eligible_pool` construction (line 468):
```python
eligible_pool = [l for l in eligible_pool if l.get("stat") != "totalBases"]
```

**Lesson:** Any production exclusion in `main.py` must be explicitly mirrored in CLR's pool construction. CLR does not inherit `main.py` filters automatically.

---

### Fix 2 — CLR Cross-Iteration Player Tracking

**File:** `src/apis/lineup_confirmation.py`

**Problem:** When CLR rebuilt multiple affected parlays in one event (e.g. 10 parlays all containing the same scratched player), the loop called `build_parlays()` separately for each iteration. `build_parlays()` has an internal `used_players` set but it resets on every call. Nothing prevented the same top-scoring player from being selected as a replacement in every iteration.

**Fix:** Added `used_replacement_player_ids: set[str] = set()` before the loop. Threaded into `available_pool` filter inside the loop. Updated with each rebuild's selected players after each successful iteration.

**Cap applied:** Max 1 per CLR batch (stricter than the cross-run cap of 2), since all replacements happen in a single event.

**Lesson:** Player tracking must span CLR loop iterations explicitly. `build_parlays()` internal diversity only covers a single call — it provides no protection across multiple sequential calls.

---

### Fix 3 — Player Cap Fallback Composition Check

**Files:** `main.py`, `src/pipelines/run_enriched_pipeline.py`

**Problem:** The cross-run 2x player cap fallback used `if len(qualifying_legs) < 20`. After 5+ pipeline runs, 29 under-only legs remained — passing the threshold but mathematically unable to combine to +400. Builder returned 0 parlays.

**Fix:** Fallback now checks over leg count in addition to total:
```python
over_legs_remaining = [l for l in qualifying_legs if l.get("direction") == "over"]
if len(qualifying_legs) < 20 or len(over_legs_remaining) < 10:
    # restore full pool
```
Same fix applied to `run_enriched_pipeline.py` for shadow.

**Commit:** `8a4a7d7` — all three fixes, pushed June 18 4:55 PM ET, auto-deployed to Railway.

---

### Analysis — Weekly Parlay Performance

Clean window (scheduled sources only, excluding CLR):

| Period | Avg Odds | Win Rate | Breakeven | Edge |
|---|---|---|---|---|
| May 4–18 | +1084–1471 | 6.9–7.6% | ~6–8% | Near breakeven / losing |
| May 25 | +982 | 8.7% | ~9.3% | Slightly below |
| Jun 1–7 | +481 | 22.6% | ~17.2% | **+5.4pp** |
| Jun 8–14 | +443 | 26.5% | ~18.4% | **+8.1pp** |
| Jun 15–18 | +473 | 16.1% (31 resolved) | ~17.4% | Below — CLR bug contaminating this period |

June 1 restructure (single flat pool, 4-leg, +400–700) is working. Jun 15 dip largely explained by CLR-generated junk parlays now fixed.

---

### Analysis — Coverage Ceiling (prop-specific, not universal)

Coverage bucket query rerun with correct 0–100 scale thresholds. Key findings per prop:

**hits/over:**
| Coverage | Resolved | Win Rate |
|---|---|---|
| 70–75% | 531 | 66.7% |
| 75–80% | 231 | **71.9%** ← peak |
| 80–84% | 44 | 61.4% ↓ |
| 84–90% | 6 | 50.0% ↓ |

Real ceiling is ~80%, not 84%. 44 legs in the 80–84 bucket are enough to act on.

**strikeouts/over:**
| Coverage | Resolved | Win Rate |
|---|---|---|
| 75–80% | 161 | 70.2% |
| 80–84% | 47 | **78.7%** |
| 84–90% | 30 | **76.7%** |

Monotonically increasing through 84%+. **No ceiling for SO/over.** A universal 84% gate would cut the best SO/over legs.

**totalBases/under:** Peaks at 70–75% (63.8%), gets noisy above 75% with small samples.

**Decision: Universal 84% coverage ceiling NOT being implemented.** The effect is prop-specific. A prop-specific hits/over ceiling at ~80% is the right approach and is pending implementation.

---

### Analysis — Shadow vs Production Performance (Jun 16–17)

| Date | Pipeline | Resolved | Win Rate | Avg Odds | Voided |
|---|---|---|---|---|---|
| Jun 16 | Shadow | 25 | **32.0%** | +430 | 0 |
| Jun 16 | Production | 10 | 10.0% | +506 | 6 |
| Jun 17 | Shadow | 20 | **25.0%** | +456 | 0 |
| Jun 17 | Production | 9 | 22.2% | +427 | 10 |

Shadow outperforming production both days. Production voids are original parlays superseded by (now-fixed) CLR.

**Shadow parlay leg composition:**
- No hits/under in shadow parlays either day — enriched scorer correctly deprioritizing
- SO/over: 81.3% / 78.9% in selected parlay legs — most consistent performer
- TB/under: 88.4% (Jun 16) / 53.7% (Jun 17) — strong but volatile day-to-day

**Signal differentiation (Jun 16–17 combined):**
- hits/over: vulnerability working (0.386 won vs 0.492 lost) ✅
- hits/under: no differentiation (0.482 won vs 0.476 lost) ❌
- TB/under: park_factor and opp_coverage both NULL — signals not being attached to this prop ⚠️

---

### Analysis — hits/under Gate Problem

hits/under average coverage across Jun 16–17 shadow scored legs: **~48%** — barely above the 40% floor. Win rates: 40.8% (Jun 17), 58.5% (Jun 16). No enriched signal differentiation. The 40% gate is letting in low-quality legs with no scoring signal to compensate.

Full coverage bucket data (clean window, Apr 27+): 1,832 hits/under legs below 55% coverage at **39.3% win rate**. That's a large volume of junk passing the gate.

**Decision pending:** Raise hits/under gate from 40% to ~65% to match the overs floor. Needs confirmation before implementing.

---

### Analysis — TB/under Signal Null Problem

Query 4 (signal differentiation) showed `park_factor` and `coverage_vs_opponent` both NULL for all TB/under legs. These enriched signals are not being attached to TB/under in `enriched_scorer.py` or `run_enriched_pipeline.py`. Before promoting TB/under to production, this needs investigation and a fix — the enriched scorer is flying partially blind on this prop.

---

### Project File Cleanup (Discussed, Not Yet Done)

Files identified as safe to retire from Project Knowledge:
- `SYSTEM_DIAGNOSTIC_REPORT_2026-05-12.md` — describes abandoned ML architecture, none of which exists in current repo
- `CHAT_HANDOFF_2026-05-28.md` — superseded by SESSION_HANDOFF.md
- `MLB_Scored_Legs_Table_Schema.csv` — superseded by SUPABASE_SCHEMA_REFERENCE.md
- `SKILL.md` (in Project Files) — duplicate of the actual skill managed in Skills settings; will diverge now that Rule 3 is being added
- `README_10.md` — June 12 snapshot, superseded by BUILD_STATUS.md

---

## Pending Items — Next Session

### 1. Investigate TB/under Null Signals (PRIORITY before promotion decision)

`park_factor` and `coverage_vs_opponent` are NULL for all TB/under legs in `mlb_scored_legs_enriched`. Find where these signals are attached in `run_enriched_pipeline.py` and `enriched_scorer.py` and confirm whether TB/under is being routed through the enrichment path correctly.

### 2. Raise hits/under Coverage Gate

Change hits/under floor from 40% to 65% in `main.py`. Data: 1,832 legs below 55% coverage at 39.3% win rate, no enriched signal differentiation at any coverage level. This is a one-line change with strong data support.

### 3. Add prop-specific Coverage Ceiling for hits/over

Add ~80% ceiling for hits/over only in `main.py`. Do NOT apply universally — SO/over has no ceiling and a universal gate would harm it. Implementation:
```python
if stat == "hits" and direction == "over" and coverage_overall > 80:
    continue  # above ceiling — skip
```

### 4. Vulnerability Penalty Calibration (~June 22)

Jun 15–18 now available. Rerun hits/over vulnerability bucket analysis:
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

### 5. TB/under Production Promotion Decision (After Fixing Null Signals + Late June)

Shadow data: 67.4% win rate (89 legs), 58.5% breakeven at -141 avg odds (+8.9pp edge). Strong case for promotion, but null signals must be fixed first to know if the enriched scorer is capturing full signal quality.

### 6. Stack Bonus Promotion Evaluation (After June 20)

Current: 72.7% vs 55.3% (11 legs — small sample). Recheck after June 20.

### 7. CLV First Read (~June 26)

First meaningful read on SO/over and hits/over closing line value. Expected: SO/over positive CLV, hits/over near zero.

### 8. Project File Cleanup

Remove 5 stale files from Project Knowledge (listed above). Add updated BUILD_STATUS, SESSION_HANDOFF, ARCHITECTURE_DECISIONS.

---

## Session 14 Commits

| Commit | Message |
|--------|---------|
| `8a4a7d7` | fix: CLR replacement pool — exclude totalBases, add cross-iteration player cap, fix fallback composition check |

---

## Bugs Fixed This Session

| Bug | File | Impact | Fix |
|-----|------|--------|-----|
| CLR pool including TB/under | `src/apis/lineup_confirmation.py` | TB/under leaking into production via CLR (27 appearances Jun 16–17) | Added `stat != "totalBases"` filter after pool construction |
| CLR no cross-iteration player tracking | `src/apis/lineup_confirmation.py` | Same player flooding all replacement parlays (Triolo 10x, Chourio 9x) | `used_replacement_player_ids` set added across loop |
| Player cap fallback ignoring over composition | `main.py`, `run_enriched_pipeline.py` | 0 parlays built when all remaining legs are unders | Added `len(over_legs_remaining) < 10` to fallback condition |

---

## System Health Indicators

### Green Lights
✅ All three CLR bugs fixed and deployed (commit `8a4a7d7`)
✅ CLV tracking live and auto-scheduling
✅ Lineup confirmation firing (T-45 verified)
✅ Shadow outperforming production (32%/25% vs 10%/22% Jun 16–17)
✅ Shadow resolution covering full scored leg pool
✅ Vulnerability signal working for hits/over
✅ SO/over confirmed edge prop — no coverage ceiling, monotonic improvement through 84%+

### Yellow Flags
⚠️ hits/under gate at 40% — avg coverage only 48%, no enriched signal, 1,832 legs below 55% at 39.3% win rate
⚠️ TB/under park_factor and opp_coverage NULL in shadow — must fix before promotion
⚠️ Vulnerability penalty thresholds need Jun 15–22 data to validate
⚠️ Stack bonus needs more data before promotion (11 legs)
⚠️ hits/over prop-specific ceiling (~80%) not yet implemented
⚠️ Same-game pairs nearly absent from production (3 of 316 parlays in 30 days) — prior correlation finding may not hold at scale

### Red Flags
None currently

---

**Last Review:** June 18, 2026
**System Status:** ✅ Operational — CLR Bugs Fixed, Coverage Analysis Complete
**Next Review:** June 22, 2026 — TB/under null signals, hits/under gate, prop-specific ceiling, vulnerability calibration
**Pending Decisions:** TB/under null signal fix + production promotion (next session), hits/under gate raise (next session), hits/over ~80% ceiling (next session), vulnerability calibration (~June 22), stack bonus promotion (after June 20)
