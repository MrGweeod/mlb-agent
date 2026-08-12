"""
tests/test_hits_v4.py — unit tests for the v4 hits/over probability model.

src.engine.hits_v4 imports nothing but `time`, so compute_p_hit() is testable
with no DB and no stubbing — deliberately, so the model's arithmetic can be
verified in isolation from the pipeline. The batch loader
(load_v4_aggregates/score_hits_over_v4) is the part that needs a connection and
is exercised by the smoke test instead.

What these tests pin:
  1. Shrinkage endpoints — zero sample lands exactly on the league mean.
  2. Monotonicity in every input, with the correct SIGN. The ERA slope being
     negative conditional on WHIP is the counterintuitive one and the one most
     likely to be "fixed" by a future reader; it is asserted explicitly.
  3. The Jensen correction — integrating over the AB distribution must give a
     LOWER probability than evaluating at the mean AB, because
     1-(1-p)^AB is concave in AB.
  4. No step functions: a small change in any continuous input must produce a
     nonzero change in output, at every point tested. This is the property the
     v3 scorer violated (era_adj returned exactly 0 for 70.5% of legs).
  5. The (0,1) guard returns None rather than clamping.
"""
from decimal import Decimal

import pytest

from src.engine.hits_v4 import (
    PLATT_A,
    PLATT_B,
    _coerce_row,
    _num,
    calibrate_p_hit,
    load_v4_aggregates,
    score_hits_over_v4,
    F_ERA,
    F_INTERCEPT,
    F_WHIP,
    K_BASE_AB,
    LG_AVG_ENV,
    LG_DER,
    MU_BP_ERA,
    MU_BP_WHIP,
    MU_SP_AVGIP,
    MU_SP_ERA,
    MU_SP_WHIP,
    P_LEAGUE_AB,
    TREND_BETA,
    _f,
    _shrink,
    compute_p_hit,
)

# A neutral batter/matchup: no prior sample anywhere, so every shrunk quantity
# should sit exactly on its league mean.
NEUTRAL = dict(
    prior_h=None, prior_ab=None, cov_overall=None, cov_window=None,
    h_vs_hand=None, ab_vs_hand=None,
    sp_ip=None, sp_h=None, sp_bb=None, sp_er=None,
    sp_ip_starts=None, sp_starts=None,
    bp_ip=None, bp_h=None, bp_bb=None, bp_er=None,
    opp_der=None, ab_recent=None,
)


def _with(**kw):
    d = dict(NEUTRAL)
    d.update(kw)
    return d


class TestShrinkage:
    def test_zero_sample_returns_league_mean_exactly(self):
        assert _shrink(0, 0, 61.9, 1.2827) == pytest.approx(1.2827)

    def test_large_sample_converges_on_observed(self):
        # 2000 IP at WHIP 1.00 should sit very close to 1.00, not the 1.2827 mean
        assert _shrink(2000.0, 2000.0, 61.9, 1.2827) == pytest.approx(1.0, abs=0.01)

    def test_shrinkage_is_continuous_not_thresholded(self):
        """No cliff anywhere — the whole point of replacing minimum-sample cutoffs."""
        prev = _shrink(0, 0, 61.9, 1.2827)
        for ip in range(1, 200):
            cur = _shrink(ip * 1.0, ip * 1.0, 61.9, 1.2827)
            assert cur != prev, f"shrinkage flat between IP {ip - 1} and {ip}"
            prev = cur


