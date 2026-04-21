"""
outcome_resolver.py — Resolve outcomes for scored legs and parlays.

Two resolution paths:
  1. resolve_all_legs(run_date) — box-score-based, groups by game_pk, 1 API
     call per game (efficient). Use this for bulk resolution of mlb_scored_legs.

  2. resolve_recommendations() — game-log-based, resolves mlb_recommendation_legs
     tied to parlay records. Kept for parlay win/loss aggregation.

Run standalone:
    python -m src.tracker.outcome_resolver 2026-04-21        # one date
    python -m src.tracker.outcome_resolver                    # all pending recs + scored legs

Environment variables required: DATABASE_URL (via .env or Railway)
"""
from __future__ import annotations

import re
import sys
from datetime import datetime

import statsapi

from src.apis.mlb_stats import get_batter_game_log
from src.utils.db import get_conn, now_utc
from src.utils.odds_math import parlay_odds

# ── Stat extraction from box score ───────────────────────────────────────────

# Map internal SGO stat key → batting stat field in statsapi boxscore_data
_BATTING_FIELD: dict[str, str] = {
    "hits":        "hits",
    "rbi":         "rbi",
    "homeRuns":    "homeRuns",
    "stolenBases": "stolenBases",
    "runsScored":  "runs",
    "walks":       "baseOnBalls",
    # strikeouts for batters resolved separately (vs pitcher strikeouts)
}

_PITCHER_POSITIONS = frozenset({"SP", "RP", "P", "TWP"})


def extract_stat_from_boxscore(
    player_stats: dict,
    stat: str,
    position: str = "",
) -> float | None:
    """
    Extract a single stat value from a player's boxscore stats dict.

    player_stats is the ``stats`` dict from:
      boxscore_data['away']['players']['ID{n}']['stats']

    It has two sub-dicts:
      - 'batting': hits, doubles, triples, homeRuns, rbi, baseOnBalls,
                   strikeOuts, stolenBases, runs, atBats, leftOnBase
      - 'pitching': strikeOuts, earnedRuns, inningsPitched, hits,
                    baseOnBalls, homeRuns, ...

    Args:
        player_stats: The 'stats' dict for one player from boxscore_data.
        stat:         Internal SGO stat key (e.g. 'hits', 'strikeouts').
        position:     Player's position abbreviation (e.g. 'SP', 'LF').
                      Used to route 'strikeouts' to pitching vs batting.

    Returns:
        Float stat value, or None if the stat or player data is missing.
    """
    batting  = player_stats.get("batting",  {})
    pitching = player_stats.get("pitching", {})

    # Total bases: hits + doubles + 2×triples + 3×homeRuns
    # (MLB API 'hits' includes doubles/triples/HRs so: TB = hits + d + 2t + 3hr)
    if stat == "totalBases":
        h  = batting.get("hits")
        d  = batting.get("doubles")
        t  = batting.get("triples")
        hr = batting.get("homeRuns")
        if any(v is None for v in (h, d, t, hr)):
            return None
        return float(h + d + 2 * t + 3 * hr)

    # Strikeouts: route to pitching for SP/RP, batting for all field positions
    if stat == "strikeouts":
        if position in _PITCHER_POSITIONS:
            val = pitching.get("strikeOuts")
        else:
            val = batting.get("strikeOuts")
        return float(val) if val is not None else None

    # Innings pitched: "6.1" means 6 full innings + 1 out = 6⅓ innings
    if stat == "inningsPitched":
        val = pitching.get("inningsPitched")
        if val is None:
            return None
        try:
            parts = str(val).split(".")
            full   = int(parts[0])
            thirds = int(parts[1]) if len(parts) > 1 else 0
            return float(full) + thirds / 3.0
        except Exception:
            return None

    # Hits allowed (pitcher stat)
    if stat == "hitsAllowed":
        val = pitching.get("hits")
        return float(val) if val is not None else None

    # Earned runs (pitcher stat)
    if stat == "earnedRuns":
        val = pitching.get("earnedRuns")
        return float(val) if val is not None else None

    # Standard batting stats
    field = _BATTING_FIELD.get(stat)
    if field:
        val = batting.get(field)
        return float(val) if val is not None else None

    return None


