"""
scripts/backfill_point_in_time_stats.py — Daily point-in-time stat refresh for
the MLB reference schema, feeding mlb_training_data's pt_*/opp_pt_* columns.

Two pieces, meant to run in this order as part of the daily job (see
scripts/daily_reference_refresh.py, which imports and chains both):

  1. refresh_cumulative_tables(cur, day) — incrementally appends one row per
     player who played on `day` to mlb_player_batting_cumulative /
     mlb_player_pitching_cumulative (running season-to-date totals, unique on
     (player_id, game_date)). Reads mlb_player_batting_logs/_pitching_logs
     joined to mlb_games for `day` (already backfilled by the daily job's
     games/logs step, which must run first) plus each player's own most
     recent prior cumulative row, and upserts the new running total. Safe to
     re-run for the same day: the "previous" row is always the latest row
     STRICTLY BEFORE `day`, so re-running never double-counts today's own
     stats into itself.

  2. backfill_training_data_point_in_time(cur, limit=None) — fills
     mlb_training_data.pt_role/pt_*/opp_pt_* for any row missing them, using
     the two cumulative tables above plus mlb_players.primary_position for
     role disambiguation. NOT date-scoped — scans the whole table each run,
     which safely covers both the historical backlog (rows that got
     opp_pitcher_id from the one-time backfill but never got opp_pt_* filled)
     and new rows from today's pipeline run. Cheap after the initial catch-up
     since the target set shrinks to just new rows.

Design note — approximate plate appearances: mlb_player_batting_logs (and
therefore mlb_player_batting_cumulative) never captures plate_appearances or
hit_by_pitch (see SUPABASE_SCHEMA_REFERENCE.md's reference-schema intro — not
available via the box-score API path used by the backfill). pt_obp/pt_k_pct/
pt_bb_pct here use (at_bats + walks) as a PA proxy, which slightly
undercounts true PA (walks/HBP/sac plays) — a known, accepted approximation,
not a bug.

Role disambiguation for stat='strikeouts': the only stat ambiguous between a
batter's own strikeouts and a pitcher's strikeouts-thrown (mirrors the same
ambiguity already handled once in scripts/backfill_training_data.py's
_is_pitcher_prop() and src/pipelines/prop_legs_capture.py's role_map, via
different mechanisms appropriate to their own data). Resolved here via
mlb_players.primary_position = 'P' -> pitcher role, else batter role. Known
limitation: two-way players would need special-casing; none currently active
enough to matter, per the historical backfill. 'hitsAllowed'/'earnedRuns' are
unambiguously pitcher-only stats (no batter equivalent), needing no lookup.

Usage (manual/cron invocation):
    python -m scripts.backfill_point_in_time_stats
    python -m scripts.backfill_point_in_time_stats --date 2026-07-29
    python -m scripts.backfill_point_in_time_stats --dry-run

Environment variables required: DATABASE_URL (same as the rest of the pipeline)
"""
from __future__ import annotations

import argparse
from bisect import bisect_left
from datetime import date, timedelta

from src.utils.db import get_conn

# Stats with no batter equivalent — always pitcher role, no position lookup needed.
_UNAMBIGUOUS_PITCHER_STATS = frozenset({"hitsAllowed", "earnedRuns"})


# ── Step 1: cumulative table refresh ────────────────────────────────────────

