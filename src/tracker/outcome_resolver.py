"""
outcome_resolver.py — Resolve outcomes for all recommended parlays.

Run this the morning after games complete. It checks box scores for every
pending recommendation leg and marks each won/lost — regardless of whether
the user placed a bet. This is the data source for model calibration.

Also provides a separate bet tracking function for placed bets.
"""
from __future__ import annotations

import re
import time
from datetime import datetime

import statsapi

from src.apis.mlb_stats import get_batter_game_log
from src.utils.db import get_conn, now_utc
from src.utils.odds_math import parlay_odds

STAT_MAP: dict[str, str] = {
    "hits": "hits",
    "totalBases": "totalBases",
    "rbi": "rbi",
    "homeRuns": "homeRuns",
    "baseOnBalls": "baseOnBalls",
    "stolenBases": "stolenBases",
    "runs": "runs",
    "strikeOuts": "strikeOuts",
    "doubles": "doubles",
    "triples": "triples",
    # SGO-normalised keys (stored in mlb_scored_legs.stat)
    "strikeouts": "strikeOuts",
    "walks": "baseOnBalls",
}

# TODO: populate with MLB prop display names matching SGO market name suffixes
_STAT_LABELS: dict[str, str] = {}


def _clean_player_name(player_name: str, stat: str) -> str:
    """
    Strip the SGO stat label suffix from a stored player_name.
    TODO: verify MLB SGO market name format matches NBA pattern before relying on this.
    """
    if "+" in stat:
        label = " + ".join(_STAT_LABELS.get(p, p.title()) for p in stat.split("+"))
    else:
        label = _STAT_LABELS.get(stat, stat.title())
    suffix = " " + label
    if player_name.endswith(suffix):
        return player_name[: -len(suffix)]
    return player_name


# ── Helpers ──────────────────────────────────────────────────────────────────

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


def _clear_player_cache(player_name: str, stat: str):
    # TODO: replace player ID lookup with statsapi equivalent once mlb_stats.py is wired up
    clean_name = _clean_player_name(player_name, stat)
    mlb_id = _name_to_mlb_id(clean_name)
    if not mlb_id:
        return
    conn = get_conn()
    cur = conn.cursor()
    cur.execute("DELETE FROM mlb_player_game_logs WHERE player_id = %s", (str(mlb_id),))
    conn.commit()
    cur.close()
    conn.close()


def _resolve_leg(player_name: str, stat: str, line: float, game_date: str,
                 direction: str = "over", player_id: int | None = None) -> tuple[str, float | None]:
    """
    Returns (result, actual_value) where result is 'won', 'lost', 'void', or 'unresolvable'.

    direction: 'over' (won when actual > line) or 'under' (won when actual < line).
    A tie (actual == line) is always 'lost' — neither over nor under wins on the number.

    Team total legs (player_name is a 2–3 uppercase-letter abbreviation like 'NYM' or 'LAD')
    are voided immediately — they have no player log and would otherwise block resolution.
    """
    if re.match(r'^[A-Z]{2,3}$', player_name.strip()):
        return "void", None  # team total leg — no player stat to resolve

    mlb_id = player_id
    if not mlb_id:
        clean_name = _clean_player_name(player_name, stat)
        mlb_id = _name_to_mlb_id(clean_name)
    if not mlb_id:
        return "unresolvable", None

    season = int(game_date[:4])
    games = get_batter_game_log(mlb_id, season)
    if not games:
        return "unresolvable", None

    game = _find_game_on_date(games, game_date)
    if not game:
        return "void", None  # player found but didn't play — leg is voided, not lost

    actual = _calc_stat(game, stat)
    if actual is None:
        return "unresolvable", None

    result = "won" if (actual > line if direction == "over" else actual < line) else "lost"
    return result, actual


# ── Recommendation resolver (runs automatically every morning) ────────────────

