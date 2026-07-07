# MLB Parlay Agent — Session Handoff
**Last Updated:** July 7, 2026 (Session 17 — SportsGameOdds Usage Audit + CLV Layer Removed)

## Current Status
✅ **OPERATIONAL — SESSION 17 DEPLOYED**
✅ **CLV tracking layer removed — no demonstrated predictive value, was ~52-78% of SGO call volume**
✅ **Fix deployed: commit d3a642c (Jul 7, 2026)**
✅ **Retrospective validation: 3-scheduled-run-only usage projects to ~1,080/month avg, ~1,350/month worst case — both well under SGO's 2,500/month free-tier cap**
🔲 **Pending user action: actually cancel SGO Pro subscription ($149/mo) and confirm account is on the Amateur/free tier — code change is deployed and validated, but the account-level downgrade itself is outside pipeline scope**
⚠️ **Unexplained elevated SGO traffic in April/May 2026, predating CLV (which didn't exist until June 12) — not investigated, flagged for a future session if it recurs**
⚠️ (Carried from Session 16) **Post-deploy void rate and win-rate checks for the batting-order slot-gate fix: recheck ~July 5-6 — not addressed this session**
⚠️ (Carried from Session 16) **void_reason column on mlb_scored_legs confirmed non-functional — not yet fixed**
⚠️ (Carried from Session 16) **TB/under parlay-level drag — construction strategy question, not yet addressed**
⚠️ (Carried from Session 16) **Unknown commit 85b5bd5 — origin not yet confirmed**

---

## What Happened on July 7, 2026 (Session 17)

### SportsGameOdds Usage Audit

Prompted by a cost question (SGO Pro tier = $149/month for ~100K objects/month, vs.
free Amateur tier capped at 2,500 objects/month), queried the previously-undocumented
`mlb_sgo_request_log` table directly via a newly-connected Supabase MCP tool (823 rows
at the start of the audit, covering Apr 16 – Jul 2).

**Found:** MLB agent's own usage alone (independent of any shared-account NBA
activity) already exceeded 2,500/month in every complete month:

| Month | Requests | Entities Consumed |
|---|---|---|
| April (from 4/16) | 203 | 2,545 |
| May | 288 | 3,365 |
| June | 310 | 3,794 |

Confirmed the SGO account is also used by an NBA parlay agent sharing the same key
(`sgo_request_log`, non-`mlb_`-prefixed table, 106 rows) — but confirmed via the user
that the **NBA agent is no longer active** (its log shows zero requests after April
2026), so MLB's own numbers above are the effective full picture going forward, not a
partial one.

**Hour-of-day breakdown (ET) isolated two usage sources:**
- ~3.6 requests/day (~43.7 entities/day) clustered at 9AM/12PM/~5PM — the three
  scheduled pipeline runs
- ~10.1 requests/day (~129.7 entities/day) scattered across all other daytime/evening
  hours — consistent with the CLV tracker firing a separate SGO call per distinct
  game-start-time group at T-1 minute

This pointed to CLV tracking as the dominant driver of excess volume (~75% of total,
by this estimate) ahead of any code changes.

### CLV Predictive-Value Test

Before deciding whether to cut CLV calls or remove the layer outright, tested whether
CLV was actually adding value: does "beating the closing line" correlate with actually
winning, using `mlb_scored_legs.closing_odds` vs. `result` (June 16 – July 7, n=2,300
resolved legs with both closing odds and a resolved outcome).

**Aggregate result looked mildly supportive of CLV theory:**

| CLV Bucket | Legs | Win Rate |
|---|---|---|
| Beat the close (positive CLV) | 930 | 57.0% |
| Lost to the close (negative CLV) | 1,105 | 55.4% |
| No movement | 265 | 54.7% |

But the 1.6pp gap is **not statistically significant** (two-proportion z-test,
z≈0.72, well below the ~1.96 threshold for 95% confidence).

**Broken down by prop, the pattern reverses for the two strongest-edge props:**

