"""
backfill_reference_snapshots.py — Season-stats (Qualified Players) and
standings+splits snapshot backfill for the MLB reference schema.

Covers the two pieces of Task 1 that backfill_reference_data.py didn't:
  - mlb_player_season_batting_stats / mlb_player_season_pitching_stats
  - mlb_team_standings / mlb_team_standings_splits

Both tables are daily time series (unique on natural key + as_of_date, never
overwritten) — this script inserts ONE snapshot for the given date (default:
today). The functions here are imported by scripts/daily_reference_refresh.py
so the "pull today's snapshot" logic isn't duplicated between the one-time
backfill and the daily cron version.

Qualification (design note): the handoff spec described recomputing
"PA >= 3.1 x team_games_played" / "IP >= 1.0 x team_games_played" ourselves
each day. Verified live against statsapi.mlb.com that `stats=season` for
group=hitting/pitching defaults to `playerPool=QUALIFIED` server-side, and
that this is the exact same computation (confirmed: min PA in the returned
set on a 105-team-games day was 329, vs. 3.1*105=325.5 -- consistent with
MLB's own rounding/rules) that MLB.com's own leaderboards use -- these are
literally the same numbers shown in the screenshots this task was scoped
from. Relying on the API's own `playerPool=QUALIFIED` filter is simpler and
more authoritative than reimplementing the threshold client-side, so that's
what this script does. A new day's call naturally captures newly-qualified
players (no separate "check for new qualifiers" step needed) and, because we
only ever write "today"'s snapshot (never backfill historical as_of_dates
for a newly-qualified player), a player's first row is naturally the day
they first qualified -- matching the "no retroactive backfill" requirement.

Usage:
    python -m scripts.backfill_reference_snapshots
    python -m scripts.backfill_reference_snapshots --date 2026-07-29
    python -m scripts.backfill_reference_snapshots --dry-run

Environment variables required: DATABASE_URL (same as the rest of the pipeline)
"""
from __future__ import annotations

import argparse
from datetime import date

import requests

from src.apis.mlb_stats import BASE_URL
from src.utils.db import get_conn

SEASON_STATS_URL = f"{BASE_URL}/stats"
STANDINGS_URL = f"{BASE_URL}/standings"


def _num(raw) -> float | None:
    """MLB stat strings like '.328', '-.--', '1.58' -> float, or None."""
    if raw is None:
        return None
    s = str(raw).strip()
    if not s or set(s) <= {"-", "."}:
        return None
    try:
        return float(s)
    except ValueError:
        return None


def _int(raw) -> int | None:
    if raw is None:
        return None
    try:
        return int(raw)
    except (ValueError, TypeError):
        return None


def _games_back(raw) -> float | None:
    """gamesBack/wildCardGamesBack: '-' means the leader, i.e. 0.0 -- NOT undefined.
    Unlike a stat like ERA where '-.--' truly means no data, '-' here is a real value.

    wildCardGamesBack specifically can also come back as a literal '+7.0' --
    confirmed live against the standings endpoint -- meaning "holds a wildcard
    spot, this many games clear of the cutoff", the inverse of the plain
    positive "this many games behind the cutoff" case. float('+7.0') == 7.0,
    which silently collapses that distinction. Stored here as a NEGATIVE
    number for the '+' (ahead of the cutoff) case so the two are numerically
    distinguishable -- standings.py's _fmt_gb() reconstructs the '+' display
    from the sign. gamesBack (division) never carries a '+' case (the leader
    is always just '-', per MLB's own convention), so this is a no-op there."""
    if raw is None:
        return None
    s = str(raw).strip()
    if s == "-":
        return 0.0
    if s.startswith("+"):
        val = _num(s[1:])
        return -val if val is not None else None
    return _num(s)


# ── Season batting/pitching stats (Qualified Players leaderboards) ─────────

