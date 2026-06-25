"""
parlay_builder.py — Single flat pool parlay builder for MLB.

Parlays are exactly 4 legs from a single flat pool.
Combined odds target: +400 to +700.

Pool: composite_score >= 65, odds in [-250, +150].

Constraints:
  - Max 1 leg per player per parlay.
  - Max 2 legs per game.
  - No duplicate odd_ids within a parlay.
  - Player diversity: each player used in at most one parlay per batch.

Public API: build_parlays(...), build_hybrid_parlays(...), _tier_params(...).
"""
import time
from src.utils.odds_math import american_to_decimal
from src.utils.db import get_players_used_today

_PITCHER_POSITIONS = frozenset({"SP", "RP", "P"})

# Parlay structure constants
MIN_PARLAY_ODDS   = 400
MAX_PARLAY_ODDS   = 700
TOTAL_LEGS        = 4
MIN_COV_POOL      = 65.0
MIN_COV_POOL_UNDER = 65.0  # hits/under gate raised from 40% to 65% (Jun 25, 2026)
                            # Data showed 40% gate let in 397 junk legs averaging
                            # 48.8% coverage at 50.1% win rate vs 56.4% breakeven.
POOL_MIN_ODDS     = -250
POOL_MAX_ODDS     = 150
MAX_LEGS_PER_GAME = 2


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


