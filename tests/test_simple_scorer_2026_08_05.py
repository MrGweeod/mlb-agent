"""
tests/test_simple_scorer_2026_08_05.py

Unit tests for the 2026-08-05 leg-scoring redesign's changes to
src/engine/simple_scorer.py:

  1. hits/over uses effective_era (falls back to raw pitcher_era when absent)
  2. hits/under is unchanged — still uses raw pitcher_era
  3. totalBases/over scores purely on pt_tb_rate's percentile rank in the pool
  4. strikeouts scoring is byte-for-byte unchanged
  5. scorer_version is stamped on every leg by score_legs()

Pure-function module — no network or DB access, no stubbing required.
"""
import pytest

from src.engine.simple_scorer import (
    SCORER_VERSION,
    calculate_composite_score,
    score_legs,
    _attach_totalbases_over_percentiles,
)


def _hits_leg(direction="over", coverage_overall=70.0, effective_era=None, pitcher_era=None):
    return {
        "stat": "hits",
        "direction": direction,
        "coverage_overall": coverage_overall,
        "coverage_vs_hand": None,
        "coverage_recent_10": None,
        "effective_era": effective_era,
        "pitcher_era": pitcher_era,
        "lineup_consistency": None,
    }


class TestHitsOverUsesEffectiveEra:
    def test_weak_effective_era_boosts_over_score(self):
        # effective_era says "weak" (>5.0) while raw pitcher_era says "ace" (<3.0) —
        # if effective_era is actually being used, the score should reflect "weak".
        leg = _hits_leg(direction="over", effective_era=5.5, pitcher_era=2.0)
        score = calculate_composite_score(leg)
        assert score == pytest.approx(75.0)  # 70 base + 5 (weak pitcher bonus)

    def test_ace_effective_era_penalizes_over_score(self):
        leg = _hits_leg(direction="over", effective_era=2.5, pitcher_era=6.0)
        score = calculate_composite_score(leg)
        assert score == pytest.approx(65.0)  # 70 base - 5 (ace pitcher penalty)

    def test_falls_back_to_raw_era_when_effective_era_missing(self):
        # e.g. season-opener with no rolling-IP data yet
        leg = _hits_leg(direction="over", effective_era=None, pitcher_era=5.5)
        score = calculate_composite_score(leg)
        assert score == pytest.approx(75.0)


class TestHitsUnderUnaffected:
    def test_under_uses_raw_era_not_effective_era(self):
        # hits/under was not part of the validated exposure fix — effective_era
        # must NOT be consulted here even when present. pitcher_era (ace, <3.0)
        # and effective_era (weak, >5.0) fall into different threshold buckets
        # here specifically so the two are distinguishable.
        leg = _hits_leg(direction="under", effective_era=5.5, pitcher_era=2.0)
        score = calculate_composite_score(leg)
        # ace branch: score -= (5 if over else -5) == score -= -5 == +5 -> 75.0.
        # (If effective_era's "weak" bucket were used instead, this would be 65.0.)
        assert score == pytest.approx(75.0)


