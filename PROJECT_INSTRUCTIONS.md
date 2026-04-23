MLB Parlay Agent — Project Instructions (Updated April 23, 2026)
Repository: github.com/MrGweeod/mlb-agent
Stack: Python 3.10, PostgreSQL (Supabase), Railway, Discord bot, MLB-StatsAPI
Full Technical Blueprint: MLB_Parlay_Agent_Blueprint_v1.docx (read for architecture, data sources, build order)

Project Overview
AI-powered MLB parlay recommendation system adapted from NBA Parlay Agent v6.0. Uses Branch-and-Bound parlay construction, composite five-factor leg scoring (transitioning to ML-based prediction), and pitcher-aware matchup logic to generate 4-8 leg parlays targeting +600 to +1500 odds.
Single-Pool Strategy (Updated April 18, 2026)

All legs ≥55% coverage scored with composite formula
Top 20 legs by composite score enter parlay builder
Branch-and-Bound finds 4-8 leg combinations in +600 to +1500 odds range
Constraints: Max 1 batter leg per player, max 3 legs per game

ML Pivot (In Progress — April 23, 2026)
Decision: Transition from hand-coded composite scoring to machine learning model.

Phase 1 (COMPLETE): Historical training data collection — 66,174 resolved samples (March 28 - April 22)
Phase 2 (NEXT): Feature engineering — populate NULL feature columns for all training samples
Phase 3 (FUTURE): Train gradient boosting classifier to predict P(hit), replace heuristic leg_scorer.py
Phase 4 (FUTURE): A/B test ML vs heuristic scoring, roll out ML-based production pipeline

Current production pipeline still uses heuristic composite scoring (coverage 70%, opponent 20%, stability 10%).

Daily Schedule (9AM/12PM/5:30PM ET)

9:00 AM: Resolve last night's games + fresh pipeline with overnight transactions
12:00 PM: Updated transactions, refreshed odds, afternoon slate recommendations
5:30 PM: Final pipeline before first pitches (most lineup cards confirmed by this run)


Discord Commands

/run — Trigger full pipeline manually
/resolve — Run outcome resolver on pending bets
/status — Show pending recommendations
/calibration — Show calibration report on resolved legs
/dashboard — Performance dashboard (hit rates, P&L, trends)


Current Status (Updated: April 23, 2026)
✅ Infrastructure Running

Railway deployment: Live (mlb-agent project, 3 daily scheduled runs)
Discord bot: Connected (slash commands synced, automated posts working)
Web app: Deployed at Railway URL (interactive parlay builder + 6-section analytics dashboard)
Supabase: All mlb_* tables created and active
Environment variables: Set in Railway

✅ What Works

Discord bot posts AI recommendations 3x/day (9AM/12PM/5:30PM ET)
Web app allows manual parlay building with real-time odds calculation
Lineup poller rescores legs every 30min from 6-8PM ET when lineups confirm
Full 8-step pipeline with pitcher-aware matchup logic
Single scored pool producing 4-8 leg parlays on 10+ game slates
Historical training data collection: 66,174 resolved samples in mlb_training_data table

⚠️ Known Issues (Production Pipeline)

Coverage overconfidence: Systematically 12-23pp too high in 60%+ buckets (614 production legs, April 17-22)
Direction bias: Unders underperform (44.3% win rate vs 50.0% overs)
Overall production win rate: 47.7% (293/614 legs hit)

📊 Training Data Status (NEW)
MetricCountTotal props logged73,942Resolved (hit/miss)66,174 (89.5%)Hits31,450 (47.5%)Misses34,724 (52.5%)NULL (DNP/scratched)7,768 (excluded from training)Date rangeMarch 28 - April 22, 2026 (26 days)
File: scripts/backfill_training_data.py (410 lines)
Database table: mlb_training_data (ready for feature engineering)

Workflow Rules — Cost & Efficiency Optimization
When to Use Manual Actions (You)
Always prefer manual actions when possible — they're free and often faster than spinning up Claude Code.
✅ Use Terminal/Web UI For:

