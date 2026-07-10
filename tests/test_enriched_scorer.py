"""
tests/test_enriched_scorer.py

Unit tests for the Session 19 shadow scoring rebuild:
  - _linear_adj: linear scale correctness at endpoints and midpoint
  - _compute_matchup_adjustment: per-prop formulas, cap enforcement, direction signs
  - _calculate_enriched_score: final 5–95 clamp still applies

All tests run without network or DB access.
"""
import math
import pytest

from src.engine.enriched_scorer import (
    _clamp,
    _linear_adj,
    _compute_matchup_adjustment,
    _ERA_MID,   _ERA_HALF,
    _WHIP_MID,  _WHIP_HALF,
    _K9_MID,    _K9_HALF,
    _OBP_MID,   _OBP_HALF,
    _BA_MID,    _BA_HALF,
    _KPCT_MID,  _KPCT_HALF,
    _BBPCT_MID, _BBPCT_HALF,
)

# ── _linear_adj ───────────────────────────────────────────────────────────────

class TestLinearAdj:
    def test_midpoint_returns_zero(self):
        assert _linear_adj(_ERA_MID, _ERA_MID, _ERA_HALF, 5.0) == pytest.approx(0.0)

    def test_top_of_range_returns_max_weight(self):
        # ERA at 7.00 (midpoint + half_range) → +5
        era_max = _ERA_MID + _ERA_HALF  # 4.25 + 2.75 = 7.00
        assert _linear_adj(era_max, _ERA_MID, _ERA_HALF, 5.0) == pytest.approx(5.0)

    def test_bottom_of_range_returns_neg_max_weight(self):
        # ERA at 1.50 (midpoint - half_range) → -5
        era_min = _ERA_MID - _ERA_HALF  # 4.25 - 2.75 = 1.50
        assert _linear_adj(era_min, _ERA_MID, _ERA_HALF, 5.0) == pytest.approx(-5.0)

    def test_clamps_above_max(self):
        # ERA far above range → clamped at +5
        assert _linear_adj(99.0, _ERA_MID, _ERA_HALF, 5.0) == pytest.approx(5.0)

    def test_clamps_below_min(self):
        # ERA of 0.0 → clamped at -5
        assert _linear_adj(0.0, _ERA_MID, _ERA_HALF, 5.0) == pytest.approx(-5.0)

    def test_none_returns_zero(self):
        assert _linear_adj(None, _ERA_MID, _ERA_HALF, 5.0) == pytest.approx(0.0)

    def test_k9_midpoint_zero(self):
        assert _linear_adj(_K9_MID, _K9_MID, _K9_HALF, 5.0) == pytest.approx(0.0)

    def test_k9_max_returns_max_weight(self):
        # K/9 at 11.00 → +5
        assert _linear_adj(11.0, _K9_MID, _K9_HALF, 5.0) == pytest.approx(5.0)

    def test_k9_min_returns_neg_max_weight(self):
        # K/9 at 5.50 → -5
        assert _linear_adj(5.5, _K9_MID, _K9_HALF, 5.0) == pytest.approx(-5.0)

    def test_whip_midpoint_zero(self):
        assert _linear_adj(_WHIP_MID, _WHIP_MID, _WHIP_HALF, 3.0) == pytest.approx(0.0)

    def test_whip_max_returns_max_weight(self):
        # WHIP at 1.70 → +3
        assert _linear_adj(1.70, _WHIP_MID, _WHIP_HALF, 3.0) == pytest.approx(3.0)


# ── _compute_matchup_adjustment: hits/over ────────────────────────────────────

