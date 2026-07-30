"""
src/pipelines/prop_legs_capture.py — Full prop-line capture into
mlb_prop_legs_history, for every player with a posted line (not just
currently-qualified players) plus game-level lines (moneyline/spread/total).

This is an explicitly SEPARATE calibration data source for a ground-up
rebuild — see the module-level notes below and ARCHITECTURE_DECISIONS.md.
It does NOT write to, read from for scoring, or otherwise touch
mlb_scored_legs, mlb_parlay_recommendations_v2/_enriched, or
mlb_training_data. No cross-contamination of production/shadow win-rate
reporting anywhere.

Zero new SGO API calls: capture_full_prop_lines() takes the SAME sgo_games/
all_sgo_props/schedule data that run_pipeline()'s existing Step 2/3 already
fetched — it's called from inside run_pipeline(), not a new standalone
fetch. Wired in for the 9 AM morning run only (skip_resolution=False) — see
main.py.

Player-role disambiguation for 'strikeouts': get_player_props() (existing,
untouched, still used by production) normalizes SGO's 'batting_strikeouts'
and 'pitching_strikeouts' raw statIDs to the same internal 'strikeouts'
stat name and does not preserve which prefix matched — the same ambiguity
already found and worked around once this session elsewhere in the
codebase (mlb_scored_legs/mlb_training_data: pitcher props use lines like
5.5+, batter props use 0.5). Rather than modify get_player_props() (a
function the live production pipeline depends on, out of scope to touch),
_build_odd_id_role_map() below independently scans the same game's raw
odds dict by key prefix and matches back to each leg's odd_id — fully
additive, no change to any existing function's behavior.

game_pk / player_id / team_id resolution: matches SGO events to MLB
schedule entries by (away_abbr, home_abbr) team-pair (same pattern
dashboard_api/shape.py's _build_games() already uses), giving real MLB
team_id/game_pk straight from the schedule already fetched at Step 2 of
run_pipeline() — no separate lookup call. player_id comes from
get_player_props()'s own already-resolved statsapi.lookup_player() result
(reused, not re-derived). mlb_teams/mlb_players/mlb_games rows are
upserted ON CONFLICT DO NOTHING (fills gaps only, never overwrites richer
data the reference-schema daily refresh may also be writing) so this
capture job works standalone regardless of whether that other, still-
uncommitted piece of work is ever deployed.
"""
from __future__ import annotations

import json
from datetime import datetime, timezone

from src.utils.db import get_conn

_TEAM_ABBR: dict[str, str] = {
    "New York Yankees": "NYY", "Boston Red Sox": "BOS", "Toronto Blue Jays": "TOR",
    "Baltimore Orioles": "BAL", "Tampa Bay Rays": "TB", "Chicago White Sox": "CWS",
    "Cleveland Guardians": "CLE", "Detroit Tigers": "DET", "Kansas City Royals": "KC",
    "Minnesota Twins": "MIN", "Houston Astros": "HOU", "Los Angeles Angels": "LAA",
    "Oakland Athletics": "OAK", "Athletics": "OAK", "Seattle Mariners": "SEA", "Texas Rangers": "TEX",
    "Atlanta Braves": "ATL", "Miami Marlins": "MIA", "New York Mets": "NYM",
    "Philadelphia Phillies": "PHI", "Washington Nationals": "WSH", "Chicago Cubs": "CHC",
    "Cincinnati Reds": "CIN", "Milwaukee Brewers": "MIL", "Pittsburgh Pirates": "PIT",
    "St. Louis Cardinals": "STL", "Arizona Diamondbacks": "ARI", "Colorado Rockies": "COL",
    "Los Angeles Dodgers": "LAD", "San Diego Padres": "SD", "San Francisco Giants": "SF",
}

_PLAYER_STAT_TARGETS = {
    # internal stat name (from get_player_props) -> capture as this many directions
    "hits":        {"over", "under"},
    "strikeouts":  {"over"},          # batter Ks — Over 0.5 only, per the handoff's target list
    "totalBases":  {"over", "under"},
}
# pitcher_strikeouts direction not restricted by the handoff — capture both
_PITCHER_STRIKEOUT_DIRECTIONS = {"over", "under"}

