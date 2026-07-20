"""
tests/test_bug_fixes.py

Tests for three surgical bug fixes:
  FIX 1: parlay_builder.py — Cap parlays to fixed 4 legs (MAX_LEGS = 4)
  FIX 2: db.py — Persist lineup_consistency to database
  FIX 3: coverage.py — Add minimum sample-size floor to coverage_recent_10 (MIN_RECENT_GAMES = 5)
"""
import sys
from unittest.mock import MagicMock, patch

import pytest

# Stub 'main' before importing parlay_builder
_main_stub = MagicMock()
_main_stub.POOL_MIN_COVERAGE = 65.0
_main_stub.POOL_MIN_ODDS     = -250
_main_stub.POOL_MAX_ODDS     = 150
sys.modules.setdefault("main", _main_stub)

from src.engine.parlay_builder import (
    MAX_LEGS,
    MIN_LEGS,
    build_parlays,
)
from src.engine.coverage import (
    MIN_RECENT_GAMES,
    calculate_coverage,
)


# ─────────────────────────────────────────────────────────────────────────────
# FIX 1: parlay_builder.py — MAX_LEGS cap
# ─────────────────────────────────────────────────────────────────────────────

class TestMaxLegsConstant:
    """Verify that MAX_LEGS = 4 (not 6)."""

    def test_max_legs_is_four(self):
        """MAX_LEGS must be exactly 4."""
        assert MAX_LEGS == 4, f"Expected MAX_LEGS=4, got {MAX_LEGS}"

    def test_min_legs_is_four(self):
        """MIN_LEGS must equal MAX_LEGS (fixed 4-leg parlays)."""
        assert MIN_LEGS == 4, f"Expected MIN_LEGS=4, got {MIN_LEGS}"

    def test_max_equals_min(self):
        """Parlays should be fixed 4 legs (no variance)."""
        assert MAX_LEGS == MIN_LEGS, (
            f"MAX_LEGS ({MAX_LEGS}) must equal MIN_LEGS ({MIN_LEGS}) for fixed 4-leg parlays"
        )


class TestParlay4LegCap:
    """Verify that build_parlays never produces parlays with >4 legs."""

    def _make_leg(self, name, score=75, odds=+110, game_pk=1, odd_id=None):
        """Helper to create a valid leg dict."""
        return {
            "player_name": name,
            "player_id": f"id_{name}",
            "composite_score": score,
            "best_odds": odds,
            "coverage_pct": 62.5,
            "p_over": 0.6,
            "ev_per_unit": 0.05,
            "direction": "over",
            "game_pk": game_pk,
            "position": "DH",
            "stat": "hits",
            "best_line": 1.5,
            "odd_id": odd_id or f"oid_{name}",
        }

    def test_parlay_with_4_legs_built_successfully(self):
        """A parlay with exactly 4 legs should build successfully."""
        pool = [
            self._make_leg("PlayerA", score=80, game_pk=1, odd_id="oid_a"),
            self._make_leg("PlayerB", score=79, game_pk=2, odd_id="oid_b"),
            self._make_leg("PlayerC", score=78, game_pk=3, odd_id="oid_c"),
            self._make_leg("PlayerD", score=77, game_pk=4, odd_id="oid_d"),
            self._make_leg("PlayerE", score=76, game_pk=5, odd_id="oid_e"),
            self._make_leg("PlayerF", score=75, game_pk=6, odd_id="oid_f"),
        ]
        parlays = build_parlays(pool, top_n=1, num_games=6)

        assert len(parlays) >= 1, "Should build at least one parlay"
        assert parlays[0]["num_legs"] == 4, (
            f"First parlay should have exactly 4 legs, got {parlays[0]['num_legs']}"
        )

    def test_multiple_parlays_all_have_4_legs(self):
        """All parlays in the batch should have exactly 4 legs."""
        pool = [
            self._make_leg(f"P{i}", score=80-i, game_pk=i, odd_id=f"oid_{i}")
            for i in range(20)
        ]
        parlays = build_parlays(pool, top_n=5, num_games=15)

        for i, parlay in enumerate(parlays):
            assert parlay["num_legs"] == 4, (
                f"Parlay {i} should have exactly 4 legs, got {parlay['num_legs']}"
            )

    def test_insufficient_legs_no_parlay_built(self):
        """With fewer than 4 eligible legs, no parlay should be built."""
        pool = [
            self._make_leg("P1", score=75, game_pk=1, odd_id="oid_1"),
            self._make_leg("P2", score=74, game_pk=2, odd_id="oid_2"),
            self._make_leg("P3", score=73, game_pk=3, odd_id="oid_3"),
        ]
        parlays = build_parlays(pool, top_n=1, num_games=3)

        # Should return empty list since MIN_LEGS = MAX_LEGS = 4
        assert len(parlays) == 0, (
            "No parlay should be built when fewer than MIN_LEGS (4) legs available"
        )


