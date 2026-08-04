"""
parlay_builder.py — Single flat pool parlay builder for MLB.

Parlays are fixed 4 legs from a single flat pool.
Combined odds minimum: +400. No ceiling.

Pool: composite_score >= 65, odds in [-250, +150].

Constraints:
  - Max 1 leg per player per parlay.
  - Max 2 legs per game.
  - No duplicate odd_ids within a parlay.
  - Player diversity: each player used in at most one parlay per batch.

Selection: greedy by composite_score (highest first). Walks sorted filtered pool,
respects constraints, stops as soon as MIN_LEGS selected and combined odds >= +400.
If MIN_LEGS legs are selected but floor not cleared, continues up to MAX_LEGS.

If the pure top-N-by-score pick doesn't clear +400, a bounded single-leg-swap
recovery search runs before giving up: each of the selected legs is tried
against the next best-scored eligible alternatives still in the pool, and the
best floor-clearing swap (by total composite_score) is kept. Only if no swap
within that bounded search clears the floor does the parlay slot produce
nothing. See _attempt_swap_recovery().

Public API: build_parlays(...), build_hybrid_parlays(...), _tier_params(...).
"""
from src.utils.odds_math import american_to_decimal
from src.utils.db import get_players_used_today

_PITCHER_POSITIONS = frozenset({"SP", "RP", "P"})

# Parlay structure constants
MIN_PARLAY_ODDS    = 400
MIN_LEGS           = 4
MAX_LEGS           = 4
TOTAL_LEGS         = MIN_LEGS   # backward-compat alias (imported by lineup_confirmation.py)
MIN_COV_POOL       = 65.0
MIN_COV_POOL_UNDER = 65.0  # hits/under gate raised from 40% to 65% (Jun 25, 2026)
                            # Data showed 40% gate let in 397 junk legs averaging
                            # 48.8% coverage at 50.1% win rate vs 56.4% breakeven.
POOL_MIN_ODDS      = -250
POOL_MAX_ODDS      = 150
MAX_LEGS_PER_GAME  = 2

# Floor-recovery: when the top-N-by-score pick misses MIN_PARLAY_ODDS, try
# swapping each selected leg against at most this many next-best-scored
# alternatives before accepting a genuine "no valid parlay" outcome.
SWAP_CANDIDATE_LIMIT = 10


def filter_already_used_players(legs: list, run_date: str) -> list:
    """
    Remove legs for players already used in today's parlays.

    Ensures portfolio diversity: each player appears in max 1 parlay per day.

    Args:
        legs: List of leg dicts with player_id
        run_date: Date string (YYYY-MM-DD)

    Returns:
        list: Filtered legs (players not yet used today)
    """
    used_players = get_players_used_today(run_date)

    if not used_players:
        print("[player_diversity] No players filtered (first run of day or query failed)")
        return legs

    filtered = [
        leg for leg in legs
        if str(leg.get("player_id") or "") not in used_players
    ]

    removed_count = len(legs) - len(filtered)
    removed_pct = (removed_count / len(legs) * 100) if legs else 0

    print(
        f"[player_diversity] Filtered {removed_count} legs from {len(used_players)} "
        f"players already used today ({removed_pct:.1f}%)"
    )
    print(f"[player_diversity] {len(filtered)} eligible legs remaining with unique players")

    if removed_pct > 80:
        print(
            f"[WARNING] Player diversity filter removed {removed_pct:.1f}% of legs — "
            "this may indicate an issue"
        )

    return filtered