def _build_player_stats_index(box: dict) -> dict[int, dict]:
    """
    Build a {player_id: stats_dict} index from a boxscore_data result.

    Covers both away and home rosters. The stats dict has 'batting' and
    'pitching' sub-dicts as returned by statsapi.boxscore_data().
    """
    index: dict[int, dict] = {}
    for side in ("away", "home"):
        for key, player in box.get(side, {}).get("players", {}).items():
            person = player.get("person", {})
            pid = person.get("id")
            if pid:
                index[int(pid)] = player.get("stats", {})
    return index


def _batch_commit(updates: list[tuple]) -> None:
    """
    Commit a batch of (result, actual_value, leg_id) updates to mlb_scored_legs.
    """
    if not updates:
        return
    conn = get_conn()
    cur  = conn.cursor()
    for result, actual, leg_id in updates:
        cur.execute(
            "UPDATE mlb_scored_legs SET result = %s, actual_value = %s WHERE id = %s",
            (result, actual, leg_id),
        )
    conn.commit()
    cur.close()
    conn.close()


# ── Box-score resolver (primary path) ────────────────────────────────────────

def resolve_all_legs(run_date: str, verbose: bool = True) -> dict:
    """
    Resolve all unresolved scored legs for *run_date* using box scores.

    Fetches one boxscore per game (not one per player), making it 10-30×
    faster than the game-log approach for a full day's slate.

    Args:
        run_date: 'YYYY-MM-DD' date string matching mlb_scored_legs.run_date.
        verbose:  Print progress to stdout.

    Returns:
        {'won': int, 'lost': int, 'void': int, 'total': int}
    """
    conn = get_conn()
    cur  = conn.cursor()
    cur.execute(
        "SELECT * FROM mlb_scored_legs "
        "WHERE run_date = %s AND (result IS NULL OR result = 'unresolvable') "
        "ORDER BY game_pk, id",
        (run_date,),
    )
    legs = [dict(r) for r in cur.fetchall()]
    cur.close()
    conn.close()

    if not legs:
        if verbose:
            print(f"[RESOLVER] No pending legs for {run_date}.")
        return {"won": 0, "lost": 0, "void": 0, "total": 0}

    if verbose:
        print(f"[RESOLVER] Fetching {len(legs)} pending legs from {run_date}...")

    # Group by game_pk — one box score fetch covers all players in that game
    by_game: dict[int, list] = {}
    no_game: list = []
    for leg in legs:
        gp = leg.get("game_pk")
        if gp:
            by_game.setdefault(int(gp), []).append(leg)
        else:
            no_game.append(leg)

    counts = {"won": 0, "lost": 0, "void": 0}
    pending: list[tuple] = []
    batch_size = 10

    for game_pk, game_legs in sorted(by_game.items()):
        if verbose:
            print(f"[RESOLVER] Processing game {game_pk} ({len(game_legs)} legs)...")

        try:
            box = statsapi.boxscore_data(game_pk)
        except Exception as exc:
            print(f"  [RESOLVER] boxscore fetch failed for {game_pk}: {exc} — voiding legs")
            for leg in game_legs:
                pending.append(("void", None, leg["id"]))
                counts["void"] += 1
            continue

        player_index = _build_player_stats_index(box)

        for leg in game_legs:
            player_id_raw = leg.get("player_id")
            stat          = leg.get("stat", "")
            line          = float(leg.get("line") or 0)
            direction     = leg.get("direction", "over")
            position      = leg.get("position", "")
            name          = leg.get("player_name", "?")

            try:
                player_id = int(player_id_raw) if player_id_raw else None
            except (ValueError, TypeError):
                player_id = None

            if not player_id:
                pending.append(("void", None, leg["id"]))
                counts["void"] += 1
                if verbose:
                    print(f"  {name}: no player_id → VOID")
                continue

            p_stats = player_index.get(player_id)
            if p_stats is None:
                # Player not in box score — scratched, injured, or DNP
                pending.append(("void", None, leg["id"]))
                counts["void"] += 1
                if verbose:
                    print(f"  {name}: not in boxscore → VOID (DNP/scratched)")
                continue

            actual = extract_stat_from_boxscore(p_stats, stat, position)
            if actual is None:
                pending.append(("void", None, leg["id"]))
                counts["void"] += 1
                if verbose:
                    print(f"  {name} {stat}: extraction failed → VOID")
                continue

            result = "won" if (actual > line if direction == "over" else actual < line) else "lost"
            pending.append((result, actual, leg["id"]))
            counts[result] += 1

            if verbose:
                dl = "u" if direction == "under" else "o"
                flag = " [in_parlay]" if leg.get("in_parlay") else ""
                print(f"  {name} {stat} {dl}{line}: got {actual:.1f} → {result.upper()}{flag}")

            # Batch commit every 10 updates to avoid holding a long transaction
            if len(pending) >= batch_size:
                _batch_commit(pending)
                pending.clear()

    # Void legs without a game_pk
    for leg in no_game:
        pending.append(("void", None, leg["id"]))
        counts["void"] += 1

    # Flush remainder
    _batch_commit(pending)

    total = sum(counts.values())
    if verbose:
        print(
            f"\n[RESOLVER] Complete: "
            f"{counts['won']} won, {counts['lost']} lost, {counts['void']} void "
            f"({total} total)"
        )
    return {**counts, "total": total}


