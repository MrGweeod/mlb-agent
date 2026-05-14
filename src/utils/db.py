import json
import os
import time
from datetime import datetime, timezone

import psycopg2
import psycopg2.extras
from dotenv import load_dotenv

load_dotenv()

DATABASE_URL = os.environ["DATABASE_URL"].removeprefix("DATABASE_URL=")


def get_conn():
    """Return a psycopg2 connection with RealDictCursor as the default cursor factory.

    Retries up to 3 times on OperationalError (e.g. transient SSL drops from
    Supabase) with a 2-second sleep between attempts. Re-raises on final failure.
    """
    last_err = None
    for attempt in range(1, 4):
        try:
            return psycopg2.connect(DATABASE_URL, cursor_factory=psycopg2.extras.RealDictCursor)
        except psycopg2.OperationalError as e:
            last_err = e
            if attempt < 3:
                print(f"  [db] connection attempt {attempt} failed, retrying in 2s ({e})")
                time.sleep(2)
    raise last_err


def init_db():
    conn = get_conn()
    cur = conn.cursor()

    cur.execute("""
        CREATE TABLE IF NOT EXISTS mlb_player_game_logs (
            player_id TEXT PRIMARY KEY,
            games_json TEXT NOT NULL,
            fetched_at TEXT NOT NULL
        )
    """)

    cur.execute("""
        CREATE TABLE IF NOT EXISTS mlb_player_positions (
            player_id TEXT PRIMARY KEY,
            position TEXT NOT NULL,
            bats TEXT,
            throws TEXT,
            fetched_at TEXT NOT NULL
        )
    """)

    cur.execute("""
        CREATE TABLE IF NOT EXISTS mlb_player_props_cache (
            cache_key TEXT PRIMARY KEY,
            props_json TEXT NOT NULL,
            fetched_at TEXT NOT NULL
        )
    """)

    cur.execute("""
        CREATE TABLE IF NOT EXISTS mlb_qualifying_legs_cache (
            cache_key TEXT PRIMARY KEY,
            legs_json TEXT NOT NULL,
            fetched_at TEXT NOT NULL
        )
    """)

    cur.execute("""
        CREATE TABLE IF NOT EXISTS mlb_bayes_scores_cache (
            cache_key TEXT PRIMARY KEY,
            p_over REAL NOT NULL,
            predicted_mean REAL NOT NULL,
            predicted_std REAL NOT NULL,
            n_trained INTEGER NOT NULL,
            fetched_at TEXT NOT NULL
        )
    """)

    cur.execute("""
        CREATE TABLE IF NOT EXISTS mlb_injury_cache (
            player_name TEXT NOT NULL,
            date TEXT NOT NULL,
            status TEXT NOT NULL,
            fetched_at TEXT NOT NULL,
            PRIMARY KEY (player_name, date)
        )
    """)

    cur.execute("""
        CREATE TABLE IF NOT EXISTS mlb_recommendations (
            id SERIAL PRIMARY KEY,
            date TEXT NOT NULL,
            parlay_odds TEXT,
            num_legs INTEGER,
            avg_coverage REAL,
            avg_ev REAL,
            parlay_type TEXT,
            status TEXT DEFAULT 'pending',
            created_at TEXT NOT NULL
        )
    """)

    cur.execute("""
        CREATE TABLE IF NOT EXISTS mlb_recommendation_legs (
            id SERIAL PRIMARY KEY,
            recommendation_id INTEGER NOT NULL,
            player_name TEXT NOT NULL,
            stat TEXT NOT NULL,
            line REAL NOT NULL,
            odds TEXT,
            coverage_pct REAL,
            p_over REAL,
            ev_per_unit REAL,
            predicted_mean REAL,
            predicted_std REAL,
            direction TEXT DEFAULT 'over',
            result TEXT DEFAULT 'pending',
            actual_value REAL,
            team TEXT,
            pitcher_id TEXT,
            prop_category TEXT,
            FOREIGN KEY (recommendation_id) REFERENCES mlb_recommendations(id)
        )
    """)

    cur.execute("""
        CREATE TABLE IF NOT EXISTS mlb_parlays (
            id SERIAL PRIMARY KEY,
            date TEXT NOT NULL,
            recommendation_id INTEGER REFERENCES mlb_recommendations(id),
            agent_odds TEXT,
            final_odds TEXT,
            stake REAL,
            status TEXT DEFAULT 'pending',
            payout REAL,
            notes TEXT,
            created_at TEXT
        )
    """)

    cur.execute("""
        CREATE TABLE IF NOT EXISTS mlb_parlay_legs (
            id SERIAL PRIMARY KEY,
            parlay_id INTEGER NOT NULL,
            player_name TEXT,
            stat TEXT,
            line REAL,
            odds TEXT,
            coverage_pct REAL,
            result TEXT DEFAULT 'pending',
            prop_category TEXT,
            pitcher_id TEXT,
            batter_hand TEXT,
            FOREIGN KEY (parlay_id) REFERENCES mlb_parlays(id)
        )
    """)

    cur.execute("""
        CREATE TABLE IF NOT EXISTS mlb_llm_analysis_cache (
            date TEXT PRIMARY KEY,
            analysis_text TEXT NOT NULL,
            created_at TEXT NOT NULL
        )
    """)

    cur.execute("""
        CREATE TABLE IF NOT EXISTS mlb_sgo_request_log (
            id SERIAL PRIMARY KEY,
            timestamp TEXT NOT NULL,
            endpoint TEXT NOT NULL,
            http_status INTEGER NOT NULL,
            entities_consumed INTEGER NOT NULL DEFAULT 0,
            notes TEXT
        )
    """)

    cur.execute("""
        CREATE TABLE IF NOT EXISTS mlb_matchup_sensitivity_cache (
            cache_key TEXT PRIMARY KEY,
            k REAL NOT NULL,
            n_games INTEGER NOT NULL,
            fetched_at TEXT NOT NULL
        )
    """)

    cur.execute("""
        CREATE TABLE IF NOT EXISTS mlb_opponent_defense_cache (
            season TEXT NOT NULL,
            data_type TEXT NOT NULL,
            payload TEXT NOT NULL,
            fetched_at TEXT NOT NULL,
            PRIMARY KEY (season, data_type)
        )
    """)

    cur.execute("""
        CREATE TABLE IF NOT EXISTS mlb_scored_legs (
            id SERIAL PRIMARY KEY,
            run_date TEXT NOT NULL,
            player_name TEXT,
            team TEXT,
            opponent TEXT,
            stat TEXT,
            line REAL,
            direction TEXT,
            odds TEXT,
            coverage_pct REAL,
            p_over REAL,
            ev_per_unit REAL,
            trend_pass BOOLEAN,
            trend_score REAL,
            opponent_adjustment REAL,
            position TEXT,
            in_parlay BOOLEAN NOT NULL DEFAULT FALSE,
            result TEXT DEFAULT NULL,
            actual_value REAL DEFAULT NULL,
            prop_category TEXT,
            pitcher_era_rank INTEGER,
            batter_vs_hand_coverage REAL,
            game_pk INTEGER,
            player_id TEXT,
            opposing_pitcher_id TEXT,
            lineup_confirmed BOOLEAN NOT NULL DEFAULT FALSE,
            last_updated TEXT,
            logged_at TEXT NOT NULL,
            odd_id TEXT,
            game_start_time TEXT,
            pitcher_hand TEXT,
            composite_score REAL,
            coverage_overall REAL,
            coverage_vs_hand REAL,
            coverage_recent_10 REAL,
            coverage_recent_5 REAL,
            pitcher_id TEXT,
            pitcher_name TEXT,
            pitcher_team TEXT,
            pitcher_era REAL,
            pitcher_k9 REAL,
            pitcher_whip REAL,
            batter_hand TEXT,
            pitcher_vs_batter_hand_era REAL,
            UNIQUE (run_date, odd_id)
        )
    """)

    cur.execute("""
        CREATE TABLE IF NOT EXISTS pitcher_profiles (
            pitcher_id TEXT PRIMARY KEY,
            pitcher_name TEXT,
            team_id TEXT,
            era REAL,
            era_rank INTEGER,
            k9 REAL,
            k9_rank INTEGER,
            whip REAL,
            whip_rank INTEGER,
            hand TEXT,
            vs_rhb_era REAL,
            vs_lhb_era REAL,
            vs_rhb_k9 REAL,
            vs_lhb_k9 REAL,
            last_updated TEXT NOT NULL
        )
    """)

    conn.commit()
    cur.close()
    conn.close()


def now_utc():
    return datetime.now(timezone.utc).isoformat()


def hours_since(iso_str):
    then = datetime.fromisoformat(iso_str)
    if then.tzinfo is None:
        then = then.replace(tzinfo=timezone.utc)
    return (datetime.now(timezone.utc) - then).total_seconds() / 3600


def get_player_log(player_id, max_age_hours=24):
    conn = get_conn()
    cur = conn.cursor()
    cur.execute(
        "SELECT games_json, fetched_at FROM mlb_player_game_logs WHERE player_id = %s",
        (player_id,)
    )
    row = cur.fetchone()
    cur.close()
    conn.close()
    if row and hours_since(row["fetched_at"]) < max_age_hours:
        return json.loads(row["games_json"])
    return None


def set_player_log(player_id, games):
    conn = get_conn()
    cur = conn.cursor()
    cur.execute(
        """
        INSERT INTO mlb_player_game_logs (player_id, games_json, fetched_at)
        VALUES (%s, %s, %s)
        ON CONFLICT (player_id) DO UPDATE
            SET games_json = EXCLUDED.games_json,
                fetched_at = EXCLUDED.fetched_at
        """,
        (player_id, json.dumps(games), now_utc())
    )
    conn.commit()
    cur.close()
    conn.close()


