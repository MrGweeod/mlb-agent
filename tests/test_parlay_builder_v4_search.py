"""
tests/test_parlay_builder_v4_search.py — the v4 constrained 4-leg search.

Covers the three paths the builder can take under v4:
  1. constrained MIN_LEGS search succeeds
  2. no MIN_LEGS combination clears the floor -> greedy 5/6-leg extension
  3. nothing valid exists at all -> no parlay

Plus the properties that make the search worth having: it must beat greedy on
joint probability whenever a 4-leg solution exists, and it must respect every
roster constraint greedy respects.

src.utils.db is stubbed (parlay_builder imports get_players_used_today at
module scope, and db.py opens a connection at import).
"""
import math
import sys
from unittest.mock import MagicMock

import pytest

if "src.utils.db" not in sys.modules:
    _stub = MagicMock()
    _stub.get_players_used_today.return_value = set()
    sys.modules["src.utils.db"] = _stub

from src.engine.parlay_builder import (  # noqa: E402
    MIN_LEGS,
    MIN_PARLAY_ODDS,
    _best_constrained_combo,
    build_parlays,
    compute_quality_floor,
)

MIN_DECIMAL = MIN_PARLAY_ODDS / 100 + 1  # 5.0


def leg(i, p, odds, game=None, name=None):
    return dict(player_id=i, player_name=name or f"P{i}", game_pk=game if game is not None else i,
                best_odds=str(odds), p_hit=p, composite_score=50.0, coverage_pct=65.0,
                ev_per_unit=0.0, position="OF", odd_id=f"o{i}", stat="hits",
                direction="over")


def build(legs, **kw):
    kw.setdefault("rank_by", "p_hit")
    kw.setdefault("max_legs", 6)
    return build_parlays(legs, top_n=1, num_games=15, **kw)


def joint(p):
    return math.prod(l["p_hit"] for l in p["legs"])


def dec(p):
    return math.prod(l["_dec"] for l in p["legs"])


class TestConstrainedSearchPath:
    def test_finds_4_leg_when_top4_misses_floor(self):
        """
        The 2026-08-11 shape: the four best by p_hit are short-priced and miss
        +400, but longer-priced legs slightly further down clear it at 4.
        """
        legs = [leg(1, 0.78, -250), leg(2, 0.77, -250), leg(3, 0.76, -250),
                leg(4, 0.75, -250), leg(5, 0.72, +100), leg(6, 0.71, +100),
                leg(7, 0.70, +100), leg(8, 0.69, +100)]
        out = build(legs, quality_floor_mode="percentile", quality_floor_value=0)
        assert out, "a 4-leg combination exists and must be found"
        p = out[0]
        assert p["num_legs"] == MIN_LEGS
        assert p["selection_path"] == "constrained_4leg"
        assert dec(p) >= MIN_DECIMAL

    def test_maximises_joint_probability_not_just_feasibility(self):
        """Among 4-leg combos clearing the floor, it must pick the best one."""
        legs = [leg(i, 0.60 + i * 0.01, +100) for i in range(1, 9)]
        out = build(legs, quality_floor_mode="percentile", quality_floor_value=0)
        p = out[0]
        # +100 => decimal 2.0; any 4 clear 5.0, so it should take the top 4 by p
        assert sorted(l["player_id"] for l in p["legs"]) == [5, 6, 7, 8]

    def test_beats_greedy_on_joint_probability(self):
        legs = [leg(1, 0.78, -250), leg(2, 0.77, -250), leg(3, 0.76, -250),
                leg(4, 0.75, -250), leg(5, 0.72, +100), leg(6, 0.71, +100),
                leg(7, 0.70, +100), leg(8, 0.69, +100)]
        greedy = build(list(legs))[0]
        constrained = build(list(legs), quality_floor_mode="percentile",
                            quality_floor_value=0)[0]
        assert constrained["num_legs"] < greedy["num_legs"]
        assert joint(constrained) > joint(greedy)

    def test_respects_max_2_legs_per_game(self):
        legs = [leg(i, 0.75, +100, game=1) for i in range(1, 5)] + \
               [leg(i, 0.60, +100, game=i) for i in range(5, 9)]
        out = build(legs, quality_floor_mode="percentile", quality_floor_value=0)
        p = out[0]
        counts = {}
        for l in p["legs"]:
            counts[l["game_pk"]] = counts.get(l["game_pk"], 0) + 1
        assert max(counts.values()) <= 2

    def test_respects_one_leg_per_player(self):
        legs = [leg(1, 0.80, +100, name="Dup"), leg(2, 0.79, +100, name="Dup"),
                leg(3, 0.70, +100), leg(4, 0.69, +100), leg(5, 0.68, +100)]
        legs[0]["player_id"] = legs[1]["player_id"] = 99
        out = build(legs, quality_floor_mode="percentile", quality_floor_value=0)
        ids = [l["player_id"] for l in out[0]["legs"]]
        assert len(ids) == len(set(ids))


