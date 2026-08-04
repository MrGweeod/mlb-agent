"""
tests/test_parlay_builder.py

Regression tests for the floor-recovery fix in src/engine/parlay_builder.py.

Bug: build_parlays() picked legs by a single greedy pass sorted only by
composite_score, then checked the +400 odds floor only after 4 legs were
already locked in. If the top-4-by-score combination missed the floor, the
function gave up entirely for that parlay slot instead of trying an
alternative combination — reproduced live on 2026-08-04 (top-4 landed at
+337, zero parlays produced despite 36 eligible legs in the pool).

Fix: when the top-4 pick misses the floor, _attempt_swap_recovery() tries
single-leg swaps against progressively lower-scored eligible alternatives
(bounded to len(legs) * SWAP_CANDIDATE_LIMIT attempts) and keeps the
floor-clearing swap with the highest total composite_score.
"""
import sys
from unittest.mock import MagicMock

# src/engine/parlay_builder.py imports src.utils.db, which connects to
# Postgres at module import time (no DATABASE_URL in this local environment).
# get_players_used_today() is only used by filter_already_used_players(),
# not by build_parlays() under test here, so a stub is sufficient.
_db_stub = MagicMock()
_db_stub.get_players_used_today = MagicMock(return_value=set())
sys.modules.setdefault("src.utils.db", _db_stub)

from src.engine.parlay_builder import (  # noqa: E402
    MIN_LEGS,
    MIN_PARLAY_ODDS,
    SWAP_CANDIDATE_LIMIT,
    _attempt_swap_recovery,
    _combined_decimal,
    build_parlays,
)


def _leg(player_id, score, odds, game_pk=None, position="OF", direction="over", coverage_pct=70.0):
    return {
        "player_id":       player_id,
        "player_name":     f"Player {player_id}",
        "composite_score": score,
        "best_odds":       odds,
        "game_pk":         game_pk if game_pk is not None else player_id,
        "position":        position,
        "odd_id":          f"odd_{player_id}",
        "direction":       direction,
        "coverage_pct":    coverage_pct,
    }


class TestCleanTopFourPass:
    """(a) Top-4-by-score already clears the floor — unchanged behavior."""

    def test_clean_pass_unchanged(self):
        legs = [
            _leg(1, 90, -150),
            _leg(2, 85, -150),
            _leg(3, 80, -150),
            _leg(4, 75, -150),
            _leg(5, 70, -150),  # extra pool depth, not needed for the pick
        ]
        result = build_parlays(legs, top_n=1, num_games=15)

        assert len(result) == 1
        parlay = result[0]
        assert parlay["num_legs"] == MIN_LEGS
        picked_players = {l["player_id"] for l in parlay["legs"]}
        assert picked_players == {1, 2, 3, 4}, "must pick the top 4 by score, no swap needed"
        assert int(parlay["parlay_odds"].lstrip("+")) >= MIN_PARLAY_ODDS


