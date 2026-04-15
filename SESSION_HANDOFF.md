# MLB Parlay Agent — Session Handoff
*April 15, 2026 — Phase 2 Priorities 3–6 complete*

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
| 7 | `src/apis/rotowire.py` | Pending | Adapt — update target URLs to MLB lineup/injury pages |

**Next session starts at:** `src/apis/rotowire.py` (Priority 7), then `main.py` (Phase 3)

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

Phase 2 also needs `src/apis/rotowire.py` (Priority 7 — update target URLs to MLB lineup/injury pages).

**Note on parlay_builder.py**: still contains NBA-era imports (`get_player_id`, `get_game_log`, `calc_stat_value` from coverage.py). These will break at runtime. Must be cleaned up before or alongside main.py — remove the `best_player_legs` NBA game-log path and replace with MLB equivalent or drop combined-hit-rate validation entirely (the hybrid builder `build_hybrid_parlays` doesn't use it).

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

These must be answered before Phase 2 scoring logic is finalised:

| Question | Why it matters |
|----------|---------------|
| Does SGO return DraftKings MLB props with `fairOdds` populated? | If missing, EV factor weight drops to 0 |
| Are pitcher prop markets available on DraftKings in MA? | If not, exclude pitcher prop category from pipeline |
| Typical lineup card lead time before first pitch? | Determines whether 5:30PM run catches all confirmations |
| Does MLB-StatsAPI provide real-time box scores same day? | Outcome resolver may need to run next morning |
| Are alt lines available for MLB pitcher props on SGO? | Affects swing leg pool diversity |

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

- **Start next session by opening this file and reading the Phase 2 section**
- Phase 2 starts with `src/apis/mlb_stats.py` — nothing else can be completed without it
- After writing mlb_stats.py, immediately write a quick smoke test (fetch one player's game log for 2026)
- Commit at the end of each logical unit; push before ending a session
- Query `mlb_scored_legs` after each pipeline run to verify pool composition
- All DB calls go through `get_conn()` which retries on OperationalError (3× with 2s sleep)

*Please gamble responsibly.*