class TestNeutralCase:
    def test_neutral_inputs_land_on_league_values(self):
        out = compute_p_hit(**NEUTRAL)
        assert out is not None
        assert out["v4_base_rate"] == pytest.approx(P_LEAGUE_AB)
        assert out["v4_platoon_mult"] == pytest.approx(1.0)
        assert out["v4_trend_mult"] == pytest.approx(1.0)
        assert out["v4_sp_whip"] == pytest.approx(MU_SP_WHIP)
        assert out["v4_sp_era"] == pytest.approx(MU_SP_ERA)
        assert out["v4_sp_avg_ip"] == pytest.approx(MU_SP_AVGIP)
        assert out["v4_bp_whip"] == pytest.approx(MU_BP_WHIP)
        assert out["v4_bp_era"] == pytest.approx(MU_BP_ERA)
        assert out["v4_opp_der"] == pytest.approx(LG_DER)

    def test_neutral_p_per_ab_is_close_to_league_rate(self):
        """A league-average batter in a league-average matchup hits at ~league rate."""
        out = compute_p_hit(**NEUTRAL)
        assert out["p_per_ab"] == pytest.approx(P_LEAGUE_AB, rel=0.02)

    def test_neutral_p_hit_is_plausible(self):
        out = compute_p_hit(**NEUTRAL)
        assert 0.45 < out["p_hit"] < 0.65


class TestMonotonicityAndSigns:
    def test_better_batter_raises_p_hit(self):
        weak = compute_p_hit(**_with(prior_h=80, prior_ab=500))    # .160
        strong = compute_p_hit(**_with(prior_h=160, prior_ab=500))  # .320
        assert strong["p_hit"] > weak["p_hit"]

    def test_higher_sp_whip_raises_p_hit(self):
        # 200 IP so the shrinkage lets the difference actually show
        lo = compute_p_hit(**_with(sp_ip=200, sp_h=150, sp_bb=40, sp_er=70,
                                   sp_ip_starts=200, sp_starts=33))
        hi = compute_p_hit(**_with(sp_ip=200, sp_h=230, sp_bb=70, sp_er=70,
                                   sp_ip_starts=200, sp_starts=33))
        assert hi["v4_sp_whip"] > lo["v4_sp_whip"]
        assert hi["p_hit"] > lo["p_hit"], "a higher-WHIP starter must mean more hits"

    def test_higher_sp_era_LOWERS_p_hit_at_fixed_whip(self):
        """
        THIS SIGN IS INTENTIONAL — DO NOT 'FIX' IT.

        Conditional on WHIP, the fitted ERA coefficient is negative
        (t = -5.7, 95% CI [-0.0034, -0.0017]): a pitcher whose baserunners
        convert to runs more often is not a pitcher who allows more hits.
        This is the explanation for the long-running "ERA signal is backwards"
        finding in this project. Both legs below hold hits+walks fixed and vary
        only earned runs, so WHIP is identical and only ERA moves.
        """
        lo_era = compute_p_hit(**_with(sp_ip=200, sp_h=190, sp_bb=55, sp_er=50,
                                       sp_ip_starts=200, sp_starts=33))
        hi_era = compute_p_hit(**_with(sp_ip=200, sp_h=190, sp_bb=55, sp_er=110,
                                       sp_ip_starts=200, sp_starts=33))
        assert lo_era["v4_sp_whip"] == pytest.approx(hi_era["v4_sp_whip"])
        assert hi_era["v4_sp_era"] > lo_era["v4_sp_era"]
        assert hi_era["p_hit"] < lo_era["p_hit"]
        assert F_ERA < 0

    def test_better_defence_lowers_p_hit(self):
        good_d = compute_p_hit(**_with(opp_der=0.7368))  # best team observed
        bad_d = compute_p_hit(**_with(opp_der=0.6747))   # worst team observed
        assert bad_d["p_hit"] > good_d["p_hit"]

    def test_hot_batter_trend_raises_p_hit(self):
        cold = compute_p_hit(**_with(cov_overall=0.55, cov_window=0.40))
        hot = compute_p_hit(**_with(cov_overall=0.55, cov_window=0.75))
        assert hot["v4_trend_mult"] > 1.0 > cold["v4_trend_mult"]
        assert hot["p_hit"] > cold["p_hit"]

    def test_more_at_bats_raises_p_hit(self):
        few = compute_p_hit(**_with(ab_recent=[2, 2, 2, 2, 2]))
        many = compute_p_hit(**_with(ab_recent=[5, 5, 5, 5, 5]))
        assert many["p_hit"] > few["p_hit"]

    def test_longer_starter_outing_shifts_env_toward_starter(self):
        short = compute_p_hit(**_with(sp_ip=100, sp_h=90, sp_bb=25, sp_er=40,
                                      sp_ip_starts=60, sp_starts=20))
        long = compute_p_hit(**_with(sp_ip=100, sp_h=90, sp_bb=25, sp_er=40,
                                     sp_ip_starts=140, sp_starts=20))
        assert long["v4_starter_share"] > short["v4_starter_share"]