def resolve_recommendations(verbose: bool = True) -> None:
    """
    Find all pending recommended parlays and resolve their legs from box scores.
    This is the primary data collection loop for model calibration.
    """
    conn = get_conn()
    cur = conn.cursor()
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
        rec_id = rec["id"]
        rec_date = rec["date"]

        if verbose:
            print(f"Recommendation #{rec_id} — {rec_date} — {rec['parlay_odds']}")

        conn = get_conn()
        cur = conn.cursor()
        cur.execute(
            "SELECT * FROM mlb_recommendation_legs WHERE recommendation_id = %s", (rec_id,)
        )
        legs = cur.fetchall()
        cur.close()
        conn.close()

        # Clear cached game logs so we get fresh box score data
        for leg in legs:
            _clear_player_cache(leg["player_name"], leg["stat"])

        any_lost = False
        any_unresolvable = False
        void_count = 0

        for leg in legs:
            result, actual = _resolve_leg(
                leg["player_name"], leg["stat"], leg["line"], rec_date,
                leg.get("direction", "over")
            )

            conn = get_conn()
            cur = conn.cursor()
            cur.execute(
                "UPDATE mlb_recommendation_legs SET result = %s, actual_value = %s WHERE id = %s",
                (result, actual, leg["id"])
            )
            conn.commit()
            cur.close()
            conn.close()

            if verbose:
                actual_str = f"{actual:.1f}" if actual is not None else "N/A"
                team_str = f" ({leg['team']})" if leg.get("team") else ""
                dl = "u" if leg.get("direction") == "under" else "o"
                print(f"  {leg['player_name']}{team_str} {leg['stat']} {dl}{leg['line']}: "
                      f"got {actual_str} → {result.upper()}")

            if result == "lost":
                any_lost = True
            elif result == "void":
                void_count += 1
            elif result == "unresolvable":
                any_unresolvable = True

        # Determine parlay status:
        # - lost legs are checked first: a lost parlay is definitive regardless of
        #   unresolvable legs (e.g. a team-total leg that can never resolve)
        # - unresolvable legs hold the parlay pending only when no leg has already lost
        # - void legs are dropped (player didn't play); parlay treats them as if removed
        # - parlay wins only if all non-void legs won
        if any_lost:
            status = "lost"
        elif any_unresolvable:
            status = "pending"
        elif void_count == len(legs):
            status = "void"
        else:
            status = "won"

        # Recalculate parlay odds when legs were voided (smaller parlay = shorter odds)
        if void_count > 0 and status != "pending":
            conn = get_conn()
            cur = conn.cursor()
            cur.execute(
                "SELECT odds FROM mlb_recommendation_legs "
                "WHERE recommendation_id = %s AND result != 'void'",
                (rec_id,)
            )
            active_odds = [r["odds"] for r in cur.fetchall() if r.get("odds")]
            cur.close()
            conn.close()
            if active_odds:
                try:
                    new_odds = parlay_odds(active_odds)
                    if verbose:
                        print(f"  [Voided {void_count} leg(s)] Adjusted odds: {new_odds}")
                except Exception:
                    new_odds = None
            else:
                new_odds = None
        else:
            new_odds = None

        conn = get_conn()
        cur = conn.cursor()
        if new_odds:
            cur.execute(
                "UPDATE mlb_recommendations SET status = %s, parlay_odds = %s WHERE id = %s",
                (status, new_odds, rec_id)
            )
        else:
            cur.execute(
                "UPDATE mlb_recommendations SET status = %s WHERE id = %s",
                (status, rec_id)
            )
        conn.commit()
        cur.close()
        conn.close()

        if verbose and status != "pending":
            icon = "✓" if status == "won" else "✗"
            print(f"  [{icon}] Parlay {status.upper()}\n")


# ── Bet tracker (manual, for when you actually place a bet) ──────────────────

