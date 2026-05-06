# MLB Parlay Agent — Project Instructions
**Last Updated:** May 6, 2026  
**Repository:** github.com/MrGweeod/mlb-agent  
**Stack:** Python 3.10, PostgreSQL (Supabase), Railway, MLB-StatsAPI

---

## 📋 LIVING DOCUMENTS (Source of Truth)

**These three documents are the ONLY up-to-date references:**

1. **SESSION_HANDOFF.md** — What was built in the last session, current status, next priorities
2. **BUILD_STATUS.md** — Component health, operational status, known issues
3. **ARCHITECTURE_DECISIONS.md** — Design rationale, lessons learned, trade-offs

**When in doubt, trust this priority order:**
1. SESSION_HANDOFF.md (current state)
2. BUILD_STATUS.md (what's working/broken)
3. ARCHITECTURE_DECISIONS.md (why things are the way they are)
4. Railway logs (ground truth of actual behavior)
5. Conversation history (may be outdated)

---

## 🚨 CRITICAL RULE: Claude Chat NEVER Edits Project Files Directly

**If you ask Claude Chat to update a project file:**
- ❌ Claude Chat does NOT edit files in the GitHub repo
- ❌ Claude Chat does NOT attempt to commit/push changes
- ✅ Claude Chat generates an **Artifact** (downloadable file)
- ✅ You download the Artifact and manually add it to the repo
- ✅ You manually commit and push to GitHub

**Why:** This prevents Claude Chat from making changes without your review and keeps you in control of the codebase.

**For code changes:** Use Claude Code (separate tool) with explicit prompts generated here in Claude Chat.

---

## 🎯 Project Overview

AI-powered MLB parlay recommendation system. Uses ML-based leg scoring, Branch-and-Bound parlay construction, and pitcher-aware matchup logic to generate daily recommendations.

**Current Strategy (as of April 29, 2026):**
- Single scored pool (no anchor/swing buckets)
- All legs ≥55% ML score eligible
- Branch-and-Bound finds optimal 4-8 leg combinations
- Target odds: +600 to +1500
- Constraints: Max 1 batter leg per player, max 3 legs per game

---

## 📅 Daily Schedule

**Current (May 6, 2026):**
| Time (ET) | Action | Status |
|-----------|--------|--------|
| 9:00 AM | Morning pipeline (resolve + fresh props + score + build) | ✅ Active |
| 12:00 PM | Midday pipeline (refresh props + score + build) | ❌ Disabled (needs re-enabling) |
| 5:30 PM | Evening pipeline (final props + score + build) | ❌ Disabled (needs re-enabling) |

**Note:** 12 PM and 5:30 PM runs were removed when Discord bot was deleted. See SESSION_HANDOFF.md for status on re-enabling them.

---

## 🏗️ System Architecture (High Level)

### **Data Pipeline (8 Steps)**
1. Fetch transaction wire (IL/DFA via MLB-StatsAPI)
2. Build schedule and pitcher maps
3. Fetch props from SportsGameOdds API
4. Compute coverage (handedness-split aware)
5. Filter blocked players (IL, low consistency)
6. Enrich with pitcher matchup profiles
7. Compute trend signals
8. Score with ML model → Build parlays

### **ML Model**
- **File:** `leg_scorer_v2.pkl` (trained April 30, 2026)
- **Type:** Scikit-learn LogisticRegression
- **Features:** 15 (direction, coverage, trends, opponent adjustment, etc.)
- **AUC:** 0.8532
- **Known Issue:** Direction overfit (77% feature importance)

### **Web App (4 Tabs)**
1. **Legs** — Browse all scored legs, filter by stat/player/team
2. **Dashboard** — 6-section performance analytics
3. **Training** — ML data quality monitoring
4. **Picks** — 5 daily parlay recommendations

---

## 🔄 Workflow Rules (Cost Optimization)

### **Use Manual Actions When:**
- Updating environment variables (Railway, Supabase)
- Checking Railway logs or deployment status
- Git operations: `git pull`, `git status`, `git commit`, `git push`
- Reading small files: `cat README.md`
- Installing packages: `pip install -r requirements.txt`
- Supabase: Table Editor, SQL Editor
- Discord Developer Portal: bot setup, tokens

### **Use Claude Chat (This Session) When:**
- Architecture decisions, debugging strategy
- Reviewing pasted code (< 100 lines)
- Writing SQL queries, config snippets
- Explaining errors, suggesting fixes
- Planning workflows before execution
- **Generating Artifacts** for project file updates

### **Use Claude Code When:**
- Writing/editing Python files (> 20 lines)
- Refactoring modules, adding features
- Running tests, linters, formatters
- Debugging across multiple files
- Building new pipelines or integrations

**Decision Rule:**
1. Can I do this manually in < 5 minutes? → Do it yourself (free)
2. Can I paste code here and get a fix? → Claude Chat (minimal cost)
3. Need to edit multiple Python files? → Claude Code (necessary cost)

---

## 🗂️ Key Files & Directories

```
mlb-agent/
├── main.py                          # Pipeline orchestrator
├── src/
│   ├── apis/
│   │   ├── mlb_stats.py            # MLB-StatsAPI wrapper
│   │   ├── sportsgameodds.py       # Props fetcher
│   │   ├── pitcher_stats.py        # ERA/K9/WHIP rankings
│   │   └── team_stats.py           # Team offensive rankings
│   ├── engine/
│   │   ├── coverage.py             # Handedness-split coverage
│   │   ├── leg_scorer_v2.pkl       # ML model (trained Apr 30)
│   │   └── parlay_builder.py      # Branch-and-Bound optimizer
│   ├── utils/
│   │   ├── db.py                   # Supabase PostgreSQL
│   │   └── lineup_consistency.py   # 3+ AB filter (fixed May 6)
│   ├── tracker/
│   │   ├── outcome_resolver.py     # Box score resolution
│   │   └── parlay_outcome_resolver.py
│   └── web/
│       ├── server.py               # Flask app + scheduler
│       └── static/index.html       # 4-tab web UI
└── docs/
    ├── SESSION_HANDOFF.md          # ✅ CURRENT STATE
    ├── BUILD_STATUS.md             # ✅ CURRENT HEALTH
    └── ARCHITECTURE_DECISIONS.md   # ✅ CURRENT RATIONALE
```

---

## 🗄️ Database (Supabase PostgreSQL)

**Active Tables:**
| Table | Purpose | Row Count (May 6) |
|-------|---------|-------------------|
| `mlb_scored_legs` | Daily props with ML scores | ~2,500 |
| `mlb_training_data` | Historical outcomes for retraining | 77,619 |
| `mlb_parlay_recommendations` | Daily parlays tracked | 23 |
| `mlb_calibration` | Predicted vs actual bucketed | Aggregated |

---

## 🚀 Deployment (Railway)

**Platform:** Railway (PaaS)  
**Deployment:** Auto-deploy from `master` branch  
**Scheduler:** APScheduler (within Flask app)  
**Uptime:** 99.9%  

**Environment Variables:**
- `SUPABASE_URL`
- `SUPABASE_KEY`
- `ODDS_API_KEY` (TheOddsAPI for props)
- `PORT` (Railway assigned)

---

## 📊 Current Performance Metrics (May 4-6)

**Parlays:**
- Total Recommended: 23
- Resolved: 17 (74%)
- Won: 1 (5.9% hit rate) ✅ Within 5-10% expected range
- Lost: 16 (94.1%)
- Void: 0 (0% after May 6 fix)

**Legs (Last 7 Days):**
| Stat Type | Total | Won | Hit % | Void % |
|-----------|-------|-----|-------|--------|
| Strikeouts | 402 | 230 | 57.2% | 0% |
| Hits | 871 | 436 | 50.1% | 2.3% |
| RBI | 48 | 24 | 50.0% | 4.2% |
| Total Bases | 75 | 37 | 49.3% | 5.3% |
| Walks | 59 | 28 | 47.5% | 3.4% |

---

## 🔧 Common Operations

### **Check System Health**
```bash
# Railway logs
https://railway.app → mlb-agent → Deployments → View Logs

# Database
Supabase → SQL Editor

# Web app
https://[railway-url].up.railway.app
```

### **Trigger Manual Pipeline**
Web app → Picks tab → "Regenerate Now" button

### **Resolve Outcomes Manually**
```bash
python3 -c "
from src.tracker.outcome_resolver import resolve_all_legs
from src.tracker.parlay_outcome_resolver import resolve_parlay_recommendations

date = '2026-05-06'
resolve_all_legs(date, verbose=True)
resolve_parlay_recommendations(date, verbose=True)
"
```

---

## 🐛 Recent Critical Fixes (May 6, 2026)

**See SESSION_HANDOFF.md for full details:**
1. ✅ Lineup consistency filter API parameter error (fixed)
2. ✅ Dashboard SQL type mismatch (fixed)
3. ✅ Parlay void logic (partial voids now handled correctly)
4. ✅ Historical backfill complete (April 22 - May 5)

---

## 📈 Next Priorities

**See SESSION_HANDOFF.md for current priorities.**

**As of May 6:**
- Monitor 7 days of clean data
- Validate ML model performance
- Analyze lineup filter effectiveness
- Consider ML model retraining (after 500+ more samples)

---

## 🔐 Security

- Never paste raw API keys in chat or Claude Code
- Store secrets in Railway Variables only
- Use `.env.example` with placeholders

---

## 📚 Historical Documents (Archive)

**These documents are outdated — do not reference them for current state:**
- ❌ `MLB_Parlay_Agent_Blueprint_v1.docx` (April 2026 design) — Original architecture, many details outdated
- ❌ Old `PROJECT_INSTRUCTIONS.md` (April 18-29) — Replaced by this document

**Use the three living documents instead:** SESSION_HANDOFF.md, BUILD_STATUS.md, ARCHITECTURE_DECISIONS.md

---

## 🆘 When Things Break

1. **Check SESSION_HANDOFF.md** — Known issues section
2. **Check Railway logs** — 90% of issues show up there
3. **Paste error in Claude Chat** — Get diagnosis before coding
4. **Verify environment variables** — Missing vars cause silent failures

---

## 📞 Resources

- **Railway Dashboard:** https://railway.app
- **Supabase Console:** https://supabase.com
- **GitHub Repo:** github.com/MrGweeod/mlb-agent
- **Living Docs:** SESSION_HANDOFF.md, BUILD_STATUS.md, ARCHITECTURE_DECISIONS.md

---

**Last Review:** May 6, 2026  
**Next Review:** After 7 days of production monitoring (May 13, 2026)
