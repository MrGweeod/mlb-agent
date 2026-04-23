#!/usr/bin/env python3
"""
scripts/backfill_training_data.py — Backfill MLB prop training data.

Fetches historical SGO props for a date range, logs them to mlb_training_data,
then resolves outcomes via MLB box scores.

Usage:
    python scripts/backfill_training_data.py --start-date 2026-03-28 --end-date 2026-04-22
    python scripts/backfill_training_data.py --start-date 2026-04-15 --end-date 2026-04-15 --props-only
    python scripts/backfill_training_data.py --start-date 2026-04-15 --end-date 2026-04-22 --resolve-only

Expected mlb_training_data schema (table must already exist in Supabase):
    id SERIAL PRIMARY KEY,
    player_id TEXT,
    player_name TEXT NOT NULL,
    stat TEXT NOT NULL,
    direction TEXT NOT NULL DEFAULT 'over',
    line REAL NOT NULL,
    odds TEXT,
    fair_line REAL,
    odd_id TEXT,
    game_date TEXT NOT NULL,
    game_pk INTEGER,
    coverage_pct REAL,           -- NULL until Phase 2 (ML feature)
    opponent_adjustment REAL,    -- NULL until Phase 2
    trend_score REAL,            -- NULL until Phase 2
    result TEXT,                 -- 'hit', 'miss', 'void', or NULL=unresolved
    actual_stat REAL,
    resolved_at TEXT,
    logged_at TEXT NOT NULL,
    UNIQUE (odd_id)
"""
from __future__ import annotations

import argparse
import sys
import os
from datetime import date, timedelta

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import statsapi
import psycopg2.extras

from src.apis.sportsgameodds import get_todays_games, _SGO_STAT_ID_MAP, _BLOCKED_STAT_IDS, _STAT_NAME_SUFFIX, PROP_STATS
from src.tracker.outcome_resolver import extract_stat_from_boxscore
from src.utils.db import get_conn, now_utc


# Pitcher-only stats — always resolve from pitching sub-dict in box score
_PITCHER_STATS = frozenset({"hitsAllowed", "earnedRuns", "inningsPitched"})
_PITCHER_POSITIONS = frozenset({"SP", "RP", "P", "TWP"})


def _is_pitcher_prop(stat: str, odd_id: str) -> bool:
    """Infer whether this is a pitcher prop from stat name and odd_id."""
    if stat in _PITCHER_STATS:
        return True
    # Strikeouts: SGO oddID contains 'pitching_strikeouts' for pitcher K props
    if stat == "strikeouts" and "pitching" in (odd_id or "").lower():
        return True
    return False


def _get_historical_player_props(game: dict) -> list[dict]:
    """
    Extract player props from a historical SGO game object.

    Identical to sportsgameodds.get_player_props() except it does NOT filter on
    `available: true` — historical games have available=false on all lines since
    the sportsbook has closed betting, but the line/odds data is still valid.

    Does not write to props cache (historical data shouldn't pollute today's cache).
    """
    odds = game.get("odds", {})
    props = []
    directions = [("over", "game-ou-over"), ("under", "game-ou-under")]

    for stat in PROP_STATS:
        api_prefixes = [ak for ak, iv in _SGO_STAT_ID_MAP.items() if iv == stat]
        if not api_prefixes:
            continue
        for direction, key_fragment in directions:
            matches = [
                v for k, v in odds.items()
                if any(k.startswith(p) for p in api_prefixes)
                and "MLB" in k
                and key_fragment in k
            ]
            for prop in matches:
                raw_stat_id = prop.get("statID", "")
                if (raw_stat_id in _BLOCKED_STAT_IDS
                        or "fantasyScore" in raw_stat_id
                        or "fantasy_score" in raw_stat_id):
                    continue

                dk = prop.get("byBookmaker", {}).get("draftkings", {})
                if not dk:
                    continue

                # For historical data, collect ALL lines regardless of available flag.
                # Use the standard line if present, then alt lines.
                all_lines = []
                if dk.get("overUnder"):
                    all_lines.append({
                        "line": float(dk["overUnder"]),
                        "odds": dk.get("odds"),
                        "available": dk.get("available", False),
                    })
                for alt in dk.get("altLines", []):
                    if alt.get("overUnder"):
                        all_lines.append({
                            "line": float(alt["overUnder"]),
                            "odds": alt.get("odds"),
                            "available": alt.get("available", False),
                        })
                if not all_lines:
                    continue
                all_lines.sort(key=lambda x: x["line"])

                normalized_stat = _SGO_STAT_ID_MAP.get(raw_stat_id, raw_stat_id)
                fair_line = prop.get("fairOverUnder")

                # Clean player name from marketName
                _raw_name = prop.get("marketName", "")
                if _raw_name.endswith(" Over/Under"):
                    _raw_name = _raw_name[: -len(" Over/Under")]
                _suffix = _STAT_NAME_SUFFIX.get(normalized_stat, "")
                if _suffix and _raw_name.endswith(_suffix):
                    _raw_name = _raw_name[: -len(_suffix)].strip()

                props.append({
                    "stat":          normalized_stat,
                    "player_id":     prop.get("playerID"),
                    "player_name":   _raw_name,
                    "standard_line": dk.get("overUnder"),
                    "standard_odds": dk.get("odds"),
                    "all_lines":     all_lines,
                    "fair_line":     fair_line,
                    "odd_id":        prop.get("oddID"),
                    "direction":     direction,
                })

    return props


