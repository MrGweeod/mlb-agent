"""
hits_v4.py — Probability model for hits/over 0.5 (P(>=1 hit)).

Replaces composite_score as the *selection* signal for hits/over legs.
composite_score is still computed and stored alongside p_hit for live
comparison (see simple_scorer.py) — it just no longer drives ranking.

────────────────────────────────────────────────────────────────────────────
MODEL
────────────────────────────────────────────────────────────────────────────
    starter_share = min(SP_avg_IP / 9, 1)
    hit_env       = starter_share * f(SP_WHIP, SP_ERA)
                    + (1 - starter_share) * f(BP_WHIP, BP_ERA)
    hit_env_adj   = hit_env * (1 + DER_GAMMA * (LG_DER - opp_DER))
    p_per_AB      = base_rate * platoon_mult * trend_mult
                    * (hit_env_adj / LG_AVG_ENV)
    P(>=1 hit)    = mean over the batter's last-5 observed AB counts k of
                    (1 - (1 - p_per_AB) ** k)

Two design rules are load-bearing and must not be relaxed:

  1. NO STEP FUNCTIONS, NO DEAD BANDS. Every prior scoring term that
     discretized a continuous value destroyed signal — the v3 era_adj
     returned exactly 0 for 70.5% of legs and lineup_adj for 100% of them.
     A 2026-08-11 diagnostic showed correlation with outcome climbing
     monotonically as the ERA term went from discretized to continuous
     (r=0.0065 -> 0.0376; continuous effective_era alone reached r=0.0548).
     Every factor here enters continuously. See ARCHITECTURE_DECISIONS.md §41
     for the superseded shadow implementation.

  2. NO HAND-PICKED CONSTANTS. Every constant below was fitted against
     historical data on games strictly before 2026-07-01, then evaluated
     out-of-sample on 2026-07-01 onward. Where a constant could not be
     derived — or came out indistinguishable from zero — that is recorded
     in its comment rather than papered over with a plausible value.

────────────────────────────────────────────────────────────────────────────
POINT-IN-TIME DISCIPLINE
────────────────────────────────────────────────────────────────────────────
Every feature is computed from games strictly before run_date. Two fields
that look usable are NOT, and both were caught by measuring population on
*unstarted* games rather than on resolved history:

  - mlb_scored_legs.batting_order   — 0% populated before lineups drop.
  - mlb_games.*_probable_pitcher_id — 0% populated on same-day games; it is
    backfilled after the game. It reads 100% on historical rows, which is
    exactly what makes it dangerous. The opposing starter therefore comes
    from mlb_scored_legs.opposing_pitcher_id (96.2% on same-day legs),
    which the pipeline writes at scoring time.

mlb_player_batting_logs.plate_appearances and .hit_by_pitch are 100% NULL,
so expected trips are measured in at-bats. That is the correct denominator
anyway — the model is per-AB — and it removes a walk-rate conversion step.
"""
from __future__ import annotations

import time

SCORER_VERSION_V4 = "v4_2026-08-12"

# ── f(): maps a pitcher's WHIP/ERA to a per-AB hit rate ──────────────────────
# Weighted least squares against observed team-game H/AB, 2,193 train
# team-games weighted by AB (73,735 AB). Fitted on the *blended* predictor
# (starter_share-weighted SP and BP), which is algebraically identical to
# applying f() to each side separately and blending the results.
#
#   intercept  +0.187327  SE 0.002158  t= +86.8
#   WHIP       +0.052044  SE 0.002612  t= +19.9  95% CI [+0.0469, +0.0572]
#   ERA        -0.002562  SE 0.000452  t=  -5.7  95% CI [-0.0034, -0.0017]
#
# The ERA coefficient is NEGATIVE and that is not a sign error. Conditional
# on WHIP, a higher ERA means the baserunners a pitcher allows convert to
# runs more often (home runs, sequencing) — not that he allows more hits.
# This is the explanation for four months of "the ERA signal is backwards"
# findings in this project: ERA's marginal effect on *hit rate* is genuinely
# negative once WHIP is controlled, and every model that used raw ERA alone
# was reading a confounded signal. Do not "fix" this sign.
F_INTERCEPT = 0.187327
F_WHIP      = 0.052044
F_ERA       = -0.002562

