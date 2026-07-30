"""
backfill_reference_data.py — One-time backfill for the MLB reference schema
(mlb_teams, mlb_players, mlb_games, mlb_player_batting_logs,
 mlb_player_pitching_logs), season-to-date from 2026-03-01.

Reuses existing, already-tested helpers from src/apis/mlb_stats.py
(get_schedule, get_box_score) rather than re-implementing API parsing.

Field names below were verified against LIVE statsapi.mlb.com responses
during Session (backfill review), not just against the wrapper's docstrings:
  - side_data["pitchers"] is a list of player_ids in appearance order — the
    first entry is the game's starting pitcher. There is NO "gamesStarted"
    field on the per-player pitching stat dict returned by
    statsapi.boxscore_data() (it isn't in that function's hardcoded `fields`
    whitelist), so the original draft's
    `pitching.get("gamesStarted", 0) == 1` check always evaluated to False.
  - Per-player `battingOrder` (e.g. "300") is present only on players who
    actually appeared in the batting order (starters + subs who entered);
    slot = int(battingOrder) // 100. This DOES let us derive the exact
    lineup slot — the original draft left this NULL as a known gap.
  - `stats.batting` from boxscore_data() does NOT include `plateAppearances`
    or `hitByPitch` (also not in the `fields` whitelist) — the original
    draft's `if batting.get("plateAppearances"):` participation gate was
    always None/falsy, meaning batting logs would never have been inserted
    at all. Fixed to gate on `if batting:` (non-empty dict), which IS a
    reliable participation signal (confirmed empty {} for non-participants).
    plate_appearances/hit_by_pitch are left NULL — not available via this
    API path without extra per-player calls, out of scope for a
    box-score-driven backfill.
  - `opposing_pitcher_id` (FK on mlb_player_batting_logs, not populated by
    the original draft at all) is now set to the other side's starter.
  - mlb_games.home_probable_pitcher_id / away_probable_pitcher_id (FK,
    not populated by the original draft) are set to the actual starters
    for completed historical games — "probable" and "actual" are the same
    pitcher in the overwhelming majority of played games. The daily refresh
    script handles today's/future games differently (real probable pitcher
    via the schedule/lineup endpoints, since the game hasn't been played).
  - pitches_thrown reads `pitching.get("pitchesThrown") or
    pitching.get("numberOfPitches")` — statsapi's own boxscore_data() uses
    this exact fallback order internally; both keys were observed present
    with the same value on real data, but pitchesThrown is preferred to
    match the wrapper's own convention.

FK ordering: mlb_player_batting_logs/mlb_player_pitching_logs both have FK
constraints on player_id AND opposing_pitcher_id -> mlb_players. Both sides'
full rosters are upserted into mlb_players in a first pass, before any log
row (from either side) is inserted, so opposing_pitcher_id never points at
a not-yet-inserted player.

Usage:
    python -m scripts.backfill_reference_data --start 2026-03-01 --end 2026-07-29
    python -m scripts.backfill_reference_data --start 2026-03-01 --end 2026-03-03 --dry-run

Environment variables required: DATABASE_URL (same as the rest of the pipeline)
"""
from __future__ import annotations

import argparse
import time
from datetime import date, timedelta

import requests

from src.apis.mlb_stats import get_schedule, get_box_score, BASE_URL
from src.utils.db import get_conn

SEASON = 2026

_TERMINAL_STATUSES = ("Final", "Game Over", "Completed Early")


# ── Teams ─────────────────────────────────────────────────────────────────

def backfill_teams(cur) -> dict[int, dict]:
    """Fetch all 30 MLB teams and upsert into mlb_teams. Returns {team_id: info}."""
    r = requests.get(f"{BASE_URL}/teams", params={"sportId": 1, "season": SEASON}, timeout=15)
    r.raise_for_status()
    teams = r.json().get("teams", [])

    team_index: dict[int, dict] = {}
    for t in teams:
        team_id = t.get("id")
        if not team_id:
            continue
        division = t.get("division", {}).get("name")
        league = t.get("league", {}).get("name")
        venue = t.get("venue", {})
        cur.execute(
            """
            INSERT INTO mlb_teams (team_id, abbreviation, name, division, league, venue_id, venue_name, updated_at)
            VALUES (%s, %s, %s, %s, %s, %s, %s, now())
            ON CONFLICT (team_id) DO UPDATE SET
                abbreviation = EXCLUDED.abbreviation,
                name = EXCLUDED.name,
                division = EXCLUDED.division,
                league = EXCLUDED.league,
                venue_id = EXCLUDED.venue_id,
                venue_name = EXCLUDED.venue_name,
                updated_at = now()
            """,
            (team_id, t.get("abbreviation"), t.get("name"), division, league,
             venue.get("id"), venue.get("name")),
        )
        team_index[team_id] = t
    print(f"[backfill] mlb_teams: upserted {len(team_index)} teams")
    return team_index