class TestNoStepFunctions:
    """
    Every factor must enter continuously. v3's era_adj returned exactly 0 for
    70.5% of legs and lineup_adj for 100% of them; that dead-banding is what
    v4 exists to remove, so it is asserted directly rather than assumed.
    """

    @pytest.mark.parametrize("field,lo,hi", [
        ("opp_der", 0.66, 0.75),
        ("cov_window", 0.30, 0.80),
    ])
    def test_output_moves_for_every_input_step(self, field, lo, hi):
        base = _with(cov_overall=0.55)
        prev = None
        steps = 60
        for i in range(steps + 1):
            val = lo + (hi - lo) * i / steps
            out = compute_p_hit(**_with(**{**base, field: val}))
            if prev is not None:
                assert out["p_hit"] != prev, (
                    f"{field} produced a dead band at {val:.4f} — "
                    "this is exactly the v3 failure v4 exists to remove"
                )
            prev = out["p_hit"]

    def test_sp_era_has_no_dead_band(self):
        prev = None
        for er in range(20, 121):
            out = compute_p_hit(**_with(sp_ip=200, sp_h=190, sp_bb=55, sp_er=er,
                                        sp_ip_starts=200, sp_starts=33))
            if prev is not None:
                assert out["p_hit"] != prev, f"ERA dead band at earned_runs={er}"
            prev = out["p_hit"]


class TestJensenCorrection:
    def test_integrated_form_is_below_point_estimate(self):
        """
        1-(1-p)^AB is concave in AB, so E[f(AB)] < f(E[AB]). Scoring at the
        mean AB over-predicted by +0.036/+0.040; averaging over the empirical
        AB counts is what halves that. A spread-out AB distribution must give a
        strictly lower probability than its own mean evaluated pointwise.
        """
        spread = [1, 2, 3, 5, 6]          # mean 3.4
        flat = [3.4, 3.4, 3.4, 3.4, 3.4]  # same mean, no spread
        p_spread = compute_p_hit(**_with(ab_recent=spread))["p_hit"]
        p_flat = compute_p_hit(**_with(ab_recent=flat))["p_hit"]
        assert p_spread < p_flat

    def test_wider_spread_gives_lower_probability(self):
        narrow = compute_p_hit(**_with(ab_recent=[3, 3, 4, 4, 4]))["p_hit"]
        wide = compute_p_hit(**_with(ab_recent=[0, 1, 4, 6, 7]))["p_hit"]
        assert wide < narrow

    def test_falls_back_to_point_form_with_no_ab_history(self):
        out = compute_p_hit(**_with(ab_recent=None))
        assert out is not None and out["p_hit"] > 0


class TestGuard:
    def test_returns_none_rather_than_clamping(self):
        """
        A negative base rate is impossible from real data, but if it ever
        arrives the model must refuse to score rather than clamp to a
        plausible-looking value.
        """
        out = compute_p_hit(**_with(prior_h=-100000, prior_ab=10))
        assert out is None

    def test_all_realistic_inputs_stay_in_range(self):
        """Sweep the observed envelope; the guard must never fire on real data."""
        for h, ab in [(20, 200), (60, 200), (80, 200), (150, 400)]:
            for der in (0.66, 0.7089, 0.75):
                for whip_h in (140, 200, 260):
                    out = compute_p_hit(**_with(
                        prior_h=h, prior_ab=ab, opp_der=der,
                        sp_ip=180, sp_h=whip_h, sp_bb=60, sp_er=80,
                        sp_ip_starts=180, sp_starts=30,
                        cov_overall=0.55, cov_window=0.80,
                        ab_recent=[4, 5, 4, 5, 5],
                    ))
                    assert out is not None
                    assert 0.0 < out["p_hit"] < 1.0