# League-average blended hit environment, AB-weighted over the train period.
# Used as the normaliser so that a league-average matchup leaves the batter's
# own base rate unchanged. Equals the pooled observed H/AB (0.24363) to 5dp,
# which is the calibration check on f().
LG_AVG_ENV = 0.24363

# ── Team defence (DER) ──────────────────────────────────────────────────────
# lg_DER is the AB-weighted league mean over the train period.
#
# DER_GAMMA is DERIVED (residual slope / hit_env = 0.0613 / 0.2436), NOT the
# 1.0 that the additive form implies — the data says the effect is ~4x
# smaller than the naive form assumes.
#
# HONEST CAVEAT: DER's incremental contribution after hit_env is
# r = 0.0151, 95% CI [-0.027, +0.057] — THE CI INCLUDES ZERO. The term is
# retained at its derived weight rather than at an assumed 1.0, but it is not
# distinguishable from no term at all. The reason is visible in the data:
# corr(hit_env, opp_DER) = -0.354, i.e. team defence is already substantially
# embedded in that team's bullpen and starter WHIP/ERA. If this model is ever
# simplified, this is the first term to drop.
LG_DER    = 0.70886
DER_GAMMA = 0.252

# ── Batter base rate ────────────────────────────────────────────────────────
# Beta-binomial method of moments over 514 batters, 85,401 train AB.
# Implied true-talent SD of per-AB hit rate = 0.0200, which independently
# reproduces the well-known ~.020 true-talent spread in batting average —
# a useful check that the derivation is sound.
P_LEAGUE_AB = 0.24404
K_BASE_AB   = 462.6

# ── Platoon ─────────────────────────────────────────────────────────────────
# Variance decomposition over 727 player-hand cells: observed variance of a
# batter's per-hand deviation is 0.0015319, of which 0.0014193 is sampling
# noise, leaving true variance 0.0001126 (true SD 0.0106).
#
# HONEST RESULT: this collapses the platoon term. With k = 1616.6 AB and a
# typical vs-LHP sample of ~58 AB, the shrinkage weight is 58/(58+1617) =
# 3.5%, so platoon_mult lands within ~1% of 1.000 for essentially every
# batter (observed SD across the scored population: 0.007-0.010). 88% of
# observed platoon-split variance is noise at one season of sample. The term
# is kept because it is correctly derived and costs nothing, not because it
# carries meaningful signal.
K_PLATOON_AB = 1616.6

# ── Recent form ─────────────────────────────────────────────────────────────
# Window DERIVED, not assumed. Correlating each candidate window's prior
# coverage against next-game hit over 17,877 batter-games:
#   season 0.1513 | w40 0.1473 | w30 0.1405 | w20 0.1329
#   w15 0.1281 | w10 0.1169 | w5 0.0912
# Raw trailing coverage is monotonically WORSE the shorter the window — there
# is no recency effect in the level, so season-to-date is the base rate.
# The *ratio* (recent / season) peaks at window 15:
#   w5 0.0269 | w10 0.0333 | w15 0.0357 | w20 0.0338 | w30 0.0334
# and survives controlling for season coverage: partial r = 0.0339,
# 95% CI [0.019, 0.048] — excludes zero. TREND_BETA is the slope of observed
# per-AB rate on the ratio, normalised by the pooled rate (0.02426 / 0.24751).
TREND_WINDOW = 15
TREND_BETA   = 0.098

# ── Starting pitcher, shrunk toward league by odd/even split-half reliability ─
# WHIP: split-half r = 0.375 at 37.2 IP/half -> k = 37.2*(1-r)/r = 61.9 IP
# ERA:  split-half r = 0.354 -> k = 67.8 IP
# avg_IP/start: split-half r = 0.594 at 7.03 starts/half -> k = 4.81 starts
#
# Shrinkage replaces a minimum-starts cutoff entirely: a starter with no
# prior starts lands exactly on the league mean, and one with 20 starts is
# weighted almost entirely on his own record — continuously, with no
# threshold anywhere. This is also how the ~4% of legs with no identified
# opposing starter are handled: zero sample -> league-average starter.
K_SP_WHIP_IP      = 61.9
MU_SP_WHIP        = 1.2827
K_SP_ERA_IP       = 67.8
MU_SP_ERA         = 4.2193
K_SP_AVGIP_STARTS = 4.81
MU_SP_AVGIP       = 5.3288

