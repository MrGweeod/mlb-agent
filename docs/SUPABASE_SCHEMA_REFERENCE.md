# Supabase Schema Reference — MLB Parlay Agent
**Last Updated:** 2026-07-29 (Session 23 — `mlb_prop_legs_history` now populated: documented `market_scope`/`player_role` columns, the two-unique-constraints gotcha (partial index for game-scope rows, and the `WHERE player_id IS NULL` requirement on its `ON CONFLICT` target), and corrected the documented-vs-actual `mlb_parlay_recommendations_v2.source` values found wrong this session.)
**Source:** Exported from Supabase information_schema + verified against migration logs + (for the new reference schema) direct live inspection of `information_schema.columns`/`table_constraints`/`pg_indexes` via Supabase MCP, session-dated 2026-07-29

This file is the authoritative schema reference. Always read this before writing SQL queries.

---

## Critical Type Rules (Read First)

| Table | Column | Type | Cast Required? |
|-------|--------|------|----------------|
| `mlb_scored_legs` | `run_date` | TEXT | Yes — `run_date = '2026-05-15'` or `(CURRENT_DATE)::text` |
| `mlb_scored_legs` | `odds` | TEXT | Yes — `odds::numeric` for math |
| `mlb_scored_legs` | `closing_odds` | TEXT | Yes — `closing_odds::numeric` for CLV math (layer removed Session 17, historical data only) |
| `mlb_scored_legs` | `line` | REAL | No cast for comparisons |
| `mlb_scored_legs` | `result` | TEXT | Values: `'won'/'lost'/'void'/'pending'` |
| `mlb_scored_legs_enriched` | `run_date` | TEXT | Same rules as `mlb_scored_legs` |
| `mlb_scored_legs_enriched` | `odds` | TEXT | Yes — `odds::numeric` for math |
| `mlb_scored_legs_enriched` | `result` | TEXT | Values: `'won'/'lost'/'void'/'pending'` |
| `mlb_scored_legs_enriched` | `pitcher_vulnerability`, `pitcher_era`, `pitcher_k9`, `pitcher_whip`, `blended_era_rank` | NUMERIC | ⚠️ psycopg2 returns these as Python `Decimal`, not float. `json.dumps()` cannot serialize `Decimal` directly — use `json.dumps(data, default=str)` in any application code, or cast explicitly in SQL. Bit the manual parlay dashboard's `/api/manual/legs` endpoint in Session 18 (silent 500, misreported as an auth failure by the frontend) before being fixed. |
| `mlb_parlay_recommendations_v2` | `run_date` | DATE | No cast needed |
| `mlb_parlay_recommendations_v2` | `total_odds` | NUMERIC | No cast needed |
| `mlb_parlay_recommendations_v2` | `outcome` | VARCHAR | Values: `'won'/'lost'/'void'/'pending'` |
| `mlb_parlay_recommendations_v2` | `source` | VARCHAR | Free text, not an enum. ⚠️ Documented-vs-actual gap found Session 23: the 9 AM slot correctly produces `'auto_9am'` (via an hour-based fallback when no explicit source is passed), but the 12 PM/5:30 PM slots pass their raw scheduler label straight through, producing literal `'midday'`/`'evening'` in production — NOT `'auto_12pm'`/`'auto_530pm'` as this doc previously claimed. Pre-existing, not fixed. Query `source` values defensively (`SELECT DISTINCT source ...`) rather than assuming the documented set is exhaustive. Also: `'manual'` (the "Regenerate Now" button — still runs the algorithm, on demand), `'manual_pick'` (Session 18 — hand-picked from `/manual`), `'dashboard_pick'` (Session 22 — hand-picked from the Diamond Line dashboard's Slate Explorer). Don't conflate `'manual'`/`'manual_pick'`/`'dashboard_pick'` — three different picking flows. |
| `mlb_parlay_legs_v2` | `line` | NUMERIC | No cast needed |
| `mlb_parlay_legs_v2` | `odds` | VARCHAR | Yes — `odds::numeric` for math |
| `mlb_parlay_legs_v2` | `outcome` | VARCHAR | Values: `'won'/'lost'/'void'/'pending'` |
| `mlb_parlay_recommendations_enriched` | `run_date` | DATE | No cast needed |
| `mlb_parlay_recommendations_enriched` | `total_odds` | NUMERIC | No cast needed |
| `mlb_parlay_recommendations_enriched` | `outcome` | VARCHAR | Values: `'won'/'lost'/'void'/'pending'` |
| `mlb_parlay_legs_enriched` | `line` | NUMERIC | No cast needed |
| `mlb_parlay_legs_enriched` | `odds` | VARCHAR | Yes — `odds::numeric` for math |
| `mlb_parlay_legs_enriched` | `outcome` | VARCHAR | Values: `'won'/'lost'/'void'/'pending'` |
| `mlb_training_data` | `result` | TEXT | Values: `'hit'/'miss'/'void'/NULL` ← different from parlay tables! |

**JOIN gotcha:** When joining `mlb_parlay_recommendations_v2` (DATE) to `mlb_scored_legs` (TEXT run_date):
```sql
ON p.run_date::text = s.run_date
```

**NEVER use `ROUND()`** on AVG or calculations — use `::numeric(5,1)` instead.

**`mlb_scored_legs_enriched.id`** is NULL for all rows — always use the natural key `(run_date, odd_id)` for writes.

---

## ⚠️ Row-Count Inflation on `mlb_parlay_legs_v2` / `mlb_parlay_legs_enriched` (found Session 18)

**The problem:** a single real-world leg (one player, one prop, one game, one day) gets a **new row** in `mlb_parlay_legs_v2` (or `_enriched`) every time it gets selected into a parlay across separate pipeline batches — the 9am/12pm/5:30pm scheduled runs, plus any CLR (Confirmed Lineup Resolution) rebuild batches that happen later the same day. These are not duplicate/erroneous rows in the data-integrity sense — each one is a legitimately different `parlay_id` — but they all describe the same underlying at-bat, and treating each row as an independent observation will overstate your sample size and understate your uncertainty.

**Measured inflation ratio (Session 18, 14-day sample):** ~2.4x across every major prop —
```
hits/over:       568 raw rows / 231 distinct (day, player) pairs
strikeouts/over: 315 raw rows / 132 distinct (day, player) pairs
hits/under:       65 raw rows /  26 distinct (day, player) pairs
```

**Does it bias the win rate itself?** Empirically, only slightly — because duplicate rows for the same real leg almost always share the same real outcome (a `void` row from an earlier batch that hadn't resolved yet, alongside a `won`/`lost` row from a later batch that had, is common; a `won` row contradicting a `lost` row for the same real leg is not — checked directly, never observed). Deduplicated vs. raw comparison:
```
hits/over:       62.8% raw (n=282) → 60.0% deduped (n=145)
strikeouts/over: 64.8% raw (n=179) → 62.6% deduped (n=91)
hits/under:      35.7% raw (n=28)  → 36.4% deduped (n=11)
```
Rates barely move. Sample sizes drop by more than half. **The real risk is false confidence from an inflated N, not a biased rate** — a thin, noisy prop (like hits/under, where the true independent sample was 11, not 28) can look far more statistically solid than it actually is if you don't dedupe first.

**Fix — always dedupe before computing a win rate from these two tables:**
```sql
WITH dedup AS (
  SELECT p.run_date, l.player_name, l.stat, l.direction,
    BOOL_OR(l.outcome = 'won')  AS any_won,
    BOOL_OR(l.outcome = 'lost') AS any_lost
  FROM mlb_parlay_legs_v2 l
  JOIN mlb_parlay_recommendations_v2 p ON p.id = l.parlay_id
  WHERE p.run_date >= '2026-06-24' AND p.run_date < CURRENT_DATE
  GROUP BY p.run_date, l.player_name, l.stat, l.direction
)
SELECT
  COUNT(*) FILTER (WHERE any_won OR any_lost)                              AS true_resolved,
  COUNT(*) FILTER (WHERE any_won)                                          AS true_won,
  (COUNT(*) FILTER (WHERE any_won) * 100.0 /
   NULLIF(COUNT(*) FILTER (WHERE any_won OR any_lost), 0))::numeric(5,1)   AS true_win_rate
FROM dedup;
```
Same pattern applies to `mlb_parlay_legs_enriched` joined to `mlb_parlay_recommendations_enriched`.

**This does not affect `mlb_scored_legs` / `mlb_scored_legs_enriched` directly** — those tables can also have multiple rows per (day, player, stat, direction) from repeated pipeline runs, but `get_scored_legs()`/`get_manual_legs()` already dedupe via `ROW_NUMBER() ... PARTITION BY player_name, stat, direction` before returning data. The inflation issue described here is specific to the *parlay leg* tables, where every batch that includes a given leg creates a new row with no equivalent dedup step downstream.

---

## Table: `mlb_scored_legs`

Production daily legs scored by the pipeline.

| column_name | data_type | notes |
|-------------|-----------|-------|
| id | integer | PK, auto-increment |
| run_date | text | ⚠️ TEXT not DATE — use string comparisons |
| player_name | text | |
| team | text | |
| opponent | text | |
| stat | text | e.g. 'hits', 'strikeouts', 'totalBases', 'rbi', 'walks' |
| line | real | numeric — no cast needed for comparisons |
| direction | text | 'over' or 'under' |
| odds | text | ⚠️ TEXT — cast to numeric for math: `odds::numeric` |
| coverage_pct | real | fallback coverage signal |
| coverage_overall | real | season-long direction-aware coverage (primary gate signal) |
| coverage_vs_hand | real | coverage vs pitcher handedness (scoring signal) |
| coverage_recent_10 | real | rolling 10-game coverage |
| coverage_recent_5 | real | rolling 5-game coverage |
| p_over | real | |
| ev_per_unit | real | |
| trend_pass | boolean | |
| trend_score | real | |
| opponent_adjustment | real | |
| composite_score | real | final score used for parlay selection — this is the actual pool-eligibility gate field (`_filter_legs()` in `parlay_builder.py` filters on `composite_score >= 65`, not `coverage_overall`) |
| position | text | |
| in_parlay | boolean | default false |
| result | text | ⚠️ 'won'/'lost'/'void'/'pending' — NOT 'hit'/'miss' |
| actual_value | real | resolved stat value |
| prop_category | text | |
| pitcher_era_rank | integer | rank 1 = best (lowest ERA). Pool: ~192 qualified starters |
| batter_vs_hand_coverage | real | |
| logged_at | text | |
| game_pk | integer | MLB game ID |
| player_id | text | ⚠️ TEXT — cast `int()` at API boundary |
| opposing_pitcher_id | text | |
| lineup_confirmed | boolean | default false |
| last_updated | text | |
| odd_id | text | SGO odds identifier |
| game_start_time | timestamp without time zone | |
| pitcher_hand | text | |
| lineup_consistency | real | |
| void_reason | text | ⚠️ still not populating for the large majority of voided legs as of Session 18 — see Lessons Learned |
| lineup_status | text | default 'unknown' |
| pitcher_id | text | |
| pitcher_name | text | opposing starting pitcher's name — the manual dashboard originally looked for `opposing_pitcher_name` here (Session 18 bug, fixed) — the correct field on this table is `pitcher_name` |
| pitcher_team | text | |
| pitcher_era | numeric | raw ERA value |
| pitcher_k9 | numeric | raw K/9 value |
| pitcher_whip | numeric | raw WHIP value |
| batter_hand | text | |
| pitcher_vs_batter_hand_era | numeric | |
| batting_order | integer | 1-9 slot from confirmed lineup (Session 10) |
| lineup_check_status | text | 'LINEUP_CONFIRMED' / 'SCRATCHED' / 'BATTING_ORDER_OUT_OF_RANGE' / 'MISSING_LINEUP_CONFIRMATION' (Session 10) |
| lineup_checked_at | timestamp without time zone | when lineup check fired (Session 10) |
| closing_odds | text | ⚠️ TEXT — CLV layer removed Session 17, column preserved for historical analysis only, no longer written to |
| closing_odds_captured_at | timestamp without time zone | CLV layer removed Session 17, historical only |

---

## Table: `mlb_scored_legs_enriched`

Shadow pipeline scored legs — mirrors `mlb_scored_legs` base columns plus enrichment signals. Written by `_log_enriched_legs()` in `run_enriched_pipeline.py`.

**⚠️ `id` is NULL for all rows** — use natural key `(run_date, odd_id)` for all writes. `ON CONFLICT (run_date, odd_id) DO UPDATE` is the write pattern.

**⚠️ NUMERIC columns return as Python `Decimal` via psycopg2** — see Critical Type Rules above. Bit the manual parlay dashboard in Session 18.

| column_name | data_type | notes |
|-------------|-----------|-------|
| id | integer | ⚠️ NULL for all rows — do not use as key |
| run_date | text | ⚠️ TEXT — same rules as `mlb_scored_legs` |
| player_name | text | |
| team | text | |
| opponent | text | |
| stat | text | |
| line | real | |
| direction | text | |
| odds | text | ⚠️ TEXT — cast `::numeric` for math |
| coverage_pct | real | |
| coverage_overall | real | |
| coverage_vs_hand | real | |
| coverage_recent_10 | real | |
| coverage_recent_5 | real | |
| p_over | real | |
| ev_per_unit | real | |
| trend_pass | boolean | |
| trend_score | real | |
| opponent_adjustment | real | |
| composite_score | real | enriched score (may include stack bonus) |
| position | text | |
| in_parlay | boolean | |
| result | text | 'won'/'lost'/'void'/'pending' |
| actual_value | real | |
| prop_category | text | |
| pitcher_era_rank | integer | rank 1 = best. Pool: ~192 qualified starters |
| pitcher_k9_rank | integer | rank 1 = best (highest K/9) |
| pitcher_whip_rank | integer | rank 1 = best (lowest WHIP) |
| batter_vs_hand_coverage | real | |
| logged_at | text | |
| game_pk | integer | |
| player_id | text | |
| opposing_pitcher_id | text | |
| lineup_confirmed | boolean | |
| last_updated | text | |
| odd_id | text | part of natural key with run_date |
| game_start_time | timestamp without time zone | |
| pitcher_hand | text | |
| lineup_consistency | real | |
| void_reason | text | |
| lineup_status | text | |
| pitcher_id | text | |
| pitcher_name | text | |
| pitcher_team | text | |
| pitcher_era | numeric | ⚠️ Decimal via psycopg2 |
| pitcher_k9 | numeric | ⚠️ Decimal via psycopg2 |
| pitcher_whip | numeric | ⚠️ Decimal via psycopg2 |
| batter_hand | text | |
| pitcher_vs_batter_hand_era | numeric | |
| coverage_vs_opponent | numeric | Signal 2: batter hit rate vs tonight's specific opponent. ⚠️ PERCENTAGE (0-100), not decimal — use `::numeric(5,1)`, never `::numeric(5,3)` |
| games_vs_opponent | integer | sample size for coverage_vs_opponent |
| park_factor | integer | Signal 3: ballpark run factor (Coors=115, Petco=94) |
| park_adjustment | numeric | scoring adjustment derived from park_factor |
| blended_era_rank | numeric | ⚠️ Decimal via psycopg2. Signal 1: season ERA rank × 0.5 + last-3-start ERA rank × 0.5 |
| recent_form_rank | numeric | |
| stack_bonus_applied | boolean | default false. True if leg received offense stack bonus (Session 11). Confirmed live and firing Session 18: 64.4% WR when true (n=101) vs 58.8% when false (n=2,153) |
| pitcher_vulnerability | numeric | ⚠️ Decimal via psycopg2. 0.0–1.0 composite score. 1.0 = weakest pitcher. Rank convention: rank 1 = best across ERA/K9/WHIP (Session 11) |
| matchup_adj | numeric | Net matchup adjustment applied to `composite_score` (sum of applicable factor adjustments, after per-prop cap). NULL when no matchup formula applies to this prop type. Added Session 19 follow-up. |
| matchup_era_adj | numeric | ERA component of matchup adjustment. Non-NULL for hits/over, hits/under, totalBases/under only. Formula: `((pitcher_era − 4.00) / 1.50) × max_era_weight`, clamped. NULL for strikeouts/over and all other props. |
| matchup_whip_adj | numeric | WHIP component of matchup adjustment. Non-NULL for hits/over, hits/under, totalBases/under only. Formula: `((pitcher_whip − 1.25) / 0.25) × max_whip_weight`, clamped. NULL for strikeouts/over and all other props. |
| matchup_k9_adj | numeric | K/9 component of matchup adjustment. Non-NULL for strikeouts/over and totalBases/under only. Formula: `((pitcher_k9 − 8.25) / 2.75) × max_k9_weight`, clamped. NULL for hits/over, hits/under, and all other props. |
| matchup_batter_adj | numeric | Batter-stat component of matchup adjustment. Non-NULL for totalBases/under only (requires ≥ 50 PA via MLB-StatsAPI gameLog). NULL for all other props. |

**⚠️ NULL semantics for matchup columns:** NULL means "this factor does not apply to this prop type," not "computed as zero." A `matchup_era_adj` of NULL on a strikeouts/over row is correct. A value of 0.0 would mean the ERA was exactly at midpoint. These are different things — do not treat NULL as zero in analysis.

---

## Table: `mlb_parlay_recommendations_v2`

Production parlay recommendations (one row per parlay).

| column_name | data_type | notes |
|-------------|-----------|-------|
| id | bigint | PK, auto-increment |
| run_date | date | ✅ DATE type — no cast needed |
| rank | smallint | rank within batch |
| total_odds | numeric | combined parlay odds (e.g. 850). As of Session 18, no longer bounded above by design — the builder no longer targets a ceiling |
| avg_coverage | numeric | |
| avg_ev | numeric | |
| num_legs | smallint | default 2, historically always 4 through Session 17. **As of Session 18, ranges 4-6** — was already a plain integer column, no migration needed for the builder redesign |
| outcome | character varying | 'won'/'lost'/'void'/'pending' |
| source | character varying | ⚠️ Actual values (Session 23 correction): `'auto_9am'`/`'midday'`/`'evening'` (NOT `'auto_12pm'`/`'auto_530pm'` — see Critical Type Rules above), `'manual'` (Regenerate Now button), `'manual_pick'` (Session 18, from `/manual`), `'dashboard_pick'` (Session 22, from the Diamond Line dashboard) |
| batch_id | character varying | groups parlays from same pipeline run |
| edge_percent | numeric | |
| resolved_at | timestamp with time zone | |
| created_at | timestamp with time zone | default now() |
| superseded_by_batch_id | character varying | batch_id of replacement parlay after CLR void (Session 10) |
| superseded_reason | text | e.g. 'SCRATCHED', 'BATTING_ORDER_OUT_OF_RANGE' (Session 10) |

---

## Table: `mlb_parlay_legs_v2`

Individual legs for each production parlay.

**⚠️ Row-count inflation** — see the dedicated section above before computing any win rate from this table.

| column_name | data_type | notes |
|-------------|-----------|-------|
| id | bigint | PK, auto-increment |
| parlay_id | bigint | FK → mlb_parlay_recommendations_v2.id |
| player_id | integer | |
| player_name | character varying | |
| team | character varying | |
| stat | character varying | |
| line | numeric | ✅ NUMERIC — no cast needed |
| direction | character varying | default 'over' |
| odds | character varying | ⚠️ VARCHAR — cast for math: `odds::numeric` |
| composite_score | numeric | |
| opponent_adjustment | numeric | |
| coverage | numeric | |
| ev | numeric | |
| game_id | integer | populated from the leg's `game_pk` at insert time (`save_parlay_recommendations_v2()`) |
| opposing_pitcher_id | integer | |
| opposing_pitcher_name | character varying | ⚠️ Note this column name differs from `mlb_scored_legs.pitcher_name` — when inserting via `save_parlay_recommendations_v2()` from a raw `mlb_scored_legs` row, this field is not automatically populated (the raw row has `pitcher_name`, not `opposing_pitcher_name`) and will save as NULL. Cosmetic gap only — does not affect resolution, which only reads `player_id`/`player_name`/`stat`/`line`/`direction`/`game_id`. Known since Session 18, not yet fixed. |
| outcome | character varying | 'won'/'lost'/'void'/'pending' — default 'pending' |
| result_value | numeric | resolved stat value |
| created_at | timestamp with time zone | default now() |
| batting_order | integer | 1-9 slot from confirmed lineup (Session 10) |
| lineup_check_status | character varying | same states as mlb_scored_legs (Session 10) |
| lineup_checked_at | timestamp with time zone | when lineup check fired (Session 10) |

---

## Table: `mlb_parlay_recommendations_enriched`

Shadow pipeline parlay recommendations — same structure as v2 plus `production_batch_id`.

| column_name | data_type | notes |
|-------------|-----------|-------|
| id | bigint | PK |
| run_date | date | ✅ DATE type — no cast needed |
| rank | smallint | |
| total_odds | numeric | |
| avg_coverage | numeric | |
| avg_ev | numeric | |
| num_legs | smallint | Session 18: ranges 4-6, was fixed at 4 through Session 17 (shadow pipeline calls the same `build_parlays()` as production) |
| outcome | character varying | 'won'/'lost'/'void'/'pending' |
| source | character varying | |
| batch_id | character varying | |
| edge_percent | numeric | |
| resolved_at | timestamp with time zone | |
| created_at | timestamp with time zone | |
| production_batch_id | text | links to mlb_parlay_recommendations_v2.batch_id for A/B comparison |

---

## Table: `mlb_parlay_legs_enriched`

Individual legs for shadow parlays — same as v2 plus enriched signal columns.

**⚠️ Row-count inflation** — same gotcha as `mlb_parlay_legs_v2`, see the dedicated section above.

| column_name | data_type | notes |
|-------------|-----------|-------|
| id | bigint | PK |
| parlay_id | bigint | FK → mlb_parlay_recommendations_enriched.id |
| player_id | integer | |
| player_name | character varying | |
| team | character varying | |
| stat | character varying | |
| line | numeric | ✅ NUMERIC — no cast needed |
| direction | character varying | |
| odds | character varying | ⚠️ VARCHAR — cast for math: `odds::numeric` |
| composite_score | numeric | |
| opponent_adjustment | numeric | |
| coverage | numeric | |
| ev | numeric | |
| game_id | integer | |
| opposing_pitcher_id | integer | |
| opposing_pitcher_name | character varying | |
| outcome | character varying | 'won'/'lost'/'void'/'pending' — default 'pending' |
| result_value | numeric | |
| created_at | timestamp with time zone | |
| blended_era_rank | numeric | Signal 1: season ERA rank × 0.5 + last-3-start ERA rank × 0.5 |
| recent_form_rank | numeric | |
| coverage_vs_opponent | numeric | Signal 2: batter hit rate vs tonight's specific opponent |
| games_vs_opponent | integer | sample size for coverage_vs_opponent |
| park_factor | integer | Signal 3: ballpark run factor (Coors=115, Petco=94) |
| park_adjustment | numeric | scoring adjustment derived from park_factor |

---

## Table: `mlb_pending_lineup_checks`

Event-driven scheduler table for lineup confirmation (T-45) and CLV snapshot (T-1, layer removed Session 17) checks. Polled by 1-minute async drain loop in `server.py`. Restart-safe by design.

| column_name | data_type | notes |
|-------------|-----------|-------|
| id | bigint | PK, auto-increment |
| run_date | date | pipeline run date |
| start_time_group | timestamp without time zone | shared game start time for grouped checks |
| game_pks | text | comma-separated or JSON list of game_pk values in this group |
| trigger_at | timestamp without time zone | when the drain should fire this check |
| offset_minutes | integer | e.g. 45 for T-45 lineup, 1 for T-1 CLV (CLV no longer scheduled as of Session 17) |
| pass_number | integer | 1 for primary, 2 for second-pass if enabled |
| check_type | text | 'lineup' (default) or 'clv' (unused as of Session 17) — discriminator for dispatch |
| status | text | 'pending' / 'fired' / 'completed' / 'failed' |
| fired_at | timestamp without time zone | when drain picked up the check |
| completed_at | timestamp without time zone | when check finished |
| result_note | text | summary of what happened (e.g. "3 confirmed, 1 scratched") |
| created_at | timestamp with time zone | default now() |

**Index:** `idx_pending_checks_type` on `(check_type, status, trigger_at)` — used by drain polling query.

---

## Table: `ballpark_factors`

Static 30-row table of park run/HR factors. Loaded once, cached in memory by enriched scorer.

| column_name | data_type | notes |
|-------------|-----------|-------|
| team | text | 3-letter abbreviation (e.g. 'COL', 'SD') |
| park_name | text | e.g. 'Coors Field' |
| run_factor | integer | 100 = neutral. Coors=115, Petco=94 |
| hr_factor | integer | 100 = neutral |

---

## Table: `mlb_training_data`

Historical resolved legs used for ML model training.

| column_name | data_type | notes |
|-------------|-----------|-------|
| result | text | ⚠️ 'hit'/'miss'/'void'/NULL — DIFFERENT from parlay tables which use 'won'/'lost' |

---

## Table: `mlb_sgo_request_log`

Logs every SportsGameOdds API call made by the MLB agent. Used for API cost/quota auditing. CLV-related volume dropped to zero as of Session 17's removal of the CLV tracking layer.

| column_name | data_type | notes |
|-------------|-----------|-------|
| id | integer | PK, auto-increment |
| timestamp | text | ⚠️ TEXT but ISO-formatted — cast `::timestamptz` for date math |
| endpoint | text | Observed values: `/events` only (as of Jul 7, 2026) |
| http_status | integer | 200 = success. Only 1 non-200 in project history (401, missing key, May 15) |
| entities_consumed | integer | SGO's billing unit — 1 object per event returned, markets included free. Drives the monthly quota (2,500/mo free tier, ~100K/mo Pro tier as of Jul 2026) |
| notes | text | Usually empty string. Populated with error detail on non-200 responses |

---

## Table: `sgo_request_log`

Same structure as `mlb_sgo_request_log`, but for a separate NBA parlay agent sharing the same SportsGameOdds account/API key. Non-`mlb_`-prefixed. Confirmed inactive since April 2026 — historical data only.

| column_name | data_type | notes |
|-------------|-----------|-------|
| id | integer | PK, auto-increment |
| timestamp | text | Same format/cast rules as `mlb_sgo_request_log` |
| endpoint | text | |
| http_status | integer | |
| entities_consumed | integer | Shares the same account-level SGO quota as `mlb_sgo_request_log` — combine both tables if the NBA agent ever becomes active again |
| notes | text | |

---

# Reference Data Schema (Session 22, 2026-07-29)

Normalized reference tables — teams, players, games, box-score-derived game logs, season-stat/standings daily snapshots. Applied directly to the live database before Session 22 (no repo migration file, same out-of-band pattern used for earlier ad-hoc columns) — the tables below existed, empty, when Session 22 started. **Additive only** — nothing here touches, joins into a write, or changes the meaning of `mlb_scored_legs`, `mlb_parlay_recommendations_v2`/`_enriched`, or any other production table. Backfilled season-to-date (2026-03-25 season opener through 2026-07-29) and validated in Session 22 — see `SESSION_HANDOFF.md`'s Session 22 entry and `ARCHITECTURE_DECISIONS.md` §30 for the full validation and design-decision writeups.

**Design note — keyed on MLB's own IDs, not synthetic keys.** `team_id` = MLB Stats API `team.id`, `player_id` = `person.id`, `game_pk` = the same `gamePk` already used throughout `mlb_scored_legs`/`mlb_games` joins elsewhere in this codebase. No new ID space was introduced.

**Populated by:**
- `scripts/backfill_reference_data.py` — one-time/range backfill for `mlb_teams`, `mlb_players`, `mlb_games`, `mlb_player_batting_logs`, `mlb_player_pitching_logs`. Reuses `src/apis/mlb_stats.py`'s `get_schedule()`/`get_box_score()`.
- `scripts/backfill_reference_snapshots.py` — one-time/range backfill for `mlb_player_season_batting_stats`, `mlb_player_season_pitching_stats`, `mlb_team_standings`, `mlb_team_standings_splits`.
- `scripts/daily_reference_refresh.py` — daily version of both of the above (yesterday's games/logs + today's season-stats/standings snapshot). Wired into `src/web/server.py`'s scheduler (`_reference_data_scheduler()`, 3 AM ET) as of Session 22, **not yet deployed** as of this doc update — check `SESSION_HANDOFF.md`'s Pending Items before assuming these tables are actually current.

**⚠️ `plate_appearances`/`hit_by_pitch` are NULL on every row of `mlb_player_batting_logs`.** `statsapi.boxscore_data()` (the function `get_box_score()` wraps) has its own hardcoded API `fields` parameter that does not include either field — confirmed by direct live inspection, not assumed from the docstring. Getting them would require either a second, unbatched per-player API call or a custom raw request outside the tested `get_box_score()` helper — deliberately not done, out of scope for a box-score-driven backfill. `total_bases` is still correctly computed (from `hits`/`doubles`/`triples`/`home_runs`, all of which ARE present) and does not depend on either missing field.

**⚠️ `mlb_player_season_batting_stats`/`_pitching_stats` are QUALIFIED-PLAYERS-ONLY, always.** Not a bug, a design choice — these mirror MLB.com's "Qualified Players" leaderboards exactly (confirmed live: the API's own `playerPool=QUALIFIED` default matches the PA≥3.1×team-games / IP≥1.0×team-games formula). On a given day this is roughly 150 hitters and 60 pitchers out of the full ~1,300-player pool. Any code reading these tables for a player who might not be qualified (e.g. `dashboard_api/season_stats.py`) needs a fallback path — see that file for the pattern (DB-first, live-API fallback only on a miss).

**⚠️ `mlb_team_standings.wcgb` (and only `wcgb`, not `games_back`) uses a sign convention, not a plain magnitude.** MLB's raw API returns a literal `'+7.0'` string for a team that currently holds a wildcard spot (X games clear of the cutoff) vs. a plain `'7.0'` for a team chasing one (X games behind) — these are semantically opposite and MLB.com displays them differently (with/without the `+`). Stored here as a **negative** number for the "+"-holds-a-spot case (the column is otherwise never negative) so the two remain numerically distinguishable; `dashboard_api/standings.py`'s `_fmt_gb()` reconstructs the `+` display from the sign. `games_back` (division) never has this ambiguity — the division leader is always plainly `0.0`/"-", per MLB's own convention, so it's stored as a plain non-negative magnitude.

---

## Table: `mlb_teams`

All 30 MLB teams. Refreshed (idempotent upsert) on every backfill/daily-refresh run.

| column_name | data_type | notes |
|-------------|-----------|-------|
| team_id | integer | PK — MLB Stats API `team.id` |
| abbreviation | text | e.g. 'NYY', 'TB' |
| name | text | full team name, e.g. 'Tampa Bay Rays' |
| division | text | full name, e.g. 'American League East' — used by `dashboard_api/standings.py` to group + derive the EAST/CENTRAL/WEST split columns by string suffix match |
| league | text | 'American League' / 'National League' |
| venue_id | integer | |
| venue_name | text | |
| created_at | timestamptz | |
| updated_at | timestamptz | |

---

## Table: `mlb_players`

Player bio/roster info. Rows are upserted lazily — only for players actually encountered in a box score during the batting/pitching-logs backfill, not a separate full-roster pull.

| column_name | data_type | notes |
|-------------|-----------|-------|
| player_id | integer | PK — MLB Stats API `person.id` |
| full_name | text | |
| primary_position | text | abbreviation, e.g. 'SS', 'P' — taken from the box score's per-player `position.abbreviation` at time of insert, so it reflects whatever position they played in their most recently backfilled game, not necessarily their listed primary position |
| bats | text | ⚠️ NOT populated by the current backfill — box scores don't carry this field, would need a separate `/people/{id}` call per player. Always NULL as of Session 22. |
| throws | text | ⚠️ Same as `bats` — always NULL as of Session 22 |
| current_team_id | integer | FK → `mlb_teams.team_id`. Updated on every re-encounter, so reflects the team they were rostered to as of their most recent backfilled game. |
| birth_date | date | ⚠️ Not populated — always NULL as of Session 22 |
| mlb_debut | date | ⚠️ Not populated — always NULL as of Session 22 |
| active | boolean | default `true` — not actually set/unset by the backfill (no deactivation logic); a player who leaves the league mid-season stays `true` |
| created_at | timestamptz | |
| updated_at | timestamptz | |

---

## Table: `mlb_games`

One row per completed (status `Final`/`Game Over`/`Completed Early`) game. `game_pk` is the same ID space as `mlb_scored_legs.game_pk` — see the Data Health Check below for a cross-check query and a known, narrow exception.

| column_name | data_type | notes |
|-------------|-----------|-------|
| game_pk | integer | PK — MLB Stats API `gamePk` |
| game_date | date | |
| game_start_time | timestamptz | ✅ proper TIMESTAMPTZ, unlike `mlb_scored_legs.game_start_time` (naive timestamp, historically UTC/ET-contaminated — see the game_start_time Data Health Check below). Populated directly from `statsapi.schedule()`'s `gameDate` field, which is a real ISO8601 UTC string with a `Z` suffix — no timezone ambiguity possible here by construction. |
| home_team_id | integer | FK → `mlb_teams.team_id` |
| away_team_id | integer | FK → `mlb_teams.team_id` |
| venue_id | integer | |
| status | text | free text, e.g. 'Final' — only completed games are ever inserted, so this is 'Final'/'Game Over'/'Completed Early' in practice for backfilled rows |
| home_score | integer | |
| away_score | integer | |
| home_probable_pitcher_id | integer | FK → `mlb_players.player_id`. ⚠️ For historical/completed games (the season-to-date backfill), this is set to the game's ACTUAL starting pitcher, not a pre-game "probable" pitcher prediction — for a completed game these are almost always the same person, and the actual starter is what the backfill already has on hand (from the box score) without an extra call. `daily_reference_refresh.py` does not yet populate this differently for today's/future scheduled games — a real probable-pitcher-vs-actual-starter distinction would need a separate schedule/lineup call for not-yet-played games, not implemented as of Session 22. |
| away_probable_pitcher_id | integer | Same caveat as `home_probable_pitcher_id` |
| created_at | timestamptz | |
| updated_at | timestamptz | |

---

## Table: `mlb_player_batting_logs`

One row per player per completed game, for every batter who appeared (not qualified-players-only — see the reference-schema intro above). Unique on `(player_id, game_pk)`.

| column_name | data_type | notes |
|-------------|-----------|-------|
| id | integer | PK, auto-increment |
| player_id | integer | FK → `mlb_players.player_id` |
| game_pk | integer | FK → `mlb_games.game_pk` |
| team_id | integer | FK → `mlb_teams.team_id` |
| opponent_team_id | integer | FK → `mlb_teams.team_id` |
| opposing_pitcher_id | integer | FK → `mlb_players.player_id`. The OTHER side's starting pitcher for this game (first entry of that side's `pitchers` list in the box score, confirmed live to be the starter) — NOT the specific pitcher(s) this batter actually faced if a reliever came in. |
| batting_order | integer | 1-9 lineup slot, derived from the box score's per-player `battingOrder` string field (e.g. `"300"` → slot 3, integer-divided by 100). NULL for players who didn't appear in the starting lineup or as an in-game substitute batter. |
| plate_appearances | integer | ⚠️ Always NULL — see reference-schema intro above |
| at_bats | integer | |
| hits | integer | |
| doubles | integer | |
| triples | integer | |
| home_runs | integer | |
| rbi | integer | |
| walks | integer | |
| strikeouts | integer | |
| hit_by_pitch | integer | ⚠️ Always NULL — see reference-schema intro above |
| stolen_bases | integer | |
| total_bases | integer | computed at insert time as `hits + doubles + 2*triples + 3*home_runs` — does not depend on `plate_appearances`/`hit_by_pitch` |
| created_at | timestamptz | |

