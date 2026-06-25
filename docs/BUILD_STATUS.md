# MLB Parlay Agent — Build Status
**Last Updated:** June 18, 2026 (Session 14 — CLR Bug Fix, Coverage Ceiling Analysis, Shadow Performance Review)

## Overall System Status: ✅ OPERATIONAL — SESSION 14 DEPLOYED

```
┌────────────────────────────────────────────────────────────────────────────────┐
│                         SYSTEM HEALTH DASHBOARD                                │
├────────────────────────────────────────────────────────────────────────────────┤
│ Prop Whitelist (Production):    ✅ HITS OVER 0.5 + SO OVER 0.5               │
│ Prop Whitelist (Coverage):      ✅ + HITS UNDER 0.5 + TOTALBASES UNDER 1.5  │
│ Coverage Gate (Overs):          ✅ 65% FLOOR                                  │
│ Coverage Gate (Unders):         ✅ 40% FLOOR (⚠️ hits/under needs raising)  │
│ Coverage Ceiling (Universal):   ✅ NOT IMPLEMENTING — prop-specific analysis  │
│                                    showed SO/over has NO ceiling through 84%+ │
│ Coverage Ceiling (hits/over):   ⚠️  ~80% CEILING PENDING — data confirmed   │
│                                    win rate drops at 80–84% (61.4%, 44 legs) │
│ hits/under Coverage Gate:       ⚠️  40% TOO LOW — avg coverage 48%, no      │
│                                    enriched signal, 1832 legs below 55% at   │
│                                    39.3% win rate. Raise to 65% pending.     │
│ Builder Score Floor (Overs):    ✅ 65.0 MIN_COV_POOL                         │
│ Builder Score Floor (Unders):   ✅ 40.0 MIN_COV_POOL_UNDER                  │
│ Parlay Structure:               ✅ 4-LEG, +400 TO +700 TARGET                │
│ Parlay Builder Sort:            ✅ COMPOSITE SCORE DESC                      │
│ MAX_CANDIDATES:                 ✅ 50                                         │
│ Cross-Run Player Cap (Prod):    ✅ MAX 2 PARLAY APPEARANCES/PLAYER/DAY       │
│ Cross-Run Player Cap (Shadow):  ✅ MAX 2 PARLAY APPEARANCES/PLAYER/DAY       │
│ Player Cap Fallback Logic:      ✅ FIXED (Session 14 — now checks            │
│                                    over_legs_remaining < 10, not just total) │
│ Intra-Run Player Diversity:     ✅ MAX 1 PER PLAYER PER PARLAY               │
│ Odds Cap:                       ✅ -250 HARD CAP PER LEG                    │
│ Max Legs Per Game:              ✅ 2                                          │
├────────────────────────────────────────────────────────────────────────────────┤
│ LINEUP CONFIRMATION LAYER (CLR)                                                │
│ Scheduler Table:                ✅ mlb_pending_lineup_checks LIVE             │
│ lineup_scheduler.py:            ✅ COMMITTED + DEPLOYED (Session 12)         │
│ Drain Cron (1-min):             ✅ RUNNING IN server.py                      │
│ T-45 Lineup Checks:             ✅ CONFIRMED FIRING                           │
│ Four-State Annotation:          ✅ MISSING/CONFIRMED/OUT_OF_RANGE/SCRATCHED  │
│ CLR Run Type:                   ✅ BUILT — UPSTREAM-ONLY REPLACEMENT POOL    │
│ CLR TB/under Exclusion:         ✅ FIXED (Session 14 — commit 8a4a7d7)       │
│                                    TB/under now excluded from CLR pool       │
│ CLR Cross-Iter Player Tracking: ✅ FIXED (Session 14 — commit 8a4a7d7)       │
│                                    used_replacement_player_ids across loop   │
│ Slot Gate (soft, -8pts):        ✅ IN simple_scorer.py                       │
│ Batting Order Backfill:         ✅ 881/1031 LEGS (85.5%) JUNE 1-10          │
│ Live Annotation:                ✅ CONFIRMED LIVE                             │
├────────────────────────────────────────────────────────────────────────────────┤
│ CLV TRACKING LAYER                                                             │
│ check_type Column:              ✅ ON mlb_pending_lineup_checks               │
│ closing_odds Column:            ✅ ON mlb_scored_legs                         │
│ clv_tracker.py:                 ✅ COMMITTED + DEPLOYED (Session 13)         │
│ CLV Rows Scheduled at T-1:      ✅ AFTER EVERY 9AM PIPELINE RUN              │
│ Live CLV Capture:               ✅ LIVE (started June 16)                    │
│ First CLV Read:                 ⏳ ~JUNE 26 (10 days of data needed)         │
├────────────────────────────────────────────────────────────────────────────────┤
│ SHADOW PIPELINE                                                                │
│ Shadow Pipeline:                ✅ RUNNING AFTER EVERY PRODUCTION RUN        │
│ Shadow Enrichment Rate:         ✅ 100%                                       │
│ Shadow Resolution (parlays):    ✅ mlb_parlay_legs_enriched.outcome CORRECT  │
│ Shadow Resolution (scored legs):✅ resolve_all_enriched_legs() ACTIVE        │
│ Shadow Resolution Direction Bug:✅ FIXED (Session 13)                        │
│ Cross-Run Player Cap (Shadow):  ✅ LIVE (Session 13)                         │
│ Park Factor Signal:             ✅ VALIDATED + PERSISTING CORRECTLY           │
│ SO/over K9 Direction:           ✅ CORRECTED (Session 13)                    │
│ hits/over Pitcher Signal:       ✅ VULNERABILITY PENALTY (<0.25=-6,<0.15=-10)│
│ hits/under Pitcher Signal:      ✅ REMOVED (no signal in data)               │
│ TB/over + TB/under WHIP Signal: ✅ UNCHANGED — WHIP ±5 direction-aware      │
│ TB/under park_factor Signal:    ⚠️  NULL FOR ALL TB/UNDER LEGS — signal     │
│                                    not populating. Fix before promotion.     │
│ TB/under opp_coverage Signal:   ⚠️  NULL FOR ALL TB/UNDER LEGS — same issue │
│ Rank Normalization (all paths): ✅ DYNAMIC — 205-pitcher pool (June 16)      │
│ Offense Stack Bonus:            ✅ BUILT + LIVE (Session 11)                 │
│ Stack Bonus Early Signal:       ⚠️  72.7% vs 55.3% — only 11 legs resolved  │
│ Shadow Win Rate Jun 16–17:      ✅ 32.0% / 25.0% vs production 10% / 22%   │
├────────────────────────────────────────────────────────────────────────────────┤
│ SCORING + SIGNALS                                                              │
│ Direction-Aware Coverage:       ✅ coverage_overall BASE SIGNAL               │
│ Consistency Signal:             ✅ GAP-BASED ±6/±4/±2/+2/+1                 │
│ WHIP Rank Signal (Hits Prod):   ✅ FIRING IN simple_scorer.py               │
│ K9 Rank Signal (SO Prod):       ✅ FIRING IN simple_scorer.py               │
│ Pitcher Vulnerability (Shadow): ✅ USED AS HITS/OVER PENALTY SIGNAL         │
│ Pitcher Ranks Pool:             ✅ 205 QUALIFIED STARTERS (June 16)          │
│ Pitcher Rank Population:        ✅ 89-96% ACROSS ERA/K9/WHIP/RAW ERA        │
│ coverage_vs_hand Fallback:      ✅ FALLS BACK TO coverage_overall            │
├────────────────────────────────────────────────────────────────────────────────┤
│ TRAINING DATA                                                                  │
│ Training Data Volume:           ✅ 94K+ ROWS                                  │
│ coverage_overall:               ✅ PERSISTED                                  │
│ coverage_recent_10:             ✅ PERSISTED                                  │
│ pitcher_era_rank:               ✅ PERSISTED                                  │
│ pitcher_k9_rank:                ✅ PERSISTED                                  │
│ pitcher_whip_rank:              ✅ PERSISTED                                  │
│ whip_adj / k9_adj / era_adj:    ✅ PERSISTED                                 │
│ Clean Data Cutoff:              ✅ APRIL 27, 2026                            │
│ Clean Shadow Cutoff:            ✅ JUNE 15, 2026 (first clean vulnerability) │
├────────────────────────────────────────────────────────────────────────────────┤
│ INFRASTRUCTURE                                                                 │
│ Database Logging:               ✅ STABLE                                     │
│ Web UI:                         ✅ FUNCTIONAL                                 │
│ Deployment:                     ✅ LIVE (Railway auto-deploy)                │
│ sklearn Version Warning:        ⚠️  1.7.2→1.8.0 mismatch on ML model        │
│                                    (non-fatal, model not in production path) │
└────────────────────────────────────────────────────────────────────────────────┘
```