# ─────────────────────────────────────────────────────────────────────────────
# FIX 2: db.py — lineup_consistency in INSERT statement
# ─────────────────────────────────────────────────────────────────────────────

class TestLineupConsistencyDbInsert:
    """Verify that lineup_consistency is included in log_scored_legs INSERT."""

    def test_log_scored_legs_includes_lineup_consistency_column(self):
        """The INSERT statement must list lineup_consistency in columns."""
        from src.utils import db
        import inspect

        source = inspect.getsource(db.log_scored_legs)

        # Check that column is in the INSERT
        assert "lineup_consistency" in source, (
            "lineup_consistency must appear in the INSERT INTO ... (columns...) list"
        )

    def test_log_scored_legs_includes_lineup_consistency_value(self):
        """The values tuple must include leg.get('lineup_consistency')."""
        from src.utils import db
        import inspect

        source = inspect.getsource(db.log_scored_legs)

        # Check that value extraction is present
        assert 'leg.get("lineup_consistency")' in source, (
            "Values tuple must extract lineup_consistency: leg.get('lineup_consistency')"
        )

    def test_log_scored_legs_includes_conflict_update(self):
        """The ON CONFLICT SET must include lineup_consistency."""
        from src.utils import db
        import inspect

        source = inspect.getsource(db.log_scored_legs)

        # Check that ON CONFLICT DO UPDATE includes lineup_consistency
        assert "lineup_consistency" in source and "ON CONFLICT" in source, (
            "lineup_consistency must be in the ON CONFLICT DO UPDATE SET clause"
        )

        # More specific check: COALESCE pattern for preservation
        assert "COALESCE(mlb_scored_legs.lineup_consistency" in source, (
            "Should use COALESCE to preserve existing lineup_consistency on conflict"
        )


# ─────────────────────────────────────────────────────────────────────────────
# FIX 3: coverage.py — MIN_RECENT_GAMES floor for coverage_recent_10
# ─────────────────────────────────────────────────────────────────────────────

class TestMinRecentGamesConstant:
    """Verify that MIN_RECENT_GAMES = 5."""

    def test_min_recent_games_is_five(self):
        """MIN_RECENT_GAMES must be exactly 5."""
        assert MIN_RECENT_GAMES == 5, (
            f"Expected MIN_RECENT_GAMES=5, got {MIN_RECENT_GAMES}"
        )


