# Architecture Decisions — Session 11 Append
**Date:** June 13, 2026
**Appends:** ARCHITECTURE_DECISIONS.md (last updated June 12, 2026)

---

## Scoring System — Additions

### **Decision: K/9 Rank Direction Fixed (June 13, 2026)**

The K/9 signal for batter SO over props in `_calculate_enriched_score()` was inverted since the shadow scorer was built. The formula `(15.5 - k9_rank) / 2.9` gave rank 1 (elite K pitcher, most strikeouts) a +5.0 boost to SO over — the opposite of correct. A batter facing an elite strikeout pitcher is *less* likely to strike out, not more.

**Corrected formula:** `(k9_rank - 15.5) / 2.9`
- rank 1 (elite K pitcher) → -5.0 (penalize SO over)
- rank ~15 (average) → ~0
- high rank (weak K pitcher) → +5.0 (boost SO over)

**Evidence that confirmed the bug:** 100% of shadow parlay legs over the June 5-12 window were SO over. The inverted signal drove systematic anti-selection — shadow consistently promoted legs facing elite K pitchers into parlays. 7-day shadow comparison is invalid and should be discarded. Clean shadow vs production comparison clock starts June 13.

**Historical backfill:** `scripts/backfill_k9_adj_june.py` corrected `composite_score` for 72 SO over legs in `mlb_scored_legs_enriched` (June 9-12 only — June 5-8 had no `pitcher_k9_rank` populated). Score delta: ~+10 points per leg (full direction flip).

---

## Pitcher Signal Pipeline — Additions

### **Decision: Pitcher Rank Normalization Must Be Dynamic (June 13, 2026)**

All pitcher rank normalization must use the actual max rank from the current pool, not a hardcoded constant. The pitcher rank pool is ~192-201 qualified starters (3+ starts, 3.0+ IP/start), not 30 teams.

The initial `pitcher_vulnerability()` implementation hardcoded `/29.0` (assuming max rank = 30), producing scores of -5.69 to +6.72 instead of the intended 0-1 range. The `STACK_VULNERABILITY_THRESHOLD = 0.60` would have triggered on almost every pitcher with rank ≥18 of 196 — making the bonus near-universal.

**Correct pattern:**
```python
max_era_rank = max((leg.get("pitcher_era_rank") or 0 for leg in scored_legs), default=0)
era_vuln = (era_rank - 1) / (max_era_rank - 1) if max_era_rank > 1 else 0.0
```

Max ranks are computed once at the start of `apply_stack_bonuses()` from the live scored leg pool, then passed to `pitcher_vulnerability()`. This automatically tracks pool growth through the season.

**Rule added to Lessons Learned:** Hardcoded rank denominators are wrong whenever the pool size is not fixed.

### **Decision: Pitcher Vulnerability Composite Score — Built and Fixed (June 13, 2026)**

Updates the June 12 entry which noted the spec was "ready, not yet built."

`pitcher_vulnerability()` is now live in `src/engine/enriched_scorer.py`. Rank convention confirmed from DB:
- ERA rank 1 = lowest ERA = best = least vulnerable
- K/9 rank 1 = highest K/9 = most strikeouts = least vulnerable for batters
- WHIP rank 1 = lowest WHIP = fewest baserunners = least vulnerable

All three use identical formula direction: `(rank - 1) / (max_rank - 1)` → 0.0 at rank 1, 1.0 at max rank.

---

## Shadow Pipeline Strategy — Additions

### **Decision: Offense Stack Bonus — Built, Shadow Only (June 13, 2026)**

Updates the June 12 entry which noted the spec was ready but not built.

Stack bonus is live in shadow pipeline. Three correctness bugs were found and fixed before the first pipeline run — see Lessons Learned entries 33-35. Promotion clock starts June 13 (first clean pipeline run post-fix).

### **Decision: Stack Eligibility Restricted to Favorable-Direction Props Only (June 13, 2026)**

`apply_stack_bonuses()` groups legs by `(team, game_pk)` but only counts `STACK_ELIGIBLE_PROPS` toward the stack minimum and applies the bonus. Currently:

```python
STACK_ELIGIBLE_PROPS = {
    ("hits", "over"),   # bad pitcher → more hits → over wins
}
```

Excluded from stacking: `hits under` (bad pitcher hurts the under), `strikeouts over` (bad K pitcher hurts batter SO over), `totalBases under` (bad pitcher hurts the under). These legs still get `pitcher_vulnerability` computed for data collection but receive no bonus and don't count toward `STACK_MIN_LEGS`.

To add a prop to `STACK_ELIGIBLE_PROPS` in the future, the directional logic must be confirmed: does a vulnerable (bad) pitcher make this bet *more* likely to win?

---

## Database Design — Additions

### **New Columns Added Session 11**

