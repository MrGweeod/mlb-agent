"""
leg_scorer.py — Coverage-based composite scoring for qualifying MLB parlay legs.

Phase 2 formula — pure coverage signals, no penalty multipliers.

HITTER scoring (3 signals):
  coverage_overall   × 0.40   (full-season base rate)
  coverage_vs_hand   × 0.30   (handedness-adjusted rate)
  coverage_recent_10 × 0.30   (last-10-game trend)

  Weight redistribution when a signal is missing:
    vs_hand=None            → overall 0.70 / recent 0.30
    recent_10=None          → overall 0.55 / vs_hand 0.45
    both None               → overall 1.00

PITCHER scoring (2 signals):
  coverage_overall  × 0.60
  coverage_recent_4 × 0.40

  Weight redistribution:
    recent_4=None           → overall 1.00

All coverage values arrive as percentages (0–100) from calculate_coverage()
in main.py, so composite_score is already in [0, 100] without an extra ×100.

score_legs_composite() signature is unchanged so parlay_builder.py keeps working.
Phase 4 will add pitcher quality + opponent factors back in.
"""
from __future__ import annotations

# Pitcher-only prop stats (no batter game log)
_PITCHER_STATS = frozenset({"inningsPitched", "hitsAllowed", "earnedRuns"})


def _build_team_to_blocked(blocked_players: set[str], candidate_legs: list[dict]) -> dict[str, int]:
    """
    Return {team_abbr: blocked_player_count} from the candidate leg pool.

    Looks for blocked player names in the leg pool to infer team from the
    leg dict's 'team' field.
    """
    name_to_team: dict[str, str] = {}
    for leg in candidate_legs:
        name = leg.get("player_name", "")
        team = leg.get("team", "")
        if name and team:
            name_to_team[name] = team

    team_blocked: dict[str, int] = {}
    for name in blocked_players:
        team = name_to_team.get(name)
        if team:
            team_blocked[team] = team_blocked.get(team, 0) + 1

    return team_blocked


def _score_hitter_leg(leg: dict) -> float:
    """
    Composite score for a hitter prop using 3 coverage signals.

    Falls back to coverage_pct if the Phase 2 fields are missing
    (e.g. for legs logged before the Phase 1 refactor).
    """
    overall = leg.get("coverage_overall")
    vs_hand = leg.get("coverage_vs_hand")
    recent  = leg.get("coverage_recent_10")

    if overall is None:
        return round(leg.get("coverage_pct") or 0.0, 2)

    if vs_hand is not None and recent is not None:
        score = overall * 0.40 + vs_hand * 0.30 + recent * 0.30
    elif vs_hand is None and recent is not None:
        score = overall * 0.70 + recent * 0.30
    elif vs_hand is not None and recent is None:
        score = overall * 0.55 + vs_hand * 0.45
    else:
        score = overall

    return round(score, 2)


def _score_pitcher_leg(leg: dict) -> float:
    """
    Composite score for a pitcher prop using 2 coverage signals.

    Falls back to coverage_pct if the Phase 2 fields are missing.
    """
    overall = leg.get("coverage_overall")
    recent  = leg.get("coverage_recent_4")

    if overall is None:
        return round(leg.get("coverage_pct") or 0.0, 2)

    if recent is not None:
        score = overall * 0.60 + recent * 0.40
    else:
        score = overall

    return round(score, 2)


def score_leg(
    leg: dict,
    team_to_blocked: dict[str, int] | None = None,
    role: str = "swing",
) -> float:
    """
    Compute the composite score (0–100) for a single qualifying leg.

    Routes to _score_hitter_leg() or _score_pitcher_leg() based on
    position and stat type. The role and team_to_blocked parameters are
    accepted for API compatibility but not used in Phase 2 scoring.

    Returns:
        Float ∈ [0, 100].
    """
    position = leg.get("position", "")
    stat     = leg.get("stat", "")
    is_pitcher = (
        position in {"SP", "RP", "P", "TWP"}
        or stat in _PITCHER_STATS
    )

    if is_pitcher:
        return _score_pitcher_leg(leg)
    return _score_hitter_leg(leg)


def score_legs_composite(
    legs: list[dict],
    blocked_players: set[str] | None = None,
    team_to_blocked: dict[str, int] | None = None,
    role: str = "swing",
) -> list[dict]:
    """
    Attach composite_score to every leg in-place and return the list unchanged.

    Args:
        legs:            Qualifying legs entering the parlay builder.
        role:            Accepted for API compatibility; not used in Phase 2.
        team_to_blocked: Accepted for API compatibility; not used in Phase 2.
        blocked_players: Fallback to build team_to_blocked if needed.

    Returns:
        The same list with composite_score added to each leg dict.
    """
    if team_to_blocked is None and blocked_players:
        team_to_blocked = _build_team_to_blocked(blocked_players, legs)

    if team_to_blocked:
        print(f"  [leg_scorer] teammate injury context: {team_to_blocked}")

    for leg in legs:
        leg["composite_score"] = score_leg(leg, team_to_blocked, role=role)

    return legs