# Bullpens are NOT shrunk: every team had >=372 relief IP by mid-season
# (minimum observed 372.3), so the sample is large enough that shrinkage
# would be a no-op. These league means are used only when a team's relief
# aggregate is missing entirely.
MU_BP_WHIP = 1.3113
MU_BP_ERA  = 3.9873

# ── Expected at-bats ────────────────────────────────────────────────────────
# P(>=1 hit) = 1 - (1-p)^AB is CONCAVE in AB, so evaluating it at the mean AB
# overstates the expectation (Jensen's inequality). Scoring at mean AB
# over-predicted by +0.036 train / +0.040 test. Averaging the probability
# over the batter's empirical last-5 AB counts instead — same window, no new
# constant — halves that to +0.018 / +0.022.
#
# The residual +0.02 is structural, not a missing constant: per-AB outcomes
# within a game are positively correlated (same pitcher, same conditions),
# which depresses true P(>=1 hit) below the independent-Bernoulli value. It
# is a monotone shift and does not affect ranking, which is all v4 uses p_hit
# for. If p_hit is ever used for EV rather than ranking, fit a recalibration
# intercept on train data first — do not tune these constants to close it.
EXP_AB_WINDOW = 5
MU_AB         = 3.187   # train-period mean of the last-5 AB average; used
                        # only when a batter has no prior games at all.


def _f(whip: float, era: float) -> float:
    """Map a pitcher's WHIP/ERA to an expected per-AB hit rate against him."""
    return F_INTERCEPT + F_WHIP * whip + F_ERA * era


def _shrink(observed_num: float, observed_den: float, k: float, mu: float) -> float:
    """
    Continuous shrinkage toward a league mean. At zero sample this returns mu
    exactly; as the sample grows it converges on the observed rate. There is
    no threshold and no branch — a starter with 1 IP and one with 200 IP go
    through the same expression.
    """
    return (observed_num + k * mu) / (observed_den + k)


