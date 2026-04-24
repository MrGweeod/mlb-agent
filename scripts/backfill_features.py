#!/usr/bin/env python3
"""
scripts/backfill_features.py — Backfill ML features for mlb_training_data.

Fetches all rows WHERE result IS NOT NULL AND coverage_pct IS NULL,
calculates features using existing pipeline modules, and batch-updates the DB.

Architecture:
  - In-script game log cache: one full-season fetch per player, filtered per row
  - Process rows sorted by game_date to maximise cache hits (same players appear
    multiple times per date → all share one cached log)
  - Batch DB updates: 100 rows per commit (100× faster than row-by-row)
  - Rate limit: 10 API calls/second (conservative, MLB-StatsAPI undocumented)
  - Resumable: WHERE opponent_adjustment IS NULL; re-run safely after crash
    (opponent_adjustment always writes a float ≥ 0 even when fair_line missing,
    so it reliably marks rows as processed even when coverage data is absent)

Usage:
    python scripts/backfill_features.py            # full 66K run
    python scripts/backfill_features.py --limit 100  # test on 100 rows first
"""
from __future__ import annotations

import argparse
import math
import os
import sys
import time
from datetime import datetime

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import psycopg2.extras
import requests
import statsapi

from src.engine.coverage import PROP_STAT_MAP, _count_coverage
from src.pipelines.trend_analysis import get_trend_signal
from src.pipelines.trend_analysis import _process_cache as _trend_cache
from src.utils.db import get_conn

# ── Constants ─────────────────────────────────────────────────────────────────

SEASON = 2026
BASE_URL = "https://statsapi.mlb.com/api/v1"

# Pitcher-only stats — fetch pitching game log instead of hitting log
_PITCHER_STATS = frozenset({"hitsAllowed", "earnedRuns", "inningsPitched"})

# Pitching stat name → MLB-StatsAPI field name in pitching game log splits
_PITCHING_STAT_MAP: dict[str, str] = {
    "strikeouts":    "strikeOuts",
    "hitsAllowed":   "hits",
    "earnedRuns":    "earnedRuns",
    "inningsPitched": "inningsPitched",
}

# Per-prop coverage penalty (mirrors leg_scorer._PROP_COVERAGE_PENALTY)
_PROP_COVERAGE_PENALTY: dict[str, float] = {
    "strikeouts":  1.00,
    "hits":        0.85,
    "totalBases":  0.78,
    "rbi":         0.90,
    "walks":       0.85,
    "homeRuns":    0.85,
    "runsScored":  0.90,
    "stolenBases": 0.90,
}

_PA_FULL = 4.0  # 4+ AB/game → PA stability factor = 1.0

# ── In-script game log cache ──────────────────────────────────────────────────
# Full-season logs cached per player. Filtered locally per game_date.
# One fetch per player across the entire run → 99%+ API call reduction.

_batter_log_cache: dict[int, list] = {}    # mlb_id → full season hitting log
_pitcher_log_cache: dict[int, list] = {}   # mlb_id → full season pitching log

# Player name → MLB person ID cache (looked up once per unique name)
_name_to_mlb_id: dict[str, int | None] = {}  # player_name → MLB int ID or None

# ── Rate limiting ─────────────────────────────────────────────────────────────

_api_calls_in_window = 0
_api_window_start = time.time()
_total_api_calls = 0


def _rate_limit() -> None:
    """Enforce max 10 API calls per second (conservative MLB-StatsAPI limit)."""
    global _api_calls_in_window, _api_window_start, _total_api_calls
    _total_api_calls += 1
    _api_calls_in_window += 1
    if _api_calls_in_window >= 10:
        elapsed = time.time() - _api_window_start
        if elapsed < 1.0:
            time.sleep(1.0 - elapsed)
        _api_calls_in_window = 0
        _api_window_start = time.time()


# ── Player name → MLB person ID resolution ────────────────────────────────────

def _resolve_mlb_id(player_name: str) -> int | None:
    """
    Resolve a player display name to an MLB person ID via statsapi.lookup_player.

    mlb_training_data stores SGO player IDs (e.g. 'CARLOS_CORREA_1_MLB'), not
    numeric MLB person IDs. We derive the MLB ID from the player_name field
    (which is the official full name from SGO's marketName) using MLB search.

    Result is cached in _name_to_mlb_id for the script lifetime (one call per
    unique name). Returns None when not found or on API error.
    """
    if player_name in _name_to_mlb_id:
        return _name_to_mlb_id[player_name]

    _rate_limit()
    try:
        results = statsapi.lookup_player(player_name, season=SEASON, sportId=1)
        if results:
            # First result is usually the best match; use it directly
            mlb_id = int(results[0]["id"])
            _name_to_mlb_id[player_name] = mlb_id
            return mlb_id
        _name_to_mlb_id[player_name] = None
        return None
    except Exception as e:
        print(f"  [WARNING] MLB ID lookup failed for '{player_name}': {e}")
        _name_to_mlb_id[player_name] = None
        return None


