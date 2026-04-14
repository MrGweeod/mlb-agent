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
            logged_at TEXT NOT NULL
        )
    """)

    cur.execute("""
        CREATE TABLE IF NOT EXISTS pitcher_profiles (
            pitcher_id TEXT PRIMARY KEY,
            team_id TEXT,
            era REAL,
            era_rank INTEGER,
            k9 REAL,
            k9_rank INTEGER,
            whip REAL,
            whip_rank INTEGER,
            hand TEXT,
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


def get_player_position(player_id: str, max_age_hours: int = 168) -> str | None:
    """Return cached position for a player, or None if missing/expired (TTL 7 days)."""
    conn = get_conn()
    cur = conn.cursor()
    cur.execute(
        "SELECT position, fetched_at FROM mlb_player_positions WHERE player_id = %s",
        (player_id,)
    )
    row = cur.fetchone()
    cur.close()
    conn.close()
    if row and hours_since(row["fetched_at"]) < max_age_hours:
        return row["position"]
    return None


def set_player_position(player_id: str, position: str, bats: str = None, throws: str = None):
    """Write or update a player's position in the cache."""
    conn = get_conn()
    cur = conn.cursor()
    cur.execute(
        """
        INSERT INTO mlb_player_positions (player_id, position, bats, throws, fetched_at)
        VALUES (%s, %s, %s, %s, %s)
        ON CONFLICT (player_id) DO UPDATE
            SET position = EXCLUDED.position,
                bats = EXCLUDED.bats,
                throws = EXCLUDED.throws,
                fetched_at = EXCLUDED.fetched_at
        """,
        (player_id, position, bats, throws, now_utc())
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

    Marks in_parlay=True for any leg whose odd_id appears in parlay_odd_ids.
    Idempotent: skips silently if rows already exist for run_date.
    Returns the number of rows inserted (0 on a skip).
    """
    if not legs:
        return 0
    conn = get_conn()
    cur = conn.cursor()
    cur.execute("SELECT COUNT(*) FROM mlb_scored_legs WHERE run_date = %s", (run_date,))
    if cur.fetchone()["count"] > 0:
        cur.close()
        conn.close()
        return 0
    ts = now_utc()
    psycopg2.extras.execute_values(
        cur,
        """
        INSERT INTO mlb_scored_legs
            (run_date, player_name, team, opponent, stat, line, direction, odds,
             coverage_pct, p_over, ev_per_unit, trend_pass, trend_score,
             opponent_adjustment, position, in_parlay, logged_at)
        VALUES %s
        """,
        [
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
                ts,
            )
            for leg in legs
            if leg.get("stat") and leg.get("player_name")  # skip totals legs (no player)
        ],
    )
    conn.commit()
    inserted = cur.rowcount
    cur.close()
    conn.close()
    return inserted


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


init_db()
