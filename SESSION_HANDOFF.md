# MLB Parlay Agent — Session Handoff
*April 16, 2026 — Phase 2 complete + lineup poller, web server, mobile app*

---

## Project Overview

AI-powered MLB parlay recommendation system, adapted directly from the NBA Parlay Agent v6.0.
Python 3.10, WSL2 Ubuntu. Hosted on Railway. Discord bot delivers recommendations.
PostgreSQL via Supabase (same instance as NBA agent, new `mlb_*` tables).
GitHub: github.com/MrGweeod/mlb-agent.
Blueprint: `MLB_Parlay_Agent_Blueprint_v1.docx` in repo root.

---

## Phase 1 Complete — Infrastructure Copied and MLB-Adapted

All sport-agnostic infrastructure is in place. The repo is importable but not runnable —
Phase 2 modules (mlb_stats.py, coverage.py, etc.) are stubs or absent.

### Files written this session

| File | Status | Notes |
|------|--------|-------|
| `bot.py` | Done | MLBBot class, scheduled tasks enabled, /dashboard stub added |
| `src/utils/db.py` | Done | All tables `mlb_*` prefixed; `pitcher_profiles` table added; two post-commit fixes (see below) |
| `src/utils/odds_math.py` | Done | Straight copy |
| `src/engine/parlay_builder.py` | Done | Tier thresholds updated for MLB slate sizes (Tier 1 ≥10 games) |
| `src/bot/runner.py` | Done | Table names updated to `mlb_*`; no nba_api calls present |
| `src/bot/formatter.py` | Done | "NBA Parlay Agent" → "MLB Parlay Agent" only change |
| `src/tracker/recommendation_logger.py` | Done | Table names updated |
| `src/tracker/calibration.py` | Done | Table names updated |
| `src/tracker/bet_logger.py` | Done | Table names updated |
| `src/tracker/outcome_resolver.py` | **Skeleton only** | nba_api removed; all stat/box score logic stubbed with TODO comments |
| `src/__init__.py` and all sub-package `__init__.py` | Done | Full src/ tree importable |

### Post-commit fixes to `src/utils/db.py` (commit 603541a)

- `get_player_position()` now returns `{"position": ..., "bats": ...}` instead of a bare string
- `get_player_handedness(player_id)` added — returns just the `bats` value (`"L"`, `"R"`, `"S"`, or `None`)
- `set_player_position()` signature simplified to `(player_id, position, bats=None)` — `throws` parameter removed; column stays in schema as nullable but nothing writes to it. Pitcher hand is handled separately via `pitcher_profiles.hand`.

### Database tables created by `init_db()` on first import of `src/utils/db.py`

```
mlb_player_game_logs        mlb_player_positions (bats nullable; throws nullable, unused)
mlb_player_props_cache      mlb_qualifying_legs_cache
mlb_bayes_scores_cache      mlb_injury_cache
mlb_recommendations         mlb_recommendation_legs (+ pitcher_id, prop_category)
mlb_parlays                 mlb_parlay_legs (+ prop_category, pitcher_id, batter_hand)
mlb_llm_analysis_cache      mlb_sgo_request_log
mlb_matchup_sensitivity_cache   mlb_opponent_defense_cache
mlb_scored_legs (+ prop_category, pitcher_era_rank, batter_vs_hand_coverage)
pitcher_profiles            ← new table, no NBA equivalent
```

---

## Phase 2 — Progress

Phase 2 is the adaptation layer: replace NBA data sources with MLB equivalents.
Build order per blueprint Section 10:

| Priority | File | Status | Notes |
|----------|------|--------|-------|
| 1 | `src/apis/mlb_stats.py` | **Done** | Wraps MLB-StatsAPI: schedule, game logs, box scores, lineup, transactions, pitcher hand, player info |
| 2 | `src/engine/coverage.py` | **Done** | Handedness-split coverage via statSplits+Poisson; exact game-log fallback; seasonal ramp-up gate |
| 3 | `src/pipelines/trend_analysis.py` | **Done** | PA stability (atBats proxy); 10/20-game windows; oldest-first log; no TOV signal |
| 4 | `src/apis/matchup.py` | **Done** | Pitcher ERA/K9/WHIP → [-1,+1] batter adj; pitcher_profiles DB cache (24h TTL) |
| 5 | `src/pipelines/enrich_legs.py` | **Done** | Prop routing per §5.2: hits→K/9, TB/RBI→ERA, walks→WHIP, SB→0; takes pitcher_id_map + opponent_map from caller |
| 6 | `src/engine/leg_scorer.py` | **Done** | PA stability replaces teammate injury as Factor 5; recency-weighted coverage from MLB oldest-first log |
| 7 | `src/apis/rotowire.py` | **Done** | Context-only scraper; `get_lineup_notes` + `get_injury_notes`; never gates legs; returns [] on failure |

