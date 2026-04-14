import time
from itertools import combinations
from collections import defaultdict, Counter
from src.utils.odds_math import american_to_decimal
from src.engine.coverage import get_game_log, get_player_id, calc_stat_value
from src.engine.leg_scorer import score_legs_composite

MAX_LEG_ODDS = -200
MIN_PARLAY_ODDS = 500
MAX_PARLAY_ODDS = 3000
MAX_LEGS = 6
TOP_PARLAYS = 5
COMBINED_THRESHOLD = 90.0

def _stat_components(stat: str) -> set:
    """Return the individual stat names that make up a (possibly combined) stat."""
    return set(stat.split("+")) if "+" in stat else {stat}

def stats_overlap(stat_a: str, stat_b: str) -> bool:
    """True if two stat strings share any component — means sportsbook won't allow both."""
    return bool(_stat_components(stat_a) & _stat_components(stat_b))

def legs_are_compatible(leg_a: dict, leg_b: dict) -> bool:
    """Two legs from the same player are compatible only if their stats don't overlap."""
    if leg_a.get("player_id") != leg_b.get("player_id"):
        return True  # different players, always fine
    return not stats_overlap(leg_a["stat"], leg_b["stat"])

def is_within_odds_cap(odds_str):
    if not odds_str:
        return False
    odds = int(str(odds_str).replace("+", ""))
    if odds > 0:
        return True
    return odds >= MAX_LEG_ODDS

def parlay_american_odds(legs):
    decimal = 1.0
    for leg in legs:
        decimal *= american_to_decimal(str(leg["best_odds"]))
    return int((decimal - 1) * 100)

def avg_coverage(legs):
    return round(sum(l["coverage_pct"] for l in legs) / len(legs), 1)

def combined_hit_rate(games, legs):
    if not games:
        return 0.0
    hit = 0
    for game in games:
        if all(
            calc_stat_value(game, leg["stat"]) is not None and
            calc_stat_value(game, leg["stat"]) > leg["best_line"]
            for leg in legs
        ):
            hit += 1
    return round((hit / len(games)) * 100, 1)

def _compatible_subset(legs: list) -> list:
    """Filter a list of same-player legs to a mutually compatible subset.
    Greedily keeps the highest-coverage leg and drops anything that overlaps with it."""
    if len(legs) <= 1:
        return legs
    # Sort by coverage descending so we keep the best legs first
    sorted_legs = sorted(legs, key=lambda x: x["coverage_pct"], reverse=True)
    kept = [sorted_legs[0]]
    for candidate in sorted_legs[1:]:
        if all(not stats_overlap(candidate["stat"], k["stat"]) for k in kept):
            kept.append(candidate)
    return kept

def best_player_legs(pid, player_legs):
    # First remove any stat-overlapping legs — sportsbook won't allow them together
    player_legs = _compatible_subset(player_legs)
    if len(player_legs) == 1:
        return player_legs

    nba_id = get_player_id(pid)
    if not nba_id:
        return [max(player_legs, key=lambda x: x["coverage_pct"])]
    games = get_game_log(nba_id)
    if not games:
        return [max(player_legs, key=lambda x: x["coverage_pct"])]

    rate_all = combined_hit_rate(games, player_legs)
    if rate_all >= COMBINED_THRESHOLD:
        return player_legs
    if len(player_legs) >= 3:
        best_pair = None
        best_rate = 0.0
        for pair in combinations(player_legs, 2):
            rate = combined_hit_rate(games, list(pair))
            if rate >= COMBINED_THRESHOLD and rate > best_rate:
                best_rate = rate
                best_pair = list(pair)
        if best_pair:
            return best_pair
    return [max(player_legs, key=lambda x: x["coverage_pct"])]

def validate_and_trim(legs):
    by_player = defaultdict(list)
    for leg in legs:
        pid = leg.get("player_id")
        if pid:
            by_player[pid].append(leg)
    final_legs = []
    for pid, player_legs in by_player.items():
        final_legs.extend(best_player_legs(pid, player_legs))
    return final_legs