def build_parlays(
    pool_legs: list,
    top_n: int = 5,
    num_games: int = 15,
) -> list:
    """
    Build up to top_n parlays from a single flat leg pool.

    4 legs per parlay. Target combined odds: +400 to +700.
    All legs must have coverage_overall >= 65%, odds -250 to +150.

    Constraints:
      - Max 1 leg per player per parlay
      - Max 2 legs per game
      - No duplicate odd_ids within a parlay
      - Player diversity: each player used in at most 1 parlay per batch
    """
    params = _tier_params(num_games)
    if params is None:
        return []

    TIER = params["tier"]
    MAX_CANDIDATES = 50
    TIMEOUT_SECS   = 90

    MIN_DECIMAL = MIN_PARLAY_ODDS / 100 + 1
    MAX_DECIMAL = MAX_PARLAY_ODDS / 100 + 1

    # Filter pool by threshold gates
    filtered_pool = _filter_legs(pool_legs)

    if len(filtered_pool) < TOTAL_LEGS:
        print(
            f"  [parlay_builder] Insufficient pool legs: "
            f"{len(filtered_pool)} < {TOTAL_LEGS} required. Skipping."
        )
        return []

    # Stamp decimal odds for fast arithmetic
    for leg in filtered_pool:
        if "_dec" not in leg:
            leg["_dec"] = american_to_decimal(str(leg["best_odds"]))

    print(
        f"  [parlay_builder] Received {len(pool_legs)} pool legs | "
        f"target {TOTAL_LEGS} legs, +{MIN_PARLAY_ODDS} to +{MAX_PARLAY_ODDS} odds"
    )
    print(
        f"  [parlay_builder] Eligible: {len(filtered_pool)} pool legs (Tier {TIER})"
    )

    # ── Per-parlay generation with player diversity constraint ───────────────
    # Each parlay is built from its own B&B pass over the pool minus players
    # already used in earlier parlays. This prevents correlated wipeouts where
    # one player's loss eliminates all parlays in the batch.
    used_players = set()
    diverse = []
    total_iters_all = 0

    for rank in range(1, top_n + 1):
        avail_pool = [
            l for l in filtered_pool
            if l.get("player_name", "") not in used_players
        ]

        print(
            f"  [parlay_builder] Parlay {rank}: {len(avail_pool)} legs available "
            f"({len(used_players)} players excluded)"
        )

        if len(avail_pool) < TOTAL_LEGS:
            print(
                f"  [parlay_builder] Only {len(avail_pool)} legs after player exclusion. "
                f"Stopping at {len(diverse)} parlays."
            )
            break

        # Sort by composite_score DESC so B&B explores highest-quality legs first
        pool_bnb = sorted(avail_pool, key=lambda l: l.get("composite_score", 0), reverse=True)
        n = len(pool_bnb)

        # Precompute suffix-sorted dec values so UB/LB bounds remain valid under
        # any pool sort order. suffix_dec_sorted[i] = list of _dec values from
        # pool_bnb[i:] sorted descending (highest odds first).
        suffix_dec_sorted = []
        for _i in range(n + 1):
            suffix_dec_sorted.append(
                sorted([l["_dec"] for l in pool_bnb[_i:]], reverse=True)
            )

        # Fresh B&B state for this parlay
        parlays = []
        _start_time = time.time()
        _stop = [False]
        total_iters = [0]

        def _record(legs_snap, p, _parlays=parlays, _stop=_stop, _tier=TIER):
            odds_val = int((p - 1) * 100)
            avg_cov  = sum(l["coverage_pct"] for l in legs_snap) / len(legs_snap)
            avg_comp = sum(l.get("composite_score", 0.0) for l in legs_snap) / len(legs_snap)
            ev_list  = [l["ev_per_unit"] for l in legs_snap if "ev_per_unit" in l]
            avg_ev   = round(sum(ev_list) / len(ev_list), 4) if ev_list else None
            _parlays.append({
                "legs":          legs_snap,
                "parlay_odds":   f"+{odds_val}",
                "num_legs":      len(legs_snap),
                "avg_coverage":  round(avg_cov, 1),
                "avg_composite": round(avg_comp, 4),
                "avg_ev":        avg_ev,
                "parlay_type":   "pool",
                "tier":          _tier,
            })
            if len(_parlays) >= MAX_CANDIDATES:
                _stop[0] = True

        def _bnb(
            rem, idx, legs, p, by_pid, by_game, in_parlay,
            _pool_bnb=pool_bnb, _n=n,
            _suffix_dec=suffix_dec_sorted,
            _stop=_stop, _total_iters=total_iters, _start_time=_start_time,
        ):
            """
            Branch-and-bound over _pool_bnb (sorted by composite_score DESC).

            Records when rem == 0 and combined odds are in target range.
            Bounds use suffix_dec_sorted for correctness under any pool sort order.
            """
            _total_iters[0] += 1

            # ── Terminal ───────────────────────────────────────────────────────
            if rem == 0:
                odds_val = int((p - 1) * 100)
                if MIN_PARLAY_ODDS <= odds_val <= MAX_PARLAY_ODDS:
                    _record(list(legs), p)
                return

            # ── Feasibility: position bound ────────────────────────────────────
            if _n - idx < rem:
                return

            # ── Prune: upper bound (top rem odds from pool[idx:]) ──────────────
            ub = p
            for d in _suffix_dec[idx][:rem]:
                ub *= d
            if ub < MIN_DECIMAL:
                return

            # ── Prune: lower bound (bottom rem odds from pool[idx:]) ───────────
            lb = p
            for d in _suffix_dec[idx][-rem:]:
                lb *= d
            if lb > MAX_DECIMAL:
                return

            # ── Branch ────────────────────────────────────────────────────────
            for i in range(idx, _n - rem + 1):
                if _stop[0]:
                    return
                if time.time() - _start_time > TIMEOUT_SECS:
                    _stop[0] = True
                    return

                leg    = _pool_bnb[i]
                odd_id = leg.get("odd_id")

                if odd_id in in_parlay:
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

                # ── Add leg ────────────────────────────────────────────────────
                if not is_pitcher:
                    by_pid[pid] = True
                by_game[gk] = by_game.get(gk, 0) + 1
                legs.append(leg)
                in_parlay.add(odd_id)

                _bnb(rem - 1, i + 1, legs, p * leg["_dec"],
                     by_pid, by_game, in_parlay)

                # ── Remove leg ─────────────────────────────────────────────────
                legs.pop()
                in_parlay.discard(odd_id)
                by_game[gk] -= 1
                if by_game[gk] == 0:
                    del by_game[gk]
                if not is_pitcher:
                    del by_pid[pid]

        _bnb(TOTAL_LEGS, 0, [], 1.0, {}, {}, set())

        elapsed = time.time() - _start_time
        total_iters_all += total_iters[0]

        if _stop[0]:
            if elapsed > TIMEOUT_SECS:
                print(
                    f"  [parlay_builder] ⚠ hard timeout after {elapsed:.1f}s — "
                    f"{len(parlays)} raw parlays found"
                )
            else:
                print(
                    f"  [parlay_builder] early exit — {MAX_CANDIDATES} candidates "
                    f"found in {elapsed:.1f}s"
                )

        print(f"  [parlay_builder] Parlay {rank} B&B: {total_iters[0]:,} iters ({elapsed:.1f}s)")

        # ── Deduplicate and pick best candidate for this parlay ───────────────
        seen_keys = set()
        unique_candidates = []
        for pc in sorted(
            parlays,
            key=lambda x: (x["avg_composite"], x["avg_coverage"]),
            reverse=True,
        ):
            key = frozenset(l["odd_id"] for l in pc["legs"])
            if key not in seen_keys:
                seen_keys.add(key)
                unique_candidates.append(pc)

        if not unique_candidates:
            print(
                f"  [parlay_builder] ⚠  0 parlays built for rank {rank} — "
                f"check odds range (+{MIN_PARLAY_ODDS}–+{MAX_PARLAY_ODDS}). "
                f"Stopping at {len(diverse)} parlays."
            )
            break

        best = unique_candidates[0]

        for leg in best["legs"]:
            used_players.add(leg.get("player_name", ""))

        diverse.append(best)

        player_names = ", ".join(leg.get("player_name", "?") for leg in best["legs"])
        print(f"  [parlay_builder] Parlay {rank} players: {player_names}")

    print(f"  [parlay_builder] B&B total iters across all parlays: {total_iters_all:,}")
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
