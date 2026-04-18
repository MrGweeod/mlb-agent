MLB Parlay Agent — Session Handoff
April 18, 2026 — System live, web app deployed, producing 5 parlays/day

Project Overview
AI-powered MLB parlay recommendation system adapted from the NBA Parlay Agent v6.0.
Python 3.10, WSL2 Ubuntu. Hosted on Railway. Discord bot delivers recommendations.
PostgreSQL via Supabase (same instance as NBA agent, new mlb_* tables).
GitHub: github.com/MrGweeod/mlb-agent.
Blueprint: MLB_Parlay_Agent_Blueprint_v1.docx in repo root.

Status: Live and Producing Parlays
All three phases complete and running. The agent produces 5 parlays per day on a 15-game slate. Last confirmed clean run: 2026-04-18, 157 eligible legs, 5 parlays (+1441–+1482).
Deployment:

Railway: mlb-agent project (running)
Discord bot: Connected, slash commands synced
Web app: Deployed at Railway URL (see Web App section below)
Database: Supabase PostgreSQL (mlb_* tables)


Phase 2 — Complete (MLB Data Layer)
FileStatusNotessrc/apis/mlb_stats.pyDoneSchedule, game logs, box scores, lineup, transactions, pitcher hand, player infosrc/engine/coverage.pyDoneHandedness-split coverage via statSplits+Poisson; fallback to game-log ratesrc/pipelines/trend_analysis.pyDone10/20-game windows; PA stability; trend_pass removed (see below)src/apis/matchup.pyDonePer-pitcher ERA/K9/WHIP with normalised batter-perspective adjustmentssrc/pipelines/enrich_legs.pyDoneProp routing per blueprint §5.2; sets opponent_adjustment ∈ [-1, +1]src/engine/leg_scorer.pyDonePA stability replaces minutes; recency-weighted coverage uses MLB logsrc/apis/rotowire.pyDoneVisible-text scraper for RotoWire MLB lineup/injury pagessrc/engine/claude_agent.pyDoneanalyze_parlays() with web_search tool; get_injured_players() removedsrc/apis/sportsgameodds.pyDoneDK MLB props; batting_ prefix; _BLOCKED_STAT_IDS for combo propssrc/pipelines/lineup_poller.pyDoneConfirms lineups 6–8PM ET and rescores legs; runs every 30 minsrc/web/server.pyDoneaiohttp web server with /, /api/legs, /api/health routes; auth via WEB_APP_PASSWORDsrc/web/static/index.htmlDoneInteractive parlay builder UI (17.5 KB single-file app) — leg selection, correlation blocking, lineup status, auto-polling

Phase 3 — Complete (Pipeline + Bot + Web App)
FileStatusNotesmain.pyDoneFull 8-step pipeline; single scored pool (two-pool arch removed 2026-04-18)bot.pyDoneDiscord bot; 3 scheduled runs (9AM/12PM/5:30PM ET); lineup poller; web server integrationsrc/bot/runner.pyDoneAsync wrappers around run_pipeline(), resolve, status, calibrationsrc/bot/formatter.pyDoneDiscord embed formatterssrc/engine/parlay_builder.pyDoneSingle scored pool — see architecture section below

Web App Architecture
Deployment: Hosted on same Railway service as Discord bot (no extra cost)
Routes:

GET / → Serves interactive UI (no auth required for page load)
GET /api/legs?date=YYYY-MM-DD → Returns scored legs JSON (requires auth)
GET /api/health → Health check for Railway (no auth)

Authentication:

Query param: ?password=<WEB_APP_PASSWORD>
Header: Authorization: Bearer <WEB_APP_PASSWORD>
UI prompts for password before calling /api/legs

Features:

Auto-polls /api/legs every 5 minutes for lineup updates
Lineup status indicators (green checkmark = confirmed, amber clock = pending)
Correlation blocking (pitcher/batter same game blocked, max 2 legs per game)
"Reaches target" filter (highlights legs bringing combined odds into +1000-1500)
Real-time odds calculation as you select/deselect legs
Mobile-first responsive (sticky header on <768px, two-column on ≥768px)

Access:

Go to Railway dashboard → mlb-agent service → Domains
Copy the Railway URL (e.g., https://mlb-agent-production-XXXX.up.railway.app)
Visit URL in browser
Enter WEB_APP_PASSWORD when prompted
Build parlays by tapping legs


main.py Pipeline (8 Steps)

Transaction Wire    get_transactions() → filter SC/DES/OU/CU → blocked_names set
Schedule            get_schedule() → build team_id_to_abbr, pitcher_id_map, opponent_map
SGO Props           get_todays_games() + get_player_props() per game
Coverage Gate       calculate_coverage() for each batter prop at standard line
Injury Filter       transaction wire blocked_names only (LLM check removed)
Enrichment          enrich_legs(legs, pitcher_id_map, opponent_map, season)
Trend Signals       get_trend_signal() per leg (role param unused; trend_pass removed)
Parlay Builder      build_hybrid_parlays(legs, num_games, team_to_blocked)


Architecture Reference
Parlay builder — single scored pool
All legs with coverage ≥ 55% → score_legs_composite() → top 20 by composite_score. B&B searches for combinations of 4–8 legs whose combined American odds land in +600 to +1500.
Constraints: Max 1 batter leg per player, max 3 legs per game, no duplicate odd_ids. Parlays ranked by avg_composite DESC; diversity filter yields top 5.
Composite scoring weights
Coverage (recency-weighted) 40%, EV 25%, Trend score 15%, Opponent adjustment 15%, PA stability 5%
Trend signals
Windows: 10/20 games. PA proxy: atBats avg ≥ 3.0. Form labels: HOT/COLD/NEUTRAL. trend_pass gate removed.
Prop routing
hits: −K/9 70%, totalBases: ERA 60%, rbi: ERA 55%, homeRuns: ERA 75%, walks: WHIP 80%, runsScored: ERA 50%, stolenBases: 0.0, strikeouts: +K/9 90%

Known Bugs Fixed
statsapi.teams() AttributeError, 0 SGO props, player_name includes stat label, enrich_legs TypeError, LLM injury check hallucinating, opposing_pitcher_id 404 spam, Combo props errors, mlb_scored_legs missing columns, 0 parlays (two-pool arch), trend_pass failing early-season, Web app missing from documentation

Open Items / Next Steps
HIGH: Find Railway URL and test web app, Set WEB_APP_PASSWORD in Railway
MEDIUM: Pool diversity (same 2 legs anchor every parlay)
LOW: COLD legs in pool, Pitcher prop coverage model, Alt lines on DK MLB props

Pre-Launch Checklist

 Create Discord bot
 Set DISCORD_GUILD_ID and SCHEDULE_CHANNEL_ID
 Create Railway project
 Verify DATABASE_URL, SPORTSGAMEODDS_API_KEY, ANTHROPIC_API_KEY
 Verify WEB_APP_PASSWORD is set in Railway
 Find Railway deployment URL and test web app


Please gamble responsibly.