# ── Game log fetchers ─────────────────────────────────────────────────────────

def _fetch_hitting_log(player_id: int) -> list:
    """Fetch full-season hitting game log with in-script caching."""
    if player_id in _batter_log_cache:
        return _batter_log_cache[player_id]

    _rate_limit()
    try:
        r = requests.get(
            f"{BASE_URL}/people/{player_id}/stats",
            params={"stats": "gameLog", "group": "hitting", "season": str(SEASON)},
            timeout=15,
        )
        r.raise_for_status()
        splits = r.json().get("stats", [{}])[0].get("splits", [])
    except Exception as e:
        print(f"  [WARNING] Failed to fetch hitting log for player {player_id}: {e}")
        splits = []

    _batter_log_cache[player_id] = splits
    return splits


def _fetch_pitching_log(player_id: int) -> list:
    """Fetch full-season pitching game log with in-script caching."""
    if player_id in _pitcher_log_cache:
        return _pitcher_log_cache[player_id]

    _rate_limit()
    try:
        r = requests.get(
            f"{BASE_URL}/people/{player_id}/stats",
            params={"stats": "gameLog", "group": "pitching", "season": str(SEASON)},
            timeout=15,
        )
        r.raise_for_status()
        splits = r.json().get("stats", [{}])[0].get("splits", [])
    except Exception as e:
        print(f"  [WARNING] Failed to fetch pitching log for player {player_id}: {e}")
        splits = []

    _pitcher_log_cache[player_id] = splits
    return splits


def _filter_before(game_logs: list, game_date_str: str) -> list:
    """
    Return only game log entries with date strictly before game_date_str.

    MLB-StatsAPI game log entries have a top-level 'date' field ('YYYY-MM-DD').
    For a prop on April 15, we want logs through April 14 so today's game
    is not included in the historical sample.

    game_date_str must be an ISO string ('YYYY-MM-DD'); DB rows are converted
    upstream with str(row['game_date']) since psycopg2 returns datetime.date.
    """
    return [g for g in game_logs if g.get("date", "") < game_date_str]


# ── Feature calculators ───────────────────────────────────────────────────────

def _is_pitcher_prop(stat: str, odd_id: str) -> bool:
    """Infer whether this is a pitcher prop from stat name and odd_id."""
    if stat in _PITCHER_STATS:
        return True
    # Strikeouts: SGO odd_id contains 'pitching_strikeouts' for pitcher K props
    if stat == "strikeouts" and "pitching" in (odd_id or "").lower():
        return True
    return False


def _calc_coverage_pct(
    game_logs: list,
    stat: str,
    line: float,
    is_pitcher: bool,
) -> float | None:
    """
    Calculate coverage percentage from filtered game logs.

    Returns float in [0, 100] or None when fewer than 5 games are available.
    Uses exact hit rate (games >= line / total games).
    """
    if is_pitcher:
        stat_field = _PITCHING_STAT_MAP.get(stat)
    else:
        stat_field = PROP_STAT_MAP.get(stat)

    if not stat_field:
        return None

    over, total = _count_coverage(game_logs, stat_field, line)
    if total < 5:
        return None
    return round((over / total) * 100.0, 2)


def _calc_opponent_adjustment(fair_line: float | None, line: float) -> float:
    """
    Approximate opponent adjustment from fair_line as matchup quality proxy.

    fair_line > line  → market expects player to exceed line → favorable matchup
    fair_line < line  → market expects player to fall short → unfavorable matchup

    Uses tanh to normalise to [-1, 1]:
      0.5 unit difference → tanh(1.0) ≈ 0.76
      1.0 unit difference → tanh(2.0) ≈ 0.96

    Returns 0.0 when fair_line is not available.
    """
    if fair_line is None or fair_line <= 0 or line <= 0:
        return 0.0
    line_diff = fair_line - line
    return round(math.tanh(line_diff / 0.5), 4)


def _calc_composite_score(
    stat: str,
    coverage_pct: float | None,
    opponent_adjustment: float,
    pa_avg_10: float,
) -> float | None:
    """
    Composite score formula from leg_scorer.score_leg() (swing profile).

    Weights: coverage 70%, opponent 20%, PA stability 10%.
    EV and trend are both 0% (per April 2026 emergency recalibration).

    Returns float in [0, 100] or None when coverage_pct is unavailable.
    """
    if coverage_pct is None:
        return None

    prop_mult = _PROP_COVERAGE_PENALTY.get(stat, 0.85)
    f_coverage = min(coverage_pct / 100.0, 1.0) * prop_mult
    f_opponent = (opponent_adjustment + 1.0) / 2.0       # maps [-1,1] → [0,1]
    f_pa = min(pa_avg_10 / _PA_FULL, 1.0)                # maps [0, 4+] → [0,1]

    composite = (f_coverage * 0.70 + f_opponent * 0.20 + f_pa * 0.10) * 100.0
    return round(composite, 2)