---

## Recent Deployments

### 🔧 June 18, 2026 (Session 14): CLR Bug Fix + Coverage Analysis

#### Fix 1 — CLR Pool Excluding totalBases
`run_confirmed_lineup_resolution()` was building its replacement pool from `mlb_scored_legs` without the `stat != "totalBases"` filter that `main.py` uses for production parlays. TB/under legs were leaking into every CLR-generated parlay. Confirmed: 27 TB/under appearances in production Jun 16–17, almost all from `confirmed_lineup_resolution` source.

Fix: Added `eligible_pool = [l for l in eligible_pool if l.get("stat") != "totalBases"]` after pool construction in `lineup_confirmation.py`.

#### Fix 2 — CLR Cross-Iteration Player Tracking
When CLR rebuilt multiple affected parlays in one event, `build_parlays()` was called separately for each iteration with a fresh internal `used_players` set. The same top-scoring player was independently selected in every iteration. Confirmed: Jared Triolo in 10 CLR parlays Jun 17, Jackson Chourio in 9.

Fix: Added `used_replacement_player_ids: set[str] = set()` before the loop. Filtered `available_pool` against it. Updated after each successful rebuild. Cap: max 1 per CLR batch.

#### Fix 3 — Player Cap Fallback Composition Check
Fallback condition `len(qualifying_legs) < 20` didn't check prop type mix. After 5+ runs, 29 under-only legs passed the threshold but couldn't combine to +400. Builder returned 0 parlays.

