"""
Enriched coverage-based leg scorer.

Based on simple_scorer.py with three additional signals layered on top.
Do NOT modify simple_scorer.py.

Validated prop scope: hits o/u 0.5, strikeouts o 0.5 (hitter only).

Additional signals:
  1. Blended ERA Rank      — season ERA rank blended with pitcher's last-3-start ERA (hits only)
  2. Opponent-Specific Coverage — batter's hit rate vs tonight's specific opponent
  3. Ballpark Factor Adjustment — park run/HR factor applied to composite score
"""

from src.apis.mlb_stats import get_batter_game_log, get_pitcher_game_log
from src.apis.pitcher_stats import get_pitcher_ranks
from src.utils.db import get_conn

# Prop type → stat key in batter game log (mirrors coverage.py PROP_STAT_MAP)
_PROP_STAT_MAP = {
    "hits":        "hits",
    "strikeouts":  "strikeOuts",
    "totalBases":  "totalBases",   # added Jun 25, 2026 — enables opponent-specific
                                   # coverage calculation for TB props
}

_ballpark_cache: dict | None = None

# ── Absolute-value matchup scoring constants ──────────────────────────────────
# Ranges derived from actual mlb_scored_legs data (p5–p95, 11k+ legs, May–Jul 2026)
# K/9 range confirmed by user 2026-07-10.
_ERA_MID,   _ERA_HALF   = 4.25, 2.75   # range 1.50–7.00
_WHIP_MID,  _WHIP_HALF  = 1.20, 0.50   # range 0.70–1.70
_K9_MID,    _K9_HALF    = 8.25, 2.75   # range 5.50–11.00  (user-confirmed 2026-07-10)
# Batter ranges: league-wide qualified-hitter estimates; validate after first shadow run.
_OBP_MID,   _OBP_HALF   = 0.350, 0.070  # range 0.28–0.42
_BA_MID,    _BA_HALF    = 0.265, 0.055  # range 0.21–0.32
_KPCT_MID,  _KPCT_HALF  = 0.220, 0.100  # range 0.12–0.32
_BBPCT_MID, _BBPCT_HALF = 0.090, 0.050  # range 0.04–0.14

# ── Stack bonus constants ─────────────────────────────────────────────────────

STACK_VULNERABILITY_THRESHOLD = 0.60   # bottom ~40% of the actual rank pool
STACK_BONUS                   = 4.0    # points added to composite_score per stack leg
STACK_MIN_LEGS                = 2      # minimum same-team legs to qualify as a stack

# Only props where a vulnerable (bad) pitcher helps the bet qualify for stacking
STACK_ELIGIBLE_PROPS = {
    ("hits", "over"),         # bad pitcher → more hits → over hits
    # Future: ("totalBases", "over"), ("rbi", "over") if added to whitelist
}


# ── Linear adjustment helpers ────────────────────────────────────────────────

def _clamp(val: float, limit: float) -> float:
    return max(-limit, min(limit, val))


def _linear_adj(value: float | None, midpoint: float, half_range: float, max_weight: float) -> float:
    """
    Standard linear scoring adjustment — clamped to ±max_weight.

    adjustment = ((value − midpoint) / half_range) × max_weight

    Returns 0.0 when value is None (graceful degradation for missing stats).
    Sign convention: value > midpoint → positive adjustment.
    Flip the return value for factors where below-midpoint should be positive.
    """
    if value is None:
        return 0.0
    return _clamp(((float(value) - midpoint) / half_range) * max_weight, max_weight)


# ── Batter season stats ───────────────────────────────────────────────────────

