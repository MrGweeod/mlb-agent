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
-