# ── Stat map for the game-log path (parlay resolver) ─────────────────────────

STAT_MAP: dict[str, str] = {
    "hits":        "hits",
    "totalBases":  "totalBases",
    "rbi":         "rbi",
    "homeRuns":    "homeRuns",
    "baseOnBalls": "baseOnBalls",
    "stolenBases": "stolenBases",
    "runs":        "runs",
    "strikeOuts":  "strikeOuts",
    "doubles":     "doubles",
    "triples":     "triples",
    # SGO-normalised keys stored in mlb_scored_legs.stat
    "strikeouts":  "strikeOuts",
    "walks":       "baseOnBalls",
}

_STAT_LABELS: dict[str, str] = {}


# ── Helpers for the game-log path ─────────────────────────────────────────────

def _clean_player_name(player_name: str, stat: str) -> str:
    if "+" in stat:
        label = " + ".join(_STAT_LABELS.get(p, p.title()) for p in stat.split("+"))
    else:
        label = _STAT_LABELS.get(stat, stat.title())
    suffix = " " + label
    if player_name.endswith(suffix):
        return player_name[: -len(suffix)]
    return player_name


def _name_to_mlb_id(player_name: str) -> int | None:
    try:
        results = statsapi.lookup_player(player_name, season=datetime.now().year)
        if results:
            return results[0]["id"]
    except Exception:
        pass
    return None


def _calc_stat(game: dict, stat: str) -> float | None:
    field = STAT_MAP.get(stat)
    if not field:
        return None
    val = game.get("stat", {}).get(field)
    return float(val) if val is not None else None


def _find_game_on_date(games: list, target_date_str: str) -> dict | None:
    for game in games:
        if game.get("date") == target_date_str:
            return game
    return None


def _clear_player_cache(player_name: str, stat: str) -> None:
    clean_name = _clean_player_name(player_name, stat)
    mlb_id = _name_to_mlb_id(clean_name)
    if not mlb_id:
        return
    conn = get_conn()
    cur  = conn.cursor()
    cur.execute("DELETE FROM mlb_player_game_logs WHERE player_id = %s", (str(mlb_id),))
    conn.commit()
    cur.close()
    conn.close()


def _resolve_leg(
    player_name: str,
    stat: str,
    line: float,
    game_date: str,
    direction: str = "over",
    player_id: int | None = None,
) -> tuple[str, float | None]:
    """
    Resolve a single leg via the per-player game-log API.

    Returns (result, actual_value) where result is 'won', 'lost',
    'void', or 'unresolvable'.
    """
    if re.match(r"^[A-Z]{2,3}$", player_name.strip()):
        return "void", None  # team total — no player stat

    mlb_id = player_id
    if not mlb_id:
        clean_name = _clean_player_name(player_name, stat)
        mlb_id = _name_to_mlb_id(clean_name)
    if not mlb_id:
        return "unresolvable", None

    season = int(game_date[:4])
    games  = get_batter_game_log(mlb_id, season)
    if not games:
        return "unresolvable", None

    game = _find_game_on_date(games, game_date)
    if not game:
        return "void", None  # player found but didn't play

    actual = _calc_stat(game, stat)
    if actual is None:
        return "unresolvable", None

    result = "won" if (actual > line if direction == "over" else actual < line) else "lost"
    return result, actual


# ── Recommendation resolver ───────────────────────────────────────────────────