def _compute_batter_season_stats(leg: dict, season: int) -> dict | None:
    """
    Compute season-to-date BA, OBP, K%, BB% from the batter's game log.

    Field names confirmed against live MLB-StatsAPI gameLog response 2026-07-10:
    atBats, hits, baseOnBalls, strikeOuts, plateAppearances, hitByPitch
    are all present in each split's stat dict.

    Requires ≥50 plate appearances; returns None for small samples / no data.
    """
    player_id = leg.get("player_id")
    if not player_id:
        return None
    try:
        game_log = get_batter_game_log(int(player_id), season)
    except Exception:
        return None
    if not game_log:
        return None

    ab = hits = bb = so = pa = hbp = 0
    for g in game_log:
        s = g.get("stat", {})
        try:
            ab  += int(s.get("atBats",           0) or 0)
            hits += int(s.get("hits",             0) or 0)
            bb  += int(s.get("baseOnBalls",       0) or 0)
            so  += int(s.get("strikeOuts",        0) or 0)
            pa  += int(s.get("plateAppearances",  0) or 0)
            hbp += int(s.get("hitByPitch",        0) or 0)
        except (ValueError, TypeError):
            pass

    if pa < 50:
        return None

    return {
        "ba":     hits / ab if ab > 0 else None,
        "obp":    (hits + bb + hbp) / pa,
        "k_pct":  so / pa,
        "bb_pct": bb / pa,
    }


# ── Absolute-value matchup adjustment ────────────────────────────────────────

def _compute_matchup_adjustment(
    stat: str,
    direction: str,
    era: float | None,
    whip: float | None,
    k9: float | None,
    batter_stats: dict | None,
) -> tuple[float, dict]:
    """
    Compute absolute-value matchup adjustment using linear scale formulas.

    Per-prop weight table and combined caps (from session 19 build prompt):
      hits/over:        ERA ±5, WHIP ±3 (weak pitcher → +)   combined cap ±7
      hits/under:       ERA ±5, WHIP ±3 (elite pitcher → +)  combined cap ±7
      strikeouts/over:  K/9 ±5 (high K/9 → +)                combined cap ±5
      totalBases/under: Pitcher ERA ±4, WHIP ±2, K/9 ±1 +
                        Batter OBP ±2, K% ±1.5, BB% ±1, BA ±0.5  combined cap ±12

    For hits/over and hits/under: when the sum of individually-clamped factors
    exceeds ±7, both factors are scaled proportionally (not hard-clipped).

    Returns (total_adjustment, debug_fields_dict).
    """
    debug: dict = {}

    if stat == "hits":
        # Weak pitcher (high ERA/WHIP) → positive for over; elite → positive for under
        sign = 1.0 if direction == "over" else -1.0
        era_adj  = _linear_adj(era,  _ERA_MID,  _ERA_HALF,  5.0) * sign
        whip_adj = _linear_adj(whip, _WHIP_MID, _WHIP_HALF, 3.0) * sign
        raw = era_adj + whip_adj
        cap = 7.0
        if abs(raw) > cap and raw != 0.0:
            scale    = cap / abs(raw)
            era_adj  *= scale
            whip_adj *= scale
        debug["matchup_era_adj"]  = round(era_adj,  2)
        debug["matchup_whip_adj"] = round(whip_adj, 2)
        return era_adj + whip_adj, debug

    if stat == "strikeouts" and direction == "over":
        # High K/9 → positive
        k9_adj = _linear_adj(k9, _K9_MID, _K9_HALF, 5.0)
        debug["matchup_k9_adj"] = round(k9_adj, 2)
        return k9_adj, debug

    if stat == "totalBases" and direction == "under":
        # Elite pitcher → positive (low ERA/WHIP, high K/9 → +)
        era_adj  = -_linear_adj(era,  _ERA_MID,  _ERA_HALF,  4.0)
        whip_adj = -_linear_adj(whip, _WHIP_MID, _WHIP_HALF, 2.0)
        k9_adj   =  _linear_adj(k9,   _K9_MID,   _K9_HALF,   1.0)
        debug["matchup_era_adj"]  = round(era_adj,  2)
        debug["matchup_whip_adj"] = round(whip_adj, 2)
        debug["matchup_k9_adj"]   = round(k9_adj,   2)

        # Weak batter → positive (low OBP/BA/BB%, high K% → fewer total bases)
        batter_total = 0.0
        if batter_stats:
            obp_adj  = -_linear_adj(batter_stats.get("obp"),   _OBP_MID,   _OBP_HALF,   2.0)
            k_adj    =  _linear_adj(batter_stats.get("k_pct"), _KPCT_MID,  _KPCT_HALF,  1.5)
            bb_adj   = -_linear_adj(batter_stats.get("bb_pct"),_BBPCT_MID, _BBPCT_HALF, 1.0)
            ba_adj   = -_linear_adj(batter_stats.get("ba"),    _BA_MID,    _BA_HALF,    0.5)
            batter_total = obp_adj + k_adj + bb_adj + ba_adj
            debug["matchup_batter_adj"] = round(batter_total, 2)

        total = _clamp(era_adj + whip_adj + k9_adj + batter_total, 12.0)
        return total, debug

    # Prop/direction not covered by matchup formulas — no adjustment
    return 0.0, debug