def backfill_season_batting_stats(cur, as_of: date, season: int) -> int:
    r = requests.get(SEASON_STATS_URL, params={
        "stats": "season", "group": "hitting", "sportId": 1,
        "season": season, "limit": 2000,
    }, timeout=20)
    r.raise_for_status()
    splits = r.json().get("stats", [{}])[0].get("splits", [])

    n = 0
    for sp in splits:
        player = sp.get("player", {})
        pid = player.get("id")
        if not pid:
            continue
        stat = sp.get("stat", {})
        team_id = sp.get("team", {}).get("id")
        cur.execute(
            """
            INSERT INTO mlb_player_season_batting_stats (
                player_id, team_id, season, as_of_date, games, at_bats, plate_appearances, runs, hits,
                doubles, triples, home_runs, rbi, walks, strikeouts, stolen_bases,
                caught_stealing, avg, obp, slg, ops
            ) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
            ON CONFLICT (player_id, season, as_of_date) DO UPDATE SET
                team_id = EXCLUDED.team_id, games = EXCLUDED.games, at_bats = EXCLUDED.at_bats,
                plate_appearances = EXCLUDED.plate_appearances,
                runs = EXCLUDED.runs, hits = EXCLUDED.hits, doubles = EXCLUDED.doubles,
                triples = EXCLUDED.triples, home_runs = EXCLUDED.home_runs, rbi = EXCLUDED.rbi,
                walks = EXCLUDED.walks, strikeouts = EXCLUDED.strikeouts,
                stolen_bases = EXCLUDED.stolen_bases, caught_stealing = EXCLUDED.caught_stealing,
                avg = EXCLUDED.avg, obp = EXCLUDED.obp, slg = EXCLUDED.slg, ops = EXCLUDED.ops
            """,
            (int(pid), team_id, season, as_of.isoformat(), stat.get("gamesPlayed"),
             stat.get("atBats"), stat.get("plateAppearances"), stat.get("runs"), stat.get("hits"), stat.get("doubles"),
             stat.get("triples"), stat.get("homeRuns"), stat.get("rbi"), stat.get("baseOnBalls"),
             stat.get("strikeOuts"), stat.get("stolenBases"), stat.get("caughtStealing"),
             _num(stat.get("avg")), _num(stat.get("obp")), _num(stat.get("slg")), _num(stat.get("ops"))),
        )
        n += 1
    print(f"[snapshots] mlb_player_season_batting_stats: {n} qualified hitters as of {as_of}")
    return n


def backfill_season_pitching_stats(cur, as_of: date, season: int) -> int:
    r = requests.get(SEASON_STATS_URL, params={
        "stats": "season", "group": "pitching", "sportId": 1,
        "season": season, "limit": 2000,
    }, timeout=20)
    r.raise_for_status()
    splits = r.json().get("stats", [{}])[0].get("splits", [])

    n = 0
    for sp in splits:
        player = sp.get("player", {})
        pid = player.get("id")
        if not pid:
            continue
        stat = sp.get("stat", {})
        team_id = sp.get("team", {}).get("id")
        pitches_thrown = stat.get("pitchesThrown")
        if pitches_thrown is None:
            pitches_thrown = stat.get("numberOfPitches")
        cur.execute(
            """
            INSERT INTO mlb_player_season_pitching_stats (
                player_id, team_id, season, as_of_date, wins, losses, era, games,
                games_started, complete_games, shutouts, saves, save_opportunities,
                innings_pitched, hits_allowed, runs_allowed, earned_runs,
                home_runs_allowed, hit_batters, walks, strikeouts, whip, avg_against
            ) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
            ON CONFLICT (player_id, season, as_of_date) DO UPDATE SET
                team_id = EXCLUDED.team_id, wins = EXCLUDED.wins, losses = EXCLUDED.losses,
                era = EXCLUDED.era, games = EXCLUDED.games, games_started = EXCLUDED.games_started,
                complete_games = EXCLUDED.complete_games, shutouts = EXCLUDED.shutouts,
                saves = EXCLUDED.saves, save_opportunities = EXCLUDED.save_opportunities,
                innings_pitched = EXCLUDED.innings_pitched, hits_allowed = EXCLUDED.hits_allowed,
                runs_allowed = EXCLUDED.runs_allowed, earned_runs = EXCLUDED.earned_runs,
                home_runs_allowed = EXCLUDED.home_runs_allowed, hit_batters = EXCLUDED.hit_batters,
                walks = EXCLUDED.walks, strikeouts = EXCLUDED.strikeouts, whip = EXCLUDED.whip,
                avg_against = EXCLUDED.avg_against
            """,
            (int(pid), team_id, season, as_of.isoformat(), stat.get("wins"), stat.get("losses"),
             _num(stat.get("era")), stat.get("gamesPitched") or stat.get("gamesPlayed"),
             stat.get("gamesStarted"), stat.get("completeGames"), stat.get("shutouts"),
             stat.get("saves"), stat.get("saveOpportunities"), _num(stat.get("inningsPitched")),
             stat.get("hits"), stat.get("runs"), stat.get("earnedRuns"), stat.get("homeRuns"),
             stat.get("hitBatsmen"), stat.get("baseOnBalls"), stat.get("strikeOuts"),
             _num(stat.get("whip")), _num(stat.get("avg"))),
        )
        n += 1
    print(f"[snapshots] mlb_player_season_pitching_stats: {n} qualified pitchers as of {as_of}")
    return n


# ── Standings + splits ──────────────────────────────────────────────────────