SPORTSBOOK = "draftkings"


def _abbr(team_full_name: str) -> str:
    return _TEAM_ABBR.get(team_full_name, team_full_name[:3].upper())


def _build_odd_id_role_map(game: dict) -> dict[str, str]:
    """oddID -> 'batter'/'pitcher', from the raw batting_/pitching_ key prefix."""
    odds = game.get("odds", {}) or {}
    role_map: dict[str, str] = {}
    for key, prop in odds.items():
        odd_id = (prop or {}).get("oddID")
        if not odd_id:
            continue
        if key.startswith("batting_"):
            role_map[odd_id] = "batter"
        elif key.startswith("pitching_"):
            role_map[odd_id] = "pitcher"
    return role_map


def _match_game_pk(sgo_game: dict, team_pair_to_schedule: dict[tuple[str, str], dict]) -> dict | None:
    # SGO's names.short is already an abbreviation-style string (e.g. "NYY") —
    # used as-is, matching the proven pattern in dashboard_api/shape.py's
    # _build_games(). Do NOT run it back through _abbr() (that function only
    # knows how to convert FULL team names, e.g. "New York Yankees" -> "NYY";
    # feeding it an already-short string risks a silent mismatch).
    teams = sgo_game.get("teams", {})
    away_short = (teams.get("away", {}).get("names") or {}).get("short", "")
    home_short = (teams.get("home", {}).get("names") or {}).get("short", "")
    return team_pair_to_schedule.get((away_short, home_short))


def _extract_game_lines(sgo_game: dict, sched_game: dict) -> list[dict]:
    """Game-level legs: moneyline, spread (run line), total. market_scope='game'."""
    odds = sgo_game.get("odds", {}) or {}
    home_id = sched_game.get("home_id")
    away_id = sched_game.get("away_id")

    specs = [
        # (odd_key, stat, direction, line_field)
        ("points-home-game-ml-home", "moneyline", "home", None),
        ("points-away-game-ml-away", "moneyline", "away", None),
        ("points-home-game-sp-home", "spread", "home", "spread"),
        ("points-away-game-sp-away", "spread", "away", "spread"),
        ("points-all-game-ou-over",  "total", "over", "overUnder"),
        ("points-all-game-ou-under", "total", "under", "overUnder"),
    ]

    legs = []
    for odd_key, stat, direction, line_field in specs:
        mkt = odds.get(odd_key)
        if not mkt:
            continue
        dk = (mkt.get("byBookmaker", {}) or {}).get(SPORTSBOOK, {})
        if not dk.get("available"):
            continue
        line = float(dk.get(line_field)) if line_field and dk.get(line_field) is not None else 0.0
        odds_val = dk.get("odds")
        if odds_val is None:
            continue
        legs.append({
            "player_id": None,
            "market_scope": "game",
            "player_role": None,
            "game_pk": sched_game.get("game_id"),
            "stat": stat,
            "line": line,
            "direction": direction,
            "odds": int(str(odds_val).replace("+", "")),
        })
    return legs


def _extract_player_legs(all_sgo_props_for_game: list[dict], game_pk: int, role_map: dict[str, str]) -> list[dict]:
    legs = []
    for prop in all_sgo_props_for_game:
        stat = prop.get("stat")
        direction = prop.get("direction")
        line = prop.get("standard_line")
        odds_val = prop.get("standard_odds")
        player_id = prop.get("player_id")
        odd_id = prop.get("odd_id")

        if stat not in _PLAYER_STAT_TARGETS or player_id is None or line is None or odds_val is None:
            continue

        if stat == "strikeouts":
            role = role_map.get(odd_id)
            if role == "pitcher":
                if direction not in _PITCHER_STRIKEOUT_DIRECTIONS:
                    continue
            elif role == "batter":
                if direction not in _PLAYER_STAT_TARGETS["strikeouts"]:
                    continue
            else:
                continue  # couldn't resolve role — skip rather than guess
        else:
            role = "batter"  # hits/totalBases are batter-only stats in this pipeline
            if direction not in _PLAYER_STAT_TARGETS[stat]:
                continue

        legs.append({
            "player_id": player_id,
            "market_scope": "player",
            "player_role": role,
            "game_pk": game_pk,
            "stat": stat,
            "line": float(line),
            "direction": direction,
            "odds": int(str(odds_val).replace("+", "")),
            "player_name": prop.get("player_name"),
        })
    return legs


