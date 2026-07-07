# Supabase Schema Reference — MLB Parlay Agent
**Last Updated:** 2026-07-07 (Session 17 — added mlb_sgo_request_log and sgo_request_log, discovered mid-session, previously undocumented)
**Source:** Exported from Supabase information_schema + verified against migration logs

This file is the authoritative schema reference. Always read this before writing SQL queries.

---

## Critical Type Rules (Read First)

| Table | Column | Type | Cast Required? |
|-------|--------|------|----------------|
| `mlb_scored_legs` | `run_date` | TEXT | Yes — `run_date = '2026-05-15'` or `(CURRENT_DATE)::text` |
| `mlb_scored_legs` | `odds` | TEXT | Yes — `odds::numeric` for math |
| `mlb_scored_legs` | `closing_odds` | TEXT | Yes — `closing_odds::numeric` for CLV math |
| `mlb_scored_legs` | `line` | REAL | No cast for comparisons |
| `mlb_scored_legs` | `result` | TEXT | Values: `'won'/'lost'/'void'/'pending'` |
| `mlb_scored_legs_enriched` | `run_date` | TEXT | Same rules as `mlb_scored_legs` |
| `mlb_scored_legs_enriched` | `odds` | TEXT | Yes — `odds::numeric` for math |
| `mlb_scored_legs_enriched` | `result` | TEXT | Values: `'won'/'lost'/'void'/'pending'` |
| `mlb_parlay_recommendations_v2` | `run_date` | DATE | No cast needed |
| `mlb_parlay_recommendations_v2` | `total_odds` | NUMERIC | No cast needed |
| `mlb_parlay_recommendations_v2` | `outcome` | VARCHAR | Values: `'won'/'lost'/'void'/'pending'` |
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
| composite_score | real | final score used for parlay selection |
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
| void_reason | text | |
| lineup_status | text | default 'unknown' |
| pitcher_id | text | |
| pitcher_name | text | |
| pitcher_team | text | |
| pitcher_era | numeric | raw ERA value |
| pitcher_k9 | numeric | raw K/9 value |
| pitcher_whip | numeric | raw WHIP value |
| batter_hand | text | |
| pitcher_vs_batter_hand_era | numeric | |
| batting_order | integer | 1-9 slot from confirmed lineup (Session 10) |
| lineup_check_status | text | 'LINEUP_CONFIRMED' / 'SCRATCHED' / 'BATTING_ORDER_OUT_OF_RANGE' / 'MISSING_LINEUP_CONFIRMATION' (Session 10) |
| lineup_checked_at | timestamp without time zone | when lineup check fired (Session 10) |
| closing_odds | text | ⚠️ TEXT — cast `::numeric` for CLV math (Session 10) |
| closing_odds_captured_at | timestamp without time zone | when CLV snapshot was taken (Session 10) |

---

## Table: `mlb_scored_legs_enriched`

Shadow pipeline scored legs — mirrors `mlb_scored_legs` base columns plus enrichment signals. Written by `_log_enriched_legs()` in `run_enriched_pipeline.py`.

**⚠️ `id` is NULL for all rows** — use natural key `(run_date, odd_id)` for all writes. `ON CONFLICT (run_date, odd_id) DO UPDATE` is the write pattern.

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
| pitcher_era | numeric | |
| pitcher_k9 | numeric | |
| pitcher_whip | numeric | |
| batter_hand | text | |
| pitcher_vs_batter_hand_era | numeric | |
| coverage_vs_opponent | numeric | Signal 2: batter hit rate vs tonight's specific opponent. ⚠️ PERCENTAGE (0-100), not decimal — use `::numeric(5,1)`, never `::numeric(5,3)` |
| games_vs_opponent | integer | sample size for coverage_vs_opponent |
| park_factor | integer | Signal 3: ballpark run factor (Coors=115, Petco=94) |
| park_adjustment | numeric | scoring adjustment derived from park_factor |
| blended_era_rank | numeric | Signal 1: season ERA rank × 0.5 + last-3-start ERA rank × 0.5 |
| recent_form_rank | numeric | |
| stack_bonus_applied | boolean | default false. True if leg received offense stack bonus (Session 11) |
| pitcher_vulnerability | numeric | 0.0–1.0 composite score. 1.0 = weakest pitcher. Rank convention: rank 1 = best across ERA/K9/WHIP (Session 11) |

---

## Table: `mlb_parlay_recommendations_v2`

Production parlay recommendations (one row per parlay).

| column_name | data_type | notes |
|-------------|-----------|-------|
| id | bigint | PK, auto-increment |
| run_date | date | ✅ DATE type — no cast needed |
| rank | smallint | rank within batch |
| total_odds | numeric | combined parlay odds (e.g. 850) |
| avg_coverage | numeric | |
| avg_ev | numeric | |
| num_legs | smallint | default 2 |
| outcome | character varying | 'won'/'lost'/'void'/'pending' |
| source | character varying | 'auto_9am'/'auto_12pm'/'auto_530pm'/'manual' |
| batch_id | character varying | groups parlays from same pipeline run |
| edge_percent | numeric | |
| resolved_at | timestamp with time zone | |
| created_at | timestamp with time zone | default now() |
| superseded_by_batch_id | character varying | batch_id of replacement parlay after CLR void (Session 10) |
| superseded_reason | text | e.g. 'SCRATCHED', 'BATTING_ORDER_OUT_OF_RANGE' (Session 10) |

---

## Table: `mlb_parlay_legs_v2`

