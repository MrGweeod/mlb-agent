# MLB Parlay Agent — Session Handoff
*April 17, 2026 — main.py complete, agent runnable end-to-end*

---

## Project Overview

AI-powered MLB parlay recommendation system adapted from the NBA Parlay Agent v6.0.
Python 3.10, WSL2 Ubuntu. Hosted on Railway. Discord bot delivers recommendations.
PostgreSQL via Supabase (same instance as NBA agent, new `mlb_*` tables).
GitHub: github.com/MrGweeod/mlb-agent.
Blueprint: `MLB_Parlay_Agent_Blueprint_v1.docx` in repo root.

---

## Status: End-to-End Runnable

All three phases are complete. The agent can be started with `python bot.py`.
The pipeline runs when `/run` is invoked or at 9AM/12PM/5:30PM ET scheduled runs.

---

## Phase 1 — Complete (Infrastructure)

Sport-agnostic infrastructure copied and MLB-adapted. See earlier handoffs for details.

---

## Phase 2 — Complete (MLB Data Layer)

| File | Status | Notes |
|------|--------|-------|
| `src/apis/mlb_stats.py` | Done | Schedule, game logs, box scores, lineup, transactions, pitcher hand, player info |
| `src/engine/coverage.py` | Done | Handedness-split coverage via statSplits+Poisson; fallback to game-log rate |
| `src/pipelines/trend_analysis.py` | Done | 10/20-game windows; PA stability replaces minutes; MLB game log oldest-first |
| `src/apis/matchup.py` | Done | Per-pitcher ERA/K9/WHIP with normalised batter-perspective adjustments |
| `src/pipelines/enrich_legs.py` | Done | Prop routing per blueprint §5.2; sets opponent_adjustment ∈ [-1, +1] |
| `src/engine/leg_scorer.py` | Done | PA stability replaces minutes; recency-weighted coverage uses MLB log |
| `src/apis/rotowire.py` | Done | Visible-text scraper for RotoWire MLB lineup/injury pages |
| `src/engine/claude_agent.py` | Done | analyze_parlays() + get_injured_players() with web_search tool |
| `src/apis/sportsgameodds.py` | Done | DK MLB props; fairOverUnder confirmed; `odds` field (not overOdds/underOdds) |
| `src/pipelines/lineup_poller.py` | Done | Confirms lineups 6–8PM ET and rescores legs; runs every 30 min |
| `src/web/server.py` | Done | Minimal web server for Railway health checks |

---

## Phase 3 — Complete (Pipeline + Bot)

| File | Status | Notes |
|------|--------|-------|
| `main.py` | **Done** | Full 8-step pipeline; see below |
| `bot.py` | Done | Discord bot; 3 scheduled runs (9AM/12PM/5:30PM ET); lineup poller |
| `src/bot/runner.py` | Done | Async wrappers around run_pipeline(), resolve, status, calibration |
| `src/bot/formatter.py` | Done | Discord embed formatters |

---

## main.py Pipeline (8 Steps)

```
1. Transaction Wire    get_transactions() → filter SC/DES/OU/CU → blocked_names set
2. Schedule            get_schedule() → build team_id_to_abbr, pitcher_id_map, opponent_map
                       home_probable_pitcher (name str) → MLB person ID via statsapi.lookup_player()
3. SGO Props           get_todays_games() + get_player_props() per game
4. Coverage Gate       calculate_coverage() for each batter prop at standard line
                       min 55% to enter pool; seasonal ramp-up minimum games gate
5. Injury Filter       transaction wire blocked_names + LLM spot-check (claude_agent)
                       team_to_blocked built BEFORE removing blocked legs
6. Enrichment          enrich_legs(legs, pitcher_id_map, opponent_map, season)
7. Trend Signals       get_trend_signal() per leg; role = anchor if ≥70% coverage
8. Parlay Builder      build_hybrid_parlays(legs, num_games, team_to_blocked)
   → log_recommendations() + log_scored_legs() → analyze_parlays() (LLM)
```

---

## Known Limitations / Next Steps

