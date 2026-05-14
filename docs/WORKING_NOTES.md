# Working Notes — MLB Parlay Agent

Scratchpad for in-session findings. Not authoritative — see SESSION_HANDOFF.md for
decisions that carry forward.

---

## 2026-04-16 — Feed Validation Session

Ran `validate_feeds.py` against all live data sources. All 6 tests passed.

### Test 1 — Schedule (PASS)

- 10 games today (Tier 1 slate — full schedule)
- All required fields present: `game_id`, `away_name`, `home_name`, `away_id`, `home_id`,
  `home_probable_pitcher`, `away_probable_pitcher`, `status`
- `home_probable_pitcher` / `away_probable_pitcher` return **name strings** (e.g., `"Braxton Ashcraft"`),
  not pitcher IDs — `main.py` will need to resolve names → IDs via `get_player_info()` or
  the `matchup.py` pitcher lookup flow
- First game: Washington Nationals @ Pittsburgh Pirates, `game_id=823396`, status=`"Pre-Game"`

### Test 2 — Batter Game Log (PASS)

- **Player ID correction**: `660670` = Ronald Acuña Jr. (not Juan Soto as spec'd)
  Soto's correct ID = `665742`
- 19 game log entries returned for Acuña (2026 season, as of April 16)
- All required stat fields confirmed in `entry["stat"]`:
  `hits`, `totalBases`, `rbi`, `homeRuns`, `atBats`, `baseOnBalls`, `stolenBases`, `runs`
- `date` field confirmed at top level (e.g., `"2026-03-27"`)
- Stat access path validated: `entry.get("stat", {}).get("hits")` — exactly what `coverage.py` uses
- Entries are oldest-first (2026-03-27 first) — consistent with design notes

### Test 3 — Pitcher Hand (PASS)

- Wheeler (554430) → `'R'` ✓
- Kershaw (477132) → `'L'` ✓
- API path confirmed: `people/{id}` → `pitchHand.code`

### Test 4 — Handedness Split Endpoint (PASS)

Full confirmed path: `stats[0]["splits"][0]["stat"]`

Sample (Acuña vs RHP, 2026):
- `gamesPlayed`: 18
- `hits`: 12
- `totalBases`: 17
- `atBats`: 51, `baseOnBalls`: 7, `homeRuns`: 1

Fields NOT present in statSplits (confirming design notes):
- `stolenBases` — absent → always uses gameLog fallback
- `runs` — absent → always uses gameLog fallback

Only 1 split returned for `sitCodes=vr` (vs Right-handed pitchers) — a single aggregate
row, not per-game. Poisson approximation is the right model for this.

### Test 5 — Transaction Wire (PASS with caveats)

**813 transactions** returned for today. The `toTeam.sport.id in (1, None)` filter in
`get_transactions()` passes through foreign-league entries because their `toTeam` is
absent (None evaluates as "include"). Almost all 813 are:
- `typeCode='NUM'` — uniform number changes (Dodgers, Padres, Angels, etc. roster updates)
- `typeCode='SFA'` — free agent signings to Mexican League clubs
- `typeCode='ASG'` — minor-league assignments

Only notable MLB-level transactions today:
- `typeCode='DES'`: Atlanta Braves DFA'd RHP Osvaldo Bido
- `typeCode='ASG'`: Spencer Strider sent on rehab assignment to Rome Emperors

0 IL placements or reinstatements (typeCode=SC with "placed"/"reinstated") today.
The `is_il_placement()` / `is_il_reinstatement()` functions work correctly on the SC
entries — the noise problem is pre-filter volume, not detection logic.

**Fix needed in main.py**: Before printing/logging transactions, pre-filter to:
```python
relevant_types = {"SC", "DES", "CU", "OU"}
txns = [t for t in get_transactions(date) if t.get("typeCode") in relevant_types]
```
This reduces 813 to a manageable subset of MLB-relevant moves.

### Test 6 — SGO MLB Props (PASS)

**Key findings for pipeline:**

1. **`fairOverUnder` is populated** — 20/20 in first 20 player props. EV factor uses
   full 25% weight. The field is `prop.get("fairOverUnder")`, not `prop.get("fairOdds")`.

2. **No `overOdds`/`underOdds`** — DK sub-object uses a single `odds` field.
   `prop["byBookmaker"]["draftkings"]["odds"]` = the American odds for the over side
   (or under side, depending on which key you're iterating).

3. **`statID`** = prop category field. Examples seen:
   - `"batting_hits+runs+rbi"` (combination prop)
   - Format: `"{group}_{stat1}+{stat2}+..."` or `"{group}_{stat}"`

4. **DK `available=false`** on all tested props — markets likely post 1–2 hours before
   first pitch. Tests were run ~11AM ET; first game is 4:35PM ET. Re-check closer to
   game time to confirm alt lines and availability.

5. **Alt lines**: 0 on the first prop tested (DK unavailable). Cannot confirm whether
   MLB props have alt lines until markets open.

6. **Combination props** (hits+runs+rbi) appear in the odds dict — `get_player_props()`
   will try to parse `statID="batting_hits+runs+rbi"`. Check if `PROP_STATS` in
   `sportsgameodds.py` covers these or if they fall through silently.

7. **`bookOdds` / `fairOdds`** also exist at the top-level market dict (string format
   like `"+134"`). These are consensus across all bookmakers, not DK-specific.

### Remaining unknowns resolved in 2026-04-17 session

- `home_probable_pitcher` name→ID resolution: handled in `main.py` via `statsapi.lookup_player()` ✓
- Transaction Wire pre-filter: implemented in `main.py _get_blocked_players()` using `_RELEVANT_TXNS = {"SC", "DES", "OU", "CU"}` ✓

### Still open

- Are DK MLB props `available=true` when markets open (closer to game time)?
- Do MLB props on DK include alt lines (needed for swing leg diversity)?
- Does the Transaction Wire SC filter miss any IL-type moves that use a different typeCode?

---

## 2026-04-17 — Phase 3 Complete (main.py)

### What was built

Confirmed all Phase 2 files were already committed (trend_analysis, matchup, enrich_legs,
leg_scorer, rotowire, lineup_poller, web/server). The only missing piece was `main.py`.

Wrote `main.py` — full 8-step pipeline orchestrator:

1. **Transaction Wire** — `_get_blocked_players()` pre-filters to SC/DES/OU/CU, detects IL placements
2. **Schedule + maps** — `_build_team_maps()` builds `pitcher_id_map` and `opponent_map`
   - `home_probable_pitcher` is a name string → resolved via `statsapi.lookup_player()`
   - `pitcher_id_map[home_abbr] = away_pitcher_id` (home batters face away pitcher)
3. **SGO props** — `get_todays_games()` + `get_player_props()` per game
4. **Coverage gate** — `_find_qualifying_legs()` calls `calculate_coverage()` at standard line only
   - Pitcher props skipped (`_PITCHER_POSITIONS = {"P", "SP", "RP", "TWP"}`)
   - Player team resolved via `get_player_info(mlb_id).team_id` → `team_id_to_abbr`
   - Min 55% coverage to enter pool
5. **Injury filter** — transaction wire blocked_names + `get_injured_players()` LLM spot-check
6. **Enrichment** — `enrich_legs(legs, pitcher_id_map, opponent_map, season)`
7. **Trend signals** — `_attach_trend_signals()` calls `get_trend_signal()` per leg; role from coverage_pct
8. **Parlay builder** — `build_hybrid_parlays()` → `log_recommendations()` + `log_scored_legs()` → `analyze_parlays()`

### Import smoke test passed

```
python -c "import main; print('import OK')"           → import OK
python -c "from src.bot.runner import pipeline_run"   → import OK
```

---

## 2026-04-17 — Live Pipeline Fixes

First live `main.py` run revealed several bugs, all fixed in this session:

| Bug | Root cause | Fix |
|-----|-----------|-----|
| `statsapi.teams()` AttributeError | `statsapi` has no `teams()` method | `statsapi.get("teams", {"sportId": 1}).get("teams", [])` |
| 0 SGO props returned | `_SGO_STAT_ID_MAP` used `hitting_` prefix; API uses `batting_` | Renamed all keys to `batting_`, re-derived filter logic |
| `player_name` includes stat label | `marketName` = `"{Player} {Stat Label} Over/Under"` | Added `_STAT_NAME_SUFFIX` dict to strip labels |
| `enrich_legs.py:137` TypeError | `sorted(set)` with `None` in set | Filter: `sorted(pid for pid in unique_pitcher_ids if pid is not None)` |
| LLM injury check returning garbage | `get_injured_players()` hallucinating dates | Added digit/length guard; then removed LLM call entirely |
| `opposing_pitcher_id or 0` → 404 spam | Sending pitcher ID 0 to MLB Stats API | Changed to `opposing_pitcher_id or None` |
| `batting_hits+runs+rbi` combo props | Unmapped combination stat | Added `_BLOCKED_STAT_IDS` with silent skip |
| `mlb_scored_legs` missing columns | Table created before `game_pk`/`player_id`/`opposing_pitcher_id` added | `ALTER TABLE mlb_scored_legs ADD COLUMN IF NOT EXISTS ...` |

### 0 parlays root cause identified

With the two-pool architecture, positive-odds legs (coverage ~57–63%, odds +130 to +215)
were classified as swings, not anchors. The anchor pool had only 3 legs (all negative-money),
and the swing pool couldn't bridge them into the +1000–+1500 window. Fix applied next session.

---

## 2026-04-18 — Single Scored Pool Refactor

### What was changed

Replaced two-pool anchor/swing architecture with a single composite-scored pool.

**`src/engine/parlay_builder.py`** — full rewrite:
- Removed `_anchor_floor()`, anchor/connector/swing buckets, and three-phase B&B logic
- `_tier_params()` now returns only `{min_legs, max_legs, tier}` — no coverage floors or bucket params
- All legs with coverage ≥55% enter one pool; scored once by `score_legs_composite()`
- Top 20 by composite_score fed to B&B
- Single-phase B&B finds combinations of 4–8 legs (Tier 1/2) or 3–8 (Tier 3) in +600–+1500 odds window
- Constraints: max 1 batter leg per player (pitchers exempt), max 3 legs per game (`game_pk`)
- Parlays ranked by `avg_composite` DESC; diversity filter (≤3 shared legs) yields top 5

**`src/pipelines/trend_analysis.py`**:
- Removed `trend_pass` boolean gate entirely (from `_SAFE_DEFAULT`, computation block, result dict)
- `role` parameter retained in signature for backwards-compat but defaults to `"swing"` and is unused

**`main.py`**:
- `_attach_trend_signals()`: removed `role` assignment; no longer passes `role=` to `get_trend_signal()`
- Step 7 print: removed `trend_pass_count`; shows form label breakdown only

### Results on live slates

- 2026-04-17: 156 eligible legs → top 20 → **5 parlays** in +1447–+1491 range, B&B 49 iters
- 2026-04-18: 157 eligible legs → top 20 → **5 parlays** in +1441–+1482 range, B&B 78 iters

### Still open

- Pool diversity: all 5 parlays share same 2 anchor legs (Dingler RBI + Kim Walk on 04-18).
  Consider a per-leg appearance cap (e.g., max 3 of 5 parlays) to force variety.
- COLD legs now eligible (trend_pass removed). Consider soft COLD penalty in leg_scorer
  instead of a hard gate — a small composite_score deduction rather than disqualification.
- `get_batter_game_log(701678)` logs `list index out of range` — likely a non-MLB player
  ID leaking in from the SGO feed. Investigate and add a guard if recurrent.