def get_player_position(player_id: str, max_age_hours: int = 168) -> dict | None:
    """Return {"position": ..., "bats": ...} for a player, or None if missing/expired (TTL 7 days)."""
    conn = get_conn()
    cur = conn.cursor()
    cur.execute(
        "SELECT position, bats, fetched_at FROM mlb_player_positions WHERE player_id = %s",
        (player_id,)
    )
    row = cur.fetchone()
    cur.close()
    conn.close()
    if row and hours_since(row["fetched_at"]) < max_age_hours:
        return {"position": row["position"], "bats": row["bats"]}
    return None


def get_player_handedness(player_id: str, max_age_hours: int = 168) -> str | None:
    """Return bats value ('L', 'R', or 'S') for a player, or None if missing/expired (TTL 7 days)."""
    conn = get_conn()
    cur = conn.cursor()
    cur.execute(
        "SELECT bats, fetched_at FROM mlb_player_positions WHERE player_id = %s",
        (player_id,)
    )
    row = cur.fetchone()
    cur.close()
    conn.close()
    if row and hours_since(row["fetched_at"]) < max_age_hours:
        return row["bats"]
    return None


def set_player_position(player_id: str, position: str, bats: str = None):
    """Write or update a player's position in the cache."""
    conn = get_conn()
    cur = conn.cursor()
    cur.execute(
        """
        INSERT INTO mlb_player_positions (player_id, position, bats, fetched_at)
        VALUES (%s, %s, %s, %s)
        ON CONFLICT (player_id) DO UPDATE
            SET position = EXCLUDED.position,
                bats = EXCLUDED.bats,
                fetched_at = EXCLUDED.fetched_at
        """,
        (player_id, position, bats, now_utc())
    )
    conn.commit()
    cur.close()
    conn.close()


def get_props_cache(date, game_id, max_age_hours=6):
    """
    Return cached props for a given date and game ID, or None if stale/missing.

    Args:
        date: ISO date string (YYYY-MM-DD).
        game_id: Event ID or team-pair key (e.g. 'ATL@NYM') used at write time.
        max_age_hours: Cache TTL in hours. Use 6 for Odds API standard lines
                       (want reasonably fresh prices) and 24 for SGO alt-line
                       lookups (valid all day — alt-line ladders don't change).
    """
    key = f"{date}_{game_id}"
    conn = get_conn()
    cur = conn.cursor()
    cur.execute(
        "SELECT props_json, fetched_at FROM mlb_player_props_cache WHERE cache_key = %s",
        (key,)
    )
    row = cur.fetchone()
    cur.close()
    conn.close()
    if row and hours_since(row["fetched_at"]) < max_age_hours:
        return json.loads(row["props_json"])
    return None


def set_props_cache(date, game_id, props):
    key = f"{date}_{game_id}"
    conn = get_conn()
    cur = conn.cursor()
    cur.execute(
        """
        INSERT INTO mlb_player_props_cache (cache_key, props_json, fetched_at)
        VALUES (%s, %s, %s)
        ON CONFLICT (cache_key) DO UPDATE
            SET props_json = EXCLUDED.props_json,
                fetched_at = EXCLUDED.fetched_at
        """,
        (key, json.dumps(props), now_utc())
    )
    conn.commit()
    cur.close()
    conn.close()


def get_legs_cache(date):
    conn = get_conn()
    cur = conn.cursor()
    cur.execute(
        "SELECT legs_json, fetched_at FROM mlb_qualifying_legs_cache WHERE cache_key = %s",
        (date,)
    )
    row = cur.fetchone()
    cur.close()
    conn.close()
    if row and hours_since(row["fetched_at"]) < 6:
        return json.loads(row["legs_json"])
    return None


def set_legs_cache(date, legs):
    conn = get_conn()
    cur = conn.cursor()
    cur.execute(
        """
        INSERT INTO mlb_qualifying_legs_cache (cache_key, legs_json, fetched_at)
        VALUES (%s, %s, %s)
        ON CONFLICT (cache_key) DO UPDATE
            SET legs_json = EXCLUDED.legs_json,
                fetched_at = EXCLUDED.fetched_at
        """,
        (date, json.dumps(legs), now_utc())
    )
    conn.commit()
    cur.close()
    conn.close()


def _bayes_key(player_id: str, stat: str, line: float, date: str) -> str:
    return f"{date}|{player_id}|{stat}|{line}"


def get_bayes_score(player_id: str, stat: str, line: float, date: str):
    """Returns cached (p_over, mean, std, n_trained) for today or None."""
    key = _bayes_key(player_id, stat, line, date)
    conn = get_conn()
    cur = conn.cursor()
    cur.execute(
        "SELECT p_over, predicted_mean, predicted_std, n_trained FROM mlb_bayes_scores_cache WHERE cache_key = %s",
        (key,)
    )
    row = cur.fetchone()
    cur.close()
    conn.close()
    if row:
        return row["p_over"], row["predicted_mean"], row["predicted_std"], row["n_trained"]
    return None


def set_bayes_score(player_id: str, stat: str, line: float, date: str,
                    p_over: float, mean: float, std: float, n_trained: int):
    key = _bayes_key(player_id, stat, line, date)
    conn = get_conn()
    cur = conn.cursor()
    cur.execute(
        """
        INSERT INTO mlb_bayes_scores_cache (cache_key, p_over, predicted_mean, predicted_std, n_trained, fetched_at)
        VALUES (%s, %s, %s, %s, %s, %s)
        ON CONFLICT (cache_key) DO UPDATE
            SET p_over = EXCLUDED.p_over,
                predicted_mean = EXCLUDED.predicted_mean,
                predicted_std = EXCLUDED.predicted_std,
                n_trained = EXCLUDED.n_trained,
                fetched_at = EXCLUDED.fetched_at
        """,
        (key, p_over, mean, std, n_trained, now_utc())
    )
    conn.commit()
    cur.close()
    conn.close()


def get_injury_status(player_name: str, date: str) -> str | None:
    """Returns 'out' or 'clear' if cached for today, else None."""
    conn = get_conn()
    cur = conn.cursor()
    cur.execute(
        "SELECT status FROM mlb_injury_cache WHERE player_name = %s AND date = %s",
        (player_name, date)
    )
    row = cur.fetchone()
    cur.close()
    conn.close()
    return row["status"] if row else None


def set_injury_status(player_name: str, date: str, status: str):
    """Cache a player's injury/IL status ('out' or 'clear') for today."""
    conn = get_conn()
    cur = conn.cursor()
    cur.execute(
        """
        INSERT INTO mlb_injury_cache (player_name, date, status, fetched_at)
        VALUES (%s, %s, %s, %s)
        ON CONFLICT (player_name, date) DO UPDATE
            SET status = EXCLUDED.status,
                fetched_at = EXCLUDED.fetched_at
        """,
        (player_name, date, status, now_utc())
    )
    conn.commit()
    cur.close()
    conn.close()


def get_analysis_cache(date: str) -> str | None:
    """Return cached Claude analysis text for today, or None if not cached."""
    conn = get_conn()
    cur = conn.cursor()
    cur.execute(
        "SELECT analysis_text FROM mlb_llm_analysis_cache WHERE date = %s",
        (date,)
    )
    row = cur.fetchone()
    cur.close()
    conn.close()
    return row["analysis_text"] if row else None


def set_analysis_cache(date: str, analysis_text: str):
    """Cache Claude analysis text for today."""
    conn = get_conn()
    cur = conn.cursor()
    cur.execute(
        """
        INSERT INTO mlb_llm_analysis_cache (date, analysis_text, created_at)
        VALUES (%s, %s, %s)
        ON CONFLICT (date) DO UPDATE
            SET analysis_text = EXCLUDED.analysis_text,
                created_at = EXCLUDED.created_at
        """,
        (date, analysis_text, now_utc())
    )
    conn.commit()
    cur.close()
    conn.close()


def log_sgo_request(endpoint: str, http_status: int, entities_consumed: int, notes: str = ""):
    """
    Persist one SGO API call to mlb_sgo_request_log for quota tracking.

    Called by sportsgameodds._sgo_get() after every request (success or failure).
    Does not raise on error — logging failures are non-fatal.

    Args:
        endpoint: API path called (e.g. '/events').
        http_status: HTTP response status code.
        entities_consumed: Number of objects returned (len of data array).
        notes: Optional context string (e.g. 'quota_exhausted', 'rate_limited').
    """
    try:
        conn = get_conn()
        cur = conn.cursor()
        cur.execute(
            """
            INSERT INTO mlb_sgo_request_log (timestamp, endpoint, http_status, entities_consumed, notes)
            VALUES (%s, %s, %s, %s, %s)
            """,
            (now_utc(), endpoint, http_status, entities_consumed, notes)
        )
        conn.commit()
        cur.close()
        conn.close()
    except Exception:
        pass  # logging failures must never break the pipeline


def get_sensitivity_cache(player_id: str, stat_type: str, max_age_hours: int = 24) -> float | None:
    """Return cached sensitivity k for (player_id, stat_type), or None if stale/missing."""
    key = f"{player_id}|{stat_type}"
    conn = get_conn()
    cur = conn.cursor()
    cur.execute(
        "SELECT k, fetched_at FROM mlb_matchup_sensitivity_cache WHERE cache_key = %s",
        (key,)
    )
    row = cur.fetchone()
    cur.close()
    conn.close()
    if row and hours_since(row["fetched_at"]) < max_age_hours:
        return float(row["k"])
    return None


def load_all_sensitivity_cache(max_age_hours: int = 24) -> dict[str, float]:
    """
    Bulk-load all non-stale sensitivity rows in a single query.
    Returns {cache_key: k} for all rows fresher than max_age_hours.
    """
    conn = get_conn()
    cur = conn.cursor()
    cur.execute("SELECT cache_key, k, fetched_at FROM mlb_matchup_sensitivity_cache")
    rows = cur.fetchall()
    cur.close()
    conn.close()
    return {
        row["cache_key"]: float(row["k"])
        for row in rows
        if hours_since(row["fetched_at"]) < max_age_hours
    }


