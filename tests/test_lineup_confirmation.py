"""
tests/test_lineup_confirmation.py

Tests for scratch-handling and dead-link fixes in
src/apis/lineup_confirmation.py (Session 19 rewrite).

Coverage:
  1. Scratch + all other legs >1hr out            → rebuild triggered
  2. Scratch + a surviving leg <1hr out           → reduce path (leg dropped, parlay kept)
  3. Reduce path: 3 survivors remain              → parlay stays pending (_reduce_parlay called)
  4. Reduce path: 2 survivors remain              → parlay voided (SCRATCHED_NO_REBUILD)
  5. Second scratch on already-reduced parlay     → same rule re-applied correctly
  6. Thin-pool rebuild failure                    → superseded_by_batch_id stays NULL
  7. Successful rebuild                           → superseded_by_batch_id set to real batch
"""
import sys
from unittest.mock import MagicMock, patch, call

import pytest

# ── Stub 'main' before any project import that may trigger it ─────────────────
_main_stub = MagicMock()
_main_stub.POOL_MIN_COVERAGE = 65.0
_main_stub.POOL_MIN_ODDS     = -250
_main_stub.POOL_MAX_ODDS     = 150
sys.modules.setdefault("main", _main_stub)

from src.apis.lineup_confirmation import (  # noqa: E402
    run_confirmed_lineup_resolution,
    _void_parlay,
    _void_legs,
    _reduce_parlay,
)


# ── Fixtures / builders ───────────────────────────────────────────────────────

def _leg(leg_id, player_id, player_name, status="LINEUP_CONFIRMED",
         game_id=101, odds=-130, outcome="pending"):
    return {
        "leg_id":               leg_id,
        "player_id":            player_id,
        "player_name":          player_name,
        "lineup_check_status":  status,
        "stat":                 "hits",
        "direction":            "over",
        "game_id":              game_id,
        "odds":                 odds,
        "outcome":              outcome,
    }


# A minimal valid parlay candidate returned by build_parlays (rebuild path)
_REPLACEMENT_LEGS = [
    {
        "player_id": 900, "player_name": "Replacement A", "team": "BOS",
        "stat": "hits", "direction": "over", "best_line": 1.5,
        "best_odds": -120, "composite_score": 73.0, "coverage_pct": 70.0,
        "ev_per_unit": 0.04, "game_pk": 555, "opposing_pitcher_id": 800,
        "opposing_pitcher_name": "Starter X", "lineup_check_status": "LINEUP_CONFIRMED",
        "batting_order": 2,
    }
]
_MOCK_CANDIDATE = {
    "parlay_odds":    "+450",
    "num_legs":       4,
    "avg_composite":  73.0,
    "legs":           _REPLACEMENT_LEGS,
}


def _make_conn(fetchall_return=None, fetchone_return=None):
    """Return a single mock DB connection + cursor."""
    conn = MagicMock()
    cur  = MagicMock()
    conn.cursor.return_value = cur
    cur.fetchall.return_value = fetchall_return if fetchall_return is not None else []
    cur.fetchone.return_value = fetchone_return if fetchone_return is not None else {"id": 9999}
    return conn


def _run(legs, game_seconds, *, pool=None, build_result=None, extra_conn=None):
    """
    Call run_confirmed_lineup_resolution with mocked DB and builder.

    Returns (result_dict, void_parlay_spy, void_legs_spy, reduce_parlay_spy).

    DB call sequence inside the function (non-rebuild tests):
      1. Pool SELECT  → empty
      2. Game seconds → derived from game_seconds arg
      3. Affected parlays → [parlay with legs]

    For rebuild path add extra_conn for the INSERT.
    """
    pool         = pool or []
    build_result = build_result or []

    secs_rows    = [{"game_pk": str(k), "seconds_until_start": v}
                    for k, v in game_seconds.items()]
    parlay_row   = {"id": 1, "rank": 1, "batch_id": "orig_batch", "legs": legs}

    conn_pool    = _make_conn(fetchall_return=pool)
    conn_secs    = _make_conn(fetchall_return=secs_rows)
    conn_parlays = _make_conn(fetchall_return=[parlay_row])

    conns = [conn_pool, conn_secs, conn_parlays]
    if extra_conn is not None:
        conns.append(extra_conn)

    mock_void   = MagicMock()
    mock_vlegs  = MagicMock()
    mock_reduce = MagicMock()

    with patch("src.apis.lineup_confirmation.get_conn", side_effect=conns), \
         patch("src.apis.lineup_confirmation._void_parlay", mock_void),     \
         patch("src.apis.lineup_confirmation._void_legs",   mock_vlegs),    \
         patch("src.apis.lineup_confirmation._reduce_parlay", mock_reduce), \
         patch("src.engine.parlay_builder.build_parlays",
               return_value=build_result),                                   \
         patch("src.utils.sorting.sort_legs_by_game_time",
               side_effect=lambda x: x):
        result = run_confirmed_lineup_resolution("2026-07-10", [1])

    return result, mock_void, mock_vlegs, mock_reduce


