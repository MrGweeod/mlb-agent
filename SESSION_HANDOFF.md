# MLB Parlay Agent — Session Handoff
*April 18, 2026 — single scored-pool refactor complete, pipeline producing parlays*

---

## Project Overview

AI-powered MLB parlay recommendation system adapted from the NBA Parlay Agent v6.0.
Python 3.10, WSL2 Ubuntu. Hosted on Railway. Discord bot delivers recommendations.
PostgreSQL via Supabase (same instance as NBA agent, new `mlb_*` tables).
GitHub: github.com/MrGweeod/mlb-agent.
Blueprint: `MLB_Parlay_Agent_Blueprint_v1.docx` in repo root.

---

## Status: Live and Producing Parlays

All three phases complete and running. The agent produces 5 parlays per day on a 15-game
slate. Last confirmed clean run: 2026-04-18, 157 eligible legs, 5 parlays (+1441–+1482).

---

## Phase 2 — Complete (MLB Data Layer)

| File | Status | Notes |
|------|--------|-------|
| `src/apis/mlb_stats.py` | Done | Schedule, game logs, box scores, lineup, transactions, pitcher hand, player info |
| `src/engine/coverage.py` | Done | Handedness-split coverage via statSplits+Poisson; fallback to game-log rate |
| `src/pipelines/trend_analysis.py` | Done | 10/20-game windows; PA stability; `trend_pass` removed (see below) |
| `src/apis/matchup.py` | Done | Per-pitcher ERA/K9/WHIP with normalised batter-perspective adjustments |
| `src/pipelines/enrich_legs.py` | Done | Prop routing per blueprint §5.2; sets opponent_adjustment ∈ [-1, +1] |
| `src/engine/leg_scorer.py` | Done | PA stability replaces minutes; recency-weighted coverage uses MLB log |
| `src/apis/rotowire.py` | Done | Visible-text scraper for RotoWire MLB lineup/injury pages |
| `src/engine/claude_agent.py` | Done | `analyze_parlays()` with web_search tool; `get_injured_players()` removed |
| `src/apis/sportsgameodds.py` | Done | DK MLB props; `batting_` prefix; `_BLOCKED_STAT_IDS` for combo props |
| `src/pipelines/lineup_poller.py` | Done | Confirms lineups 6–8PM ET and rescores legs; runs every 30 min |
| `src/web/server.py` | Done | Minimal web server for Railway health checks |

---

## Phase 3 — Complete (Pipeline + Bot)

| File | Status | Notes |
|------|--------|-------|
| `main.py` | Done | Full 8-step pipeline; single scored pool (two-pool arch removed 2026-04-18) |
| `bot.py` | Done | Discord bot; 3 scheduled runs (9AM/12PM/5:30PM ET); lineup poller |
| `src/bot/runner.py` | Done | Async wrappers around run_pipeline(), resolve, status, calibration |
| `src/bot/formatter.py` | Done | Discord embed formatters |
| `src/engine/parlay_builder.py` | Done | Single scored pool — see architecture section below |

---

## main.py Pipeline (8 Steps)

```
1. Transaction Wire    get_transactions() → filter SC/DES/OU/CU → blocked_names set
2. Schedule            get_schedule() → build team_id_to_abbr, pitcher_id_map, opponent_map
                       home_probable_pitcher (name str) → MLB person ID via statsapi.lookup_player()
3. SGO Props           get_todays_games() + get_player_props() per game
4. Coverage Gate       calculate_coverage() for each batter prop at standard line
                       min 55% to enter pool; pitcher props skipped (_PITCHER_POSITIONS)
5. Injury Filter       transaction wire blocked_names only (LLM check removed — wire is authoritative)
                       team_to_blocked built BEFORE removing blocked legs
6. Enrichment          enrich_legs(legs, pitcher_id_map, opponent_map, season)
7. Trend Signals       get_trend_signal() per leg (role param unused; trend_pass removed)
8. Parlay Builder      build_hybrid_parlays(legs, num_games, team_to_blocked)
   → log_recommendations() + log_scored_legs() → analyze_parlays() (LLM + web_search)
```

---

## Architecture Reference

### Parlay builder — single scored pool (parlay_builder.py)

```
All legs with coverage ≥ 55% → score_legs_composite() → top 20 by composite_score

B&B searches for combinations of 4–8 legs (Tier 1/2) or 3–8 legs (Tier 3)
whose combined American odds land in +600 to +1500.

Constraints:
  - Max 1 batter leg per player (pitchers exempt — multiple pitcher props allowed)
  - Max 3 legs per game (keyed by game_pk, fallback to team abbr)
  - No duplicate odd_ids within a parlay

Parlays ranked by avg_composite DESC; diversity filter (≤3 shared legs) yields top 5.

Tier 1: ≥10 games, min 4 legs  |  Tier 2: 5–9 games, min 4 legs
Tier 3: 2–4 games, min 3 legs  |  Tier 4: ≤1 game, returns []
```