def set_sensitivity_cache(player_id: str, stat_type: str, k: float, n_games: int):
    """Upsert sensitivity k for (player_id, stat_type)."""
    key = f"{player_id}|{stat_type}"
    conn = get_conn()
    cur = conn.cursor()
    cur.execute(
        """
        INSERT INTO mlb_matchup_sensitivity_cache (cache_key, k, n_games, fetched_at)
        VALUES (%s, %s, %s, %s)
        ON CONFLICT (cache_key) DO UPDATE
            SET k = EXCLUDED.k,
                n_games = EXCLUDED.n_games,
                fetched_at = EXCLUDED.fetched_at
        """,
        (key, k, n_games, now_utc())
    )
    conn.commit()
    cur.close()
    conn.close()


def bulk_set_sensitivity_cache(entries: list[tuple[str, str, float, int]]):
    """
    Batch-upsert sensitivity entries in a single DB transaction.
    entries: list of (player_id, stat_type, k, n_games)
    """
    if not entries:
        return
    ts = now_utc()
    conn = get_conn()
    cur = conn.cursor()
    psycopg2.extras.execute_values(
        cur,
        """
        INSERT INTO mlb_matchup_sensitivity_cache (cache_key, k, n_games, fetched_at)
        VALUES %s
        ON CONFLICT (cache_key) DO UPDATE
            SET k = EXCLUDED.k,
                n_games = EXCLUDED.n_games,
                fetched_at = EXCLUDED.fetched_at
        """,
        [(f"{pid}|{stat}", k, n, ts) for pid, stat, k, n in entries],
    )
    conn.commit()
    cur.close()
    conn.close()


def get_opponent_defense_cache(season: str, data_type: str, max_age_hours: int = 24) -> list | None:
    """Return cached opponent defense rows for (season, data_type), or None if stale/missing."""
    conn = get_conn()
    cur = conn.cursor()
    cur.execute(
        "SELECT payload, fetched_at FROM mlb_opponent_defense_cache WHERE season = %s AND data_type = %s",
        (season, data_type)
    )
    row = cur.fetchone()
    cur.close()
    conn.close()
    if row and hours_since(row["fetched_at"]) < max_age_hours:
        return json.loads(row["payload"])
    return None


def set_opponent_defense_cache(season: str, data_type: str, rows: list):
    """Upsert opponent defense rows for (season, data_type)."""
    conn = get_conn()
    cur = conn.cursor()
    cur.execute(
        """
        INSERT INTO mlb_opponent_defense_cache (season, data_type, payload, fetched_at)
        VALUES (%s, %s, %s, %s)
        ON CONFLICT (season, data_type) DO UPDATE
            SET payload = EXCLUDED.payload,
                fetched_at = EXCLUDED.fetched_at
        """,
        (season, data_type, json.dumps(rows), now_utc())
    )
    conn.commit()
    cur.close()
    conn.close()


def get_sgo_daily_log(date: str) -> list[dict]:
    """
    Return all SGO request log entries for a given date (YYYY-MM-DD).

    Args:
        date: ISO date string to filter by (matches timestamp prefix).

    Returns:
        List of log row dicts ordered by timestamp ascending.
    """
    conn = get_conn()
    cur = conn.cursor()
    cur.execute(
        """
        SELECT timestamp, endpoint, http_status, entities_consumed, notes
        FROM mlb_sgo_request_log
        WHERE timestamp LIKE %s
        ORDER BY timestamp ASC
        """,
        (f"{date}%",)
    )
    rows = [dict(r) for r in cur.fetchall()]
    cur.close()
    conn.close()
    return rows


def log_scored_legs(legs: list[dict], run_date: str, parlay_odd_ids: set) -> int:
    """
    Bulk-insert all scored legs from a pipeline run into mlb_scored_legs.

    Idempotent per (run_date, odd_id): uses ON CONFLICT (run_date, odd_id) DO NOTHING
    so that re-running the pipeline later in the same day (e.g. after pitcher K props
    become available) appends new legs without duplicating existing ones.
    Legs without an odd_id are skipped entirely.

    Marks in_parlay=True for any leg whose odd_id appears in parlay_odd_ids.
    Returns the number of rows inserted.
    """
    if not legs:
        return 0
    conn = get_conn()
    cur = conn.cursor()
    ts = now_utc()
    rows = [
        (
            run_date,
            leg.get("player_name", ""),
            leg.get("team"),
            leg.get("opponent"),
            leg.get("stat", ""),
            leg.get("best_line"),
            leg.get("direction", "over"),
            str(leg.get("best_odds", "")),
            leg.get("coverage_pct"),
            leg.get("p_over"),
            leg.get("ev_per_unit"),
            leg.get("trend_pass"),
            leg.get("trend_score"),
            leg.get("opponent_adjustment"),
            leg.get("position"),
            leg.get("odd_id") in parlay_odd_ids,
            leg.get("game_pk"),
            str(leg.get("player_id")) if leg.get("player_id") else None,
            str(leg.get("opposing_pitcher_id")) if leg.get("opposing_pitcher_id") else None,
            ts,
            leg.get("odd_id"),
            leg.get("game_start_time"),
            leg.get("pitcher_hand"),
            leg.get("composite_score"),
            leg.get("coverage_overall"),
            leg.get("coverage_vs_hand"),
            leg.get("coverage_recent_10"),
            leg.get("coverage_recent_5"),
            leg.get("pitcher_id"),
            leg.get("pitcher_name"),
            leg.get("pitcher_team"),
            leg.get("pitcher_era"),
            leg.get("pitcher_k9"),
            leg.get("pitcher_whip"),
            leg.get("batter_hand"),
            leg.get("pitcher_vs_batter_hand_era"),
        )
        for leg in legs
        if leg.get("stat") and leg.get("player_name") and leg.get("odd_id")
    ]
    if not rows:
        cur.close()
        conn.close()
        return 0
    psycopg2.extras.execute_values(
        cur,
        """
        INSERT INTO mlb_scored_legs
            (run_date, player_name, team, opponent, stat, line, direction, odds,
             coverage_pct, p_over, ev_per_unit, trend_pass, trend_score,
             opponent_adjustment, position, in_parlay,
             game_pk, player_id, opposing_pitcher_id, logged_at, odd_id,
             game_start_time, pitcher_hand, composite_score,
             coverage_overall, coverage_vs_hand, coverage_recent_10, coverage_recent_5,
             pitcher_id, pitcher_name, pitcher_team, pitcher_era, pitcher_k9, pitcher_whip,
             batter_hand, pitcher_vs_batter_hand_era)
        VALUES %s
        ON CONFLICT (run_date, odd_id) DO UPDATE
            SET composite_score             = COALESCE(mlb_scored_legs.composite_score,             EXCLUDED.composite_score),
                game_start_time             = COALESCE(mlb_scored_legs.game_start_time,             EXCLUDED.game_start_time),
                coverage_overall            = EXCLUDED.coverage_overall,
                coverage_vs_hand            = EXCLUDED.coverage_vs_hand,
                coverage_recent_10          = EXCLUDED.coverage_recent_10,
                coverage_recent_5           = EXCLUDED.coverage_recent_5,
                pitcher_id                  = COALESCE(mlb_scored_legs.pitcher_id,                  EXCLUDED.pitcher_id),
                pitcher_name                = COALESCE(mlb_scored_legs.pitcher_name,                EXCLUDED.pitcher_name),
                pitcher_team                = COALESCE(mlb_scored_legs.pitcher_team,                EXCLUDED.pitcher_team),
                pitcher_era                 = COALESCE(mlb_scored_legs.pitcher_era,                 EXCLUDED.pitcher_era),
                pitcher_k9                  = COALESCE(mlb_scored_legs.pitcher_k9,                  EXCLUDED.pitcher_k9),
                pitcher_whip                = COALESCE(mlb_scored_legs.pitcher_whip,                EXCLUDED.pitcher_whip),
                pitcher_hand                = COALESCE(mlb_scored_legs.pitcher_hand,                EXCLUDED.pitcher_hand),
                batter_hand                 = COALESCE(mlb_scored_legs.batter_hand,                 EXCLUDED.batter_hand),
                pitcher_vs_batter_hand_era  = COALESCE(mlb_scored_legs.pitcher_vs_batter_hand_era,  EXCLUDED.pitcher_vs_batter_hand_era)
        """,
        rows,
    )
    conn.commit()
    inserted = cur.rowcount
    cur.close()
    conn.close()
    return inserted


def log_training_data_legs(legs: list[dict], run_date: str) -> int:
    """
    Bulk-insert all scored legs from a live pipeline run into mlb_training_data.

    Uses the same {date}|{odd_id} prefix format as the backfill script so
    prospective and backfill rows coexist under the UNIQUE (odd_id) constraint.

    Called after build_hybrid_parlays() so composite_score is populated for
    legs that made the 60%+ pool; it remains NULL for the 55-60% bucket.
    ON CONFLICT (odd_id) DO NOTHING — safe to re-run the same pipeline day.

    Returns the number of newly inserted rows.
    """
    if not legs:
        return 0
    ts = now_utc()
    rows = []
    for leg in legs:
        raw_odd_id = leg.get("odd_id")
        line = leg.get("best_line")
        if not raw_odd_id or line is None:
            continue
        odd_id = f"{run_date}|{raw_odd_id}"
        rows.append((
            str(leg.get("player_id") or ""),
            leg.get("player_name", ""),
            leg.get("stat", ""),
            leg.get("direction", "over"),
            float(line),
            str(leg.get("best_odds", "")),
            odd_id,
            run_date,
            leg.get("game_pk"),
            leg.get("coverage_pct"),
            leg.get("composite_score"),
            leg.get("opponent_adjustment"),
            leg.get("trend_score"),
            ts,
        ))

    if not rows:
        return 0

    conn = get_conn()
    cur = conn.cursor()
    psycopg2.extras.execute_values(
        cur,
        """
        INSERT INTO mlb_training_data
            (player_id, player_name, stat, direction, line, odds,
             odd_id, game_date, game_pk,
             coverage_pct, composite_score, opponent_adjustment, trend_score,
             logged_at)
        VALUES %s
        ON CONFLICT (odd_id) DO NOTHING
        """,
        rows,
    )
    conn.commit()
    inserted = cur.rowcount
    cur.close()
    conn.close()
    return inserted


