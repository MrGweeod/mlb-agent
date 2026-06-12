# MLB Parlay Agent — Session Handoff
**Last Updated:** June 12, 2026 (Session 10 — Lineup Confirmation Layer + CLV Tracking + Backtest Harness + Correlation Spec)

## Current Status
✅ **OPERATIONAL — SESSION 10 DEPLOYED**
✅ **Lineup confirmation layer fully built, migrated, verified (19/19 spot-check)**
✅ **CLV tracking layer fully built, migrated, verified**
✅ **Batting order backfill complete (881/1031 legs, 85.5%)**
✅ **Backtest harness built and run — EV-sort and slot gate both discard on clean pool**
✅ **Correlation restructure (offense stack bonus) specced and ready for Claude Code**
✅ **verify_lineup_layer.py and verify_clv.py both passing**

---

## What Happened on June 12, 2026 (Session 10)

### Performance Analysis + Diagnostic Queries
Ran four diagnostic queries (Q1-Q4) against June 1-10 data to investigate the "multiple losing legs per parlay" frustration:

**Key findings:**
- **Adverse selection disconfirmed** — selected legs win at same rate as pool (63.7% vs 64.1% hits over, 68.0% vs 61.8% SO over). Builder mechanics are working.
- **Score signal healthy** — in-parlay win rate rises monotonically: 63.7% (65-74 bucket) → 68.5% (75-84 bucket). Only 2 legs in 85+ bucket reached parlays.
- **Correlation confirmed positive** — same-game parlays win 20.0% vs 12.6% distinct-game. Positive correlation fattens both tails — this is net favorable for parlays.
- **Root cause identified: hits/over at or below breakeven** — 63.7% win rate vs 66.9% breakeven at -202 avg odds. SO/over is the genuine edge (+5.6pp). Multi-loss clustering is expected variance, not a system flaw.

### Lineup Confirmation Layer (Phases 1-5 built, all verified)
Full event-driven layer keyed off game start times. Key design elements:

- **Database-backed scheduler** — `mlb_pending_lineup_checks` table, 1-minute drain loop in `server.py`. Restart-safe by construction.
- **T-45 lineup checks** — `LINEUP_CHECK_OFFSET_MINUTES = 45`, configurable. Second pass (`LINEUP_CHECK_SECOND_PASS`) available if lineups not posted at T-45.
- **Four annotation states:** `MISSING_LINEUP_CONFIRMATION`, `LINEUP_CONFIRMED`, `BATTING_ORDER_OUT_OF_RANGE`, `SCRATCHED`
- **CONFIRMED_LINEUP_RESOLUTION run type** — when a selected player is SCRATCHED or OUT_OF_RANGE, affected parlays are voided and rebuilt from upcoming-games-only pool. Superseded parlays marked void with `superseded_by_batch_id` and `superseded_reason`.
- **Slot gate (soft)** — `-8` scoring penalty for legs with known unfavorable batting order slot. Unfavorable defined by `BATTING_ORDER_FAVORABLE` constants in `main.py`.
- **Hydrate parser verified** — reads `liveData.boxscore.teams[side].battingOrder` (list of player IDs, index+1 = slot). Verified 19/19 match on game_pk=824105.
- **Batting order backfill** — 881/1031 June 1-10 legs populated via `scripts/backfill_batting_order.py`.

**Migrations applied:**
```sql
ALTER TABLE mlb_scored_legs ADD COLUMN IF NOT EXISTS batting_order integer;
ALTER TABLE mlb_scored_legs ADD COLUMN IF NOT EXISTS lineup_check_status text;
ALTER TABLE mlb_scored_legs ADD COLUMN IF NOT EXISTS lineup_checked_at timestamp without time zone;
ALTER TABLE mlb_parlay_legs_v2 ADD COLUMN IF NOT EXISTS batting_order integer;
ALTER TABLE mlb_parlay_legs_v2 ADD COLUMN IF NOT EXISTS lineup_check_status varchar;
ALTER TABLE mlb_parlay_legs_v2 ADD COLUMN IF NOT EXISTS lineup_checked_at timestamp with time zone;
ALTER TABLE mlb_parlay_recommendations_v2 ADD COLUMN IF NOT EXISTS superseded_by_batch_id varchar;
ALTER TABLE mlb_parlay_recommendations_v2 ADD COLUMN IF NOT EXISTS superseded_reason text;
CREATE TABLE IF NOT EXISTS mlb_pending_lineup_checks (...);
```