def resolve_recommendations(verbose: bool = True) -> None:
    """
    Find all pending recommended parlays and resolve their legs.

    Uses the per-player game-log approach, which also handles the parlay
    won/lost/void aggregation and bet-payout tracking.
    """
    conn = get_conn()
    cur  = conn.cursor()
    cur.execute("SELECT * FROM mlb_recommendations WHERE status = 'pending'")
    pending = cur.fetchall()
    cur.close()
    conn.close()

    if not pending:
        if verbose:
            print("No pending recommendations to resolve.")
        return

    if verbose:
        print(f"Resolving {len(pending)} pending recommendation(s)...\n")

    for rec in pending:
        rec_id   = rec["id"]
        rec_date = rec["date"]

        if verbose:
            print(f"Recommendation #{rec_id} — {rec_date} — {rec['parlay_odds']}")

        conn = get_conn()
        cur  = conn.cursor()
        cur.execute(
            "SELECT * FROM mlb_recommendation_legs WHERE recommendation_id = %s", (rec_id,)
        )
        legs = cur.fetchall()
        cur.close()
        conn.close()

        for leg in legs:
            _clear_player_cache(leg["player_name"], leg["stat"])

        any_lost = False
        any_unresolvable = False
        void_count = 0

        for leg in legs:
            result, actual = _resolve_leg(
                leg["player_name"], leg["stat"], leg["line"], rec_date,
                leg.get("direction", "over"),
            )

            conn = get_conn()
            cur  = conn.cursor()
            cur.execute(
                "UPDATE mlb_recommendation_legs SET result = %s, actual_value = %s WHERE id = %s",
                (result, actual, leg["id"]),
            )
            conn.commit()
            cur.close()
            conn.close()

            if verbose:
                actual_str = f"{actual:.1f}" if actual is not None else "N/A"
                team_str   = f" ({leg['team']})" if leg.get("team") else ""
                dl         = "u" if leg.get("direction") == "under" else "o"
                print(f"  {leg['player_name']}{team_str} {leg['stat']} {dl}{leg['line']}: "
                      f"got {actual_str} → {result.upper()}")

            if result == "lost":
                any_lost = True
            elif result == "void":
                void_count += 1
            elif result == "unresolvable":
                any_unresolvable = True

        if any_lost:
            status = "lost"
        elif any_unresolvable:
            status = "pending"
        elif void_count == len(legs):
            status = "void"
        else:
            status = "won"

        if void_count > 0 and status != "pending":
            conn = get_conn()
            cur  = conn.cursor()
            cur.execute(
                "SELECT odds FROM mlb_recommendation_legs "
                "WHERE recommendation_id = %s AND result != 'void'",
                (rec_id,),
            )
            active_odds = [r["odds"] for r in cur.fetchall() if r.get("odds")]
            cur.close()
            conn.close()
            new_odds = None
            if active_odds:
                try:
                    new_odds = parlay_odds(active_odds)
                    if verbose:
                        print(f"  [Voided {void_count} leg(s)] Adjusted odds: {new_odds}")
                except Exception:
                    pass
        else:
            new_odds = None

        conn = get_conn()
        cur  = conn.cursor()
        if new_odds:
            cur.execute(
                "UPDATE mlb_recommendations SET status = %s, parlay_odds = %s WHERE id = %s",
                (status, new_odds, rec_id),
            )
        else:
            cur.execute(
                "UPDATE mlb_recommendations SET status = %s WHERE id = %s",
                (status, rec_id),
            )
        conn.commit()
        cur.close()
        conn.close()

        if verbose and status != "pending":
            icon = "✓" if status == "won" else "✗"
            print(f"  [{icon}] Parlay {status.upper()}\n")


# ── Bet tracker ───────────────────────────────────────────────────────────────

def log_placed_bet(recommendation_id: int, stake: float, final_odds: str, notes: str = "") -> int:
    """Record a placed real-money bet linked to a recommendation."""
    conn = get_conn()
    cur  = conn.cursor()
    cur.execute(
        """
        INSERT INTO mlb_parlays (date, recommendation_id, stake, final_odds, notes, status, created_at)
        VALUES (
            (SELECT date FROM mlb_recommendations WHERE id = %s),
            %s, %s, %s, %s, 'pending', %s
        )
        RETURNING id
        """,
        (recommendation_id, recommendation_id, stake, final_odds, notes, now_utc()),
    )
    bet_id = cur.fetchone()["id"]
    conn.commit()
    cur.close()
    conn.close()
    return bet_id