def _build_game_pk_map(date_str: str) -> dict[str, int]:
    """
    Return {team_abbr: game_pk} for all regular-season MLB games on date_str.
    Calls statsapi.get("teams") + statsapi.schedule() once per date.
    """
    try:
        team_id_to_abbr: dict[int, str] = {
            t["id"]: t["abbreviation"]
            for t in statsapi.get("teams", {"sportId": 1}).get("teams", [])
        }
    except Exception as e:
        print(f"  [WARNING] Failed to load team abbreviations: {e}")
        return {}

    result: dict[str, int] = {}
    try:
        for game in statsapi.schedule(date=date_str, sportId=1):
            if game.get("game_type") not in ("R", "F", "D", "L", "W", "C"):
                continue
            home_abbr = team_id_to_abbr.get(game.get("home_id"), "")
            away_abbr = team_id_to_abbr.get(game.get("away_id"), "")
            game_pk = game.get("game_id")
            if home_abbr and away_abbr and game_pk:
                result[home_abbr] = game_pk
                result[away_abbr] = game_pk
    except Exception as e:
        print(f"  [WARNING] Failed to load schedule for {date_str}: {e}")

    return result


def _build_box_score_index(
    box: dict,
) -> dict[str, tuple[dict, str]]:
    """
    Build {player_name_lower: (stats_dict, position)} from a boxscore_data result.

    Uses full name as the lookup key since SGO player_ids are not MLB person IDs.
    Also adds MLB person_id → entry mapping in a secondary dict returned as second value.
    """
    by_name: dict[str, tuple[dict, str]] = {}
    by_id: dict[int, tuple[dict, str]] = {}
    for side in ("away", "home"):
        for _, player in box.get(side, {}).get("players", {}).items():
            person = player.get("person", {})
            pid = person.get("id")
            name = person.get("fullName", "")
            pos = player.get("position", {}).get("abbreviation", "")
            stats = player.get("stats", {})
            entry = (stats, pos)
            if name:
                by_name[name.lower()] = entry
            if pid:
                by_id[int(pid)] = entry
    return by_name, by_id