**Files created/modified:**
- `sql/lineup_confirmation_migration.sql`
- `src/apis/lineup_confirmation.py` (new — full worker)
- `src/pipelines/lineup_scheduler.py` (new — scheduler)
- `src/web/server.py` — drain cron added
- `src/engine/simple_scorer.py` — slot gate penalty
- `main.py` — log_slate_start_times(), schedule_lineup_checks() call
- `scripts/backfill_batting_order.py` (new)
- `verify_lineup_layer.py` (new)

### CLV Tracking Layer (fully built, migrated, verified)
Closing Line Value capture at `game_start_time − 1 minute` for all scored legs. Reuses existing scheduler infrastructure.

- **check_type column** added to `mlb_pending_lineup_checks` — `'lineup'` | `'clv'`, default `'lineup'`
- **CLV rows scheduled** alongside lineup rows in every 9 AM pipeline run (one CLV row per start-time group at T-1)
- **SGO reuse** — `run_clv_snapshot()` imports `get_todays_games()` and `get_player_props()` from existing `sportsgameodds.py`. Natural key match: `(player_id, stat, line, direction)`.
- **Forward-only** — CLV clock started with first 9 AM pipeline run after June 12 deployment.
- **`compute_clv()` unit tests pass 7/7** including null inputs and unparseable odds.

**Migrations applied:**
```sql
ALTER TABLE mlb_pending_lineup_checks ADD COLUMN IF NOT EXISTS check_type text NOT NULL DEFAULT 'lineup';
ALTER TABLE mlb_scored_legs ADD COLUMN IF NOT EXISTS closing_odds text;
ALTER TABLE mlb_scored_legs ADD COLUMN IF NOT EXISTS closing_odds_captured_at timestamp without time zone;
CREATE INDEX IF NOT EXISTS idx_pending_checks_type ON mlb_pending_lineup_checks (check_type, status, trigger_at);
```

**Files created/modified:**
- `sql/clv_tracking_migration.sql`
- `src/apis/clv_tracker.py` (new)
- `src/apis/lineup_confirmation.py` — check_type dispatch added
- `main.py` — CLV_OFFSET_MINUTES constant, schedule_clv_checks() call
- `verify_clv.py` (new)

### Backtest Harness (built and run)
`scripts/run_backtest.py` — replays June 1-10 history against two variants.

**Key finding — both variants discard on clean production pool (hits/over + SO/over only, 533 legs):**

| Variant | Leg Δ | Parlay Δ | Parlays Built | Verdict |
|---|---|---|---|---|
| EV-sort | +0.0pp | -6.2pp | 49 vs 191 | Discard |
| Slot gate | -0.0pp | -9.7pp | 47 vs 191 | Discard |
| Combined | -0.1pp | -8.6pp | 43 vs 191 | Discard |

**Root cause:** pool-thinning. With only 533 production legs and 4-leg minimum + construction constraints, any filtering drops parlays from 191 to 43-49, forcing the builder into worse combinations. The variants improve nothing at leg level within the production whitelist because coverage_overall doesn't discriminate well within an already-validated leg pool.

**Important: first harness run was contaminated** — it ran against 960 legs (included TB/under at 55.5% and hits/under at 39.2%). The apparent +6.3pp leg improvement in the first run was entirely from filtering out those bad props, not from EV-sort finding better legs. Second run (`backtest_june1_10_v2.txt`) on the clean 533-leg pool shows +0.0pp.

**Other validated findings:**
- Pitcher SO props: zero pitcher legs in DB — only batter SO scored. Pitcher K total market not integrated.
- TB under: 55.5% win rate vs 60.7% breakeven — below breakeven. Shadow validation continuing.
- TB over: no data (1 leg, 0 wins) — excluded permanently.
- Batting order signal: slots 6-9 won at 66.7% vs slots 1-5 at 61.2% — contradicts the PA-count hypothesis. Keep annotation, skip production gate.

### Correlation Restructure Spec (ready for Claude Code)
`CORRELATION_RESTRUCTURE_SPEC.md` written and ready. Offense stack bonus in shadow pipeline only.