def resolve_placed_bets(verbose: bool = True) -> None:
    """Settle placed bets based on already-resolved recommendation outcomes."""
    conn = get_conn()
    cur  = conn.cursor()
    cur.execute(
        """
        SELECT p.*, r.status as rec_status, r.parlay_odds as rec_odds
        FROM mlb_parlays p
        JOIN mlb_recommendations r ON p.recommendation_id = r.id
        WHERE p.status = 'pending' AND r.status != 'pending'
        """
    )
    pending_bets = cur.fetchall()
    cur.close()
    conn.close()

    if not pending_bets:
        if verbose:
            print("No placed bets to settle.")
        return

    for bet in pending_bets:
        if bet["rec_status"] == "won":
            from src.utils.odds_math import american_to_decimal
            payout = round(bet["stake"] * american_to_decimal(bet["final_odds"]), 2)
            status = "won"
        else:
            payout = 0.0
            status = "lost"

        conn = get_conn()
        cur  = conn.cursor()
        cur.execute(
            "UPDATE mlb_parlays SET status = %s, payout = %s WHERE id = %s",
            (status, payout, bet["id"]),
        )
        conn.commit()
        cur.close()
        conn.close()

        if verbose:
            icon = "✓" if status == "won" else "✗"
            print(f"  [{icon}] Bet #{bet['id']} {status.upper()} — "
                  f"stake ${bet['stake']:.2f} → payout ${payout:.2f}")


# ── Scored-leg resolver (game-log fallback) ───────────────────────────────────

def resolve_scored_legs(verbose: bool = True) -> None:
    """
    Resolve unresolved mlb_scored_legs via the per-player game-log API.

    Kept as a fallback for legs that lack a game_pk. For full-date resolution
    use resolve_all_legs() instead — it is much faster (1 API call per game).
    """
    conn = get_conn()
    cur  = conn.cursor()
    cur.execute(
        "SELECT * FROM mlb_scored_legs WHERE result IS NULL OR result = 'unresolvable' "
        "ORDER BY run_date, id"
    )
    unresolved = [dict(r) for r in cur.fetchall()]
    cur.close()
    conn.close()

    if not unresolved:
        if verbose:
            print("No unresolved scored legs.")
        return

    if verbose:
        print(f"Resolving {len(unresolved)} scored leg(s) via game-log fallback...")

    seen_players: set[tuple] = set()
    for leg in unresolved:
        key = (leg["player_name"], leg["stat"])
        if key not in seen_players:
            seen_players.add(key)
            _clear_player_cache(leg["player_name"], leg["stat"])

    resolved = 0
    pending: list[tuple] = []
    for leg in unresolved:
        result, actual = _resolve_leg(
            leg["player_name"], leg["stat"], leg["line"], leg["run_date"],
            leg.get("direction", "over"), leg.get("player_id"),
        )
        pending.append((result, actual, leg["id"]))
        resolved += 1

        if verbose:
            actual_str = f"{actual:.1f}" if actual is not None else "N/A"
            team_str   = f" ({leg['team']})" if leg.get("team") else ""
            flag       = " [in_parlay]" if leg.get("in_parlay") else ""
            dl         = "u" if leg.get("direction") == "under" else "o"
            print(f"  {leg['player_name']}{team_str} {leg['stat']} {dl}{leg['line']}: "
                  f"got {actual_str} → {result.upper()}{flag}")

        if len(pending) >= 10:
            _batch_commit(pending)
            pending.clear()

    _batch_commit(pending)
    if verbose:
        print(f"\n  Resolved {resolved} scored leg(s).")


# ── Entry point ───────────────────────────────────────────────────────────────

if __name__ == "__main__":
    # Usage:
    #   python -m src.tracker.outcome_resolver 2026-04-21   # box-score resolver for one date
    #   python -m src.tracker.outcome_resolver               # run all resolvers (no date filter)
    if len(sys.argv) > 1:
        run_date = sys.argv[1]
        resolve_all_legs(run_date)
    else:
        resolve_recommendations()
        resolve_placed_bets()
        resolve_scored_legs()