def build_parlays(qualifying_legs):
    eligible = [l for l in qualifying_legs if is_within_odds_cap(l["best_odds"])]
    eligible.sort(key=lambda x: x["coverage_pct"], reverse=True)
    if len(eligible) < 2:
        return []
    valid_parlays = []

    def build(current_legs, remaining):
        if len(current_legs) >= 2:
            trimmed = validate_and_trim(current_legs)
            if len(trimmed) >= 2:
                odds = parlay_american_odds(trimmed)
                if MIN_PARLAY_ODDS <= odds <= MAX_PARLAY_ODDS:
                    valid_parlays.append({
                        "legs": trimmed,
                        "parlay_odds": f"+{odds}",
                        "num_legs": len(trimmed),
                        "avg_coverage": avg_coverage(trimmed),
                        "confidence": round(
                            (avg_coverage(trimmed) / 100) ** len(trimmed) * 100, 2
                        )
                    })
        if len(current_legs) >= MAX_LEGS:
            return
        for i, leg in enumerate(remaining):
            build(current_legs + [leg], remaining[i+1:])

    build([], eligible[:6])
    seen = set()
    unique_parlays = []
    for p in valid_parlays:
        key = frozenset(l["odd_id"] for l in p["legs"])
        if key not in seen:
            seen.add(key)
            unique_parlays.append(p)
    unique_parlays.sort(key=lambda x: (-x["avg_coverage"], -x["confidence"]))
    return unique_parlays[:TOP_PARLAYS]

# ── Hybrid Parlay Builder ─────────────────────────────────────────────────────

def _tier_params(num_games: int) -> dict | None:
    """
    Return constraint params for the hybrid builder based on today's slate size.

    Larger slates have more legs to choose from, so we can afford strict filters.
    Smaller slates relax coverage floors to surface valid parlays on thin schedules.

    Returns None for Tier 4 (≤1 game) — no point building parlays on a near-empty slate.
    """
    if num_games >= 10:
        # Tier 1 — full slate (MLB: 10+ games), strictest filters
        return dict(anchor_min_cov=70.0, swing_min_cov=55.0, min_anchors=2, tier=1)
    elif num_games >= 5:
        # Tier 2 — moderate slate, relaxed swing coverage floor
        return dict(anchor_min_cov=70.0, swing_min_cov=45.0, min_anchors=2, tier=2)
    elif num_games >= 2:
        # Tier 3 — thin slate, further relaxed to find any valid parlays
        return dict(anchor_min_cov=70.0, swing_min_cov=40.0, min_anchors=2, tier=3)
    else:
        # Tier 4 — 0 or 1 game, not enough to build a parlay
        return None


