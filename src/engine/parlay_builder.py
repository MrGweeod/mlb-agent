"""
parlay_builder.py — Single flat pool parlay builder for MLB.

Parlays are MIN_LEGS..max_legs legs from a single flat pool.
Combined odds minimum: +400. No ceiling.

Two ranking modes, selected by the `rank_by` argument:

  rank_by="composite_score"  (default, pre-v4 behaviour)
      Pool: composite_score >= 65, odds in [-250, +150]. Fixed 4 legs.

  rank_by="p_hit"            (v4 hits/over, 2026-08-12)
      Pool: every hits/over leg carrying a p_hit, odds in [-250, +150].
      NO score floor — removing it is the point of v4 (see main.py
      V4_HITS_ENABLED and docs/ARCHITECTURE_DECISIONS.md §42). Callers pass
      max_legs=6 so the builder can reach the +400 floor by ADDING a 5th or
      6th leg rather than swapping down the probability ranking; see the
      comment on the greedy loop for why that ordering matters.

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
against every other eligible alternative still in the pool (not just the
next-best-scored ones — odds and composite_score aren't correlated, so a
good-odds leg can rank far down by score), and the best floor-clearing swap
(by total composite_score) is kept. Only if no swap within that bounded
search clears the floor does the parlay slot produce nothing. See
_attempt_swap_recovery().

Public API: build_parlays(...), build_hybrid_parlays(...), _tier_params(...).
"""
import math

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
# swapping each selected leg against at most this many alternatives before
# accepting a genuine "no valid parlay" outcome.
#
# This is NOT restricted to the next-best-scored alternatives — live-data
# testing on 2026-08-04 found a real floor-clearing combination (+725) that
# a top-10-by-score-only search missed entirely, because composite_score and
# odds aren't correlated: the legs with the best (least negative) odds
# ranked 18th-33rd by score, well outside a top-10 cutoff. Eligible pools in
# this system run ~30-180 legs, so scanning the full remaining pool per
# position (4 * ~180 = ~720 checks worst case) stays cheap and bounded —
# nowhere near "unbounded search" — while actually finding the swap the
# single-swap search is capable of finding.
SWAP_CANDIDATE_LIMIT = 200


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


def _filter_legs(legs: list, rank_by: str = "composite_score") -> list:
    filtered = []
    low_score_blocked = 0
    extreme_juice_blocked = 0

    for leg in legs:
        # Under v4 (rank_by="p_hit") there is no score floor at all — the whole
        # point of v4 is that the coverage/composite gate was compressing the
        # model's spread and discarding real signal. Gate 2 (the odds band
        # below) still applies, and so do every per-game and per-player cap.
        if rank_by == "composite_score":
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


def compute_quality_floor(pool: list, rank_by: str, mode: str, value: float) -> float:
    """
    Minimum `rank_by` score a leg needs to enter the constrained search.

    mode="percentile": `value` is a percentile (0-100) of the day's pool.
        Adapts to pool composition — important under v4, where the pool is
        ungated and its size and shape vary a lot day to day.
    mode="max_drop": `value` is the largest allowed absolute drop below the
        best leg's score. Anchored to the day's best available leg rather
        than to the pool's shape.
    """
    scores = sorted((l.get(rank_by) or 0.0) for l in pool)
    if not scores:
        return 0.0
    if mode == "percentile":
        idx = min(len(scores) - 1, max(0, int(round(value / 100.0 * (len(scores) - 1)))))
        return scores[idx]
    if mode == "max_drop":
        return scores[-1] - value
    raise ValueError(f"unknown quality floor mode: {mode!r}")