---

## Table: `mlb_player_pitching_logs`

One row per player per completed game, for every pitcher who recorded at least one out. Unique on `(player_id, game_pk)`.

| column_name | data_type | notes |
|-------------|-----------|-------|
| id | integer | PK, auto-increment |
| player_id | integer | FK → `mlb_players.player_id` |
| game_pk | integer | FK → `mlb_games.game_pk` |
| team_id | integer | FK → `mlb_teams.team_id` |
| opponent_team_id | integer | FK → `mlb_teams.team_id` |
| is_starter | boolean | `player_id == ` that side's starting pitcher (first entry of the box score's `pitchers` list) — NOT derived from a `gamesStarted` stat field, which is never present via this API path (see reference-schema intro) |
| innings_pitched | numeric | parsed from MLB's `"6.1"` = 6⅓-innings string format into a true decimal (6.333...) before storage — same convention as `src/engine/coverage.py`'s existing `_parse_ip()` |
| hits_allowed | integer | |
| earned_runs | integer | |
| walks_allowed | integer | |
| strikeouts | integer | |
| home_runs_allowed | integer | |
| pitches_thrown | integer | reads the box score's `pitchesThrown` field, falling back to `numberOfPitches` if absent — same fallback order `statsapi`'s own `boxscore_data()` uses internally; both keys were observed present with identical values on real data |
| created_at | timestamptz | |