class TestCoverageRecent10Floor:
    """Verify that coverage_recent_10 returns None when recent_games < 5."""

    @patch("src.engine.coverage.get_batter_game_log")
    @patch("src.engine.coverage.get_pitcher_hand")
    @patch("src.engine.coverage.get_player_handedness")
    @patch("src.engine.coverage.get_season_minimum")
    def test_coverage_recent_10_none_with_fewer_than_5_games(
        self, mock_min, mock_hand, mock_pitcher_hand, mock_log
    ):
        """When fewer than 5 recent games, coverage_recent_10 should be None."""
        # Mock season minimum check to pass
        mock_min.return_value = 1

        # Mock a game log with 10 total games but only 2 in recent window
        # (This tests the "last 10 games" logic when there are only 2 games total)
        game_log = [
            {"stat": {"hits": 2}},
            {"stat": {"hits": 1}},
        ]
        mock_log.return_value = game_log
        mock_pitcher_hand.return_value = "R"
        mock_hand.return_value = "R"

        result = calculate_coverage(
            player_id=123456,
            prop_type="hits",
            line=1.5,
            opposing_pitcher_id=999,
            season=2026,
            position="DH",
            direction="over",
        )

        assert result is not None, "Result should not be None overall"
        assert result["coverage_recent_10"] is None, (
            f"coverage_recent_10 should be None with <5 recent games, got {result['coverage_recent_10']}"
        )

    @patch("src.engine.coverage.get_batter_game_log")
    @patch("src.engine.coverage.get_pitcher_hand")
    @patch("src.engine.coverage.get_player_handedness")
    @patch("src.engine.coverage.get_season_minimum")
    def test_coverage_recent_10_value_with_5_or_more_games(
        self, mock_min, mock_hand, mock_pitcher_hand, mock_log
    ):
        """When 5+ recent games, coverage_recent_10 should have a numeric value."""
        # Mock season minimum check to pass
        mock_min.return_value = 1

        # Create game log with enough total games and exactly 5 in recent window
        game_log = [
            {"stat": {"hits": 0}},  # Game 1
            {"stat": {"hits": 1}},  # Game 2
            {"stat": {"hits": 2}},  # Game 3
            {"stat": {"hits": 0}},  # Game 4
            {"stat": {"hits": 1}},  # Game 5 (recent window start, since last 10)
            {"stat": {"hits": 1}},  # Game 6
            {"stat": {"hits": 2}},  # Game 7
            {"stat": {"hits": 1}},  # Game 8
            {"stat": {"hits": 0}},  # Game 9
            {"stat": {"hits": 2}},  # Game 10
        ]
        mock_log.return_value = game_log
        mock_pitcher_hand.return_value = "R"
        mock_hand.return_value = "R"

        result = calculate_coverage(
            player_id=123456,
            prop_type="hits",
            line=1.5,
            opposing_pitcher_id=999,
            season=2026,
            position="DH",
            direction="over",
        )

        assert result is not None, "Result should not be None overall"
        assert result["coverage_recent_10"] is not None, (
            "coverage_recent_10 should have a value with >=5 recent games"
        )
        assert isinstance(result["coverage_recent_10"], (int, float)), (
            f"coverage_recent_10 should be numeric, got {type(result['coverage_recent_10'])}"
        )

    @patch("src.engine.coverage.get_pitcher_game_log")
    @patch("src.engine.coverage.get_season_minimum_pitcher")
    def test_pitcher_coverage_recent_10_none_with_fewer_than_5_games(
        self, mock_min, mock_log
    ):
        """For pitchers, coverage_recent_10 should also return None with <5 recent games."""
        # Mock season minimum check to pass
        mock_min.return_value = 1

        # Pitcher log with only 2 games total
        pitcher_log = [
            {"stat": {"strikeOuts": 8}},
            {"stat": {"strikeOuts": 7}},
        ]
        mock_log.return_value = pitcher_log

        result = calculate_coverage(
            player_id=999,
            prop_type="strikeouts",
            line=7.5,
            opposing_pitcher_id=None,
            season=2026,
            position="SP",
            direction="over",
        )

        assert result is not None, "Result should not be None overall"
        assert result["coverage_recent_10"] is None, (
            f"Pitcher coverage_recent_10 should be None with <5 recent games, got {result['coverage_recent_10']}"
        )

    @patch("src.engine.coverage.get_pitcher_game_log")
    @patch("src.engine.coverage.get_season_minimum_pitcher")
    def test_pitcher_coverage_recent_10_value_with_5_or_more_games(
        self, mock_min, mock_log
    ):
        """For pitchers, coverage_recent_10 should have a value with 5+ games."""
        # Mock season minimum check to pass
        mock_min.return_value = 1

        # Pitcher log with 10 games
        pitcher_log = [
            {"stat": {"strikeOuts": 6}},  # 1
            {"stat": {"strikeOuts": 8}},  # 2
            {"stat": {"strikeOuts": 7}},  # 3
            {"stat": {"strikeOuts": 9}},  # 4
            {"stat": {"strikeOuts": 8}},  # 5
            {"stat": {"strikeOuts": 10}},  # 6
            {"stat": {"strikeOuts": 7}},  # 7
            {"stat": {"strikeOuts": 8}},  # 8
            {"stat": {"strikeOuts": 9}},  # 9
            {"stat": {"strikeOuts": 8}},  # 10
        ]
        mock_log.return_value = pitcher_log

        result = calculate_coverage(
            player_id=999,
            prop_type="strikeouts",
            line=7.5,
            opposing_pitcher_id=None,
            season=2026,
            position="SP",
            direction="over",
        )

        assert result is not None, "Result should not be None overall"
        assert result["coverage_recent_10"] is not None, (
            "Pitcher coverage_recent_10 should have a value with >=5 recent games"
        )
        assert isinstance(result["coverage_recent_10"], (int, float)), (
            f"Pitcher coverage_recent_10 should be numeric, got {type(result['coverage_recent_10'])}"
        )
