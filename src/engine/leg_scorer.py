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

PITCHER scoring (4 signals):
  coverage_overall   × 0.35
  coverage_recent_5  × 0.25
  pitcher_quality    × 0.20
  opponent_offense   × 0.20

  Weight redistribution when a signal is missing:
    pitcher_quality=None    → overall +0.10 / recent +0.10
    opponent_offense=None   → overall +0.10 / recent +0.10
    recent_5=None           → overall 1.00 (after other redistribution)

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


def _normalize_rank(rank: int, inverted: bool = False) -> float:
    """
    Convert a 1–30 rank to a [-1.0, 1.0] score.

    rank=1 (best) → +1.0, rank=15 (avg) → 0.0, rank=30 (worst) → -1.0.
    If inverted=True, flip the scale (rank=1 worst → -1.0, rank=30 best → +1.0).
    """
    # Linear interpolation: rank 1 → +1.0, rank 30 → -1.0
    score = 1.0 - (rank - 1) * (2.0 / 29.0)
    return -score if inverted else score


def _score_pitcher_leg(leg: dict) -> float:
    """
    Composite score for a pitcher prop using 4 signals:
      coverage_overall × 0.35, coverage_recent_5 × 0.25,
      pitcher_quality  × 0.20, opponent_offense  × 0.20.

    Falls back to coverage_pct if coverage_overall is missing.
    Missing rank signals redistribute weight to coverage signals.
    """
    overall = leg.get("coverage_overall")
    recent  = leg.get("coverage_recent_5")

    if overall is None:
        return round(leg.get("coverage_pct") or 0.0, 2)

    stat = leg.get("stat", "")

    # ── Pitcher quality signal ────────────────────────────────────────────────
    pitcher_quality: float | None = None
    if stat == "strikeouts":
        rank = leg.get("pitcher_k9_rank")
    elif stat == "hitsAllowed":
        rank = leg.get("pitcher_whip_rank")
    elif stat == "earnedRuns":
        rank = leg.get("pitcher_era_rank")
    else:
        rank = None

    if rank is not None:
        # Normalize rank to [-1, 1] then scale to [0, 100] around 50
        pitcher_quality = 50.0 + _normalize_rank(rank) * 50.0

    # ── Opponent offense signal ───────────────────────────────────────────────
    opponent_offense: float | None = None
    if stat == "strikeouts":
        opp_rank = leg.get("opponent_k_pct_rank")
        # High K% team = more Ks for pitcher → inverted (rank 30 = high K% = good)
        inverted = True
    elif stat == "hitsAllowed":
        opp_rank = leg.get("opponent_ba_rank")
        # Low BA = good for pitcher → inverted (rank 30 = low BA = good)
        inverted = True
    elif stat == "earnedRuns":
        opp_rank = leg.get("opponent_rpg_rank")
        # Low RPG = good for pitcher → inverted
        inverted = True
    else:
        opp_rank = None
        inverted = False

    if opp_rank is not None:
        opponent_offense = 50.0 + _normalize_rank(opp_rank, inverted=inverted) * 50.0

    # ── Weight redistribution ─────────────────────────────────────────────────
    w_overall  = 0.35
    w_recent   = 0.25
    w_pitcher  = 0.20
    w_opponent = 0.20

    if pitcher_quality is None:
        w_overall  += 0.10
        w_recent   += 0.10
        w_pitcher   = 0.0

    if opponent_offense is None:
        w_overall  += 0.10
        w_recent   += 0.10
        w_opponent  = 0.0

    # ── Compute score ─────────────────────────────────────────────────────────
    if recent is None:
        # Collapse remaining weight onto overall
        score = overall
    else:
        score = overall * w_overall + recent * w_recent
        if pitcher_quality is not None:
            score += pitcher_quality * w_pitcher
        if opponent_offense is not None:
            score += opponent_offense * w_opponent

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
