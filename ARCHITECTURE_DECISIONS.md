# MLB Parlay Agent — Architecture Decisions
*Captured from Chat Session April 18, 2026*

---

## Parlay Builder — Unified Scoring Pool

**Decision:** Replace fixed anchor/swing pool architecture with a unified 
scoring pool.

**Old architecture (NBA-inherited, caused 0 parlays):**
- Pre-sort legs into anchor bucket (≥70% coverage, -500 to -150 odds)
- Pre-sort legs into swing bucket (≥55% coverage, -150 to +250 odds)
- Fill fixed slots: 2-4 anchors + exactly 2 swings
- Problem: high-coverage positive-odds legs fell into swing bucket but 
  required connector legs that were rarely available

**New architecture:**
- Single pool: all legs ≥55% coverage
- Score all legs with composite formula
- Take top 20 by composite_score
- Branch-and-Bound finds 5-8 leg combinations in +1000 to +1500 odds range
- Constraints: max 1 batter leg per player, max 3 legs per game, 
  no duplicate odd_ids
- Optimize for geometric mean of individual coverage rates across 
  selected legs
- Diversity filter: ≤3 shared legs between parlays yields top 5

---

## Coverage Thresholds — MLB Calibrated

**Decision:** Replace NBA coverage thresholds with MLB-specific values.

**Rationale:** NBA points props have different variance profiles than 
MLB hitting props. A .300 hitter goes hitless ~37% of games — 70% 
coverage anchor floor would filter out almost everything.

| Category | Anchor Floor | Swing Floor | Notes |
|---|---|---|---|
| Hits O/U 0.5 | 62% | 52% | Baseball variance is structural |
| Total Bases O/U 1.5 | 60% | 50% | Harder line, lower floor |
| Pitcher Strikeouts O/U 4.5+ | 68% | 55% | More predictable |
| RBIs, Runs, HR | Not anchor eligible | 48% | Swing only |
| Walks O/U 0.5 | 60% | 50% | Platoon dependent |

**Logging floor:** Log ALL eligible legs to mlb_scored_legs regardless 
of coverage score. No floor on logging — floor only applied for parlay 
selection. This maximizes training data velocity.

---

## Target Parlay Odds Window

**Decision:** +1000 to +1500

**Rationale:** +800 is too low (achievable with safe legs, low payout), 
+2500 is too high (requires too many long shots). +1000-+1500 is 
achievable with 4-6 solid legs without stacking variance.

**Leg count:** 5-8 legs per parlay (min 5, max 8)

---

## Composite Scoring Weights

**Current implementation in leg_scorer.py:**

| Factor | Anchor | Swing | Signal |
|---|---|---|---|
| Recency-weighted coverage | 60% | 40% | MLB game log, 3x/2x/1x weighting |
| EV | 0% | 25% | SGO fairOverUnder vs DK book odds |
| Trend score | 15% | 15% | HOT/COLD/NEUTRAL 10/20 game windows |
| Opponent adjustment | 15% | 15% | Pitcher ERA/K9/WHIP rank |
| PA stability | 10% | 5% | pa_avg_10 / 4.0 normalized |

**Note:** anchor/swing labels are now unused in the single-pool 
architecture. All legs scored with role="swing" weights. The 
anchor-weight variant (60% coverage, 0% EV) is available but 
not currently called. Recalibrate weights after 500+ resolved legs.

**EV calculation:** `ev_per_unit = 0.50 - implied_probability(book_odds)`
SGO fairOverUnder is the 50/50 fair line. Positive = bettor-friendly.

---

## Trend Pass Gate — Removed

**Decision:** Remove trend_pass boolean hard gate from eligibility.

**Rationale:** Early season avg_10 ≈ avg_20 caused near-universal 
trend_pass failures. Small sample sizes make slope/momentum signals 
unreliable in April.

**Current behavior:** trend_score contributes 15% weight to 
composite_score but does NOT hard-gate eligibility. COLD legs 
can enter pool — monitored as a risk.

---

## Daily Pipeline Schedule

**Three runs per day:**

| Time ET | Primary Job | Notes |
|---|---|---|
| 9:00 AM | Resolve last night + early props | 1PM game lineups may be confirmed |
| 12:00 PM | Afternoon slate | Most important run for 1PM/4PM games |
| 5:30 PM | Evening slate | Bulk of daily slate |