---

## Table: `mlb_team_standings`

Daily standings snapshot, one row per team per `as_of_date`. Unique on `(team_id, as_of_date)` — never overwritten across days, append-only time series (unlike `mlb_teams`, which is a live-state upsert).

| column_name | data_type | notes |
|-------------|-----------|-------|
| id | integer | PK, auto-increment |
| team_id | integer | FK → `mlb_teams.team_id` |
| as_of_date | date | |
| wins | integer | |
| losses | integer | |
| win_pct | numeric | |
| division_rank | integer | |
| games_back | numeric | ✅ plain non-negative magnitude, "-"/leader → `0.0`. No sign ambiguity — see reference-schema intro |
| wcgb | numeric | ⚠️ SIGNED — see reference-schema intro above. Negative = holds a wildcard spot (displays as `+X.X`); positive = chasing one. Do not treat like `games_back`. |
| runs_scored | integer | |
| runs_allowed | integer | |
| run_diff | integer | |
| streak | text | raw `streakCode`, e.g. `'W2'`, `'L1'` |
| created_at | timestamptz | |

---

## Table: `mlb_team_standings_splits`

Split records (home/away, vs.-hand, day/night, etc.), one row per team per split type per `as_of_date`. Unique on `(team_id, as_of_date, split_type)`.