Fix: Added `over_legs_remaining = [l for l in qualifying_legs if l.get("direction") == "over"]` and extended fallback to `len(qualifying_legs) < 20 or len(over_legs_remaining) < 10`. Applied same fix to `run_enriched_pipeline.py`.

**Commit:** `8a4a7d7` — 3 files changed, 21 insertions, 8 deletions. Pushed June 18 4:55 PM ET.

#### Analysis — Coverage Ceiling Is Prop-Specific
Full coverage bucket analysis (corrected 0–100 scale) run on clean data (Apr 27+). Key finding: the 84% coverage ceiling effect exists only for hits/over, and the actual peak is ~80% not 84%. SO/over shows monotonically improving win rates through 84%+. Universal ceiling not being implemented.

| Prop | Coverage Peak | Behavior Above Peak |
|---|---|---|
| hits/over | 75–80% (71.9%) | Drops to 61.4% at 80–84%, 50% at 84–90% |
| SO/over | Increasing through 84%+ | 78.7% at 80–84%, 76.7% at 84–90% — NO ceiling |
| TB/under | 70–75% (63.8%) | Gets noisy above 75% — small samples |

---

### 🔧 June 16, 2026 (Session 13): CLV Activation + Shadow Resolution Fix + Pitcher Signal Overhaul
*(See prior SESSION_HANDOFF for full details)*

Key changes: `clv_tracker.py` committed, shadow resolution direction bug fixed, `resolve_all_enriched_legs()` added, enriched scorer pitcher signals overhauled, cross-run player cap added to shadow.

**Commits:** `50cc5a9`, `d9eb7f1`, `a538fd0`

---

## Component Status

### **1. Prop Whitelist**
```python
# Production coverage + scoring:
ALLOWED_PROPS = {
    ("hits",       "over",  0.5),
    ("hits",       "under", 0.5),
    ("strikeouts", "over",  0.5),   # hitter only
    ("totalBases", "under", 1.5),   # shadow validation only
}

# Production parlays (TB/under excluded):
production_legs = [l for l in qualifying_legs if l.get("stat") != "totalBases"]
```

### **2. Coverage Gates**
| Prop / Direction | Gate | Ceiling | Status |
|---|---|---|---|
| hits/over | 65% floor | ~80% ceiling | ⚠️ Ceiling pending implementation |
| SO/over | 65% floor | None | ✅ No ceiling — data confirmed |
| hits/under | 40% floor | None | ⚠️ Floor too low — raise to 65% pending |
| TB/under (shadow) | 40% floor | ~75% (tentative) | ⚠️ Pending null signal fix |

### **3. Parlay Construction**
| Parameter | Value |
|---|---|
| Pool sort | `composite_score` DESC |
| MAX_CANDIDATES | 50 |
| Score floor (overs) | 65.0 |
| Score floor (unders) | 40.0 |
| Odds range | -250 to +150 per leg |
| Legs per parlay | 4 |
| Target odds | +400 to +700 |
| Max legs per game | 2 |
| Player diversity (intra-run) | 1 per parlay |
| Player diversity (cross-run prod) | Max 2 total appearances today |
| Player diversity (cross-run shadow) | Max 2 total appearances today |
| CLR player diversity | Max 1 per CLR batch (Session 14) |