Updating environment variables (Railway, Discord Developer Portal, Supabase)
Checking Railway logs, deployment status
Git operations: git pull, git status, git commit, git push
Reading small files: cat README.md, less bot.py
Installing packages: pip install -r requirements.txt
Running the bot locally: python bot.py
Supabase: Table Editor for schema inspection, SQL Editor for queries
GitHub: Creating repos, branches, reviewing diffs
Discord Developer Portal: Creating bots, copying tokens, generating invite URLs

When to Use Claude Chat (This Session)
Use Claude Chat for strategy, planning, and small code reviews.
✅ Use Claude Chat For:

Architecture decisions, debugging strategy, interpreting error logs
Reviewing pasted code snippets (< 100 lines) — paste code here instead of asking Claude Code to view it
Writing SQL queries, environment variable templates, config snippets
Explaining errors or suggesting targeted fixes
Planning multi-step workflows before execution
Cost-benefit analysis on whether a task needs Claude Code at all

When to Use Claude Code
Use Claude Code only for actual coding work that requires file editing.
✅ Use Claude Code For:

Writing or editing Python files (> 20 lines of changes)
Refactoring modules, adding new features
Running tests, linters, formatters across the codebase
Debugging errors that require reading multiple interconnected files
Building new pipelines, data models, or API integrations

Decision Tree — Which Tool?
Before starting any task, ask:

Can I do this manually in < 5 minutes? → Do it yourself (free)
Can I paste the code here and get a fix in chat? → Use Claude Chat (minimal cost)
Does this require editing/creating multiple Python files? → Use Claude Code (necessary cost)


API Key & Token Hygiene

❌ Never paste raw API keys or tokens in chat or Claude Code sessions
✅ Use placeholders: ANTHROPIC_API_KEY=your_key_here
✅ Store all secrets in Railway Variables, never in .env files committed to GitHub
✅ Use .env.example as a template with placeholder values only


Git Workflow

Always git pull origin main before starting work
Commit small, logical units: "Add pitcher handedness split logic" not "Updates"
Push after every working session: git push origin main
Use branches only for experimental features, not for daily work


Railway Workflow

Check logs in Railway UI before asking for help
Redeploy after environment variable changes (Railway → Deployments → Redeploy)
Monitor build times — if builds take > 3 minutes, investigate dependency caching


Supabase Workflow

Use Table Editor (web UI) for schema inspection — no code needed
Use SQL Editor for complex queries or bulk updates
Export table data as CSV for local analysis before writing code to process it


Web App — Interactive Parlay Builder
Access: Railway deployment URL → Enter WEB_APP_PASSWORD when prompted
Purpose: Manual parlay building with real-time feedback (Discord bot only posts AI recommendations)
Features:

Browse today's scored legs with coverage %, composite score, lineup status
Tap legs to select 4-8 for a parlay
Real-time combined odds calculation
Correlation blocking (pitcher/batter same game, max 3 legs per game)
"Reaches target" filter (highlights legs bringing odds into +600-1500 range)
Auto-polls /api/legs every 5min for lineup updates
Mobile-first responsive design
NEW: 6-section analytics dashboard (calibration, prop performance, direction bias, coverage accuracy, trend validation, recent legs)

Technical:

Runs on same Railway service as Discord bot (no extra cost)
Single-file HTML app (~20 KB, vanilla JS, no build step)
Backend: src/web/server.py (aiohttp server)
Frontend: src/web/static/index.html
Data: Fetches from Supabase via /api/legs endpoint