class TestTotalBasesOverPercentileScoring:
    def test_scores_ignore_coverage_and_use_percentile_only(self):
        legs = [
            {"stat": "totalBases", "direction": "over", "pt_tb_rate": 1.0,
             "coverage_overall": 99.0},  # coverage_overall must be ignored
            {"stat": "totalBases", "direction": "over", "pt_tb_rate": 2.0,
             "coverage_overall": 1.0},
            {"stat": "totalBases", "direction": "over", "pt_tb_rate": 3.0,
             "coverage_overall": 50.0},
        ]
        score_legs(legs)
        scores = [l["composite_score"] for l in legs]
        # Highest pt_tb_rate must score highest, regardless of coverage_overall.
        assert scores[2] > scores[1] > scores[0]

    def test_percentile_formula_exact(self):
        legs = [
            {"stat": "totalBases", "direction": "over", "pt_tb_rate": 1.0},
            {"stat": "totalBases", "direction": "over", "pt_tb_rate": 2.0},
            {"stat": "totalBases", "direction": "over", "pt_tb_rate": 3.0},
            {"stat": "totalBases", "direction": "over", "pt_tb_rate": 4.0},
        ]
        _attach_totalbases_over_percentiles(legs)
        percentiles = [l["tb_percentile_score"] for l in legs]
        assert percentiles == [25.0, 50.0, 75.0, 100.0]

    def test_other_stats_not_included_in_percentile_pool(self):
        legs = [
            {"stat": "totalBases", "direction": "over", "pt_tb_rate": 1.0},
            {"stat": "hits", "direction": "over", "pt_tb_rate": 999.0},  # must be ignored
        ]
        _attach_totalbases_over_percentiles(legs)
        assert legs[0]["tb_percentile_score"] == 100.0
        assert "tb_percentile_score" not in legs[1]

    def test_missing_pt_tb_rate_falls_back_to_neutral(self):
        leg = {"stat": "totalBases", "direction": "over"}  # no pt_tb_rate at all
        score = calculate_composite_score(leg)
        assert score == 50  # neutral default, clamped range is a no-op here


class TestStrikeoutsScoringUnchanged:
    """Confirms the 2026-08-05 redesign left strikeout scoring untouched."""

    def _leg(self, k9_rank=None, pitcher_k9=None, lineup_consistency=None):
        return {
            "stat": "strikeouts",
            "direction": "over",
            "coverage_overall": 70.0,
            "coverage_vs_hand": None,
            "coverage_recent_10": None,
            "opp_pitcher_k9_rank": k9_rank,
            "pitcher_k9": pitcher_k9,
            "lineup_consistency": lineup_consistency,
        }

    def test_elite_k9_rank_boosts_score(self):
        leg = self._leg(k9_rank=5)
        assert calculate_composite_score(leg) == pytest.approx(75.0)

    def test_weak_k9_rank_penalizes_score(self):
        leg = self._leg(k9_rank=25)
        assert calculate_composite_score(leg) == pytest.approx(65.0)

    def test_falls_back_to_raw_k9_when_rank_missing(self):
        leg = self._leg(k9_rank=None, pitcher_k9=11.0)
        assert calculate_composite_score(leg) == pytest.approx(75.0)


class TestScorerVersionStamped:
    def test_every_leg_gets_scorer_version(self):
        legs = [
            {"stat": "hits", "direction": "over", "coverage_overall": 60.0},
            {"stat": "strikeouts", "direction": "over", "coverage_overall": 70.0},
            {"stat": "totalBases", "direction": "over", "pt_tb_rate": 2.0},
            {"stat": "totalBases", "direction": "under", "coverage_overall": 45.0},
        ]
        score_legs(legs)
        for leg in legs:
            assert leg["scorer_version"] == SCORER_VERSION
        assert SCORER_VERSION == "v2_2026-08-05"


class TestNoPitcherRoleStrikeoutProps:
    """
    Confirms the scoring redesign didn't accidentally open a path for
    pitcher-thrown strikeout props — pitcher strikeouts stay explicitly out
    of scope (see docs/ARCHITECTURE_DECISIONS.md). simple_scorer.py has no
    position-based branching at all; this is a documentation-level guard so a
    future change to this file doesn't silently add one.
    """
    def test_strikeouts_scoring_has_no_position_field_dependency(self):
        leg = {
            "stat": "strikeouts",
            "direction": "over",
            "coverage_overall": 70.0,
            "position": "SP",  # even if a pitcher-role leg slipped through
            "opp_pitcher_k9_rank": 5,
        }
        # simple_scorer.py doesn't gate on position — that filtering happens
        # upstream in main.py (`Skip all pitchers` in _find_qualifying_legs).
        # This just documents that scoring itself is position-agnostic.
        assert calculate_composite_score(leg) == pytest.approx(75.0)
