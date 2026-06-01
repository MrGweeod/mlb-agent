"""
parlay_outcome_resolver.py — Resolve daily parlay recommendation outcomes.

Depends on mlb_scored_legs already having result populated for the target date
(run resolve_all_legs() first via outcome_resolver.py).

Logic:
  - If ALL legs = 'void' → parlay = 'void'
  - If ANY leg = 'lost'  → parlay = 'lost' (void legs ignored)
  - If remaining legs won (some may be void) → parlay = 'won' (adjusted odds)
  - If any leg still NULL → skip (not all legs resolved yet)

Run standalone:
    python -m src.tracker.parlay_outcome_resolver 2026-05-04
"""
from __future__ import annotations

import sys
from datetime import datetime, timezone

from src.utils.db import get_conn


def resolve_parlay_recommendations(date: str, verbose: bool = True) -> dict:
    """
    Resolve all pending parlay recommendations for *date*.

    Looks up each recommendation's leg results in mlb_scored_legs, determines
    the parlay outcome, and updates mlb_parlay_recommendations.bet_status and
    resolved_at.

    Args:
        date: 'YYYY-MM-DD' matching mlb_parlay_recommendations.recommendation_date
              AND mlb_scored_legs.run_date.
        verbose: Print progress to stdout.

    Returns:
        {'won': int, 'lost': int, 'void': int, 'skipped': int, 'total': int}
    """
    conn = get_conn()
    cur  = conn.cursor()
    cur.execute(
        """
        SELECT id, rank, leg_odd_ids
        FROM mlb_parlay_recommendations
        WHERE recommendation_date = %s
          AND bet_status = 'pending'
        ORDER BY rank
        """,
        (date,),
    )
    parlays = [dict(r) for r in cur.fetchall()]
    cur.close()
    conn.close()

    if not parlays:
        if verbose:
            print(f"[PARLAY RESOLVER] No pending parlays for {date}.")
        return {"won": 0, "lost": 0, "void": 0, "skipped": 0, "total": 0}

    if verbose:
        print(f"[PARLAY RESOLVER] Resolving {len(parlays)} parlay(s) for {date}...")

    # Bulk-fetch all relevant leg results in one query
    all_odd_ids = list({oid for p in parlays for oid in p["leg_odd_ids"]})
    conn = get_conn()
    cur  = conn.cursor()
    cur.execute(
        """
        SELECT odd_id, result
        FROM mlb_scored_legs
        WHERE run_date = %s
          AND odd_id = ANY(%s)
        """,
        (date, all_odd_ids),
    )
    leg_results: dict[str, str | None] = {
        row["odd_id"]: row["result"] for row in cur.fetchall()
    }
    cur.close()
    conn.close()

    counts = {"won": 0, "lost": 0, "void": 0, "skipped": 0}
    resolved_at = datetime.now(timezone.utc)

    for parlay in parlays:
        rank     = parlay["rank"]
        odd_ids  = parlay["leg_odd_ids"]
        parlay_id = parlay["id"]

        results = [leg_results.get(oid) for oid in odd_ids]

        # Skip if any leg hasn't been resolved yet
        if any(r is None for r in results):
            unresolved = sum(1 for r in results if r is None)
            if verbose:
                print(f"  Rank {rank}: {unresolved}/{len(results)} leg(s) unresolved → SKIP")
            counts["skipped"] += 1
            continue

        # Determine parlay outcome
        # void only if ALL legs void; partial voids adjust odds but parlay can still win
        void_count = sum(1 for r in results if r == "void")
        lost_count = sum(1 for r in results if r == "lost")

        if void_count == len(results):
            outcome = "void"
        elif lost_count > 0:
            outcome = "lost"
        else:
            outcome = "won"

        counts[outcome] += 1

        conn = get_conn()
        cur  = conn.cursor()
        cur.execute(
            """
            UPDATE mlb_parlay_recommendations
            SET bet_status = %s, resolved_at = %s
            WHERE id = %s
            """,
            (outcome, resolved_at, parlay_id),
        )
        conn.commit()
        cur.close()
        conn.close()

        if verbose:
            icon = "✓" if outcome == "won" else ("○" if outcome == "void" else "✗")
            leg_summary = ", ".join(str(r) for r in results)
            void_note = f" (adjusted odds, {void_count} void)" if outcome == "won" and void_count > 0 else ""
            print(f"  [{icon}] Rank {rank}: [{leg_summary}] → {outcome.upper()}{void_note}")

    total = sum(counts.values())
    if verbose:
        print(
            f"\n[PARLAY RESOLVER] Complete: "
            f"{counts['won']} won, {counts['lost']} lost, "
            f"{counts['void']} void, {counts['skipped']} skipped "
            f"({total} total)"
        )

    return {**counts, "total": total}