def _best_constrained_combo(
    pool: list, k: int, min_decimal: float, rank_by: str
) -> tuple[list | None, int]:
    """
    Exact branch-and-bound search for the k-leg combination that MAXIMISES
    joint probability (product of `rank_by`) subject to combined decimal odds
    >= min_decimal and every roster constraint _leg_fits() enforces.

    Why this exists: greedy top-k-by-score then check-the-floor is not a search
    — it inspects exactly one combination. On 2026-08-11 the top 4 by p_hit
    multiplied to +351 and the builder extended to 5 legs, while 61 of the 121
    legs were priced long enough (decimal >= 1.495) that some four of them
    clear +400. Greedy never looks at them. Price and the ranking signal are
    negatively correlated (corr(decimal, coverage) = -0.405; corr(decimal,
    p_hit) = -0.175 — weaker, but the same direction), so ranking by
    probability systematically picks the shortest prices. That tension is
    structural and cannot be greedy-ed away.

    Work is done in logs so both objective and constraint are additive.
    Two bounds prune:
      - probability: items are sorted by score DESC, so the best any partial
        solution can still reach is the next `slots` scores. If that can't
        beat the incumbent, cut.
      - odds: suffix maximum of log(decimal) gives the most odds any partial
        solution can still accumulate. If that can't reach the floor, cut.

    Returns (best_legs, nodes_visited); best_legs is None if no combination
    satisfies both the odds floor and the constraints.
    """
    items = sorted(pool, key=lambda l: l.get(rank_by) or 0.0, reverse=True)
    n = len(items)
    if n < k:
        return None, 0

    NEG = float("-inf")
    logp = [math.log(s) if (s := (l.get(rank_by) or 0.0)) > 0 else NEG for l in items]
    logd = [math.log(l["_dec"]) for l in items]
    target = math.log(min_decimal)

    # suffix maxima for the odds bound
    suf_max_d = [0.0] * (n + 1)
    suf_max_d[n] = NEG
    for i in range(n - 1, -1, -1):
        suf_max_d[i] = max(logd[i], suf_max_d[i + 1])

    # prefix sums of logp for the probability bound (items are score-sorted)
    best = {"legs": None, "logp": NEG}
    nodes = 0

    def dfs(i: int, chosen: list, sum_logp: float, sum_logd: float) -> None:
        nonlocal nodes
        nodes += 1
        slots = k - len(chosen)
        if slots == 0:
            if sum_logd >= target and sum_logp > best["logp"]:
                best["logp"] = sum_logp
                best["legs"] = list(chosen)
            return
        if i >= n or n - i < slots:
            return
        # probability bound: best remaining `slots` scores start at i
        if sum_logp + sum(logp[i:i + slots]) <= best["logp"]:
            return
        # odds bound: most odds still reachable
        if sum_logd + slots * suf_max_d[i] < target:
            return
        for j in range(i, n - slots + 1):
            if sum_logp + sum(logp[j:j + slots]) <= best["logp"]:
                break  # sorted DESC — no later j can do better either
            if sum_logd + slots * suf_max_d[j] < target:
                break
            if _leg_fits(items[j], chosen):
                chosen.append(items[j])
                dfs(j + 1, chosen, sum_logp + logp[j], sum_logd + logd[j])
                chosen.pop()

    dfs(0, [], 0.0, 0.0)
    return best["legs"], nodes