def _ensure_team(cur, team_id: int, name: str) -> None:
    if not team_id:
        return
    cur.execute(
        """
        INSERT INTO mlb_teams (team_id, abbreviation, name, updated_at)
        VALUES (%s, %s, %s, now())
        ON CONFLICT (team_id) DO NOTHING
        """,
        (team_id, _abbr(name), name),
    )


def _ensure_game(cur, sched_game: dict) -> None:
    game_pk = sched_game.get("game_id")
    if not game_pk:
        return
    cur.execute(
        """
        INSERT INTO mlb_games (game_pk, game_date, game_start_time, home_team_id, away_team_id, updated_at)
        VALUES (%s, %s, %s, %s, %s, now())
        ON CONFLICT (game_pk) DO NOTHING
        """,
        (game_pk, sched_game.get("game_date"), sched_game.get("game_datetime"),
         sched_game.get("home_id"), sched_game.get("away_id")),
    )


def _ensure_player(cur, player_id: int, full_name: str) -> None:
    if not player_id:
        return
    cur.execute(
        """
        INSERT INTO mlb_players (player_id, full_name, updated_at)
        VALUES (%s, %s, now())
        ON CONFLICT (player_id) DO NOTHING
        """,
        (player_id, full_name or ""),
    )


def _upsert_leg(cur, leg: dict, now_iso: str) -> None:
    odds_history_entry = json.dumps({"odds": leg["odds"], "at": now_iso})

    if leg["market_scope"] == "player":
        conflict_target = "(player_id, game_pk, stat, line, direction, sportsbook)"
    else:
        # Must repeat the partial index's WHERE predicate here -- Postgres
        # only matches ON CONFLICT against a partial unique index if the
        # predicate is restated in the conflict clause itself, not inferred
        # from the column list alone (confirmed live: omitting this raised
        # "there is no unique or exclusion constraint matching the ON
        # CONFLICT specification" on every single game-scope upsert).
        conflict_target = "(game_pk, stat, line, direction, sportsbook) WHERE player_id IS NULL"

    cur.execute(
        f"""
        INSERT INTO mlb_prop_legs_history (
            player_id, game_pk, stat, line, direction, sportsbook,
            market_scope, player_role,
            first_seen_odds, first_seen_at, last_recorded_odds, last_recorded_at, odds_history
        ) VALUES (
            %(player_id)s, %(game_pk)s, %(stat)s, %(line)s, %(direction)s, %(sportsbook)s,
            %(market_scope)s, %(player_role)s,
            %(odds)s, %(now)s, %(odds)s, %(now)s, %(history)s::jsonb
        )
        ON CONFLICT {conflict_target} DO UPDATE SET
            last_recorded_odds = EXCLUDED.last_recorded_odds,
            last_recorded_at = EXCLUDED.last_recorded_at,
            odds_history = mlb_prop_legs_history.odds_history || EXCLUDED.odds_history,
            updated_at = now()
        """,
        {
            "player_id": leg["player_id"],
            "game_pk": leg["game_pk"],
            "stat": leg["stat"],
            "line": leg["line"],
            "direction": leg["direction"],
            "sportsbook": SPORTSBOOK,
            "market_scope": leg["market_scope"],
            "player_role": leg["player_role"],
            "odds": leg["odds"],
            "now": now_iso,
            "history": f"[{odds_history_entry}]",
        },
    )