def resolve_parlay_recommendations_v2(date: str, verbose: bool = True) -> dict:
    """
    Resolve pending parlay recommendations in the v2 normalized schema.

    Fetches box scores for each leg's game, computes individual leg outcomes,
    then rolls up to the parlay level using the same logic as the old resolver.

    Args:
        date: 'YYYY-MM-DD' — must match mlb_parlay_recommendations_v2.run_date.
        verbose: Print progress to stdout.

    Returns:
        {'won': int, 'lost': int, 'void': int, 'skipped': int, 'total': int}
    """
    import statsapi as _statsapi
    from src.tracker.outcome_resolver import extract_stat_from_boxscore, _PITCHER_POSITIONS

    conn = get_conn()
    cur = conn.cursor()
    cur.execute(
        """
        SELECT id, rank
        FROM mlb_parlay_recommendations_v2
        WHERE run_date = %s AND outcome = 'pending'
        ORDER BY rank
        """,
        (date,),
    )
    parlays = [dict(r) for r in cur.fetchall()]
    cur.close()
    conn.close()

    if not parlays:
        if verbose:
            print(f"[PARLAY RESOLVER V2] No pending v2 parlays for {date}.")
        return {"won": 0, "lost": 0, "void": 0, "skipped": 0, "total": 0}

    if verbose:
        print(f"[PARLAY RESOLVER V2] Resolving {len(parlays)} parlay(s) for {date}...")

    # Pre-fetch all legs for today's pending parlays in one query
    parlay_ids = [p["id"] for p in parlays]
    conn = get_conn()
    cur = conn.cursor()
    cur.execute(
        """
        SELECT id, parlay_id, player_id, player_name, stat, line, direction,
               game_id, outcome
        FROM mlb_parlay_legs_v2
        WHERE parlay_id = ANY(%s)
        """,
        (parlay_ids,),
    )
    all_legs = [dict(r) for r in cur.fetchall()]
    cur.close()
    conn.close()

    # Pre-fetch box scores grouped by game_id (one API call per game)
    game_ids = list({l["game_id"] for l in all_legs if l["game_id"]})
    box_scores: dict[int, dict] = {}
    for gid in game_ids:
        try:
            bs = _statsapi.boxscore_data(gid)
            box_scores[gid] = bs
        except Exception as _e:
            if verbose:
                print(f"  [v2] box score error game {gid}: {_e}")

    resolved_at = datetime.now(timezone.utc)
    counts = {"won": 0, "lost": 0, "void": 0, "skipped": 0}

    for parlay in parlays:
        parlay_id = parlay["id"]
        rank = parlay["rank"]
        legs = [l for l in all_legs if l["parlay_id"] == parlay_id]

        leg_outcomes: list[str] = []
        all_resolved = True

        for leg in legs:
            gid = leg["game_id"]
            if not gid or gid not in box_scores:
                # Box score unavailable — leave leg pending and skip parlay resolution
                # until the game data arrives. Do NOT void: we can't distinguish
                # "game postponed" from "API not yet populated".
                if verbose:
                    print(
                        f"  [RESOLVER] game_id={gid} not in box_scores for"
                        f" {leg['player_name']} — deferring parlay {parlay_id} (leg pending)"
                    )
                all_resolved = False
                continue

            bs = box_scores[gid]
            player_id_str = str(leg["player_id"])
            player_stats = None
            position = ""

            for side in ("away", "home"):
                for pid_key, pdata in bs.get(side, {}).get("players", {}).items():
                    if pid_key == f"ID{player_id_str}" or str(pdata.get("person", {}).get("id")) == player_id_str:
                        player_stats = pdata.get("stats", {})
                        position = pdata.get("position", {}).get("abbreviation", "")
                        break
                if player_stats is not None:
                    break

            if not player_stats:  # catches both None (not found) and {} (found but empty stats)
                void_reason = "player_not_in_lineup"
                leg_outcomes.append("void")
                conn = get_conn()
                cur = conn.cursor()
                cur.execute(
                    "UPDATE mlb_parlay_legs_v2 SET outcome = 'void', void_reason = %s WHERE id = %s",
                    (void_reason, leg["id"]),
                )
                conn.commit()
                cur.execute(
                    "UPDATE mlb_scored_legs SET result = 'void', void_reason = %s"
                    " WHERE player_name = %s AND stat = %s AND run_date = %s",
                    (void_reason, leg["player_name"], leg["stat"], date),
                )
                conn.commit()
                cur.close()
                conn.close()
                continue

            # Early Exit Protection: void legs where the player barely participated
            batting  = player_stats.get("batting",  {})
            pitching = player_stats.get("pitching", {})
            if position in _PITCHER_POSITIONS:
                batters_faced = pitching.get("battersFaced")
                if batters_faced is not None and batters_faced < 5:
                    if verbose:
                        print(
                            f"  [RESOLVER] Early Exit Protection: {leg['player_name']}"
                            f" ({position}) had {batters_faced} batters_faced → void"
                        )
                    void_reason = "early_exit_protection"
                    leg_outcomes.append("void")
                    conn = get_conn()
                    cur = conn.cursor()
                    cur.execute(
                        "UPDATE mlb_parlay_legs_v2 SET outcome = 'void', void_reason = %s WHERE id = %s",
                        (void_reason, leg["id"]),
                    )
                    conn.commit()
                    cur.execute(
                        "UPDATE mlb_scored_legs SET result = 'void', void_reason = %s"
                        " WHERE player_name = %s AND stat = %s AND run_date = %s",
                        (void_reason, leg["player_name"], leg["stat"], date),
                    )
                    conn.commit()
                    cur.close()
                    conn.close()
                    continue
            else:
                plate_appearances = batting.get("plateAppearances")
                if plate_appearances is not None and plate_appearances < 2:
                    if verbose:
                        print(
                            f"  [RESOLVER] Early Exit Protection: {leg['player_name']}"
                            f" ({position}) had {plate_appearances} PA → void"
                        )
                    void_reason = "early_exit_protection"
                    leg_outcomes.append("void")
                    conn = get_conn()
                    cur = conn.cursor()
                    cur.execute(
                        "UPDATE mlb_parlay_legs_v2 SET outcome = 'void', void_reason = %s WHERE id = %s",
                        (void_reason, leg["id"]),
                    )
                    conn.commit()
                    cur.execute(
                        "UPDATE mlb_scored_legs SET result = 'void', void_reason = %s"
                        " WHERE player_name = %s AND stat = %s AND run_date = %s",
                        (void_reason, leg["player_name"], leg["stat"], date),
                    )
                    conn.commit()
                    cur.close()
                    conn.close()
                    continue

            result_value = extract_stat_from_boxscore(player_stats, leg["stat"], position)
            if result_value is None:
                void_reason = "stat_extraction_failed"
                leg_outcomes.append("void")
                conn = get_conn()
                cur = conn.cursor()
                cur.execute(
                    "UPDATE mlb_parlay_legs_v2 SET outcome = 'void', void_reason = %s WHERE id = %s",
                    (void_reason, leg["id"]),
                )
                conn.commit()
                cur.execute(
                    "UPDATE mlb_scored_legs SET result = 'void', void_reason = %s"
                    " WHERE player_name = %s AND stat = %s AND run_date = %s",
                    (void_reason, leg["player_name"], leg["stat"], date),
                )
                conn.commit()
                cur.close()
                conn.close()
                continue

            line = leg["line"]
            direction = (leg["direction"] or "over").lower()
            if direction == "over":
                outcome = "won" if result_value > line else "lost"
            else:
                outcome = "won" if result_value < line else "lost"

            leg_outcomes.append(outcome)

            # Update individual leg
            conn = get_conn()
            cur = conn.cursor()
            cur.execute(
                "UPDATE mlb_parlay_legs_v2 SET outcome = %s, result_value = %s WHERE id = %s",
                (outcome, result_value, leg["id"]),
            )
            conn.commit()
            cur.close()
            conn.close()

        if not all_resolved:
            counts["skipped"] += 1
            continue

        # Roll up to parlay outcome
        void_count = leg_outcomes.count("void")
        lost_count = leg_outcomes.count("lost")
        if void_count == len(leg_outcomes):
            parlay_outcome = "void"
        elif lost_count > 0:
            parlay_outcome = "lost"
        elif all(o in ("won", "void") for o in leg_outcomes) and any(o == "won" for o in leg_outcomes):
            parlay_outcome = "won"
        else:
            parlay_outcome = "pending"

        if parlay_outcome != "pending":
            counts[parlay_outcome] += 1
            conn = get_conn()
            cur = conn.cursor()
            cur.execute(
                """
                UPDATE mlb_parlay_recommendations_v2
                SET outcome = %s, resolved_at = %s
                WHERE id = %s
                """,
                (parlay_outcome, resolved_at.isoformat(), parlay_id),
            )
            conn.commit()
            cur.close()
            conn.close()
        else:
            counts["skipped"] += 1

        if verbose:
            icon = "✓" if parlay_outcome == "won" else ("○" if parlay_outcome == "void" else "✗")
            summary = ", ".join(leg_outcomes)
            print(f"  [{icon}] Rank {rank}: [{summary}] → {parlay_outcome.upper()}")

    total = sum(counts.values())
    if verbose:
        print(
            f"\n[PARLAY RESOLVER V2] Complete: "
            f"{counts['won']} won, {counts['lost']} lost, "
            f"{counts['void']} void, {counts['skipped']} skipped "
            f"({total} total)"
        )
    return {**counts, "total": total}