def _attempt_swap_recovery(
    legs: list, pool: list, min_decimal: float, rank_by: str = "composite_score"
) -> tuple[list | None, int]:
    """
    When `legs` (the greedy top-N-by-score pick) doesn't clear `min_decimal`,
    search for a single-leg swap that does.

    For each position in `legs`, tries replacing it with each eligible
    alternative in `pool` not already selected (up to SWAP_CANDIDATE_LIMIT of
    them — a safety cap, not a score-based cutoff, since a good-odds leg can
    rank far down the pool by score), checking constraints and the odds
    floor. Bounded to len(legs) * SWAP_CANDIDATE_LIMIT attempts — never an
    unbounded search.

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
        key=lambda l: l.get(rank_by) or 0,
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

            total_score = sum((l.get(rank_by) or 0.0) for l in trial_legs)
            if total_score > best_score:
                best_score = total_score
                best_legs = trial_legs

    return best_legs, attempts


def build_parlays(
    pool_legs: list,
    top_n: int = 5,
    num_games: int = 15,
    rank_by: str = "composite_score",
    max_legs: int | None = None,
    quality_floor_mode: str | None = None,
    quality_floor_value: float | None = None,
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
    EFF_MAX_LEGS = max_legs if max_legs is not None else MAX_LEGS

    # Filter pool by threshold gates
    filtered_pool = _filter_legs(pool_legs, rank_by=rank_by)

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
        f"target {MIN_LEGS}–{EFF_MAX_LEGS} legs, +{MIN_PARLAY_ODDS}+ combined odds "
        f"| ranking by {rank_by}"
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

        # Sort by the ranking signal DESC — greedy selects best legs first.
        # Under v4 that's p_hit (probability of >=1 hit); otherwise composite_score.
        pool_sorted = sorted(avail_pool, key=lambda l: l.get(rank_by) or 0, reverse=True)

        legs: list = []
        by_pid: dict = {}
        by_game: dict = {}
        in_parlay: set = set()
        combined_dec = 1.0

        # ── Stage 1: constrained MIN_LEGS search (v4 only) ───────────────────
        # Look for the MIN_LEGS-leg combination with the highest joint
        # probability that ALSO clears the odds floor, among legs passing the
        # quality floor. Only if no such combination exists do we fall through
        # to the greedy extension below.
        combo_status = None
        if quality_floor_mode is not None:
            floor_score = compute_quality_floor(
                avail_pool, rank_by, quality_floor_mode, quality_floor_value
            )
            eligible = [l for l in pool_sorted
                        if (l.get(rank_by) or 0.0) >= floor_score]
            combo, nodes = _best_constrained_combo(
                eligible, MIN_LEGS, MIN_DECIMAL, rank_by
            )
            if combo is not None:
                legs = combo
                combined_dec = _combined_decimal(legs)
                joint = 1.0
                for l in legs:
                    joint *= (l.get(rank_by) or 0.0)
                combo_status = (
                    f"constrained {MIN_LEGS}-leg search — {len(eligible)} legs "
                    f"above floor {floor_score:.4f}, {nodes} nodes, "
                    f"joint prob {joint:.4f}"
                )
                print(f"  [parlay_builder] Parlay {rank}: {combo_status}")
            else:
                print(
                    f"  [parlay_builder] Parlay {rank}: no {MIN_LEGS}-leg "
                    f"combination clears +{MIN_PARLAY_ODDS} among "
                    f"{len(eligible)} legs above floor {floor_score:.4f} "
                    f"({nodes} nodes) — falling back to extension"
                )

        # ── Stage 2: greedy extension (fallback, and the only path pre-v4) ───
        # Greedy walk in rank order. The loop only stops early once MIN_LEGS
        # are held AND the odds floor is cleared; otherwise it keeps ADDING
        # legs up to EFF_MAX_LEGS.
        #
        # That ordering is deliberate and is the whole reason EFF_MAX_LEGS can
        # exceed MIN_LEGS under v4. Ranking by probability and requiring +400
        # pull against each other — higher-probability legs are priced shorter,
        # so a 4-leg parlay of the very best p_hit legs will often sit under
        # the floor. The two ways out are (a) add a 5th/6th leg, or (b) swap a
        # top leg for a longer-priced one further down the ranking. (a) keeps
        # every leg the model likes and buys odds with an extra selection;
        # (b) discards the model's own preference to buy the same odds. So
        # extension is tried first, exhaustively, and _attempt_swap_recovery()
        # below fires only if EFF_MAX_LEGS legs still miss the floor.
        #
        # Skipped entirely when Stage 1 already found a valid MIN_LEGS combo.
        for leg in (pool_sorted if not legs else []):
            if len(legs) >= EFF_MAX_LEGS:
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
        if combo_status is not None:
            recovery_status = combo_status
        elif len(legs) < MIN_LEGS:
            recovery_status = f"insufficient pool — only {len(legs)} constraint-eligible leg(s)"
        elif combined_dec >= MIN_DECIMAL:
            recovery_status = f"clean greedy pass at {len(legs)} legs"
        else:
            recovery_status = None  # set below by the swap attempt

        if len(legs) >= MIN_LEGS and combined_dec < MIN_DECIMAL:
            swapped_legs, swap_attempts = _attempt_swap_recovery(
                legs, pool_sorted, MIN_DECIMAL, rank_by=rank_by
            )
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
        p_hits   = [l["p_hit"] for l in legs if l.get("p_hit") is not None]
        avg_p_hit = round(sum(p_hits) / len(p_hits), 4) if p_hits else None
        ev_list  = [l["ev_per_unit"] for l in legs if "ev_per_unit" in l]
        avg_ev   = round(sum(ev_list) / len(ev_list), 4) if ev_list else None

        best = {
            "legs":          legs,
            "parlay_odds":   f"+{odds_val}",
            "num_legs":      len(legs),
            "avg_coverage":  round(avg_cov, 1),
            "avg_composite": round(avg_comp, 4),
            "avg_p_hit":     avg_p_hit,
            "joint_p_hit":   (round(math.prod(p_hits), 6) if len(p_hits) == len(legs) else None),
            "avg_ev":        avg_ev,
            "parlay_type":   "pool",
            "tier":          TIER,
            "ranked_by":     rank_by,
            "selection_path": ("constrained_4leg" if combo_status else
                               f"greedy_{len(legs)}leg"),
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
