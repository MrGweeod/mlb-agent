# Coverage Threshold vs. Matchup Quality — Analysis (2026-07-30)

**Scope:** Read-only analysis. No changes made to `simple_scorer.py`, `parlay_builder.py`,
`_filter_legs()`, or any other production/shadow scoring code. This document is a
recommendation for the operator to act on — not an implemented change.

**Question being answered:** Does opposing-pitcher matchup quality (`opp_pt_era`,
`opp_pt_whip`, `opp_pt_k9`) change a leg's win probability independent of — or in
interaction with — the player's own coverage/consistency signal? Specifically: is
there a real quadrant where LOW coverage + GOOD matchup beats HIGH coverage + BAD
matchup, such that the current `composite_score >= 65` gate (coverage-heavy, matchup
as only a ±5 rank adjustment — see `calculate_composite_score()` in `simple_scorer.py`)
might be discarding +EV legs?

---

## 0. Two methodological findings that govern how to read everything below

These were discovered while reproducing the baseline population and must be read
before any table in this document, or the numbers will be misinterpreted.

### 0.1 `coverage_overall` has a hard floor by construction — "low coverage" barely exists for hits/over and batter-K

`main.py`'s `_find_qualifying_legs()` (the Step-4 "Coverage Gate", `POOL_MIN_COVERAGE
= 65.0`) rejects any **over**-direction leg with `coverage_overall < 65.0` *before it
is ever scored or logged* — hits/under and totalBases/under get a separate, lower
40.0 floor (`main.py` lines 350–368). Confirmed directly against the live table:

| Bet type | `coverage_overall` range in `mlb_training_data` (no other filter) |
|---|---|
| hits/over | 65.0 – 80.2 (min is *exactly* 65.0 across 10,940 rows — zero rows below) |
| totalBases (under-only, per current `ALLOWED_PROPS`) | 40.0 – 86.4 |
| strikeouts (batter, over-only) | 65.0 – 86.6 |
| strikeouts (pitcher) | `coverage_overall` is never populated for pitcher-role legs at all |

**Consequence:** for hits/over and batter-K, "low coverage" in this dataset never
means what it sounds like — it means "just above the 65% gate," not "a genuinely
low-consistency player." The operator's question (does a *truly* low-coverage,
good-matchup leg beat a high-coverage, bad-matchup one) **cannot be fully answered
for these two bet types from this table** — the low end of the real range was never
logged. **totalBases is the only bet type with a real, wide coverage range**, and is
therefore the most trustworthy evidence for the operator's actual question. This is
a stronger version of the range-restriction risk the handoff flagged for
`composite_score` — it turns out the raw `coverage_overall` signal itself is also
gated, upstream of scoring, not just the downstream `composite_score >= 65` pool
filter.

### 0.2 `coverage_overall`/`composite_score` reflect two different eras — analysis restricted to the post-6/9 regime

`coverage_overall` is `NULL` for every row before **2026-06-09** (8,657 of 105,728
rows have it populated; the rest predate the current `calculate_coverage()`/
`calculate_composite_score()` pipeline — confirmed via `composite_score` ranging as
low as 1.36 pre-June, impossible under the current formula's `max(5, base_coverage
+ adjustments)` given a 65+ base floor). Mixing eras would compare two different,
non-commensurable scoring systems as if they were one signal. **Every table below is
therefore restricted to `coverage_overall IS NOT NULL` (2026-06-09 onward)** —
sample sizes are smaller than the handoff's baseline table as a result, but the
population is internally consistent.

One consequence of this restriction: **pitcher-strikeout (K9) legs have zero rows in
the post-6/9 regime.** `main.py`'s `ALLOWED_PROPS` whitelist confirms pitcher SO was
removed from the pipeline entirely (`# hitter K only — pitcher SO removed`); all 613
baseline rows are historical (2026-04-05 – 2026-06-01), pre-dating the current
scorer, and this prop type is no longer bet on in production. It's analyzed below
on its own (pre-cutover) terms with that caveat attached, and — because
`opp_pt_games`/`opp_pt_era` etc. are never populated for pitcher-role legs at
all (no "opposing pitcher" concept for a leg facing an entire lineup, confirmed
zero matches) — **it has no opposing-matchup metric and cannot support Steps 2–3
at all.**