# ── Player upsert (bio info, lazy — only called for newly-seen player_ids) ──

_known_player_ids: set[int] = set()


def _ensure_player(cur, player_id: int, full_name: str, position: str | None, team_id: int | None) -> None:
    if player_id in _known_player_ids:
        return
    cur.execute(
        """
        INSERT INTO mlb_players (player_id, full_name, primary_position, current_team_id, updated_at)
        VALUES (%s, %s, %s, %s, now())
        ON CONFLICT (player_id) DO UPDATE SET
            full_name = EXCLUDED.full_name,
            current_team_id = EXCLUDED.current_team_id,
            updated_at = now()
        """,
        (player_id, full_name, position, team_id),
    )
    _known_player_ids.add(player_id)


# ── Games + box scores ────────────────────────────────────────────────────

def _parse_ip(raw) -> float | None:
    """'6.1' -> 6.333... (6 full innings + 1 out)."""
    if raw is None:
        return None
    try:
        parts = str(raw).split(".")
        full = int(parts[0])
        thirds = int(parts[1]) if len(parts) > 1 else 0
        return round(full + thirds / 3.0, 3)
    except Exception:
        return None


def _starter_id(side_data: dict) -> int | None:
    """First entry of the side's `pitchers` list is the starter (appearance order)."""
    pitchers = side_data.get("pitchers") or []
    if not pitchers:
        return None
    try:
        return int(pitchers[0])
    except (ValueError, TypeError):
        return None


def _batting_slot(player: dict) -> int | None:
    """Per-player battingOrder string ('300') -> slot int (3). None if not in lineup."""
    raw = player.get("battingOrder")
    if raw is None:
        return None
    try:
        return int(str(raw)) // 100
    except (ValueError, TypeError):
        return None