def compute_p_hit(
    *,
    prior_h: float | None,
    prior_ab: float | None,
    cov_overall: float | None,
    cov_window: float | None,
    h_vs_hand: float | None,
    ab_vs_hand: float | None,
    sp_ip: float | None,
    sp_h: float | None,
    sp_bb: float | None,
    sp_er: float | None,
    sp_ip_starts: float | None,
    sp_starts: float | None,
    bp_ip: float | None,
    bp_h: float | None,
    bp_bb: float | None,
    bp_er: float | None,
    opp_der: float | None,
    ab_recent: list | None,
) -> dict | None:
    """
    Compute p_hit and every intermediate component for one batter/game.

    Pure function — no DB, no clock, no globals beyond the fitted constants.
    Returns a dict of components, or None if p_per_AB falls outside (0, 1),
    which would make the probability undefined.

    Note that None is returned rather than clamping. A clamp would silently
    manufacture a plausible-looking probability out of broken inputs, and this
    model's whole premise is that quietly-wrong values are worse than absent
    ones. Across all 38,147 historical batter-games the guard never fires;
    if it ever does in production it means an input is corrupt, and the leg
    should be dropped and investigated rather than scored.
    """
    # Batter base rate, shrunk toward league.
    base = _shrink(prior_h or 0.0, prior_ab or 0.0, K_BASE_AB, P_LEAGUE_AB)

    # Platoon: the batter's rate vs this hand, shrunk toward his own overall
    # rate (not toward league — the relevant prior is the batter himself).
    p_hand = _shrink(h_vs_hand or 0.0, ab_vs_hand or 0.0, K_PLATOON_AB, base)
    platoon_mult = p_hand / base if base else 1.0

    # Recent form as a ratio to season-to-date. Absent either side -> 1.0.
    if cov_window is not None and cov_overall:
        trend_mult = 1.0 + TREND_BETA * (cov_window / cov_overall - 1.0)
    else:
        trend_mult = 1.0

    # Opposing starter, shrunk. Missing starter -> league-average starter.
    sp_whip = _shrink((sp_h or 0.0) + (sp_bb or 0.0), sp_ip or 0.0, K_SP_WHIP_IP, MU_SP_WHIP)
    sp_era  = _shrink(9.0 * (sp_er or 0.0), sp_ip or 0.0, K_SP_ERA_IP, MU_SP_ERA)
    avg_ip  = _shrink(sp_ip_starts or 0.0, sp_starts or 0.0, K_SP_AVGIP_STARTS, MU_SP_AVGIP)

    starter_share = min(avg_ip / 9.0, 1.0)

    # Opposing bullpen — unshrunk (see MU_BP_* note), league mean if absent.
    if bp_ip:
        bp_whip = ((bp_h or 0.0) + (bp_bb or 0.0)) / bp_ip
        bp_era  = 9.0 * (bp_er or 0.0) / bp_ip
    else:
        bp_whip, bp_era = MU_BP_WHIP, MU_BP_ERA

    hit_env = starter_share * _f(sp_whip, sp_era) + (1.0 - starter_share) * _f(bp_whip, bp_era)

    der = opp_der if opp_der is not None else LG_DER
    hit_env_adj = hit_env * (1.0 + DER_GAMMA * (LG_DER - der))

    p_per_ab = base * platoon_mult * trend_mult * (hit_env_adj / LG_AVG_ENV)

    if not (0.0 < p_per_ab < 1.0):
        return None

    # Integrate over the empirical AB distribution rather than evaluating at
    # its mean — see the EXP_AB_WINDOW note on Jensen's inequality.
    abs_list = [a for a in (ab_recent or []) if a is not None]
    if abs_list:
        p_hit = sum(1.0 - (1.0 - p_per_ab) ** a for a in abs_list) / len(abs_list)
        exp_ab = sum(abs_list) / len(abs_list)
    else:
        exp_ab = MU_AB
        p_hit = 1.0 - (1.0 - p_per_ab) ** exp_ab

    return {
        "p_hit":          p_hit,
        "p_per_ab":       p_per_ab,
        "v4_base_rate":   base,
        "v4_platoon_mult": platoon_mult,
        "v4_trend_mult":  trend_mult,
        "v4_hit_env":     hit_env,
        "v4_hit_env_adj": hit_env_adj,
        "v4_starter_share": starter_share,
        "v4_sp_whip":     sp_whip,
        "v4_sp_era":      sp_era,
        "v4_sp_avg_ip":   avg_ip,
        "v4_bp_whip":     bp_whip,
        "v4_bp_era":      bp_era,
        "v4_opp_der":     der,
        "v4_exp_ab":      exp_ab,
    }


# ────────────────────────────────────────────────────────────────────────────
# Batch feature loading
#
# RUNTIME: this is deliberately four aggregate queries per pipeline run, not
# per leg. The ungated hits/over pool is materially larger than the gated one
# it replaces, and per-leg aggregation over 38K batting logs + 15K pitching
# logs is exactly the unbounded per-leg work that caused the Session 25 silent
# pipeline stall. Every aggregate below is keyed by run_date and computed once.
# Timing is instrumented and logged.
# ────────────────────────────────────────────────────────────────────────────

_BATTER_SQL = """
WITH bl AS (
    SELECT b.player_id, b.game_pk, g.game_date, b.hits, b.at_bats,
           (b.hits > 0)::int AS got_hit, p.throws AS sp_throws
    FROM mlb_player_batting_logs b
    JOIN mlb_games g ON g.game_pk = b.game_pk
    LEFT JOIN mlb_players p ON p.player_id = b.opposing_pitcher_id
    WHERE b.player_id = ANY(%(pids)s) AND g.game_date < %(cutoff)s
), r AS (
    SELECT *, row_number() OVER (
        PARTITION BY player_id ORDER BY game_date DESC, game_pk DESC) AS rn
    FROM bl
)
SELECT player_id,
       count(*)                                          AS prior_g,
       avg(got_hit)::float8                              AS cov_overall,
       sum(hits)                                         AS prior_h,
       sum(at_bats)                                      AS prior_ab,
       avg(got_hit) FILTER (WHERE rn <= %(twin)s)::float8 AS cov_window,
       (array_agg(at_bats ORDER BY rn) FILTER (WHERE rn <= %(abwin)s)) AS ab_recent,
       sum(hits)    FILTER (WHERE sp_throws = 'L')       AS h_vs_l,
       sum(at_bats) FILTER (WHERE sp_throws = 'L')       AS ab_vs_l,
       sum(hits)    FILTER (WHERE sp_throws = 'R')       AS h_vs_r,
       sum(at_bats) FILTER (WHERE sp_throws = 'R')       AS ab_vs_r
FROM r GROUP BY player_id
"""