### **4. Shadow Pipeline Pitcher Signal Routing**
| Prop | Pitcher Signal | Direction |
|---|---|---|
| hits/over | Vulnerability penalty | vuln<0.15 → -10, vuln<0.25 → -6 |
| hits/under | None | Removed — no signal in data |
| strikeouts/over | K/9 rank ±5 | Elite K (rank 1) = +5 boost |
| totalBases/over | WHIP rank ±5 | High WHIP = boost over |
| totalBases/under | WHIP rank ±5 | Low WHIP = boost under |

### **5. Shadow Pipeline Signal Status**
| Signal | Status | Last Fix |
|---|---|---|
| Pitcher Vulnerability (hits/over) | ✅ Active — penalty -6/-10 below 0.25 | Session 13 |
| K/9 for SO/over | ✅ Active — direction corrected | Session 13 |
| WHIP for TB | ✅ Active — direction-aware | Session 12 |
| Blended ERA Rank | ✅ Active — scale corrected | Session 12 |
| Opponent Coverage | ✅ Active (thin population); NULL for TB/under ⚠️ | — |
| Ballpark Factor | ✅ Validated + persisting; NULL for TB/under ⚠️ | Session 9 |
| Offense Stack Bonus | ✅ Active — early signal positive | Session 11 |

---

## Performance Metrics

### Production Parlay Win Rates (Scheduled Sources Only)
| Period | Resolved | Win Rate | Avg Odds | Edge vs Breakeven |
|---|---|---|---|---|
| Jun 1–7 | 62 | 22.6% | +481 | +5.4pp ✅ |
| Jun 8–14 | 98 | 26.5% | +443 | +8.1pp ✅ |
| Jun 15–18 | 31 | 16.1% | +473 | -1.3pp (CLR-contaminated period) |

### Production Leg Win Rates (Clean Window Apr 27+)
| Prop | Resolved | Win Rate | Avg Odds | Breakeven | Edge |
|---|---|---|---|---|---|
| totalBases/under | 89 | **67.4%** | -141 | 58.5% | **+8.9pp** ✅ |
| hits/over | 618 | 65.7% | -202 | 66.9% | -1.2pp ⚠️ |
| SO/over | 444 | 62.2% | -138 | 58.0% | **+4.2pp** ✅ |
| hits/under | 169 | 48.5% | +83 | 54.6% | -6.1pp ❌ |

### Shadow Performance Jun 16–17
| Date | Shadow Win Rate | Production Win Rate | Shadow Advantage |
|---|---|---|---|
| Jun 16 | 32.0% (25 resolved) | 10.0% (10 resolved) | +22pp |
| Jun 17 | 25.0% (20 resolved) | 22.2% (9 resolved) | +2.8pp |

---

## Pending Code Changes

| Item | File | Priority |
|---|---|---|
| Fix TB/under null park_factor + opp_coverage signals | `run_enriched_pipeline.py`, `enriched_scorer.py` | **🔴 HIGH — required before TB/under promotion** |
| Raise hits/under coverage gate from 40% to 65% | `main.py` | **High — data confirmed, one-line fix** |
| Add prop-specific hits/over ceiling at ~80% | `main.py` | **High — data confirmed, simple filter** |
| Vulnerability penalty calibration (Jun 15–22 data) | `enriched_scorer.py` | Medium — recheck thresholds ~June 22 |
| TB/under production promotion | `main.py` | Medium — after null signal fix + shadow validation |
| Stack bonus promotion | `enriched_scorer.py` | Medium — after June 20 data |
| Fix sklearn version mismatch | model retraining | Low — non-fatal |
| verify_common.py refactor | `verify_lineup_layer.py`, `verify_clv.py` | Low |
| Dead ERA cleanup | `simple_scorer.py` | Low |
| Health check threshold update | `server.py` | Low |
| Project file cleanup (retire 5 stale docs) | Project Knowledge | Low |

---

**Build Status:** ✅ HEALTHY
**Last Deployment:** June 18, 2026 — CLR bugs fixed (commit `8a4a7d7`)
**Next Review:** June 22, 2026 — TB/under null signals, hits/under gate, hits/over ceiling, vulnerability calibration