def refresh_batting_cumulative(cur, day: date) -> int:
    """Upsert one mlb_player_batting_cumulative row per batter who played on `day`."""
    cur.execute(
        """
        WITH todays AS (
            SELECT b.player_id,
                   COUNT(*)                        AS games,
                   SUM(COALESCE(b.at_bats, 0))      AS at_bats,
                   SUM(COALESCE(b.hits, 0))         AS hits,
                   SUM(COALESCE(b.doubles, 0))      AS doubles,
                   SUM(COALESCE(b.triples, 0))      AS triples,
                   SUM(COALESCE(b.home_runs, 0))    AS home_runs,
                   SUM(COALESCE(b.rbi, 0))          AS rbi,
                   SUM(COALESCE(b.walks, 0))        AS walks,
                   SUM(COALESCE(b.strikeouts, 0))   AS strikeouts,
                   SUM(COALESCE(b.stolen_bases, 0)) AS stolen_bases,
                   SUM(COALESCE(b.total_bases, 0))  AS total_bases
            FROM mlb_player_batting_logs b
            JOIN mlb_games g ON g.game_pk = b.game_pk
            WHERE g.game_date = %(day)s
            GROUP BY b.player_id
        ),
        prev AS (
            SELECT DISTINCT ON (c.player_id)
                   c.player_id, c.games, c.at_bats, c.hits, c.doubles, c.triples,
                   c.home_runs, c.rbi, c.walks, c.strikeouts, c.stolen_bases, c.total_bases
            FROM mlb_player_batting_cumulative c
            WHERE c.game_date < %(day)s
              AND c.player_id IN (SELECT player_id FROM todays)
            ORDER BY c.player_id, c.game_date DESC
        )
        INSERT INTO mlb_player_batting_cumulative
            (player_id, game_date, games, at_bats, hits, doubles, triples,
             home_runs, rbi, walks, strikeouts, stolen_bases, total_bases)
        SELECT
            t.player_id, %(day)s,
            COALESCE(p.games, 0) + t.games,
            COALESCE(p.at_bats, 0) + t.at_bats,
            COALESCE(p.hits, 0) + t.hits,
            COALESCE(p.doubles, 0) + t.doubles,
            COALESCE(p.triples, 0) + t.triples,
            COALESCE(p.home_runs, 0) + t.home_runs,
            COALESCE(p.rbi, 0) + t.rbi,
            COALESCE(p.walks, 0) + t.walks,
            COALESCE(p.strikeouts, 0) + t.strikeouts,
            COALESCE(p.stolen_bases, 0) + t.stolen_bases,
            COALESCE(p.total_bases, 0) + t.total_bases
        FROM todays t
        LEFT JOIN prev p ON p.player_id = t.player_id
        ON CONFLICT (player_id, game_date) DO UPDATE SET
            games = EXCLUDED.games, at_bats = EXCLUDED.at_bats, hits = EXCLUDED.hits,
            doubles = EXCLUDED.doubles, triples = EXCLUDED.triples, home_runs = EXCLUDED.home_runs,
            rbi = EXCLUDED.rbi, walks = EXCLUDED.walks, strikeouts = EXCLUDED.strikeouts,
            stolen_bases = EXCLUDED.stolen_bases, total_bases = EXCLUDED.total_bases
        """,
        {"day": day.isoformat()},
    )
    return cur.rowcount


def refresh_pitching_cumulative(cur, day: date) -> int:
    """Upsert one mlb_player_pitching_cumulative row per pitcher who appeared on `day`."""
    cur.execute(
        """
        WITH todays AS (
            SELECT p.player_id,
                   COUNT(*)                            AS games,
                   SUM(COALESCE(p.innings_pitched, 0))  AS innings_pitched,
                   SUM(COALESCE(p.hits_allowed, 0))     AS hits_allowed,
                   SUM(COALESCE(p.earned_runs, 0))      AS earned_runs,
                   SUM(COALESCE(p.walks_allowed, 0))    AS walks_allowed,
                   SUM(COALESCE(p.strikeouts, 0))       AS strikeouts
            FROM mlb_player_pitching_logs p
            JOIN mlb_games g ON g.game_pk = p.game_pk
            WHERE g.game_date = %(day)s
            GROUP BY p.player_id
        ),
        prev AS (
            SELECT DISTINCT ON (c.player_id)
                   c.player_id, c.games, c.innings_pitched, c.hits_allowed,
                   c.earned_runs, c.walks_allowed, c.strikeouts
            FROM mlb_player_pitching_cumulative c
            WHERE c.game_date < %(day)s
              AND c.player_id IN (SELECT player_id FROM todays)
            ORDER BY c.player_id, c.game_date DESC
        )
        INSERT INTO mlb_player_pitching_cumulative
            (player_id, game_date, games, innings_pitched, hits_allowed,
             earned_runs, walks_allowed, strikeouts)
        SELECT
            t.player_id, %(day)s,
            COALESCE(p.games, 0) + t.games,
            COALESCE(p.innings_pitched, 0) + t.innings_pitched,
            COALESCE(p.hits_allowed, 0) + t.hits_allowed,
            COALESCE(p.earned_runs, 0) + t.earned_runs,
            COALESCE(p.walks_allowed, 0) + t.walks_allowed,
            COALESCE(p.strikeouts, 0) + t.strikeouts
        FROM todays t
        LEFT JOIN prev p ON p.player_id = t.player_id
        ON CONFLICT (player_id, game_date) DO UPDATE SET
            games = EXCLUDED.games, innings_pitched = EXCLUDED.innings_pitched,
            hits_allowed = EXCLUDED.hits_allowed, earned_runs = EXCLUDED.earned_runs,
            walks_allowed = EXCLUDED.walks_allowed, strikeouts = EXCLUDED.strikeouts
        """,
        {"day": day.isoformat()},
    )
    return cur.rowcount