_PITCHER_SQL = """
SELECT p.player_id,
       sum(round(p.innings_pitched * 3) / 3.0)                            AS ip,
       sum(p.hits_allowed)                                                AS h,
       sum(p.walks_allowed)                                               AS bb,
       sum(p.earned_runs)                                                 AS er,
       sum(round(p.innings_pitched * 3) / 3.0) FILTER (WHERE p.is_starter) AS ip_starts,
       count(*) FILTER (WHERE p.is_starter)                               AS starts
FROM mlb_player_pitching_logs p
JOIN mlb_games g ON g.game_pk = p.game_pk
WHERE p.player_id = ANY(%(pids)s) AND g.game_date < %(cutoff)s
GROUP BY p.player_id
"""

_BULLPEN_SQL = """
SELECT p.team_id,
       sum(round(p.innings_pitched * 3) / 3.0) AS ip,
       sum(p.hits_allowed)                     AS h,
       sum(p.walks_allowed)                    AS bb,
       sum(p.earned_runs)                      AS er
FROM mlb_player_pitching_logs p
JOIN mlb_games g ON g.game_pk = p.game_pk
WHERE NOT p.is_starter AND g.game_date < %(cutoff)s
GROUP BY p.team_id
"""

_DER_SQL = """
SELECT b.opponent_team_id AS team_id,
       1 - (sum(b.hits) - sum(b.home_runs))::numeric
           / NULLIF(sum(b.at_bats) - sum(b.strikeouts) - sum(b.home_runs), 0) AS der
FROM mlb_player_batting_logs b
JOIN mlb_games g ON g.game_pk = b.game_pk
WHERE g.game_date < %(cutoff)s
GROUP BY b.opponent_team_id
"""

_GAME_SQL = """
SELECT game_pk, home_team_id, away_team_id FROM mlb_games WHERE game_pk = ANY(%(gpks)s)
"""


def load_v4_aggregates(conn, *, batter_ids, pitcher_ids, game_pks, cutoff_date):
    """
    Load every aggregate v4 needs in four grouped queries plus one small
    lookup. Returns a dict of dicts keyed by id. Never queries per leg.
    """
    t0 = time.time()
    cur = conn.cursor()

    cur.execute(_BATTER_SQL, {
        "pids": list(batter_ids), "cutoff": cutoff_date,
        "twin": TREND_WINDOW, "abwin": EXP_AB_WINDOW,
    })
    batters = {r["player_id"]: dict(r) for r in cur.fetchall()}
    t_bat = time.time()

    cur.execute(_PITCHER_SQL, {"pids": list(pitcher_ids), "cutoff": cutoff_date})
    pitchers = {r["player_id"]: dict(r) for r in cur.fetchall()}
    t_pit = time.time()

    cur.execute(_BULLPEN_SQL, {"cutoff": cutoff_date})
    bullpens = {r["team_id"]: dict(r) for r in cur.fetchall()}

    cur.execute(_DER_SQL, {"cutoff": cutoff_date})
    ders = {r["team_id"]: r["der"] for r in cur.fetchall()}
    t_team = time.time()

    cur.execute(_GAME_SQL, {"gpks": list(game_pks)})
    games = {r["game_pk"]: dict(r) for r in cur.fetchall()}
    cur.close()
    t_end = time.time()

    print(
        f"  [hits_v4] aggregates loaded in {t_end - t0:.2f}s "
        f"(batters {len(batters)} {t_bat - t0:.2f}s | "
        f"pitchers {len(pitchers)} {t_pit - t_bat:.2f}s | "
        f"teams {len(bullpens)}bp/{len(ders)}der {t_team - t_pit:.2f}s | "
        f"games {len(games)} {t_end - t_team:.2f}s)"
    )
    return {"batters": batters, "pitchers": pitchers,
            "bullpens": bullpens, "ders": ders, "games": games}


