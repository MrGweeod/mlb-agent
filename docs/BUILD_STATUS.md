# MLB Parlay Agent — Build Status
**Last Updated:** June 1, 2026 (Session 4 — Performance Diagnosis + Full System Refactor)

## Overall System Status: ✅ OPERATIONAL — SESSION 4 DEPLOYED
```
┌────────────────────────────────────────────────────────────────────┐
│                    SYSTEM HEALTH DASHBOARD                         │
├────────────────────────────────────────────────────────────────────┤
│ Prop Whitelist:            ✅ HITS O/U 0.5 + SO OVER 0.5 ONLY    │
│ Single Flat Pool:          ✅ 65% COVERAGE, -250 TO +150 ODDS     │
│ Parlay Structure:          ✅ 4-LEG, +400 TO +700 TARGET          │
│ EEP Bug Fix:               ✅ FALSE-VOID BUG RESOLVED             │
│ Backfill (May 29-Jun 1):   ✅ 43 PARLAYS CORRECTLY RE-RESOLVED    │
│ Coverage Gate:             ✅ 65% MINIMUM (70% FOR HITS UNDER)    │
│ Odds Cap:                  ✅ -250 HARD CAP PER LEG               │
│ Player Diversity:          ✅ MAX 1 PER PLAYER PER PARLAY         │
│ Max Legs Per Game:         ✅ 2                                    │
│ Shadow Pipeline:           ✅ 4 SIGNALS, FULLY WIRED              │
│ Training Data:             ✅ LOGGING (94K+ ROWS)                 │
│ Database Logging:          ✅ STABLE                              │
│ Web UI:                    ✅ FUNCTIONAL                          │
│ Deployment:                ✅ LIVE (Railway auto-deploy)          │
│ 9AM Pipeline:              ✅ PRODUCING PARLAYS                   │
│ June 1 Output:             ✅ 3 PARLAYS (+613, +447, +419)        │
└────────────────────────────────────────────────────────────────────┘
```

---

## Recent Deployments

### 🎯 June 1, 2026: Single Flat Pool + 4-Leg Parlays
**Commit:** `1ebbb24`

- Eliminated anchor/swing two-pool system entirely
- New structure: single pool, `coverage_overall >= 65%`, odds `-250 to +150`
- 4-leg parlays, target +400 to +700
- `build_parlays()` is the new primary function; `build_hybrid_parlays()` retained as backward-compat wrapper
- `_find_qualifying_legs()` returns `list[dict]` instead of tuple
- Shadow pipeline updated to use single pool
- 238 lines removed from `parlay_builder.py`

**Motivation:** Anchor/swing caused parlay starvation — only 1 swing leg available on thin slates. With only 3 validated prop types all priced similarly (-250 to +150), the two-pool distinction added no value.

---

### 🔧 June 1, 2026: Anchor Floor Fix
**Commit:** `351ec61`

- `MIN_COV_ANCHOR`: 75.0 → 65.0
- `ANCHOR_MAX_ODDS`: -150 → -130
- `SWING_MIN_ODDS`: -150 → -129 (closed dead zone)

**Motivation:** With anchor floor at 75%, 0 anchor legs were qualifying on a 9-game slate (all legs scoring 64-69).

---

### 🎯 June 1, 2026: Prop Whitelist + 3-Leg Parlays
**Commit:** `885a4a7`

- `ALLOWED_PROPS` whitelist in `_find_qualifying_legs()`: only `hits over 0.5`, `hits under 0.5`, `strikeouts over 0.5` (hitter)
- 3-leg parlays, +300 to +550 (superseded same day by 4-leg refactor)
- Hard -200 odds cap
- Removed all dead signals: pitcher ERA block, pitcher K9 for pitchers, Signal 4 (team SO), `calculate_pitcher_k_coverage()`
- Removed props: totalBases, rbi, walks, pitcher SO, homeRuns, stolenBases

---

### 🐛 June 1, 2026: EEP False-Void Bug Fix
**Commit:** `928b6c6`

**Bug:** Early Exit Protection voiding every batter leg. `batting.get("plateAppearances", 0)` defaulted to 0 when `boxscore_data()` returned empty stats dict. `0 < 2` → EEP fired → leg voided before stat extraction.

**Fixes:**
1. `plateAppearances`: `get(..., 0) or 0` → `get(...)` with `is not None` guard
2. `battersFaced`: same fix
3. `not player_stats` guard catches both `None` and `{}` (empty dict)
4. `game_not_found`: now sets `all_resolved = False` and defers parlay instead of voiding leg (fixes dead `all_resolved` code)

**Impact:** 43 void parlays backfilled (May 29–June 1). 3 parlays recovered as wins.

---

## Component Status

### **1. Prop Whitelist** ✅ ENFORCED IN `_find_qualifying_legs()`

```python
ALLOWED_PROPS = {
    ("hits",       "over",  0.5),
    ("hits",       "under", 0.5),
    ("strikeouts", "over",  0.5),  # hitter only — pitchers skipped unconditionally
}
```