# ── Pitcher vulnerability scoring ─────────────────────────────────────────────

def pitcher_vulnerability(
    leg: dict,
    max_era_rank: int = 0,
    max_k9_rank: int = 0,
    max_whip_rank: int = 0,
) -> float | None:
    """
    Returns a vulnerability score in [0, 1] where 1.0 = weakest possible pitcher.

    Rank convention (all three stats): rank 1 = best pitcher, max rank = worst.
      - ERA rank 1  = lowest ERA = toughest to score against
      - K/9 rank 1  = highest K/9 = most strikeouts = toughest to hit against
      - WHIP rank 1 = lowest WHIP = fewest baserunners

    All three: (rank - 1) / (max_rank - 1) → high rank = more vulnerable.

    Returns None if insufficient data to score.
    """
    def _get_rank(leg: dict, opp_key: str, fallback_key: str):
        v = leg.get(opp_key)
        return v if v is not None else leg.get(fallback_key)

    era_rank  = _get_rank(leg, "opp_pitcher_era_rank",  "pitcher_era_rank")
    k9_rank   = _get_rank(leg, "opp_pitcher_k9_rank",   "pitcher_k9_rank")
    whip_rank = _get_rank(leg, "opp_pitcher_whip_rank", "pitcher_whip_rank")

    scores = []
    if era_rank is not None and max_era_rank > 1:
        scores.append((era_rank - 1) / (max_era_rank - 1))
    if k9_rank is not None and max_k9_rank > 1:
        scores.append((k9_rank - 1) / (max_k9_rank - 1))
    if whip_rank is not None and max_whip_rank > 1:
        scores.append((whip_rank - 1) / (max_whip_rank - 1))

    if not scores:
        # Fall back to raw ERA if ranks missing (98% populated)
        era = leg.get("pitcher_era")
        if era is not None:
            # ERA > 4.50 = vulnerable; normalize roughly to [0,1] capped at ERA 7.0
            return min(float(era) / 7.0, 1.0)
        return None                                  # truly no data — no score

    return sum(scores) / len(scores)               # average of available signals


# ── Ballpark factor cache ─────────────────────────────────────────────────────

def _load_ballpark_factors() -> dict:
    """Load ballpark_factors table once per pipeline run, keyed by team_abbrev."""
    global _ballpark_cache
    if _ballpark_cache is not None:
        return _ballpark_cache
    try:
        conn = get_conn()
        cur = conn.cursor()
        cur.execute("SELECT team_abbrev, run_factor, hr_factor FROM ballpark_factors")
        rows = cur.fetchall()
        cur.close()
        conn.close()
        _ballpark_cache = {row["team_abbrev"]: dict(row) for row in rows}
        print(f"[enriched_scorer] Loaded {len(_ballpark_cache)} ballpark factors")
    except Exception as e:
        print(f"[enriched_scorer] Failed to load ballpark factors: {e}")
        _ballpark_cache = {}
    return _ballpark_cache


def reset_ballpark_cache():
    """Reset cache so the next pipeline run forces a fresh DB load."""
    global _ballpark_cache
    _ballpark_cache = None


# ── IP parsing (mirrors pitcher_stats._parse_ip) ─────────────────────────────