def get_players_used_today(run_date: str) -> set:
    """
    Get set of player IDs already used in parlays today.

    Ensures each player appears in at most 1 parlay per day, across all
    pipeline runs (9am, 12pm, 5:30pm) and manual regenerations.

    Args:
        run_date: Date string (YYYY-MM-DD)

    Returns:
        set: Player IDs (as strings) already used in today's parlays
    """
    conn = get_conn()
    cur = conn.cursor()
    try:
        cur.execute(
            """
            SELECT DISTINCT l.player_id
            FROM mlb_parlay_legs_v2 l
            JOIN mlb_parlay_recommendations_v2 p ON l.parlay_id = p.id
            WHERE p.run_date = %s
              AND l.player_id IS NOT NULL
            """,
            (run_date,),
        )
        rows = cur.fetchall()
        return {str(row["player_id"]) for row in rows}
    except Exception as e:
        print(f"[ERROR] Failed to get players used today: {e}")
        return set()  # fail open — don't block parlay generation
    finally:
        cur.close()
        conn.close()


def get_pitcher_profile(pitcher_id: str, max_age_hours: int = 24) -> dict | None:
    """Return cached pitcher profile, or None if missing/expired (TTL 24hr)."""
    conn = get_conn()
    cur = conn.cursor()
    cur.execute(
        "SELECT * FROM pitcher_profiles WHERE pitcher_id = %s",
        (pitcher_id,)
    )
    row = cur.fetchone()
    cur.close()
    conn.close()
    if row and hours_since(row["last_updated"]) < max_age_hours:
        return dict(row)
    return None


def set_pitcher_profile(pitcher_id: str, team_id: str, era: float, era_rank: int,
                        k9: float, k9_rank: int, whip: float, whip_rank: int, hand: str):
    """Upsert a pitcher's profile stats."""
    conn = get_conn()
    cur = conn.cursor()
    cur.execute(
        """
        INSERT INTO pitcher_profiles
            (pitcher_id, team_id, era, era_rank, k9, k9_rank, whip, whip_rank, hand, last_updated)
        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
        ON CONFLICT (pitcher_id) DO UPDATE
            SET team_id = EXCLUDED.team_id,
                era = EXCLUDED.era,
                era_rank = EXCLUDED.era_rank,
                k9 = EXCLUDED.k9,
                k9_rank = EXCLUDED.k9_rank,
                whip = EXCLUDED.whip,
                whip_rank = EXCLUDED.whip_rank,
                hand = EXCLUDED.hand,
                last_updated = EXCLUDED.last_updated
        """,
        (pitcher_id, team_id, era, era_rank, k9, k9_rank, whip, whip_rank, hand, now_utc())
    )
    conn.commit()
    cur.close()
    conn.close()


def get_pending_lineup_legs(run_date: str) -> list[dict]:
    """
    Return today's scored legs where lineup_confirmed is FALSE and game_pk is set.

    Used by lineup_poller to find legs that need re-scoring once lineups are posted.
    """
    conn = get_conn()
    cur = conn.cursor()
    cur.execute(
        """
        SELECT id, game_pk, player_id, player_name, team, stat, line, direction,
               opposing_pitcher_id, coverage_pct, p_over, ev_per_unit,
               trend_score, opponent_adjustment, position, in_parlay
        FROM mlb_scored_legs
        WHERE run_date = %s
          AND lineup_confirmed = FALSE
          AND game_pk IS NOT NULL
        """,
        (run_date,)
    )
    rows = [dict(r) for r in cur.fetchall()]
    cur.close()
    conn.close()
    return rows


def update_leg_after_rescore(leg_id: int, coverage_pct: float | None,
                              p_over: float | None, ev_per_unit: float | None,
                              trend_score: float | None, opponent_adjustment: float | None):
    """Update a scored leg's scoring fields and mark lineup_confirmed after re-scoring."""
    conn = get_conn()
    cur = conn.cursor()
    cur.execute(
        """
        UPDATE mlb_scored_legs
        SET coverage_pct = %s,
            p_over = %s,
            ev_per_unit = %s,
            trend_score = %s,
            opponent_adjustment = %s,
            lineup_confirmed = TRUE,
            last_updated = %s
        WHERE id = %s
        """,
        (coverage_pct, p_over, ev_per_unit, trend_score, opponent_adjustment,
         now_utc(), leg_id)
    )
    conn.commit()
    cur.close()
    conn.close()


def mark_lineup_confirmed(leg_id: int):
    """Mark a scored leg as lineup_confirmed without changing its scores."""
    conn = get_conn()
    cur = conn.cursor()
    cur.execute(
        "UPDATE mlb_scored_legs SET lineup_confirmed = TRUE, last_updated = %s WHERE id = %s",
        (now_utc(), leg_id)
    )
    conn.commit()
    cur.close()
    conn.close()


def get_scored_legs(run_date: str) -> list[dict]:
    """
    Return the best-direction leg per player+stat for a given date.

    For each (player_name, stat) pair, keeps only the direction with the
    higher ev_per_unit (tiebreak: higher coverage_pct). This eliminates
    both OVER and UNDER showing for the same player prop.

    Used by the web API to serve today's leg table.
    """
    conn = get_conn()
    cur = conn.cursor()
    cur.execute(
        """
        WITH ranked_legs AS (
            SELECT *,
                   ROW_NUMBER() OVER (
                       PARTITION BY player_name, stat
                       ORDER BY ev_per_unit DESC NULLS LAST,
                                coverage_pct DESC NULLS LAST
                   ) AS rn
            FROM mlb_scored_legs
            WHERE run_date = %s
        )
        SELECT *
        FROM ranked_legs
        WHERE rn = 1
        ORDER BY stat, ev_per_unit DESC NULLS LAST
        """,
        (run_date,)
    )
    rows = [dict(r) for r in cur.fetchall()]
    cur.close()
    conn.close()
    return rows