**Filters reproduced and confirmed exact-match to the handoff's baseline table**
(n and win% both matched to the decimal before applying the above restriction):
hits/over `stat='hits' AND direction='over' AND pt_role='batter'`; totalBases
`stat='totalBases' AND pt_role='batter'` (both directions); batter-K
`stat='strikeouts' AND pt_role='batter'` (100% direction='over' in this table);
pitcher-K9 `stat='strikeouts' AND pt_role='pitcher' AND pt_games>=5` (this bet type's
floor is 5, not 10 — the only one that reproduced n=613 exactly). All four use
`pt_games>=10`/`opp_pt_games>=3` (except pitcher-K9) and `result IN ('hit','miss')`.

**Post-restriction sample sizes** (all analysis below uses these):

| Bet type | n | Win rate | Coverage range |
|---|---|---|---|
| hits/over | 1,559 | 62.5% | 65.0 – 80.2 |
| totalBases (under) | 4,469 | 58.1% | 40.0 – 86.4 |
| strikeouts (batter) | 701 | 62.6% | 65.0 – 86.6 |
| strikeouts (pitcher) | 613 (pre-6/9, discontinued prop) | 51.4% | n/a |

Win rates jumping from the baseline's 50–53% to 58–63% once restricted to the
current-pipeline regime is itself notable (current pipeline outperforming the
season's earlier eras) but is a side observation, not the subject of this analysis.

---

## 1. Step 1 — 2D banded grid (coverage × matchup, win rate + EV/$1)

Coverage bucketed into quintiles (`NTILE(5)`, both `coverage_overall` and
`composite_score` reported). Matchup metric bucketed into quintiles, **band 1 =
conventionally favorable for the bettor's side** (highest `opp_pt_era` for
hits/over batter-K uses `opp_pt_k9`; totalBases uses a direction-signed ERA since
the table mixes... actually totalBases in the current regime is 100% `under`, so
signed = plain `opp_pt_era` ascending = band1 lowest ERA = best pitcher = favorable
for an *under* bet). EV/$1 = realized profit using each leg's own actual resolved
odds (`AVG(hit ? decimal_odds-1 : -1)`), not an assumed flat price. **Cells with
n<50 are flagged — do not read a trend into them.**

### 1a. hits/over (n=1,559) — banded by `coverage_overall`

Cell counts run 53–74 (average ~62/cell) — **borderline, treat single-cell EV
numbers as noisy, not as clean signal.**

| cov band (range) \ matchup band → | 1 (ERA 4.7–15.2, weak P) | 2 | 3 | 4 | 5 (ERA 0.7–2.8, ace) |
|---|---|---|---|---|---|
| 1 (65.0–65.8) | n=69, 55.1%, EV **−0.192** | n=65, 72.3%, EV +0.083 | n=55, 60.0%, EV −0.104 | n=70, 70.0%, EV +0.048 | n=53, 60.4%, EV −0.080 |
| 2 (65.9–67.0) | n=55, 54.5%, EV −0.206 | n=61, 63.9%, EV −0.055 | n=67, 62.7%, EV −0.066 | n=71, 63.4%, EV −0.052 | n=58, 58.6%, EV −0.122 |
| 3 (67.0–68.7) | n=64, 62.5%, EV −0.096 | n=62, 67.7%, EV +0.002 | n=73, 68.5%, EV +0.006 | n=55, 70.9%, EV +0.053 | n=58, 48.3%, EV **−0.269** |
| 4 (68.7–71.3) | n=66, 68.2%, EV −0.007 | n=66, 63.6%, EV −0.083 | n=53, 60.4%, EV −0.101 | n=59, 45.8%, EV **−0.323** | n=68, 64.7%, EV −0.040 |
| 5 (71.3–80.2) | n=58, 53.4%, EV −0.231 | n=58, 55.2%, EV −0.194 | n=64, 75.0%, EV +0.107 | n=57, 68.4%, EV 0.000 | n=74, 63.5%, EV −0.062 |