# ── Test 1: Scratch + all other legs >1 hr out → rebuild triggered ────────────

def test_scratch_all_games_far_triggers_rebuild():
    """
    When all surviving legs' games are more than 1 hour away, the rebuild path
    is taken (not the reduce path).
    """
    legs = [
        _leg(1, 10, "Scratched Player", status="SCRATCHED", game_id=101),
        _leg(2, 20, "Good Player A",    status="LINEUP_CONFIRMED", game_id=102),
        _leg(3, 30, "Good Player B",    status="LINEUP_CONFIRMED", game_id=103),
        _leg(4, 40, "Good Player C",    status="LINEUP_CONFIRMED", game_id=104),
    ]
    # All games > 1 hour out (7200 seconds)
    game_seconds = {101: 7200.0, 102: 7200.0, 103: 7200.0, 104: 7200.0}

    # Provide a replacement pool large enough to satisfy TOTAL_LEGS (4)
    pool_legs = [
        {
            "player_id": 900 + i, "composite_score": 70.0, "coverage_pct": 68.0,
            "direction": "over", "odds": -130, "stat": "hits",
            "game_start_time": "2026-07-10T20:00:00",
        }
        for i in range(6)
    ]
    conn_insert = _make_conn()  # extra conn for INSERT in rebuild path

    result, mock_void, mock_vlegs, mock_reduce = _run(
        legs, game_seconds,
        pool=pool_legs,
        build_result=[_MOCK_CANDIDATE],
        extra_conn=conn_insert,
    )

    # Rebuild path taken: _void_legs not called (reduce path skipped)
    mock_vlegs.assert_not_called()
    mock_reduce.assert_not_called()
    # The original parlay was voided with a real batch_id
    mock_void.assert_called_once()
    _, kwargs = mock_void.call_args
    assert kwargs.get("batch_id") is not None, "batch_id must be set after a successful rebuild"
    assert result["rebuilt"] == 1
    assert result["kept"] == 0


# ── Test 2: Scratch + a surviving leg <1 hr out → reduce path ─────────────────

def test_scratch_close_game_takes_reduce_path():
    """
    When any surviving leg's game is ≤1 hour away, the reduce path is taken
    (no rebuild is attempted, build_parlays is never called).
    """
    legs = [
        _leg(1, 10, "Scratched Player", status="SCRATCHED",        game_id=101),
        _leg(2, 20, "Good Player A",    status="LINEUP_CONFIRMED",  game_id=102),  # close
        _leg(3, 30, "Good Player B",    status="LINEUP_CONFIRMED",  game_id=103),
        _leg(4, 40, "Good Player C",    status="LINEUP_CONFIRMED",  game_id=104),
        _leg(5, 50, "Good Player D",    status="LINEUP_CONFIRMED",  game_id=105),
    ]
    # game 102 starts in 30 minutes — below the 1-hour threshold
    game_seconds = {101: 7200.0, 102: 1800.0, 103: 7200.0, 104: 7200.0, 105: 7200.0}

    with patch("src.engine.parlay_builder.build_parlays") as mock_build:
        result, mock_void, mock_vlegs, mock_reduce = _run(legs, game_seconds)

    # Reduce path: scratched leg voided, parlay kept (4 survivors)
    mock_vlegs.assert_called_once_with([1])  # leg_id of the scratched leg
    mock_reduce.assert_called_once()
    mock_build.assert_not_called()
    assert result["kept"] == 1
    assert result["rebuilt"] == 0


# ── Test 3: Reduce path — 3 survivors → parlay stays pending ─────────────────