def refresh_cumulative_tables(cur, day: date) -> dict:
    """Refresh both cumulative tables for `day`. Returns a summary dict."""
    n_batting = refresh_batting_cumulative(cur, day)
    n_pitching = refresh_pitching_cumulative(cur, day)
    summary = {"date": day.isoformat(), "batting_rows": n_batting, "pitching_rows": n_pitching}
    print(f"[point_in_time] cumulative refresh: {summary}")
    return summary


# ── Step 2: mlb_training_data point-in-time backfill ────────────────────────

def _resolved_player_id(raw: str | None) -> int | None:
    """Numeric player_id strings copy straight through; anything else is unresolvable."""
    if raw is None:
        return None
    try:
        return int(raw)
    except (ValueError, TypeError):
        return None


def _index_by_player(rows: list[dict]) -> dict[int, tuple[list, list[dict]]]:
    """Group rows by player_id, sorted ascending by game_date, for bisect lookups.

    Returns {player_id: (sorted_dates, sorted_rows)} — two parallel lists so
    bisect_left can search dates directly without a key function.
    """
    grouped: dict[int, list[dict]] = {}
    for r in rows:
        grouped.setdefault(r["player_id"], []).append(r)
    indexed: dict[int, tuple[list, list[dict]]] = {}
    for pid, prows in grouped.items():
        prows.sort(key=lambda r: r["game_date"])
        indexed[pid] = ([r["game_date"] for r in prows], prows)
    return indexed


def _latest_before(index: dict[int, tuple[list, list[dict]]], player_id: int | None, before: date) -> dict | None:
    if player_id is None or player_id not in index:
        return None
    dates, rows = index[player_id]
    i = bisect_left(dates, before)
    return rows[i - 1] if i > 0 else None


def _batting_pt_fields(row: dict) -> dict:
    at_bats = row["at_bats"] or 0
    walks = row["walks"] or 0
    pa_approx = at_bats + walks  # see module docstring — PA/HBP not tracked upstream
    return {
        "pt_games": row["games"],
        "pt_avg": round(row["hits"] / at_bats, 3) if at_bats else None,
        "pt_obp": round((row["hits"] + walks) / pa_approx, 3) if pa_approx else None,
        "pt_slg": round(row["total_bases"] / at_bats, 3) if at_bats else None,
        "pt_ops": (
            round(row["total_bases"] / at_bats + (row["hits"] + walks) / pa_approx, 3)
            if at_bats and pa_approx else None
        ),
        "pt_k_pct": round(row["strikeouts"] / pa_approx, 3) if pa_approx else None,
        "pt_bb_pct": round(walks / pa_approx, 3) if pa_approx else None,
    }


def _pitching_pt_fields(row: dict, prefix: str) -> dict:
    ip = row["innings_pitched"] or 0
    return {
        f"{prefix}_games": row["games"],
        f"{prefix}_era": round(row["earned_runs"] * 9 / ip, 3) if ip else None,
        f"{prefix}_whip": round((row["hits_allowed"] + row["walks_allowed"]) / ip, 3) if ip else None,
        f"{prefix}_k9": round(row["strikeouts"] * 9 / ip, 3) if ip else None,
        f"{prefix}_innings_pitched": ip if ip else None,
    }


