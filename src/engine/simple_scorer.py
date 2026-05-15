"""
Simple, transparent leg scoring based on coverage and pitcher matchup quality.
No ML model. No adjustments. Just math.
"""


def calculate_composite_score(leg):
    """
    Score = coverage_overall + pitcher_matchup_adjustment

    Args:
        leg (dict): Must contain:
            - coverage_overall (float): 0-100, % times player goes over/under
            - direction (str): 'over' or 'under'
            - pitcher_era (float, optional): Opposing pitcher's ERA
            - stat (str): 'hits', 'strikeouts', etc.

    Returns:
        float: composite_score (5-95 range)
    """
    # Base score is just coverage
    base_score = leg.get("coverage_overall", 0)

    # Pitcher quality adjustment (if available)
    pitcher_adjustment = 0
    pitcher_era = leg.get("pitcher_era")

    if pitcher_era is not None and leg.get("stat") in ["hits", "totalBases", "rbi"]:
        direction = leg.get("direction", "").lower()

        if direction == "under":
            # UNDER props benefit from elite pitchers
            if pitcher_era < 3.0:
                pitcher_adjustment = 15
            elif pitcher_era < 3.5:
                pitcher_adjustment = 10
            elif pitcher_era < 4.0:
                pitcher_adjustment = 5
            elif pitcher_era > 5.0:
                pitcher_adjustment = -10  # Weak pitcher = avoid under

        elif direction == "over":
            # OVER props benefit from weak pitchers
            if pitcher_era > 5.0:
                pitcher_adjustment = 10
            elif pitcher_era > 4.5:
                pitcher_adjustment = 5
            elif pitcher_era < 3.0:
                pitcher_adjustment = -10  # Elite pitcher = avoid over

    # Calculate final score
    composite_score = base_score + pitcher_adjustment

    # Keep within bounds (5-95)
    composite_score = max(5, min(95, composite_score))

    return composite_score


def score_legs(legs):
    """
    Score all legs using simple coverage + pitcher adjustment.

    Args:
        legs (list): List of leg dictionaries with coverage and pitcher data

    Returns:
        list: Same legs with composite_score added
    """
    scored = []

    for leg in legs:
        # Calculate score
        score = calculate_composite_score(leg)

        # Add to leg
        leg["composite_score"] = score

        # Add scoring breakdown for transparency
        leg["score_breakdown"] = {
            "base_coverage": leg.get("coverage_overall", 0),
            "pitcher_adjustment": score - leg.get("coverage_overall", 0),
            "final_score": score,
        }

        scored.append(leg)

    if scored:
        print(
            f"[simple_scorer] Scored {len(scored)} legs | "
            f"avg score: {sum(l['composite_score'] for l in scored) / len(scored):.1f}"
        )

    return scored
