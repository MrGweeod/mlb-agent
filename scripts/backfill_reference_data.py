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
    """
    Per-player battingOrder string ('300') -> slot int (3). None if not in lineup.

    NOTE: this deliberately discards the trailing digit, which is the
    substitution marker. Use _batting_order_raw()/_is_substitute() when you
    need to know whether the player STARTED — see below.
    """
    raw = player.get("battingOrder")
    if raw is None:
        return None
    try:
        return int(str(raw)) // 100
    except (ValueError, TypeError):
        return None


def _batting_order_raw(player: dict) -> str | None:
    """
    The raw per-player battingOrder string, substitution digit intact.

    '300' = started in the 3-spot. '301' = first substitute in that spot,
    '302' = second. The trailing digit is the ONLY place the box score records
    whether a player started, and _batting_slot() throws it away by design
    (integer-dividing by 100), which is why this exists alongside it.
    """
    raw = player.get("battingOrder")
    return str(raw) if raw is not None else None


def _is_substitute(player: dict) -> bool | None:
    """
    True if the player did NOT start.

    The trailing digit of battingOrder is the signal that actually works on
    THIS code path. Two indicators exist in MLB's boxscore and agree on every
    leg checked from 2026-08-12 (30/30) — gameStatus.isSubstitute and the
    trailing digit — but statsapi.boxscore_data(), which get_box_score() wraps,
    returns gameStatus as an EMPTY DICT because the field is outside its
    hardcoded `fields` whitelist (verified live against game 823916). So the
    isSubstitute branch below is dead code on the current fetcher and the digit
    fallback is what runs. It is kept, not deleted, so that this function stays
    correct if the fetcher is ever pointed at the raw
    /api/v1/game/{pk}/boxscore endpoint, which does return gameStatus.

    WHY THIS MATTERS: DraftKings grades pre-live batter props on a must-start
    AND record-a-plate-appearance rule, so a pinch-hitter voids EVEN WITH an
    at-bat. Grading on box-score presence alone is FanDuel's rule and silently
    settles DK voids as wins or losses. On 2026-08-12 that misgraded 8 legs and
    turned three winning parlays (1496, 1498, 1501) into losses.

    Do NOT substitute mlb_scored_legs.lineup_check_status='SCRATCHED' for this.
    It happened to be correct on all 12 cases that day, but it is a PRE-GAME
    inference from a possibly non-final lineup, whereas this is post-game
    ground truth. Grade settled bets from the box score.
    """
    status = player.get("gameStatus") or {}
    if "isSubstitute" in status:
        return bool(status["isSubstitute"])
    raw = _batting_order_raw(player)
    if raw is None:
        return None
    try:
        return int(raw) % 100 != 0
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
                # participation signal).
                #
                # plate_appearances / hit_by_pitch are read through rather than
                # hardcoded to None. On the CURRENT fetcher this is a no-op —
                # statsapi.boxscore_data() omits both (module docstring above is
                # correct; verified live on game 823916), so they stay NULL as
                # they have been for all 38,147 rows. Passing the getters costs
                # nothing and makes the row correct automatically if the fetcher
                # ever moves to the raw /api/v1/game/{pk}/boxscore endpoint,
                # which does return them.
                #
                # This matters because DraftKings' rule is must-start AND
                # record a plate appearance. The must-start half is covered by
                # is_substitute below. For the PA half, at_bats + walks is a
                # sound proxy from what this path DOES return — and in practice
                # every 0-AB case on 2026-08-12 (Walker '502', Springer '802',
                # Lukes '801') was also a substitute, so the sub check catches
                # them regardless.
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
                            batting_order, batting_order_raw, is_substitute,
                            plate_appearances, at_bats, hits, doubles, triples,
                            home_runs, rbi, walks, strikeouts, hit_by_pitch, stolen_bases, total_bases
                        ) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
                        ON CONFLICT (player_id, game_pk) DO UPDATE SET
                            -- Backfill-safe: only fields that were previously
                            -- absent or lossy are refreshed. Everything else
                            -- keeps its original value, preserving the old
                            -- DO NOTHING semantics for existing rows.
                            batting_order_raw = EXCLUDED.batting_order_raw,
                            is_substitute     = EXCLUDED.is_substitute,
                            plate_appearances = COALESCE(mlb_player_batting_logs.plate_appearances,
                                                         EXCLUDED.plate_appearances),
                            hit_by_pitch      = COALESCE(mlb_player_batting_logs.hit_by_pitch,
                                                         EXCLUDED.hit_by_pitch)
                        """,
                        (pid, game_pk, team_id, opp_id, opp_starter,
                         _batting_slot(player), _batting_order_raw(player), _is_substitute(player),
                         batting.get("plateAppearances"), batting.get("atBats"), h, d, t, hr,
                         batting.get("rbi"), batting.get("baseOnBalls"), batting.get("strikeOuts"),
                         batting.get("hitByPitch"), batting.get("stolenBases"), total_bases),
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
