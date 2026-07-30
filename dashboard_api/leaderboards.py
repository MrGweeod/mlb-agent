"""
dashboard_api/leaderboards.py — MLB.com-style Hitting/Pitching leaderboard
tables for the Diamond Line dashboard, sourced from the reference schema
(mlb_player_season_batting_stats / mlb_player_season_pitching_stats,
QUALIFIED-PLAYERS-ONLY by design — see backfill_reference_snapshots.py's
module docstring) rather than a live API call.

Column set matches MLB.com's own Hitting/Pitching stat pages exactly, since
those tables were built to capture the same fields.
"""
from src.utils.db import get_conn


def get_hitting_leaderboard(season: int) -> dict:
    conn = get_conn()
    cur = conn.cursor()
    cur.execute("SELECT max(as_of_date) AS d FROM mlb_player_season_batting_stats WHERE season = %s", (season,))
    as_of = cur.fetchone()["d"]
    if as_of is None:
        cur.close()
        conn.close()
        return {"as_of_date": None, "players": []}

    cur.execute(
        """
        SELECT b.player_id, p.full_name AS name, t.abbreviation AS team,
               b.games, b.at_bats, b.runs, b.hits, b.doubles, b.triples,
               b.home_runs, b.rbi, b.walks, b.strikeouts, b.stolen_bases,
               b.caught_stealing, b.avg, b.obp, b.slg, b.ops
        FROM mlb_player_season_batting_stats b
        JOIN mlb_players p ON p.player_id = b.player_id
        LEFT JOIN mlb_teams t ON t.team_id = b.team_id
        WHERE b.season = %s AND b.as_of_date = %s
        ORDER BY b.at_bats DESC NULLS LAST
        """,
        (season, as_of),
    )
    rows = [dict(r) for r in cur.fetchall()]
    cur.close()
    conn.close()

    for r in rows:
        for k in ("avg", "obp", "slg", "ops"):
            if r.get(k) is not None:
                r[k] = round(float(r[k]), 3)

    return {"as_of_date": as_of.isoformat() if hasattr(as_of, "isoformat") else str(as_of), "players": rows}


def get_pitching_leaderboard(season: int) -> dict:
    conn = get_conn()
    cur = conn.cursor()
    cur.execute("SELECT max(as_of_date) AS d FROM mlb_player_season_pitching_stats WHERE season = %s", (season,))
    as_of = cur.fetchone()["d"]
    if as_of is None:
        cur.close()
        conn.close()
        return {"as_of_date": None, "players": []}

    cur.execute(
        """
        SELECT b.player_id, p.full_name AS name, t.abbreviation AS team,
               b.wins, b.losses, b.era, b.games, b.games_started, b.complete_games,
               b.shutouts, b.saves, b.save_opportunities, b.innings_pitched,
               b.hits_allowed, b.runs_allowed, b.earned_runs, b.home_runs_allowed,
               b.hit_batters, b.walks, b.strikeouts, b.whip, b.avg_against
        FROM mlb_player_season_pitching_stats b
        JOIN mlb_players p ON p.player_id = b.player_id
        LEFT JOIN mlb_teams t ON t.team_id = b.team_id
        WHERE b.season = %s AND b.as_of_date = %s
        ORDER BY b.strikeouts DESC NULLS LAST
        """,
        (season, as_of),
    )
    rows = [dict(r) for r in cur.fetchall()]
    cur.close()
    conn.close()

    for r in rows:
        if r.get("innings_pitched") is not None:
            r["innings_pitched"] = float(r["innings_pitched"])
        for k in ("era", "whip", "avg_against"):
            if r.get(k) is not None:
                r[k] = round(float(r[k]), 2)

    return {"as_of_date": as_of.isoformat() if hasattr(as_of, "isoformat") else str(as_of), "players": rows}