def get_dashboard_data() -> dict:
    """
    Return all dashboard analytics sections in a single DB round-trip.

    Queries mlb_scored_legs for resolved legs (result IS NOT NULL) across
    all dates. Returns a dict with six keys, one per dashboard section.

    Coverage calibration note: coverage_pct is stored on the 0-100 scale.
    """
    conn = get_conn()
    cur = conn.cursor()

    # Dedup CTE used by all dashboard queries.
    # The raw mlb_scored_legs table can have same-direction duplicates when
    # odd_id is NULL (PostgreSQL UNIQUE constraints don't treat NULLs as equal).
    # This CTE keeps the highest-EV row per (run_date, player_name, stat, direction).
    DEDUP_CTE = """
        deduped AS (
            SELECT *,
                   ROW_NUMBER() OVER (
                       PARTITION BY run_date, player_name, stat, direction
                       ORDER BY ev_per_unit DESC NULLS LAST
                   ) AS _rn
            FROM mlb_scored_legs
            WHERE result IS NOT NULL
        )
    """

    # ── Section 1: Coverage calibration ──────────────────────────────────────
    cur.execute(f"""
        WITH {DEDUP_CTE}
        SELECT
            CASE
                WHEN coverage_pct < 55 THEN '<55%'
                WHEN coverage_pct < 60 THEN '55-60%'
                WHEN coverage_pct < 65 THEN '60-65%'
                WHEN coverage_pct < 70 THEN '65-70%'
                ELSE '70%+'
            END AS bucket,
            AVG(coverage_pct)                                        AS avg_predicted,
            COUNT(*)                                                  AS total,
            SUM(CASE WHEN result = 'won'  THEN 1 ELSE 0 END)         AS won,
            SUM(CASE WHEN result = 'lost' THEN 1 ELSE 0 END)         AS lost,
            AVG(CASE WHEN result = 'won'  THEN 1.0 ELSE 0.0 END)     AS actual_rate
        FROM deduped
        WHERE _rn = 1
          AND coverage_pct IS NOT NULL
        GROUP BY bucket
        ORDER BY avg_predicted
    """)
    calibration = [dict(r) for r in cur.fetchall()]

    # ── Section 2: Prop type performance ─────────────────────────────────────
    cur.execute(f"""
        WITH {DEDUP_CTE}
        SELECT
            stat,
            COUNT(*)                                                  AS total,
            SUM(CASE WHEN result = 'won'  THEN 1 ELSE 0 END)         AS won,
            SUM(CASE WHEN result = 'lost' THEN 1 ELSE 0 END)         AS lost,
            AVG(CASE WHEN result = 'won'  THEN 1.0 ELSE 0.0 END)     AS win_rate,
            AVG(coverage_pct)                                         AS avg_coverage,
            AVG(
                CASE
                    WHEN odds ~ '^[+-]?[0-9]+$'
                    THEN odds::numeric
                    ELSE NULL
                END
            )                                                         AS avg_odds
        FROM deduped
        WHERE _rn = 1
        GROUP BY stat
        ORDER BY total DESC
    """)
    by_prop = [dict(r) for r in cur.fetchall()]

    # ── Section 3: Direction analysis ────────────────────────────────────────
    cur.execute(f"""
        WITH {DEDUP_CTE}
        SELECT
            direction,
            COUNT(*)                                                  AS total,
            SUM(CASE WHEN result = 'won'  THEN 1 ELSE 0 END)         AS won,
            AVG(CASE WHEN result = 'won'  THEN 1.0 ELSE 0.0 END)     AS win_rate,
            AVG(coverage_pct)                                         AS avg_coverage
        FROM deduped
        WHERE _rn = 1
        GROUP BY direction
        ORDER BY direction
    """)
    by_direction = [dict(r) for r in cur.fetchall()]

    # ── Section 4: Recent 7-day trend ────────────────────────────────────────
    cur.execute(f"""
        WITH {DEDUP_CTE}
        SELECT
            run_date,
            COUNT(*)                                                  AS total,
            SUM(CASE WHEN result = 'won'  THEN 1 ELSE 0 END)         AS won,
            SUM(CASE WHEN result = 'lost' THEN 1 ELSE 0 END)         AS lost,
            AVG(CASE WHEN result = 'won'  THEN 1.0 ELSE 0.0 END)     AS win_rate
        FROM deduped
        WHERE _rn = 1
          AND run_date >= (CURRENT_DATE - INTERVAL '7 days')::text
        GROUP BY run_date
        ORDER BY run_date DESC
    """)
    recent_trend = [dict(r) for r in cur.fetchall()]

    # Compute rolling 3-day win rate (chronological then re-reverse)
    days_chron = list(reversed(recent_trend))
    for i, row in enumerate(days_chron):
        window = days_chron[max(0, i - 2): i + 1]
        total_w = sum(d["won"] for d in window)
        total_n = sum(d["total"] for d in window)
        row["rolling_3d"] = round(total_w / total_n, 4) if total_n else None
    recent_trend = list(reversed(days_chron))

    # ── Section 5: Top performers (min 5 resolved legs) ──────────────────────
    cur.execute(f"""
        WITH {DEDUP_CTE}
        SELECT
            player_name,
            stat,
            COUNT(*)                                                  AS total,
            SUM(CASE WHEN result = 'won'  THEN 1 ELSE 0 END)         AS won,
            SUM(CASE WHEN result = 'lost' THEN 1 ELSE 0 END)         AS lost,
            AVG(CASE WHEN result = 'won'  THEN 1.0 ELSE 0.0 END)     AS win_rate
        FROM deduped
        WHERE _rn = 1
        GROUP BY player_name, stat
        HAVING COUNT(*) >= 5
        ORDER BY win_rate DESC, total DESC
        LIMIT 10
    """)
    top_performers = [dict(r) for r in cur.fetchall()]

    # ── Section 6: EV signal validation ──────────────────────────────────────
    cur.execute(f"""
        WITH {DEDUP_CTE}
        SELECT
            CASE
                WHEN ev_per_unit < -0.10 THEN 'Strong -EV (<-10%)'
                WHEN ev_per_unit < 0     THEN 'Weak -EV (-10% to 0)'
                WHEN ev_per_unit < 0.10  THEN 'Neutral (0 to 10%)'
                WHEN ev_per_unit < 0.15  THEN 'Weak +EV (10-15%)'
                ELSE                          'Strong +EV (>15%)'
            END AS ev_bucket,
            MIN(ev_per_unit)                                          AS _sort_key,
            COUNT(*)                                                  AS total,
            SUM(CASE WHEN result = 'won'  THEN 1 ELSE 0 END)         AS won,
            AVG(CASE WHEN result = 'won'  THEN 1.0 ELSE 0.0 END)     AS win_rate
        FROM deduped
        WHERE _rn = 1
          AND ev_per_unit IS NOT NULL
        GROUP BY ev_bucket
        ORDER BY _sort_key
    """)
    ev_validation = [dict(r) for r in cur.fetchall()]
    for row in ev_validation:
        row.pop("_sort_key", None)

    # ── Summary totals ────────────────────────────────────────────────────────
    cur.execute(f"""
        WITH {DEDUP_CTE}
        SELECT
            COUNT(*)                                                  AS total_resolved,
            SUM(CASE WHEN result = 'won'  THEN 1 ELSE 0 END)         AS total_won,
            AVG(CASE WHEN result = 'won'  THEN 1.0 ELSE 0.0 END)     AS overall_win_rate,
            COUNT(DISTINCT run_date)                                  AS days_tracked
        FROM deduped
        WHERE _rn = 1
    """)
    summary = dict(cur.fetchone())

    cur.close()
    conn.close()

    return {
        "summary":        summary,
        "calibration":    calibration,
        "by_prop":        by_prop,
        "by_direction":   by_direction,
        "recent_trend":   recent_trend,
        "top_performers": top_performers,
        "ev_validation":  ev_validation,
    }


def get_training_dashboard_data() -> dict:
    """
    Return dashboard analytics from mlb_training_data (66K historical samples).

    All six sections query mlb_training_data instead of mlb_scored_legs.
    Results use 'hit'/'miss' terminology (not 'won'/'lost').
    Percentage values are pre-computed on the 0-100 scale by the DB.
    """
    conn = get_conn()
    cur = conn.cursor()

    # ── Summary ────────────────────────────────────────────────────────────────
    cur.execute("""
        SELECT
            COUNT(*)                                                         AS total_props,
            COUNT(*) FILTER (
                WHERE composite_score IS NOT NULL AND result IN ('hit', 'miss')
            )                                                                AS calibrated_samples,
            COUNT(*) FILTER (WHERE result IN ('hit', 'miss'))                AS total_resolved,
            COUNT(*) FILTER (WHERE result = 'hit')                           AS total_hits,
            ROUND(
                100.0 * COUNT(*) FILTER (WHERE result = 'hit') /
                NULLIF(COUNT(*) FILTER (WHERE result IN ('hit', 'miss')), 0),
                1
            )                                                                AS overall_hit_rate
        FROM mlb_training_data
    """)
    summary = dict(cur.fetchone())

    # ── Section 1: Calibration by composite_score bucket ──────────────────────
    cur.execute("""
        SELECT
            CASE
                WHEN composite_score < 25 THEN '<25'
                WHEN composite_score < 35 THEN '25-35'
                WHEN composite_score < 45 THEN '35-45'
                WHEN composite_score < 55 THEN '45-55'
                WHEN composite_score < 65 THEN '55-65'
                ELSE '65+'
            END                                                              AS score_bucket,
            COUNT(*)                                                         AS total,
            COUNT(*) FILTER (WHERE result = 'hit')                          AS hits,
            ROUND(
                100.0 * COUNT(*) FILTER (WHERE result = 'hit') / COUNT(*),
                1
            )                                                                AS hit_rate_pct,
            ROUND(AVG(coverage_pct)::numeric, 1)                            AS avg_predicted_coverage
        FROM mlb_training_data
        WHERE composite_score IS NOT NULL
          AND result IN ('hit', 'miss')
        GROUP BY score_bucket
        ORDER BY score_bucket
    """)
    calibration = [dict(r) for r in cur.fetchall()]

    # ── Section 2: Prop performance by stat ───────────────────────────────────
    cur.execute("""
        SELECT
            stat,
            COUNT(*)                                                         AS total,
            COUNT(*) FILTER (WHERE result = 'hit')                          AS hits,
            ROUND(
                100.0 * COUNT(*) FILTER (WHERE result = 'hit') / COUNT(*),
                1
            )                                                                AS hit_rate_pct,
            ROUND(AVG(composite_score)::numeric, 1)                         AS avg_composite
        FROM mlb_training_data
        WHERE result IN ('hit', 'miss')
        GROUP BY stat
        ORDER BY total DESC
        LIMIT 15
    """)
    by_prop = [dict(r) for r in cur.fetchall()]

    # ── Section 3: Direction bias ──────────────────────────────────────────────
    cur.execute("""
        SELECT
            direction,
            COUNT(*)                                                         AS total,
            COUNT(*) FILTER (WHERE result = 'hit')                          AS hits,
            ROUND(
                100.0 * COUNT(*) FILTER (WHERE result = 'hit') / COUNT(*),
                1
            )                                                                AS hit_rate_pct
        FROM mlb_training_data
        WHERE result IN ('hit', 'miss')
        GROUP BY direction
        ORDER BY total DESC
    """)
    by_direction = [dict(r) for r in cur.fetchall()]

    # ── Section 4: Coverage accuracy (predicted vs actual) ────────────────────
    cur.execute("""
        SELECT
            CASE
                WHEN coverage_pct < 30 THEN '<30%'
                WHEN coverage_pct < 40 THEN '30-40%'
                WHEN coverage_pct < 50 THEN '40-50%'
                WHEN coverage_pct < 60 THEN '50-60%'
                WHEN coverage_pct < 70 THEN '60-70%'
                ELSE '70%+'
            END                                                              AS coverage_bucket,
            COUNT(*)                                                         AS total,
            COUNT(*) FILTER (WHERE result = 'hit')                          AS hits,
            ROUND(
                100.0 * COUNT(*) FILTER (WHERE result = 'hit') / COUNT(*),
                1
            )                                                                AS actual_hit_rate,
            ROUND(AVG(coverage_pct)::numeric, 1)                            AS predicted_coverage
        FROM mlb_training_data
        WHERE coverage_pct IS NOT NULL
          AND result IN ('hit', 'miss')
        GROUP BY coverage_bucket
        ORDER BY coverage_bucket
    """)
    coverage_accuracy = [dict(r) for r in cur.fetchall()]

    # ── Section 5: Trend validation ───────────────────────────────────────────
    cur.execute("""
        SELECT
            CASE
                WHEN trend_score >= 0.7 THEN 'HOT'
                WHEN trend_score <= 0.3 THEN 'COLD'
                ELSE 'NEUTRAL'
            END                                                              AS trend_category,
            COUNT(*)                                                         AS total,
            COUNT(*) FILTER (WHERE result = 'hit')                          AS hits,
            ROUND(
                100.0 * COUNT(*) FILTER (WHERE result = 'hit') / COUNT(*),
                1
            )                                                                AS hit_rate_pct
        FROM mlb_training_data
        WHERE trend_score IS NOT NULL
          AND result IN ('hit', 'miss')
        GROUP BY trend_category
        ORDER BY trend_category
    """)
    trend_validation = [dict(r) for r in cur.fetchall()]

    # ── Section 6: Recent legs ─────────────────────────────────────────────────
    cur.execute("""
        SELECT
            game_date,
            player_name,
            stat,
            direction,
            line,
            composite_score,
            coverage_pct,
            result,
            actual_stat
        FROM mlb_training_data
        WHERE result IS NOT NULL
        ORDER BY game_date DESC, id DESC
        LIMIT 50
    """)
    recent_legs = [dict(r) for r in cur.fetchall()]

    cur.close()
    conn.close()

    return {
        "summary":           summary,
        "calibration":       calibration,
        "by_prop":           by_prop,
        "by_direction":      by_direction,
        "coverage_accuracy": coverage_accuracy,
        "trend_validation":  trend_validation,
        "recent_legs":       recent_legs,
    }