class TestQualityFloor:
    def test_percentile_floor_selects_expected_cut(self):
        legs = [leg(i, i / 10.0, +100) for i in range(1, 11)]
        assert compute_quality_floor(legs, "p_hit", "percentile", 0) == pytest.approx(0.1)
        assert compute_quality_floor(legs, "p_hit", "percentile", 100) == pytest.approx(1.0)
        assert compute_quality_floor(legs, "p_hit", "percentile", 50) == pytest.approx(0.5, abs=0.11)

    def test_max_drop_floor_is_anchored_to_best(self):
        legs = [leg(i, i / 10.0, +100) for i in range(1, 11)]
        assert compute_quality_floor(legs, "p_hit", "max_drop", 0.25) == pytest.approx(0.75)

    def test_unknown_mode_raises(self):
        with pytest.raises(ValueError):
            compute_quality_floor([leg(1, 0.5, +100)], "p_hit", "nonsense", 1)

    def test_tight_floor_starves_search_and_falls_back(self):
        """
        A floor so tight only 3 legs survive cannot yield a 4-leg combo, so the
        builder must fall through to extension rather than produce nothing.
        This is the failure mode that makes max_drop fragile.
        """
        legs = [leg(1, 0.80, -250), leg(2, 0.79, -250), leg(3, 0.78, -250)] + \
               [leg(i, 0.50, -250) for i in range(4, 10)]
        out = build(legs, quality_floor_mode="max_drop", quality_floor_value=0.03)
        assert out, "must still build via the fallback path"
        assert out[0]["selection_path"].startswith("greedy")


class TestFallbackPath:
    def test_falls_back_to_extension_when_no_4_leg_clears(self):
        """
        Every leg at -245 (decimal 1.408, the short end of the odds band):
        4 legs reach only 3.93 < 5.0, but 5 reach 5.54. So no 4-leg solution
        exists and the builder must extend rather than give up.
        """
        legs = [leg(i, 0.75 - i * 0.01, -245) for i in range(1, 10)]
        out = build(legs, quality_floor_mode="percentile", quality_floor_value=0)
        assert out
        p = out[0]
        assert p["num_legs"] > MIN_LEGS, "should have extended past 4"
        assert p["selection_path"].startswith("greedy")
        assert dec(p) >= MIN_DECIMAL

    def test_v4_max_legs_still_caps_extension(self):
        legs = [leg(i, 0.75 - i * 0.001, -400) for i in range(1, 30)]
        out5 = build(legs, quality_floor_mode="percentile", quality_floor_value=0, max_legs=5)
        if out5:
            assert out5[0]["num_legs"] <= 5
        out6 = build(legs, quality_floor_mode="percentile", quality_floor_value=0, max_legs=6)
        if out6:
            assert out6[0]["num_legs"] <= 6

    def test_legacy_composite_path_never_uses_the_search(self):
        legs = [leg(i, 0.7, +100) for i in range(1, 9)]
        for l in legs:
            l["composite_score"] = 90 - l["player_id"]
        out = build_parlays(legs, top_n=1, num_games=15)  # defaults: no floor mode
        assert out
        assert out[0]["ranked_by"] == "composite_score"
        assert out[0]["num_legs"] == 4
        assert out[0]["selection_path"].startswith("greedy")


class TestNoValidParlay:
    def test_returns_nothing_when_pool_too_small(self):
        legs = [leg(i, 0.7, +100) for i in range(1, 4)]  # only 3
        assert build(legs, quality_floor_mode="percentile", quality_floor_value=0) == []

    def test_returns_nothing_when_all_legs_outside_the_odds_band(self):
        """
        Gate 2 still applies under v4. Legs at -2000 are outside [-250, +150]
        and are filtered before the search runs, leaving nothing to build from.

        Worth recording why there is no "odds floor unreachable" test: inside
        the odds band the shortest price is -250 (decimal 1.4), and 1.4^6 =
        7.53 > 5.0, so SIX in-band legs always clear +400. Within the band,
        infeasibility can only come from the pool being too small or from the
        roster constraints — never from the odds floor alone.
        """
        legs = [leg(i, 0.9, -2000, game=i) for i in range(1, 12)]
        out = build(legs, quality_floor_mode="percentile", quality_floor_value=0)
        assert out == []

    def test_constraints_can_make_it_infeasible(self):
        """Enough legs, but all in one game -> max 2 per game blocks a parlay."""
        legs = [leg(i, 0.75, +100, game=1) for i in range(1, 10)]
        out = build(legs, quality_floor_mode="percentile", quality_floor_value=0)
        assert out == []


class TestSearchDirectly:
    def test_returns_none_when_infeasible(self):
        legs = [leg(i, 0.8, -2000, game=i) for i in range(1, 8)]
        for l in legs:
            l["_dec"] = 1.05
        combo, nodes = _best_constrained_combo(legs, 4, MIN_DECIMAL, "p_hit")
        assert combo is None
        assert nodes > 0

    def test_exact_optimum_matches_brute_force(self):
        """The branch-and-bound must find the true optimum, not a good one."""
        import itertools
        from src.utils.odds_math import american_to_decimal
        legs = [leg(i, 0.50 + (i % 7) * 0.04, (-250 + (i % 5) * 90), game=i % 6)
                for i in range(1, 15)]
        for l in legs:
            l["_dec"] = american_to_decimal(str(l["best_odds"]))
        combo, _ = _best_constrained_combo(legs, 4, MIN_DECIMAL, "p_hit")

        best_bf, best_p = None, -1.0
        for c in itertools.combinations(legs, 4):
            if math.prod(l["_dec"] for l in c) < MIN_DECIMAL:
                continue
            games = {}
            for l in c:
                games[l["game_pk"]] = games.get(l["game_pk"], 0) + 1
            if max(games.values()) > 2:
                continue
            if len({l["player_id"] for l in c}) < 4:
                continue
            jp = math.prod(l["p_hit"] for l in c)
            if jp > best_p:
                best_p, best_bf = jp, c
        if best_bf is None:
            assert combo is None
        else:
            assert combo is not None
            assert math.prod(l["p_hit"] for l in combo) == pytest.approx(best_p)