def recalculate_parlay_outcome(parlay_id: int) -> str:
    """
    Recalculate a parlay's outcome based on its legs' current outcomes.

    DraftKings rules:
    - If ALL legs are void → parlay is 'void'
    - If ANY leg is lost → parlay is 'lost' (void legs ignored)
    - If ALL non-void legs are won → parlay is 'won'
    - If ANY leg is pending → parlay is 'pending'

    Returns: 'won', 'lost', 'void', or 'pending'
    """
    conn = get_conn()
    cur = conn.cursor()
    cur.execute(
        "SELECT outcome FROM mlb_parlay_legs_v2 WHERE parlay_id = %s",
        (parlay_id,),
    )
    leg_outcomes = [row["outcome"] for row in cur.fetchall()]
    cur.close()
    conn.close()

    if not leg_outcomes:
        return "pending"

    if all(o == "void" for o in leg_outcomes):
        return "void"

    if any(o == "pending" for o in leg_outcomes):
        return "pending"

    non_void = [o for o in leg_outcomes if o != "void"]
    if any(o == "lost" for o in non_void):
        return "lost"

    if all(o == "won" for o in non_void):
        return "won"

    return "pending"


if __name__ == "__main__":
    if len(sys.argv) > 1:
        resolve_parlay_recommendations(sys.argv[1])
    else:
        from datetime import date, timedelta
        yesterday = str(date.today() - timedelta(days=1))
        resolve_parlay_recommendations(yesterday)