Individual legs for each production parlay.

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
| game_id | integer | |
| opposing_pitcher_id | integer | |
| opposing_pitcher_name | character varying | |
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
| num_legs | smallint | |
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

Event-driven scheduler table for lineup confirmation (T-45) and CLV snapshot (T-1) checks. Polled by 1-minute async drain loop in `server.py`. Restart-safe by design.

| column_name | data_type | notes |
|-------------|-----------|-------|
| id | bigint | PK, auto-increment |
| run_date | date | pipeline run date |
| start_time_group | timestamp without time zone | shared game start time for grouped checks |
| game_pks | text | comma-separated or JSON list of game_pk values in this group |
| trigger_at | timestamp without time zone | when the drain should fire this check |
| offset_minutes | integer | e.g. 45 for T-45 lineup, 1 for T-1 CLV |
| pass_number | integer | 1 for primary, 2 for second-pass if enabled |
| check_type | text | 'lineup' (default) or 'clv' — discriminator for dispatch |
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

Logs every SportsGameOdds API call made by the MLB agent. Not tied to any migration
— discovered by direct table listing in Session 17 (Jul 7, 2026), not previously
documented here. Used for API cost/quota auditing.

| column_name | data_type | notes |
|-------------|-----------|-------|
| id | integer | PK, auto-increment |
| timestamp | text | ⚠️ TEXT but ISO-formatted — cast `::timestamptz` for date math |
| endpoint | text | Observed values: `/events` only (as of Jul 7, 2026) |
| http_status | integer | 200 = success. Only 1 non-200 in project history (401, missing key, May 15) |
| entities_consumed | integer | SGO's billing unit — 1 object per event returned, markets included free. Drives the monthly quota (2,500/mo free tier, ~100K/mo Pro tier as of Jul 2026) |
| notes | text | Usually empty string. Populated with error detail on non-200 responses |

**As of Session 17:** correlate against `mlb_pending_lineup_checks.check_type` (join
on approximate timestamp) to distinguish scheduled-pipeline-run calls from CLV-check
calls — there's no direct foreign key, so this requires a time-window join, not an
exact match. CLV scheduling was removed in Session 17 (commit `d3a642c`); expect no
more CLV-attributable rows in this table from July 7, 2026 onward.

---

## Table: `sgo_request_log`

Same structure as `mlb_sgo_request_log`, but for a separate NBA parlay agent sharing
the same SportsGameOdds account/API key. Non-`mlb_`-prefixed. **Confirmed inactive
since April 2026** (zero rows after April as of Session 17) — historical data only,
not part of current combined usage projections.

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
-- Parlay win rate last 7 days (production)
SELECT
    COUNT(*) FILTER (WHERE outcome = 'won') as won,
    COUNT(*) FILTER (WHERE outcome = 'lost') as lost,
    (COUNT(*) FILTER (WHERE outcome = 'won') * 100.0 /
     NULLIF(COUNT(*) FILTER (WHERE outcome IN ('won','lost')), 0))::numeric(5,1) as win_rate
FROM mlb_parlay_recommendations_v2
WHERE run_date >= CURRENT_DATE - 7;

-- In-parlay leg win rate by stat/direction
SELECT
    l.stat, l.direction, l.line::numeric(4,1) as line,
    COUNT(*) FILTER (WHERE l.outcome IN ('won','lost')) as appearances,
    COUNT(*) FILTER (WHERE l.outcome = 'won') as won,
    (COUNT(*) FILTER (WHERE l.outcome = 'won') * 100.0 /
     NULLIF(COUNT(*) FILTER (WHERE l.outcome IN ('won','lost')), 0))::numeric(5,1) as win_rate
FROM mlb_parlay_legs_v2 l
JOIN mlb_parlay_recommendations_v2 p ON p.id = l.parlay_id
WHERE p.run_date >= CURRENT_DATE - 7
GROUP BY l.stat, l.direction, l.line::numeric(4,1)
ORDER BY appearances DESC;

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

-- Stack bonus analysis (enriched legs)
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

-- CLV analysis (closing vs selection odds)
SELECT
    stat, direction,
    COUNT(*) FILTER (WHERE closing_odds IS NOT NULL) as clv_captured,
    COUNT(*) as total_legs,
    AVG(
        CASE WHEN closing_odds IS NOT NULL
        THEN (1.0 / (1.0 + ABS(closing_odds::numeric)/100.0)) -
             (1.0 / (1.0 + ABS(odds::numeric)/100.0))
        END
    )::numeric(5,4) as avg_clv_implied_delta
FROM mlb_scored_legs
WHERE run_date >= (CURRENT_DATE - INTERVAL '7 days')::text
  AND result IN ('won', 'lost')
GROUP BY stat, direction;

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

---

## Schema Last Verified
- `mlb_scored_legs`: 2026-06-13 (this update — columns verified against migration logs + BUILD_STATUS.md)
- `mlb_scored_legs_enriched`: 2026-06-13 (this update — columns verified against `_log_enriched_legs()` INSERT + stack bonus migration)
- `mlb_parlay_recommendations_v2`: 2026-06-13 (this update — superseded columns verified against lineup migration)
- `mlb_parlay_legs_v2`: 2026-06-13 (this update — batting_order columns verified against lineup migration)
- `mlb_parlay_recommendations_enriched`: 2026-05-28
- `mlb_parlay_legs_enriched`: 2026-05-28
- `mlb_pending_lineup_checks`: 2026-06-13 (this update — verified against lineup + CLV migrations)
- `ballpark_factors`: 2026-06-13 (this update — verified against enriched_scorer.py cache loader)
