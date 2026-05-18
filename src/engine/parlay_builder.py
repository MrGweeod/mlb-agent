"""
parlay_builder.py — Single scored-pool parlay builder for MLB.

All eligible legs (composite_score >= 65) are scored once by simple_scorer,
then the top POOL_SIZE are searched for combinations of exactly 4 legs
whose combined parlay odds land in +1000 to +1400.

Constraints:
  - Exactly 4 legs per parlay.
  - Target odds: +1000 to +1400 combined American odds.
  - Score gatekeeper: only legs with composite_score >= 65 enter consideration.
  - Max 1 batter leg per player (pitchers exempt — multiple pitcher props allowed).
  - Max 2 legs per game (keyed by game_pk, fallback to team abbreviation).
  - No duplicate odd_ids within a parlay.
  - High-variance props (homeRuns, stolenBases) require composite_score >= 70.
  - No directional bias — score threshold is the only filter.

Public API unchanged: build_hybrid_parlays(...) and _tier_params(...).
"""
import time
from src.utils.odds_math import american_to_decimal
from src.utils.db import get_players_used_today

_PITCHER_POSITIONS = frozenset({"SP", "RP", "P"})

# High variance props that need extra caution (regardless of direction).
_HIGH_VARIANCE_PROPS = frozenset({"homeRuns", "stolenBases"})


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


def _filter_legs(legs, min_coverage=65.0):
    """
    Filter legs by composite_score threshold.

    Simple unified filter:
    1. composite_score >= min_coverage
    2. Extra threshold for high-variance props (homeRuns, stolenBases)

    No ML model adjustments. No direction bias. Just quality threshold.
    """
    filtered = []
    high_variance_blocked = 0
    low_score_blocked = 0

    for leg in legs:
        score = leg.get("composite_score", 0)
        stat = leg.get("stat", "").lower()

        # Universal score threshold
        if score < min_coverage:
            low_score_blocked += 1
            continue

        # High-variance props need higher score
        if stat in _HIGH_VARIANCE_PROPS:
            if score < 70:
                high_variance_blocked += 1
                continue

        filtered.append(leg)

    over_count = len([x for x in filtered if x.get("direction", "").lower() == "over"])
    under_count = len([x for x in filtered if x.get("direction", "").lower() == "under"])

    print(f"  [filter_legs] Blocked {low_score_blocked} low score + {high_variance_blocked} high variance")
    print(f"  [filter_legs] Kept {over_count} overs + {under_count} unders = {len(filtered)} total eligible")

    return filtered


def _tier_params(num_games: int) -> dict | None:
    """
    Return constraint params based on today's slate size.

    Returns None for Tier 4 (≤1 game) — not enough to build a parlay.
    """
    if num_games >= 10:
        return dict(min_legs=4, max_legs=4, tier=1)
    elif num_games >= 5:
        return dict(min_legs=4, max_legs=4, tier=2)
    elif num_games >= 2:
        return dict(min_legs=4, max_legs=4, tier=3)
    else:
        return None