def _parse_ip(raw) -> float:
    """Convert MLB API '6.1' format (6⅓ innings) to a float."""
    try:
        parts = str(raw).split(".")
        full = int(parts[0])
        thirds = int(parts[1]) if len(parts) > 1 else 0
        return full + thirds / 3.0
    except (ValueError, TypeError, IndexError):
        return 0.0


# ── Signal 1: Blended ERA Rank ────────────────────────────────────────────────

def _compute_blended_era_rank(
    leg: dict,
    pitcher_ranks: dict,
    season: int,
) -> tuple[float | None, int | None]:
    """
    Compute blended_era_rank = (season_era_rank * 0.5) + (recent_era_rank * 0.5).

    recent_era_rank is derived from the pitcher's last 1–3 starts.
    Rank 1 = best (lowest ERA), rank N = worst (highest ERA).

    Returns (blended_era_rank, recent_form_rank) or (None, None) on failure.
    Edge cases:
      - Fewer than 3 starts: uses available starts (min 1).
      - Zero starts (reliever): returns (season_era_rank, None) — no blending.
      - Zero innings pitched: treats recent_era = 9.0.
    """
    # Opposing pitcher for hitter legs
    pitcher_id = leg.get("pitcher_id") or leg.get("opposing_pitcher_id")
    if not pitcher_id:
        return None, None
    try:
        pitcher_id_int = int(pitcher_id)
    except (ValueError, TypeError):
        return None, None

    p_ranks = pitcher_ranks.get(pitcher_id_int, {})
    era_rank = p_ranks.get("era_rank")
    if era_rank is None:
        # Not a qualified starter in pitcher_ranks — skip blending
        return None, None

    # Fetch game log for recent-start form
    try:
        game_log = get_pitcher_game_log(pitcher_id_int, season)
    except Exception:
        normalized_solo = 1 + (era_rank - 1) * (29.0 / (max(len(pitcher_ranks), 30) - 1))
        return round(max(1.0, min(30.0, normalized_solo)), 1), None

    if not game_log:
        normalized_solo = 1 + (era_rank - 1) * (29.0 / (max(len(pitcher_ranks), 30) - 1))
        return round(max(1.0, min(30.0, normalized_solo)), 1), None

    # Filter to starts only (gamesStarted == 1 in the stat dict)
    starts = [
        g for g in game_log
        if int(g.get("stat", {}).get("gamesStarted", 0) or 0) == 1
    ]
    if not starts:
        # Reliever — no starts, use season ERA rank only (no blending)
        normalized_solo = 1 + (era_rank - 1) * (29.0 / (max(len(pitcher_ranks), 30) - 1))
        return round(max(1.0, min(30.0, normalized_solo)), 1), None

    # Last 3 starts (game_log is oldest-first so last element = most recent)
    recent = starts[-3:]

    total_er = sum(float(g.get("stat", {}).get("earnedRuns", 0) or 0) for g in recent)
    total_ip = sum(_parse_ip(g.get("stat", {}).get("inningsPitched", "0")) for g in recent)
    recent_era = (total_er * 9.0) / total_ip if total_ip > 0 else 9.0

    # Convert recent_era to a 1–N rank using 1.5–7.5 ERA range normalization
    n = max(len(pitcher_ranks), 30)
    ERA_MIN, ERA_MAX = 1.5, 7.5
    norm = max(0.0, min(1.0, (recent_era - ERA_MIN) / (ERA_MAX - ERA_MIN)))
    recent_era_rank = max(1, min(n, round(1 + norm * (n - 1))))

    raw_blended = (era_rank * 0.5) + (recent_era_rank * 0.5)
    # Normalize raw_blended (which is on a 1-N scale where N = pool size,
    # currently ~192) back to a 1-30 scale so downstream bucket thresholds
    # (elite ≤10, avg 11-20, weak 21+) are meaningful regardless of pool size.
    normalized = 1 + (raw_blended - 1) * (29.0 / (n - 1)) if n > 1 else raw_blended
    blended_normalized = round(max(1.0, min(30.0, normalized)), 1)
    return blended_normalized, recent_era_rank