def _calculate_features(row: dict) -> dict:
    """
    Calculate all ML features for a single training data row.

    Returns a dict with keys: coverage_pct, trend_score, opponent_adjustment,
    pa_last_10, composite_score. Values may be None on failure.

    player_id in mlb_training_data is an SGO string ID (e.g. 'CARLOS_CORREA_1_MLB'),
    NOT a numeric MLB person ID. We resolve the MLB ID via player_name lookup.
    """
    features: dict = {
        "coverage_pct":        None,
        "trend_score":         None,
        "opponent_adjustment": None,
        "pa_last_10":          None,
        "composite_score":     None,
    }

    player_name = row.get("player_name", "")
    stat        = row.get("stat", "")
    line        = float(row.get("line") or 0)
    odd_id      = row.get("odd_id", "")
    game_date   = str(row.get("game_date", ""))  # psycopg2 returns datetime.date
    fair_line   = row.get("fair_line")

    if not player_name or not stat or not game_date:
        return features

    # Resolve player name → MLB person ID (cached after first lookup)
    mlb_id = _resolve_mlb_id(player_name)
    if mlb_id is None:
        return features

    is_pitcher = _is_pitcher_prop(stat, odd_id)

    # ── Fetch + filter game logs ───────────────────────────────────────────────
    try:
        if is_pitcher:
            full_log = _fetch_pitching_log(mlb_id)
        else:
            full_log = _fetch_hitting_log(mlb_id)
        filtered_log = _filter_before(full_log, game_date)
    except Exception as e:
        print(f"  [WARNING] Game log error for {player_name} ({mlb_id}): {e}")
        return features

    # ── Coverage ──────────────────────────────────────────────────────────────
    try:
        features["coverage_pct"] = _calc_coverage_pct(filtered_log, stat, line, is_pitcher)
    except Exception as e:
        print(f"  [WARNING] Coverage failed for {player_name} {stat}: {e}")

    # ── Trend signal (batter props only) ──────────────────────────────────────
    pa_avg_10 = 0.0
    if not is_pitcher:
        try:
            trend = get_trend_signal(str(mlb_id), stat, filtered_log, line)
            features["trend_score"] = trend.get("trend_score", 0.0)
            pa_avg_10 = float(trend.get("pa_avg_10") or 0.0)
            features["pa_last_10"] = pa_avg_10
        except Exception as e:
            print(f"  [WARNING] Trend failed for {player_name} {stat}: {e}")

    # ── Opponent adjustment ───────────────────────────────────────────────────
    try:
        opp_adj = _calc_opponent_adjustment(fair_line, line)
        features["opponent_adjustment"] = opp_adj
    except Exception as e:
        print(f"  [WARNING] Opponent adj failed for {player_name}: {e}")
        opp_adj = 0.0

    # ── Composite score ───────────────────────────────────────────────────────
    try:
        features["composite_score"] = _calc_composite_score(
            stat, features["coverage_pct"], opp_adj, pa_avg_10
        )
    except Exception as e:
        print(f"  [WARNING] Composite score failed for {player_name}: {e}")

    return features


# ── Database helpers ──────────────────────────────────────────────────────────

_UPDATE_SQL = """
    UPDATE mlb_training_data
    SET coverage_pct        = %s,
        trend_score         = %s,
        opponent_adjustment = %s,
        pa_last_10          = %s,
        composite_score     = %s
    WHERE id = %s
"""


def _ensure_columns(conn) -> None:
    """Add composite_score column if it does not yet exist."""
    cur = conn.cursor()
    try:
        cur.execute(
            "ALTER TABLE mlb_training_data ADD COLUMN IF NOT EXISTS composite_score REAL"
        )
        cur.execute(
            "ALTER TABLE mlb_training_data ADD COLUMN IF NOT EXISTS pa_last_10 REAL"
        )
        conn.commit()
    except Exception as e:
        conn.rollback()
        print(f"  [WARNING] Could not add columns: {e}")
    finally:
        cur.close()


def _flush_batch(conn, batch: list) -> bool:
    """Write a batch of (features..., id) tuples to the DB. Returns True on success."""
    if not batch:
        return True
    try:
        cur = conn.cursor()
        psycopg2.extras.execute_batch(cur, _UPDATE_SQL, batch)
        conn.commit()
        cur.close()
        return True
    except Exception as e:
        print(f"  [ERROR] DB batch update failed: {e}")
        try:
            conn.rollback()
        except Exception:
            pass
        return False