| column_name | data_type | notes |
|-------------|-----------|-------|
| id | integer | PK, auto-increment |
| team_id | integer | FK → `mlb_teams.team_id` |
| as_of_date | date | |
| split_type | text | free text, not an enum. Values populated by the current backfill: `home`, `away`, `vs_lhp`, `vs_rhp`, `last_ten`, `extra_innings`, `one_run`, `day`, `night`, `grass`, `turf`, `vs_east`, `vs_central`, `vs_west`, `vs_al`, `vs_nl` — 16 rows/team/day as of Session 22 (`30 teams × 16 = 480`, confirmed on every snapshot run). `vs_east`/`vs_central`/`vs_west` are derived by matching the raw API's `divisionRecords` division name against an `East`/`Central`/`West` string suffix — works regardless of whether the team itself is AL or NL. `vs_al`/`vs_nl` show the OTHER league's record relative to the team (an AL team's meaningful cross-league number is its NL record, and vice versa) — matches MLB.com's single "AL/NL" column convention. |
| wins | integer | |
| losses | integer | |
| pct | numeric | |
| created_at | timestamptz | |

---

## Table: `mlb_player_season_batting_stats`

Daily time series, one row per player per `season` per `as_of_date` — **never overwritten across days** (unlike the game-log tables' natural key, this is intentionally append-only so historical qualification-day snapshots are preserved). Unique on `(player_id, season, as_of_date)`. **Qualified Players only** — see reference-schema intro above.

| column_name | data_type | notes |
|-------------|-----------|-------|
| id | integer | PK, auto-increment |
| player_id | integer | FK → `mlb_players.player_id` |
| team_id | integer | FK → `mlb_teams.team_id`, nullable |
| season | integer | |
| as_of_date | date | |
| games | integer | |
| at_bats | integer | |
| plate_appearances | integer | Added Session 22 (was missing from the schema as originally applied) — see Schema Change Log below. Needed as the correct denominator for K%/BB% (NOT `at_bats`, which runs ~10-15% below PA and would inflate both). |
| runs | integer | |
| hits | integer | |
| doubles | integer | |
| triples | integer | |
| home_runs | integer | |
| rbi | integer | |
| walks | integer | |
| strikeouts | integer | |
| stolen_bases | integer | |
| caught_stealing | integer | |
| avg | numeric | |
| obp | numeric | |
| slg | numeric | |
| ops | numeric | |
| created_at | timestamptz | |

---

## Table: `mlb_player_season_pitching_stats`

Same daily-time-series pattern as `mlb_player_season_batting_stats`, for pitchers. Unique on `(player_id, season, as_of_date)`. **Qualified Players only.**

| column_name | data_type | notes |
|-------------|-----------|-------|
| id | integer | PK, auto-increment |
| player_id | integer | FK → `mlb_players.player_id` |
| team_id | integer | FK → `mlb_teams.team_id`, nullable |
| season | integer | |
| as_of_date | date | |
| wins | integer | |
| losses | integer | |
| era | numeric | |
| games | integer | reads the API's `gamesPitched`, falling back to `gamesPlayed` if absent |
| games_started | integer | |
| complete_games | integer | |
| shutouts | integer | |
| saves | integer | |
| save_opportunities | integer | |
| innings_pitched | numeric | stored as the API's own decimal representation (e.g. `120.0`, `133.1`) — ⚠️ NOTE this is the MLB "innings.outs" convention (`.1`/`.2` = ⅓/⅔ innings, NOT true decimal tenths), same convention as everywhere else in this codebase, unlike `mlb_player_pitching_logs.innings_pitched` which IS true-decimal-parsed. Don't average or sum this column directly without converting first. |
| hits_allowed | integer | maps from the API's `hits` field (pitching context) |
| runs_allowed | integer | maps from the API's `runs` field (pitching context) |
| earned_runs | integer | |
| home_runs_allowed | integer | maps from the API's `homeRuns` field (pitching context) |
| hit_batters | integer | maps from the API's `hitBatsmen` field |
| walks | integer | maps from the API's `baseOnBalls` field |
| strikeouts | integer | |
| whip | numeric | |
| avg_against | numeric | maps from the API's `avg` field (pitching context — opponents' batting average) |
| created_at | timestamptz | |

**k9 is NOT a stored column** — `dashboard_api/leaderboards.py`/`season_stats.py` compute it on read as `strikeouts / innings_pitched * 9` rather than storing a separate value that could drift out of sync with the other two.

---

## Table: `mlb_prop_legs_history`

Full, non-qualified-filtered prop-line + game-line capture — an isolated ground-up-rebuild calibration dataset, explicitly separate from `mlb_scored_legs` and NOT read by any production/shadow scoring or win-rate query. Append-once ledger, populated as of Session 23 (2026-07-29) by `src/pipelines/prop_legs_capture.py`, called from `main.py`'s 9 AM-only pipeline path. Resolved daily by `resolve_prop_legs_history()`, chained into `scripts/daily_reference_refresh.py`.

| column_name | data_type | notes |
|-------------|-----------|-------|
| id | integer | PK, auto-increment |
| player_id | integer | ⚠️ NULLABLE as of Session 23 (was NOT NULL). FK → `mlb_players.player_id`. NULL for `market_scope='game'` rows (moneyline/spread/total have no associated player) — enforced by a CHECK constraint requiring `player_id IS NOT NULL` iff `market_scope='player'`. |
| game_pk | integer | FK → `mlb_games.game_pk` |
| stat | text | Player-scope: `'hits'`/`'strikeouts'`/`'totalBases'`. Game-scope: `'moneyline'`/`'spread'`/`'total'`. |
| line | real | For `stat='moneyline'`, this is a placeholder `0.0` (moneyline has no numeric line) — not a real value, don't aggregate/average it. |
| direction | text | Player-scope: `'over'`/`'under'` (batter strikeouts captured Over-only, per design). Game-scope moneyline/spread: `'home'`/`'away'`. Game-scope total: `'over'`/`'under'`. |
| sportsbook | text | Always `'draftkings'` as of Session 23 — matches the rest of the codebase's DK-only convention. |
| market_scope | text | ⚠️ NEW Session 23. NOT NULL. `'player'` or `'game'`. CHECK-constrained to stay consistent with `player_id` (see above). |
| player_role | text | ⚠️ NEW Session 23. `'batter'`/`'pitcher'`/NULL (NULL for `market_scope='game'` rows). Disambiguates the SAME `stat='strikeouts'` value between a pitcher's own strikeout total and a batter's strikeouts-against line — these are NOT distinguishable from `stat`/`line` alone (pitcher lines run 4.5+, batter lines run 0.5, but nothing in this table's own columns encodes which is which without this column). Derived from the raw SGO `batting_`/`pitching_` statID prefix at capture time, independently of `get_player_props()`'s own normalization (which discards that prefix) — see `ARCHITECTURE_DECISIONS.md` §34. |
| first_seen_odds | integer | |
| first_seen_at | timestamptz | |
| last_recorded_odds | integer | |
| last_recorded_at | timestamptz | |
| odds_history | jsonb | default `'[]'`. Appended to (not overwritten) on each capture run that still sees the same leg — `mlb_prop_legs_history.odds_history \|\| EXCLUDED.odds_history` via jsonb array concatenation. Confirmed live: a leg captured across two runs had 2 entries with correct timestamps. |
| result | text | default `'pending'`. Set by `resolve_prop_legs_history()`: `'won'`/`'lost'`/`'void'` (void = push, or player didn't appear in the box score for that game). ⚠️ Same `'won'`/`'lost'`/`'void'`/`'pending'` convention as `mlb_scored_legs`, NOT the `'hit'`/`'miss'` convention `mlb_training_data` uses — don't confuse the two when writing a query that touches both. |
| actual_value | real | Player-scope: the actual stat value from `mlb_player_batting_logs`/`_pitching_logs`. Game-scope total: combined score. Game-scope moneyline: always NULL (win/lose is binary, no natural "value"). Game-scope spread: the actual margin (signed, from the leg's own side's perspective). |
| resolved_at | timestamptz | |
| created_at | timestamptz | |
| updated_at | timestamptz | |

**⚠️ Unique constraints — TWO, not one, as of Session 23:**
- `(player_id, game_pk, stat, line, direction, sportsbook)` — the original constraint, covers `market_scope='player'` rows (`player_id` present).
- `mlb_prop_legs_history_game_scope_key`: a **partial** unique index on `(game_pk, stat, line, direction, sportsbook) WHERE player_id IS NULL` — covers `market_scope='game'` rows. Required because Postgres treats every `NULL` as distinct for `UNIQUE` purposes; without this, game-scope rows would never dedupe across repeated capture runs, silently accumulating duplicates instead of upserting. **When writing an `INSERT ... ON CONFLICT` against this table, the conflict target for a game-scope row MUST restate `WHERE player_id IS NULL`** — Postgres only matches `ON CONFLICT` against a partial index if the predicate is repeated in the conflict clause itself, not inferred from the column list. Confirmed live: omitting it raises `there is no unique or exclusion constraint matching the ON CONFLICT specification` on every single game-scope upsert. See `src/pipelines/prop_legs_capture.py`'s `_upsert_leg()` for the working pattern.

---

## Common Query Patterns

```sql
-- Parlay win rate last 7 days (production) — parlay-level, no dedup needed
-- (one row per parlay, not per leg — this table doesn't have the row-inflation issue)
SELECT
    COUNT(*) FILTER (WHERE outcome = 'won') as won,
    COUNT(*) FILTER (WHERE outcome = 'lost') as lost,
    (COUNT(*) FILTER (WHERE outcome = 'won') * 100.0 /
     NULLIF(COUNT(*) FILTER (WHERE outcome IN ('won','lost')), 0))::numeric(5,1) as win_rate
FROM mlb_parlay_recommendations_v2
WHERE run_date >= CURRENT_DATE - 7;

-- In-parlay leg win rate by stat/direction — ⚠️ DEDUPED, see Row-Count Inflation section above
WITH dedup AS (
  SELECT p.run_date, l.player_name, l.stat, l.direction, l.line,
    BOOL_OR(l.outcome = 'won')  AS any_won,
    BOOL_OR(l.outcome = 'lost') AS any_lost
  FROM mlb_parlay_legs_v2 l
  JOIN mlb_parlay_recommendations_v2 p ON p.id = l.parlay_id
  WHERE p.run_date >= CURRENT_DATE - 7
  GROUP BY p.run_date, l.player_name, l.stat, l.direction, l.line
)
SELECT stat, direction, line::numeric(4,1) as line,
    COUNT(*) FILTER (WHERE any_won OR any_lost) as appearances,
    COUNT(*) FILTER (WHERE any_won) as won,
    (COUNT(*) FILTER (WHERE any_won) * 100.0 /
     NULLIF(COUNT(*) FILTER (WHERE any_won OR any_lost), 0))::numeric(5,1) as win_rate
FROM dedup
GROUP BY stat, direction, line::numeric(4,1)
ORDER BY appearances DESC;

-- Manual vs. automated parlay comparison (new query pattern, Session 18)
SELECT
    CASE WHEN source = 'manual_pick' THEN 'manual' ELSE 'automated' END as pick_type,
    COUNT(*) FILTER (WHERE outcome IN ('won','lost')) as resolved,
    COUNT(*) FILTER (WHERE outcome = 'won') as won,
    (COUNT(*) FILTER (WHERE outcome = 'won') * 100.0 /
     NULLIF(COUNT(*) FILTER (WHERE outcome IN ('won','lost')), 0))::numeric(5,1) as win_rate,
    AVG(num_legs)::numeric(3,1) as avg_legs,
    AVG(total_odds)::numeric(7,0) as avg_odds
FROM mlb_parlay_recommendations_v2
WHERE run_date >= CURRENT_DATE - 30
GROUP BY pick_type;

-- Production vs shadow A/B comparison
SELECT
    'production' as pipeline, p.rank, p.total_odds, p.outcome,
    l.player_name, l.stat, l.direction, l.outcome as leg_outcome
FROM mlb_parlay_recommendations_v2 p
JOIN mlb_parlay_legs_v2 l ON l.parlay_id = p.id
WHERE p.batch_id IN (
    SELECT DISTINCT production_batch_id FROM mlb_parlay_recommendations_enriched
    WHERE run_date >= CURRENT_DATE - 7
)
UNION ALL
SELECT
    'shadow' as pipeline, p.rank, p.total_odds, p.outcome,
    l.player_name, l.stat, l.direction, l.outcome as leg_outcome
FROM mlb_parlay_recommendations_enriched p
JOIN mlb_parlay_legs_enriched l ON l.parlay_id = p.id
WHERE p.run_date >= CURRENT_DATE - 7
ORDER BY pipeline DESC, rank, player_name;

-- Filter scored legs by date (TEXT run_date)
SELECT * FROM mlb_scored_legs
WHERE run_date = '2026-05-27'
  AND result IN ('won', 'lost')
  AND odds::numeric > -300;

-- Coverage analysis with proper rounding
SELECT
    stat, direction,
    AVG(coverage_overall)::numeric(5,1) as avg_cov,
    (COUNT(*) FILTER (WHERE result = 'won') * 100.0 /
     NULLIF(COUNT(*) FILTER (WHERE result IN ('won','lost')), 0))::numeric(5,1) as win_rate
FROM mlb_scored_legs
WHERE run_date >= (CURRENT_DATE - INTERVAL '7 days')::text
  AND coverage_overall IS NOT NULL
GROUP BY stat, direction;

-- Stack bonus analysis (enriched legs) — confirmed live and positive Session 18
SELECT
    stack_bonus_applied,
    COUNT(*) as legs,
    (COUNT(*) FILTER (WHERE result = 'won') * 100.0 /
     NULLIF(COUNT(*) FILTER (WHERE result IN ('won','lost')), 0))::numeric(5,1) as win_rate,
    AVG(pitcher_vulnerability)::numeric(5,3) as avg_vulnerability
FROM mlb_scored_legs_enriched
WHERE run_date >= (CURRENT_DATE - INTERVAL '7 days')::text
  AND result IN ('won', 'lost')
GROUP BY stack_bonus_applied;

-- Lineup check status distribution
SELECT
    lineup_check_status,
    COUNT(*) as legs
FROM mlb_scored_legs
WHERE run_date >= (CURRENT_DATE - INTERVAL '3 days')::text
GROUP BY lineup_check_status
ORDER BY legs DESC;
```

---

## Schema Change Log

| Date | Table | Change |
|------|-------|--------|
| 2026-06-12 | `mlb_scored_legs` | Added: `batting_order`, `lineup_check_status`, `lineup_checked_at`, `closing_odds`, `closing_odds_captured_at` |
| 2026-06-12 | `mlb_parlay_legs_v2` | Added: `batting_order`, `lineup_check_status`, `lineup_checked_at` |
| 2026-06-12 | `mlb_parlay_recommendations_v2` | Added: `superseded_by_batch_id`, `superseded_reason` |
| 2026-06-12 | `mlb_pending_lineup_checks` | New table created. `check_type` column + index added for CLV dispatch. |
| 2026-06-12 | `mlb_scored_legs_enriched` | Added: `stack_bonus_applied`, `pitcher_vulnerability` |
| 2026-07-08 | *(none — no migrations this session)* | Session 18 added a new **value** (`'manual_pick'`) to the existing `mlb_parlay_recommendations_v2.source` free-text column — not a schema change, no migration needed. `num_legs` on both `_v2` and `_enriched` recommendation tables now legitimately ranges 4-6 (was always 4) — also not a schema change, that column was always a plain integer. |
| 2026-07-10 | *(none — no migrations this session)* | Session 19 changes are application-layer only: scratch handler rewrite (logic changes in `lineup_confirmation.py` only, no new DB columns), shadow scorer rebuild (enriched scorer reads existing `pitcher_era`/`pitcher_whip`/`pitcher_k9` raw values from `mlb_scored_legs` — confirmed present since May 12 with 11k+ rows — and adds in-memory batter stats from the MLB-StatsAPI gameLog; no new DB columns). |
| 2026-07-10 | `mlb_scored_legs_enriched` | Added 5 matchup debug columns: `matchup_adj`, `matchup_era_adj`, `matchup_whip_adj`, `matchup_k9_adj`, `matchup_batter_adj` (all NUMERIC). Migration: `sql/matchup_debug_columns_migration.sql`. Session 19 follow-up — these were computed in-memory since Session 19 but silently dropped before the INSERT (column list never updated). Now persisted to enable per-factor attribution analysis. |
| *(before Session 22, exact date unrecorded)* | `mlb_teams`, `mlb_players`, `mlb_games`, `mlb_player_batting_logs`, `mlb_player_pitching_logs`, `mlb_team_standings`, `mlb_team_standings_splits`, `mlb_player_season_batting_stats`, `mlb_player_season_pitching_stats`, `mlb_prop_legs_history` | New reference-data schema created, applied directly to the live database — no repo migration file, tables existed empty when Session 22 started. Full documentation added this session, see the new "Reference Data Schema" section above. |
| 2026-07-29 | `mlb_player_season_batting_stats` | Session 22 — added `plate_appearances` (INTEGER, nullable). Missing from the schema as originally applied; needed as the correct K%/BB% denominator for `dashboard_api/season_stats.py`'s reworked version (using `at_bats` instead would have inflated both). Additive, backfilled for the existing 2026-07-29 snapshot row via a re-run of `scripts/backfill_reference_snapshots.py` after the migration. |
| 2026-07-29 | `mlb_prop_legs_history` | Session 23 — `player_id` made nullable; added `market_scope` (TEXT NOT NULL, `'player'`/`'game'`) and `player_role` (TEXT, `'batter'`/`'pitcher'`/NULL) with CHECK constraints enforcing they stay consistent with `player_id`/each other. Also added a **partial unique index** `mlb_prop_legs_history_game_scope_key` on `(game_pk, stat, line, direction, sportsbook) WHERE player_id IS NULL` — the original single UNIQUE constraint never would have deduped game-scope rows across runs (Postgres treats every NULL as distinct). Both applied live, no repo migration file, same pattern as the reference schema's own application. |

---

## Data Health Checks

Run these periodically to catch silent data quality regressions.

### game_start_time consistency
Confirms no `game_pk` has two conflicting `game_start_time` values (symptom of the UTC/ET backfill contamination bug, fixed 2026-07-10):

```sql
-- Run against mlb_scored_legs
SELECT game_pk, COUNT(DISTINCT game_start_time) AS distinct_times
FROM mlb_scored_legs
WHERE game_pk IS NOT NULL
GROUP BY game_pk
HAVING COUNT(DISTINCT game_start_time) > 1
ORDER BY game_pk;

-- Run against mlb_scored_legs_enriched
SELECT game_pk, COUNT(DISTINCT game_start_time) AS distinct_times
FROM mlb_scored_legs_enriched
WHERE game_pk IS NOT NULL
GROUP BY game_pk
HAVING COUNT(DISTINCT game_start_time) > 1
ORDER BY game_pk;
```

Zero rows is the expected healthy result. If any rows appear, run `scripts/fix_game_start_time_contamination.py` to investigate and remediate.

### mlb_scored_legs.game_pk vs. mlb_games.game_pk (new, Session 22)
Found 8 mismatches (out of 1,320 checked, ~0.6%) on the very first run of this check — `game_pk` values in `mlb_scored_legs` that actually belong to a different, future/unplayed game than the one that was happening on that leg's `run_date`. Confirmed directly against the live API for each one (officialDate in Aug/Sep 2026, status `Scheduled`). Root cause not investigated — flagged, not fixed, out of scope for the read-only backfill work that found it. Worth periodically re-running to see if this is growing, static, or an isolated historical batch:

```sql
SELECT sl.game_pk, sl.run_date, COUNT(*) AS legs
FROM mlb_scored_legs sl
LEFT JOIN mlb_games g ON g.game_pk = sl.game_pk
WHERE sl.game_pk IS NOT NULL
  AND sl.run_date < CURRENT_DATE::text  -- exclude today's not-yet-Final games, which are expected to be absent from mlb_games
  AND g.game_pk IS NULL
GROUP BY sl.game_pk, sl.run_date
ORDER BY sl.run_date;
```

Any row returned by this query is worth spot-checking directly against `https://statsapi.mlb.com/api/v1.1/game/{game_pk}/feed/live` (look at `gameData.datetime.officialDate` and `gameData.status.detailedState`) before assuming it's the same bug — confirm it's actually a future/wrong game, not just a legitimate gap in the reference-schema backfill's own coverage.

---

## Schema Last Verified
- `mlb_scored_legs`: 2026-07-10 (Session 19 — no changes; confirmed `pitcher_era`/`pitcher_whip`/`pitcher_k9` raw NUMERIC columns populated since May 12; MLB-StatsAPI gameLog batter field names confirmed: `atBats`, `hits`, `baseOnBalls`, `strikeOuts`, `plateAppearances`, `hitByPitch` — these are transient/in-memory, not stored in DB)
- `mlb_scored_legs_enriched`: 2026-07-10 (Session 19 follow-up — 5 matchup debug columns added and confirmed present: `matchup_adj`, `matchup_era_adj`, `matchup_whip_adj`, `matchup_k9_adj`, `matchup_batter_adj` — all NUMERIC, written by `_log_enriched_legs()`, NULL when not applicable to the prop type. Decimal coercion note: `float(value)` applied inside `_linear_adj()` to handle psycopg2 returning NUMERIC columns as Python `Decimal`.)
- `mlb_parlay_recommendations_v2`: 2026-07-29 (Session 23 — `source` documented values CORRECTED: actual production values are `'auto_9am'`/`'midday'`/`'evening'`, not `'auto_9am'`/`'auto_12pm'`/`'auto_530pm'` as previously documented since Session 18; also added `'dashboard_pick'`, missing since Session 22)
- `mlb_parlay_legs_v2`: 2026-07-10 (Session 19 — `outcome='void'` now applied to individual scratched legs when the reduce-path is taken; they remain as rows, not deleted, so `num_legs`/`total_odds` can be recalculated off survivors)
- `mlb_parlay_recommendations_enriched`: 2026-07-08 (Session 18 — `num_legs` behavior note added)
- `mlb_parlay_legs_enriched`: 2026-07-08 (Session 18 — row-count inflation gotcha cross-referenced)
- `mlb_pending_lineup_checks`: 2026-07-10 (Session 19 — `result_note` field: now only counts parlays actually rebuilt or reduced-and-kept, not voided-with-nothing; `superseded_by_batch_id` stays NULL on no-rebuild paths, `superseded_reason` set to `'SCRATCHED_NO_REBUILD'` or `'THIN_POOL_NO_REBUILD'`)
- `ballpark_factors`: 2026-06-13
- `mlb_sgo_request_log` / `sgo_request_log`: 2026-07-07
- `mlb_teams` / `mlb_players` / `mlb_games` / `mlb_player_batting_logs` / `mlb_player_pitching_logs`: 2026-07-29 (Session 22 — full documentation added; backfilled season-to-date 2026-03-25–2026-07-29, validated via 3 live spot-checks; `plate_appearances`/`hit_by_pitch` confirmed always-NULL on the batting-logs table via live API inspection, not assumed)
- `mlb_team_standings` / `mlb_team_standings_splits`: 2026-07-29 (Session 22 — full documentation added; `wcgb` sign convention found and fixed this session, documented above; 480 splits rows/day = 30 teams × 16 split types, confirmed on every snapshot run)
- `mlb_player_season_batting_stats` / `mlb_player_season_pitching_stats`: 2026-07-29 (Session 22 — full documentation added; `plate_appearances` column added to the batting table this session, see Schema Change Log; confirmed QUALIFIED-only via live `playerPool=QUALIFIED` inspection)
- `mlb_prop_legs_history`: 2026-07-29 (Session 23 — now populated: `market_scope`/`player_role` columns added and documented, partial unique index for game-scope dedup added and documented, `ON CONFLICT` gotcha documented after being confirmed live. No longer empty as of this session — first live capture run wrote 158 rows across game lines and player props.)