Key MLB-Specific Differences from NBA Agent
If you're familiar with the NBA agent, these are the critical changes:
ComponentNBA AgentMLB AgentStats APInba_apiMLB-StatsAPI (pip install MLB-StatsAPI)Injury dataOfficial NBA injury PDFMLB Transaction Wire via statsapi.get('transactions')Matchup logicTeam DEF_RATING, paint/3P suppressionPitcher ERA/K9/WHIP profilesCoverage calculationOverall season hit rateSplit by opposing pitcher handedness (RHP vs LHP)Trend windows5/10/15 game rolling windows10/20 game rolling windowsStability metricMinutes stability (last 5 vs prior 10)Plate appearance stability + batting order positionLineup confirmationNBA injury PDF at 5:30 PM ETStarting lineups posted ~3.5 hours before first pitchParlay strategyTwo-pool anchor/swing (legacy)Single scored pool (current)
Most Important: Every batter's coverage rate must be calculated separately for games vs RHP and vs LHP. A .280 hitter vs RHP but .320 vs LHP facing a LHP tonight has a different edge than overall season average suggests.

Build Order Reference
See Section 10 of MLB_Parlay_Agent_Blueprint_v1.docx for full build order.

Phase 1: Direct copies from NBA agent (Discord bot, database, parlay builder, Claude agent) — ✅ COMPLETE
Phase 2: MLB adaptations (MLB-StatsAPI, coverage calculator, pitcher matchup logic, leg scorer) — ✅ COMPLETE
Phase 3: New modules (Transaction Wire, lineup confirmation, main pipeline, web app) — ✅ COMPLETE
Phase 4: Training data collection (historical backfill, database table) — ✅ COMPLETE
Phase 5: ML model training (feature engineering, GradientBoostingClassifier, ML-based scorer) — ⏳ NEXT

Before building each module: Check if it already exists in the repo. Don't rebuild what's already there.

Validation Checklist Before Building
Complete these before writing any Phase 5 code:

✅ Verify SportsGameOdds API returns MLB props with fairOdds field (tested with sport='MLB')
✅ Verify pitcher prop markets (Strikeouts, Innings Pitched) are available on DraftKings in Massachusetts
✅ Verify MLB-StatsAPI provides real-time box scores for same-day outcome resolution
✅ Test that alt lines are available for MLB pitcher props on SGO
✅ Confirm all environment variables are set in Railway: SPORTSGAMEODDS_API_KEY, ODDS_API_KEY, ANTHROPIC_API_KEY, DATABASE_URL, DISCORD_BOT_TOKEN, DISCORD_GUILD_ID, SCHEDULE_CHANNEL_ID, WEB_APP_PASSWORD
✅ Verify historical training data collection works (66,174 samples collected March 28 - April 22)


Current Scoring Weights (Heuristic — Pre-ML)
Production pipeline still uses hand-coded composite scoring:

Coverage: 70%
Opponent adjustment: 20%
PA stability: 10%
Trend: 0% (no predictive value found)
EV: 0% (dropped — not useful for parlay construction, see ARCHITECTURE_DECISIONS.md)

Note: These weights will be replaced by ML model predictions in Phase 5.

For Claude Code Sessions
When starting a Claude Code session:
Always read these files first:

PROJECT_INSTRUCTIONS.md (this file)
SESSION_HANDOFF.md (tracks what was done in the last session)
ARCHITECTURE_DECISIONS.md (tracks major architectural decisions)
BUILD_STATUS.md (tracks what's built vs what's missing)

Best practices:

Check existing code before suggesting changes — use view or git log to see what's already there
Prefer targeted fixes over rewrites — if a function works, don't rewrite it just to match a different style
Commit and push at the end of every logical unit of work — don't wait until the end of the session
Update SESSION_HANDOFF.md before ending the session — document what was built, what's next, any blockers


For Claude Chat Sessions
When working in Claude Chat (Desktop Project):

This session has access to uploaded files only — if you need to reference code, paste it here or upload the file
Before asking for code changes, paste the relevant code here first — saves Claude Code tokens
Use this session for planning, strategy, and small fixes — escalate to Claude Code only when you need to edit multiple files
Document decisions in ARCHITECTURE_DECISIONS.md — if we decide on an architectural approach, add it to the notes so Claude Code sessions can reference it