**Reading it:** no clean monotonic pattern in either direction — matchup band 1
(conventionally "favorable," weak opposing pitcher) does **not** consistently
outperform band 5 (ace) at any coverage level; several cells show the opposite
of the conventional-wisdom direction (e.g., cov band 3: band 1 at 62.5% but band
5 at only 48.3%). This echoes the Session 21 finding that the ERA-based adjustment
in `simple_scorer.py` is directionally unreliable — now confirmed on the newer,
point-in-time `opp_pt_era` metric too, not just the season-aggregate `pitcher_era`
Session 21 tested.

*(composite_score-banded version of this same grid, and the full totalBases/
batter-K/pitcher-K9 grids, are in the raw query output retained with this
analysis; the quadrant extremes relevant to the operator's question are pulled
out explicitly in §3 below rather than repeating all 100+ cells here.)*

### 1b. totalBases/under (n=4,469) — the widest real coverage range, most trustworthy bet type for this question

Deciles used (n≈35–65/cell, healthier than hits/over). Full range 40.0–86.4.
Selected deciles (1=lowest coverage, 10=highest; matchup decile 1=best pitcher/
lowest ERA=favorable for under, decile 10=worst pitcher/highest ERA=unfavorable):

| cov decile (coverage range) | matchup=1 (best P) | matchup=10 (worst P) |
|---|---|---|
| 1 (40.0–54.8) | n=56, 55.7%(quintile)/60.7%(decile),¹ EV +0.01 to −0.07 | n=52, 59.0%(quintile)/65.4%(decile), EV +0.03 to +0.17 |
| 10 (66.7–86.4) | n=29, 48.3%, EV **−0.264** | n=65, 49.2%, EV **−0.199** |

¹ Quintile-band cell (§1, five bands) and decile-band cell (used for quadrants,
§3) differ slightly in boundary — both cited since the grid was built at
quintile resolution and the quadrant extremes at decile resolution; the
direction and magnitude of the finding is the same either way.

**Reading it:** the entire high-coverage row (decile 10, coverage 66.7–86.4)
underperforms the entire low-coverage row (decile 1, coverage 40.0–54.8) —
regardless of matchup quality. This is the opposite of what the current
coverage-heavy gate assumes. See §3 for the full quadrant table with EV.

### 1c. strikeouts (batter, n=701) — thinnest sample, most cells flagged

25 cells at n≈18–40 each — **every single cell is under the reliable-n<50
threshold; treat this entire grid as directional, not conclusive.**

| cov band \ matchup band (opp K9, 1=elite-K best-for-over, 5=weak-K) | 1 | 5 |
|---|---|---|
| 1 (65.0–66.2) | n=32, 75.0%, EV +0.105 | n=24, 37.5%, EV **−0.399** |
| 5 (72.0–86.6) | n=23, 52.2%(cov)/53.4%(shown earlier), EV −0.237 | n=74→40(decile), 65.0%, EV −0.054 |

**Reading it:** the widest single spread in the whole analysis (75.0% vs 37.5%
within the same low-coverage row, just changing matchup) — but n=32/n=24 means
this is exactly the kind of thin cell the handoff says not to draw conclusions
from. Directionally interesting, not proof.

### 1d. strikeouts (pitcher, n=613, pre-6/9 discontinued prop) — coverage axis only, no matchup metric exists

| composite_score band | n | win% | EV/$1 |
|---|---|---|---|
| 1 (0.1–20.9) | 93 | 48.4% | −0.113 |
| 2 (20.9–40.0) | 93 | 54.8% | +0.010 |
| 3 (40.0–62.5) | 93 | 52.7% | −0.045 |
| 4 (62.5–70.0) | 92 | 48.9% | −0.111 |
| 5 (70.0–95.0) | 92 | 54.3% | −0.010 |

Flat, non-monotonic, no signal — consistent with the baseline's 0.008 correlation.
No opposing-matchup metric exists for this bet type (by design — a pitcher faces
a lineup, not one opposing pitcher), so **Steps 2 and 3 do not apply to it at all.**

---

## 2. Step 2 — Grouped logistic regression with interaction term

