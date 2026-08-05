"""
tests/test_main_gates_2026_08_05.py

Unit tests for the 2026-08-05 leg-scoring redesign's qualification gates in
main.py's _find_qualifying_legs():

  1. hits/over coverage floor lowered from 65% to 55%
  2. strikeouts/over coverage floor unchanged at 65%
  3. totalBases/over gated on sample size only (games >= 5 in
     mlb_player_batting_cumulative), not coverage_overall
  4. totalBases/under's existing 40% coverage_overall floor is unchanged
  5. ("totalBases", "over", 1.5) is in the ALLOWED_PROPS whitelist

main.py has a heavy import chain (statsapi, live API clients, src.utils.db).
All of it is stubbed out before import — the same pattern test_bug_fixes.py /
test_lineup_confirmation.py use for src.engine.parlay_builder.

Other test files (e.g. test_parlay_builder.py) need the REAL versions of some
of these same modules, and sys.modules is process-global — a stub left behind
here would silently break them depending on collection order. So every stub
is inserted with its prior sys.modules value recorded, and restored (removed,
or put back) once `import main` has captured its own bound references —
main.py doesn't need the stub to remain in sys.modules after that point.
"""
import sys
from unittest.mock import MagicMock, patch

import pytest

_STUB_MODULES = {
    "statsapi": MagicMock(),
    "src.apis.mlb_stats": MagicMock(),
    "src.apis.pitcher_stats": MagicMock(),
    "src.apis.sportsgameodds": MagicMock(),
    "src.pipelines.prop_legs_capture": MagicMock(),
    "src.apis.team_stats": MagicMock(),
    "src.engine.parlay_builder": MagicMock(),
    "src.pipelines.enrich_legs": MagicMock(),
    "src.pipelines.trend_analysis": MagicMock(),
    "src.utils.net": MagicMock(),
    "src.engine.coverage": MagicMock(),
    "src.utils.db": MagicMock(),
}
# main.py needs the real PROP_STAT_MAP values (used to reject unknown stats)
# but not the real calculate_coverage (network/DB) — stub the module, keep
# the real dict.
_STUB_MODULES["src.engine.coverage"].PROP_STAT_MAP = {
    "hits":        "hits",
    "totalBases":  "totalBases",
    "rbi":         "rbi",
    "homeRuns":    "homeRuns",
    "stolenBases": "stolenBases",
    "runsScored":  "runs",
    "walks":       "baseOnBalls",
    "strikeouts":  "strikeOuts",
}

_prior_modules = {name: sys.modules.get(name) for name in _STUB_MODULES}
for _name, _stub in _STUB_MODULES.items():
    sys.modules[_name] = _stub

import main  # noqa: E402

# Restore sys.modules to whatever it was before this file ran — main.py has
# already bound its own copies of every name it imported (calculate_coverage,
# PROP_STAT_MAP, set_player_position, get_batter_point_in_time_totals, ...),
# so it doesn't need these stubs to remain cached for other test files.
for _name, _prior in _prior_modules.items():
    if _prior is None:
        sys.modules.pop(_name, None)
    else:
        sys.modules[_name] = _prior


def _make_prop(stat, direction, line, odds=-150, odd_id="odd_1", player_name="Test Batter"):
    return {
        "stat": stat,
        "direction": direction,
        "standard_line": line,
        "standard_odds": odds,
        "odd_id": odd_id,
        "player_name": player_name,
        "ev_per_unit": 0.0,
    }


TEAM_MAPS = dict(
    team_id_to_abbr={1: "NYY"},
    team_abbr_to_game_pk={"NYY": 99999},
    pitcher_id_map={"NYY": 456},
)


def _run(prop, coverage_return, pt_totals_return=None):
    """Run _find_qualifying_legs for a single prop with common mocks wired up."""
    with patch("main._lookup_player_id", return_value=123), \
         patch("main.get_player_info", return_value={"position": "OF", "team_id": 1, "bats": "R"}), \
         patch("main.set_player_position"), \
         patch("main.calculate_coverage", return_value=coverage_return), \
         patch("main.get_batter_point_in_time_totals", return_value=pt_totals_return):
        return main._find_qualifying_legs(
            [prop], TEAM_MAPS["team_id_to_abbr"], TEAM_MAPS["team_abbr_to_game_pk"],
            TEAM_MAPS["pitcher_id_map"], season=2026, run_date="2026-08-05",
        )


class TestHitsOverGateLowered:
    """hits/over: floor lowered from 65% to 55% — no evidence 65% was calibrated."""

    def test_60pct_now_qualifies(self):
        prop = _make_prop("hits", "over", 0.5)
        coverage = {"coverage_overall": 60.0, "coverage_vs_hand": None,
                    "coverage_recent_10": 60.0, "games_total": 50,
                    "games_vs_hand": None, "games_recent": 10,
                    "pitcher_hand": "R", "batter_hand": "R"}
        legs = _run(prop, coverage)
        assert len(legs) == 1, "60% coverage should qualify under the new 55% floor"

    def test_below_55pct_still_rejected(self):
        prop = _make_prop("hits", "over", 0.5)
        coverage = {"coverage_overall": 50.0, "coverage_vs_hand": None,
                    "coverage_recent_10": 50.0, "games_total": 50,
                    "games_vs_hand": None, "games_recent": 10,
                    "pitcher_hand": "R", "batter_hand": "R"}
        legs = _run(prop, coverage)
        assert legs == [], "50% coverage is still below the new 55% floor"