**Late games (9PM/10PM west coast):** Handled by lineup pending 
indicator in web app, not a 4th cron job. Background poller runs 
every 30 minutes from 6-8 PM ET. When lineup confirms, triggers 
targeted rescore: fresh SGO odds + confirmed pitcher profile + 
recalculated coverage. NOT just a status flag flip.

**Late game resolution:** 10PM games resolved in next morning's 
9AM run. No overnight resolver needed.

---

## Web App — Not Discord Slash Commands

**Decision:** Interactive parlay builder lives at a web URL, 
not inside Discord.

**Rationale:** Discord slash commands require a new command for 
every state update. Parlay building needs real-time reactivity — 
tap a leg, odds update instantly. Discord can't do this cleanly.

**Architecture:**
- Discord bot: delivery only — posts scored legs report 3x/day
- Web app: hosted on same Railway service as bot (no extra cost)
- Single Railway service runs both bot and aiohttp web server
- Frontend: single self-contained HTML file, no build step, 
  no npm, vanilla JS
- Data: fetches scored legs from Supabase via /api/legs endpoint
- Auth: WEB_APP_PASSWORD env var, bearer token, sessionStorage

**Web app behavior:**
- Auto-polls /api/legs every 5 minutes for lineup updates
- Updates cards in place without resetting selections or scroll
- Lineup confirmed: green checkmark indicator
- Lineup pending: amber clock indicator with "lineup pending" text
- Last updated timestamp shown as relative time on each card
- Correlation blocking: pitcher/batter same game blocked, 
  2-leg per game cap enforced
- Reaches target filter: highlights legs that bring combined 
  odds into +1000-+1500 window
- Submit = sendPrompt() with full parlay for Claude analysis

**Mobile-first responsive:**
- Mobile (<768px): sticky header, bottom drawer for selected legs, 
  horizontally scrollable filter pills
- Desktop (≥768px): two-column layout, selected panel fixed right
- One codebase handles both via CSS media query

---

## Training Velocity — Priority

**Decision:** Optimize early architecture for training data 
generation, not parlay accuracy.

**Rationale:** Composite weights are principled priors, not 
validated values. Need 500+ resolved legs before recalibration 
is meaningful. Maximize resolved legs per day to reach that 
threshold faster.

**Implementation:**
- Log all eligible legs (no coverage floor on logging)
- Run all three daily pipeline windows even when props are thin
- Log complete factor breakdowns per leg (not just outcome)
- Surface top 20-30 scored legs per run in addition to parlays
- Small real-money wagers placed manually during calibration 
  phase to generate real outcome data

---

## SGO API — Confirmed Field Names

**Validated live April 16, 2026:**

| Field | SGO Name | Notes |
|---|---|---|
| Fair odds | fairOverUnder | Populated 20/20 in test |
| Book odds | byBookmaker.draftkings.odds | Single field, not over/under split |
| Prop category | statID | e.g. "hitting_hits", "pitching_strikeouts" |
| Alt lines | altLines | 0 found at 11AM — recheck at game time |

**StatID normalization map in sportsgameodds.py:**
SGO statIDs like "hitting_hits" normalized to internal keys 
like "hits" via _SGO_STAT_ID_MAP before any downstream routing.

**DK props available=false until ~2 hours before first pitch.**
9AM pipeline will return 0 props on most days. 12PM and 5:30PM 
are the meaningful runs.

---

## Pre-Launch Checklist Status

| Item | Status | Notes |
|---|---|---|
| Discord bot created | In progress | Need SCHEDULE_CHANNEL_ID |
| Railway project created | Unknown | Needs verification |
| Railway env vars set | Unknown | See variable list below |
| railway.toml verified | Unknown | Check repo root |
| Supabase init_db() run | Not done | Run before first deploy |
| First deploy + health check | Not done | After env vars set |
| First live pipeline test | Not done | Run after 2PM ET on game day |
| Coverage threshold in main.py | UNVERIFIED | Check 62% not 70% |

**Railway environment variables required:**