class TestSwapRecovery:
    """(b) Top-4 misses the floor but a valid swap exists."""

    def test_recovery_picks_highest_scoring_valid_swap(self):
        # Top 4 by score (-220 each => decimal ~1.4545, combined ~4.48) miss the +400 floor (needs 5.0).
        top4 = [
            _leg(1, 90, -220, game_pk=101),
            _leg(2, 85, -220, game_pk=102),
            _leg(3, 80, -220, game_pk=103),
            _leg(4, 75, -220, game_pk=104),
        ]
        # Two floor-clearing alternatives once swapped in for the lowest-scored leg (75):
        # alt_b (score 68, +100) yields a higher total score than alt_a (score 65, +150),
        # even though alt_a's odds are juicier — recovery must prefer total score, not odds.
        alt_a = _leg(5, 65, 150, game_pk=105)
        alt_b = _leg(6, 68, 100, game_pk=106)

        pool = top4 + [alt_a, alt_b]
        result = build_parlays(pool, top_n=1, num_games=15)

        assert len(result) == 1, "a valid floor-clearing swap exists and must be used"
        parlay = result[0]
        assert parlay["num_legs"] == MIN_LEGS
        assert int(parlay["parlay_odds"].lstrip("+")) >= MIN_PARLAY_ODDS

        picked_ids = {l["player_id"] for l in parlay["legs"]}
        # The lowest-scored original leg (75, player 4) must be the one swapped out,
        # and alt_b (higher total score than alt_a) must be the one swapped in.
        assert picked_ids == {1, 2, 3, 6}, f"expected the max-total-score swap, got players {picked_ids}"

    def test_attempt_swap_recovery_returns_best_not_first(self):
        """Unit-level check directly on the helper: among multiple floor-clearing
        swaps, the one with the highest total composite_score is returned."""
        legs = [
            _leg(1, 90, -220, game_pk=101),
            _leg(2, 85, -220, game_pk=102),
            _leg(3, 80, -220, game_pk=103),
            _leg(4, 75, -220, game_pk=104),
        ]
        for l in legs:
            l["_dec"] = 1.4545454545454546  # matches -220 american_to_decimal
        alt_a = _leg(5, 65, 150, game_pk=105)
        alt_a["_dec"] = 2.5
        alt_b = _leg(6, 68, 100, game_pk=106)
        alt_b["_dec"] = 2.0

        min_decimal = MIN_PARLAY_ODDS / 100 + 1  # 5.0
        pool = legs + [alt_a, alt_b]

        new_legs, attempts = _attempt_swap_recovery(legs, pool, min_decimal)

        assert new_legs is not None
        assert attempts <= len(legs) * SWAP_CANDIDATE_LIMIT, "search must stay bounded"
        assert _combined_decimal(new_legs) >= min_decimal
        new_ids = {l["player_id"] for l in new_legs}
        assert new_ids == {1, 2, 3, 6}

    def test_recovery_finds_good_odds_leg_ranked_far_down_by_score(self):
        """
        Regression for a real gap found via live-data testing on 2026-08-04:
        an early version of the swap search only considered the next 10
        best-SCORED alternatives, which missed a real floor-clearing
        combination because the legs with the best (least negative) odds
        were ranked 18th-33rd by score, not in the top 10 — composite_score
        and odds are not correlated. The search must consider the full
        remaining pool, not just a score-sorted top-N slice.
        """
        top4 = [
            _leg(1, 83, -222, game_pk=101),
            _leg(2, 79, -244, game_pk=102),
            _leg(3, 77, -229, game_pk=103),
            _leg(4, 77, -201, game_pk=104),
        ]
        # 20 mediocre-odds "filler" legs ranked between the top 4 and the
        # real rescue leg, none of which can individually clear the floor
        # when swapped in (all short odds, same as the top 4).
        filler = [
            _leg(10 + i, 76 - i, -220, game_pk=200 + i)
            for i in range(20)
        ]
        # The actual rescue: modest score (67, ranked ~25th overall) but
        # much longer odds (-123) than everything else in the pool.
        rescue = _leg(999, 67, -123, game_pk=999)

        pool = top4 + filler + [rescue]
        result = build_parlays(pool, top_n=1, num_games=15)

        assert len(result) == 1, "a real floor-clearing swap exists deep in the pool and must be found"
        picked_ids = {l["player_id"] for l in result[0]["legs"]}
        assert 999 in picked_ids, "the good-odds leg ranked far down by score must be part of the recovered parlay"

    def test_swap_candidate_sharing_player_is_rejected(self):
        """A candidate for the same player as an unswapped leg must never be
        accepted, even if it would clear the floor and score higher."""
        from src.engine.parlay_builder import _leg_fits

        other_legs = [_leg(1, 90, -220), _leg(2, 85, -220), _leg(3, 80, -220)]
        dup_player_candidate = _leg(1, 99, 500)  # same player_id as other_legs[0]
        assert _leg_fits(dup_player_candidate, other_legs) is False

    def test_swap_candidate_over_per_game_cap_is_rejected(self):
        from src.engine.parlay_builder import _leg_fits, MAX_LEGS_PER_GAME

        other_legs = [
            _leg(1, 90, -220, game_pk=101),
            _leg(2, 85, -220, game_pk=101),  # game 101 already at MAX_LEGS_PER_GAME (2)
            _leg(3, 80, -220, game_pk=103),
        ]
        assert MAX_LEGS_PER_GAME == 2
        candidate = _leg(4, 99, 500, game_pk=101)  # would make game 101 a 3rd leg
        assert _leg_fits(candidate, other_legs) is False

    def test_swap_candidate_duplicate_odd_id_is_rejected(self):
        from src.engine.parlay_builder import _leg_fits

        other_legs = [_leg(1, 90, -220), _leg(2, 85, -220)]
        candidate = dict(_leg(5, 99, 500))
        candidate["odd_id"] = other_legs[0]["odd_id"]
        assert _leg_fits(candidate, other_legs) is False

    def test_swap_candidate_respecting_all_constraints_is_accepted(self):
        from src.engine.parlay_builder import _leg_fits

        other_legs = [
            _leg(1, 90, -220, game_pk=101),
            _leg(2, 85, -220, game_pk=102),
            _leg(3, 80, -220, game_pk=103),
        ]
        candidate = _leg(4, 68, 100, game_pk=104)
        assert _leg_fits(candidate, other_legs) is True


class TestNoValidCombination:
    """(c) No combination in the pool can clear the floor — legitimate failure."""

    def test_no_combination_reports_failure_cleanly(self):
        # Every leg's odds are short enough that no 4-of-N combination can
        # reach the +400 floor, even after every possible swap.
        legs = [_leg(pid, 90 - pid, -240, game_pk=pid) for pid in range(1, 7)]
        result = build_parlays(legs, top_n=1, num_games=15)

        assert result == [], "must report a clean failure, not a crash or a below-floor parlay"

    def test_no_combination_does_not_hang(self):
        """Bounded search: attempts must scale linearly, not explode, even
        with a larger pool of alternatives."""
        from src.utils.odds_math import american_to_decimal

        legs = [_leg(pid, 100 - pid, -240, game_pk=pid) for pid in range(1, 51)]
        top4 = legs[:MIN_LEGS]
        min_decimal = MIN_PARLAY_ODDS / 100 + 1
        for l in legs:
            l["_dec"] = american_to_decimal(str(l["best_odds"]))

        new_legs, attempts = _attempt_swap_recovery(top4, legs, min_decimal)

        assert new_legs is None
        assert attempts <= MIN_LEGS * SWAP_CANDIDATE_LIMIT