| Prop | Positive CLV WR | Non-Positive CLV WR | Direction |
|---|---|---|---|
| hits/over | 62.4% (n=282) | 64.0% (n=200) | Reversed |
| hits/under | 45.3% (n=139) | 44.4% (n=275) | Weakly consistent, tiny gap |
| strikeouts/over | 64.0% (n=114) | 70.9% (n=79) | Reversed, largest gap (6.9pp, also not significant) |
| totalBases/under | 55.2% (n=395) | 55.3% (n=816) | Flat |

**Conclusion: the aggregate "CLV predicts wins" signal is a composition artifact of
mixing props with different base rates and different CLV-bucket proportions — it
disappears, and partly reverses, once split by prop.** No prop shows a statistically
credible relationship between beating the close and winning, in either direction, at
current sample sizes. This directly informed the decision below — CLV wasn't just
expensive, it wasn't shown to be doing anything.

### Decision: Cancel SGO Pro Plan, Remove CLV Tracking Layer

Given (a) SGO's free tier alone would require cutting current volume by ~75-93%
depending on which calls are cut, and (b) CLV — the single largest volume driver —
had no demonstrated predictive value, the decision was made to remove CLV tracking
entirely (not throttle it) and keep only the three scheduled pipeline runs
(9AM/12PM/5:30PM) as the sole remaining SGO call path.

**Fix implemented via Claude Code, validated against live repo before changes:**
- Confirmed via direct DB query (joining `mlb_pending_lineup_checks.check_type`
  rather than inferring from timestamps) that CLV was responsible for **52% of total
  SGO volume overall, and 78% of July's volume specifically** — higher and more
  precise than the ~75% hour-bucket estimate used to scope the work, and showing the
  cost was accelerating, not flat.
- **Caught a measurement artifact in the original volume estimate:** a spike
  attributed to "scheduled-run" traffic on June 16 (150 entities) was actually a
  one-off backlog of June 12 + June 15 CLV checks that had queued up while the drain
  cron wasn't running, then fired in a single catch-up burst on June 16 — not
  representative of steady-state cost. Excluded from the final projection.
- Confirmed lineup confirmation (`check_type='lineup'`) does **not** call SGO at all
  — only MLB-StatsAPI, as assumed.
- Confirmed `closing_odds` is not read by any live scoring, parlay-building, or
  resolution code — safe to stop collecting without affecting any active decision
  path.
- `main.py`: commented out (not deleted) the `schedule_clv_checks()` call inside
  `log_slate_start_times()`, with inline recovery instructions.
- `src/apis/lineup_confirmation.py`: the `check_type='clv'` drain branch no longer
  calls `run_clv_snapshot()` — any already-queued CLV rows are marked `done` with an
  explanatory note instead of being left stuck `pending` indefinitely.
- `src/apis/clv_tracker.py` left fully intact but no longer called — recoverable.
- Historical `closing_odds` / `closing_odds_captured_at` data in `mlb_scored_legs`
  left untouched — this is a stop-collecting change, not a data-deletion change.
- 10/10 tests passed in a standalone test script (`test_clv_removal.py`).
- Deployed: commit `d3a642c`, clean push (no rebase conflict this time).

**Retrospective validation (18 clean 3-run days since June 16, excluding the June 16
catch-up artifact):**

| Metric | Value |
|---|---|
| Avg scheduled-only entities/day | 36 |
| Peak scheduled-only entities/day | 45 (June 30) |
| 30-day average projection | ~1,080/month |
| 30-day worst-case projection (30 days at peak) | 1,350/month |
| Headroom under 2,500/month cap | ~1,150 (46%) |

Both projections land comfortably under the free tier's 2,500/month cap.

### Open Item Surfaced, Not Resolved

Claude Code's investigation noted **April and May 2026 both show elevated
non-scheduled-run SGO traffic that predates CLV entirely** (CLV didn't exist until
June 12). This wasn't identified as a specific cause — possibly early
development/testing calls — and doesn't threaten the current projection since it's
not part of what's still running, but it's an unexplained data point worth a line in
the record, similar in spirit to the still-untraced commit `85b5bd5` from Session 16.

---

## What Happened on July 2, 2026 (Session 16)