Data-validated over 60 days / 90K+ resolved legs:

| Prop | Coverage Predictive? | Win Rate at 75%+ | Avg Odds | Edge |
|---|---|---|---|---|
| hits over 0.5 | ✅ Yes | 75.4% | -225 | +6pp above breakeven |
| SO over 0.5 (hitter) | ✅ Yes | 73.7% | -207 | +7pp above breakeven |
| hits under 0.5 | ⚠️ Limited data | 66.7% (24 apps) | -127 | +11pp above breakeven |

**Removed props and why:**

| Prop | Reason Removed |
|---|---|
| totalBases under 1.5 | Flat signal — 57-63% win rate at ALL coverage levels |
| rbi under 0.5 | Flat signal — book prices edge away (-270 to -348) |
| Pitcher SO (all lines) | Coverage missing 55%+ of legs; win rates 30-52% |
| walks, homeRuns, stolenBases | Insufficient data / unprofitable |

---

### **2. Coverage Gating** ✅ TWO-GATE SYSTEM IN `_find_qualifying_legs()`

| Gate | Threshold | Applies To |
|---|---|---|
| Gate 1 | `coverage_overall >= 65%` | All props |
| Gate 2 | `coverage_overall >= 70%` | `hits under 0.5` only |
| Odds cap | `-250 to +150` | All props |

---

### **3. Parlay Construction** ✅ SINGLE FLAT POOL

| Parameter | Value |
|---|---|
| Pool floor | 65% `composite_score` |
| Odds range | -250 to +150 per leg |
| Legs per parlay | 4 |
| Target odds | +400 to +700 |
| Max legs per game | 2 |
| Player diversity | 1 player per parlay, 1 per batch |
| Builder | Branch-and-bound (`build_parlays()`) |

---

### **4. Scoring (simple_scorer.py)** ✅ PRODUCTION

Active signals:
- **Base:** `coverage_vs_hand` (preferred) or `coverage_overall`
- **Consistency:** gap-based ±6/±4/±2/+2/+1 (coverage_overall vs coverage_recent_10)
- **K9 matchup:** pitcher K/9 ±5 for SO over props (hitter only)
- **Lineup stability:** -5 if `lineup_consistency < 0.50`

Removed signals:
- Pitcher ERA block (was running for `hits/totalBases/rbi/runsScored` — dead for 100% of legs after prop whitelist)
- Pitcher K9 for pitcher positions (pitchers no longer in pool)

---

### **5. Shadow Enriched Pipeline** ✅ 3 SIGNALS ACTIVE

| Signal | Status | Applies To |
|---|---|---|
| Base + Consistency | ✅ | All props |
| 1: Blended ERA Rank | ✅ | `hits` props only |
| 2: Opponent Coverage Split | ✅ | All hitter props |
| 3: Ballpark Factor | ✅ | All hitter props |
| 4: Team SO Rank | ❌ REMOVED | Pitcher SO only — prop removed |

---

### **6. Outcome Resolution** ✅ FIXED

Key fix (June 1):
- EEP only fires when `plateAppearances` / `battersFaced` explicitly present in API response
- All 5 void paths write `void_reason` to `mlb_parlay_legs_v2`
- `game_not_found` defers parlay (sets `all_resolved = False`) instead of voiding leg

---

## Performance Metrics

### Pre-Refactor Baseline (May 26–31)
| Metric | Value |
|---|---|
| Parlay win rate | 7.9% production, 5.1% shadow |
| Primary loss drivers | totalBases under (36% win rate), SO over 4.5/5.5 (23-39%) |
| Coverage-to-win correlation | Flat at parlay level across all coverage buckets |

### New System Target (June 2026)
| Metric | Target | Basis |
|---|---|---|
| Per-leg win rate | 67-75% | 60-day validated coverage data |
| 4-leg parlay win probability | ~20-25% | 70% × 70% × 70% × 70% = 24% |
| Win rate at +400-+700 odds | Profitable above ~17% | Math: 17% × 500 - 83% × 100 = +2 |
| Parlays per day | 3-5 (weekday), 4-6 (weekend) | Pool size data |

---

## Pending Code Changes

| Item | File | Priority |
|---|---|---|
| Health check threshold update (63-72%) | `src/web/server.py` or health module | Medium |
| EV minimum gate for parlay selection | `main.py` `generate_recommendations()` | Discuss after data accumulates |
| `won_with_void` outcome tracking | `src/tracker/parlay_outcome_resolver.py` | Low |
| Dead ERA adjustment cleanup | `src/engine/simple_scorer.py` | Low |

---

**Build Status:** ✅ HEALTHY — Single Pool + Validated Props Live
**Last Deployment:** June 1, 2026 (Single flat pool, 4-leg +400-+700)
**Next Review:** June 2, 2026 (Morning resolution + first full-day output quality)