def capture_full_prop_lines(sgo_games: list[dict], all_sgo_props: list[dict], schedule: list[dict]) -> dict:
    """
    Capture every player-with-a-posted-line prop (hits/strikeouts/totalBases,
    at the specific directions the handoff targeted) plus game-level lines
    (moneyline/spread/total) into mlb_prop_legs_history.

    Args:
        sgo_games: raw SGO event list, as already fetched by run_pipeline()
            Step 3 (get_todays_games()) — not re-fetched here.
        all_sgo_props: parsed player props for ALL those games, as already
            built by run_pipeline() Step 3's get_player_props() loop, BEFORE
            _filter_useless_props() narrows it to the production betting
            pool — full capture is the point of this table, so the
            production filter must not be applied upstream of this call.
        schedule: MLB schedule for today, as already fetched by
            run_pipeline() Step 2 (get_schedule()) — used only for
            game_pk/home_id/away_id/game_datetime, not re-fetched.

    Returns a summary dict for logging. Exceptions are caught per-game so one
    bad game's odds structure can't take down the rest of the morning run —
    this table is a calibration side-channel, not something worth failing
    the production pipeline over.
    """
    team_pair_to_schedule = {}
    for g in schedule:
        away = _abbr(g.get("away_name", ""))
        home = _abbr(g.get("home_name", ""))
        team_pair_to_schedule[(away, home)] = g

    # Group already-parsed player props back by their source game so we can
    # attach the right game_pk to each — get_player_props() doesn't carry
    # game_pk in its output, but odd_id is unique enough to regroup here by
    # re-deriving each prop's owning game via the role map's odd_id keys.
    now_iso = datetime.now(timezone.utc).isoformat()
    conn = get_conn()
    cur = conn.cursor()

    n_games_matched = 0
    n_games_unmatched = 0
    n_game_lines = 0
    n_player_legs = 0
    errors: list[str] = []

    for sgo_game in sgo_games:
        try:
            sched_game = _match_game_pk(sgo_game, team_pair_to_schedule)
            if not sched_game:
                n_games_unmatched += 1
                continue
            n_games_matched += 1

            _ensure_team(cur, sched_game.get("home_id"), sched_game.get("home_name", ""))
            _ensure_team(cur, sched_game.get("away_id"), sched_game.get("away_name", ""))
            _ensure_game(cur, sched_game)

            game_pk = sched_game.get("game_id")
            role_map = _build_odd_id_role_map(sgo_game)
            game_odd_ids = set(role_map.keys())

            props_for_this_game = [p for p in all_sgo_props if p.get("odd_id") in game_odd_ids]

            for leg in _extract_game_lines(sgo_game, sched_game):
                _upsert_leg(cur, leg, now_iso)
                n_game_lines += 1

            for leg in _extract_player_legs(props_for_this_game, game_pk, role_map):
                _ensure_player(cur, leg["player_id"], leg.get("player_name", ""))
                _upsert_leg(cur, leg, now_iso)
                n_player_legs += 1

            conn.commit()
        except Exception as exc:
            conn.rollback()
            errors.append(f"{sgo_game.get('eventID', '?')}: {exc}")

    cur.close()
    conn.close()

    summary = {
        "games_matched": n_games_matched,
        "games_unmatched": n_games_unmatched,
        "game_lines_captured": n_game_lines,
        "player_legs_captured": n_player_legs,
        "errors": errors,
    }
    print(f"[prop_legs_capture] {summary}")
    return summary


# ── Resolution ───────────────────────────────────────────────────────────
#
# Reconciles pending mlb_prop_legs_history rows against
# mlb_player_batting_logs / mlb_player_pitching_logs / mlb_games once the
# underlying game is Final. Takes a cursor (not its own connection) so it
# composes into scripts/daily_reference_refresh.py's existing single
# transaction, immediately after that job backfills yesterday's game logs —
# the exact moment the data this needs becomes available. Writes ONLY to
# mlb_prop_legs_history — never mlb_scored_legs, mlb_parlay_recommendations_
# v2/_enriched, mlb_training_data, or anything a dashboard blends production/
# shadow performance from.

