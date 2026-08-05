"""
tests/test_db_point_in_time_2026_08_05.py

Unit tests for the two new point-in-time query helpers added to
src/utils/db.py for the 2026-08-05 leg-scoring redesign:

  - get_batter_point_in_time_totals(): games/total_bases strictly before a date
  - get_starter_rolling_ip(): average IP over a starter's last N starts
    strictly before a date

db.py reads DATABASE_URL from the environment at import time AND unconditionally
calls init_db() at module scope, which opens a real connection during import —
a pre-existing property of this module, not something introduced here. To keep
this test file honest about "no network or DB access" regardless of whatever
DATABASE_URL happens to be set to in the running environment (which could be a
real production connection string on a dev machine), psycopg2.connect is
mocked for the duration of the import so init_db() completes against a fake
connection. Every test below then patches db.get_conn() directly for its own
controlled behavior.
"""
import os
import sys
from unittest.mock import MagicMock, patch

import pytest

os.environ.setdefault("DATABASE_URL", "postgresql://test:test@localhost/test")

# Other test modules in this suite stub sys.modules["src.utils.db"] with a
# MagicMock (to dodge this same init_db()-on-import issue) without any
# teardown, which — depending on collection order — can leave a stub cached
# under "src.utils.db" without "src.utils" itself ever being real-imported,
# breaking `import src.utils.db`. Force a clean, real import regardless of
# what ran before this module.
sys.modules.pop("src.utils.db", None)
sys.modules.pop("src.utils", None)

with patch("psycopg2.connect", return_value=MagicMock()):
    import src.utils.db as db  # noqa: E402


def _mock_conn_returning(row):
    """Build a fake psycopg2 connection whose cursor.fetchone() returns `row`."""
    cur = MagicMock()
    cur.fetchone.return_value = row
    conn = MagicMock()
    conn.cursor.return_value = cur
    return conn, cur


class TestGetBatterPointInTimeTotals:
    def test_returns_games_and_total_bases(self):
        conn, cur = _mock_conn_returning({"games": 12, "total_bases": 24})
        with patch.object(db, "get_conn", return_value=conn):
            result = db.get_batter_point_in_time_totals("12345", "2026-08-05")
        assert result == {"games": 12.0, "total_bases": 24.0}

    def test_query_filters_strictly_before_date(self):
        conn, cur = _mock_conn_returning({"games": 5, "total_bases": 10})
        with patch.object(db, "get_conn", return_value=conn):
            db.get_batter_point_in_time_totals("12345", "2026-08-05")
        sql_text = cur.execute.call_args[0][0]
        params = cur.execute.call_args[0][1]
        assert "game_date < %s" in sql_text
        assert "mlb_player_batting_cumulative" in sql_text
        assert params == (12345, "2026-08-05")

    def test_no_row_returns_none(self):
        conn, cur = _mock_conn_returning(None)
        with patch.object(db, "get_conn", return_value=conn):
            result = db.get_batter_point_in_time_totals("12345", "2026-08-05")
        assert result is None

    def test_zero_games_returns_none(self):
        # Guards against a spurious row with games=0/NULL producing a
        # division-by-zero later when computing pt_tb_rate.
        conn, cur = _mock_conn_returning({"games": 0, "total_bases": 0})
        with patch.object(db, "get_conn", return_value=conn):
            result = db.get_batter_point_in_time_totals("12345", "2026-08-05")
        assert result is None


class TestGetStarterRollingIp:
    def test_returns_average_ip(self):
        conn, cur = _mock_conn_returning({"avg_ip": 5.4})
        with patch.object(db, "get_conn", return_value=conn):
            result = db.get_starter_rolling_ip("456", "2026-08-05")
        assert result == pytest.approx(5.4)

    def test_query_filters_is_starter_and_strictly_before_date(self):
        conn, cur = _mock_conn_returning({"avg_ip": 5.4})
        with patch.object(db, "get_conn", return_value=conn):
            db.get_starter_rolling_ip("456", "2026-08-05", n=5)
        sql_text = cur.execute.call_args[0][0]
        params = cur.execute.call_args[0][1]
        assert "is_starter = true" in sql_text
        assert "g.game_date < %s" in sql_text
        assert "mlb_player_pitching_logs" in sql_text
        assert params == (456, "2026-08-05", 5)

    def test_no_starts_returns_none(self):
        conn, cur = _mock_conn_returning({"avg_ip": None})
        with patch.object(db, "get_conn", return_value=conn):
            result = db.get_starter_rolling_ip("456", "2026-08-05")
        assert result is None
