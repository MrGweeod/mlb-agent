"""
parlay_builder.py — Anchor/swing pool parlay builder for MLB.

Parlays are exactly 5 legs: 3 anchors (high-coverage, moderate odds) +
2 swings (moderate-coverage, higher odds). Combined odds target: +900 to +1100.

Anchor pool  — composite_score >= 75, odds in [-300, -150].
Swing pool   — composite_score >= 55, odds in (-150, +150].

Constraints (unchanged from prior version):
  - Max 1 batter leg per player (pitchers exempt).
  - Max 2 legs per game.
  - No duplicate odd_ids within a parlay.
  - High-variance props (homeRuns, stolenBases) require composite_score >= 70.
  - DraftKings: no walks + strikeouts in same parlay.
  - Player diversity: each player used in at most one parlay per batch.

Public API: build_hybrid_parlays(anchor_legs, swing_legs, ...) and _tier_params(...).
"""
import time
from src.utils.odds_math import american_to_decimal
from src.utils.db import get_players_used_today

_PITCHER_POSITIONS = frozenset({"SP", "RP", "P"})
_HIGH_VARIANCE_PROPS = frozenset({"homeRuns", "stolenBases"})

# Parlay structure constants
MIN_PARLAY_ODDS = 900
MAX_PARLAY_ODDS = 1100
MIN_ANCHOR_LEGS = 3
MIN_SWING_LEGS  = 2
TOTAL_LEGS      = 5
MIN_COV_ANCHOR  = 75.0
MIN_COV_SWING   = 55.0


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


def _filter_legs(anchor_legs: list, swing_legs: list) -> tuple[list, list]:
    """
    Filter both pools by composite_score threshold and quality gates.

    Anchor gates: composite_score >= MIN_COV_ANCHOR (75.0)
    Swing gates:  composite_score >= MIN_COV_SWING (55.0)

    Both pools share:
      - High-variance props (homeRuns, stolenBases) require composite_score >= 70
      - Juice cap: exclude any leg with odds worse than -300
    """
    def _filter_pool(legs: list, min_cov: float, pool_name: str) -> list:
        filtered = []
        low_score_blocked = 0
        high_variance_blocked = 0
        extreme_juice_blocked = 0

        for leg in legs:
            score = leg.get("composite_score", 0)
            stat  = leg.get("stat", "")

            if score < min_cov:
                low_score_blocked += 1
                continue

            if stat in _HIGH_VARIANCE_PROPS and score < 70:
                high_variance_blocked += 1
                continue

            odds = leg.get("best_odds")
            if odds is not None:
                try:
                    if float(odds) < -300:
                        extreme_juice_blocked += 1
                        continue
                except (ValueError, TypeError):
                    pass

            filtered.append(leg)

        print(
            f"  [filter_legs:{pool_name}] Blocked {low_score_blocked} low score + "
            f"{high_variance_blocked} high variance + {extreme_juice_blocked} extreme juice"
        )
        over_count  = sum(1 for l in filtered if l.get("direction", "").lower() == "over")
        under_count = sum(1 for l in filtered if l.get("direction", "").lower() == "under")
        print(
            f"  [filter_legs:{pool_name}] Kept {over_count} overs + "
            f"{under_count} unders = {len(filtered)} total eligible"
        )
        return filtered

    filtered_anchors = _filter_pool(anchor_legs, MIN_COV_ANCHOR, "anchor")
    filtered_swings  = _filter_pool(swing_legs,  MIN_COV_SWING,  "swing")
    return filtered_anchors, filtered_swings


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