def test_reduce_three_survivors_parlay_kept():
    """
    After dropping the scratched leg, if exactly 3 survivors remain,
    _reduce_parlay is called (parlay stays pending) and _void_parlay is NOT called.
    """
    legs = [
        _leg(1, 10, "Scratched Player", status="SCRATCHED",        game_id=101),
        _leg(2, 20, "Good Player A",    status="LINEUP_CONFIRMED",  game_id=102),  # close
        _leg(3, 30, "Good Player B",    status="LINEUP_CONFIRMED",  game_id=103),
        _leg(4, 40, "Good Player C",    status="LINEUP_CONFIRMED",  game_id=104),
    ]
    # game 102 is close → reduce path
    game_seconds = {101: 7200.0, 102: 500.0, 103: 7200.0, 104: 7200.0}

    result, mock_void, mock_vlegs, mock_reduce = _run(legs, game_seconds)

    # 3 survivors → reduce
    mock_vlegs.assert_called_once_with([1])
    mock_reduce.assert_called_once_with(1, [legs[1], legs[2], legs[3]])
    mock_void.assert_not_called()  # parlay stays alive
    assert result["kept"] == 1


# ── Test 4: Reduce path — 2 survivors → parlay voided ────────────────────────

def test_reduce_two_survivors_parlay_voided():
    """
    After dropping the scratched leg, if only 2 survivors remain,
    the parlay is voided with SCRATCHED_NO_REBUILD and superseded_by_batch_id stays NULL.
    """
    legs = [
        _leg(1, 10, "Scratched Player", status="SCRATCHED",        game_id=101),
        _leg(2, 20, "Good Player A",    status="LINEUP_CONFIRMED",  game_id=102),  # close
        _leg(3, 30, "Good Player B",    status="LINEUP_CONFIRMED",  game_id=103),
    ]
    # game 102 is close → reduce path; only 2 survivors
    game_seconds = {101: 7200.0, 102: 500.0, 103: 7200.0}

    result, mock_void, mock_vlegs, mock_reduce = _run(legs, game_seconds)

    mock_vlegs.assert_called_once_with([1])
    mock_reduce.assert_not_called()
    mock_void.assert_called_once()
    void_args, void_kwargs = mock_void.call_args
    assert void_args[0] == 1                             # parlay_id
    assert "SCRATCHED_NO_REBUILD" in void_args[1]
    assert void_kwargs.get("batch_id") is None           # no replacement parlay inserted
    assert result["voided_no_rebuild"] == 1
    assert result["kept"] == 0


# ── Test 5: Second scratch on already-reduced parlay ─────────────────────────

def test_second_scratch_reapplies_same_rule():
    """
    A parlay that was already reduced (one leg void from a prior scratch) gets
    a second scratch. The rule is re-applied: only non-void, non-scratched legs
    count as survivors. The previously-voided leg is ignored.
    """
    legs = [
        _leg(1, 10, "First Scratched",  status="SCRATCHED", game_id=101, outcome="void"),  # already handled
        _leg(2, 20, "Second Scratched", status="SCRATCHED", game_id=102, outcome="pending"),  # new scratch
        _leg(3, 30, "Good Player A",    status="LINEUP_CONFIRMED",  game_id=103),  # close → reduce
        _leg(4, 40, "Good Player B",    status="LINEUP_CONFIRMED",  game_id=104),
        _leg(5, 50, "Good Player C",    status="LINEUP_CONFIRMED",  game_id=105),
    ]
    # game 103 is close → reduce path
    game_seconds = {101: 7200.0, 102: 7200.0, 103: 900.0, 104: 7200.0, 105: 7200.0}

    result, mock_void, mock_vlegs, mock_reduce = _run(legs, game_seconds)

    # bad_legs = only leg 2 (leg 1 is already outcome='void')
    # surviving_legs = legs 3, 4, 5 (3 survivors) → reduce, keep parlay
    mock_vlegs.assert_called_once_with([2])   # only the new scratched leg
    mock_reduce.assert_called_once()
    survivors = mock_reduce.call_args[0][1]
    survivor_ids = {l["leg_id"] for l in survivors}
    assert survivor_ids == {3, 4, 5}          # leg 1 excluded (void), leg 2 excluded (scratch)
    mock_void.assert_not_called()
    assert result["kept"] == 1


# ── Test 6: Thin-pool failure → superseded_by_batch_id stays NULL ────────────