### Immediate (before first real run)

| Issue | Location | Fix |
|-------|----------|-----|
| DK props `available=false` until ~2hr before first pitch | WORKING_NOTES Test 6 | Schedule 5:30PM run only; confirm with /run at game time |
| Alt lines not yet tested for MLB props | sportsgameodds.py | Test when markets open |
| Pitcher props skipped (no coverage model) | main.py `_PITCHER_POSITIONS` | Phase 4 extension |
| `home_probable_pitcher` returns name string not ID | main.py `_build_team_maps` | Handled via statsapi.lookup_player(); TBD starters set pitcher_id_map=None |

### Pre-Launch Checklist

- [ ] Create new Discord bot application → `DISCORD_BOT_TOKEN` in `.env`
- [ ] Set `DISCORD_GUILD_ID` and `SCHEDULE_CHANNEL_ID` in `.env`
- [ ] Create Railway project for MLB agent
- [ ] Verify `DATABASE_URL` in `.env` (Supabase)
- [ ] Verify `SPORTSGAMEODDS_API_KEY` in `.env`
- [ ] Verify `ANTHROPIC_API_KEY` in `.env`
- [ ] Run `/run` at game time (after ~2PM ET) to confirm DK props are available=true
- [ ] Run `.venv/bin/python -c "from src.utils.db import init_db; init_db()"` to create tables

### Validation Questions (from WORKING_NOTES)

| Question | Why it matters |
|----------|---------------|
| Are DK MLB props `available=true` closer to game time? | If not, pipeline returns 0 props |
| Do MLB DK props include alt lines? | Swing leg pool diversity |
| Does SGO fairOverUnder persist across the day? | EV factor accuracy (20/20 confirmed in Test 6) |
| Does the Transaction Wire SC filter catch all IL moves? | Injury filter completeness |

---

## Architecture Reference

### Composite scoring weights (per leg_scorer.py)

| Factor | Anchor | Swing | Signal |
|--------|--------|-------|--------|
| Coverage (recency-weighted) | 60% | 40% | MLB game log, 3×/2×/1× recent weighting |
| EV | 0% | 25% | SGO fairOverUnder vs DK book odds |
| Trend score | 15% | 15% | HOT/COLD/NEUTRAL over 10/20 game windows |
| Opponent adjustment | 15% | 15% | Pitcher ERA/K9/WHIP rank (enrich_legs.py) |
| PA stability | 10% | 5% | pa_avg_10 / 4.0 normalized |

### Prop routing (enrich_legs.py `_compute_adjustment`)

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

### Parlay structure (parlay_builder.py)

```
Anchor heavy:  -1000 to -500   up to 3 legs   coverage ≥70%, trend_pass=True
Anchor mid:    -499  to -150   up to 3 legs   coverage ≥70%, trend_pass=True
Connector:     -149  to -100   1 (or 2 fallback)  coverage ≥70%, trend_pass=True
Swings:        +100  to +150   exactly 2      coverage ≥55% (Tier 1)

Total legs: 5–8  |  Odds target: +1000 to +1500
Tier 1: ≥10 games  |  Tier 2: 5–9  |  Tier 3: 2–4  |  Tier 4: ≤1 (no parlays)
```

### Key MLB-specific differences from NBA agent

1. **Pitcher-driven**: opposing pitcher ERA/K9/WHIP rank drives opponent_adjustment
2. **Handedness splits**: coverage.py uses statSplits+Poisson; stolenBases/runs fallback to overall
3. **Transaction Wire**: `get_transactions()` replaces NBA injury PDF; pre-filter to SC/DES/OU/CU
4. **Lineup poller**: legs rescored at 6–8PM ET when batting orders confirmed via `get_lineup()`
5. **PA stability**: atBats avg over 10 games ≥ 3.0 replaces minutes_pass (NBA: 20min)
6. **Rolling windows**: 10/20 games (NBA: 5/10/15)
7. **Pitcher names in schedule**: `home_probable_pitcher` is a name string → resolved via statsapi.lookup_player()

---

*Please gamble responsibly.*
