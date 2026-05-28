"""
Simple coverage-based leg scorer using existing database fields.
No ML model required - uses contextual adjustments on validated coverage data.

Phase 1: Uses only data already in mlb_scored_legs table
- coverage_vs_hand (handedness-specific coverage)
- coverage_overall (fallback if no handedness data)
- coverage_recent_10 (hot/cold streaks)
- pitcher_era, pitcher_k9 (opponent quality)
- lineup_consistency (playing time stability, 0-1 scale)
"""

_PITCHER_POSITIONS = frozenset({"P", "SP", "RP", "TWP"})


def calculate_composite_score(leg):
    """
    Score = base_coverage + contextual adjustments.

    Args:
        leg (dict): Leg data with coverage and context fields.

    Returns:
        float: composite_score (5-95 range)
    """

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
    position  = leg.get("position", "")

    # For HITTER props: adjust based on opposing pitcher ERA
    if stat in ("hits", "totalBases", "rbi", "runsScored"):
        pitcher_era = leg.get("pitcher_era")
        if pitcher_era is not None:
            if pitcher_era > 5.0:   # Weak pitcher
                score += 5 if direction == "over" else -5
            elif pitcher_era < 3.0: # Ace pitcher
                score -= 5 if direction == "over" else -5

    # For STRIKEOUT props: K-rate matters
    if stat == "strikeouts":
        pitcher_k9 = leg.get("pitcher_k9")
        if pitcher_k9 is not None:
            if position in _PITCHER_POSITIONS and direction == "over":
                # Pitcher K over props
                if pitcher_k9 > 10.0:
                    score += 5
                elif pitcher_k9 < 7.0:
                    score -= 5
            elif position not in _PITCHER_POSITIONS:
                # Hitter strikeout props
                if pitcher_k9 > 10.0 and direction == "over":
                    score += 5   # High-K pitcher → hitter likely to K
                elif pitcher_k9 < 7.0 and direction == "over":
                    score -= 5   # Low-K pitcher → hitter unlikely to K

    # ============================================
    # 4. LINEUP STABILITY: Playing Time Risk
    # ============================================
    # lineup_consistency is on 0-1 scale (fraction of last 10 games with 3+ AB)
    lineup_consistency = leg.get("lineup_consistency")
    if lineup_consistency is not None and lineup_consistency < 0.50:
        score -= 5

    return max(5, min(95, score))


def score_legs(legs):
    """
    Score all legs using simple coverage + contextual adjustments.

    Args:
        legs (list): List of leg dictionaries with coverage and pitcher data

    Returns:
        list: Same legs with composite_score added (mutated in-place)
    """
    for leg in legs:
        base = (
            leg.get("coverage_vs_hand")
            or leg.get("coverage_overall")
            or leg.get("coverage_pct", 50)
        )
        score = calculate_composite_score(leg)
        leg["composite_score"] = score
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