def log_placed_bet(recommendation_id: int, stake: float, final_odds: str, notes: str = "") -> int:
    """
    Record that you placed a real-money bet on a recommendation.
    Links back to the recommendation so calibration data is shared.
    """
    conn = get_conn()
    cur = conn.cursor()
    cur.execute(
        """
        INSERT INTO mlb_parlays (date, recommendation_id, stake, final_odds, notes, status, created_at)
        VALUES (
            (SELECT date FROM mlb_recommendations WHERE id = %s),
            %s, %s, %s, %s, 'pending', %s
        )
        RETURNING id
        """,
        (recommendation_id, recommendation_id, stake, final_odds, notes, now_utc())
    )
    bet_id = cur.fetchone()["id"]
    conn.commit()
    cur.close()
    conn.close()
    return bet_id


def resolve_placed_bets(verbose: bool = True) -> None:
    """
    Update payout status for placed bets based on already-resolved recommendation outcomes.
    Run after resolve_recommendations() has completed.
    """
    conn = get_conn()
    cur = conn.cursor()
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
        rec_status = bet["rec_status"]
        if rec_status == "won":
            from src.utils.odds_math import american_to_decimal
            dec = american_to_decimal(bet["final_odds"])
            payout = round(bet["stake"] * dec, 2)
            status = "won"
        else:
            payout = 0.0
            status = "lost"

        conn = get_conn()
        cur = conn.cursor()
        cur.execute(
            "UPDATE mlb_parlays SET status = %s, payout = %s WHERE id = %s",
            (status, payout, bet["id"])
        )
        conn.commit()
        cur.close()
        conn.close()

        if verbose:
            icon = "✓" if status == "won" else "✗"
            print(f"  [{icon}] Bet #{bet['id']} {status.upper()} — "
                  f"stake ${bet['stake']:.2f} → payout ${payout:.2f}")


# ── Scored-leg resolver (full prop pool, not just parlay legs) ────────────────

def resolve_scored_legs(verbose: bool = True) -> None:
    """
    Resolve all unresolved rows in mlb_scored_legs from box scores.

    Complements resolve_recommendations() by covering the full prop pool —
    including legs that qualified but didn't make it into any parlay.
    Clears the player game log cache once per unique player before resolving
    so box score data is always fresh.
    """
    conn = get_conn()
    cur = conn.cursor()
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
        print(f"Resolving {len(unresolved)} scored leg(s)...")

    # Clear each unique player cache once so we get fresh box scores
    seen_players: set[tuple] = set()
    for leg in unresolved:
        key = (leg["player_name"], leg["stat"])
        if key not in seen_players:
            seen_players.add(key)
            _clear_player_cache(leg["player_name"], leg["stat"])

    resolved = 0
    for leg in unresolved:
        result, actual = _resolve_leg(
            leg["player_name"], leg["stat"], leg["line"], leg["run_date"],
            leg.get("direction", "over"), leg.get("player_id")
        )
        conn = get_conn()
        cur = conn.cursor()
        cur.execute(
            "UPDATE mlb_scored_legs SET result = %s, actual_value = %s WHERE id = %s",
            (result, actual, leg["id"])
        )
        conn.commit()
        cur.close()
        conn.close()
        resolved += 1

        if verbose:
            actual_str = f"{actual:.1f}" if actual is not None else "N/A"
            team_str = f" ({leg['team']})" if leg.get("team") else ""
            flag = " [in_parlay]" if leg.get("in_parlay") else ""
            dl = "u" if leg.get("direction") == "under" else "o"
            print(f"  {leg['player_name']}{team_str} {leg['stat']} {dl}{leg['line']}: "
                  f"got {actual_str} → {result.upper()}{flag}")

    if verbose:
        print(f"\n  Resolved {resolved} scored leg(s).")


# ── Entry point ───────────────────────────────────────────────────────────────

if __name__ == "__main__":
    resolve_recommendations()
    resolve_placed_bets()
    resolve_scored_legs()