_SPLIT_TYPE_MAP = {
    "home": "home", "away": "away", "left": "vs_lhp", "right": "vs_rhp",
    "lastTen": "last_ten", "extraInning": "extra_innings", "oneRun": "one_run",
    "day": "day", "night": "night", "grass": "grass", "turf": "turf",
}


def backfill_standings(cur, as_of: date, season: int) -> tuple[int, int]:
    r = requests.get(STANDINGS_URL, params={
        "leagueId": "103,104", "season": season, "date": as_of.isoformat(),
        "standingsTypes": "regularSeason",
    }, timeout=15)
    r.raise_for_status()
    records = r.json().get("records", [])

    n_teams = 0
    n_splits = 0
    for div_record in records:
        for tr in div_record.get("teamRecords", []):
            team_id = tr.get("team", {}).get("id")
            if not team_id:
                continue

            games_back = tr.get("gamesBack")
            wcgb = tr.get("wildCardGamesBack")
            cur.execute(
                """
                INSERT INTO mlb_team_standings (
                    team_id, as_of_date, wins, losses, win_pct, division_rank,
                    games_back, wcgb, runs_scored, runs_allowed, run_diff, streak
                ) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
                ON CONFLICT (team_id, as_of_date) DO UPDATE SET
                    wins = EXCLUDED.wins, losses = EXCLUDED.losses, win_pct = EXCLUDED.win_pct,
                    division_rank = EXCLUDED.division_rank, games_back = EXCLUDED.games_back,
                    wcgb = EXCLUDED.wcgb, runs_scored = EXCLUDED.runs_scored,
                    runs_allowed = EXCLUDED.runs_allowed, run_diff = EXCLUDED.run_diff,
                    streak = EXCLUDED.streak
                """,
                (team_id, as_of.isoformat(), tr.get("wins"), tr.get("losses"),
                 _num(tr.get("winningPercentage")), _int(tr.get("divisionRank")),
                 _games_back(games_back), _games_back(wcgb), tr.get("runsScored"), tr.get("runsAllowed"),
                 tr.get("runDifferential"), (tr.get("streak") or {}).get("streakCode")),
            )
            n_teams += 1

            records_block = tr.get("records", {})
            split_rows: list[tuple[str, int, int, float | None]] = []

            for sr in records_block.get("splitRecords", []):
                mapped = _SPLIT_TYPE_MAP.get(sr.get("type"))
                if mapped:
                    split_rows.append((mapped, sr.get("wins"), sr.get("losses"), _num(sr.get("pct"))))

            for dr in records_block.get("divisionRecords", []):
                dname = dr.get("division", {}).get("name", "")
                for suffix, label in (("East", "vs_east"), ("Central", "vs_central"), ("West", "vs_west")):
                    if dname.endswith(suffix):
                        split_rows.append((label, dr.get("wins"), dr.get("losses"), _num(dr.get("pct"))))
                        break

            for lr in records_block.get("leagueRecords", []):
                lname = lr.get("league", {}).get("name", "")
                label = "vs_al" if "American" in lname else "vs_nl" if "National" in lname else None
                if label:
                    split_rows.append((label, lr.get("wins"), lr.get("losses"), _num(lr.get("pct"))))

            for split_type, wins, losses, pct in split_rows:
                if wins is None or losses is None:
                    continue
                cur.execute(
                    """
                    INSERT INTO mlb_team_standings_splits (team_id, as_of_date, split_type, wins, losses, pct)
                    VALUES (%s,%s,%s,%s,%s,%s)
                    ON CONFLICT (team_id, as_of_date, split_type) DO UPDATE SET
                        wins = EXCLUDED.wins, losses = EXCLUDED.losses, pct = EXCLUDED.pct
                    """,
                    (team_id, as_of.isoformat(), split_type, wins, losses, pct),
                )
                n_splits += 1

    print(f"[snapshots] mlb_team_standings: {n_teams} teams, mlb_team_standings_splits: {n_splits} rows as of {as_of}")
    return n_teams, n_splits


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--date", default=date.today().isoformat())
    ap.add_argument("--season", type=int, default=None)
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    as_of = date.fromisoformat(args.date)
    season = args.season or as_of.year

    conn = get_conn()
    cur = conn.cursor()

    backfill_season_batting_stats(cur, as_of, season)
    backfill_season_pitching_stats(cur, as_of, season)
    backfill_standings(cur, as_of, season)

    if args.dry_run:
        conn.rollback()
        print("[snapshots] DRY RUN — rolled back")
    else:
        conn.commit()
        print("[snapshots] committed")

    cur.close()
    conn.close()


if __name__ == "__main__":
    main()