# ── Signal 2: Opponent-Specific Coverage Split ───────────────────────────────

def _compute_coverage_vs_opponent(
    leg: dict,
    season: int,
    opp_team_id: int | None,
) -> tuple[float | None, int]:
    """
    Compute batter's direction-aware coverage rate vs tonight's opponent team.

    Requires minimum 3 games vs that opponent.
    Returns (coverage_vs_opponent_pct, games_count) or (None, 0).
    """
    player_id = leg.get("player_id")
    stat = leg.get("stat", "")
    direction = leg.get("direction", "over")
    best_line = leg.get("best_line")
    stat_key = _PROP_STAT_MAP.get(stat)

    if not player_id or best_line is None or stat_key is None or opp_team_id is None:
        return None, 0

    try:
        game_log = get_batter_game_log(int(player_id), season)
    except Exception:
        return None, 0

    if not game_log:
        return None, 0

    # Filter to games vs tonight's opponent by team ID
    opp_games = [
        g for g in game_log
        if g.get("opponent", {}).get("id") == opp_team_id
    ]

    if len(opp_games) < 3:
        return None, len(opp_games)

    # Compute direction-aware hit rate (same logic as coverage_overall)
    hits = 0
    total = 0
    for g in opp_games:
        val = g.get("stat", {}).get(stat_key)
        if val is None:
            continue
        try:
            val = float(val)
        except (ValueError, TypeError):
            continue
        if direction == "over":
            hits += 1 if val > float(best_line) else 0
        else:
            hits += 1 if val < float(best_line) else 0
        total += 1

    if total < 3:
        return None, total

    return (hits / total) * 100.0, total


# ── Signal 3: Ballpark Factor Adjustment ─────────────────────────────────────

def _compute_park_adjustment(
    leg: dict,
    home_team_abbr: str | None,
    ballpark_factors: dict,
) -> tuple[float | None, float | None]:
    """
    Compute park factor adjustment based on the home team's ballpark.

    Hitter run props:  park_adjustment = (run_factor - 100) / 100 * 5
    Home run props:    park_adjustment = (hr_factor  - 100) / 100 * 5
    Pitcher props:     park_adjustment = (100 - run_factor) / 100 * 3

    Returns (park_factor, park_adjustment) or (None, None) if home team unknown.
    """
    if not home_team_abbr:
        return None, None

    factors = ballpark_factors.get(home_team_abbr)
    if not factors:
        return None, None

    run_factor = factors.get("run_factor")
    hr_factor = factors.get("hr_factor")
    if run_factor is None:
        return None, None

    stat = leg.get("stat", "")
    position = leg.get("position", "")

    if stat == "hits":
        return float(run_factor), (run_factor - 100) / 100 * 5
    elif stat == "strikeouts":
        return float(run_factor), (100 - run_factor) / 100 * 3
    elif stat == "totalBases":
        # Same formula as hits — hitter parks (Coors 115) produce more total bases.
        # Direction inversion (under vs over) is handled by the caller.
        return float(run_factor), (run_factor - 100) / 100 * 5
    else:
        return None, None


# ── Core scorer ───────────────────────────────────────────────────────────────

