"""
Simple coverage-based leg scorer using existing database fields.
No ML model required - uses contextual adjustments on validated coverage data.

Validated prop scope: hits o/u 0.5, strikeouts o 0.5 (hitter only),
totalBases o/u 1.5 (over added 2026-08-05 — see scoring redesign notes below).

Signals:
- coverage_vs_hand (handedness-specific coverage)
- coverage_overall (fallback if no handedness data)
- coverage_recent_10 (hot/cold streaks)
- effective_era (for hits/over; exposure-weighted opposing-starter ERA — see
  src/pipelines/enrich_legs.py), pitcher_k9 (for hitter SO props)
- lineup_consistency (playing time stability, 0-1 scale)
- pt_tb_rate percentile rank within the day's pool, run through an empirical
  win-rate calibration (totalBases/over only — everything else above is
  bypassed for this stat/direction; see calculate_composite_score()'s early
  return and _TB_CAL_INTERCEPT/_TB_CAL_SLOPE below)

2026-08-05 scoring redesign confidence levels (see docs/ARCHITECTURE_DECISIONS.md
for the full evidence writeup):
  - hits/over effective_era: well-validated, two rounds of live-data testing
  - totalBases/over pt_tb_rate: real correlation found (r=0.121) but zero
    production track record — this is the first live scoring pass
  - strikeouts: no validated improvement exists; scoring unchanged deliberately

2026-08-06 totalBases/over calibration fix (v3): the original percentile
mapping scaled the day-pool percentile rank linearly onto a 5-95 composite_score
range, which implied a top-of-pool leg was ~95% likely to hit. Checked against
real outcomes (1,421 resolved totalBases/over legs from mlb_prop_legs_history,
joined to point-in-time pt_tb_rate via mlb_player_batting_cumulative, percentile-
ranked within each day's pool the same way the live scorer does) and the actual
win rate only ranges ~21% (bottom of pool) to ~39% (top of pool) — clearing 1.5
total bases is a structurally harder outcome than hits/strikeouts props, so it
should never have scored anywhere near their range. Fit via direct linear
regression of win/loss against day-pool percentile (leg-level, not bucket
means): win_prob = 0.2483 + 0.001523 * percentile, r=0.0944, n=1,421. This
score is now on the same units as coverage_overall (an actual historical win
rate, 0-100 scale) instead of an arbitrary within-pool rank — so totalBases/over
legs will correctly sit below hits/strikeouts most days rather than dominating
the top of a greedy composite_score sort purely because percentile ranking
manufactures high numbers at the top of any distribution by construction.
Investigated and ruled out (near-zero correlation, r<0.03 for all of: opposing
starter WHIP alone, opposing starter rolling IP/start alone, their interaction)
before landing on this fix — see chat 2026-08-06 for the full test.
"""

SCORER_VERSION = "v3_2026-08-06"

# Empirical win-rate calibration for totalBases/over, fit 2026-08-06 — see
# module docstring above for methodology and evidence. Score = intercept +
# slope * day-pool percentile (0-100), expressed on the same 0-100 scale as
# coverage_overall. Deliberately NOT re-fit inline from live data each run —
# this is a fixed, versioned constant so scorer_version stays a meaningful
# "which calibration produced this score" marker; re-fitting requires bumping
# SCORER_VERSION again, same discipline as every other signal in this file.
_TB_CAL_INTERCEPT = 24.83   # win rate (%) at the bottom of the day's pool
_TB_CAL_SLOPE = 0.1523      # additional win rate (%) per percentile point