Previous two-pool architecture (anchors/connectors/swings, +1000–+1500 target) produced
0 parlays because high-coverage, positive-odds legs (+130–+215) fell in the swing bucket,
which required connectors as bridges — rarely available. Replaced 2026-04-18.

### Composite scoring weights (leg_scorer.py)

| Factor | Weight | Signal |
|--------|--------|--------|
| Coverage (recency-weighted) | 40% | MLB game log, 3×/2×/1× recent weighting |
| EV | 25% | SGO fairOverUnder vs DK book odds |
| Trend score | 15% | HOT/COLD/NEUTRAL form over 10/20 game windows |
| Opponent adjustment | 15% | Pitcher ERA/K9/WHIP rank (enrich_legs.py) |
| PA stability | 5% | pa_avg_10 / 4.0 normalized |

`score_legs_composite()` called with `role="swing"` for all legs (single pool).
The anchor-weight variant (60% coverage, 0% EV) is no longer used.

### Trend signals (trend_analysis.py)

- Windows: 10/20 games (oldest-first native MLB log order)
- PA proxy: `atBats` avg over last 10 games ≥ 3.0 → `pa_pass`
- Form labels: HOT (streak ≥4 AND momentum), COLD (streak ≤-3 OR declining + no momentum), NEUTRAL
- `trend_pass` boolean gate **removed** — early-season avg_10 ≈ avg_20 caused near-universal failure
- `trend_score` contributes to composite_score via 15% weight but does not hard-gate eligibility
- `role` parameter accepted but unused (defaults to `"swing"`)

### Prop routing (enrich_legs.py)

| Stat | Primary signal | Secondary |
|------|---------------|-----------|
| hits | −K/9 (70%) | ERA (20%), WHIP (10%) |
| totalBases | ERA (60%) | −K/9 (25%), WHIP (15%) |
| rbi | ERA (55%) | WHIP (30%), −K/9 (15%) |
| homeRuns | ERA (75%) | −K/9 (25%) |
| walks | WHIP (80%) | ERA (20%) |
| runsScored | ERA (50%) | WHIP (30%), −K/9 (20%) |
| stolenBases | 0.0 | pitcher-independent |
| strikeouts (batter Ks) | +K/9 (90%) | −ERA (10%) |

---

## Known Bugs Fixed (cumulative)

| Bug | Fix | Session |
|-----|-----|---------|
| `statsapi.teams()` AttributeError | `statsapi.get("teams", {"sportId": 1})` | 2026-04-17 |
| 0 SGO props (`hitting_` prefix) | Renamed to `batting_` in `_SGO_STAT_ID_MAP` | 2026-04-17 |
| `player_name` includes stat label | `_STAT_NAME_SUFFIX` dict to strip labels | 2026-04-17 |
| `enrich_legs` TypeError on None pitcher | Filter `None` before `sorted()` | 2026-04-17 |
| LLM injury check hallucinating dates | Removed `get_injured_players()` call entirely | 2026-04-17 |
| `opposing_pitcher_id or 0` → 404 spam | Changed to `or None` | 2026-04-17 |
| Combo props (`hits+runs+rbi`) logged as errors | `_BLOCKED_STAT_IDS` silent skip | 2026-04-17 |
| `mlb_scored_legs` missing columns | `ALTER TABLE … ADD COLUMN IF NOT EXISTS` | 2026-04-17 |
| 0 parlays (two-pool arch too narrow) | Single scored pool, +600–+1500 window | 2026-04-18 |
| `trend_pass` failing early-season | Removed hard gate; trend_score contributes via 15% weight | 2026-04-18 |

---

## Open Items / Next Steps

| Item | Priority | Notes |
|------|----------|-------|
| Pool diversity — same 2 legs anchor every parlay | Medium | Consider per-leg appearance cap (max 3 of 5 parlays) to force variety in top-5 output |
| COLD legs in pool | Low | trend_pass removal means COLD legs eligible; consider soft COLD penalty in leg_scorer |
| Pitcher prop coverage model | Low | Phase 4 extension; currently skipped via `_PITCHER_POSITIONS` |
| Alt lines on DK MLB props | Low | Not yet tested when markets open; would improve leg diversity |
| `get_batter_game_log(701678)` error | Low | One player ID returns `list index out of range`; likely non-MLB player in SGO feed |

---

## Pre-Launch Checklist

- [ ] Create Discord bot application → `DISCORD_BOT_TOKEN` in `.env`
- [ ] Set `DISCORD_GUILD_ID` and `SCHEDULE_CHANNEL_ID` in `.env`
- [ ] Create Railway project for MLB agent
- [ ] Verify `DATABASE_URL`, `SPORTSGAMEODDS_API_KEY`, `ANTHROPIC_API_KEY` in `.env`

---

*Please gamble responsibly.*