def build_hybrid_parlays(
    anchor_legs: list,
    swing_legs: list,
    raw_props=None,
    top_n: int = 5,
    num_games: int = 15,
    blocked_players=None,
    team_to_blocked=None,
) -> list:
    """
    Build parlays with exactly 3 anchors + 2 swings (5 legs total).

    Target combined American odds: +900 to +1100.

    Anchors: composite_score >= 75, odds [-300, -150].
    Swings:  composite_score >= 55, odds (-150, +150].

    raw_props and blocked_players are accepted for backwards-compatibility
    but unused.
    """
    params = _tier_params(num_games)
    if params is None:
        return []

    TIER = params["tier"]
    MAX_LEGS_PER_GAME = 2
    MAX_CANDIDATES    = 15
    TIMEOUT_SECS      = 90

    MIN_DECIMAL = MIN_PARLAY_ODDS / 100 + 1
    MAX_DECIMAL = MAX_PARLAY_ODDS / 100 + 1

    # ── Pool construction ──────────────────────────────────────────────────────
    # Filter each pool by threshold gates
    filtered_anchors, filtered_swings = _filter_legs(anchor_legs, swing_legs)

    if len(filtered_anchors) < MIN_ANCHOR_LEGS:
        print(
            f"  [parlay_builder] Insufficient anchor legs: "
            f"{len(filtered_anchors)} < {MIN_ANCHOR_LEGS} required. Skipping."
        )
        return []
    if len(filtered_swings) < MIN_SWING_LEGS:
        print(
            f"  [parlay_builder] Insufficient swing legs: "
            f"{len(filtered_swings)} < {MIN_SWING_LEGS} required. Skipping."
        )
        return []

    # Stamp decimal odds for fast arithmetic
    for leg in filtered_anchors + filtered_swings:
        if "_dec" not in leg:
            leg["_dec"] = american_to_decimal(str(leg["best_odds"]))

    print(
        f"  [parlay_builder] Received {len(anchor_legs)} anchor + {len(swing_legs)} swing legs | "
        f"target {MIN_ANCHOR_LEGS}A+{MIN_SWING_LEGS}S, +{MIN_PARLAY_ODDS} to +{MAX_PARLAY_ODDS} odds"
    )
    print(
        f"  [parlay_builder] Eligible: {len(filtered_anchors)} anchors + "
        f"{len(filtered_swings)} swings (Tier {TIER})"
    )

    # ── Per-parlay generation with player diversity constraint ───────────────
    # Each parlay is built from its own B&B pass over the pool minus players
    # already used in earlier parlays. This prevents correlated wipeouts where
    # one player's loss eliminates all parlays in the batch.
    used_players = set()
    diverse = []
    total_iters_all = 0

    for rank in range(1, top_n + 1):
        # Filter both pools to exclude players used in previous parlays
        avail_anchors = [
            l for l in filtered_anchors
            if l.get("player_name", "") not in used_players
        ]
        avail_swings = [
            l for l in filtered_swings
            if l.get("player_name", "") not in used_players
        ]

        print(
            f"  [parlay_builder] Parlay {rank}: {len(avail_anchors)} anchor + "
            f"{len(avail_swings)} swing available ({len(used_players)} players excluded)"
        )

        if len(avail_anchors) < MIN_ANCHOR_LEGS:
            print(
                f"  [parlay_builder] Only {len(avail_anchors)} anchor legs after player exclusion. "
                f"Stopping at {len(diverse)} parlays."
            )
            break
        if len(avail_swings) < MIN_SWING_LEGS:
            print(
                f"  [parlay_builder] Only {len(avail_swings)} swing legs after player exclusion. "
                f"Stopping at {len(diverse)} parlays."
            )
            break

        # Sort by decimal odds DESC for B&B bounds; tag each leg with its type
        for l in avail_anchors:
            l["leg_type"] = "anchor"
        for l in avail_swings:
            l["leg_type"] = "swing"

        # Combined pool sorted by decimal odds DESC for B&B pruning
        pool_bnb = sorted(avail_anchors + avail_swings, key=lambda l: l["_dec"], reverse=True)
        n = len(pool_bnb)

        # Pre-compute suffix counts of anchors and swings for O(1) feasibility checks
        # suffix_anchors[i] = number of anchor legs in pool_bnb[i:]
        # suffix_swings[i]  = number of swing  legs in pool_bnb[i:]
        suffix_anchors = [0] * (n + 1)
        suffix_swings  = [0] * (n + 1)
        for j in range(n - 1, -1, -1):
            lt = pool_bnb[j].get("leg_type", "swing")
            suffix_anchors[j] = suffix_anchors[j + 1] + (1 if lt == "anchor" else 0)
            suffix_swings[j]  = suffix_swings[j + 1]  + (1 if lt == "swing"  else 0)

        # Fresh B&B state for this parlay
        parlays = []
        _start_time = time.time()
        _stop = [False]
        total_iters = [0]

        def _record(legs_snap, p, na, ns, _parlays=parlays, _stop=_stop, _tier=TIER):
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
                "anchor_count":  na,
                "swing_count":   ns,
                "parlay_type":   "anchor_swing",
                "tier":          _tier,
            })
            if len(_parlays) >= MAX_CANDIDATES:
                _stop[0] = True

        def _bnb(
            rem, idx, legs, p, by_pid, by_game, in_parlay, n_anchors, n_swings,
            _pool_bnb=pool_bnb, _n=n,
            _suffix_anchors=suffix_anchors, _suffix_swings=suffix_swings,
            _stop=_stop, _total_iters=total_iters, _start_time=_start_time,
        ):
            """
            Branch-and-bound over _pool_bnb (sorted by _dec DESC).

            Tracks n_anchors and n_swings separately. Only records when
            n_anchors == MIN_ANCHOR_LEGS and n_swings == MIN_SWING_LEGS.

            Feasibility pruning: prune if remaining pool cannot supply
            the required number of anchor or swing legs to complete the parlay.
            """
            _total_iters[0] += 1

            anchors_needed = MIN_ANCHOR_LEGS - n_anchors
            swings_needed  = MIN_SWING_LEGS  - n_swings

            # ── Terminal ───────────────────────────────────────────────────────
            if rem == 0:
                if n_anchors == MIN_ANCHOR_LEGS and n_swings == MIN_SWING_LEGS:
                    odds_val = int((p - 1) * 100)
                    if MIN_PARLAY_ODDS <= odds_val <= MAX_PARLAY_ODDS:
                        _record(list(legs), p, n_anchors, n_swings)
                return

            # ── Feasibility: pool type counts ──────────────────────────────────
            if _suffix_anchors[idx] < anchors_needed:
                return  # not enough anchors left to satisfy anchor quota
            if _suffix_swings[idx] < swings_needed:
                return  # not enough swings left to satisfy swing quota
            if _suffix_anchors[idx] + _suffix_swings[idx] < rem:
                return  # not enough legs of any type

            # ── Feasibility: position bound ────────────────────────────────────
            if _n - idx < rem:
                return

            # ── Prune: upper bound (best possible completion) ──────────────────
            ub = p
            for j in range(idx, idx + rem):
                ub *= _pool_bnb[j]["_dec"]
            if ub < MIN_DECIMAL:
                return

            # ── Prune: lower bound (cheapest possible completion) ──────────────
            lb = p
            for j in range(_n - rem, _n):
                lb *= _pool_bnb[j]["_dec"]
            if lb > MAX_DECIMAL:
                return

            # ── Branch ────────────────────────────────────────────────────────
            for i in range(idx, _n - rem + 1):
                if _stop[0]:
                    return
                if time.time() - _start_time > TIMEOUT_SECS:
                    _stop[0] = True
                    return

                leg     = _pool_bnb[i]
                odd_id  = leg.get("odd_id")
                lt      = leg.get("leg_type", "swing")

                if odd_id in in_parlay:
                    continue

                # Quota enforcement: skip if this type's quota is already full
                if lt == "anchor" and n_anchors >= MIN_ANCHOR_LEGS:
                    continue
                if lt == "swing" and n_swings >= MIN_SWING_LEGS:
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

                # DraftKings: no walks + strikeouts in same parlay
                leg_stat = leg.get("stat", "").lower()
                if leg_stat == "walks" and any(l.get("stat", "").lower() == "strikeouts" for l in legs):
                    continue
                if leg_stat == "strikeouts" and any(l.get("stat", "").lower() == "walks" for l in legs):
                    continue

                # ── Add leg ────────────────────────────────────────────────────
                if not is_pitcher:
                    by_pid[pid] = True
                by_game[gk] = by_game.get(gk, 0) + 1
                legs.append(leg)
                in_parlay.add(odd_id)

                new_n_anchors = n_anchors + (1 if lt == "anchor" else 0)
                new_n_swings  = n_swings  + (1 if lt == "swing"  else 0)

                _bnb(rem - 1, i + 1, legs, p * leg["_dec"],
                     by_pid, by_game, in_parlay, new_n_anchors, new_n_swings)

                # ── Remove leg ─────────────────────────────────────────────────
                legs.pop()
                in_parlay.discard(odd_id)
                by_game[gk] -= 1
                if by_game[gk] == 0:
                    del by_game[gk]
                if not is_pitcher:
                    del by_pid[pid]

        _bnb(TOTAL_LEGS, 0, [], 1.0, {}, {}, set(), 0, 0)

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

        # Add this parlay's players to the exclusion set for subsequent parlays
        for leg in best["legs"]:
            used_players.add(leg.get("player_name", ""))

        diverse.append(best)

        player_names = ", ".join(leg.get("player_name", "?") for leg in best["legs"])
        print(f"  [parlay_builder] Parlay {rank} players: {player_names}")

    print(f"  [parlay_builder] B&B total iters across all parlays: {total_iters_all:,}")
    print(f"  [parlay_builder] Built {len(diverse)} parlays ({len(used_players)} unique players used)")

    # Correlation risk logging — no behavior change, for post-hoc analysis only
    for i, parlay in enumerate(diverse, start=1):
        game_ids    = [leg.get("game_pk") or leg.get("team", "") for leg in parlay["legs"]]
        unique_games = len(set(game_ids))
        legs_same_game = len(game_ids) - unique_games
        correlation_risk = legs_same_game / len(parlay["legs"]) if parlay["legs"] else 0
        total_odds = int(parlay["parlay_odds"].lstrip("+")) if parlay.get("parlay_odds") else 0
        print(
            f"[parlay_correlation] rank={i} "
            f"correlation_risk={correlation_risk:.3f} "
            f"legs_same_game={legs_same_game} "
            f"num_legs={len(parlay['legs'])} "
            f"anchor_count={parlay.get('anchor_count',0)} "
            f"swing_count={parlay.get('swing_count',0)} "
            f"avg_coverage={parlay.get('avg_coverage', 0):.3f} "
            f"total_odds={total_odds}"
        )

    return diverse