_PLAYER_STAT_COLUMN = {
    ("batter", "hits"): ("mlb_player_batting_logs", "hits"),
    ("batter", "strikeouts"): ("mlb_player_batting_logs", "strikeouts"),
    ("batter", "totalBases"): ("mlb_player_batting_logs", "total_bases"),
    ("pitcher", "strikeouts"): ("mlb_player_pitching_logs", "strikeouts"),
}


def _resolve_player_leg(cur, leg: dict) -> tuple[str, float | None]:
    table, column = _PLAYER_STAT_COLUMN.get((leg["player_role"], leg["stat"]), (None, None))
    if table is None:
        return "void", None  # unrecognized (player_role, stat) combo — shouldn't happen, defensive only

    cur.execute(
        f"SELECT {column} AS val FROM {table} WHERE player_id = %s AND game_pk = %s",
        (leg["player_id"], leg["game_pk"]),
    )
    row = cur.fetchone()
    if not row or row["val"] is None:
        return "void", None  # player didn't appear in the box score for this game (scratch, DNP, etc.)

    actual = float(row["val"])
    if actual == leg["line"]:
        return "void", actual
    if leg["direction"] == "over":
        return ("won" if actual > leg["line"] else "lost"), actual
    else:
        return ("won" if actual < leg["line"] else "lost"), actual


def _resolve_game_leg(cur, leg: dict) -> tuple[str, float | None]:
    cur.execute(
        "SELECT home_score, away_score FROM mlb_games WHERE game_pk = %s",
        (leg["game_pk"],),
    )
    row = cur.fetchone()
    if not row or row["home_score"] is None or row["away_score"] is None:
        return "void", None

    home_score, away_score = row["home_score"], row["away_score"]

    if leg["stat"] == "total":
        actual = float(home_score + away_score)
        if actual == leg["line"]:
            return "void", actual
        if leg["direction"] == "over":
            return ("won" if actual > leg["line"] else "lost"), actual
        return ("won" if actual < leg["line"] else "lost"), actual

    if leg["stat"] == "moneyline":
        if home_score == away_score:
            return "void", None  # not possible in a completed MLB game, defensive only
        side_won = (home_score > away_score) if leg["direction"] == "home" else (away_score > home_score)
        return ("won" if side_won else "lost"), None

    if leg["stat"] == "spread":
        margin = (home_score - away_score) if leg["direction"] == "home" else (away_score - home_score)
        adjusted = margin + leg["line"]
        if adjusted == 0:
            return "void", float(margin)
        return ("won" if adjusted > 0 else "lost"), float(margin)

    return "void", None


def resolve_prop_legs_history(cur) -> dict:
    """
    Resolve every pending mlb_prop_legs_history row whose game is Final.
    Returns a summary dict. Caller (daily_reference_refresh.py) owns the
    transaction — this function only executes SELECT/UPDATE via the passed
    cursor, no commit/rollback here.
    """
    cur.execute(
        """
        SELECT h.id, h.player_id, h.game_pk, h.stat, h.line, h.direction,
               h.market_scope, h.player_role
        FROM mlb_prop_legs_history h
        JOIN mlb_games g ON g.game_pk = h.game_pk
        WHERE h.result = 'pending'
          AND g.status IN ('Final', 'Game Over', 'Completed Early')
        """
    )
    pending = [dict(r) for r in cur.fetchall()]

    n_won = n_lost = n_void = 0
    for leg in pending:
        if leg["market_scope"] == "player":
            result, actual_value = _resolve_player_leg(cur, leg)
        else:
            result, actual_value = _resolve_game_leg(cur, leg)

        cur.execute(
            """
            UPDATE mlb_prop_legs_history
            SET result = %s, actual_value = %s, resolved_at = now()
            WHERE id = %s
            """,
            (result, actual_value, leg["id"]),
        )
        if result == "won":
            n_won += 1
        elif result == "lost":
            n_lost += 1
        else:
            n_void += 1

    summary = {"resolved": len(pending), "won": n_won, "lost": n_lost, "void": n_void}
    print(f"[prop_legs_resolution] {summary}")
    return summary