**Next session starts at:** `main.py` (Phase 3) — feeds validated, pre-main fixes complete, lineup poller + web server running

### Pre-main.py Bug Fixes (April 16, session 3)

| Fix | File | Status |
|-----|------|--------|
| 1 — SGO stat field normalization | `src/apis/sportsgameodds.py` | **Done** |
| 2 — `ev_per_unit` on every prop dict | `src/apis/sportsgameodds.py` | **Done** |
| 3 — Transaction filter noise (813→1) | `src/apis/mlb_stats.py` | **Done** |

**Fix 1**: Added `_SGO_STAT_ID_MAP` after `PROP_STATS`. Maps SGO statID strings
(`"hitting_hits"`, `"pitching_strikeouts"`, etc.) to internal pipeline keys (`"hits"`,
`"strikeouts"`, etc.). Unknown statIDs pass through unchanged and print a warning line.
Combination props (`"batting_hits+runs+rbi"`) intentionally unmapped — will appear in logs.

**Fix 2**: Added `_compute_ev(fair_line, standard_odds)` helper. `ev_per_unit` now set on
every prop dict in `get_player_props()`. Formula: `0.50 - implied_probability(book_odds)`.
Positive = bettor-friendly price; negative = book-favourite. Returns 0.0 on missing inputs.

**Fix 3**: Added `RELEVANT_TYPE_CODES = {"SC", "DES", "CU", "OU"}` module constant in
`mlb_stats.py`. Filter now requires BOTH typeCode in whitelist AND sport.id check.
Result: 813 → 1 transaction on 2026-04-16 (only Bido DFA remained — correct).

**main.py is now unblocked.**

---

## Phase A/B/C — Lineup Poller, Web Server, Mobile App (April 16, session 4)

### Phase A — Background Lineup Poller (`src/pipelines/lineup_poller.py`)

New module. Public API: `poll_and_refresh(season=None) -> int`.

**How it works:**
1. Calls `_ensure_schema()` — `ALTER TABLE ADD COLUMN IF NOT EXISTS` for 5 new columns on `mlb_scored_legs`: `game_pk INTEGER`, `player_id TEXT`, `opposing_pitcher_id TEXT`, `lineup_confirmed BOOLEAN DEFAULT FALSE`, `last_updated TEXT`.
2. Fetches today's unconfirmed legs (`get_pending_lineup_legs`) filtered to `game_pk IS NOT NULL`.
3. Groups by `game_pk`, calls `get_lineup(game_pk)` once per game.
4. For confirmed lineups: re-calculates coverage with `calculate_coverage()`, calls `score_leg()` for new composite, updates DB via `update_leg_after_rescore()`.
5. Players not found in the confirmed batting order are marked confirmed (scratched/DH exclusion).
6. Returns count of legs updated.

**Bot wiring:** `lineup_poll` task runs every 30 minutes. Inside the task, a `datetime.now(ET).hour` guard restricts execution to 18–19 (6:00–8:00 PM ET). Uses `run_in_executor(None, poll_and_refresh)` since `poll_and_refresh` is synchronous.

**DB changes in `src/utils/db.py`:**
- `mlb_scored_legs` CREATE TABLE now includes the 5 new columns.
- `log_scored_legs()` INSERT now writes `game_pk`, `player_id`, `opposing_pitcher_id` from the leg dict (all optional, default None).
- New helpers: `get_pending_lineup_legs()`, `update_leg_after_rescore()`, `mark_lineup_confirmed()`, `get_scored_legs()`.

### Phase B — Web Server (`src/web/server.py`)

aiohttp server started in `MLBBot.setup_hook()` via `await start_server()`. Shares the discord.py asyncio event loop. Listens on `PORT` env var (default 8080 — Railway sets this automatically).

**Routes:**
| Route | Auth | Returns |
|-------|------|---------|
| `GET /` | None | `src/web/static/index.html` |
| `GET /api/legs` | Required | JSON array of today's scored legs |
| `GET /api/health` | None | `{"status":"ok","date":"YYYY-MM-DD"}` |

**Auth:** `WEB_APP_PASSWORD` checked against `?password=` query param or `Authorization: Bearer` header. If `WEB_APP_PASSWORD` is unset, all requests pass (open access). Default in `.env`: `changeme` — change before deploying.

**`requirements.txt`:** `aiohttp==3.13.5` added.