def build_hybrid_parlays(all_legs, raw_props=None, top_n=5, num_games=15, blocked_players=None, team_to_blocked=None):
    """
    Build hybrid parlays from two pools: anchors and swings.

    Anchor pool: coverage >= anchor_min_cov AND trend_pass=True AND odds -500 to -100.
    Swing pool:  coverage >= swing_min_cov AND odds -150 to +250.

    Parlay structure: 2–4 anchors + exactly 2 swings = 4–6 legs total.
    Target odds window: +1100 to +2000.

    Legs are ranked within each pool by composite_score from leg_scorer.py:
      40% recency-weighted coverage + 25% EV + 15% trend + 15% opponent + 5% teammate injury

    DraftKings overlap rules are enforced: max 2 legs per player per parlay,
    no two same-player legs may share a stat component, and no leg may occupy
    both anchor and swing slots in the same parlay (deduplicated by odd_id).

    Thresholds scale with slate size via _tier_params():
      Tier 1 (10+ games): anchor 70%, swing 55%
      Tier 2 (5–9 games):  anchor 70%, swing 45%
      Tier 3 (2–4 games):  anchor 70%, swing 40%
      Tier 4 (≤1 game):   returns [] immediately

    raw_props is accepted for backwards-compatibility but unused — both pools
    are built from all_legs (scored legs with trend signals attached).

    blocked_players: set of player display names currently blocked by the injury
    pipeline.  Used as fallback for teammate injury context via game log cache.

    team_to_blocked: pre-built {team_abbr: count} dict from main.py (preferred).
    When provided, forwarded directly to score_legs_composite and blocked_players
    is ignored for the teammate injury factor.
    """
    params = _tier_params(num_games)
    if params is None:
        return []

    ANCHOR_MIN_COV    = params["anchor_min_cov"]
    SWING_MIN_COV     = params["swing_min_cov"]
    ANCHOR_HEAVY_MIN  = -1000  # heavy bucket lower bound
    ANCHOR_HEAVY_MAX  = -500   # heavy bucket upper bound (2–3 legs)
    ANCHOR_MID_MIN    = -499   # mid bucket lower bound
    ANCHOR_MID_MAX    = -150   # mid bucket upper bound (2–3 legs)
    CONNECTOR_MIN_ODDS = -149  # connector pool lower bound
    CONNECTOR_MAX_ODDS = -100  # connector pool upper bound (top 2 by composite)
    SWING_MIN_ODDS    = 100    # swing odds lower bound (positive-odds only)
    SWING_MAX_ODDS    = 150    # swing odds upper bound
    MIN_ANCHORS       = params["min_anchors"]
    MAX_ANCHORS       = 6
    N_SWINGS          = 2      # always exactly 2 swing legs per parlay
    MIN_PARLAY_ODDS   = 1000
    MAX_PARLAY_ODDS   = 1500
    TIER              = params["tier"]
    MAX_CANDIDATES    = 15
    TIMEOUT_SECS      = 90

    def _odds_int(leg):
        try:
            return int(str(leg.get("best_odds", "0")).replace("+", ""))
        except ValueError:
            return 0

    # ── Pool construction ─────────────────────────────────────────────────────
    # Anchor pool: two tiered buckets by odds (heavy + mid) to enforce diversity.
    # Connector pool: odds -149 to -100 — lighter favourites that bridge anchor
    # juice to swing payout; tried 1-first then 2 as fallback in B&B outer loop.
    # Scoring runs once on the full candidate list before bucketing so
    # composite_score is comparable across buckets.
    all_anchors = [
        l for l in all_legs
        if l.get("best_odds")
        and l.get("coverage_pct", 0) >= ANCHOR_MIN_COV
        and l.get("trend_pass", True)
        and ANCHOR_HEAVY_MIN <= _odds_int(l) <= ANCHOR_MID_MAX
    ]
    score_legs_composite(all_anchors, team_to_blocked=team_to_blocked, role="anchor")

    heavy = sorted(
        [l for l in all_anchors if ANCHOR_HEAVY_MIN <= _odds_int(l) <= ANCHOR_HEAVY_MAX],
        key=lambda l: l.get("composite_score", 0.0), reverse=True)[:3]
    mid   = sorted(
        [l for l in all_anchors if ANCHOR_MID_MIN <= _odds_int(l) <= ANCHOR_MID_MAX],
        key=lambda l: l.get("composite_score", 0.0), reverse=True)[:3]

    anchors = heavy + mid

    # Connector pool: scored with anchor weights, capped at top 2.
    all_connectors = [
        l for l in all_legs
        if l.get("best_odds")
        and l.get("coverage_pct", 0) >= ANCHOR_MIN_COV
        and l.get("trend_pass", True)
        and CONNECTOR_MIN_ODDS <= _odds_int(l) <= CONNECTOR_MAX_ODDS
    ]
    score_legs_composite(all_connectors, team_to_blocked=team_to_blocked, role="anchor")
    connectors = sorted(all_connectors, key=lambda l: l.get("composite_score", 0.0), reverse=True)[:2]

    # Swing pool: positive-odds legs only — these supply parlay payout value.
    swings = [
        l for l in all_legs
        if l.get("best_odds")
        and SWING_MIN_ODDS <= _odds_int(l) <= SWING_MAX_ODDS
        and l.get("coverage_pct", 0) >= SWING_MIN_COV
    ]

    if not anchors or not connectors or not swings:
        return []

    # Swings scored with EV at full weight (25%) since payout value matters there.
    score_legs_composite(swings, team_to_blocked=team_to_blocked, role="swing")
    swings = sorted(swings, key=lambda l: l.get("composite_score", 0.0), reverse=True)[:20]

    from math import comb
    total_combos = sum(
        comb(len(anchors), n_a) * comb(len(connectors), n_c) * comb(len(swings), N_SWINGS)
        for n_a in range(MIN_ANCHORS, MAX_ANCHORS + 1)
        for n_c in [1, 2]
    )
    print(f"  [parlay_builder] pools: {len(anchors)} anchors, {len(connectors)} connectors, "
          f"{len(swings)} swings (Tier {TIER})")
    print(f"  [parlay_builder] exhaustive would be: {total_combos:,}")

    parlays = []
    _start_time = time.time()
    _stop = [False]

    # Stamp decimal odds for fast arithmetic; reuse if already present
    for _leg in anchors + connectors + swings:
        if "_dec" not in _leg:
            _leg["_dec"] = american_to_decimal(str(_leg["best_odds"]))

    # B&B bounds require each pool sorted descending by decimal odds
    anchors_bnb    = sorted(anchors,    key=lambda x: x["_dec"], reverse=True)
    connectors_bnb = sorted(connectors, key=lambda x: x["_dec"], reverse=True)
    swings_bnb     = sorted(swings,     key=lambda x: x["_dec"], reverse=True)

    MIN_DECIMAL = MIN_PARLAY_ODDS / 100 + 1
    MAX_DECIMAL = MAX_PARLAY_ODDS / 100 + 1

    # Best possible connector + swing contribution for anchor-phase upper bounds
    _best_connector = connectors_bnb[0]["_dec"] if connectors_bnb else 1.0
    _best_swing = 1.0
    for _j in range(min(N_SWINGS, len(swings_bnb))):
        _best_swing *= swings_bnb[_j]["_dec"]

    total_iters = [0]

    def _can_add(leg, pid, by_pid):
        """Return True if adding leg doesn't violate per-player overlap rules."""
        existing = by_pid.get(pid)
        if not existing:
            return True
        if len(existing) >= 2:
            return False
        return all(not stats_overlap(leg["stat"], el["stat"]) for el in existing)

    def _record(legs_snap, p, n_a):
        odds_val = int((p - 1) * 100)
        avg_cov  = sum(l["coverage_pct"] for l in legs_snap) / len(legs_snap)
        ev_list  = [l["ev_per_unit"] for l in legs_snap if "ev_per_unit" in l]
        avg_ev   = round(sum(ev_list) / len(ev_list), 4) if ev_list else None
        parlays.append({
            "legs":         legs_snap,
            "parlay_odds":  f"+{odds_val}",
            "num_legs":     len(legs_snap),
            "avg_coverage": round(avg_cov, 1),
            "avg_ev":       avg_ev,
            "n_anchors":    n_a,
            "n_swings":     N_SWINGS,
            "parlay_type":  "hybrid",
            "tier":         TIER,
        })
        if len(parlays) >= MAX_CANDIDATES:
            _stop[0] = True

    def _bnb(a_rem, c_rem, l_rem, a_idx, c_idx, l_idx, legs, p, by_pid, in_parlay, swing_pids, n_a):
        """
        Branch-and-bound parlay search.

        Fills anchor slots first (a_rem > 0), then connector slots (c_rem > 0),
        then swing slots (l_rem > 0).
        Prunes branches where:
          - upper bound (best possible completion) < MIN_DECIMAL
          - lower bound (cheapest possible completion) > MAX_DECIMAL
        in_parlay tracks odd_ids already selected to prevent duplicate legs.
        Pools must be sorted descending by _dec for bounds to be valid.
        """
        total_iters[0] += 1

        # ── Terminal: all slots filled ────────────────────────────────────────
        if a_rem == 0 and c_rem == 0 and l_rem == 0:
            odds_val = int((p - 1) * 100)
            if MIN_PARLAY_ODDS <= odds_val <= MAX_PARLAY_ODDS:
                team_counts = Counter(l.get("team", "") for l in legs)
                if max(team_counts.values()) > 2:
                    return
                _record(list(legs), p, n_a)
            return

        # ── Anchor phase ──────────────────────────────────────────────────────
        if a_rem > 0:
            pool = anchors_bnb
            if len(pool) - a_idx < a_rem:
                return  # not enough anchors left to fill remaining slots

            # Upper bound: best a_rem anchors + best connector + best N_SWINGS swings
            ub = p
            for _j in range(a_idx, a_idx + a_rem):
                ub *= pool[_j]["_dec"]
            ub *= _best_connector * _best_swing
            if ub < MIN_DECIMAL:
                return  # whole subtree cannot reach MIN_PARLAY_ODDS

            # Lower bound: worst a_rem anchors + worst connector + worst N_SWINGS swings
            lb = p
            n_sp = len(swings_bnb)
            for _j in range(len(pool) - a_rem, len(pool)):
                lb *= pool[_j]["_dec"]
            if connectors_bnb:
                lb *= connectors_bnb[-1]["_dec"]
            if n_sp >= N_SWINGS:
                lb *= swings_bnb[n_sp - 1]["_dec"] * swings_bnb[n_sp - 2]["_dec"]
            if lb > MAX_DECIMAL:
                return  # cheapest possible completion already busts MAX_PARLAY_ODDS

            for i in range(a_idx, len(pool) - a_rem + 1):
                if _stop[0]:
                    return
                if time.time() - _start_time > TIMEOUT_SECS:
                    _stop[0] = True
                    return
                leg = pool[i]
                pid = leg.get("player_id") or leg.get("player_name", "")
                if not _can_add(leg, pid, by_pid):
                    continue
                by_pid.setdefault(pid, []).append(leg)
                legs.append(leg)
                in_parlay.add(leg.get("odd_id"))
                _bnb(a_rem - 1, c_rem, l_rem, i + 1, c_idx, l_idx, legs, p * leg["_dec"],
                     by_pid, in_parlay, swing_pids, n_a)
                legs.pop()
                in_parlay.discard(leg.get("odd_id"))
                by_pid[pid].pop()
                if not by_pid[pid]:
                    del by_pid[pid]
            return

        # ── Connector phase ───────────────────────────────────────────────────
        if c_rem > 0:
            pool = connectors_bnb
            if len(pool) - c_idx < c_rem:
                return  # not enough connectors left

            # Upper bound: best c_rem remaining connectors + best N_SWINGS swings
            ub = p
            for _j in range(c_idx, c_idx + c_rem):
                ub *= pool[_j]["_dec"]
            ub *= _best_swing
            if ub < MIN_DECIMAL:
                return

            # Lower bound: worst c_rem connectors + worst N_SWINGS swings
            lb = p
            n_sp = len(swings_bnb)
            for _j in range(len(pool) - c_rem, len(pool)):
                lb *= pool[_j]["_dec"]
            if n_sp >= N_SWINGS:
                lb *= swings_bnb[n_sp - 1]["_dec"] * swings_bnb[n_sp - 2]["_dec"]
            if lb > MAX_DECIMAL:
                return

            for i in range(c_idx, len(pool) - c_rem + 1):
                if _stop[0]:
                    return
                if time.time() - _start_time > TIMEOUT_SECS:
                    _stop[0] = True
                    return
                leg = pool[i]
                if leg.get("odd_id") in in_parlay:
                    continue
                pid = leg.get("player_id") or leg.get("player_name", "")
                if not _can_add(leg, pid, by_pid):
                    continue
                by_pid.setdefault(pid, []).append(leg)
                legs.append(leg)
                in_parlay.add(leg.get("odd_id"))
                _bnb(a_rem, c_rem - 1, l_rem, a_idx, i + 1, l_idx, legs, p * leg["_dec"],
                     by_pid, in_parlay, swing_pids, n_a)
                legs.pop()
                in_parlay.discard(leg.get("odd_id"))
                by_pid[pid].pop()
                if not by_pid[pid]:
                    del by_pid[pid]
            return

        # ── Swing phase ───────────────────────────────────────────────────────
        pool = swings_bnb
        if len(pool) - l_idx < l_rem:
            return  # not enough swings left

        # Upper bound: best l_rem remaining swings
        ub = p
        for _j in range(l_idx, l_idx + l_rem):
            ub *= pool[_j]["_dec"]
        if ub < MIN_DECIMAL:
            return

        # Lower bound: worst l_rem swings in pool
        lb = p
        n_sp = len(pool)
        for _j in range(n_sp - l_rem, n_sp):
            lb *= pool[_j]["_dec"]
        if lb > MAX_DECIMAL:
            return

        for i in range(l_idx, len(pool) - l_rem + 1):
            leg = pool[i]
            if leg.get("odd_id") in in_parlay:
                continue  # already selected as anchor/connector; skip to prevent duplicate
            pid = leg.get("player_id") or leg.get("player_name", "")
            if pid in swing_pids:
                continue  # max 1 swing leg per player
            if not _can_add(leg, pid, by_pid):
                continue
            by_pid.setdefault(pid, []).append(leg)
            legs.append(leg)
            in_parlay.add(leg.get("odd_id"))
            swing_pids.add(pid)
            _bnb(a_rem, c_rem, l_rem - 1, a_idx, c_idx, i + 1, legs, p * leg["_dec"],
                 by_pid, in_parlay, swing_pids, n_a)
            legs.pop()
            in_parlay.discard(leg.get("odd_id"))
            by_pid[pid].pop()
            if not by_pid[pid]:
                del by_pid[pid]
            swing_pids.discard(pid)

    # Try n_c=1 connector across all anchor counts first.
    # Only try n_c=2 if no valid parlays were found with n_c=1.
    for n_c_val in [1, 2]:
        for n_a_val in range(MIN_ANCHORS, MAX_ANCHORS + 1):
            _bnb(n_a_val, n_c_val, N_SWINGS, 0, 0, 0, [], 1.0, {}, set(), set(), n_a_val)
            if _stop[0]:
                break
        if parlays:  # found valid parlays with this n_c, don't escalate
            break
        if _stop[0]:
            elapsed = time.time() - _start_time
            if elapsed > TIMEOUT_SECS:
                print(f"  [parlay_builder] ⚠ hard timeout after {elapsed:.1f}s — "
                      f"{len(parlays)} raw parlays found, stopping search")
            else:
                print(f"  [parlay_builder] early exit — {MAX_CANDIDATES} candidates "
                      f"found in {elapsed:.1f}s")
            break

    elapsed = time.time() - _start_time
    print(f"  [parlay_builder] B&B iterations: {total_iters[0]:,}  "
          f"({elapsed:.1f}s, exhaustive would be {total_combos:,})")

    # ── Deduplicate and rank ───────────────────────────────────────────────────
    seen = set()
    unique = []
    for p in sorted(
        parlays,
        key=lambda x: (x["avg_ev"] if x["avg_ev"] is not None else -999, x["avg_coverage"]),
        reverse=True,
    ):
        key = frozenset(l["odd_id"] for l in p["legs"])
        if key not in seen:
            seen.add(key)
            unique.append(p)

    if not unique:
        return []

    # Diversity filter: always keep the best parlay, then only add parlays
    # that share 3 or fewer legs with every already-selected parlay
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