| Variable | Source |
|---|---|
| DISCORD_BOT_TOKEN | Discord developer portal |
| DISCORD_GUILD_ID | Right-click server → Copy Server ID |
| SCHEDULE_CHANNEL_ID | Right-click channel → Copy Channel ID |
| ANTHROPIC_API_KEY | Reuse from NBA agent |
| SPORTSGAMEODDS_API_KEY | Reuse from NBA agent |
| ODDS_API_KEY | Reuse from NBA agent |
| DATABASE_URL | Supabase → Settings → Database → Session Pooler |
| WEB_APP_PASSWORD | Your choice — not changeme |

---

## Known Bugs Fixed (This Session)

| Bug | Fix | File |
|---|---|---|
| SGO statIDs not normalized | Added _SGO_STAT_ID_MAP | sportsgameodds.py |
| ev_per_unit never set | Added _compute_ev() helper | sportsgameodds.py |
| Transaction filter returned 813 entries | Added RELEVANT_TYPE_CODES whitelist | mlb_stats.py |
| Two-pool arch produced 0 parlays | Single scored pool refactor | parlay_builder.py |
| trend_pass failing early season | Removed hard gate | trend_analysis.py |

---

## Open Items / Next Session Priorities

| Item | Priority | Notes |
|---|---|---|
| Verify coverage threshold in main.py (62% not 70%) | HIGH | Before any live run |
| Complete pre-launch checklist | HIGH | Blocking first live run |
| First live pipeline test at game time | HIGH | After deploy |
| Per-leg appearance cap in top-5 output | Medium | Max 3 of 5 parlays per leg |
| COLD leg soft penalty in leg_scorer | Low | Accept as tradeoff for now |
| Pitcher prop coverage model | Low | Phase 4 extension |
| Alt lines on DK MLB props | Low | Retest at game time |

---

## Pitcher Strikeout Props — Poisson Coverage Model
**Date:** April 21, 2026

**Decision:** Enable pitcher K props using a simple Poisson coverage model instead of waiting for full pitcher game log implementation.

**Implementation:**
- New function: `calculate_pitcher_k_coverage()` in `src/engine/coverage.py`
- Fetches pitcher season stats via `statsapi.player_stat_data()`
- Calculates K/game rate (prefers games started, falls back to games pitched)
- Uses Poisson distribution: P(K > line) = 1 - poisson.cdf(line, lambda=k_per_game)
- Minimum 3 appearances required for reliability
- Confidence multiplier applied same as batter props