# ── Main ──────────────────────────────────────────────────────────────────────

def main() -> None:
    parser = argparse.ArgumentParser(
        description="Backfill ML features for mlb_training_data."
    )
    parser.add_argument(
        "--limit", type=int, default=None,
        help="Limit rows for testing (e.g. --limit 100)",
    )
    args = parser.parse_args()

    run_start = time.time()

    print("MLB Training Data Feature Backfill")
    print("===================================")

    conn = get_conn()
    _ensure_columns(conn)

    # ── Fetch unprocessed rows ────────────────────────────────────────────────
    print("Fetching unprocessed rows...")
    cur = conn.cursor()
    query = """
        SELECT id, player_id, player_name, stat, direction, line,
               fair_line, odd_id, game_date
        FROM mlb_training_data
        WHERE result IS NOT NULL AND opponent_adjustment IS NULL
        ORDER BY game_date, id
    """
    if args.limit:
        query += f" LIMIT {args.limit}"
    cur.execute(query)
    all_rows = [dict(r) for r in cur.fetchall()]
    cur.close()

    total_rows = len(all_rows)
    if args.limit:
        print(f"TEST MODE: Processing only {args.limit} rows")
    print(f"Found {total_rows:,} rows to process\n")

    if total_rows == 0:
        print("Nothing to process — all rows already have features. Exiting.")
        conn.close()
        return

    # ── Process rows ──────────────────────────────────────────────────────────
    print("Processing by game_date...")

    processed      = 0
    batch: list    = []
    current_date   = None
    date_count     = 0
    date_start_idx = 0

    for i, row in enumerate(all_rows):
        game_date = str(row.get("game_date", ""))  # psycopg2 returns datetime.date

        # Date boundary — report date count and clear trend cache
        if game_date != current_date:
            if current_date is not None:
                print(f"  {current_date}: {date_count} props")
                _trend_cache.clear()  # avoid stale cache across dates
            current_date   = game_date
            date_count     = 0
            date_start_idx = i

        date_count += 1

        # ── Calculate features ────────────────────────────────────────────────
        try:
            features = _calculate_features(row)
        except Exception as e:
            print(f"  [ERROR] Unexpected failure on row {row['id']}: {e}")
            features = {
                "coverage_pct": None, "trend_score": None,
                "opponent_adjustment": None, "pa_last_10": None,
                "composite_score": None,
            }

        batch.append((
            features["coverage_pct"],
            features["trend_score"],
            features["opponent_adjustment"],
            features["pa_last_10"],
            features["composite_score"],
            row["id"],
        ))
        processed += 1

        # ── Flush every 100 rows ──────────────────────────────────────────────
        if len(batch) >= 100:
            _flush_batch(conn, batch)
            batch = []

        # ── Progress report every 500 rows ────────────────────────────────────
        if processed % 500 == 0:
            cache_size = len(_batter_log_cache) + len(_pitcher_log_cache)
            elapsed    = time.time() - run_start
            rate       = processed / elapsed if elapsed > 0 else 1.0
            remaining  = (total_rows - processed) / rate
            pct        = processed / total_rows * 100
            print(f"\nProgress: {processed:,}/{total_rows:,} ({pct:.1f}%)")
            print(f"  Cache size : {cache_size} players")
            print(f"  API calls  : {_total_api_calls}")
            print(f"  Est. remaining: {remaining / 60:.1f} minutes")

    # Print last date
    if current_date:
        print(f"  {current_date}: {date_count} props")

    # Flush final partial batch
    _flush_batch(conn, batch)

    conn.close()

    # ── Final summary ─────────────────────────────────────────────────────────
    elapsed     = time.time() - run_start
    elapsed_min = int(elapsed // 60)
    elapsed_sec = int(elapsed % 60)
    total_cache = len(_batter_log_cache) + len(_pitcher_log_cache)
    hit_rate    = (1 - total_cache / max(processed, 1)) * 100 if processed else 0

    print(f"\nBACKFILL COMPLETE")
    print(f"=================")
    print(f"Total rows processed : {processed:,}")
    print(f"Total API calls      : {_total_api_calls}")
    print(f"Total time           : {elapsed_min}m {elapsed_sec}s")
    print(f"Cache hit rate       : {hit_rate:.1f}%")

    # Verification query hint
    print(f"\nVerify with:")
    print(f"  SELECT COUNT(*), AVG(composite_score), AVG(coverage_pct)")
    print(f"  FROM mlb_training_data WHERE result IS NOT NULL AND opponent_adjustment IS NOT NULL;")


if __name__ == "__main__":
    main()