def get_training_analytics_data() -> dict:
    """
    Return all data needed for the Training Data analytics tab.

    Five sections:
      daily_health    — last 14 days of collection volume + resolution
      direction_bias  — hit rate by stat+direction (last 30 days, ≥20 samples)
      calibration     — predicted coverage vs actual hit rate by bucket
      feature_health  — feature completeness % per day (last 7 days)
      summary         — aggregate totals, date range, unresolved count
    """
    conn = get_conn()
    cur = conn.cursor()

    # ── Daily health ──────────────────────────────────────────────────────────
    cur.execute("""
        SELECT
            game_date,
            COUNT(*)                                                 AS total,
            COUNT(*) FILTER (WHERE result = 'hit')                   AS hits,
            COUNT(*) FILTER (WHERE result = 'miss')                  AS misses,
            COUNT(*) FILTER (WHERE result IS NULL)                   AS pending,
            ROUND(
                100.0 * COUNT(*) FILTER (WHERE result = 'hit') /
                NULLIF(COUNT(*) FILTER (WHERE result IN ('hit','miss')), 0),
                1
            )                                                        AS hit_rate,
            COUNT(*) FILTER (WHERE coverage_pct IS NOT NULL AND coverage_pct >= 60) AS high_coverage
        FROM mlb_training_data
        WHERE game_date >= CURRENT_DATE - INTERVAL '14 days'
        GROUP BY game_date
        ORDER BY game_date DESC
    """)
    daily_health = [dict(r) for r in cur.fetchall()]

    # ── Direction bias ────────────────────────────────────────────────────────
    cur.execute("""
        SELECT
            stat,
            direction,
            COUNT(*)                                                 AS total,
            COUNT(*) FILTER (WHERE result = 'hit')                   AS hits,
            COUNT(*) FILTER (WHERE result = 'miss')                  AS misses,
            ROUND(
                100.0 * COUNT(*) FILTER (WHERE result = 'hit') /
                NULLIF(COUNT(*) FILTER (WHERE result IN ('hit','miss')), 0),
                1
            )                                                        AS hit_rate
        FROM mlb_training_data
        WHERE result IN ('hit', 'miss')
          AND game_date >= CURRENT_DATE - INTERVAL '30 days'
        GROUP BY stat, direction
        HAVING COUNT(*) >= 20
        ORDER BY stat, direction
    """)
    direction_bias = [dict(r) for r in cur.fetchall()]

    # ── Calibration ───────────────────────────────────────────────────────────
    cur.execute("""
        SELECT
            CASE
                WHEN coverage_pct < 55 THEN '<55%'
                WHEN coverage_pct < 60 THEN '55-60%'
                WHEN coverage_pct < 65 THEN '60-65%'
                WHEN coverage_pct < 70 THEN '65-70%'
                ELSE '70%+'
            END                                                      AS bucket,
            COUNT(*)                                                 AS total,
            COUNT(*) FILTER (WHERE result = 'hit')                   AS hits,
            ROUND(
                100.0 * COUNT(*) FILTER (WHERE result = 'hit') / COUNT(*),
                1
            )                                                        AS actual_hit_rate,
            ROUND(AVG(coverage_pct)::numeric, 1)                     AS avg_predicted,
            ROUND(
                (AVG(coverage_pct) -
                100.0 * COUNT(*) FILTER (WHERE result = 'hit') / COUNT(*))::numeric,
                1
            )                                                        AS error_pp
        FROM mlb_training_data
        WHERE coverage_pct IS NOT NULL
          AND result IN ('hit', 'miss')
        GROUP BY bucket
        ORDER BY bucket
    """)
    calibration = [dict(r) for r in cur.fetchall()]

    # ── Feature health ────────────────────────────────────────────────────────
    cur.execute("""
        SELECT
            game_date,
            COUNT(*)                                                                       AS total,
            ROUND(100.0 * COUNT(*) FILTER (WHERE coverage_pct IS NOT NULL)       / COUNT(*), 1) AS coverage_pct,
            ROUND(100.0 * COUNT(*) FILTER (WHERE composite_score IS NOT NULL)    / COUNT(*), 1) AS score_pct,
            ROUND(100.0 * COUNT(*) FILTER (WHERE opponent_adjustment IS NOT NULL) / COUNT(*), 1) AS opponent_pct,
            ROUND(100.0 * COUNT(*) FILTER (WHERE trend_score IS NOT NULL)        / COUNT(*), 1) AS trend_pct
        FROM mlb_training_data
        WHERE game_date >= CURRENT_DATE - INTERVAL '7 days'
        GROUP BY game_date
        ORDER BY game_date DESC
    """)
    feature_health = [dict(r) for r in cur.fetchall()]

    # ── Summary ───────────────────────────────────────────────────────────────
    cur.execute("""
        SELECT
            COUNT(*)                                                         AS total_props,
            MIN(game_date)                                                   AS first_date,
            MAX(game_date)                                                   AS last_date,
            COUNT(DISTINCT game_date)                                        AS days_covered,
            ROUND(
                100.0 * COUNT(*) FILTER (WHERE result = 'hit') /
                NULLIF(COUNT(*) FILTER (WHERE result IN ('hit', 'miss')), 0),
                1
            )                                                                AS overall_hit_rate,
            COUNT(*) FILTER (WHERE result IS NULL)                           AS unresolved_count
        FROM mlb_training_data
    """)
    s = dict(cur.fetchone())
    summary = {
        "total_props":      s["total_props"],
        "days_covered":     s["days_covered"],
        "date_range":       f"{s['first_date']} to {s['last_date']}",
        "overall_hit_rate": s["overall_hit_rate"],
        "unresolved_count": s["unresolved_count"],
        "last_updated":     now_utc(),
    }

    cur.close()
    conn.close()

    return {
        "daily_health":   daily_health,
        "direction_bias": direction_bias,
        "calibration":    calibration,
        "feature_health": feature_health,
        "summary":        summary,
    }


def get_recommendation_history(run_date: str) -> list[dict]:
    """
    Return all parlay recommendation batches for a given date, newest first.

    Each batch groups parlays generated in the same pipeline run (9am, 12pm,
    5:30pm, or manual).  Full leg details are hydrated for each parlay.

    Args:
        run_date: Date string (YYYY-MM-DD)

    Returns:
        List of batch dicts:
            {batch_id, source, generated_time, parlay_count, parlays: [...]}
        Each parlay has {id, rank, total_odds, avg_coverage, num_legs,
                         outcome, created_at, legs: [...]}
    """
    print(f"[db.get_recommendation_history] Querying date: {run_date}")
    conn = get_conn()
    cur = conn.cursor()
    try:
        cur.execute(
            """
            SELECT
                p.batch_id,
                p.source,
                MIN(p.created_at) AS created_at,
                COUNT(DISTINCT p.id) AS parlay_count
            FROM mlb_parlay_recommendations_v2 p
            WHERE p.run_date = %s
            GROUP BY p.batch_id, p.source
            ORDER BY MIN(p.created_at) DESC
            """,
            (run_date,),
        )
        batches = [dict(r) for r in cur.fetchall()]
        print(f"[db.get_recommendation_history] Found {len(batches)} batches")

        result = []
        for batch in batches:
            cur.execute(
                """
                SELECT id, rank, total_odds, avg_coverage, num_legs,
                       outcome, created_at
                FROM mlb_parlay_recommendations_v2
                WHERE batch_id = %s
                ORDER BY rank
                """,
                (batch["batch_id"],),
            )
            parlays = [dict(r) for r in cur.fetchall()]

            for parlay in parlays:
                cur.execute(
                    """
                    SELECT player_name, team, stat, line, direction, odds,
                           coverage, ev, outcome, result_value
                    FROM mlb_parlay_legs_v2
                    WHERE parlay_id = %s
                    ORDER BY id
                    """,
                    (parlay["id"],),
                )
                parlay["legs"] = [dict(r) for r in cur.fetchall()]

            created_at = batch["created_at"]
            if created_at:
                from datetime import timezone
                from zoneinfo import ZoneInfo
                if created_at.tzinfo is None:
                    created_at = created_at.replace(tzinfo=timezone.utc)
                created_at_et = created_at.astimezone(ZoneInfo("America/New_York"))
                h = created_at_et.hour
                period = "PM" if h >= 12 else "AM"
                display_hour = h % 12 or 12
                generated_time = f"{display_hour}:{created_at_et.strftime('%M')} {period}"
            else:
                generated_time = "Unknown"
            result.append({
                "batch_id":       batch["batch_id"],
                "source":         batch["source"],
                "generated_time": generated_time,
                "parlay_count":   batch["parlay_count"],
                "parlays":        parlays,
            })

        return result
    except Exception as e:
        print(f"[ERROR] Failed to load recommendation history: {e}")
        return []
    finally:
        cur.close()
        conn.close()