**Pipeline changes:**
- `main.py`: Removed pitcher K props from blocking gates
- `leg_scorer.py`: Route pitcher K props to fallback coverage (don't fetch batter game log)
- Result: 278 pitcher K props now eligible

**Rationale:**
- Quick win: implemented in 1 hour vs 3 hours for full pitcher coverage
- Pitcher K is highest-quality pitcher prop market (most liquid)
- Validates strategy before investing in full IP/HA/ER implementation
- Can upgrade to game log model later if needed

---

## Web App as Primary Interface
**Date:** April 21, 2026

**Decision:** Make web app the primary interface, remove automated parlay generation from pipeline.

**Current architecture (NBA agent legacy):**
- Discord bot posts automated parlays 3x/day
- Pipeline: resolve + props + build parlays + Claude analysis → Discord
- Web app is secondary manual builder

**New architecture (to be implemented):**
- Web app is primary: browse legs → build → analyze → place bet → auto-resolve
- Pipeline simplified: resolve + props + score legs only (no parlay building)
- Claude analysis: only triggered manually from web app (saves tokens)
- Bet tracking: user places bets via web app, resolver checks them next day

**Rationale:**
- Don't waste tokens on automated analysis (3x/day) for parlays not being bet
- User wants to build parlays manually, not receive recommendations
- Training data velocity: resolve ALL legs (not just parlays) for model improvement
- Cleaner UX: one interface for everything

**Implementation status:** Partially complete — web app is primary interface, pipeline still generates parlays for Discord (low priority to remove)

---

## Web Search Removed from Analyze Feature
**Date:** April 21, 2026

**Decision:** Remove web search tool from `analyze_parlays()` — analyze based purely on statistical data provided (coverage, EV, trend, opponent adjustment).

**Rationale:**
- Web search caused 60-second delays (now 10-20s)
- Hallucinated incorrect injury info (said players were on IL when they weren't)
- Added token costs without accuracy benefit
- Lineup confirmation already handled by pipeline (legs without confirmed starters excluded)

**Implementation:**
- Removed `tools` parameter from Claude API call
- Updated prompt to explicitly say "Do NOT search for external information"
- Enhanced leg data passed to Claude: coverage + EV + trend + opponent adjustment
- Claude now analyzes: coverage quality, correlations, parlay construction, matchup quality

**Result:** Fast, accurate, statistical analysis with no hallucinations.

---

## Position Filters Added to Web App
**Date:** April 21, 2026

**Decision:** Add position-based filters (All / Hitters / Pitchers) to web app for easy separation of batter props from pitcher props.

**Implementation:**
- New filter row above stat filter chips
- Dynamic counts update on load: "All (N) / Hitters (N) / Pitchers (N)"
- `PITCHER_POSITIONS` set: `{SP, RP, P, TWP}`
- Combined filtering: position + stat (AND logic)
- Scoped click handlers so position and stat filters don't clear each other

**Rationale:** With pitcher K props now in the pipeline, users need easy way to isolate pitcher props (calibrated +2.6% error) from batter props (calibrated +2.4% error for hits).

---

## Per-Odd_id Deduplication (Database)
**Date:** April 21, 2026

**Decision:** Change `log_scored_legs()` from date-level deduplication to per-`odd_id` deduplication with `ON CONFLICT (odd_id) DO NOTHING`.

**Old behavior:**
- Check: `SELECT COUNT(*) WHERE run_date = ?`
- If count > 0 → skip entire insertion
- Problem: Morning run blocks afternoon pitcher K props from being added

**New behavior:**
- `INSERT ... ON CONFLICT (odd_id) DO NOTHING`
- Afternoon pipeline can add pitcher K props without duplicating morning's batter props
- Each leg identified by unique SGO odd_id

**Migration:**
```sql
ALTER TABLE mlb_scored_legs ADD COLUMN odd_id TEXT;
ALTER TABLE mlb_scored_legs ADD CONSTRAINT mlb_scored_legs_odd_id_uq UNIQUE (odd_id);
```

**Result:** Pitcher K props can be added when DraftKings posts them (mid-afternoon) without waiting for next day.

---

## Box-Score-Based Outcome Resolver
**Date:** April 21, 2026

**Decision:** Replace per-player game-log resolver with box-score-based resolver that fetches one box score per game (not one per player).

**Old approach:**
- Call `statsapi.player_stat_data()` for each player (1 API call per leg)
- 300 legs = 300 API calls
- Slow, rate-limited, inefficient

**New approach:**
- Group legs by `game_pk`
- Fetch `statsapi.boxscore_data(game_pk)` once per game
- Extract all player stats from single box score
- 300 legs across 15 games = 15 API calls

**Performance:** 10-30x faster resolution

**Files:** `src/tracker/outcome_resolver.py` (complete rewrite)

---

## Calibration Results — April 21, 2026
**Date:** April 21, 2026

**Dataset:** 458 resolved legs (April 17-20, 2026)

**Key Findings:**

### Coverage Calibration (After Fixes)
- 70%+ bucket: predicted 74.4%, actual 68.3% (+6.1% error) ✅
- 60-65% bucket: predicted 62.8%, actual 60.5% (+2.3% error) ✅
- **Before fixes:** 70%+ bucket hit at 46% (+30.9% error) ❌

**Fixes applied:**
1. Confidence multipliers now applied: `adjusted = 0.50 + mult × (raw - 0.50)`
2. Fixed lineup_poller scale bug (coverage_pct stored as 0-1 instead of 0-100)

### Prop-Specific Performance
- **Hits (over):** +2.4% error (150 legs) — well calibrated
- **Pitcher Ks (over):** +2.6% error (77 legs) — well calibrated
- **Total Bases (over):** +13.4% error (24 legs) — penalty tightened to 0.78x
- **RBIs, Walks:** Small samples (14-11 legs) — pending more data

### EV Signal
**Status:** Inverted in historical data (April 17-20 used old broken formula)
- Strong +EV legs: 42.9% hit rate ❌
- Strong -EV legs: 61.0% hit rate ❌

**Root cause:** Old `_compute_ev` used `0.50 - book_implied` ignoring fair_line entirely, rewarding longshot odds. Fixed April 21 to use `fair_line vs book_line` comparison.

**Action:** Need 2-3 days of new data to validate correction. Current weight: 0% (disabled until validated).

### Trend Signal
**Status:** No predictive value
- Passing trend: 50.0% hit rate
- Failing trend: 54.7% hit rate (slightly inverted)

**Action:** Weight set to 0% (trend signal has zero correlation with outcomes in this dataset).

### Current Scoring Weights (Post-Calibration)
- Coverage: 70% (up from 40%)
- Opponent adjustment: 20% (up from 15%)
- PA stability: 10% (up from 5%)
- EV: 0% (disabled until signal validates)
- Trend: 0% (no predictive value)

---

## Coverage Calculation — Log-Odds Transformation
**Date:** April 22, 2026

**Decision:** Replace linear split ratio multiplication with a log-odds transformation when applying handedness adjustments to coverage rates.

**Problem with linear multiplication:**
```python
# Old (broken):
coverage = overall_rate × (rate_vs_hand / rate_overall)
# → Jeremiah Jackson vs LHP: 65.2% × 1.608 = 104.8% → capped to 100%
# → Both OVER and UNDER of the same prop could get 100% coverage
# → Same coverage for both directions is mathematically impossible
```

**Fix — log-odds transformation:**
```python
# New (fixed):
log_odds_base = math.log(overall_rate / (1 - overall_rate))   # logit(overall_rate)
log_odds_adj  = math.log(rate_vs_hand / rate_overall)          # split adjustment
coverage_rate = 1.0 / (1.0 + math.exp(-(log_odds_base + log_odds_adj)))  # sigmoid
# → Jeremiah Jackson vs LHP: logit(0.652) + log(0.471/0.293) = sigmoid(1.104) = 75.1%
# → Always in (0, 1) — no capping needed
```

**Result:**
- Coverage range: 23.1%–90.5% (was many at 100%)
- Historical legs rescored: 618/639 updated via `scripts/rescore_historical_legs.py`
- Files: `src/engine/coverage.py` — commit `f849237`

**Remaining issue:** Coverage is still systematically overconfident (12-23pp errors in upper buckets). The log-odds fix eliminated the 100% clipping problem but did not close the gap between predicted and actual rates. A global deflation multiplier (0.85×) is under consideration.

---

## Database Deduplication — DEDUP_CTE
**Date:** April 22, 2026

**Decision:** Add a `DEDUP_CTE` to all dashboard calibration queries, and surgically delete 59 true-duplicate NULL odd_id rows from the database.

**Problem:** PostgreSQL UNIQUE constraints do NOT prevent multiple NULLs. `ON CONFLICT (odd_id) DO NOTHING` only fires for non-NULL values. Some legs were inserted twice — once with `odd_id=NULL` (early pipeline run) and once with a real odd_id (later run). This inflated calibration sample sizes by ~10%.

**Investigation:**
- 673 raw resolved legs → 614 unique after dedup
- 59 rows safely deletable: NULL odd_id rows with a non-NULL sibling for the same (run_date, player_name, stat, direction)
- 504 NULL odd_id rows kept: sole records with no non-NULL equivalent

**Fix 1 — Delete true duplicates (one-time migration):**
```sql
DELETE FROM mlb_scored_legs
WHERE odd_id IS NULL
  AND id NOT IN (
    SELECT MIN(id) FROM mlb_scored_legs
    WHERE odd_id IS NULL
    GROUP BY run_date, player_name, stat, direction
  )
  AND (run_date, player_name, stat, direction) IN (
    SELECT run_date, player_name, stat, direction
    FROM mlb_scored_legs
    WHERE odd_id IS NOT NULL
  );
```

**Fix 2 — DEDUP_CTE in all dashboard queries (defensive, ongoing):**
```sql
WITH deduped AS (
    SELECT *,
           ROW_NUMBER() OVER (
               PARTITION BY run_date, player_name, stat, direction
               ORDER BY ev_per_unit DESC NULLS LAST
           ) AS _rn
    FROM mlb_scored_legs
    WHERE result IS NOT NULL
)
SELECT ... FROM deduped WHERE _rn = 1
```

**Fix 3 — init_db() schema updated:**
```sql
odd_id TEXT,
UNIQUE (odd_id)
```
Added to `CREATE TABLE mlb_scored_legs` so fresh Railway deployments include the column without requiring a manual `ALTER TABLE`.

**Files:** `src/utils/db.py` — commit `41be85d`