def insert_props(
    conn,
    date_str: str,
    props: list[dict],
    game_pk: int | None,
) -> int:
    """
    Bulk-insert props into mlb_training_data.
    Skips props without an odd_id or standard_line.
    ON CONFLICT (odd_id) DO NOTHING — safe to re-run.
    Returns number of newly inserted rows.
    """
    if not props:
        return 0

    ts = now_utc()
    rows = []
    for prop in props:
        raw_odd_id = prop.get("odd_id")
        standard_line = prop.get("standard_line")
        if not raw_odd_id or standard_line is None:
            continue
        # Prefix with game_date so the UNIQUE (odd_id) constraint works per-date.
        # SGO reuses the same oddID across dates (e.g. same player/stat key each day),
        # so without this prefix rows from different dates would collide.
        odd_id = f"{date_str}|{raw_odd_id}"
        rows.append((
            str(prop.get("player_id") or ""),
            prop.get("player_name", ""),
            prop.get("stat", ""),
            prop.get("direction", "over"),
            float(standard_line),
            str(prop.get("standard_odds") or ""),
            prop.get("fair_line"),
            odd_id,
            date_str,
            game_pk,
            ts,
        ))

    if not rows:
        return 0

    cur = conn.cursor()
    psycopg2.extras.execute_values(
        cur,
        """
        INSERT INTO mlb_training_data
            (player_id, player_name, stat, direction, line, odds, fair_line,
             odd_id, game_date, game_pk, logged_at)
        VALUES %s
        ON CONFLICT (odd_id) DO NOTHING
        """,
        rows,
    )
    conn.commit()
    n = cur.rowcount
    cur.close()
    return n


def resolve_outcomes_for_date(conn, date_str: str) -> dict:
    """
    Resolve all unresolved training rows for date_str using box scores.

    For each game, fetches one box score then resolves all props in that game.
    Looks up players by full name (case-insensitive) from the box score roster.

    Returns {'hit': int, 'miss': int, 'void': int}
    """
    cur = conn.cursor()
    cur.execute(
        """
        SELECT id, player_id, player_name, stat, direction, line, odd_id, game_pk
        FROM mlb_training_data
        WHERE game_date = %s AND result IS NULL AND game_pk IS NOT NULL
        ORDER BY game_pk, id
        """,
        (date_str,),
    )
    rows = [dict(r) for r in cur.fetchall()]
    cur.close()

    if not rows:
        print(f"    No unresolved rows for {date_str}")
        return {"hit": 0, "miss": 0, "skipped": 0}

    # Group by game_pk — one box score fetch covers all props in that game
    by_game: dict[int, list] = {}
    for row in rows:
        gp = row.get("game_pk")
        if gp:
            by_game.setdefault(int(gp), []).append(row)

    counts = {"hit": 0, "miss": 0, "skipped": 0}
    updates: list[tuple] = []  # (result, actual, resolved_at, row_id)

    for game_pk, game_rows in sorted(by_game.items()):
        print(f"    Resolving game_pk={game_pk} ({len(game_rows)} props)...")
        try:
            box = statsapi.boxscore_data(game_pk)
        except Exception as exc:
            print(f"      Box score unavailable: {exc} — skipping {len(game_rows)} props (left NULL)")
            counts["skipped"] += len(game_rows)
            continue

        by_name, by_id = _build_box_score_index(box)

        for row in game_rows:
            player_name = row.get("player_name", "")
            stat = row.get("stat", "")
            line = float(row.get("line") or 0)
            direction = row.get("direction", "over")
            odd_id = row.get("odd_id", "")

            # Look up player: try name first, then SGO player_id as MLB ID fallback
            entry = by_name.get(player_name.lower())
            if entry is None:
                try:
                    entry = by_id.get(int(row.get("player_id") or 0))
                except (ValueError, TypeError):
                    pass

            if entry is None:
                # Player not in box score (DNP / scratched) — leave result=NULL
                counts["skipped"] += 1
                continue

            p_stats, position = entry

            # Force pitcher routing for pitcher-only stats or pitcher K props
            if _is_pitcher_prop(stat, odd_id) and position not in _PITCHER_POSITIONS:
                position = "SP"

            actual = extract_stat_from_boxscore(p_stats, stat, position)
            if actual is None:
                counts["skipped"] += 1
                continue

            is_hit = (actual > line) if direction == "over" else (actual < line)
            result = "hit" if is_hit else "miss"
            ts = now_utc()
            updates.append((result, actual, ts, row["id"]))
            counts[result] += 1

            dl = "o" if direction == "over" else "u"
            print(f"      {player_name} {stat} {dl}{line}: got {actual:.1f} → {result}")

    # Flush all updates
    if updates:
        cur = conn.cursor()
        for result, actual, resolved_at, row_id in updates:
            cur.execute(
                """
                UPDATE mlb_training_data
                SET result = %s, actual_stat = %s, resolved_at = %s
                WHERE id = %s
                """,
                (result, actual, resolved_at, row_id),
            )
        conn.commit()
        cur.close()

    return counts