def test_thin_pool_no_rebuild_leaves_batch_id_null():
    """
    When the replacement pool is too thin to rebuild, _void_parlay is called
    with batch_id=None (superseded_by_batch_id stays NULL) and reason contains
    THIN_POOL_NO_REBUILD.
    """
    legs = [
        _leg(1, 10, "Scratched Player", status="SCRATCHED",        game_id=101),
        _leg(2, 20, "Good Player A",    status="LINEUP_CONFIRMED",  game_id=102),
        _leg(3, 30, "Good Player B",    status="LINEUP_CONFIRMED",  game_id=103),
        _leg(4, 40, "Good Player C",    status="LINEUP_CONFIRMED",  game_id=104),
    ]
    # All games >1hr → rebuild path
    game_seconds = {101: 7200.0, 102: 7200.0, 103: 7200.0, 104: 7200.0}

    # Empty pool → available_pool < TOTAL_LEGS (4)
    result, mock_void, mock_vlegs, mock_reduce = _run(legs, game_seconds, pool=[])

    mock_vlegs.assert_not_called()
    mock_reduce.assert_not_called()
    mock_void.assert_called_once()
    void_args, void_kwargs = mock_void.call_args
    assert void_args[0] == 1
    assert "THIN_POOL_NO_REBUILD" in void_args[1]
    assert void_kwargs.get("batch_id") is None   # no replacement inserted → NULL
    assert result["thin_pool"] == 1
    assert result["rebuilt"] == 0


# ── Test 7: Successful rebuild → superseded_by_batch_id set correctly ─────────

def test_successful_rebuild_sets_batch_id():
    """
    When a replacement parlay is successfully built and inserted,
    _void_parlay is called with the real batch_id (not NULL).
    """
    legs = [
        _leg(1, 10, "Scratched Player", status="SCRATCHED",        game_id=101),
        _leg(2, 20, "Good Player A",    status="LINEUP_CONFIRMED",  game_id=102),
        _leg(3, 30, "Good Player B",    status="LINEUP_CONFIRMED",  game_id=103),
        _leg(4, 40, "Good Player C",    status="LINEUP_CONFIRMED",  game_id=104),
    ]
    # All games >1hr → rebuild path
    game_seconds = {101: 7200.0, 102: 7200.0, 103: 7200.0, 104: 7200.0}

    pool_legs = [
        {
            "player_id": 900 + i, "composite_score": 70.0, "coverage_pct": 68.0,
            "direction": "over", "odds": -130, "stat": "hits",
            "game_start_time": "2026-07-10T20:00:00", "game_pk": 999 + i,
        }
        for i in range(6)
    ]
    conn_insert = _make_conn()  # extra conn for INSERT in rebuild path

    result, mock_void, mock_vlegs, mock_reduce = _run(
        legs, game_seconds,
        pool=pool_legs,
        build_result=[_MOCK_CANDIDATE],
        extra_conn=conn_insert,
    )

    mock_void.assert_called_once()
    void_args, void_kwargs = mock_void.call_args
    assert void_args[0] == 1                             # correct parlay_id
    assert "lineup_resolution" in void_args[1]
    batch_id = void_kwargs.get("batch_id")
    assert batch_id is not None, "batch_id must not be NULL after a real rebuild"
    assert "clr_" in batch_id, f"expected batch_id starting with 'clr_', got {batch_id!r}"
    assert result["rebuilt"] == 1
    assert result["kept"] == 0


# ── Unit tests for _void_parlay ───────────────────────────────────────────────

def _void_parlay_conn():
    """Return a mock conn/cur for _void_parlay calls (2 execute calls, no fetchall)."""
    conn = MagicMock()
    cur  = MagicMock()
    conn.cursor.return_value = cur
    return conn, cur


def test_void_parlay_with_batch_id_sets_superseded():
    """_void_parlay(batch_id=...) passes the batch_id to the UPDATE."""
    conn, cur = _void_parlay_conn()
    with patch("src.apis.lineup_confirmation.get_conn", return_value=conn):
        _void_parlay(42, "lineup_resolution: foo SCRATCHED", batch_id="clr_2026-07-10_1400")

    first_call_args = cur.execute.call_args_list[0][0]
    params = first_call_args[1]          # (batch_id, reason, parlay_id)
    assert params[0] == "clr_2026-07-10_1400"
    assert params[2] == 42


def test_void_parlay_without_batch_id_leaves_null():
    """_void_parlay() without batch_id passes None → superseded_by_batch_id stays NULL."""
    conn, cur = _void_parlay_conn()
    with patch("src.apis.lineup_confirmation.get_conn", return_value=conn):
        _void_parlay(99, "THIN_POOL_NO_REBUILD: some reason")

    first_call_args = cur.execute.call_args_list[0][0]
    params = first_call_args[1]
    assert params[0] is None             # batch_id = NULL
    assert params[2] == 99