class TestStrikeoutsOverGateUnchanged:
    """strikeouts/over: no validated fix — floor stays at 65%."""

    def test_60pct_still_rejected(self):
        prop = _make_prop("strikeouts", "over", 0.5)
        coverage = {"coverage_overall": 60.0, "coverage_vs_hand": None,
                    "coverage_recent_10": 60.0, "games_total": 50,
                    "games_vs_hand": None, "games_recent": 10,
                    "pitcher_hand": "R", "batter_hand": "R"}
        legs = _run(prop, coverage)
        assert legs == [], "60% coverage must stay rejected — strikeouts gate is unchanged at 65%"

    def test_70pct_qualifies(self):
        prop = _make_prop("strikeouts", "over", 0.5)
        coverage = {"coverage_overall": 70.0, "coverage_vs_hand": None,
                    "coverage_recent_10": 70.0, "games_total": 50,
                    "games_vs_hand": None, "games_recent": 10,
                    "pitcher_hand": "R", "batter_hand": "R"}
        legs = _run(prop, coverage)
        assert len(legs) == 1


class TestTotalBasesOverSampleSizeGate:
    """totalBases/over: no coverage_overall gate — sample size only (games >= 5)."""

    def test_five_games_qualifies_even_with_no_coverage(self):
        prop = _make_prop("totalBases", "over", 1.5)
        legs = _run(prop, coverage_return=None,
                    pt_totals_return={"games": 5.0, "total_bases": 10.0})
        assert len(legs) == 1, "5 games should qualify regardless of coverage_overall"
        assert legs[0]["pt_tb_rate"] == pytest.approx(2.0)

    def test_four_games_rejected(self):
        prop = _make_prop("totalBases", "over", 1.5)
        legs = _run(prop, coverage_return=None,
                    pt_totals_return={"games": 4.0, "total_bases": 8.0})
        assert legs == [], "4 games is below the 5-game sample-size floor"

    def test_no_cumulative_row_rejected(self):
        prop = _make_prop("totalBases", "over", 1.5)
        legs = _run(prop, coverage_return=None, pt_totals_return=None)
        assert legs == [], "No mlb_player_batting_cumulative row before run_date must reject"

    def test_high_coverage_overall_does_not_bypass_sample_gate(self):
        # Even a hypothetical 90% coverage_overall shouldn't matter for this
        # direction — the gate is sample-size only.
        prop = _make_prop("totalBases", "over", 1.5)
        coverage = {"coverage_overall": 90.0, "coverage_vs_hand": None,
                    "coverage_recent_10": 90.0, "games_total": 50,
                    "games_vs_hand": None, "games_recent": 10,
                    "pitcher_hand": "R", "batter_hand": "R"}
        legs = _run(prop, coverage, pt_totals_return={"games": 3.0, "total_bases": 6.0})
        assert legs == [], "3 games must still fail the sample-size gate despite high coverage"


class TestTotalBasesUnderGateUnchanged:
    """totalBases/under keeps its existing coverage_overall >= 40% gate."""

    def test_below_40pct_rejected(self):
        prop = _make_prop("totalBases", "under", 1.5)
        coverage = {"coverage_overall": 35.0, "coverage_vs_hand": None,
                    "coverage_recent_10": 35.0, "games_total": 50,
                    "games_vs_hand": None, "games_recent": 10,
                    "pitcher_hand": "R", "batter_hand": "R"}
        legs = _run(prop, coverage)
        assert legs == []

    def test_above_40pct_qualifies(self):
        prop = _make_prop("totalBases", "under", 1.5)
        coverage = {"coverage_overall": 45.0, "coverage_vs_hand": None,
                    "coverage_recent_10": 45.0, "games_total": 50,
                    "games_vs_hand": None, "games_recent": 10,
                    "pitcher_hand": "R", "batter_hand": "R"}
        legs = _run(prop, coverage)
        assert len(legs) == 1


class TestAllowedPropsWhitelist:
    def test_totalbases_over_1_5_is_whitelisted(self):
        prop = _make_prop("totalBases", "over", 1.5)
        legs = _run(prop, coverage_return=None,
                    pt_totals_return={"games": 5.0, "total_bases": 10.0})
        assert len(legs) == 1

    def test_unlisted_totalbases_line_still_rejected(self):
        prop = _make_prop("totalBases", "over", 2.5)  # not in ALLOWED_PROPS
        legs = _run(prop, coverage_return=None,
                    pt_totals_return={"games": 5.0, "total_bases": 10.0})
        assert legs == [], "Only the 1.5 line is whitelisted for totalBases"