def process_date(
    date_str: str,
    conn,
    props_only: bool = False,
    resolve_only: bool = False,
) -> dict:
    """Fetch props + insert + resolve outcomes for one date."""
    totals = {"inserted": 0, "hit": 0, "miss": 0, "void": 0}

    if not resolve_only:
        # Build team_abbr → game_pk map from MLB schedule
        team_to_game_pk = _build_game_pk_map(date_str)
        if not team_to_game_pk:
            print(f"  No MLB schedule found for {date_str} — skipping")
            return totals
        n_games = len(team_to_game_pk) // 2
        print(f"  MLB schedule: {n_games} game(s)")

        # Fetch SGO games and get props
        try:
            sgo_games = get_todays_games(date_str)
        except RuntimeError as e:
            print(f"  SGO error: {e} — skipping date")
            return totals
        print(f"  SGO: {len(sgo_games)} game(s)")

        for game in sgo_games:
            teams = game.get("teams", {})
            # SGO uses names.short for abbreviations (e.g. "HOU", "COL")
            away_abbr = (teams.get("away", {}).get("names") or {}).get("short", "")
            home_abbr = (teams.get("home", {}).get("names") or {}).get("short", "")
            game_pk = team_to_game_pk.get(away_abbr) or team_to_game_pk.get(home_abbr)

            print(f"  Game: {away_abbr} @ {home_abbr} (game_pk={game_pk})")

            try:
                props = _get_historical_player_props(game)
            except Exception as e:
                print(f"    prop extraction error: {e} — skipping")
                continue

            # Dedup by odd_id before inserting
            seen: set[str] = set()
            unique_props = []
            for p in props:
                oid = p.get("odd_id")
                if oid and oid not in seen:
                    seen.add(oid)
                    unique_props.append(p)

            n = insert_props(conn, date_str, unique_props, game_pk)
            totals["inserted"] += n
            print(f"    {len(props)} props ({len(unique_props)} unique odd_ids) → {n} new rows")

    if not props_only:
        print(f"  Resolving outcomes...")
        outcome_counts = resolve_outcomes_for_date(conn, date_str)
        for k, v in outcome_counts.items():
            totals[k] = totals.get(k, 0) + v
        print(f"  Outcomes: {outcome_counts['hit']} hit, {outcome_counts['miss']} miss, {outcome_counts['skipped']} skipped (NULL)")

    return totals


def main():
    parser = argparse.ArgumentParser(
        description="Backfill MLB prop training data for a date range."
    )
    parser.add_argument("--start-date", required=True, help="Start date (YYYY-MM-DD)")
    parser.add_argument("--end-date",   required=True, help="End date   (YYYY-MM-DD)")
    parser.add_argument(
        "--props-only", action="store_true",
        help="Only insert props, skip outcome resolution",
    )
    parser.add_argument(
        "--resolve-only", action="store_true",
        help="Only resolve outcomes for already-inserted rows",
    )
    args = parser.parse_args()

    start = date.fromisoformat(args.start_date)
    end   = date.fromisoformat(args.end_date)
    if start > end:
        print("ERROR: --start-date must be <= --end-date")
        sys.exit(1)

    conn = get_conn()
    grand_totals = {"inserted": 0, "hit": 0, "miss": 0, "skipped": 0}

    current = start
    while current <= end:
        date_str = current.isoformat()
        print(f"\n{'='*60}")
        print(f"  DATE: {date_str}")
        print(f"{'='*60}")

        day_result = process_date(
            date_str, conn,
            props_only=args.props_only,
            resolve_only=args.resolve_only,
        )
        for k, v in day_result.items():
            grand_totals[k] = grand_totals.get(k, 0) + v

        current += timedelta(days=1)

    conn.close()

    print(f"\n{'='*60}")
    print(f"BACKFILL COMPLETE  ({args.start_date} → {args.end_date})")
    print(f"  Props inserted : {grand_totals['inserted']}")
    print(f"  Outcomes       : {grand_totals['hit']} hit  |  {grand_totals['miss']} miss  |  {grand_totals['skipped']} skipped (NULL)")
    print(f"{'='*60}")


if __name__ == "__main__":
    main()