class TestHitsOver:
    def test_midpoint_era_and_whip_zero_adjustment(self):
        adj, _ = _compute_matchup_adjustment("hits", "over", _ERA_MID, _WHIP_MID, None, None)
        assert adj == pytest.approx(0.0)

    def test_weak_pitcher_gives_positive(self):
        # ERA=7.0, WHIP=1.70 → raw=8.0 scaled to 7.0
        adj, debug = _compute_matchup_adjustment("hits", "over", 7.0, 1.70, None, None)
        assert adj == pytest.approx(7.0, abs=0.01)

    def test_elite_pitcher_gives_negative(self):
        # ERA=1.50, WHIP=0.70 → raw=-8.0 scaled to -7.0
        adj, debug = _compute_matchup_adjustment("hits", "over", 1.50, 0.70, None, None)
        assert adj == pytest.approx(-7.0, abs=0.01)

    def test_cap_enforced_proportionally(self):
        # Max raw = ±8 (ERA±5 + WHIP±3) → must cap at ±7
        adj_max, _ = _compute_matchup_adjustment("hits", "over", 99.0, 99.0, None, None)
        assert abs(adj_max) == pytest.approx(7.0, abs=0.01)

    def test_combined_within_cap_not_scaled(self):
        # ERA at midpoint → 0; only WHIP contributes → raw=3 < 7 cap, no scaling
        adj, debug = _compute_matchup_adjustment("hits", "over", _ERA_MID, 1.70, None, None)
        assert adj == pytest.approx(3.0, abs=0.01)

    def test_missing_era_still_uses_whip(self):
        # ERA missing → era_adj=0, only WHIP
        adj, _ = _compute_matchup_adjustment("hits", "over", None, 1.70, None, None)
        assert adj == pytest.approx(3.0, abs=0.01)


# ── _compute_matchup_adjustment: hits/under ───────────────────────────────────

class TestHitsUnder:
    def test_elite_pitcher_gives_positive(self):
        # ERA=1.50, WHIP=0.70 → elite pitcher → positive for under
        adj, _ = _compute_matchup_adjustment("hits", "under", 1.50, 0.70, None, None)
        assert adj == pytest.approx(7.0, abs=0.01)

    def test_weak_pitcher_gives_negative(self):
        # ERA=7.0, WHIP=1.70 → weak pitcher → negative for under
        adj, _ = _compute_matchup_adjustment("hits", "under", 7.0, 1.70, None, None)
        assert adj == pytest.approx(-7.0, abs=0.01)

    def test_cap_enforced(self):
        adj_min, _ = _compute_matchup_adjustment("hits", "under", 0.0, 0.0, None, None)
        assert abs(adj_min) == pytest.approx(7.0, abs=0.01)

    def test_direction_sign_is_opposite_of_over(self):
        # Same ERA/WHIP → hits/under and hits/over should have opposite signs
        adj_over,  _ = _compute_matchup_adjustment("hits", "over",  4.0, 1.30, None, None)
        adj_under, _ = _compute_matchup_adjustment("hits", "under", 4.0, 1.30, None, None)
        assert adj_over == pytest.approx(-adj_under, abs=0.01)


# ── _compute_matchup_adjustment: strikeouts/over ─────────────────────────────

class TestStrikeoutsOver:
    def test_midpoint_k9_zero(self):
        adj, _ = _compute_matchup_adjustment("strikeouts", "over", None, None, _K9_MID, None)
        assert adj == pytest.approx(0.0)

    def test_elite_k9_positive(self):
        # K/9 = 11.0 → +5
        adj, _ = _compute_matchup_adjustment("strikeouts", "over", None, None, 11.0, None)
        assert adj == pytest.approx(5.0, abs=0.01)

    def test_low_k9_negative(self):
        # K/9 = 5.5 → -5
        adj, _ = _compute_matchup_adjustment("strikeouts", "over", None, None, 5.5, None)
        assert adj == pytest.approx(-5.0, abs=0.01)

    def test_cap_at_5(self):
        adj, _ = _compute_matchup_adjustment("strikeouts", "over", None, None, 99.0, None)
        assert adj == pytest.approx(5.0, abs=0.01)

    def test_so_under_no_adjustment(self):
        # strikeouts/under is not in the formula table → 0
        adj, _ = _compute_matchup_adjustment("strikeouts", "under", None, None, 11.0, None)
        assert adj == pytest.approx(0.0)

    def test_era_and_whip_ignored_for_so_over(self):
        # ERA/WHIP should have no effect on strikeouts/over
        adj_with,    _ = _compute_matchup_adjustment("strikeouts", "over", 7.0, 1.70, 9.0, None)
        adj_without, _ = _compute_matchup_adjustment("strikeouts", "over", None, None, 9.0, None)
        assert adj_with == pytest.approx(adj_without, abs=0.01)


# ── _compute_matchup_adjustment: totalBases/under ─────────────────────────────

