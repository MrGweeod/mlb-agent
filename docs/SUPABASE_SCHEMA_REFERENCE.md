# Supabase Schema Reference — MLB Parlay Agent
**Last Updated:** 2026-07-10 (Session 19 follow-up — added 5 matchup debug columns to `mlb_scored_legs_enriched`: `matchup_adj`, `matchup_era_adj`, `matchup_whip_adj`, `matchup_k9_adj`, `matchup_batter_adj`)
**Source:** Exported from Supabase information_schema + verified against migration logs

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
| `mlb_parlay_recommendations_v2` | `source` | VARCHAR | Free text, not an enum. Known values as of Session 18: `'auto_9am'`, `'auto_12pm'`, `'auto_530pm'`, `'manual'` (the "Regenerate Now" button — still runs the algorithm, on demand), and `'manual_pick'` (new, Session 18 — a genuinely hand-picked leg set from `/manual`). Don't conflate `'manual'` and `'manual_pick'` — they mean different things. |
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
| source | character varying | 'auto_9am'/'auto_12pm'/'auto_530pm'/'manual' (Regenerate Now button)/**'manual_pick'** (new Session 18 — genuinely hand-picked from `/manual`) |
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

---

## Schema Last Verified
- `mlb_scored_legs`: 2026-07-10 (Session 19 — no changes; confirmed `pitcher_era`/`pitcher_whip`/`pitcher_k9` raw NUMERIC columns populated since May 12; MLB-StatsAPI gameLog batter field names confirmed: `atBats`, `hits`, `baseOnBalls`, `strikeOuts`, `plateAppearances`, `hitByPitch` — these are transient/in-memory, not stored in DB)
- `mlb_scored_legs_enriched`: 2026-07-10 (Session 19 follow-up — 5 matchup debug columns added and confirmed present: `matchup_adj`, `matchup_era_adj`, `matchup_whip_adj`, `matchup_k9_adj`, `matchup_batter_adj` — all NUMERIC, written by `_log_enriched_legs()`, NULL when not applicable to the prop type. Decimal coercion note: `float(value)` applied inside `_linear_adj()` to handle psycopg2 returning NUMERIC columns as Python `Decimal`.)
- `mlb_parlay_recommendations_v2`: 2026-07-08 (Session 18 — `source` values documented including `'manual_pick'`; `num_legs`/`total_odds` behavior note added)
- `mlb_parlay_legs_v2`: 2026-07-10 (Session 19 — `outcome='void'` now applied to individual scratched legs when the reduce-path is taken; they remain as rows, not deleted, so `num_legs`/`total_odds` can be recalculated off survivors)
- `mlb_parlay_recommendations_enriched`: 2026-07-08 (Session 18 — `num_legs` behavior note added)
- `mlb_parlay_legs_enriched`: 2026-07-08 (Session 18 — row-count inflation gotcha cross-referenced)
- `mlb_pending_lineup_checks`: 2026-07-10 (Session 19 — `result_note` field: now only counts parlays actually rebuilt or reduced-and-kept, not voided-with-nothing; `superseded_by_batch_id` stays NULL on no-rebuild paths, `superseded_reason` set to `'SCRATCHED_NO_REBUILD'` or `'THIN_POOL_NO_REBUILD'`)
- `ballpark_factors`: 2026-06-13
- `mlb_sgo_request_log` / `sgo_request_log`: 2026-07-07
