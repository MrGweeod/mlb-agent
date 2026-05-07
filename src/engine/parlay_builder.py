"""
parlay_builder.py — Single scored-pool parlay builder for MLB.

All eligible legs (ML score >= 55%) are scored once by composite_score,
then the top POOL_SIZE are searched for combinations of MIN_LEGS–MAX_LEGS
whose combined parlay odds land in +1000 to +1500.

Constraints:
  - Min 4 legs, max 6 legs per parlay.
  - Target odds: +1000 to +1500 combined American odds.
  - ML gatekeeper: only legs with composite_score >= 65% enter consideration.
  - Max 1 batter leg per player (pitchers exempt — multiple pitcher props allowed).
  - Max 3 legs per game (keyed by game_pk, fallback to team abbreviation).
  - No duplicate odd_ids within a parlay.
  - High-variance overs (homeRuns, stolenBases) require ML score >= 70.
  - All other legs evaluated uniformly by ML score — no directional bias.
  - The calibrated ML model (77K samples) already learned direction bias;
    we do not impose additional directional filters on top of its predictions.

Public API unchanged: build_hybrid_parlays(...) and _tier_params(...).
"""
import time
from src.utils.odds_math import american_to_decimal

_PITCHER_POSITIONS = frozenset({"SP", "RP", "P"})

# Stats whose overs require a higher ML score (>= 70) due to extreme variance.
# homeRuns ~6.1% hit rate, stolenBases extremely volatile.
# rbi and walks are no longer blocked — the ML model can score them on merit.
_HIGH_VARIANCE_OVER_STATS = frozenset({"homeRuns", "stolenBases"})


def filter_and_tag_legs(scored_legs: list) -> list:
    """
    Filter legs by ML score, enforcing strikeout line rules and a higher
    threshold for genuinely high-variance over stats.

    High-variance overs (require composite_score >= 70):
      homeRuns overs  ~6.1% hit rate
      stolenBases overs extremely volatile

    Strikeout line rules (both directions):
      hitter strikeouts: only line 0.5 allowed
      pitcher strikeouts: only line >= 3.5 allowed

    All other legs (overs and unders) are evaluated uniformly. The
    calibrated ML model (77K samples, AUC 0.8532) already learned
    directional bias — we do not override it with hand-coded filters.
    """
    filtered = []
    blocked_hv     = 0
    blocked_other  = 0
    allowed_over   = 0
    allowed_under  = 0

    for leg in scored_legs:
        direction  = leg.get("direction", "")
        stat       = leg.get("stat", "")
        line       = leg.get("line") or leg.get("best_line")
        score      = leg.get("composite_score", 0.0) or 0.0
        position   = leg.get("position", "")
        is_pitcher = position in _PITCHER_POSITIONS

        # Block invalid strikeout lines for both directions.
        # Hitters: only 0.5 allowed. Pitchers: only ≥ 3.5 allowed.
        if stat == "strikeouts":
            if not is_pitcher and line != 0.5:
                blocked_other += 1
                continue
            if is_pitcher and (line is None or line < 3.5):
                blocked_other += 1
                continue

        if direction == "over" and stat in _HIGH_VARIANCE_OVER_STATS:
            if score < 70:
                blocked_hv += 1
                continue

        if direction == "over":
            allowed_over += 1
        else:
            allowed_under += 1

        filtered.append(leg)

    print(
        f"  [filter_legs] blocked {blocked_hv} high-variance overs, "
        f"{blocked_other} invalid lines | "
        f"kept {allowed_under} unders + {allowed_over} overs "
        f"→ {len(filtered)} legs"
    )
    return filtered


def _tier_params(num_games: int) -> dict | None:
    """
    Return constraint params based on today's slate size.

    Returns None for Tier 4 (≤1 game) — not enough to build a parlay.
    """
    if num_games >= 10:
        return dict(min_legs=4, max_legs=6, tier=1)
    elif num_games >= 5:
        return dict(min_legs=4, max_legs=6, tier=2)
    elif num_games >= 2:
        return dict(min_legs=4, max_legs=6, tier=3)
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
    MAX_PARLAY_ODDS = 1500
    MAX_LEGS_PER_GAME = 3
    POOL_SIZE       = 20
    MAX_CANDIDATES  = 15
    TIMEOUT_SECS    = 90

    # ── Pool construction ──────────────────────────────────────────────────────
    eligible = [
        l for l in all_legs
        if l.get("best_odds") and l.get("coverage_pct", 0) >= MIN_COV
    ]
    if not eligible:
        return []

    # Scoring is performed upstream in main.py (ML model, all qualifying legs).
    # Fallback: if any leg is still missing a score (e.g. regeneration path), score now.
    unscored = [l for l in eligible if l.get("composite_score") is None]
    if unscored:
        from src.engine.ml_leg_scorer import score_legs_ml
        score_legs_ml(unscored)
        print(f"  [parlay_builder] Fallback-scored {len(unscored)} unscored legs with ML model")

    # Filter poison/non-qualifying overs; tag risky overs for B&B constraint.
    eligible = filter_and_tag_legs(eligible)
    if not eligible:
        return []

    pool = sorted(eligible, key=lambda l: l.get("composite_score", 0.0), reverse=True)[:POOL_SIZE]

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

    # Diversity filter: keep best, then only add parlays sharing ≤3 legs with all kept
    diverse = [unique[0]]
    for candidate in unique[1:]:
        candidate_ids = frozenset(l["odd_id"] for l in candidate["legs"])
        if all(
            len(candidate_ids & frozenset(l["odd_id"] for l in sel["legs"])) <= 3
            for sel in diverse
        ):
            diverse.append(candidate)
        if len(diverse) >= top_n:
            break

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
