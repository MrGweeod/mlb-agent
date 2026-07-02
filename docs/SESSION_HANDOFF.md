# MLB Parlay Agent — Session Handoff
**Last Updated:** July 2, 2026 (Session 16 — 7-Day Performance Review + Batting Order Slot Gate Removal)

## Current Status
✅ **OPERATIONAL — SESSION 16 DEPLOYED**
✅ **Batting order -8 scoring penalty removed — confirmed backwards on 3+ weeks of data**
✅ **BATTING_ORDER_OUT_OF_RANGE downgraded from CLR rebuild trigger to annotation-only**
✅ **SCRATCHED remains the sole CLR rebuild trigger — unchanged**
✅ **Fix deployed: commit 4cd3c37 (Jul 2, 2026), rebased cleanly onto 85b5bd5**
✅ **Post-deploy test (superseded_reason check): PASS — 0 rows, confirmed live**
⚠️ **Post-deploy void rate (0.0% vs 58.3% pre-fix) and win-rate checks: promising but n too small to confirm — recheck ~July 5-6**
⚠️ **void_reason column on mlb_scored_legs confirmed non-functional — 97% NULL even for voided legs — not yet fixed**
⚠️ **TB/under parlay-level drag identified as structural/combinatorial, not a signal-quality bug — construction strategy question for a future session**
⚠️ **Unknown commit 85b5bd5 appeared between Session 15 (9eed486) and this session — origin not yet confirmed, recommend `git log 9eed486..85b5bd5 --oneline`**

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

## Session 16 Commits

| Commit | Message |
|--------|---------|
| `4cd3c37` | fix: remove batting order slot gate — scoring penalty and CLR rebuild trigger |

---

## Pending Items — Next Session

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
✅ Slot-gate fix deployed and validated against live repo before changes made
✅ 13/13 standalone tests passed
✅ Post-deploy binary test (`superseded_reason`) confirms fix is live
✅ CLR annotation layer itself confirmed healthy — 80% `LINEUP_CONFIRMED` rate, 91.1% of legs get some status, over the review window
✅ Shadow's per-leg scoring advantage on hits/over and SO/over is now quantified and understood (+4.9pp both props)
✅ TB/under null-signal fix from Session 15 confirmed live (park_factor 83.2% populated, opp_coverage 59.4%, both were 0% pre-fix)

### Yellow Flags
⚠️ Void rate and win-rate post-fix checks need more volume (~July 5-6 recheck)
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

**Last Review:** July 2, 2026
**System Status:** ✅ Operational — Slot Gate Fix Deployed, Verification In Progress
**Next Review:** July 5-6, 2026 — slot-gate fix volume recheck
**Pending Decisions:** TB/under promotion + construction strategy (~July 9), K/9/WHIP re-evaluation (~July 9), hits/over ceiling (carried, no target date set)
