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
    "hits":       "hits",
    "strikeouts": "strikeOuts",
}

_ballpark_cache: dict | None = None

# ── Stack bonus constants ─────────────────────────────────────────────────────

STACK_VULNERABILITY_THRESHOLD = 0.60   # bottom ~40% of the actual rank pool
STACK_BONUS                   = 4.0    # points added to composite_score per stack leg
STACK_MIN_LEGS                = 2      # minimum same-team legs to qualify as a stack

# Only props where a vulnerable (bad) pitcher helps the bet qualify for stacking
STACK_ELIGIBLE_PROPS = {
    ("hits", "over"),         # bad pitcher → more hits → over hits
    # Future: ("totalBases", "over"), ("rbi", "over") if added to whitelist
}


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

    n = max(len(pitcher_ranks), 2)
    midpoint = (n + 1) / 2.0

    # Line gate: totalBases is only meaningful at the 1.5 line
    if stat == "totalBases" and leg.get("best_line") != 1.5:
        return None

    # ── Signal 1: Blended ERA rank replaces raw pitcher_era in matchup calc ───
    blended_era_rank, recent_form_rank = _compute_blended_era_rank(
        leg, pitcher_ranks, season
    )
    enriched["blended_era_rank"] = blended_era_rank
    enriched["recent_form_rank"] = recent_form_rank

    # K/9 rank signal for strikeouts over props
    # Rank convention: rank 1 = highest K/9 = elite = TOUGH for batter to strike out against
    # High rank = weak K pitcher = favorable for batter SO over
    if stat == "strikeouts" and direction == "over":
        k9_rank = leg.get("opp_pitcher_k9_rank")
        if k9_rank is not None:
            # rank 1 → -5 (elite K pitcher, penalize SO over)
            # rank 15.5 → 0 (neutral)
            # high rank → +5 capped (weak K pitcher, boost SO over)
            k9_adj = round((k9_rank - midpoint) / (midpoint - 1) * 5.0, 1)
            k9_adj = max(-5.0, min(5.0, k9_adj))
            score += k9_adj
            enriched["k9_adj"] = k9_adj

    # Combined pitcher signal for hits props — ERA + K/9 + WHIP each capped ±2
    if stat == "hits":
        pitcher_adj = 0.0

        era_rank = leg.get("opp_pitcher_era_rank")
        if era_rank is not None:
            # High ERA rank = weak pitcher = favorable for hits over
            era_adj = round((era_rank - midpoint) / (midpoint - 1) * 2.0, 1)
            era_adj = max(-2.0, min(2.0, era_adj))
            pitcher_adj += era_adj
            enriched["era_adj"] = era_adj

        k9_rank = leg.get("opp_pitcher_k9_rank")
        if k9_rank is not None:
            # High K/9 rank = weak strikeout pitcher = favorable for hits over
            k9_adj = round((k9_rank - midpoint) / (midpoint - 1) * 2.0, 1)
            k9_adj = max(-2.0, min(2.0, k9_adj))
            pitcher_adj += k9_adj
            enriched["k9_adj"] = k9_adj

        whip_rank = leg.get("opp_pitcher_whip_rank")
        if whip_rank is not None:
            # High WHIP rank = weak pitcher = favorable for hits over
            whip_adj = round((whip_rank - midpoint) / (midpoint - 1) * 2.0, 1)
            whip_adj = max(-2.0, min(2.0, whip_adj))
            pitcher_adj += whip_adj
            enriched["whip_adj"] = whip_adj

        if direction == "under":
            pitcher_adj = -pitcher_adj
            if "era_adj" in enriched:
                enriched["era_adj"] = -enriched["era_adj"]
            if "k9_adj" in enriched:
                enriched["k9_adj"] = -enriched["k9_adj"]
            if "whip_adj" in enriched:
                enriched["whip_adj"] = -enriched["whip_adj"]
        score += pitcher_adj

    # WHIP rank signal for totalBases props
    # Low WHIP (rank 1) = elite pitcher = fewer baserunners = boost UNDER, penalize OVER
    # High WHIP (rank 30) = weak pitcher = more baserunners = boost OVER, penalize UNDER
    if stat == "totalBases":
        whip_rank = leg.get("opp_pitcher_whip_rank")
        if whip_rank is not None:
            # rank 1 → -5, rank 15.5 → 0, rank 30 → +5
            whip_adj = round((whip_rank - midpoint) / (midpoint - 1) * 5.0, 1)
            whip_adj = max(-5.0, min(5.0, whip_adj))
            if direction == "under":
                whip_adj = -whip_adj  # invert: elite WHIP boosts under
            score += whip_adj
            enriched["whip_adj"] = whip_adj

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
        score += park_adjustment

    enriched.setdefault("era_adj", None)
    enriched.setdefault("k9_adj", None)
    enriched.setdefault("whip_adj", None)
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
                leg.setdefault("era_adj", None)
                leg.setdefault("k9_adj", None)
                leg.setdefault("whip_adj", None)
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
            leg.setdefault("era_adj", None)
            leg.setdefault("k9_adj", None)
            leg.setdefault("whip_adj", None)

    if legs:
        scores = [l["composite_score"] for l in legs if l.get("composite_score") is not None]
        if scores:
            print(
                f"[enriched_scorer] Scored {len(legs)} legs | "
                f"avg={sum(scores)/len(scores):.1f} | "
                f"min={min(scores):.1f} | max={max(scores):.1f}"
            )

    return legs