### 7-Day Performance Review (June 24 – July 1)

Full production vs. shadow comparison across scored legs, parlay legs, and overall parlays, run via direct Supabase queries.

**Scored leg win rates (production vs shadow, same props nearly identical):**
| Prop | Production WR | Shadow WR |
|---|---|---|
| strikeouts/over | 69.7% (n=109) | 69.4% (n=108) |
| totalBases/under | 59.1% (n=674, prod scoring only — excluded from prod parlays) | 58.8% (n=663) |
| hits/over | 58.8% (n=267) | 59.0% (n=266) |
| hits/under | 51.4% (n=109) | 51.4% (n=109) |

**Parlay-level leg win rates — same-prop comparison revealed a real shadow scoring advantage:**
| Prop | Shadow Leg WR | Production Leg WR | Shadow Advantage |
|---|---|---|---|
| hits/over | 66.7% (n=78) | 61.8% (n=152) | **+4.9pp** |
| strikeouts/over | 77.0% (n=100) | 72.1% (n=61) | **+4.9pp** |

**Overall parlay win rate, 7-day totals:**
| Pipeline | Resolved | Won | Void | Win Rate |
|---|---|---|---|---|
| Production | 60 | 18 | 89 | 30.0% |
| Shadow | 97 | 16 | 0 | 16.5% |

### Finding 1 — TB/under Dilutes Shadow's Parlay Win Rate (Combinatorial, Not a Bug)

Shadow's blended parlay win rate (16.5%) looked worse than production's (30.0%) despite shadow's per-leg scoring being measurably better on shared props. Isolating totalBases/under (50.6% of shadow's leg volume, weakest win rate of shadow's three props) resolved the apparent contradiction:

| Segment | Resolved | Won | Win Rate |
|---|---|---|---|
| Shadow — with TB/under leg | 87 | 12 | 13.8% |
| Shadow — without TB/under leg | 10 | 4 | 40.0% |
| Production | 60 | 18 | 30.0% |

Shadow's TB-free parlays (40.0%, small n=10) exceed production's win rate — consistent with shadow's genuine per-leg scoring advantage. TB/under itself is not broken — its own leg win rate (57.9-59.4%) is well above its ~39.1% documented breakeven — but because a 4-leg parlay's win probability is closer to a *product* than an *average* of its legs, mixing a weaker-but-still-profitable prop into the same pool as stronger props structurally caps the blended parlay win rate. This is a parlay-construction-strategy question (flat pool vs. segregated pools vs. quality-weighted selection), not a scoring defect. **Not yet addressed — flagged for a future session** (see Future Considerations).

Also confirmed live: the Session 15 TB/under null-signal fix has taken effect — `park_factor` now populated on 83.2% of legs and `coverage_vs_opponent` on 59.4% (both were 0% pre-fix).

### Finding 2 — Batting Order Slot Gate Confirmed Backwards, Fixed and Deployed

**Investigation:** Re-tested the June 12 slot-gate hypothesis (documented as contradicted-but-unresolved in `ARCHITECTURE_DECISIONS.md` Lesson 32) against the most recent 7 days of data:

| Prop | Protected slots (no penalty) | Penalized slots (-8) |
|---|---|---|
| hits/over | slots 1-5: 60.0% WR (n=205) | slots 6-9: **63.3% WR** (n=30) |
| strikeouts/over | slots 1-6: 67.8% WR (n=87) | slots 7-9: **73.7% WR** (n=19) |

Penalized slots outperformed protected slots on both props, consistent with the June 12 finding — three additional weeks of data did not resolve the contradiction, confirming it should be removed rather than continue to be monitored.

**Void investigation:** Queried `mlb_parlay_recommendations_v2.superseded_reason` joined to `mlb_parlay_legs_v2.lineup_check_status` for all 78 voided parlays in the window:

- **100% of void parlays** had a `SCRATCHED` or `BATTING_ORDER_OUT_OF_RANGE` leg — confirms CLR is the sole void mechanism (no other cause found)
- **OUT_OF_RANGE present in 60/78 (76.9%)** — the dominant trigger
- **SCRATCHED present in 39/78 (50.0%)**
- **35/78 (44.9%) voided from OUT_OF_RANGE alone** — no scratched player involved, meaning the selected player genuinely was in the starting lineup and the parlay was rebuilt purely because the confirmed slot fell outside the (contradicted) favorable range

This quantified the cost of the bad slot-gate assumption beyond just the -8 scoring penalty: it was also driving a large share of unnecessary parlay voids.

Separately, the `void_reason` column on `mlb_scored_legs` was checked as a potential shortcut for this analysis and found to be non-functional — 66 of 68 voided legs in the window had `void_reason = NULL`. The `lineup_check_status`-based join was used instead. **`void_reason` logging gap not yet fixed — flagged for a future session.**

**Fix implemented via Claude Code, validated against live repo before changes:**
- `src/engine/simple_scorer.py` — removed the `-8` slot-gate penalty block entirely (not flipped — went neutral). `batting_order` and `lineup_check_status` annotation/logging left fully intact.
- `src/apis/lineup_confirmation.py` — two call sites changed so only `SCRATCHED` triggers a CLR rebuild: `_find_affected_parlays()` SQL filter and `run_confirmed_lineup_resolution()` bad-legs filter. `BATTING_ORDER_OUT_OF_RANGE` is now annotation-only. Docstring and log message updated to match.
- Confirmed shadow pipeline unaffected — no `batting_order`/`lineup_check_status` columns exist on shadow tables.
- 13/13 tests passed in a standalone test script (`test_slot_gate_removal.py` — no pytest in the environment).
- Deployed: commit `4cd3c37`, pushed after a clean rebase onto `origin/master` (which had advanced to `85b5bd5` since Session 15's `9eed486` — origin of that intermediate commit not yet confirmed).

**Post-deploy verification (same day, very small sample so far):**
| Test | Result | Confidence |
|---|---|---|
| `superseded_reason LIKE '%OUT_OF_RANGE%' AND NOT LIKE '%SCRATCHED%'` | **0 rows** | **Confirmed pass** — binary test, not sample-dependent |
| Void rate, post-fix vs pre-fix | 0.0% (n=5) vs 58.3% (n=168) | Directionally strong, too small to confirm yet |
| Composite score gap, OOR vs CONFIRMED legs | 69.6 vs 77.8 (n=1 vs n=3) | Inconclusive — sample far too small to interpret |

---

## Session 17 Commits

| Commit | Message |
|--------|---------|
| `d3a642c` | feat: remove CLV tracking layer, scope SGO to 3 scheduled pipeline runs |

## Session 16 Commits

| Commit | Message |
|--------|---------|
| `4cd3c37` | fix: remove batting order slot gate — scoring penalty and CLR rebuild trigger |

---

## Pending Items — Next Session

### 0. Cancel SGO Pro Subscription (High Priority, Session 17)
The pipeline change is deployed and validated (~1,080-1,350 projected objects/month,
well under the 2,500 free-tier cap), but the actual account-level downgrade — canceling
the $149/mo Pro plan and confirming the SGO account is active on the Amateur/free tier
— is a manual action outside the codebase and hasn't been confirmed done yet. Do this
first; the code change alone doesn't save any money until the subscription itself is
downgraded.

### 0.1 Verify Live SGO Volume Post-Deploy (High Priority, Session 17)
Query `mlb_sgo_request_log` a few days after the `d3a642c` deploy. Expected pattern:
exactly 3 requests/day, all inside the 9AM/12PM/5:30PM windows, nothing scattered
outside them, and no new `check_type='clv'` rows in `mlb_pending_lineup_checks`.
```sql
SELECT (timestamp::timestamptz AT TIME ZONE 'America/New_York')::date as et_day,
    COUNT(*) as requests, SUM(entities_consumed) as entities
FROM mlb_sgo_request_log
WHERE timestamp::timestamptz >= '2026-07-07'
GROUP BY 1 ORDER BY 1;
```

### 0.2 Investigate Unexplained April/May SGO Traffic (Low Priority, Session 17)
Elevated non-scheduled-run SGO volume in April/May 2026 predates CLV (which didn't
exist until June 12) and was never identified. Doesn't threaten the current usage
projection since it's not part of what's still running, but worth a quick look if SGO
volume ever unexpectedly climbs again post-CLV-removal.

### 1. Recheck Slot Gate Removal With Real Volume (~July 5-6, High Priority)
Re-run the four post-deploy tests with several days of accumulated data:
```sql
-- Void rate, pre vs post fix
SELECT
    CASE WHEN run_date >= '2026-07-02' THEN 'post_fix' ELSE 'pre_fix' END as period,
    COUNT(*) as total_parlays,
    COUNT(*) FILTER (WHERE outcome = 'void') as void_parlays,
    (COUNT(*) FILTER (WHERE outcome = 'void') * 100.0 / COUNT(*))::numeric(5,1) as void_rate
FROM mlb_parlay_recommendations_v2
WHERE run_date >= '2026-06-24'
GROUP BY period;

-- Composite score gap, now with real volume
SELECT
    lineup_check_status,
    COUNT(*) as legs,
    AVG(composite_score)::numeric(5,1) as avg_composite_score
FROM mlb_scored_legs
WHERE run_date >= '2026-07-02'
  AND stat IN ('hits', 'strikeouts') AND direction = 'over'
  AND lineup_check_status IN ('LINEUP_CONFIRMED', 'BATTING_ORDER_OUT_OF_RANGE')
GROUP BY lineup_check_status;

-- Win rate on formerly-penalized slots — should hold near 63.3% (hits/over) and 73.7% (SO/over)
SELECT
    stat, direction, lineup_check_status,
    COUNT(*) FILTER (WHERE result IN ('won','lost')) as resolved,
    (COUNT(*) FILTER (WHERE result = 'won') * 100.0 /
     NULLIF(COUNT(*) FILTER (WHERE result IN ('won','lost')), 0))::numeric(5,1) as win_rate
FROM mlb_scored_legs
WHERE run_date >= '2026-07-02'
  AND stat IN ('hits', 'strikeouts') AND direction = 'over'
  AND lineup_check_status IN ('LINEUP_CONFIRMED', 'BATTING_ORDER_OUT_OF_RANGE')
GROUP BY stat, direction, lineup_check_status;
```
Target: void rate meaningfully below 58.3% (some voids still expected — SCRATCHED remains a legitimate trigger), composite score gap shrinking toward ~0, formerly-penalized-slot win rates holding at or above the levels that motivated the fix.

### 2. Confirm Origin of Commit 85b5bd5 (Medium Priority)
`git log 9eed486..85b5bd5 --oneline` — this commit landed on `origin/master` between Session 15 and Session 16 without a corresponding session doc entry. The rebase was clean with no conflicts, so it's very unlikely to have broken anything, but its contents aren't yet confirmed against any session record.

### 3. Fix void_reason Logging Gap (Medium Priority)
66 of 68 voided legs in `mlb_scored_legs` have `void_reason = NULL`. The column exists specifically to answer "why did this void" and isn't being populated for the large majority of cases. Investigate the resolver code path (`parlay_outcome_resolver.py` / `outcome_resolver.py`) to determine why, and fix so future void investigations don't require a manual join through `lineup_check_status`.

### 4. TB/under Parlay Construction Strategy (Medium Priority — ties to existing TB/under promotion decision)
TB/under's own leg-level edge is real (+~20pp above breakeven) but structurally drags down blended parlay win rate when mixed with faster props (hits/over, SO/over) in a flat 4-leg pool, since parlay win probability is closer to a product than an average of leg win rates. Before the existing TB/under production-promotion decision (previously targeted ~July 9), consider whether promotion should come with a construction change — e.g., segregated TB-only vs. non-TB parlay pools, or quality-weighted leg selection — rather than adding it to the existing flat pool as-is. Simulating this against existing shadow leg data (no new signal work required) would be a reasonable next step.

### 5. Add hits/over Coverage Ceiling at ~80% (Carried over from Session 15, still pending)
See Session 15 notes below — not addressed this session.

### 6. Re-evaluate K/9 and WHIP Signals After Starter-Only Data Accumulates (~July 9, carried over)
See Session 15 notes below — not addressed this session.

### 7. Project File Cleanup (Carried over, still pending)
Retire stale files from Project Knowledge: `SYSTEM_DIAGNOSTIC_REPORT_2026-05-12.md`, `CHAT_HANDOFF_2026-05-28.md`, `MLB_Scored_Legs_Table_Schema.csv`, `README_10.md` (superseded by this file + `BUILD_STATUS.md`).

---

## System Health Indicators

### Green Lights
✅ CLV removal deployed and validated against live repo before changes made (Session 17)
✅ 10/10 standalone tests passed for CLV removal
✅ CLV volume attribution independently confirmed via DB join, not just estimated (52% overall, 78% of July)
✅ Retrospective usage projection (~1,080-1,350/month) comfortably clears the 2,500 free-tier cap
✅ CLV predictive-value test run before removal, not just cost analysis — decision backed by both cost and signal-quality evidence
✅ Slot-gate fix deployed and validated against live repo before changes made (Session 16)
✅ 13/13 standalone tests passed for slot-gate removal
✅ Post-deploy binary test (`superseded_reason`) confirms slot-gate fix is live
✅ CLR annotation layer itself confirmed healthy — 80% `LINEUP_CONFIRMED` rate, 91.1% of legs get some status, over the review window
✅ Shadow's per-leg scoring advantage on hits/over and SO/over is now quantified and understood (+4.9pp both props)
✅ TB/under null-signal fix from Session 15 confirmed live (park_factor 83.2% populated, opp_coverage 59.4%, both were 0% pre-fix)

### Yellow Flags
🔲 SGO Pro subscription cancellation not yet confirmed — code change alone doesn't reduce cost until account is downgraded
⚠️ Unexplained April/May SGO traffic, predating CLV — not investigated (Session 17)
⚠️ Void rate and win-rate post-fix checks for slot-gate removal need more volume (~July 5-6 recheck, Session 16, not addressed this session)
⚠️ void_reason column not populating — logging gap, not yet fixed
⚠️ TB/under parlay-level combinatorial drag needs a construction-strategy decision before promotion
⚠️ Unknown commit 85b5bd5 on origin/master — not yet traced to a session
⚠️ hits/over ~80% coverage ceiling still pending implementation (carried from Session 15)
⚠️ K/9 and WHIP signal re-evaluation with starter-only data still pending (~July 9)

### Red Flags
None currently

---

## Session 15 Handoff (June 25, 2026) — Preserved for Reference

✅ WHIP rank removed from production hits scorer — was creating false 80+ bucket at 47.4% win rate
✅ hits/under gate raised from 40% to 65% in main.py and parlay_builder.py
✅ Starter-only pitcher rank pool added — eliminates reliever contamination
✅ TB/under enriched signals fixed — park_factor and opp_coverage now populating (confirmed live in Session 16)
✅ Vulnerability thresholds recalibrated — symmetric penalties, weak pitcher penalty added
✅ Player cap fallback fixed — now checks production-eligible (non-TB) legs not total pool
✅ All changes deployed across 3 commits: b7b1038, 97fbcb2, 9eed486

See prior version of this document (or git history) for full Session 15 detail, including the WHIP-removal root cause, hits/under gate analysis, starter-only rank pool implementation, TB/under 3-bug fix breakdown, vulnerability recalibration data, and player-cap fallback bug chain.

---

**Last Review:** July 7, 2026
**System Status:** ✅ Operational — CLV Layer Removed, SGO Downgrade Pending User Action
**Next Review:** Post-deploy SGO volume check (few days after Jul 7) + carried-over July 5-6 slot-gate recheck (overdue, not yet done)
**Pending Decisions:** Cancel SGO Pro subscription (user action, not yet confirmed), TB/under promotion + construction strategy (~July 9), K/9/WHIP re-evaluation (~July 9), hits/over ceiling (carried, no target date set)