def backfill_training_data_point_in_time(cur, limit: int | None = None) -> dict:
    """
    Fill mlb_training_data.resolved_player_id/pt_role/pt_*/opp_pt_* for rows
    missing them. Targets rows never touched (pt_role IS NULL) as well as
    rows with a captured opp_pitcher_id still missing opp_pt_era (the
    historical backlog from before Piece 1 started writing opp_pitcher_id).

    The two fills are independent and handled separately per row: a row can
    need opp_pt_* filled (opp_pitcher_id, resolved against the OPPOSING
    pitcher's cumulative history) without its own player_id being resolvable
    at all. Confirmed live: the current backlog's ~12.2K opp_pt_*-only rows
    almost all carry a pre-Piece-1 SGO-style string player_id (e.g.
    "MICHAEL_MCGREEVY_1_MLB", not an MLB numeric person.id) left over from
    scripts/backfill_training_data.py's original insert — pt_role was
    already resolved for these via the one-time backfill's own name-based
    crosswalk (out of scope to reproduce here), so own-role/pt_* must be
    left untouched for them, but opp_pt_* is independently fillable via the
    already-numeric opp_pitcher_id column and must not be skipped just
    because this script's simple int-cast can't also resolve player_id.

    Loads both cumulative tables and mlb_players.primary_position into memory
    once, then resolves each target row via bisect lookup — avoids one query
    per row against Supabase over the network.
    """
    cur.execute(
        """
        SELECT id, player_id, stat, game_date, opp_pitcher_id, pt_role, opp_pt_era
        FROM mlb_training_data
        WHERE pt_role IS NULL
           OR (opp_pitcher_id IS NOT NULL AND opp_pt_era IS NULL)
        ORDER BY id
        """ + (" LIMIT %(limit)s" if limit else ""),
        {"limit": limit} if limit else {},
    )
    targets = [dict(r) for r in cur.fetchall()]
    if not targets:
        summary = {"targets": 0, "updated": 0, "skipped": 0}
        print(f"[point_in_time] training_data backfill: {summary}")
        return summary

    cur.execute("SELECT * FROM mlb_player_batting_cumulative")
    batting_index = _index_by_player([dict(r) for r in cur.fetchall()])

    cur.execute("SELECT * FROM mlb_player_pitching_cumulative")
    pitching_index = _index_by_player([dict(r) for r in cur.fetchall()])

    cur.execute("SELECT player_id, primary_position FROM mlb_players")
    position_by_player = {r["player_id"]: r["primary_position"] for r in cur.fetchall()}

    n_updated = 0
    n_skipped = 0
    for row in targets:
        fields: dict = {}

        if row["pt_role"] is None:
            pid = _resolved_player_id(row["player_id"])
            if pid is not None:
                stat = row["stat"]
                if stat in _UNAMBIGUOUS_PITCHER_STATS:
                    role = "pitcher"
                elif stat == "strikeouts":
                    role = "pitcher" if position_by_player.get(pid) == "P" else "batter"
                else:
                    role = "batter"

                fields["resolved_player_id"] = pid
                fields["pt_role"] = role
                if role == "batter":
                    prior = _latest_before(batting_index, pid, row["game_date"])
                    if prior:
                        fields.update(_batting_pt_fields(prior))
                else:
                    prior = _latest_before(pitching_index, pid, row["game_date"])
                    if prior:
                        fields.update(_pitching_pt_fields(prior, "pt"))
            # pid is None (legacy non-numeric player_id): no-op, matches the
            # handoff's framing of resolved_player_id as a safety net only —
            # historical rows the one-time backfill already handled via its
            # own name-based crosswalk are out of scope here.

        if row["opp_pitcher_id"] is not None and row["opp_pt_era"] is None:
            opp_prior = _latest_before(pitching_index, row["opp_pitcher_id"], row["game_date"])
            if opp_prior:
                fields.update(_pitching_pt_fields(opp_prior, "opp_pt"))

        if not fields:
            n_skipped += 1
            continue

        set_clause = ", ".join(f"{col} = %({col})s" for col in fields)
        cur.execute(
            f"UPDATE mlb_training_data SET {set_clause} WHERE id = %(id)s",
            {**fields, "id": row["id"]},
        )
        n_updated += 1

    summary = {"targets": len(targets), "updated": n_updated, "skipped": n_skipped}
    print(f"[point_in_time] training_data backfill: {summary}")
    return summary


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--date", default=(date.today() - timedelta(days=1)).isoformat(),
                     help="Date to refresh cumulative tables for (default: yesterday)")
    ap.add_argument("--limit", type=int, default=None,
                     help="Cap the number of mlb_training_data rows backfilled this run")
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    day = date.fromisoformat(args.date)

    conn = get_conn()
    cur = conn.cursor()

    refresh_cumulative_tables(cur, day)
    backfill_training_data_point_in_time(cur, limit=args.limit)

    if args.dry_run:
        conn.rollback()
        print("[point_in_time] DRY RUN — rolled back")
    else:
        conn.commit()
        print("[point_in_time] committed")

    cur.close()
    conn.close()


if __name__ == "__main__":
    main()