def _filter_legs(legs: list) -> list:
    filtered = []
    low_score_blocked = 0
    extreme_juice_blocked = 0

    for leg in legs:
        score = leg.get("composite_score", 0)
        direction = leg.get("direction", "over").lower()
        floor = MIN_COV_POOL_UNDER if direction == "under" else MIN_COV_POOL
        if score < floor:
            low_score_blocked += 1
            continue
        odds = leg.get("best_odds")
        if odds is not None:
            try:
                if not (POOL_MIN_ODDS <= float(odds) <= POOL_MAX_ODDS):
                    extreme_juice_blocked += 1
                    continue
            except (ValueError, TypeError):
                pass
        filtered.append(leg)

    over_count  = sum(1 for l in filtered if l.get("direction", "").lower() == "over")
    under_count = sum(1 for l in filtered if l.get("direction", "").lower() == "under")
    print(
        f"  [filter_legs] Blocked {low_score_blocked} low score + "
        f"{extreme_juice_blocked} out-of-range odds | "
        f"Kept {over_count} overs + {under_count} unders = {len(filtered)} total eligible"
    )
    return filtered


def _tier_params(num_games: int) -> dict | None:
    """
    Return constraint params based on today's slate size.

    Returns None for Tier 4 (<=1 game) — not enough to build a parlay.
    """
    if num_games >= 10:
        return dict(tier=1)
    elif num_games >= 5:
        return dict(tier=2)
    elif num_games >= 2:
        return dict(tier=3)
    else:
        return None


def _combined_decimal(legs: list) -> float:
    """Product of each leg's stamped decimal odds (`_dec`)."""
    dec = 1.0
    for l in legs:
        dec *= l["_dec"]
    return dec


def _leg_fits(candidate: dict, other_legs: list) -> bool:
    """
    True if `candidate` can join `other_legs` without violating the max-1-
    batter-leg-per-player, MAX_LEGS_PER_GAME, or no-duplicate-odd_id
    constraints — the same rules the greedy selection loop enforces.
    """
    odd_id = candidate.get("odd_id")
    if odd_id is not None and any(l.get("odd_id") == odd_id for l in other_legs):
        return False

    is_pitcher = candidate.get("position", "") in _PITCHER_POSITIONS
    if not is_pitcher:
        pid = candidate.get("player_id") or candidate.get("player_name", "")
        for l in other_legs:
            other_is_pitcher = l.get("position", "") in _PITCHER_POSITIONS
            other_pid = l.get("player_id") or l.get("player_name", "")
            if not other_is_pitcher and other_pid == pid:
                return False

    gk = candidate.get("game_pk") or candidate.get("team", "")
    game_count = sum(1 for l in other_legs if (l.get("game_pk") or l.get("team", "")) == gk)
    if game_count >= MAX_LEGS_PER_GAME:
        return False

    return True


def _attempt_swap_recovery(legs: list, pool: list, min_decimal: float) -> tuple[list | None, int]:
    """
    When `legs` (the greedy top-N-by-score pick) doesn't clear `min_decimal`,
    search for a single-leg swap that does.

    For each position in `legs`, tries replacing it with each of the next
    SWAP_CANDIDATE_LIMIT best-scored eligible alternatives in `pool` not
    already selected, checking constraints and the odds floor. Bounded to
    len(legs) * SWAP_CANDIDATE_LIMIT attempts — never an unbounded search.

    Score-first intent is preserved even when a swap is required: among all
    swaps that clear the floor, the one with the highest total
    composite_score across all 4 legs is returned, not just the first found.

    Returns:
        (new_legs, attempts) if a valid floor-clearing swap was found,
        else (None, attempts).
    """
    selected_ids = {id(l) for l in legs}
    alternatives = sorted(
        (l for l in pool if id(l) not in selected_ids),
        key=lambda l: l.get("composite_score", 0),
        reverse=True,
    )[:SWAP_CANDIDATE_LIMIT]

    best_legs: list | None = None
    best_score = -1.0
    attempts = 0

    for pos in range(len(legs)):
        other_legs = legs[:pos] + legs[pos + 1:]

        for candidate in alternatives:
            attempts += 1
            if not _leg_fits(candidate, other_legs):
                continue

            trial_legs = other_legs + [candidate]
            if _combined_decimal(trial_legs) < min_decimal:
                continue

            total_score = sum(l.get("composite_score", 0.0) for l in trial_legs)
            if total_score > best_score:
                best_score = total_score
                best_legs = trial_legs

    return best_legs, attempts