**Methodology note (disclosed up front):** row-level export from the live
Supabase table into a local modeling environment wasn't feasible through the
available tooling (no local `DATABASE_URL` — Supabase access is via an MCP
connection that returns query results inline; exporting 1,500–4,500 raw rows
per bet type would be several hundred thousand tokens of context). Instead,
each bet type was aggregated into a 10×10 (5×5 for the thinner batter-K set)
decile grid of coverage × matchup with per-cell hit-counts and covariate means,
and fit as a **grouped logistic regression** (`statsmodels` `GLM(family=Binomial())`,
response = (hits, misses) per cell) — a standard, legitimate technique for
binomial count data, though it approximates each continuous predictor by its
cell mean rather than using the true row-level value. `statsmodels` and `pandas`
were not previously installed locally (confirmed via `pip list` before assuming);
installed for this analysis. All covariates standardized (mean 0, SD 1) so
coefficients are comparable across predictors.

Model: `result ~ coverage_and/or_composite + matchup_metric + own_stat_metric +
coverage:matchup interaction`. Predicted probabilities shown at ±1 SD combinations
(i.e., "low"/"high" = 1 SD below/above the *in-sample* mean — remember §0.1: even
"low" coverage here is still ≥65% for hits/over and batter-K).

| Bet type | Coverage proxy | Interaction coef (p-value) | Significant? | low-cov+good-match P(hit) | high-cov+good-match P(hit) |
|---|---|---|---|---|---|
| hits/over | `coverage_overall` | −0.015 (p=0.765) | No | 0.613 | 0.633 |
| hits/over | `composite_score` | **−0.105 (p=0.037)** | **Yes** | **0.690** | 0.617 |
| totalBases | `coverage_overall` | +0.023 (p=0.451) | No | 0.605 | 0.585 |
| totalBases | `composite_score` | +0.022 (p=0.475) | No | 0.593 | 0.596 |
| strikeouts (batter) | `coverage_overall` | **−0.183 (p=0.025)** | **Yes** | **0.679** | 0.611 |
| strikeouts (batter) | `composite_score` | **−0.181 (p=0.039)** | **Yes** | 0.657 | **0.644** |

**No individual main-effect coefficient (coverage, composite_score, own-stat
metric, or the matchup metric alone) reached significance in any of the six
fits** — only the interaction term did, and only in 3 of 6. Read plainly:

- **hits/over, totalBases via `coverage_overall`:** no significant interaction.
  The raw coverage signal (the purest test, unaffected by composite_score's own
  built-in matchup adjustment) shows **no evidence** that matchup quality changes
  how much coverage matters for these two bet types.
- **hits/over via `composite_score`:** significant negative interaction — as
  composite_score rises, the benefit of a good matchup shrinks. Predicted P(hit)
  is actually *highest* at low-composite + good-matchup (0.690) among the four
  extreme combinations. Caveat: `composite_score` already bakes in a small
  ERA-based adjustment (see `calculate_composite_score()`), so this isn't fully
  independent of the matchup term — some of the "interaction" may just be
  `composite_score` partially double-counting `opp_pt_era`.
- **strikeouts (batter):** significant negative interaction in *both* coverage
  proxies, and the largest interaction coefficient magnitude of any bet type
  (−0.18 to −0.19) — but this is also the thinnest dataset (n=701, 5×5=25 cells,
  every Step-1 cell flagged n<50). Directionally the most supportive of the
  operator's hypothesis, least statistically trustworthy on sample size grounds.

---

## 3. Step 3 — Direct quadrant comparison (Q3 vs. Q2, the operator's exact question)

Quadrants built from each bet type's two most extreme coverage/matchup bands
(§1's quintile bands for hits/over and batter-K; deciles for totalBases, which
has the range to support a finer split). EV/$1 uses realized odds.

| Bet type | Q1: High cov + Good match | Q2: High cov + Bad match | Q3: Low cov + Good match | Q4: Low cov + Bad match | **Q3 vs Q2** |
|---|---|---|---|---|---|
| hits/over | n=58, 53.4%, EV −0.231 | n=74, 63.5%, EV −0.062 | n=69, 55.1%, EV −0.192 | n=53, 60.4%, EV −0.080 | **Q3 (55.1%) < Q2 (63.5%), by −8.4pp — does NOT support the hypothesis** |
| totalBases | n=29, 48.3%, EV −0.264 | n=65, 49.2%, EV −0.199 | n=56, 60.7%, EV +0.012 | n=52, 65.4%, EV +0.168 | **Q3 (60.7%) > Q2 (49.2%), by +11.5pp, EV +0.012 vs −0.199 — SUPPORTS the hypothesis, on adequate n (56 vs 65)** |
| strikeouts (batter) | n=23, 52.2%, EV −0.237 | n=40, 65.0%, EV −0.054 | n=32, 75.0%, EV +0.105 | n=23, 39.1%, EV −0.373 | **Q3 (75.0%) > Q2 (65.0%), by +10.0pp, EV +0.105 vs −0.054 — supports the hypothesis, but n=32/23 is thin (flag per project convention)** |
| strikeouts (pitcher) | n/a — no opposing-matchup metric exists for this bet type | | | | **not applicable** |