**Design:**
- Post-scoring pass in `run_enriched_pipeline.py` after individual leg scores computed
- `pitcher_vulnerability()` function: composite of ERA rank (inverted), K/9 rank (inverted), WHIP rank — averaged, normalized 0-1
- `STACK_VULNERABILITY_THRESHOLD = 0.60` (bottom third of pitcher pool)
- `STACK_BONUS = 4.0` points added to `composite_score` for each leg in qualifying stack
- Qualifying stack: 2+ hitter legs from same `(team, game_pk)` facing vulnerable pitcher
- Falls back to raw `pitcher_era` when ranks NULL (98% ERA population)
- Persists `stack_bonus_applied` (boolean) and `pitcher_vulnerability` (numeric) to `mlb_scored_legs_enriched`
- New migration: `sql/stack_bonus_migration.sql`

**Promotion criteria (after 7+ shadow days):** stack legs win ≥5pp more than non-stack legs AND shadow parlay win rate ≥ production AND ≥2 stacks/day average.

---

## Pending Items — Next Session

### 1. Run Correlation Restructure Spec (Highest Priority)
Hand `CORRELATION_RESTRUCTURE_SPEC.md` to Claude Code. Opening context:
> "Lineup confirmation layer and CLV tracking layer are fully built and verified. Do not touch production files. Shadow pipeline only. Read the spec before touching anything."

After build, apply `sql/stack_bonus_migration.sql` in Supabase, verify columns exist on `mlb_scored_legs_enriched`, confirm Railway logs show `[stack_bonus]` lines after first pipeline run.

### 2. Monitor CLV Capture Rate (First Live Slate)
Run after today's pipeline:
```bash
set -a && source .env && set +a && python verify_clv.py
```
Section 3 should show both `lineup` and `clv` rows scheduled per start-time group. Section 4 should show closing odds captured for scored legs. If capture rate near 0%, the SGO natural-key match failed — inspect a raw response.

### 3. Monitor Lineup Annotation Mix (First Live Slate)
Run `verify_lineup_layer.py` after T-45 checks fire. Section 3 should show a realistic mix of `LINEUP_CONFIRMED` and `SCRATCHED` rather than all `MISSING_LINEUP_CONFIRMATION`. If everything stays `MISSING` right up to first pitch, flip `LINEUP_CHECK_SECOND_PASS = True`.

### 4. Stack Bonus Validation Queries (After 7 Days Shadow Data)
```sql
-- Stack leg win rate vs non-stack
SELECT stack_bonus_applied,
    COUNT(*) FILTER (WHERE result IN ('won','lost')) as resolved,
    (COUNT(*) FILTER (WHERE result='won') * 100.0 /
     NULLIF(COUNT(*) FILTER (WHERE result IN ('won','lost')),0))::numeric(5,1) as win_rate
FROM mlb_scored_legs_enriched
WHERE run_date >= (CURRENT_DATE - INTERVAL '7 days')::text
GROUP BY stack_bonus_applied;
```

### 5. TB Under WHIP Signal Validation (Late June)
Run ~2 weeks after June 9:
```sql
SELECT
    CASE
        WHEN pitcher_whip_rank <= 8 THEN '1_elite'
        WHEN pitcher_whip_rank <= 16 THEN '2_above_avg'
        WHEN pitcher_whip_rank <= 24 THEN '3_below_avg'
        ELSE '4_weak'
    END as whip_tier,
    COUNT(*) FILTER (WHERE result IN ('hit','miss')) as resolved,
    (COUNT(*) FILTER (WHERE result='hit') * 100.0 /
     NULLIF(COUNT(*) FILTER (WHERE result IN ('hit','miss')),0))::numeric(5,1) as hit_rate_pct
FROM mlb_training_data
WHERE game_date >= '2026-04-27'
  AND stat = 'totalBases' AND direction = 'under'
  AND pitcher_whip_rank IS NOT NULL
GROUP BY whip_tier ORDER BY whip_tier;
```
Promote TB under to production only if elite tier (rank 1-8) wins 5pp+ above weak tier (rank 23-30).