def save_parlay_recommendation(recommendation: dict) -> int:
    """
    Upsert one row into mlb_parlay_recommendations and return its id.

    Uses ON CONFLICT (recommendation_date, rank) so re-running the pipeline
    or triggering a manual regeneration overwrites the existing row rather than
    inserting a duplicate.  Requires a UNIQUE constraint on those two columns
    (see sql/add_recommendations_unique_constraint.sql).

    Args:
        recommendation: dict with keys:
            recommendation_date, pipeline_run_time, rank, leg_odd_ids (list),
            combined_odds, win_probability, edge_pct
    Returns:
        The row's serial id.
    """
    conn = get_conn()
    cur = conn.cursor()
    cur.execute(
        """
        INSERT INTO mlb_parlay_recommendations
            (recommendation_date, pipeline_run_time, rank, leg_odd_ids,
             combined_odds, win_probability, edge_pct)
        VALUES (%s, %s, %s, %s, %s, %s, %s)
        ON CONFLICT (recommendation_date, rank)
        DO UPDATE SET
            leg_odd_ids      = EXCLUDED.leg_odd_ids,
            combined_odds    = EXCLUDED.combined_odds,
            win_probability  = EXCLUDED.win_probability,
            edge_pct         = EXCLUDED.edge_pct,
            pipeline_run_time = EXCLUDED.pipeline_run_time
        RETURNING id
        """,
        (
            recommendation["recommendation_date"],
            recommendation["pipeline_run_time"],
            recommendation["rank"],
            recommendation["leg_odd_ids"],
            recommendation["combined_odds"],
            recommendation["win_probability"],
            recommendation["edge_pct"],
        ),
    )
    row_id = cur.fetchone()["id"]
    conn.commit()
    cur.close()
    conn.close()
    return row_id


def save_parlay_recommendations_v2(
    recommendations: list[dict],
    run_date: str,
    source: str = "auto",
) -> str:
    """
    Dual-write parlay recommendations to the normalized v2 schema.

    Inserts one row into mlb_parlay_recommendations_v2 per recommendation
    and one row into mlb_parlay_legs_v2 per leg.  The v2 tables must already
    exist (run the SQL migration in Supabase first).

    Args:
        recommendations: List of rec dicts from generate_recommendations().
                         Each has: legs, combined_odds, win_probability, edge_pct.
        run_date: 'YYYY-MM-DD' date string for this recommendation set.
        source: One of 'auto_9am', 'auto_12pm', 'auto_530pm', 'manual'.

    Returns:
        batch_id string (e.g. '2026-05-07_09:05:23').
    """
    from datetime import datetime as _dt
    if not recommendations:
        return ""

    from src.utils.sorting import sort_legs_by_game_time

    batch_id = f"{run_date}_{_dt.now().strftime('%H:%M:%S')}"
    conn = get_conn()
    cur = conn.cursor()

    for rank, rec in enumerate(recommendations, start=1):
        legs = sort_legs_by_game_time(rec.get("legs", []))
        coverages = [l.get("coverage_pct") for l in legs if l.get("coverage_pct") is not None]
        evs = [l.get("ev_per_unit") for l in legs if l.get("ev_per_unit") is not None]
        avg_coverage = round(sum(coverages) / len(coverages), 3) if coverages else None
        avg_ev = round(sum(evs) / len(evs), 4) if evs else None

        cur.execute(
            """
            INSERT INTO mlb_parlay_recommendations_v2
                (run_date, rank, total_odds, avg_coverage, avg_ev, num_legs,
                 outcome, source, batch_id, edge_percent)
            VALUES (%s, %s, %s, %s, %s, %s, 'pending', %s, %s, %s)
            RETURNING id
            """,
            (
                run_date,
                rank,
                rec.get("combined_odds"),
                avg_coverage,
                avg_ev,
                len(legs),
                source,
                batch_id,
                rec.get("edge_pct"),
            ),
        )
        row = cur.fetchone()
        if row is None:
            import traceback
            raise RuntimeError(
                f"[save_v2] INSERT INTO mlb_parlay_recommendations_v2 RETURNING id returned None "
                f"for rank={rank}, run_date={run_date!r}, source={source!r}, batch_id={batch_id!r}. "
                f"rec keys: {list(rec.keys())}, legs count: {len(legs)}"
            )
        parlay_id = row["id"]

        for leg in legs:
            cur.execute(
                """
                INSERT INTO mlb_parlay_legs_v2
                    (parlay_id, player_id, player_name, team, stat, line,
                     direction, odds, composite_score, opponent_adjustment,
                     coverage, ev, game_id, opposing_pitcher_id,
                     opposing_pitcher_name, outcome)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, 'pending')
                """,
                (
                    parlay_id,
                    leg.get("player_id"),
                    leg.get("player_name"),
                    leg.get("team"),
                    leg.get("stat"),
                    leg.get("best_line") or leg.get("line"),
                    leg.get("direction", "over"),
                    leg.get("best_odds") or leg.get("odds"),
                    leg.get("composite_score"),
                    leg.get("opponent_adjustment"),
                    leg.get("coverage_pct"),
                    leg.get("ev_per_unit"),
                    leg.get("game_pk"),
                    leg.get("opposing_pitcher_id"),
                    leg.get("opposing_pitcher_name"),
                ),
            )

    conn.commit()
    cur.close()
    conn.close()
    print(f"[save_v2] Saved {len(recommendations)} parlay(s) to v2 schema (batch: {batch_id})")
    return batch_id


def get_todays_recommendations() -> list[dict]:
    """
    Fetch all recommendations for today, ordered by rank ASC.

    Hydrates full leg details from mlb_scored_legs for each odd_id in
    leg_odd_ids. Returns an empty list when none exist yet.

    Returns:
        [
            {
                "id": int,
                "rank": int,
                "legs": [leg_dicts...],
                "combined_odds": int,
                "win_probability": float,
                "edge_pct": float,
                "analysis": str | None,
                "generated_at": str,
            },
            ...
        ]
    """
    conn = get_conn()
    cur = conn.cursor()

    cur.execute(
        """
        SELECT id, rank, leg_odd_ids, combined_odds, win_probability,
               edge_pct, analysis, pipeline_run_time AS generated_at
        FROM mlb_parlay_recommendations
        WHERE recommendation_date = CURRENT_DATE
        ORDER BY rank ASC
        """,
    )
    recs = [dict(r) for r in cur.fetchall()]

    if not recs:
        cur.close()
        conn.close()
        return []

    # Collect all odd_ids across all recommendations in one batch
    all_odd_ids = list({oid for r in recs for oid in r["leg_odd_ids"]})
    cur.execute(
        """
        SELECT odd_id, player_name, team, opponent, stat, line, direction,
               odds, coverage_pct, p_over, ev_per_unit, trend_score,
               opponent_adjustment, position, game_start_time
        FROM mlb_scored_legs
        WHERE odd_id = ANY(%s)
        """,
        (all_odd_ids,),
    )
    legs_by_oid = {row["odd_id"]: dict(row) for row in cur.fetchall()}

    cur.close()
    conn.close()

    # Populate each recommendation's legs in insertion order
    for rec in recs:
        rec["legs"] = [
            legs_by_oid[oid]
            for oid in rec["leg_odd_ids"]
            if oid in legs_by_oid
        ]
        rec.pop("leg_odd_ids")  # not needed in API response

    return recs


def update_recommendation_analysis(recommendation_id: int, analysis: str) -> None:
    """Set the analysis text on an existing recommendation row."""
    conn = get_conn()
    cur = conn.cursor()
    cur.execute(
        "UPDATE mlb_parlay_recommendations SET analysis = %s WHERE id = %s",
        (analysis, recommendation_id),
    )
    conn.commit()
    cur.close()
    conn.close()