### Phase C — Mobile Web App (`src/web/static/index.html`)

Self-contained single-file HTML/CSS/JS. No external dependencies.

**Features:**
- Password entry screen (calls `/api/legs?password=<pw>` to verify)
- Stat filter chips (All / Hits / Total Bases / RBI / HRs / Ks / SBs / Walks / Runs / IPs)
- Sort by Coverage, EV, or Player name
- Toggle to hide under-direction props
- Summary bar: total legs, parlay legs, average coverage
- Card view: player, matchup, prop (stat+line+odds), coverage badge (green/yellow/red), EV, lineup-pending tag, in-parlay tag
- Tap to expand detail: P(Over), trend score, opponent adj, position, result, actual value
- Auto-refresh every 5 minutes
- Mobile-first dark theme

**Verified live (2026-04-16):**
- `/api/health` → `{"status":"ok","date":"2026-04-16"}` ✓
- `GET /` → serves index.html (title match confirmed) ✓
- `GET /api/legs?password=changeme` → JSON array (1 existing row) ✓
- `Authorization: Bearer changeme` header → JSON array ✓
- No-auth → 401 JSON ✓

---

## coverage.py — Design Notes (April 2026)

### API limitation discovered
`MLB-StatsAPI gameLog` ignores `sitCodes` — returns all games regardless.
Per-game handedness filtering is not available from the API without N additional calls.

### Approach used
- **Split path**: `statSplits&sitCodes=vl/vr` → aggregate stats (gamesPlayed + counting totals)
  per pitcher handedness. Poisson approximation converts avg_stat_per_game → P(stat >= line).
- **Fallback path**: exact game-by-game count from `gameLog` (proportion of games where stat >= line).
- **Which path**: split used when pitcher_hand known + stat supported + split_games >= 10.
  `stolenBases` and `runs` are null in statSplits → always fallback.

### statSplits gamesPlayed caveat
`gamesPlayed` in statSplits counts games where batter had *any* PA vs that pitcher type
(including relievers), not just "opposing starter was LHP/RHP". Overcounts relative
to starter-based filtering but is the best available signal without per-game lookups.

### Verified with Freeman 2025
- vs LHP (Kershaw 477132): coverage_rate=0.371, games_used=97, mult=1.0
- vs RHP (Skenes 694973): coverage_rate=0.567, games_used=142, mult=1.0
- LHB correctly lower coverage vs same-hand pitcher — baseball makes sense.

---

## New Module Design Notes (April 2026)

### trend_analysis.py

- Game log is **oldest-first** from mlb_stats — no reversal needed for chronological calcs.
- Streak iterates `reversed(game_log)` (most-recent-first).
- PA stability proxy: `atBats` field from game log entry. pa_pass threshold: avg ≥ 3.0 AB/game over last 10.
- Windows: last 10 stat values for slope/std; last 20 for momentum comparison (avg_10 > avg_20).
- trend_score components: pa_slope (+2/-1), stat_slope (+2/-1), momentum (+1). Max = 5, typical HOT = 4–5.
- Caches results in `_process_cache` dict keyed by (player_id, stat, best_line) — session-level.

### matchup.py

- Fetches `/people/{id}/stats?stats=season&group=pitching&season={year}` for cumulative season stats.
- Uses API-provided `era` and `whip` strings directly; computes K/9 from `strikeOuts / inningsPitched * 9`.
- IP parsing: "145.1" means 145⅓ innings (digit after `.` = outs, not decimal tenths).
- Skips pitchers with < 5.0 IP (too few starts to be meaningful — filters openers called up same day).
- Percentile ranks (1–100): era_rank/whip_rank → lower is better (rank 1); k9_rank → higher is better (rank 1).
- Normalisation midpoints: ERA=4.0, K/9=8.5, WHIP=1.25.

### enrich_legs.py

**Caller contract** — main.py must build and pass:
```python
pitcher_id_map = {batter_team_abbr: opposing_pitcher_id}   # e.g. {"NYY": 477132}
opponent_map   = {batter_team_abbr: opposing_team_abbr}    # e.g. {"NYY": "BOS"}
```
Built by iterating `mlb_stats.get_schedule(date)` and calling `mlb_stats.get_lineup(game_pk)` for each game.