def _calculate_enriched_score(
    leg: dict,
    season: int,
    pitcher_ranks: dict,
    ballpark_factors: dict,
    opp_team_id: int | None,
    home_team_abbr: str | None,
) -> dict | None:
    """
    Compute enriched composite score for one leg.

    Returns a dict of enriched fields to merge into the leg dict,
    or None if the leg should be excluded entirely (e.g. totalBases non-1.5 line).
    """
    enriched = {}

    # ── Base score (mirrors simple_scorer.calculate_composite_score) ──────────
    base_score = leg.get("coverage_overall") or leg.get("coverage_pct", 50)
    score = base_score

    # coverage_vs_hand as delta adjustment — not a base replacement
    coverage_vs_hand = leg.get("coverage_vs_hand")
    if coverage_vs_hand is not None:
        delta = (coverage_vs_hand - base_score) * 0.3
        score += max(-3.0, min(3.0, delta))

    # Consistency signal (mirrors simple_scorer)
    recent_10 = leg.get("coverage_recent_10")
    coverage_overall = leg.get("coverage_overall")
    if recent_10 is not None and coverage_overall is not None:
        gap = coverage_overall - recent_10
        if gap >= 20:
            score -= 6    # severe cold streak (-5.7pp actual win rate drop)
        elif gap >= 12:
            score -= 4    # moderate cold streak (-4.6pp)
        elif gap >= 6:
            score -= 2    # mild cold streak (-2.8pp)
        elif gap <= -10:
            score += 2    # meaningfully hot (+1.9pp)
        elif gap <= -5:
            score += 1    # warm (+1.4pp)
        else:
            score += 0    # neutral/consistent — no adjustment

    stat = leg.get("stat", "")
    direction = leg.get("direction", "over")

    # Line gate: totalBases is only meaningful at the 1.5 line
    if stat == "totalBases" and leg.get("best_line") != 1.5:
        return None

    # ── Signal 1: Blended ERA rank (stored as metadata, no longer drives scoring) ─
    blended_era_rank, recent_form_rank = _compute_blended_era_rank(
        leg, pitcher_ranks, season
    )
    enriched["blended_era_rank"] = blended_era_rank
    enriched["recent_form_rank"] = recent_form_rank

    # ── Matchup adjustment (absolute-value linear scale, Session 19) ──────────
    raw_era  = leg.get("pitcher_era")
    raw_whip = leg.get("pitcher_whip")
    raw_k9   = leg.get("pitcher_k9")

    batter_stats: dict | None = None
    if stat == "totalBases" and direction == "under":
        batter_stats = _compute_batter_season_stats(leg, season)

    matchup_adj, matchup_debug = _compute_matchup_adjustment(
        stat, direction, raw_era, raw_whip, raw_k9, batter_stats
    )

    score += matchup_adj
    enriched.update(matchup_debug)
    enriched["matchup_adj"] = round(matchup_adj, 2)

    # Lineup stability (unchanged from simple_scorer)
    lineup_consistency = leg.get("lineup_consistency")
    if lineup_consistency is not None and lineup_consistency < 0.50:
        score -= 5

    # ── Signal 2: Opponent-specific coverage delta ────────────────────────────
    coverage_vs_opp, games_vs_opp = _compute_coverage_vs_opponent(
        leg, season, opp_team_id
    )
    enriched["coverage_vs_opponent"] = coverage_vs_opp
    enriched["games_vs_opponent"] = games_vs_opp

    if coverage_vs_opp is not None:
        coverage_overall = leg.get("coverage_overall") or leg.get("coverage_pct", 50)
        delta = coverage_vs_opp - coverage_overall
        opp_adj = max(-8.0, min(8.0, delta * 0.25))  # 25% of delta, capped ±8
        score += opp_adj

    # ── Signal 3: Ballpark factor ─────────────────────────────────────────────
    park_factor, park_adjustment = _compute_park_adjustment(
        leg, home_team_abbr, ballpark_factors
    )
    enriched["park_factor"] = park_factor
    enriched["park_adjustment"] = park_adjustment

    if park_adjustment is not None:
        # Invert for under props: a hitter-friendly park (high run_factor)
        # boosts overs but hurts unders — the raw park_adjustment is always
        # computed as a positive value for hitter parks, so flip the sign.
        if direction == "under":
            score -= park_adjustment
        else:
            score += park_adjustment

    enriched.setdefault("matchup_adj",         None)
    enriched.setdefault("matchup_era_adj",     None)
    enriched.setdefault("matchup_whip_adj",    None)
    enriched.setdefault("matchup_k9_adj",      None)
    enriched.setdefault("matchup_batter_adj",  None)
    enriched["composite_score"] = max(5.0, min(95.0, score))
    return enriched