**Direct answer to "is Q3 > Q2":** **Mixed, and bet-type-dependent — not a uniform
yes.** It clearly holds for **totalBases** (the one bet type where "low coverage"
is a genuine, wide range rather than a compressed 65–80 band, and on adequate
sample size both sides). It also holds directionally for **batter strikeouts**,
but on a sample too thin to trust per this project's own n<50 standard applied to
three of its four cells. It **does not hold for hits/over** — there, high coverage
+ bad matchup actually beats low coverage + good matchup by 8.4 points, the
opposite of the hypothesis.

---

## 4. Recommendation

**The evidence does not support a blanket claim that "matchup quality matters more
than coverage."** It supports something narrower and more actionable:

1. **Do not raise the coverage floor or add a matchup-weighted alternate gate for
   hits/over on this evidence.** Both the `coverage_overall`-based interaction
   (p=0.765) and the direct Q3-vs-Q2 comparison (Q3 loses by 8.4pp) argue against
   it for this specific bet type.

2. **totalBases is the one bet type where this analysis found a real, adequately-
   powered effect in the operator's hypothesized direction** — low coverage (a
   genuine 40–55% range here, not a compressed near-65 band) with a good matchup
   outperformed high coverage with a bad matchup by 11.5 points of win rate and by
   roughly $0.21/$1 of EV. Caveat: totalBases is currently shadow-only (excluded
   from live parlays per `main.py`'s `production_legs` filter) — this finding is
   about a bet type not currently live, not immediately actionable for production
   without first deciding whether to promote totalBases to production at all (a
   separate decision).

3. **The batter-strikeout interaction is the largest in magnitude and significant
   in both coverage proxies, but on a genuinely thin dataset** (n=701 total, every
   quintile cell under the project's own n<50 reliability bar in at least one
   corner). Worth re-testing once more of this season's `mlb_training_data` accrues
   under the current (post-6/9) pipeline — not a basis for a gate change today.

4. **The deeper, more urgent finding is methodological, not about matchup weight
   at all:** `coverage_overall` is hard-floored at 65% (over) / 40% (under) by
   `main.py`'s Gate 1, *before* any leg is scored or logged — meaning
   `mlb_training_data` structurally cannot answer "does a truly low-coverage leg
   with a great matchup ever beat a high-coverage leg" for hits/over or batter-K,
   because those low-coverage legs are never captured in the first place. If the
   operator wants a real answer for those two bet types (not just totalBases),
   that requires either (a) prospectively logging a sample of sub-65%-coverage
   legs going forward (a Gate-1 scope change, out of scope for this task and a
   real cost/quality tradeoff to weigh separately), or (b) building a coverage
   computation against `mlb_prop_legs_history` (Session 23's ungated full-line
   capture table), which was NOT attempted here — it has no `coverage_overall`/
   `composite_score` columns at all and would need those computed retroactively,
   a meaningfully larger follow-up task.

5. **Do not trust the original baseline correlations (0.00–0.08) as clean evidence
   the whole system is signal-free** — they mixed two different scoring-pipeline
   eras (pre- and post-6/9) that are not comparable on the same scale. The
   restricted, single-era reanalysis here shows meaningfully higher win rates
   (58–63% vs. the baseline's 50–53%) — the current pipeline is doing more than
   the raw correlations suggested, even though the coverage-vs-matchup interaction
   specifically remains weak-to-mixed.

**Bottom line for the operator's stated worry** ("is the coverage threshold hurting
us"): on hits/over specifically — the bet type the current gate exists to protect —
this data does not show that. On totalBases, it does, on a bet type not currently
live. The honest overall answer is **partially yes, bet-type-specific, and the
biggest blocker to a fuller answer is a data-collection gap (§0.1), not a modeling
gap.**