class _FakeCursor:
    """
    Stands in for a psycopg2 RealDictCursor, returning the types psycopg2
    actually returns: NUMERIC -> Decimal, bigint -> int, integer[] -> list[int],
    double precision -> float. Queries are matched by a distinctive fragment so
    the fake doesn't depend on exact SQL text.
    """

    def __init__(self):
        self.rows = []
        self.closed = False

    def execute(self, sql, params=None):
        if "mlb_player_batting_logs" in sql and "row_number()" in sql:
            self.rows = [{
                "player_id": 660271, "prior_g": 100, "cov_overall": 0.62,
                "prior_h": 120, "prior_ab": 400, "cov_window": 0.66,
                "ab_recent": [4, 5, 3, 4, 5],
                "h_vs_l": 30, "ab_vs_l": 100, "h_vs_r": 90, "ab_vs_r": 300,
            }]
        elif "FILTER (WHERE p.is_starter)" in sql and "player_id = ANY" in sql:
            self.rows = [{
                "player_id": 543037,
                "ip": Decimal("180.3333333333"), "h": 165, "bb": 50, "er": 78,
                "ip_starts": Decimal("180.3333333333"), "starts": 30,
            }]
        elif "NOT p.is_starter" in sql:
            self.rows = [{
                "team_id": 147, "ip": Decimal("423.0"),
                "h": 380, "bb": 125, "er": 145,
            }]
        elif "opponent_team_id" in sql:
            self.rows = [{"team_id": 147, "der": Decimal("0.7218")}]
        elif "mlb_games" in sql:
            self.rows = [{"game_pk": 823917, "home_team_id": 147, "away_team_id": 111}]
        else:
            self.rows = []

    def fetchall(self):
        return self.rows

    def close(self):
        self.closed = True


class _FakeConn:
    def __init__(self):
        self._cur = _FakeCursor()

    def cursor(self):
        return self._cur


def _walk(obj):
    """Yield every scalar in a nested dict/list structure."""
    if isinstance(obj, dict):
        for v in obj.values():
            yield from _walk(v)
    elif isinstance(obj, (list, tuple)):
        for v in obj:
            yield from _walk(v)
    else:
        yield obj