def _attach_totalbases_over_percentiles(legs):
    """
    Compute each totalBases/over leg's percentile rank of pt_tb_rate within
    today's eligible pool and stash it as leg["tb_percentile_score"].

    Percentile 1 = lowest pt_tb_rate in the pool, 100 = highest. Legs missing
    pt_tb_rate (shouldn't happen — the Gate 1 qualification in main.py always
    sets it for this stat/direction) are left unset and fall back to the
    neutral default in calculate_composite_score().
    """
    pool = [
        l for l in legs
        if l.get("stat") == "totalBases" and l.get("direction") == "over"
        and l.get("pt_tb_rate") is not None
    ]
    if not pool:
        return
    pool.sort(key=lambda l: l["pt_tb_rate"])
    n = len(pool)
    for i, leg in enumerate(pool):
        leg["tb_percentile_score"] = round(((i + 1) / n) * 100.0, 1)


def calculate_composite_score(leg):
    """
    Score = base_coverage + contextual adjustments.

    Args:
        leg (dict): Leg data with coverage and context fields.

    Returns:
        float: composite_score (5-95 range)
    """

    # ============================================
    # 0. TOTALBASES/OVER: win-rate-calibrated percentile scoring (2026-08-06)
    # ============================================
    # No coverage_overall signal exists for this direction (see main.py Gate 1),
    # and testing found the hits/over exposure feature has no effect here
    # (deep 56.8% vs short 58.4%, flat/noisy) — so this bypasses every other
    # signal below and scores off pt_tb_rate's percentile rank within the
    # day's pool, set by _attach_totalbases_over_percentiles() in score_legs().
    # As of 2026-08-06 the raw percentile is run through an empirical win-rate
    # calibration (_TB_CAL_INTERCEPT/_TB_CAL_SLOPE, see module docstring) rather
    # than scaled linearly to a 5-95 range — the old version implied a top-of-
    # pool leg was ~95% likely to hit; real historical win rate for this stat
    # tops out around 39%. Clamp is defensive only; the fitted line stays
    # within [24.83, 40.06] for percentile in [0, 100] under normal operation.
    if leg.get("stat") == "totalBases" and leg.get("direction") == "over":
        percentile = leg.get("tb_percentile_score", 50)
        calibrated = _TB_CAL_INTERCEPT + _TB_CAL_SLOPE * percentile
        return round(max(5, min(95, calibrated)), 1)

    # ============================================
    # 1. PRIMARY SIGNAL: Handedness-Aware Coverage
    # ============================================
    if leg.get("coverage_vs_hand") is not None and leg.get("coverage_vs_hand") > 0:
        base_score = leg["coverage_vs_hand"]
        has_split = True
    elif leg.get("coverage_overall") is not None:
        base_score = leg["coverage_overall"]
        has_split = False
    else:
        base_score = leg.get("coverage_pct", 50)
        has_split = False

    score = base_score

    # ============================================
    # 2. CONSISTENCY SIGNAL: Trend vs Overall
    # ============================================
    recent_10 = leg.get("coverage_recent_10")
    coverage_overall = leg.get("coverage_overall")
    if recent_10 is not None and coverage_overall is not None:
        gap = coverage_overall - recent_10
        if gap >= 20:
            score -= 6    # severe cold streak (-5.7pp actual win rate drop)
        elif gap >= 12:
            score -= 4    # moderate cold streak (-4.6pp)
        elif gap >= 6:
            score -= 2    # mild cold streak (-2.8pp)
        elif gap <= -10:
            score += 2    # meaningfully hot (+1.9pp)
        elif gap <= -5:
            score += 1    # warm (+1.4pp)
        # else: neutral — no adjustment

    # ============================================
    # 3. PITCHER MATCHUP: Quality & Style
    # ============================================
    stat      = leg.get("stat", "")
    direction = leg.get("direction", "")

    # For hits props: adjust based on opposing pitcher ERA.
    # hits/over uses effective_era (exposure-weighted, 2026-08-05 — see
    # src/pipelines/enrich_legs.py) with a fallback to raw pitcher_era when no
    # rolling-IP data exists yet (e.g. season-opener). hits/under is unchanged —
    # the exposure fix was validated for overs only.
    if stat == "hits":
        if direction == "over":
            pitcher_era = leg.get("effective_era")
            if pitcher_era is None:
                pitcher_era = leg.get("pitcher_era")
        else:
            pitcher_era = leg.get("pitcher_era")
        if pitcher_era is not None:
            if pitcher_era > 5.0:   # Weak pitcher
                score += 5 if direction == "over" else -5
            elif pitcher_era < 3.0: # Ace pitcher
                score -= 5 if direction == "over" else -5

        # NOTE: WHIP rank signal removed Jun 25, 2026.
        # Data analysis (232 hits/over legs) showed the full-season WHIP rank
        # pool is contaminated by relievers — rank 161+ pitchers allowed
        # fewer actual hits (0.77 avg) than elite WHIP pitchers. The signal
        # was pushing legs with weak opposing pitchers into the 80+ composite
        # score bucket, which won at only 47.4% (20pp below 66.9% breakeven).
        # WHIP remains a component of pitcher_vulnerability in enriched_scorer.

    # For hitter strikeout props: K-rate matters
    if stat == "strikeouts" and direction == "over":
        k9_rank = leg.get("opp_pitcher_k9_rank")
        if k9_rank is not None:
            if k9_rank <= 8:    # elite K pitcher — batter more likely to K
                score += 5
            elif k9_rank >= 23: # weak K pitcher — batter less likely to K
                score -= 5
        else:
            # fallback to raw k9 if rank not available
            pitcher_k9 = leg.get("pitcher_k9")
            if pitcher_k9 is not None:
                if pitcher_k9 > 10.0:
                    score += 5
                elif pitcher_k9 < 7.0:
                    score -= 5

    # ============================================
    # 4. LINEUP STABILITY: Playing Time Risk
    # ============================================
    # lineup_consistency is on 0-1 scale (fraction of last 10 games with 3+ AB)
    lineup_consistency = leg.get("lineup_consistency")
    if lineup_consistency is not None and lineup_consistency < 0.50:
        score -= 5

    # ============================================
    # 5. BATTING ORDER SLOT: removed Jul 2, 2026
    # ============================================
    # The -8 slot-gate penalty (hits/over: slots 6-9; SO/over: slots 7-9) was
    # removed after a 7-day data review (Jun 24–Jul 1, 2026, mlb_scored_legs)
    # showed the hypothesis is empirically inverted:
    #   hits/over:         slots 1-5 (protected) = 60.0% WR (n=205)
    #                      slots 6-9 (penalized)  = 63.3% WR (n=30)
    #   strikeouts/over:   slots 1-6 (protected)  = 67.8% WR (n=87)
    #                      slots 7-9 (penalized)   = 73.7% WR (n=19)
    # Three more weeks of data confirmed the Jun 12 ARCHITECTURE_DECISIONS.md
    # Lesson 32 contradiction.  Going neutral — no adjustment in either direction.
    # batting_order and lineup_check_status remain annotated/logged; only the
    # scoring consequence is removed.

    return max(5, min(95, score))


def score_legs(legs):
    """
    Score all legs using simple coverage + contextual adjustments.

    Args:
        legs (list): List of leg dictionaries with coverage and pitcher data

    Returns:
        list: Same legs with composite_score added (mutated in-place)
    """
    _attach_totalbases_over_percentiles(legs)

    for leg in legs:
        base = (
            leg.get("coverage_vs_hand")
            or leg.get("coverage_overall")
            or leg.get("coverage_pct", 50)
        )
        score = calculate_composite_score(leg)
        leg["composite_score"] = score
        leg["scorer_version"] = SCORER_VERSION
        leg["score_breakdown"] = {
            "base_coverage": base,
            "final_score": score,
            "used_split": leg.get("coverage_vs_hand") is not None and leg.get("coverage_vs_hand") > 0,
        }

    if legs:
        scores = [l["composite_score"] for l in legs]
        print(
            f"[simple_scorer] Scored {len(legs)} legs | "
            f"avg={sum(scores)/len(scores):.1f} | "
            f"min={min(scores):.1f} | max={max(scores):.1f}"
        )

    return legs