def build_hybrid_parlays(
    all_legs,
    raw_props=None,
    top_n=5,
    num_games=15,
    blocked_players=None,
    team_to_blocked=None,
):
    """
    Build parlays from a single composite-scored pool.

    Selects combinations of MIN_LEGS–MAX_LEGS legs (4–6 on all slates)
    whose combined American odds land in +1000 to +1500. Legs are ranked
    by composite_score (ML-predicted P(hit) × 100 when USE_ML_SCORING=true).
    Only legs with composite_score >= 65% (ML gatekeeper) enter consideration.

    raw_props and blocked_players are accepted for backwards-compatibility
    but unused.
    """
    params = _tier_params(num_games)
    if params is None:
        return []

    MIN_LEGS        = params["min_legs"]
    MAX_LEGS        = params["max_legs"]
    TIER            = params["tier"]
    MIN_COV         = 65.0
    MIN_PARLAY_ODDS = 1000
    MAX_PARLAY_ODDS = 1400
    MAX_LEGS_PER_GAME = 2
    POOL_SIZE       = 50
    MAX_CANDIDATES  = 15
    TIMEOUT_SECS    = 90

    # ── Pool construction ──────────────────────────────────────────────────────
    eligible = [
        l for l in all_legs
        if l.get("best_odds") and (l.get("composite_score") or 0) >= MIN_COV
    ]

    if not eligible:
        return []

    # Scoring is performed upstream in main.py (simple_scorer, all qualifying legs).
    # Fallback: if any leg is still missing a score (e.g. regeneration path), score now.
    unscored = [l for l in eligible if l.get("composite_score") is None]
    if unscored:
        from src.engine.simple_scorer import score_legs
        score_legs(unscored)
        print(f"  [parlay_builder] Fallback-scored {len(unscored)} unscored legs")

    # Filter by composite_score threshold.
    eligible = _filter_legs(eligible)
    if not eligible:
        return []

    eligible_sorted = sorted(eligible, key=lambda l: l.get("composite_score", 0.0), reverse=True)

    # Quality validation: compare top 20 vs top 50 avg ML score
    if len(eligible_sorted) >= 50:
        top_20_avg = sum(l.get("composite_score", 0) for l in eligible_sorted[:20]) / 20
        top_50_avg = sum(l.get("composite_score", 0) for l in eligible_sorted[:50]) / 50
        quality_drop = ((top_20_avg - top_50_avg) / top_20_avg) * 100
        print(f"  [parlay_builder] Quality validation:")
        print(f"    Top 20 avg ML score: {top_20_avg:.1f}%")
        print(f"    Top 50 avg ML score: {top_50_avg:.1f}%")
        print(f"    Quality drop: {quality_drop:.1f}%")
        if quality_drop > 10:
            print(f"    WARNING: Quality drop >10% when expanding to top 50")
    elif len(eligible_sorted) >= 20:
        top_20_avg = sum(l.get("composite_score", 0) for l in eligible_sorted[:20]) / 20
        print(f"  [parlay_builder] Quality validation:")
        print(f"    Top 20 avg ML score: {top_20_avg:.1f}%")
        print(f"    (Not enough legs for top 50 comparison)")

    pool = eligible_sorted[:POOL_SIZE]

    print(
        f"  [parlay_builder] Received {len(all_legs)} scored legs | "
        f"target {MIN_LEGS}-{MAX_LEGS} legs, +{MIN_PARLAY_ODDS} to +{MAX_PARLAY_ODDS} odds"
    )
    print(
        f"  [parlay_builder] {len(eligible)} eligible legs → "
        f"top {len(pool)} scored (Tier {TIER})"
    )

    if len(pool) < MIN_LEGS:
        return []

    # Stamp decimal odds for fast arithmetic
    for leg in pool:
        if "_dec" not in leg:
            leg["_dec"] = american_to_decimal(str(leg["best_odds"]))

    # Sort by decimal odds DESC for B&B bounds
    pool_bnb = sorted(pool, key=lambda l: l["_dec"], reverse=True)
    n = len(pool_bnb)

    MIN_DECIMAL = MIN_PARLAY_ODDS / 100 + 1
    MAX_DECIMAL = MAX_PARLAY_ODDS / 100 + 1

    parlays = []
    _start_time = time.time()
    _stop = [False]
    total_iters = [0]

    def _record(legs_snap, p):
        odds_val = int((p - 1) * 100)
        avg_cov  = sum(l["coverage_pct"] for l in legs_snap) / len(legs_snap)
        avg_comp = sum(l.get("composite_score", 0.0) for l in legs_snap) / len(legs_snap)
        ev_list  = [l["ev_per_unit"] for l in legs_snap if "ev_per_unit" in l]
        avg_ev   = round(sum(ev_list) / len(ev_list), 4) if ev_list else None
        parlays.append({
            "legs":          legs_snap,
            "parlay_odds":   f"+{odds_val}",
            "num_legs":      len(legs_snap),
            "avg_coverage":  round(avg_cov, 1),
            "avg_composite": round(avg_comp, 4),
            "avg_ev":        avg_ev,
            "parlay_type":   "scored",
            "tier":          TIER,
        })
        if len(parlays) >= MAX_CANDIDATES:
            _stop[0] = True

    def _bnb(rem, idx, legs, p, by_pid, by_game, in_parlay):
        """
        Branch-and-bound over pool_bnb (sorted by _dec DESC).

        Upper bound: current product × best rem remaining decimals (pool_bnb[idx:idx+rem]).
        Lower bound: current product × worst rem remaining decimals (pool_bnb[n-rem:n]).
        Valid because pool_bnb is sorted desc and idx ≤ n-rem is guaranteed.
        """
        total_iters[0] += 1

        # ── Terminal ───────────────────────────────────────────────────────────
        if rem == 0:
            odds_val = int((p - 1) * 100)
            if MIN_PARLAY_ODDS <= odds_val <= MAX_PARLAY_ODDS:
                _record(list(legs), p)
            return

        if n - idx < rem:
            return  # not enough legs left

        # ── Prune: upper bound (best possible completion) ──────────────────────
        ub = p
        for j in range(idx, idx + rem):
            ub *= pool_bnb[j]["_dec"]
        if ub < MIN_DECIMAL:
            return

        # ── Prune: lower bound (cheapest possible completion) ──────────────────
        lb = p
        for j in range(n - rem, n):
            lb *= pool_bnb[j]["_dec"]
        if lb > MAX_DECIMAL:
            return

        # ── Branch ────────────────────────────────────────────────────────────
        for i in range(idx, n - rem + 1):
            if _stop[0]:
                return
            if time.time() - _start_time > TIMEOUT_SECS:
                _stop[0] = True
                return

            leg    = pool_bnb[i]
            odd_id = leg.get("odd_id")

            if odd_id in in_parlay:
                continue

            pid      = leg.get("player_id") or leg.get("player_name", "")
            position = leg.get("position", "")
            is_pitcher = position in _PITCHER_POSITIONS

            # Max 1 batter leg per player (pitchers exempt)
            if not is_pitcher and pid in by_pid:
                continue

            # Max MAX_LEGS_PER_GAME legs per game
            gk = leg.get("game_pk") or leg.get("team", "")
            if by_game.get(gk, 0) >= MAX_LEGS_PER_GAME:
                continue

            # DraftKings does not allow WALKS + STRIKEOUTS in the same parlay
            leg_stat = leg.get("stat", "").lower()
            if leg_stat == "walks" and any(l.get("stat", "").lower() == "strikeouts" for l in legs):
                continue
            if leg_stat == "strikeouts" and any(l.get("stat", "").lower() == "walks" for l in legs):
                continue

            # ── Add leg ────────────────────────────────────────────────────────
            if not is_pitcher:
                by_pid[pid] = True
            by_game[gk] = by_game.get(gk, 0) + 1
            legs.append(leg)
            in_parlay.add(odd_id)

            _bnb(rem - 1, i + 1, legs, p * leg["_dec"], by_pid, by_game, in_parlay)

            # ── Remove leg ─────────────────────────────────────────────────────
            legs.pop()
            in_parlay.discard(odd_id)
            by_game[gk] -= 1
            if by_game[gk] == 0:
                del by_game[gk]
            if not is_pitcher:
                del by_pid[pid]

    for n_legs in range(MIN_LEGS, MAX_LEGS + 1):
        _bnb(n_legs, 0, [], 1.0, {}, {}, set())
        if _stop[0]:
            elapsed = time.time() - _start_time
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
            break

    elapsed = time.time() - _start_time
    print(f"  [parlay_builder] B&B iters: {total_iters[0]:,} ({elapsed:.1f}s)")

    # ── Deduplicate and rank by avg_composite DESC ────────────────────────────
    seen   = set()
    unique = []
    for p in sorted(
        parlays,
        key=lambda x: (x["avg_composite"], x["avg_coverage"]),
        reverse=True,
    ):
        key = frozenset(l["odd_id"] for l in p["legs"])
        if key not in seen:
            seen.add(key)
            unique.append(p)

    if not unique:
        print(
            f"  [parlay_builder] ⚠  0 parlays built from {len(pool)} pool legs — "
            f"check odds range (+{MIN_PARLAY_ODDS}–+{MAX_PARLAY_ODDS}) and leg count ({MIN_LEGS}-{MAX_LEGS})"
        )
        return []

    # REMOVED: Within-batch player diversity constraint (May 11, 2026).
    # Diagnostic analysis showed this forces use of worst-performing legs:
    #   3+ appearances: 48.3% win rate (best)
    #   2 appearances:  32.8% win rate (worst — what the constraint pushed us into)
    #   1 appearance:   39.2% win rate
    # Let ML composite scores determine selection without artificial caps.
    diverse = unique[:top_n]

    print(
        f"  [parlay_builder] Built {len(diverse)} parlays (no within-batch diversity cap — "
        f"ML scores determine selection)"
    )

    # Correlation risk logging — no behavior change, for post-hoc analysis only
    for i, parlay in enumerate(diverse, start=1):
        game_ids = [leg.get("game_pk") or leg.get("team", "") for leg in parlay["legs"]]
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