`mlb_scored_legs_enriched`: `stack_bonus_applied` (boolean, default false), `pitcher_vulnerability` (numeric, 0.0-1.0)

Migration: `sql/stack_bonus_migration.sql` (applied June 13, 2026)

### **Type Rule: `coverage_vs_opponent` is a Percentage (0-100), Not a Decimal**

Confirmed June 13 during SQL query debugging. `coverage_vs_opponent` in `mlb_scored_legs_enriched` stores values like 66.7, 50.0, 100.0 — not 0.667. Always cast with `::numeric(5,1)`, never `::numeric(5,3)` (will overflow for values ≥ 10.0).

---

## Pipeline Architecture — Additions

### **Decision: log_slate_start_times() Called Once Per Day at 9AM (June 13, 2026)**

`log_slate_start_times()` is called at the end of `run_morning_pipeline()` only. It reads today's scored legs from `mlb_scored_legs`, groups `game_pk` values by `game_start_time`, and writes one lineup check row and one CLV check row per start-time group to `mlb_pending_lineup_checks`.

The 12PM and 5:30PM runs (`run_targeted_pipeline`) do not call `log_slate_start_times()`. This is correct — the full day's game schedule is known at 9AM. The drain cron fires individual checks throughout the day as each game's `trigger_at` time arrives, regardless of which pipeline run originally scored the legs.

**Edge case:** Games added to the slate after 9AM (rare) would not get lineup/CLV checks scheduled. Not currently handled. Acceptable risk given rarity.

**Manual regen also does not call `log_slate_start_times()`** — calls `run_pipeline()` directly. If `log_slate_start_times()` needs to be called before the automated 9AM run (e.g. after a mid-day deploy), it can be triggered manually:

```bash
source .venv/bin/activate && set -a && source .env && set +a && python -c "
from main import log_slate_start_times
log_slate_start_times()
"
```

### **Decision: main.py Session 10 Changes Were Never Deployed — Fixed June 13**

The `log_slate_start_times()` function, `CLV_OFFSET_MINUTES`, `LINEUP_CHECK_OFFSET_MINUTES`, and `BATTING_ORDER_FAVORABLE` constants existed on disk from Session 10 but were never committed and pushed. Railway ran the pre-Session-10 `main.py` from June 12 through June 13. This explains 0% CLV capture rate and all-NULL `lineup_check_status` on June 12 legs.

**Lesson:** After any Claude Code session that modifies `main.py`, verify the changes are pushed with `git log --oneline -5` and `git show HEAD:main.py | grep [key_function_name]` before assuming the layer is live.

---

## Lessons Learned — Additions

33. **Hardcoded rank denominators are wrong when pool size is not fixed.** The pitcher rank pool is ~192-201 qualified starters. Any formula using `/29.0` or `(30 - rank)` as normalization assumes 30 as max rank — producing scores far outside [0,1] when the actual max is ~196. Always compute max rank dynamically from the live data.

34. **Signal direction bugs are invisible without end-to-end validation.** The K/9 inversion in `_calculate_enriched_score()` existed since the enriched scorer was built. It was only caught because 100% of shadow parlay legs in a 7-day window were SO over — an obvious anomaly in retrospect. Build direction-validation tests (e.g. "elite pitcher should penalize batter prop") as part of scorer verification.

35. **Stack eligibility must be directionally aware.** Grouping legs by (team, game_pk) without filtering by (stat, direction) applies a "bad pitcher bonus" to bets where a bad pitcher actually hurts the outcome. Always ask: does this signal work in favor of or against this specific bet direction?

36. **Uncommitted changes don't exist to Railway.** Session 10 spent significant effort building and verifying the lineup and CLV layers, but a missing `git push` meant neither layer had ever actually run. After any session that builds a new feature in `main.py`, verify deployment with `git show HEAD:main.py | grep [key_function]` before trusting Railway logs are showing the new behavior.

37. **Shadow pipeline underperformance has a specific diagnosis process.** When shadow underperforms production: (1) check resolution correctness (are leg outcomes being written?), (2) check pool overlap (are the same legs available to both?), (3) check leg win rates independently (does shadow have worse leg-level outcomes?), (4) check parlay construction (are wins clustering in parlays?). Only after all four checks can you conclude the enriched signals are the cause.

38. **`coverage_vs_opponent` is a percentage, not a decimal.** Values range from 0-100 (e.g. 66.7 for a batter who hit in 2 of 3 games vs this opponent). Use `::numeric(5,1)` for rounding, never `::numeric(5,3)` which overflows above 9.999.

---

**Architecture Status:** ✅ STABLE
**Last Major Change:** June 13, 2026 (K/9 direction fix, stack bonus 3-bug hotfix, main.py lineup/CLV wiring confirmed)
**Next Architecture Review:** After stack bonus shadow validation (June 20+) and CLV first read (~June 26)
