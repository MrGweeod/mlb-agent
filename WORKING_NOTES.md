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

### Remaining unknowns for next session

- Are DK MLB props `available=true` when markets open (closer to game time)?
- Do MLB props on DK include alt lines (needed for swing leg diversity)?
- Does `home_probable_pitcher` (name string) need to be resolved to a pitcher ID
  before passing to `matchup.py`? (Yes — need a name→ID lookup in main.py)
- Does the Transaction Wire SC filter miss any IL-type moves that use a different typeCode?