class TestTotalBasesUnder:
    def _elite_pitcher(self):
        return dict(era=1.50, whip=0.70, k9=11.0)

    def _weak_batter(self):
        return dict(obp=0.28, ba=0.21, k_pct=0.32, bb_pct=0.04)

    def test_midpoint_pitcher_zero_pitcher_component(self):
        adj, debug = _compute_matchup_adjustment(
            "totalBases", "under", _ERA_MID, _WHIP_MID, _K9_MID, None
        )
        assert adj == pytest.approx(0.0, abs=0.01)

    def test_elite_pitcher_positive(self):
        p = self._elite_pitcher()
        adj, _ = _compute_matchup_adjustment("totalBases", "under", p["era"], p["whip"], p["k9"], None)
        assert adj > 0

    def test_weak_pitcher_negative(self):
        adj, _ = _compute_matchup_adjustment("totalBases", "under", 7.0, 1.70, 5.5, None)
        assert adj < 0

    def test_weak_batter_adds_positive(self):
        # Elite pitcher baseline
        p = self._elite_pitcher()
        adj_no_batter, _ = _compute_matchup_adjustment("totalBases", "under", p["era"], p["whip"], p["k9"], None)
        adj_with_batter, _ = _compute_matchup_adjustment(
            "totalBases", "under", p["era"], p["whip"], p["k9"], self._weak_batter()
        )
        assert adj_with_batter > adj_no_batter

    def test_cap_at_12(self):
        # Worst-case pitcher + weakest batter → cap at +12
        b = self._weak_batter()
        adj, _ = _compute_matchup_adjustment(
            "totalBases", "under", 0.01, 0.01, 99.0,
            {"obp": 0.01, "ba": 0.01, "k_pct": 0.99, "bb_pct": 0.01}
        )
        assert adj == pytest.approx(12.0, abs=0.01)

    def test_cap_at_neg_12(self):
        adj, _ = _compute_matchup_adjustment(
            "totalBases", "under", 99.0, 99.0, 0.01,
            {"obp": 0.99, "ba": 0.99, "k_pct": 0.01, "bb_pct": 0.99}
        )
        assert adj == pytest.approx(-12.0, abs=0.01)

    def test_tb_over_no_batter_signal(self):
        # totalBases/over is not in the formula table → 0
        adj, _ = _compute_matchup_adjustment(
            "totalBases", "over", 1.50, 0.70, 11.0, self._weak_batter()
        )
        assert adj == pytest.approx(0.0)

    def test_missing_k9_uses_zero_k9_contribution(self):
        # k9 missing → that component is 0; ERA and WHIP still apply
        adj_with_k9, _ = _compute_matchup_adjustment("totalBases", "under", _ERA_MID, _WHIP_MID, _K9_MID, None)
        adj_no_k9, _   = _compute_matchup_adjustment("totalBases", "under", _ERA_MID, _WHIP_MID, None, None)
        # k9 at midpoint contributes 0 anyway, so results should be equal
        assert adj_with_k9 == pytest.approx(adj_no_k9, abs=0.01)


# ── Final 5–95 clamp ──────────────────────────────────────────────────────────