class TestDBBoundary:
    """
    REGRESSION: the first live run crashed in _shrink() on
    `Decimal + float` while all 55 unit tests passed, because every test fed
    hand-written floats and psycopg2 returns NUMERIC as decimal.Decimal.

    Four v4 aggregates come back NUMERIC (verified with pg_typeof):
    pitchers.ip, pitchers.ip_starts, bullpens.ip, ders.der. These tests drive
    the real load_v4_aggregates() with a cursor returning those types and
    assert no Decimal survives the boundary.
    """

    def test_no_decimal_survives_load(self):
        agg = load_v4_aggregates(
            _FakeConn(), batter_ids=[660271], pitcher_ids=[543037],
            game_pks=[823917], cutoff_date="2026-08-11",
        )
        offenders = [v for v in _walk(agg) if isinstance(v, Decimal)]
        assert offenders == [], f"Decimal leaked past the boundary: {offenders}"

    def test_numeric_fields_specifically_are_floats(self):
        agg = load_v4_aggregates(
            _FakeConn(), batter_ids=[660271], pitcher_ids=[543037],
            game_pks=[823917], cutoff_date="2026-08-11",
        )
        assert isinstance(agg["pitchers"][543037]["ip"], float)
        assert isinstance(agg["pitchers"][543037]["ip_starts"], float)
        assert isinstance(agg["bullpens"][147]["ip"], float)
        assert isinstance(agg["ders"][147], float)

    def test_ids_and_prior_g_stay_int(self):
        """
        Dict keys must stay hashable ints, and prior_g is written to the
        INTEGER column mlb_scored_legs.v4_prior_games.
        """
        agg = load_v4_aggregates(
            _FakeConn(), batter_ids=[660271], pitcher_ids=[543037],
            game_pks=[823917], cutoff_date="2026-08-11",
        )
        assert isinstance(agg["batters"][660271]["prior_g"], int)
        assert isinstance(agg["batters"][660271]["player_id"], int)
        assert isinstance(agg["games"][823917]["home_team_id"], int)

    def test_loaded_aggregates_actually_score(self):
        """The end-to-end shape: loaded rows must flow into compute_p_hit()."""
        agg = load_v4_aggregates(
            _FakeConn(), batter_ids=[660271], pitcher_ids=[543037],
            game_pks=[823917], cutoff_date="2026-08-11",
        )
        b, sp, bp = agg["batters"][660271], agg["pitchers"][543037], agg["bullpens"][147]
        out = compute_p_hit(
            prior_h=b["prior_h"], prior_ab=b["prior_ab"],
            cov_overall=b["cov_overall"], cov_window=b["cov_window"],
            h_vs_hand=b["h_vs_r"], ab_vs_hand=b["ab_vs_r"],
            sp_ip=sp["ip"], sp_h=sp["h"], sp_bb=sp["bb"], sp_er=sp["er"],
            sp_ip_starts=sp["ip_starts"], sp_starts=sp["starts"],
            bp_ip=bp["ip"], bp_h=bp["h"], bp_bb=bp["bb"], bp_er=bp["er"],
            opp_der=agg["ders"][147], ab_recent=b["ab_recent"],
        )
        assert out is not None
        assert 0.0 < out["p_hit"] < 1.0
        assert all(isinstance(v, float) for v in out.values())

    def test_score_hits_over_v4_end_to_end_with_decimals(self):
        """
        The exact path that crashed in production: score_hits_over_v4() ->
        load_v4_aggregates() -> compute_p_hit(), with a cursor returning the
        Decimals psycopg2 really returns. This is the test that would have
        caught the live failure.
        """
        legs = [{
            "stat": "hits", "direction": "over", "player_id": 660271,
            "game_pk": 823917, "team": "NYY", "opposing_pitcher_id": 543037,
            "pitcher_hand": "R", "player_name": "Test Batter",
        }]
        n = score_hits_over_v4(legs, _FakeConn(), cutoff_date="2026-08-11",
                               abbr_to_team_id={"NYY": 147})
        assert n == 1
        leg = legs[0]
        assert 0.0 < leg["p_hit"] < 1.0
        assert leg["scorer_version"] == "v4_2026-08-12"
        assert isinstance(leg["v4_prior_games"], int)
        leaked = [k for k, v in leg.items() if isinstance(v, Decimal)]
        assert leaked == [], f"Decimal reached the leg dict: {leaked}"

    def test_non_hits_legs_are_untouched(self):
        """v4 must not write anything onto other stats' legs."""
        legs = [{"stat": "totalBases", "direction": "over", "player_id": 1,
                 "composite_score": 71.0}]
        n = score_hits_over_v4(legs, _FakeConn(), cutoff_date="2026-08-11",
                               abbr_to_team_id={})
        assert n == 0
        assert "p_hit" not in legs[0]
        assert legs[0]["composite_score"] == 71.0

    def test_decimal_reaching_the_model_would_still_raise(self):
        """
        Confirms the bug is real and the boundary is what prevents it — if
        someone bypasses load_v4_aggregates() and hands compute_p_hit() a
        Decimal, it must fail loudly rather than silently coerce.
        """
        with pytest.raises(TypeError):
            compute_p_hit(**_with(sp_ip=Decimal("180.3"), sp_h=165,
                                  sp_bb=50, sp_er=78,
                                  sp_ip_starts=Decimal("180.3"), sp_starts=30))