def build_parlays(
    pool_legs: list,
    top_n: int = 5,
    num_games: int = 15,
) -> list:
    """
    Build up to top_n parlays from a single flat leg pool.

    Fixed 4 legs per parlay. Minimum combined odds: +400. No ceiling.
    All legs must have composite_score >= 65, odds -250 to +150.

    Selection is greedy by composite_score (highest first). Walks the sorted
    filtered pool respecting constraints, stops as soon as MIN_LEGS legs are
    selected and combined odds >= +400. If floor isn't cleared at MIN_LEGS,
    continues adding legs up to MAX_LEGS. If MAX_LEGS reached without clearing
    floor, the parlay slot produces nothing.

    Constraints:
      - Max 1 batter leg per player per parlay (pitchers exempt)
      - Max 2 legs per game
      - No duplicate odd_ids within a parlay
      - Player diversity: each player used in at most 1 parlay per batch
    """
    params = _tier_params(num_games)
    if params is None:
        return []

    TIER = params["tier"]
    MIN_DECIMAL = MIN_PARLAY_ODDS / 100 + 1

    # Filter pool by threshold gates
    filtered_pool = _filter_legs(pool_legs)

    if len(filtered_pool) < MIN_LEGS:
        print(
            f"  [parlay_builder] Insufficient pool legs: "
            f"{len(filtered_pool)} < {MIN_LEGS} required. Skipping."
        )
        return []

    # Stamp decimal odds for fast arithmetic
    for leg in filtered_pool:
        if "_dec" not in leg:
            leg["_dec"] = american_to_decimal(str(leg["best_odds"]))

    print(
        f"  [parlay_builder] Received {len(pool_legs)} pool legs | "
        f"target {MIN_LEGS}–{MAX_LEGS} legs, +{MIN_PARLAY_ODDS}+ combined odds"
    )
    print(
        f"  [parlay_builder] Eligible: {len(filtered_pool)} pool legs (Tier {TIER})"
    )

    # ── Per-parlay generation with player diversity constraint ───────────────
    # Each parlay is built with its own greedy pass over the pool minus players
    # already used in earlier parlays. This prevents correlated wipeouts where
    # one player's loss eliminates all parlays in the batch.
    used_players = set()
    diverse = []

    for rank in range(1, top_n + 1):
        avail_pool = [
            l for l in filtered_pool
            if l.get("player_name", "") not in used_players
        ]

        print(
            f"  [parlay_builder] Parlay {rank}: {len(avail_pool)} legs available "
            f"({len(used_players)} players excluded)"
        )

        if len(avail_pool) < MIN_LEGS:
            print(
                f"  [parlay_builder] Only {len(avail_pool)} legs after player exclusion. "
                f"Stopping at {len(diverse)} parlays."
            )
            break

        # Sort by composite_score DESC — greedy selects highest-quality legs first
        pool_sorted = sorted(avail_pool, key=lambda l: l.get("composite_score", 0), reverse=True)

        # ── Greedy selection ─────────────────────────────────────────────────
        legs: list = []
        by_pid: dict = {}
        by_game: dict = {}
        in_parlay: set = set()
        combined_dec = 1.0

        for leg in pool_sorted:
            if len(legs) >= MAX_LEGS:
                break

            odd_id = leg.get("odd_id")
            if odd_id is not None and odd_id in in_parlay:
                continue

            pid        = leg.get("player_id") or leg.get("player_name", "")
            position   = leg.get("position", "")
            is_pitcher = position in _PITCHER_POSITIONS

            # Max 1 batter leg per player (pitchers exempt)
            if not is_pitcher and pid in by_pid:
                continue

            # Max MAX_LEGS_PER_GAME legs per game
            gk = leg.get("game_pk") or leg.get("team", "")
            if by_game.get(gk, 0) >= MAX_LEGS_PER_GAME:
                continue

            # Add leg
            if not is_pitcher:
                by_pid[pid] = True
            by_game[gk] = by_game.get(gk, 0) + 1
            if odd_id is not None:
                in_parlay.add(odd_id)
            legs.append(leg)
            combined_dec *= leg["_dec"]

            # Stop as soon as floor is cleared and we have at least MIN_LEGS
            if len(legs) >= MIN_LEGS and combined_dec >= MIN_DECIMAL:
                break

        # ── Floor-recovery: pure top-N-by-score missed +400 — try single-leg
        # swaps against progressively lower-scored alternatives before giving up ──
        if len(legs) < MIN_LEGS:
            recovery_status = f"insufficient pool — only {len(legs)} constraint-eligible leg(s)"
        elif combined_dec >= MIN_DECIMAL:
            recovery_status = "clean top-4 pass"
        else:
            recovery_status = None  # set below by the swap attempt

        if len(legs) >= MIN_LEGS and combined_dec < MIN_DECIMAL:
            swapped_legs, swap_attempts = _attempt_swap_recovery(legs, pool_sorted, MIN_DECIMAL)
            if swapped_legs is not None:
                legs = swapped_legs
                combined_dec = _combined_decimal(legs)
                recovery_status = f"recovered via swap — {swap_attempts} attempt(s)"
            else:
                recovery_status = f"no combination found — {swap_attempts} attempt(s)"

        # Parlay is valid only if it meets both the leg count and odds floor
        if len(legs) < MIN_LEGS or combined_dec < MIN_DECIMAL:
            odds_val = int((combined_dec - 1) * 100)
            print(
                f"  [parlay_builder] ⚠  Parlay {rank} failed ({recovery_status}): "
                f"{len(legs)} legs, +{odds_val} odds "
                f"(need >= {MIN_LEGS} legs and >= +{MIN_PARLAY_ODDS}). "
                f"Stopping at {len(diverse)} parlays."
            )
            break

        print(f"  [parlay_builder] Parlay {rank} selection: {recovery_status}")

        odds_val = int((combined_dec - 1) * 100)
        avg_cov  = sum(l["coverage_pct"] for l in legs) / len(legs)
        avg_comp = sum(l.get("composite_score", 0.0) for l in legs) / len(legs)
        ev_list  = [l["ev_per_unit"] for l in legs if "ev_per_unit" in l]
        avg_ev   = round(sum(ev_list) / len(ev_list), 4) if ev_list else None

        best = {
            "legs":          legs,
            "parlay_odds":   f"+{odds_val}",
            "num_legs":      len(legs),
            "avg_coverage":  round(avg_cov, 1),
            "avg_composite": round(avg_comp, 4),
            "avg_ev":        avg_ev,
            "parlay_type":   "pool",
            "tier":          TIER,
        }

        for leg in legs:
            used_players.add(leg.get("player_name", ""))

        diverse.append(best)

        player_names = ", ".join(leg.get("player_name", "?") for leg in legs)
        print(f"  [parlay_builder] Parlay {rank} ({len(legs)} legs, +{odds_val}): {player_names}")

    print(f"  [parlay_builder] Built {len(diverse)} parlays ({len(used_players)} unique players used)")

    # Correlation risk logging — no behavior change, for post-hoc analysis only
    for i, parlay in enumerate(diverse, start=1):
        game_ids     = [leg.get("game_pk") or leg.get("team", "") for leg in parlay["legs"]]
        unique_games = len(set(game_ids))
        legs_same_game = len(game_ids) - unique_games
        correlation_risk = legs_same_game / len(parlay["legs"]) if parlay["legs"] else 0
        total_odds = int(parlay["parlay_odds"].lstrip("+")) if parlay.get("parlay_odds") else 0
        print(
            f"[parlay_correlation] rank={i} "
            f"correlation_risk={correlation_risk:.3f} "
            f"legs_same_game={legs_same_game} "
            f"num_legs={len(parlay['legs'])} "
            f"avg_coverage={parlay.get('avg_coverage', 0):.3f} "
            f"total_odds={total_odds}"
        )

    return diverse


def build_hybrid_parlays(anchor_legs, swing_legs, **kwargs) -> list:
    """Backward-compat wrapper — merges pools and delegates to build_parlays."""
    return build_parlays(anchor_legs + swing_legs, **kwargs)