Adjustment routing summary:
| stat | formula |
|------|---------|
| hits | `-k9_adj×0.70 + era_adj×0.20 + whip_adj×0.10` |
| totalBases | `era_adj×0.60 + (-k9_adj)×0.25 + whip_adj×0.15` |
| rbi | `era_adj×0.55 + whip_adj×0.30 + (-k9_adj)×0.15` |
| homeRuns | `era_adj×0.75 + (-k9_adj)×0.25` |
| walks | `whip_adj×0.80 + era_adj×0.20` |
| runsScored | `era_adj×0.50 + whip_adj×0.30 + (-k9_adj)×0.20` |
| stolenBases | `0.0` |
| strikeouts (batter K) | `k9_adj×0.90 + (-era_adj)×0.10` |
| pitcher props | `0.0` (TODO: team K-rate) |

### leg_scorer.py

Composite weights:
| Factor | Anchor | Swing |
|--------|--------|-------|
| Recency-weighted coverage | 60% | 40% |
| EV | 0% | 25% |
| Trend score | 15% | 15% |
| Opponent adjustment | 15% | 15% |
| PA stability | 10% | 5% |

- Recency weighting: MLB log is oldest-first. `games[-5:]` = 3×, `games[-10:-5]` = 2×, `games[:-10]` = 1×.
- PA stability factor: `min(pa_avg_10 / 4.0, 1.0)`. Fallback 0.5 when `pa_avg_10` not in leg dict.
- Pitcher props fall back to `coverage_pct / 100` for recency-weighted coverage (pitcher prop coverage TBD).
- `team_to_blocked` parameter is accepted for API compatibility with parlay_builder but currently unused in scoring.

### rotowire.py

- URLs: `daily-lineups.php` and `injury-report.php` (baseball).
- `_TextExtractor(HTMLParser)` strips script/style/noscript blocks; returns visible text chunks.
- `date` parameter accepted for API compatibility; RotoWire URLs don't take a date param (always current day).
- No BeautifulSoup dependency — uses stdlib `html.parser` only.
- Both functions return `[]` silently on network errors, HTTP errors, or parse failures (logged at DEBUG).
- Verified live: both pages return nav/content text (~hundreds of chunks) — first 5 lines are nav items.

### parlay_builder.py — Cleaned up (April 16)

Legacy `build_parlays()` and its helpers (`best_player_legs`, `combined_hit_rate`,
`validate_and_trim`, `_compatible_subset`) removed. NBA-era import
`from src.engine.coverage import get_game_log, get_player_id, calc_stat_value` removed.
`build_hybrid_parlays()` is the only builder — file is importable without errors.

---

## Phase 3 — After Phase 2

| File | Action |
|------|--------|
| `src/apis/injuries.py` | Rewrite — Transaction Wire polling via MLB-StatsAPI (replace NBA PDF parser) |
| `src/apis/lineup_confirmation.py` | New — polls MLB-StatsAPI for confirmed lineups, gates legs on starter confirmation |
| `main.py` | Adapt — wire all MLB modules in same 8-step pipeline order |

---

## Pre-Build Checklist (from Blueprint Section 14)

- [ ] Create new Discord bot application and copy the token → set `DISCORD_BOT_TOKEN` in `.env`
- [ ] Set `DISCORD_GUILD_ID` and `SCHEDULE_CHANNEL_ID` in `.env`
- [ ] Create new Railway project for MLB agent (same account, no extra cost)
- [ ] Verify SGO API returns MLB props: test with `sport='MLB'` parameter
- [ ] Verify MLB-StatsAPI returns 2026 game logs: `pip install MLB-StatsAPI`, run quick test
- [ ] Add MLB tables to Supabase — happens automatically when `src/utils/db.py` is imported with a live `DATABASE_URL`

---

## Open Validation Questions (Blueprint Section 16)

Tested live 2026-04-16 via `validate_feeds.py`. See WORKING_NOTES.md for full output.

| Question | Answer |
|----------|--------|
| Does SGO return DraftKings MLB props with `fairOdds` populated? | **YES** — `fairOverUnder` populated 20/20 in first 20 props. EV factor stays at full weight. |
| Are pitcher prop markets available on DraftKings in MA? | Unknown — DK `available=false` for all props tested (markets post closer to first pitch). Re-check at 5–6PM ET. |
| Typical lineup card lead time before first pitch? | Unknown — Test 4 (Nationals @ Pirates, 4:35PM ET) showed batting orders empty at test time (~11AM). Check again post-noon. |
| Does MLB-StatsAPI provide real-time box scores same day? | Not tested this session — games hadn't started. |
| Are alt lines available for MLB pitcher props on SGO? | **Likely no / rare** — 0 altLines on DK for tested prop. DK `available=false` may be the cause; recheck post-lineup-post. |

### SGO Structure Notes (from live test)