class TestNumHelper:
    def test_preserves_none(self):
        assert _num(None) is None

    def test_converts_decimal_and_int(self):
        assert _num(Decimal("1.25")) == 1.25
        assert isinstance(_num(3), float)

    def test_recurses_into_arrays(self):
        out = _num([Decimal("1"), 2, None])
        assert out == [1.0, 2.0, None]
        assert all(isinstance(x, float) for x in out if x is not None)

    def test_passes_through_non_numerics(self):
        assert _num("2026-08-11") == "2026-08-11"

    def test_coerce_row_keeps_declared_ints(self):
        row = {"player_id": 1, "prior_g": 5, "ip": Decimal("10.5")}
        out = _coerce_row(row)
        assert isinstance(out["player_id"], int)
        assert isinstance(out["prior_g"], int)
        assert isinstance(out["ip"], float)


class TestCalibration:
    """
    Platt scaling of p_hit. Fitted on 2026-07-01..07-21 (n=4,977), validated
    out-of-sample on 07-22..08-11 (n=6,045) — both windows after the model's
    own constants were fitted, so p_hit is out-of-sample in each.
    """

    def test_slope_is_below_one(self):
        """Slope < 1 IS the over-dispersion — it pulls predictions inward."""
        assert 0.0 < PLATT_B < 1.0

    def test_shrinks_toward_the_middle_at_both_ends(self):
        assert calibrate_p_hit(0.25) > 0.25, "low predictions must move UP"
        assert calibrate_p_hit(0.78) < 0.78, "high predictions must move DOWN"

    def test_is_strictly_monotone_so_ranking_cannot_change(self):
        """
        The load-bearing property: leg selection ranks on p_hit, so the
        calibration must not be able to reorder anything.
        """
        xs = [i / 200.0 for i in range(1, 200)]
        cs = [calibrate_p_hit(x) for x in xs]
        assert all(b > a for a, b in zip(cs, cs[1:]))

    def test_stays_a_probability(self):
        for p in (1e-6, 0.001, 0.5, 0.999, 1 - 1e-6):
            assert 0.0 < calibrate_p_hit(p) < 1.0

    def test_passes_through_degenerate_inputs(self):
        assert calibrate_p_hit(0.0) == 0.0
        assert calibrate_p_hit(1.0) == 1.0

    def test_compounding_penalises_more_legs_more(self):
        """
        Why this matters to the builder: over-confidence compounds, so
        calibration shrinks a 5-leg joint probability by MORE than a 4-leg
        one. That makes the constrained 4-leg comparison strictly more
        favourable, never less.
        """
        p = 0.70
        c = calibrate_p_hit(p)
        ratio4 = c ** 4 / p ** 4
        ratio5 = c ** 5 / p ** 5
        assert ratio5 < ratio4 < 1.0

    def test_compute_p_hit_emits_both_values(self):
        out = compute_p_hit(**NEUTRAL)
        assert out["p_hit_cal"] == pytest.approx(calibrate_p_hit(out["p_hit"]))
        assert out["p_hit_cal"] != out["p_hit"]

    def test_constants_are_the_fitted_values(self):
        assert PLATT_A == pytest.approx(0.038887)
        assert PLATT_B == pytest.approx(0.665607)


class TestFittedConstants:
    def test_f_reproduces_league_average_environment(self):
        """
        f() evaluated at the league-mean blended inputs must reproduce the
        pooled observed H/AB. This is the calibration check on the fit: if
        someone edits a coefficient without refitting, this breaks.
        """
        assert _f(1.2700, 3.8489) == pytest.approx(LG_AVG_ENV, abs=0.0002)

    def test_whip_coefficient_is_positive_and_dominant(self):
        assert F_WHIP > 0
        assert abs(F_WHIP) > abs(F_ERA) * 10

    def test_constants_are_the_fitted_values(self):
        assert F_INTERCEPT == pytest.approx(0.187327)
        assert F_WHIP == pytest.approx(0.052044)
        assert F_ERA == pytest.approx(-0.002562)
        assert K_BASE_AB == pytest.approx(462.6)
        assert TREND_BETA == pytest.approx(0.098)