### 6. CLV Signal Read (After ~2 Weeks)
```sql
SELECT stat, direction,
    COUNT(*) FILTER (WHERE closing_odds IS NOT NULL) AS captured,
    (AVG(
        CASE WHEN closing_odds IS NULL OR odds IS NULL THEN NULL
        ELSE
            (CASE WHEN closing_odds::numeric < 0
                  THEN ABS(closing_odds::numeric)/(ABS(closing_odds::numeric)+100)
                  ELSE 100/(closing_odds::numeric+100) END)
          - (CASE WHEN odds::numeric < 0
                  THEN ABS(odds::numeric)/(ABS(odds::numeric)+100)
                  ELSE 100/(odds::numeric+100) END)
        END
    ) * 100)::numeric(5,2) AS avg_clv_pct
FROM mlb_scored_legs
WHERE run_date >= '2026-06-12'
  AND closing_odds IS NOT NULL
GROUP BY stat, direction ORDER BY avg_clv_pct DESC;
```
Expect SO/over positive CLV, hits/over near zero or negative.

### 7. 85%+ Coverage Ceiling (Quick Win — Still Pending)
One-line fix in `main.py` gate. Confirmed trap by training data (hits over drops from 71.8% to 31.5% above 84%). Still not implemented.

### 8. Verify_common.py Refactor (Low Priority)
Extract shared boilerplate from `verify_lineup_layer.py` and `verify_clv.py` into a `verify_common.py` module. Establishes pattern for future verification scripts (backtest, Statcast, etc.).

---

## Key Data Findings This Session

- **Hits/over is at or below breakeven** — 63.7% win rate vs 66.9% breakeven at -202 odds. Primary loss driver confirmed.
- **SO/over has genuine edge** — 68.0% selected win rate vs 62.4% breakeven at -166 odds. +5.6pp edge confirmed.
- **Same-game correlation is positive** — 20.0% parlay win rate with same-game pair vs 12.6% without. +7.4pp confirmed. Net favorable for all-or-nothing bets.
- **EV-sort and slot gate both fail** on clean 533-leg production pool due to pool-thinning.
- **Backtest pool contamination lesson** — must whitelist-filter the scored-leg pool to match production before running variants. 960-leg pool vs 533-leg clean pool produced entirely different conclusions.
- **Pitcher SO market not in pipeline** — all strikeout legs are batter props. Pitcher K total market would require new integration.
- **Batting order signal contradicts hypothesis** — slots 6-9 outperform slots 1-5 on current sample (small). Keep annotation, skip production slot gate.
- **CLV clock started** — June 12 is day 1. First read in ~2 weeks.

---

## Verification Scripts

```bash
# Lineup layer (run after each deploy)
set -a && source .env && set +a && python verify_lineup_layer.py --game-pk 824105

# CLV layer (run daily after first live slate)
set -a && source .env && set +a && python verify_clv.py

# Backtest (run against clean pool only)
set -a && source .env && set +a && python scripts/run_backtest.py --baseline-only
set -a && source .env && set +a && python scripts/run_backtest.py --output reports/backtest_june1_10_v2.txt
```

---

## System Health Indicators

### Green Lights
✅ Lineup annotation layer built and verified (19/19 spot-check)
✅ CLV tracking built, migrated, verified (10/10, 2 skipped expected)
✅ Event-driven scheduler restart-safe (Postgres-backed, stateless drain)
✅ Batting order backfill 85.5% (881/1031)
✅ Backtest harness built — both variants correctly discarded on clean data
✅ Correlation spec written and ready for Claude Code
✅ SGO CLV reuse confirmed (get_player_props() imported verbatim)
✅ Parser verified: 19/19 slot match on real game data
✅ All prior Session 9 green lights maintained

### Yellow Flags
⚠️ CLV clock started June 12 — no data yet, first read in ~2 weeks
⚠️ Lineup annotation not yet observed on a live slate — T-45 posting time unvalidated
⚠️ Correlation restructure spec ready but not yet built
⚠️ 85%+ coverage ceiling still not implemented
⚠️ TB under shadow validation ongoing — not ready for production
⚠️ Hits/over at or below breakeven — pool expansion needed before filtering improves parlay quality
⚠️ verify_common.py refactor pending

### Red Flags
None currently

---

**Last Review:** June 12, 2026
**System Status:** ✅ Operational — Lineup + CLV Layers Live, Correlation Spec Ready
**Next Review:** June 13, 2026 (Monitor first live CLV capture + lineup annotation mix)
**Pending Decisions:** Correlation restructure build (next Claude Code session), TB under promotion (late June), hits/over EV gate (after CLV data matures)