- `fairOverUnder` (not `fairOdds`) is the fair-line field on each market — `prop.get("fairOverUnder")`
- `bookOdds` and `fairOdds` also exist at the top level but are string formatted (`"+134"`)
- `byBookmaker.draftkings.odds` is the single book-odds field — no separate `overOdds`/`underOdds`
- `statID` is the prop category field (e.g., `"batting_hits+runs+rbi"`, `"hitting_hits"`) — used for prop routing
- `oddID` format: `"{statID}-{PLAYER_NAME}_{num}_MLB-game-ou-{direction}"` — note the numeric suffix before `_MLB`
- SGO surfaces combination props (hits+runs+rbi) as a single market — may need filtering in `get_player_props()`

### Transaction Wire Filter Bug (discovered Test 5)

`get_transactions()` returned **813 entries** on 2026-04-16, almost all `typeCode='NUM'`
(uniform number changes) and foreign-league `SFA`/`ASG`/`SGN` transactions.

Root cause: `toTeam` is absent (`None`) for many foreign-league entries, so
`toTeam.sport.id in (1, None)` passes them through. Fix in `main.py` before first run:
filter to `typeCode in ("SC", "DES", "CU", "OU")` before calling `is_il_placement()`.
True IL placements are `typeCode="SC"` only — the current `is_il_placement()` checks this
internally, but the volume of noise makes logging unusable. Add pre-filter at call site.

### Player ID Correction

MLB person ID `660670` = **Ronald Acuña Jr.** (not Juan Soto as noted in handoff).
Juan Soto's correct ID = **665742**. Test 2 field-structure validation is still valid
(all stat fields confirmed present); the wrong player was used for the test.

---

## Architecture Notes

### Parlay structure (inherited from NBA, MLB thresholds)

```
Anchor heavy:  odds -1000 to -500   up to 3 legs   coverage ≥70%, trend_pass=True
Anchor mid:    odds  -499 to -150   up to 3 legs   coverage ≥70%, trend_pass=True
Connector:     odds  -149 to -100   1 (or 2 fallback)   coverage ≥70%, trend_pass=True
Swings:        odds  +100 to +150   exactly 2      coverage ≥55% (Tier 1, 10+ games)

Total legs: 5–8  |  Odds target: +1000 to +1500
Tier 1: 10+ games  |  Tier 2: 5–9  |  Tier 3: 2–4  |  Tier 4: ≤1 (no parlays)
```

### Key MLB-specific differences from NBA agent

1. **Pitcher-driven**: every leg needs opposing pitcher ERA rank, K/9 rank, WHIP rank — see blueprint Section 5
2. **Handedness splits**: batter coverage rate must be calculated vs RHP or LHP separately — see blueprint Section 4.1
3. **Transaction Wire** replaces NBA injury PDF — poll `statsapi.get('transactions')` at 9AM, 12PM, 2PM ET
4. **Lineup confirmation gate** — leg only eligible after `statsapi.get('game', hydrate='lineups')` confirms starter
5. **Prop routing** — Hits uses K/9 as primary signal; Total Bases/RBIs use ERA; pitcher props use opponent team K-rate — see blueprint Section 5.2
6. **Minimum games**: 20 (vs NBA's 15); rolling windows: 10/20 games (vs NBA's 5/10/15)

### Composite scoring weights (starting priors — recalibrate after 500+ legs)

| Factor | Weight | MLB Signal |
|--------|--------|-----------|
| Coverage rate | 40% | Hit rate from MLB-StatsAPI — handedness-split aware |
| EV | 25% | SGO fair odds vs book odds — identical to NBA |
| Trend score | 15% | HOT/COLD/NEUTRAL over 10/20 game windows |
| Opponent adjustment | 15% | Pitcher ERA/K9/WHIP rank (replaces DEF_RATING) |
| PA stability | 5% | Batting order position + PA count (replaces minutes stability) |

---

## How to work with Claude Code on this project

- **Start next session by opening this file** — read the Phase 2 progress table and design notes
- **Next up**: `src/apis/rotowire.py` (Priority 7) then Phase 3 (`main.py`)
- venv is at `.venv/` — activate with `source .venv/bin/activate` or prefix `.venv/bin/python`
- `requirements.txt` created (pinned versions from `.venv`); numpy is listed — Railway will install it
- Commit at the end of each logical unit; push before ending a session
- Query `mlb_scored_legs` after each pipeline run to verify pool composition
- All DB calls go through `get_conn()` which retries on OperationalError (3× with 2s sleep)
- Unit tests for modules without DB: stub `src.utils.db` in `sys.modules` before importing (see session commands)

*Please gamble responsibly.*