def get_parlay_dashboard_data() -> dict:
    """
    Return parlay recommendation quality analytics for the new Dashboard tab.

    Queries mlb_parlay_recommendations (win/loss tracking) and mlb_scored_legs
    (individual leg performance). Returns last 30 days of data.
    """
    conn = get_conn()
    cur = conn.cursor()

    # ── Summary KPIs ──────────────────────────────────────────────────────────
    cur.execute("""
        SELECT
            COUNT(*)                                                             AS total_parlays,
            COUNT(*) FILTER (WHERE outcome = 'won')                             AS won,
            COUNT(*) FILTER (WHERE outcome = 'lost')                            AS lost,
            COUNT(*) FILTER (WHERE outcome = 'void')                            AS voided,
            COUNT(*) FILTER (WHERE outcome = 'pending')                         AS pending,
            ROUND(
                100.0 * COUNT(*) FILTER (WHERE outcome = 'won') /
                NULLIF(COUNT(*) FILTER (WHERE outcome IN ('won','lost')), 0),
                1
            )                                                                    AS parlay_win_rate,
            ROUND(AVG(total_odds::numeric) FILTER (WHERE outcome IN ('won','lost')), 0) AS avg_odds
        FROM mlb_parlay_recommendations_v2
        WHERE run_date >= CURRENT_DATE - INTERVAL '30 days'
    """)
    summary = dict(cur.fetchone())

    # ── Daily performance (last 14 days) ─────────────────────────────────────
    cur.execute("""
        SELECT
            run_date::text                                                       AS recommendation_date,
            COUNT(*)                                                             AS total,
            COUNT(*) FILTER (WHERE outcome = 'won')                             AS won,
            COUNT(*) FILTER (WHERE outcome = 'lost')                            AS lost,
            COUNT(*) FILTER (WHERE outcome = 'void')                            AS voided,
            ROUND(
                100.0 * COUNT(*) FILTER (WHERE outcome = 'won') /
                NULLIF(COUNT(*) FILTER (WHERE outcome IN ('won','lost')), 0),
                1
            )                                                                    AS win_rate
        FROM mlb_parlay_recommendations_v2
        WHERE run_date >= CURRENT_DATE - INTERVAL '14 days'
        GROUP BY run_date
        ORDER BY run_date DESC
    """)
    daily_performance = [dict(r) for r in cur.fetchall()]

    # ── Leg win rate by stat (last 30 days, mlb_scored_legs) ─────────────────
    cur.execute("""
        SELECT
            stat,
            COUNT(*)                                                             AS total,
            COUNT(*) FILTER (WHERE result = 'won')                              AS won,
            COUNT(*) FILTER (WHERE result = 'lost')                             AS lost,
            ROUND(
                100.0 * COUNT(*) FILTER (WHERE result = 'won') /
                NULLIF(COUNT(*) FILTER (WHERE result IN ('won','lost')), 0),
                1
            )                                                                    AS win_rate,
            ROUND(AVG(composite_score)::numeric, 1)                             AS avg_score,
            ROUND(AVG(coverage_pct)::numeric, 1)                                AS avg_coverage
        FROM mlb_scored_legs
        WHERE result IN ('won', 'lost')
          AND run_date::date >= CURRENT_DATE - INTERVAL '30 days'
        GROUP BY stat
        HAVING COUNT(*) >= 5
        ORDER BY win_rate DESC NULLS LAST, total DESC
    """)
    leg_by_stat = [dict(r) for r in cur.fetchall()]

    # ── Score calibration: composite_score bucket vs actual win rate ──────────
    cur.execute("""
        SELECT
            CASE
                WHEN composite_score < 60 THEN '<60'
                WHEN composite_score < 65 THEN '60-65'
                WHEN composite_score < 70 THEN '65-70'
                WHEN composite_score < 75 THEN '70-75'
                ELSE '75+'
            END                                                                  AS score_bucket,
            COUNT(*)                                                             AS total,
            COUNT(*) FILTER (WHERE result = 'won')                              AS won,
            ROUND(
                100.0 * COUNT(*) FILTER (WHERE result = 'won') /
                NULLIF(COUNT(*) FILTER (WHERE result IN ('won','lost')), 0),
                1
            )                                                                    AS win_rate
        FROM mlb_scored_legs
        WHERE result IN ('won', 'lost')
          AND composite_score IS NOT NULL
        GROUP BY score_bucket
        ORDER BY score_bucket
    """)
    score_calibration = [dict(r) for r in cur.fetchall()]

    # ── Top performing legs (min 3 resolved, last 30 days) ───────────────────
    cur.execute("""
        SELECT
            player_name,
            stat,
            COUNT(*)                                                             AS total,
            COUNT(*) FILTER (WHERE result = 'won')                              AS won,
            ROUND(
                100.0 * COUNT(*) FILTER (WHERE result = 'won') /
                NULLIF(COUNT(*) FILTER (WHERE result IN ('won','lost')), 0),
                1
            )                                                                    AS win_rate,
            ROUND(AVG(composite_score)::numeric, 1)                             AS avg_score
        FROM mlb_scored_legs
        WHERE result IN ('won', 'lost')
          AND run_date::date >= CURRENT_DATE - INTERVAL '30 days'
        GROUP BY player_name, stat
        HAVING COUNT(*) >= 3
        ORDER BY win_rate DESC NULLS LAST, total DESC
        LIMIT 10
    """)
    top_legs = [dict(r) for r in cur.fetchall()]

    # ── Recent recommendations (last 20, v2 only) ────────────────────────────
    cur.execute("""
        SELECT
            id,
            run_date::text                     AS recommendation_date,
            rank,
            total_odds                         AS combined_odds,
            ROUND(avg_coverage::numeric, 1)    AS win_probability,
            COALESCE(edge_percent, 0.0)        AS edge_pct,
            outcome                            AS bet_status,
            NULL::text                         AS resolved_at,
            source,
            'v2'                               AS schema_version
        FROM mlb_parlay_recommendations_v2
        ORDER BY run_date DESC, rank ASC
        LIMIT 20
    """)
    recent_recs = [dict(r) for r in cur.fetchall()]
    print(f"[dashboard] Pending parlays: {summary.get('pending', 0)} (v2)")

    cur.close()
    conn.close()

    return {
        "summary":           summary,
        "daily_performance": daily_performance,
        "leg_by_stat":       leg_by_stat,
        "score_calibration": score_calibration,
        "top_legs":          top_legs,
        "recent_recs":       recent_recs,
    }


def get_ml_health_data() -> dict:
    """
    Return ML model health data for the new Training tab.

    Loads feature importance from models/leg_scorer_v2.pkl and queries
    mlb_training_data for calibration drift and data quality.
    """
    import pathlib
    import pickle

    conn = get_conn()
    cur = conn.cursor()

    # ── Model status from pkl file ────────────────────────────────────────────
    model_path = pathlib.Path("models/leg_scorer_v2.pkl")
    model_status: dict = {
        "model_file": str(model_path),
        "exists": model_path.exists(),
        "file_size_kb": None,
        "last_modified": None,
        "feature_count": None,
        "auc": None,
        "samples": None,
    }
    feature_importance: list[dict] = []

    if model_path.exists():
        import datetime as _dt
        stat = model_path.stat()
        model_status["file_size_kb"] = round(stat.st_size / 1024, 1)
        model_status["last_modified"] = _dt.datetime.fromtimestamp(
            stat.st_mtime, tz=_dt.timezone.utc
        ).strftime("%Y-%m-%d %H:%M UTC")
        try:
            with open(model_path, "rb") as f:
                bundle = pickle.load(f)
            clf = bundle.get("model") or bundle.get("clf")
            features = bundle.get("features") or bundle.get("feature_names") or []
            model_status["feature_count"] = len(features)
            model_status["auc"] = bundle.get("auc")
            model_status["samples"] = bundle.get("n_samples") or bundle.get("samples")
            if clf is not None and hasattr(clf, "feature_importances_") and features:
                imp = clf.feature_importances_
                feature_importance = sorted(
                    [{"feature": f, "importance": round(float(v) * 100, 2)}
                     for f, v in zip(features, imp)],
                    key=lambda x: x["importance"],
                    reverse=True,
                )[:15]
        except Exception as e:
            model_status["load_error"] = str(e)

    # ── Calibration drift (training data, last 60 days) ───────────────────────
    cur.execute("""
        SELECT
            CASE
                WHEN coverage_pct < 55 THEN '<55%'
                WHEN coverage_pct < 60 THEN '55-60%'
                WHEN coverage_pct < 65 THEN '60-65%'
                WHEN coverage_pct < 70 THEN '65-70%'
                ELSE '70%+'
            END                                                                  AS bucket,
            COUNT(*)                                                             AS total,
            COUNT(*) FILTER (WHERE result = 'hit')                              AS hits,
            ROUND(
                100.0 * COUNT(*) FILTER (WHERE result = 'hit') / COUNT(*),
                1
            )                                                                    AS actual_hit_rate,
            ROUND(AVG(coverage_pct)::numeric, 1)                                AS avg_predicted,
            ROUND(
                (AVG(coverage_pct) -
                 100.0 * COUNT(*) FILTER (WHERE result = 'hit') / COUNT(*))::numeric,
                1
            )                                                                    AS error_pp
        FROM mlb_training_data
        WHERE coverage_pct IS NOT NULL
          AND result IN ('hit', 'miss')
          AND game_date >= CURRENT_DATE - INTERVAL '60 days'
        GROUP BY bucket
        ORDER BY bucket
    """)
    calibration_drift = [dict(r) for r in cur.fetchall()]

    # ── Data quality (last 14 days) ───────────────────────────────────────────
    cur.execute("""
        SELECT
            game_date,
            COUNT(*)                                                             AS total,
            COUNT(*) FILTER (WHERE result = 'hit')                              AS hits,
            COUNT(*) FILTER (WHERE result = 'miss')                             AS misses,
            COUNT(*) FILTER (WHERE result IS NULL)                              AS pending,
            ROUND(
                100.0 * COUNT(*) FILTER (WHERE result = 'hit') /
                NULLIF(COUNT(*) FILTER (WHERE result IN ('hit','miss')), 0),
                1
            )                                                                    AS hit_rate
        FROM mlb_training_data
        WHERE game_date >= CURRENT_DATE - INTERVAL '14 days'
        GROUP BY game_date
        ORDER BY game_date DESC
    """)
    data_quality = [dict(r) for r in cur.fetchall()]

    # ── Overall training data summary ─────────────────────────────────────────
    cur.execute("""
        SELECT
            COUNT(*)                                                             AS total_samples,
            COUNT(*) FILTER (WHERE result IN ('hit','miss'))                    AS resolved,
            COUNT(*) FILTER (WHERE result IS NULL)                              AS unresolved,
            COUNT(DISTINCT game_date)                                           AS days_covered,
            MIN(game_date)                                                       AS first_date,
            MAX(game_date)                                                       AS last_date,
            ROUND(
                100.0 * COUNT(*) FILTER (WHERE result = 'hit') /
                NULLIF(COUNT(*) FILTER (WHERE result IN ('hit','miss')), 0),
                1
            )                                                                    AS overall_hit_rate
        FROM mlb_training_data
    """)
    training_summary = dict(cur.fetchone())

    cur.close()
    conn.close()

    # ── Retrain triggers ──────────────────────────────────────────────────────
    # Compute days since last model training from file mtime
    retrain_triggers: list[dict] = []
    if model_path.exists():
        import datetime as _dt
        mtime = model_path.stat().st_mtime
        days_since = (_dt.datetime.now().timestamp() - mtime) / 86400
        retrain_triggers.append({
            "trigger": "Days since last retrain",
            "value": f"{days_since:.0f} days",
            "status": "warn" if days_since >= 7 else "ok",
            "threshold": "retrain if ≥ 7 days",
        })
    new_samples = training_summary.get("resolved", 0)
    retrain_triggers.append({
        "trigger": "Total resolved samples",
        "value": f"{new_samples:,}",
        "status": "ok" if new_samples >= 1000 else "warn",
        "threshold": "need ≥ 1000 resolved to retrain",
    })
    auc = model_status.get("auc")
    retrain_triggers.append({
        "trigger": "Current model AUC",
        "value": f"{auc:.4f}" if auc else "unknown",
        "status": "ok" if auc and auc >= 0.80 else "warn",
        "threshold": "warn if AUC < 0.80",
    })

    return {
        "model_status":       model_status,
        "feature_importance": feature_importance,
        "calibration_drift":  calibration_drift,
        "data_quality":       data_quality,
        "training_summary":   training_summary,
        "retrain_triggers":   retrain_triggers,
    }


init_db()