Common Commands Reference
Local Development
bash# Start bot locally
python bot.py

# Run a manual pipeline test
python -c "from main import run_pipeline; run_pipeline()"

# Run historical backfill (training data collection)
python scripts/backfill_training_data.py

# Check what's been built
ls -la src/apis/
ls -la src/engine/
ls -la src/pipelines/

# View recent commits
git log --oneline -10
Railway
bash# View logs (web UI is easier)
railway logs

# Redeploy
railway up
API Testing
python# Test SportsGameOdds API for MLB props
import requests
api_key = "YOUR_KEY"
response = requests.get(
    "https://api.sportsgameodds.com/v1/props",
    params={"sport": "MLB", "apiKey": api_key}
)
print(response.json()[:2])

When You Get Stuck

Check Railway logs first — 90% of deployment issues show up there
Paste error messages in Claude Chat — get a diagnosis before spinning up Claude Code
Verify environment variables — missing or misnamed vars cause silent failures
Check Discord Developer Portal — bot permissions issues are common and easy to fix manually
Review SESSION_HANDOFF.md — previous sessions may have documented known issues


Next Session Priorities (from SESSION_HANDOFF.md)
HIGH PRIORITY

Add prospective collection to daily pipeline — log today's props to training_data each run
Build feature calculation module — populate NULL feature columns for all 66K rows
Train initial ML model — sklearn GradientBoostingClassifier with 66K samples
A/B test ML vs heuristic scoring — compare parlay quality over 3-5 days

MEDIUM PRIORITY

Investigate why coverage is systematically overconfident (global 0.85× deflation?)
Filter unders more aggressively (44.3% vs 50.0% overs)
Add ballpark factors, weather signals to feature set

LOW PRIORITY

Parlay-level ML optimizer (learns which leg combinations work best)
Reinforcement learning approach for parlay construction


Key Files & Directories
mlb-agent/
├── bot.py                              # Discord bot entry point
├── main.py                             # Main pipeline orchestrator
├── scripts/
│   └── backfill_training_data.py      # Historical training data collection (410 lines)
├── src/
│   ├── apis/
│   │   ├── mlb_stats.py               # MLB-StatsAPI wrapper
│   │   ├── sportsgameodds.py          # SGO props fetcher
│   │   ├── injuries.py                # Transaction Wire poller
│   │   └── lineup_confirmation.py     # Lineup card confirmation gate
│   ├── engine/
│   │   ├── coverage.py                # Handedness-split coverage calculator
│   │   ├── leg_scorer.py              # Heuristic composite scorer (to be replaced by ML)
│   │   └── parlay_builder.py          # Branch-and-Bound optimizer
│   ├── pipelines/
│   │   ├── enrich_legs.py             # Pitcher matchup profiles
│   │   └── trend_analysis.py          # HOT/COLD/NEUTRAL rolling windows
│   ├── tracker/
│   │   ├── outcome_resolver.py        # Box score outcome resolution
│   │   └── calibration.py             # Coverage accuracy tracking
│   └── web/
│       ├── server.py                  # aiohttp web server
│       └── static/index.html          # Interactive parlay builder + dashboard
└── docs/
    ├── PROJECT_INSTRUCTIONS.md        # This file
    ├── SESSION_HANDOFF.md             # Last session summary
    ├── ARCHITECTURE_DECISIONS.md      # Major design decisions
    └── BUILD_STATUS.md                # What's built vs what's missing

Database Tables (Supabase PostgreSQL)
TablePurposeRow Countmlb_scored_legsProduction legs from daily pipeline614 (April 17-22)mlb_training_dataHistorical props + outcomes for ML training73,942 (March 28 - April 22)mlb_recommendationsAI-generated parlay recommendations~50mlb_calibrationCoverage accuracy trackingAggregated from scored_legs

For full technical details, architecture diagrams, and MLB-specific implementation notes, see MLB_Parlay_Agent_Blueprint_v1.docx.
