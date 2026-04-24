"""
parlay_builder.py — Single scored-pool parlay builder for MLB.

All eligible legs (coverage >= 55%) are scored once by composite_score,
then the top POOL_SIZE are searched for combinations of MIN_LEGS–MAX_LEGS
whose combined parlay odds land in +600 to +1500.

Constraints:
  - Max 1 batter leg per player (pitchers exempt — multiple pitcher props allowed).
  - Max 3 legs per game (keyed by game_pk, fallback to team abbreviation).
  - No duplicate odd_ids within a parlay.
  - Poison overs (rbi, walks, homeRuns) blocked entirely.
  - Other overs blocked unless they meet high-confidence risky-over criteria.
  - Max 1 risky over per parlay.

Public API unchanged: build_hybrid_parlays(...) and _tier_params(...).
"""
import time
from src.utils.odds_math import american_to_decimal
from src.engine.leg_scorer import score_legs_composite

_PITCHER_POSITIONS = frozenset({"SP", "RP", "P"})

# Stats whose overs are blocked entirely regardless of score.
_POISON_OVER_STATS = frozenset({"rbi", "walks", "homeRuns"})


def filter_and_tag_legs(scored_legs: list) -> list:
    """
    Filter out poison overs and tag high-confidence risky overs.

    Poison overs (blocked entirely — too low hit rates to include):
      rbi overs      ~14.6% hit rate
      walks overs    ~19.4% hit rate
      homeRuns overs  ~6.1% hit rate

    Risky overs (allowed but capped at 1 per parlay via B&B constraint):
      hits over 0.5 with composite_score >= 65
      pitcher strikeouts over 4.5+ with composite_score >= 65

    All other overs are also blocked — only unders and the two risky-over
    categories pass, reflecting the 79.2% under vs 21.9% over hit split.

    Mutates each leg in-place to add ``is_risky_over`` (bool).
    Returns the filtered list (poison overs and non-qualifying overs removed).
    """
    filtered = []
    blocked_poison = 0
    blocked_other  = 0
    allowed_risky  = 0
    allowed_under  = 0

    for leg in scored_legs:
        direction = leg.get("direction", "")
        stat      = leg.get("stat", "")
        line      = leg.get("line") or leg.get("best_line")
        score     = leg.get("composite_score", 0.0) or 0.0

        if direction == "over":
            # Block poison overs entirely
            if stat in _POISON_OVER_STATS:
                blocked_poison += 1
                continue

            # Qualify risky overs
            is_risky = (
                (stat == "hits" and line == 0.5 and score >= 65)
                or (stat == "strikeouts" and line is not None and line >= 4.5 and score >= 65)
            )
            leg["is_risky_over"] = is_risky

            if not is_risky:
                blocked_other += 1
                continue

            allowed_risky += 1
        else:
            leg["is_risky_over"] = False
            allowed_under += 1

        filtered.append(leg)

    print(
        f"  [filter_legs] blocked {blocked_poison} poison overs, "
        f"{blocked_other} other overs | "
        f"kept {allowed_under} unders + {allowed_risky} risky overs "
        f"→ {len(filtered)} legs"
    )
    return filtered


def _tier_params(num_games: int) -> dict | None:
    """
    Return constraint params based on today's slate size.

    Returns None for Tier 4 (≤1 game) — not enough to build a parlay.
    """
    if num_games >= 10:
        return dict(min_legs=4, max_legs=8, tier=1)
    elif num_games >= 5:
        return dict(min_legs=4, max_legs=8, tier=2)
    elif num_games >= 2:
        return dict(min_legs=3, max_legs=8, tier=3)
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

    Selects combinations of MIN_LEGS–MAX_LEGS legs whose combined
    American odds land in +600 to +1500. Legs are ranked by composite_score
    (40% recency-weighted coverage, 25% EV, 15% trend, 15% opp adj, 5% PA).

    raw_props and blocked_players are accepted for backwards-compatibility
    but unused.
    """
    params = _tier_params(num_games)
    if params is None:
        return []

    MIN_LEGS        = params["min_legs"]
    MAX_LEGS        = params["max_legs"]
    TIER            = params["tier"]
    MIN_COV         = 55.0
    MIN_PARLAY_ODDS = 600
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

    score_legs_composite(eligible, team_to_blocked=team_to_blocked, role="swing")

    # Filter poison/non-qualifying overs; tag risky overs for B&B constraint.
    eligible = filter_and_tag_legs(eligible)
    if not eligible:
        return []

    pool = sorted(eligible, key=lambda l: l.get("composite_score", 0.0), reverse=True)[:POOL_SIZE]

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

    MAX_RISKY_OVERS = 1

    def _bnb(rem, idx, legs, p, by_pid, by_game, in_parlay, risky_overs):
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

            # Max 1 risky over per parlay
            is_risky = leg.get("is_risky_over", False)
            if is_risky and risky_overs >= MAX_RISKY_OVERS:
                continue

            # ── Add leg ────────────────────────────────────────────────────────
            if not is_pitcher:
                by_pid[pid] = True
            by_game[gk] = by_game.get(gk, 0) + 1
            legs.append(leg)
            in_parlay.add(odd_id)
            new_risky = risky_overs + (1 if is_risky else 0)

            _bnb(rem - 1, i + 1, legs, p * leg["_dec"], by_pid, by_game, in_parlay, new_risky)

            # ── Remove leg ─────────────────────────────────────────────────────
            legs.pop()
            in_parlay.discard(odd_id)
            by_game[gk] -= 1
            if by_game[gk] == 0:
                del by_game[gk]
            if not is_pitcher:
                del by_pid[pid]

    for n_legs in range(MIN_LEGS, MAX_LEGS + 1):
        _bnb(n_legs, 0, [], 1.0, {}, {}, set(), 0)
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

    return diverse