# ── Public entry point ────────────────────────────────────────────────────────

def score_legs(
    legs: list[dict],
    season: int,
    pitcher_ranks: dict | None = None,
    ballpark_factors: dict | None = None,
    abbr_to_team_id: dict | None = None,
    game_pk_to_home_abbr: dict | None = None,
    today_starter_ranks: dict | None = None,   # ← add this
) -> list[dict]:
    """
    Score all legs using enriched signals. Mutates legs in-place.

    Args:
        legs: Leg dicts already enriched by the production pipeline.
        season: MLB season year (e.g. 2026).
        pitcher_ranks: {pitcher_id_int: {era_rank, k9_rank, whip_rank}}.
                       Fetched via get_pitcher_ranks() if None (uses 24h cache).
        ballpark_factors: {team_abbrev: {run_factor, hr_factor}}.
                          Loaded from DB if None.
        abbr_to_team_id: {team_abbrev: team_id} for opponent matching.
        game_pk_to_home_abbr: {game_pk: home_team_abbr} for park factor lookup.

    Returns:
        Same legs list with enriched composite_score and new fields.
    """
    print("[enriched_scorer] Consistency signal: applied independently ✓")

    if pitcher_ranks is None:
        pitcher_ranks = get_pitcher_ranks(season)
    if ballpark_factors is None:
        ballpark_factors = _load_ballpark_factors()
    if abbr_to_team_id is None:
        abbr_to_team_id = {}
    if game_pk_to_home_abbr is None:
        game_pk_to_home_abbr = {}

    # Override opp_pitcher_*_rank with today's starter-only ranks where available
    if today_starter_ranks:
        for leg in legs:
            opp_id = leg.get("opposing_pitcher_id") or leg.get("pitcher_id")
            if opp_id:
                try:
                    today = today_starter_ranks.get(int(opp_id), {})
                    if today.get("era_rank") is not None:
                        leg["opp_pitcher_era_rank"] = today["era_rank"]
                    if today.get("k9_rank") is not None:
                        leg["opp_pitcher_k9_rank"] = today["k9_rank"]
                    if today.get("whip_rank") is not None:
                        leg["opp_pitcher_whip_rank"] = today["whip_rank"]
                except (ValueError, TypeError):
                    pass

    for leg in legs:
        opp_abbr = leg.get("opponent", "")
        opp_team_id = abbr_to_team_id.get(opp_abbr) if opp_abbr else None

        game_pk = leg.get("game_pk")
        home_team_abbr = game_pk_to_home_abbr.get(game_pk) if game_pk else None

        try:
            enriched_fields = _calculate_enriched_score(
                leg=leg,
                season=season,
                pitcher_ranks=pitcher_ranks,
                ballpark_factors=ballpark_factors,
                opp_team_id=opp_team_id,
                home_team_abbr=home_team_abbr,
            )
            if enriched_fields is None:
                # Leg excluded by line gate (e.g. totalBases non-1.5 line)
                leg["composite_score"] = None
                leg.setdefault("matchup_adj", None)
            else:
                leg.update(enriched_fields)
        except Exception as e:
            # Per-leg failure must not crash the pipeline — keep original score
            print(f"[enriched_scorer] Score failed for {leg.get('player_name')}: {e}")
            leg.setdefault("composite_score", leg.get("composite_score", 50.0))
            leg.setdefault("coverage_vs_opponent", None)
            leg.setdefault("games_vs_opponent", 0)
            leg.setdefault("park_factor", None)
            leg.setdefault("park_adjustment", None)
            leg.setdefault("blended_era_rank", None)
            leg.setdefault("recent_form_rank", None)
            leg.setdefault("matchup_adj", None)

    if legs:
        scores = [l["composite_score"] for l in legs if l.get("composite_score") is not None]
        if scores:
            print(
                f"[enriched_scorer] Scored {len(legs)} legs | "
                f"avg={sum(scores)/len(scores):.1f} | "
                f"min={min(scores):.1f} | max={max(scores):.1f}"
            )

    return legs