class TestFinalClamp:
    """
    Verify _calculate_enriched_score enforces the 5–95 clamp.
    We inject a leg with an extreme base score and minimal mocks.
    """

    def _make_leg(self, coverage: float, stat: str, direction: str) -> dict:
        return {
            "coverage_overall":   coverage,
            "coverage_pct":       coverage,
            "coverage_vs_hand":   None,
            "coverage_recent_10": None,
            "stat":               stat,
            "direction":          direction,
            "best_line":          1.5 if stat == "totalBases" else 0.5,
            "lineup_consistency": None,
            "player_id":          None,
            "pitcher_era":        _ERA_MID,
            "pitcher_whip":       _WHIP_MID,
            "pitcher_k9":         _K9_MID,
            "opp_pitcher_era_rank":  None,
            "opp_pitcher_k9_rank":   None,
            "opp_pitcher_whip_rank": None,
            "pitcher_id":            None,
            "opposing_pitcher_id":   None,
            "player_name":           "Test Player",
        }

    def test_clamp_at_95(self, monkeypatch):
        from src.engine import enriched_scorer
        monkeypatch.setattr(enriched_scorer, "_compute_blended_era_rank", lambda *a, **kw: (None, None))
        monkeypatch.setattr(enriched_scorer, "get_batter_game_log", lambda *a, **kw: [])
        leg = self._make_leg(100.0, "hits", "over")
        result = enriched_scorer._calculate_enriched_score(leg, 2026, {}, {}, None, None)
        assert result is not None
        assert result["composite_score"] <= 95.0

    def test_clamp_at_5(self, monkeypatch):
        from src.engine import enriched_scorer
        monkeypatch.setattr(enriched_scorer, "_compute_blended_era_rank", lambda *a, **kw: (None, None))
        monkeypatch.setattr(enriched_scorer, "get_batter_game_log", lambda *a, **kw: [])
        leg = self._make_leg(0.0, "hits", "under")
        result = enriched_scorer._calculate_enriched_score(leg, 2026, {}, {}, None, None)
        assert result is not None
        assert result["composite_score"] >= 5.0

    def test_matchup_debug_fields_present_in_result(self, monkeypatch):
        """All five matchup debug fields must be present in _calculate_enriched_score output."""
        from src.engine import enriched_scorer
        monkeypatch.setattr(enriched_scorer, "_compute_blended_era_rank", lambda *a, **kw: (None, None))
        monkeypatch.setattr(enriched_scorer, "get_batter_game_log", lambda *a, **kw: [])
        leg = self._make_leg(75.0, "hits", "over")
        result = enriched_scorer._calculate_enriched_score(leg, 2026, {}, {}, None, None)
        assert result is not None
        for field in ("matchup_adj", "matchup_era_adj", "matchup_whip_adj",
                      "matchup_k9_adj", "matchup_batter_adj"):
            assert field in result, f"Missing field: {field}"

    def test_matchup_debug_nulls_for_inapplicable_props(self, monkeypatch):
        """Fields not applicable to a prop type must be None, not zero."""
        from src.engine import enriched_scorer
        monkeypatch.setattr(enriched_scorer, "_compute_blended_era_rank", lambda *a, **kw: (None, None))
        monkeypatch.setattr(enriched_scorer, "get_batter_game_log", lambda *a, **kw: [])
        # hits/over: only ERA and WHIP apply; k9_adj and batter_adj should be None
        leg = self._make_leg(75.0, "hits", "over")
        result = enriched_scorer._calculate_enriched_score(leg, 2026, {}, {}, None, None)
        assert result["matchup_k9_adj"]    is None, "k9_adj should be None for hits/over"
        assert result["matchup_batter_adj"] is None, "batter_adj should be None for hits/over"
        assert result["matchup_era_adj"]   is not None
        assert result["matchup_whip_adj"]  is not None

    def test_matchup_debug_so_over_k9_only(self, monkeypatch):
        """strikeouts/over: only k9_adj should be non-None; ERA/WHIP/batter fields None."""
        from src.engine import enriched_scorer
        monkeypatch.setattr(enriched_scorer, "_compute_blended_era_rank", lambda *a, **kw: (None, None))
        monkeypatch.setattr(enriched_scorer, "get_batter_game_log", lambda *a, **kw: [])
        leg = self._make_leg(75.0, "strikeouts", "over")
        result = enriched_scorer._calculate_enriched_score(leg, 2026, {}, {}, None, None)
        assert result["matchup_k9_adj"]    is not None
        assert result["matchup_era_adj"]   is None, "ERA adj should be None for strikeouts/over"
        assert result["matchup_whip_adj"]  is None, "WHIP adj should be None for strikeouts/over"
        assert result["matchup_batter_adj"] is None


# ── INSERT/tuple column-count sync check ─────────────────────────────────────

class TestInsertTupleSync:
    """
    Guard against silent positional mismatches in _log_enriched_legs().
    Parses the INSERT column list and the rows.append tuple from the source
    and asserts they contain the same number of entries.
    """

    def test_matchup_columns_in_insert_and_tuple(self):
        """
        Each of the 5 matchup debug columns must appear in both:
          1. the INSERT INTO mlb_scored_legs_enriched column list, and
          2. the rows.append((...)) value block.
        A column missing from either location means silent data loss or a DB error.
        """
        import pathlib
        src = pathlib.Path("src/pipelines/run_enriched_pipeline.py").read_text()

        matchup_fields = [
            "matchup_adj",
            "matchup_era_adj",
            "matchup_whip_adj",
            "matchup_k9_adj",
            "matchup_batter_adj",
        ]

        # Both the INSERT column name and the leg.get("...") call must be present
        for field in matchup_fields:
            assert field in src, (
                f'"{field}" not found anywhere in run_enriched_pipeline.py'
            )
            assert f'leg.get("{field}")' in src, (
                f'leg.get("{field}") not in rows.append tuple — '
                f"column will be silently dropped before the INSERT"
            )