def score_hits_over_v4(legs: list, conn, *, cutoff_date, abbr_to_team_id: dict) -> int:
    """
    Attach p_hit and every v4 component to each hits/over leg, in place.

    Legs of any other stat/direction are left completely untouched — this
    never overwrites composite_score and never reads it.

    Returns the number of legs successfully scored.
    """
    targets = [l for l in legs
               if l.get("stat") == "hits" and l.get("direction") == "over"]
    if not targets:
        return 0

    t0 = time.time()

    batter_ids = {int(l["player_id"]) for l in targets if l.get("player_id")}
    pitcher_ids = {int(l["opposing_pitcher_id"]) for l in targets
                   if l.get("opposing_pitcher_id")}
    game_pks = {int(l["game_pk"]) for l in targets if l.get("game_pk")}

    agg = load_v4_aggregates(
        conn, batter_ids=batter_ids, pitcher_ids=pitcher_ids,
        game_pks=game_pks, cutoff_date=cutoff_date,
    )

    scored = 0
    guard_failures = 0
    for leg in targets:
        try:
            pid = int(leg["player_id"])
        except (TypeError, ValueError, KeyError):
            continue

        b = agg["batters"].get(pid, {})

        # Opposing team: resolve from the game and the batter's own team.
        opp_team = None
        gpk = leg.get("game_pk")
        game = agg["games"].get(int(gpk)) if gpk else None
        my_team = abbr_to_team_id.get(leg.get("team", ""))
        if game and my_team:
            if my_team == game["home_team_id"]:
                opp_team = game["away_team_id"]
            elif my_team == game["away_team_id"]:
                opp_team = game["home_team_id"]

        bp = agg["bullpens"].get(opp_team, {}) if opp_team else {}
        der = agg["ders"].get(opp_team) if opp_team else None

        sp = {}
        if leg.get("opposing_pitcher_id"):
            try:
                sp = agg["pitchers"].get(int(leg["opposing_pitcher_id"]), {})
            except (TypeError, ValueError):
                sp = {}

        # Platoon side is chosen by the opposing starter's throwing hand as
        # the pipeline recorded it. A switch-pitcher (throws='S', 2 in the
        # league) or an unknown hand falls through to no split, which the
        # shrinkage turns into platoon_mult = 1.0.
        hand = (leg.get("pitcher_hand") or "").upper()
        if hand == "L":
            h_vs_hand, ab_vs_hand = b.get("h_vs_l"), b.get("ab_vs_l")
        elif hand == "R":
            h_vs_hand, ab_vs_hand = b.get("h_vs_r"), b.get("ab_vs_r")
        else:
            h_vs_hand, ab_vs_hand = None, None

        out = compute_p_hit(
            prior_h=b.get("prior_h"), prior_ab=b.get("prior_ab"),
            cov_overall=b.get("cov_overall"), cov_window=b.get("cov_window"),
            h_vs_hand=h_vs_hand, ab_vs_hand=ab_vs_hand,
            sp_ip=sp.get("ip"), sp_h=sp.get("h"), sp_bb=sp.get("bb"),
            sp_er=sp.get("er"), sp_ip_starts=sp.get("ip_starts"),
            sp_starts=sp.get("starts"),
            bp_ip=bp.get("ip"), bp_h=bp.get("h"), bp_bb=bp.get("bb"),
            bp_er=bp.get("er"),
            opp_der=float(der) if der is not None else None,
            ab_recent=b.get("ab_recent"),
        )
        if out is None:
            guard_failures += 1
            continue

        leg.update(out)
        leg["v4_prior_games"] = b.get("prior_g")
        leg["scorer_version"] = SCORER_VERSION_V4
        scored += 1

    elapsed = time.time() - t0
    if scored:
        ps = sorted(l["p_hit"] for l in targets if l.get("p_hit") is not None)
        print(
            f"  [hits_v4] scored {scored}/{len(targets)} hits/over legs in "
            f"{elapsed:.2f}s | p_hit min={ps[0]:.4f} "
            f"med={ps[len(ps) // 2]:.4f} max={ps[-1]:.4f}"
        )
    if guard_failures:
        print(
            f"  [hits_v4] WARNING: {guard_failures} leg(s) produced p_per_AB "
            f"outside (0,1) and were left unscored — inputs are suspect"
        )
    return scored