def backfill_date(cur, day: date) -> int:
    """Backfill all completed games for a single date. Returns games processed."""
    games = get_schedule(day.isoformat())
    processed = 0

    for g in games:
        game_pk = g.get("game_id")
        status = g.get("status", "")
        if not game_pk or status not in _TERMINAL_STATUSES:
            continue  # skip in-progress/scheduled/postponed

        home_id = g.get("home_id")
        away_id = g.get("away_id")
        if not home_id or not away_id:
            continue

        box = get_box_score(game_pk)
        if not box:
            print(f"    [warn] no box score for game {game_pk} on {day}")
            continue

        home_data = box.get("home", {})
        away_data = box.get("away", {})
        home_starter = _starter_id(home_data)
        away_starter = _starter_id(away_data)

        # ── Pass 1: upsert every player on BOTH rosters before any log insert,
        # so opposing_pitcher_id (FK -> mlb_players) always resolves. ─────────
        for side_key, team_id in (("home", home_id), ("away", away_id)):
            for _, player in box.get(side_key, {}).get("players", {}).items():
                person = player.get("person", {})
                pid = person.get("id")
                if not pid:
                    continue
                position = player.get("position", {}).get("abbreviation", "")
                _ensure_player(cur, int(pid), person.get("fullName", ""), position, team_id)

        cur.execute(
            """
            INSERT INTO mlb_games (game_pk, game_date, game_start_time, home_team_id, away_team_id,
                                    venue_id, status, home_score, away_score,
                                    home_probable_pitcher_id, away_probable_pitcher_id, updated_at)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, now())
            ON CONFLICT (game_pk) DO UPDATE SET
                status = EXCLUDED.status,
                home_score = EXCLUDED.home_score,
                away_score = EXCLUDED.away_score,
                home_probable_pitcher_id = EXCLUDED.home_probable_pitcher_id,
                away_probable_pitcher_id = EXCLUDED.away_probable_pitcher_id,
                updated_at = now()
            """,
            (game_pk, day.isoformat(), g.get("game_datetime"), home_id, away_id,
             g.get("venue_id"), status, g.get("home_score"), g.get("away_score"),
             home_starter, away_starter),
        )

        # ── Pass 2: batting + pitching logs, both sides ────────────────────
        for side_key, team_id, opp_id, own_starter, opp_starter in (
            ("home", home_id, away_id, home_starter, away_starter),
            ("away", away_id, home_id, away_starter, home_starter),
        ):
            side_data = box.get(side_key, {})

            for _, player in side_data.get("players", {}).items():
                person = player.get("person", {})
                pid = person.get("id")
                if not pid:
                    continue
                pid = int(pid)

                stats = player.get("stats", {})
                batting = stats.get("batting", {})
                pitching = stats.get("pitching", {})

                # Batting log — gate on non-empty batting stats dict (a real
                # participation signal; plateAppearances is not returned by
                # this API path, see module docstring).
                if batting:
                    h = batting.get("hits") or 0
                    d = batting.get("doubles") or 0
                    t = batting.get("triples") or 0
                    hr = batting.get("homeRuns") or 0
                    total_bases = h + d + 2 * t + 3 * hr
                    cur.execute(
                        """
                        INSERT INTO mlb_player_batting_logs (
                            player_id, game_pk, team_id, opponent_team_id, opposing_pitcher_id,
                            batting_order, plate_appearances, at_bats, hits, doubles, triples,
                            home_runs, rbi, walks, strikeouts, hit_by_pitch, stolen_bases, total_bases
                        ) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
                        ON CONFLICT (player_id, game_pk) DO NOTHING
                        """,
                        (pid, game_pk, team_id, opp_id, opp_starter,
                         _batting_slot(player), None, batting.get("atBats"), h, d, t, hr,
                         batting.get("rbi"), batting.get("baseOnBalls"), batting.get("strikeOuts"),
                         None, batting.get("stolenBases"), total_bases),
                    )

                # Pitching log — only if the player recorded any innings
                ip = _parse_ip(pitching.get("inningsPitched"))
                if ip is not None and ip > 0:
                    is_starter = pid == own_starter
                    pitches = pitching.get("pitchesThrown")
                    if pitches is None:
                        pitches = pitching.get("numberOfPitches")
                    cur.execute(
                        """
                        INSERT INTO mlb_player_pitching_logs (
                            player_id, game_pk, team_id, opponent_team_id, is_starter,
                            innings_pitched, hits_allowed, earned_runs, walks_allowed,
                            strikeouts, home_runs_allowed, pitches_thrown
                        ) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
                        ON CONFLICT (player_id, game_pk) DO NOTHING
                        """,
                        (pid, game_pk, team_id, opp_id, is_starter,
                         ip, pitching.get("hits"), pitching.get("earnedRuns"),
                         pitching.get("baseOnBalls"), pitching.get("strikeOuts"),
                         pitching.get("homeRuns"), pitches),
                    )

        processed += 1

    return processed


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--start", default="2026-03-01")
    ap.add_argument("--end", default=date.today().isoformat())
    ap.add_argument("--dry-run", action="store_true",
                     help="Run the full fetch/parse/insert logic but roll back instead of committing.")
    args = ap.parse_args()

    conn = get_conn()
    cur = conn.cursor()

    print("[backfill] Step 1/2: teams")
    backfill_teams(cur)
    if args.dry_run:
        conn.commit()  # teams are safe to keep even in a dry run (idempotent upsert)
    else:
        conn.commit()

    print("[backfill] Step 2/2: games + box scores")
    start = date.fromisoformat(args.start)
    end = date.fromisoformat(args.end)
    day = start
    total_games = 0
    while day <= end:
        if args.dry_run:
            # Each day is its own rolled-back transaction in dry-run mode —
            # clear the in-memory "already inserted" cache so a player whose
            # insert got rolled back on a prior day is re-attempted today
            # instead of silently skipped (which would otherwise violate the
            # opposing_pitcher_id/player_id FK on the log tables).
            _known_player_ids.clear()
        n = backfill_date(cur, day)
        if args.dry_run:
            conn.rollback()
        else:
            conn.commit()
        total_games += n
        print(f"  {day.isoformat()}: {n} games" + ("  [DRY RUN — rolled back]" if args.dry_run else ""))
        day += timedelta(days=1)
        time.sleep(0.3)  # be polite to statsapi.mlb.com

    cur.close()
    conn.close()
    print(f"[backfill] Done. {total_games} games processed, {len(_known_player_ids)} distinct players seen.")


if __name__ == "__main__":
    main()
